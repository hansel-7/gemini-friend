"""Brain automation handlers.

Main automation class that integrates the thinking partner functionality
and weekly persona enrichment.
"""

import asyncio
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from src.automations.base import BaseAutomation
from src.automations.brain.scheduler import BrainScheduler
from src.automations.brain.thinker import BrainThinker
from src.automations.brain.persona_enricher import PersonaEnricher
from src.utils.conversation import conversation_history
from src.utils.logger import logger
from config.settings import settings


class BrainAutomation(BaseAutomation):
    """Proactive AI thinking partner automation.
    
    Features:
    1. Periodic proactive thoughts (every 2 hours)
    2. Weekly persona enrichment (Sundays at 9 PM)
    """
    
    name = "brain"
    description = "AI thinking partner with persona learning"
    version = "2.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        """Initialize the brain automation."""
        super().__init__(application, config)
        
        # Get the user ID to send messages to (ALLOWED_USER_IDS is a set)
        allowed_ids = list(settings.ALLOWED_USER_IDS)
        self.user_id = allowed_ids[0] if allowed_ids else None
        
        # Initialize thinker for proactive thoughts
        self.thinker = BrainThinker(
            conversation_file=config.get('conversation_file')
        )
        
        # Initialize proactive thinking scheduler
        self.scheduler = BrainScheduler(
            check_interval_hours=config.get('check_interval_hours', 2),
            quiet_hours_start=config.get('quiet_hours_start', 23.5),
            quiet_hours_end=config.get('quiet_hours_end', 7),
            min_gap_hours=config.get('min_gap_between_messages_hours', 2),
            on_think=self._on_think,
            on_message=self._on_message
        )
        
        # Initialize persona enricher
        self.enricher = PersonaEnricher()
        
        # Weekly persona enrichment config
        self.persona_day = config.get('persona_update_day', 6)  # 0=Mon, 6=Sun
        self.persona_hour = config.get('persona_update_hour', 21)  # 9 PM
        
        # State for pending persona updates
        self._pending_persona_update: Optional[str] = None
        self._last_persona_check_date: Optional[datetime] = None
        self._persona_task: Optional[asyncio.Task] = None
    
    def register_handlers(self) -> None:
        """Register Telegram handlers."""
        # Handler for "update" approval message
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
        
        logger.info(f"Brain automation started (persona update: day {self.persona_day}, hour {self.persona_hour})")
    
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
        logger.info("Brain automation stopped")
    
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
        
        # Already ran today?
        if self._last_persona_check_date and self._last_persona_check_date.date() == now.date():
            return
        
        # Is it the right day and hour?
        if now.weekday() != self.persona_day:
            return
        
        if now.hour < self.persona_hour:
            return
        
        # Time to run!
        logger.info("Brain: Running weekly persona enrichment...")
        self._last_persona_check_date = now
        
        learnings, suggestions = await self.enricher.analyze_for_updates()
        
        if learnings and suggestions:
            # Store for approval
            self._pending_persona_update = suggestions
            
            # Send to user for approval
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
        # Check if from authorized user
        if update.effective_user.id != self.user_id:
            return
        
        if not self._pending_persona_update:
            await update.message.reply_text(
                "No pending persona updates. Updates are suggested weekly on Sundays."
            )
            return
        
        # Apply the update
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
    
    async def _on_think(self) -> str | None:
        """Callback for scheduler - generate a thought."""
        return await self.thinker.generate_thought()
    
    async def _on_message(self, message: str) -> None:
        """Callback for scheduler - send a proactive message."""
        if not self.user_id:
            logger.error("Brain: No user ID configured, cannot send message")
            return
        
        try:
            formatted_message = f"💭 {message}"
            
            await self.application.bot.send_message(
                chat_id=self.user_id,
                text=formatted_message
            )
            
            conversation_history.add_message("ASSISTANT", f"[Proactive] {message}")
            logger.info(f"Brain: Sent proactive message to user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Brain: Error sending message: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the brain automation."""
        status = super().get_status()
        status.update({
            "scheduler_running": self.scheduler.is_running,
            "user_id": self.user_id,
            "pending_persona_update": self._pending_persona_update is not None,
            "persona_update_schedule": f"Day {self.persona_day}, Hour {self.persona_hour}"
        })
        return status
