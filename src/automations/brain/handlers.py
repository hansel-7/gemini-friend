"""Brain automation handlers — autonomous agent version.

Replaces the stateless "think every 2 hours" brain with a goal-driven agent
that maintains a persistent task queue, works across cycles, and reacts to events.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from src.automations.base import BaseAutomation
from src.automations.brain.agent_state import AgentState
from src.automations.brain.learnings import AgentLearnings
from src.automations.brain.scheduler import AgentScheduler
from src.automations.brain.thinker import AgentThinker
from src.automations.brain.persona_enricher import PersonaEnricher
from src.utils.conversation import conversation_history
from src.utils.logger import logger
from config.settings import settings


class BrainAutomation(BaseAutomation):
    """Autonomous AI agent automation.
    
    Features:
    1. Persistent backlog with adaptive scheduling
    2. Two-phase thinking: triage → work
    3. Event-driven triggers from user messages
    4. Task list awareness (reads from TaskManager)
    5. Weekly persona enrichment (unchanged)
    """
    
    name = "brain"
    description = "Autonomous AI agent with persistent backlog"
    version = "3.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        """Initialize the brain automation."""
        super().__init__(application, config)
        
        # Get the user ID to send messages to
        allowed_ids = list(settings.ALLOWED_USER_IDS)
        self.user_id = allowed_ids[0] if allowed_ids else None
        
        # Initialize agent state (persistent)
        state_file = config.get('state_file', 'agent_state.json')
        if not Path(state_file).is_absolute():
            state_file = str(settings.DATA_DIR / state_file)
        self.state = AgentState(state_file=state_file)
        
        # Initialize learnings store (persistent)
        learnings_file = config.get('learnings_file', 'agent_learnings.json')
        if not Path(learnings_file).is_absolute():
            learnings_file = str(settings.DATA_DIR / learnings_file)
        self.learnings = AgentLearnings(learnings_file=learnings_file)
        
        # Initialize thinker
        self.thinker = AgentThinker(
            state=self.state,
            learnings=self.learnings,
            conversation_file=config.get('conversation_file')
        )
        
        # Initialize scheduler
        self.scheduler = AgentScheduler(
            state=self.state,
            min_cycle_minutes=config.get('min_cycle_minutes', 30),
            max_cycle_minutes=config.get('max_cycle_minutes', 240),
            quiet_hours_start=config.get('quiet_hours_start', 23.5),
            quiet_hours_end=config.get('quiet_hours_end', 7),
            on_cycle=self._on_cycle,
            on_message=self._on_message
        )
        
        # Task manager reference (set externally via set_task_manager)
        self._task_manager = None
        
        # Initialize persona enricher (kept from v2)
        self.enricher = PersonaEnricher()
        
        # Weekly persona enrichment config
        self.persona_day = config.get('persona_update_day', 6)  # 0=Mon, 6=Sun
        self.persona_hour = config.get('persona_update_hour', 21)  # 9 PM
        
        # State for pending persona updates
        self._pending_persona_update: Optional[str] = None
        self._last_persona_check_date: Optional[datetime] = None
        self._persona_task: Optional[asyncio.Task] = None
    
    def set_task_manager(self, task_manager) -> None:
        """Set the TaskManager instance for task list awareness.
        
        Called by main.py after loading all automations.
        """
        self._task_manager = task_manager
        if task_manager:
            logger.info("Agent: Task list awareness enabled")
    
    def register_handlers(self) -> None:
        """Register Telegram handlers."""
        # Handler for "update" approval message (persona)
        update_handler = MessageHandler(
            filters.TEXT & filters.Regex(r'^update$'),
            self._handle_update_approval
        )
        self.application.add_handler(update_handler)
        self._handlers.append(update_handler)
        logger.info("Brain: Registered persona update approval handler")
    
    async def start(self) -> None:
        """Start the brain automation."""
        await super().start()
        await self.scheduler.start()
        
        # Start weekly persona check loop
        self._persona_task = asyncio.create_task(self._persona_loop())
        
        active = len(self.state.get_active_tasks())
        logger.info(
            f"Brain agent v3 started — "
            f"{active} backlog items, "
            f"cycle #{self.state.cycle_count}, "
            f"persona update: day {self.persona_day} hour {self.persona_hour}"
        )
    
    async def stop(self) -> None:
        """Stop the brain automation."""
        await self.scheduler.stop()
        
        if self._persona_task:
            self._persona_task.cancel()
            try:
                await self._persona_task
            except asyncio.CancelledError:
                pass
        
        await super().stop()
        logger.info("Brain agent stopped")
    
    # --- Event Triggers ---
    
    async def on_user_message(self, message: str) -> None:
        """Called when the user sends a message.
        
        Saves the message as an observation and bumps the next cycle
        if the message is substantive enough.
        """
        # Skip trivial messages
        if len(message.strip()) < 30:
            return
        
        # Save as observation (no API call)
        self.state.add_observation(f"User said: {message[:200]}")
        
        # Bump next cycle to fire sooner
        self.state.bump_next_cycle(minutes_from_now=5)
    
    def on_news_digest(self, summary: str) -> None:
        """Called when a news digest is sent.
        
        Saves key points as observations.
        """
        # Just save the first 300 chars as an observation
        if summary:
            self.state.add_observation(f"News digest: {summary[:300]}")
    
    # --- Core Agent Cycle ---
    
    async def _on_cycle(self) -> Optional[Tuple[Optional[str], bool]]:
        """Run a full triage → work cycle.
        
        Returns:
            Tuple of (report_message, is_task_done), or None if nothing to do
        """
        # Get user's pending tasks for context
        user_tasks_context = self._get_user_tasks_context()
        
        # Phase 1: Triage — decide what to work on
        task_id = await self.thinker.run_triage(user_tasks_context)
        
        if not task_id:
            logger.info("Agent: Triage decided nothing to do")
            return None
        
        # Phase 2: Work — execute one step
        report, is_done = await self.thinker.run_work(task_id)
        
        # Check if learnings need consolidation
        if self.learnings.needs_consolidation():
            logger.info("Agent: Triggering learnings consolidation...")
            await self.learnings.consolidate(self.thinker.gemini)
        
        return (report, is_done)
    
    def _get_user_tasks_context(self) -> str:
        """Build a context string from the user's pending TaskManager tasks."""
        if not self._task_manager:
            return ""
        
        try:
            pending = self._task_manager.get_pending_tasks()
            if not pending:
                return "(no pending tasks)"
            
            lines = []
            for task in pending:
                due_str = task.due_at.strftime("%Y-%m-%d %H:%M") if task.due_at else "no deadline"
                age_days = (datetime.now() - task.created_at).days
                stale = " ⚠️ STALE" if age_days > 7 else ""
                lines.append(f"- #{task.id}: {task.description} (due: {due_str}){stale}")
            
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Agent: Error reading user tasks: {e}")
            return ""
    
    # --- Message Delivery ---
    
    async def _on_message(self, message: str) -> None:
        """Send an agent report to the user via Telegram."""
        if not self.user_id:
            logger.error("Agent: No user ID configured")
            return
        
        try:
            formatted = f"🤖 {message}"
            
            if len(formatted) <= 4096:
                try:
                    await self.application.bot.send_message(
                        chat_id=self.user_id,
                        text=formatted,
                        parse_mode='Markdown'
                    )
                except Exception:
                    # Markdown failed, send plain
                    await self.application.bot.send_message(
                        chat_id=self.user_id,
                        text=formatted
                    )
            else:
                # Chunk long messages
                for i in range(0, len(message), 4000):
                    chunk = message[i:i+4000]
                    prefix = "🤖 " if i == 0 else ""
                    await self.application.bot.send_message(
                        chat_id=self.user_id,
                        text=prefix + chunk
                    )
            
            conversation_history.add_message("ASSISTANT", f"[Agent] {message}")
            logger.info(f"Agent: Sent report to user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Agent: Error sending message: {e}")
    
    # --- Persona Enrichment (unchanged from v2) ---
    
    async def _persona_loop(self) -> None:
        """Background loop for weekly persona enrichment."""
        while self._running:
            try:
                await self._check_persona_update()
            except Exception as e:
                logger.error(f"Brain: Error in persona loop: {e}")
            
            # Check every hour
            await asyncio.sleep(3600)
    
    async def _check_persona_update(self) -> None:
        """Check if it's time for weekly persona update."""
        now = datetime.now()
        
        if self._last_persona_check_date and self._last_persona_check_date.date() == now.date():
            return
        
        if now.weekday() != self.persona_day:
            return
        
        if now.hour < self.persona_hour:
            return
        
        logger.info("Brain: Running weekly persona enrichment...")
        self._last_persona_check_date = now
        
        learnings, suggestions = await self.enricher.analyze_for_updates()
        
        if learnings and suggestions:
            self._pending_persona_update = suggestions
            await self._send_persona_proposal(learnings, suggestions)
        else:
            logger.info("Brain: No persona updates to suggest this week")
    
    async def _send_persona_proposal(self, learnings: str, suggestions: str) -> None:
        """Send persona update proposal to user."""
        if not self.user_id:
            return
        
        message = (
            "🧠 *Weekly Persona Update*\n\n"
            "I noticed these new things about you this week:\n"
            f"{learnings}\n\n"
            "Reply with `update` to add these to your persona, or ignore to skip."
        )
        
        try:
            await self.application.bot.send_message(
                chat_id=self.user_id,
                text=message,
                parse_mode='Markdown'
            )
            logger.info("Brain: Sent persona update proposal")
        except Exception as e:
            logger.error(f"Brain: Error sending persona proposal: {e}")
    
    async def _handle_update_approval(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle user's 'update' approval for persona changes."""
        if update.effective_user.id != self.user_id:
            return
        
        if not self._pending_persona_update:
            await update.message.reply_text(
                "No pending persona updates. Updates are suggested weekly on Sundays."
            )
            return
        
        if self.enricher.apply_update(self._pending_persona_update):
            await update.message.reply_text(
                "✅ *Persona Updated!*\n\n"
                "Your `persona.txt` has been enriched with the new learnings.\n"
                "Use `/persona` to reload if needed.",
                parse_mode='Markdown'
            )
            self._pending_persona_update = None
        else:
            await update.message.reply_text(
                "❌ Failed to update persona. Check logs for details."
            )
    
    # --- Status ---
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the brain automation."""
        status = super().get_status()
        
        active_tasks = self.state.get_active_tasks()
        
        status.update({
            "version": "3.0.0 (autonomous agent)",
            "scheduler_running": self.scheduler.is_running,
            "user_id": self.user_id,
            "cycle_count": self.state.cycle_count,
            "backlog_items": len(active_tasks),
            "observations": len(self.state.observations),
            "learnings_count": self.learnings.get_lesson_count(),
            "next_cycle": self.state.next_cycle_at.isoformat() if self.state.next_cycle_at else None,
            "pending_persona_update": self._pending_persona_update is not None,
            "persona_update_schedule": f"Day {self.persona_day}, Hour {self.persona_hour}"
        })
        return status
