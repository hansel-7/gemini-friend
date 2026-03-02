"""Cron automation handlers.

Main automation class that integrates dynamic cron job management
with Telegram commands and natural language detection.
"""

import asyncio
import re
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.base import BaseAutomation
from src.automations.cron.manager import CronJobManager, CronJob
from src.automations.cron.scheduler import CronScheduler
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.conversation import conversation_history
from src.utils.logger import logger
from config.settings import settings
from src.bot.security import authorized_only


# Keywords that indicate a recurring schedule request
SCHEDULE_PATTERNS = [
    r'\bevery\s+(day|morning|evening|night|afternoon|weekday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|hour)\b',
    r'\bdaily\b',
    r'\bweekly\b',
    r'\bmonthly\b',
    r'\bevery\s+\d+\s+(minute|hour|day)s?\b',
    r'\bevery\s+(mon|tue|wed|thu|fri|sat|sun)\b',
]

SCHEDULE_RE = re.compile('|'.join(SCHEDULE_PATTERNS), re.IGNORECASE)


# Prompt template for Gemini to extract cron schedule from natural language
SCHEDULE_EXTRACTION_PROMPT = """You are a cron schedule parser. The user wants to create a recurring scheduled job.

Extract the cron schedule and the action to perform from their message.

Respond ONLY with valid JSON in this exact format, no other text:
{{
    "schedule": "<cron expression with 5 fields: minute hour day-of-month month day-of-week>",
    "prompt": "<the action/prompt to execute on schedule>",
    "label": "<short human-readable label, max 50 chars>"
}}

Rules for cron expressions:
- "every day at 8am" → "0 8 * * *"
- "every morning" → "0 8 * * *" (default morning = 8am)
- "every evening" → "0 18 * * *" (default evening = 6pm)
- "every monday at 9am" → "0 9 * * 1"
- "every weekday at 6pm" → "0 18 * * 1-5"
- "every hour" → "0 * * * *"
- "every 30 minutes" → "*/30 * * * *"
- "daily" → "0 9 * * *" (default = 9am)
- "weekly" → "0 9 * * 1" (default = Monday 9am)

The user's message: "{message}"

Respond with JSON only:"""


class CronAutomation(BaseAutomation):
    """Dynamic cron job automation.
    
    Features:
    1. /cron command for listing, deleting, pausing, resuming jobs
    2. Natural language detection for creating recurring scheduled jobs
    3. Background scheduler that fires due jobs via Gemini CLI
    """
    
    name = "cron"
    description = "Dynamic scheduled jobs via cron expressions"
    version = "1.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        """Initialize the cron automation."""
        super().__init__(application, config)
        
        # Manager for job CRUD
        data_file = config.get('data_file', 'cron_jobs.json')
        if not Path(data_file).is_absolute():
            data_file = str(settings.DATA_DIR / data_file)
        self.manager = CronJobManager(data_file=data_file)
        
        # Scheduler for background execution
        self.scheduler = CronScheduler(
            manager=self.manager,
            check_interval=config.get('check_interval_seconds', 60),
            quiet_hours_start=config.get('quiet_hours_start', 23.5),
            quiet_hours_end=config.get('quiet_hours_end', 7),
            on_execute=self._on_execute,
            on_message=self._on_message
        )
        
        # Gemini CLI instance for executing job prompts
        self.gemini = GeminiCLI.get_instance()
        
        # Get user_id from settings
        self.user_id = next(iter(settings.ALLOWED_USER_IDS)) if settings.ALLOWED_USER_IDS else None
    
    def register_handlers(self) -> None:
        """Register /cron command handler."""
        handler = CommandHandler("cron", self._cron_command)
        self.application.add_handler(handler)
        self._handlers.append(handler)
        
        logger.info("Cron: Registered /cron command handler")
    
    async def start(self) -> None:
        """Start the cron scheduler."""
        await super().start()
        await self.scheduler.start()
        
        job_count = len(self.manager.list_jobs())
        active_count = len(self.manager.list_jobs(active_only=True))
        logger.info(f"Cron: {job_count} total jobs, {active_count} active")
    
    async def stop(self) -> None:
        """Stop the cron scheduler."""
        await self.scheduler.stop()
        await super().stop()
    
    # --- Natural Language Detection ---
    
    def is_schedule_message(self, message: str) -> bool:
        """Check if a message looks like a recurring schedule request.
        
        Args:
            message: The user's message text
            
        Returns:
            True if the message contains scheduling keywords
        """
        return bool(SCHEDULE_RE.search(message))
    
    async def create_job_from_natural_language(
        self,
        message: str,
        update: Update
    ) -> bool:
        """Create a cron job from a natural language message.
        
        Uses Gemini CLI to parse the message into a cron expression + prompt.
        
        Args:
            message: The user's natural language message
            update: Telegram update for sending confirmation
            
        Returns:
            True if a job was created successfully
        """
        try:
            # Ask Gemini to extract schedule (no MCP needed, pure text parsing)
            extraction_prompt = SCHEDULE_EXTRACTION_PROMPT.format(message=message)
            response = await self.gemini.send_message(extraction_prompt, use_mcp=False)
            
            # Parse JSON from response
            import json
            
            # Try to find JSON in the response
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if not json_match:
                logger.warning(f"Cron: Could not extract JSON from Gemini response: {response[:200]}")
                return False
            
            parsed = json.loads(json_match.group())
            
            schedule = parsed.get('schedule', '')
            prompt = parsed.get('prompt', '')
            label = parsed.get('label', '')
            
            if not schedule or not prompt:
                logger.warning(f"Cron: Missing schedule or prompt in parsed response")
                return False
            
            # Create the job
            job = self.manager.add_job(
                schedule=schedule,
                prompt=prompt,
                label=label,
                use_mcp=True
            )
            
            if not job:
                await update.message.reply_text(
                    f"❌ Invalid schedule expression: `{schedule}`",
                    parse_mode='Markdown'
                )
                return False
            
            # Send confirmation
            next_run = job.next_run()
            next_run_str = next_run.strftime("%a, %b %d at %H:%M") if next_run else "unknown"
            
            await update.message.reply_text(
                f"✅ *Scheduled job created!*\n\n"
                f"📋 *#{job.job_id}* — {job.label}\n"
                f"🔄 Schedule: {job.human_schedule()}\n"
                f"⏭️ Next run: {next_run_str}\n\n"
                f"_Manage with /cron list | /cron delete {job.job_id}_",
                parse_mode='Markdown'
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Cron: Error creating job from NL: {e}")
            return False
    
    # --- /cron Command Handler ---
    
    @authorized_only
    async def _cron_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /cron command.
        
        Usage:
            /cron list          — List all jobs
            /cron delete <id>   — Delete a job
            /cron pause <id>    — Pause a job
            /cron resume <id>   — Resume a paused job
            /cron add "<cron>" <prompt> — Add job with explicit cron expression
        """
        args = context.args if context.args else []
        
        if not args:
            await self._show_help(update)
            return
        
        subcommand = args[0].lower()
        
        if subcommand == 'list':
            await self._list_jobs(update)
        elif subcommand == 'delete' and len(args) >= 2:
            await self._delete_job(update, args[1])
        elif subcommand == 'pause' and len(args) >= 2:
            await self._pause_job(update, args[1])
        elif subcommand == 'resume' and len(args) >= 2:
            await self._resume_job(update, args[1])
        elif subcommand == 'add' and len(args) >= 3:
            await self._add_job_explicit(update, args[1:])
        else:
            await self._show_help(update)
    
    async def _show_help(self, update: Update) -> None:
        """Show cron command help."""
        await update.message.reply_text(
            "⏰ *Cron Jobs — Dynamic Scheduling*\n\n"
            "*Create jobs naturally:*\n"
            "Just send a message like:\n"
            "• \"Every morning at 8am, check the weather in HCMC\"\n"
            "• \"Every Monday, review my deal pipeline\"\n"
            "• \"Daily at 6pm, summarize my unread emails\"\n\n"
            "*Manage jobs:*\n"
            "`/cron list` — List all jobs\n"
            "`/cron delete <id>` — Delete a job\n"
            "`/cron pause <id>` — Pause a job\n"
            "`/cron resume <id>` — Resume a job\n\n"
            "*Add with explicit cron:*\n"
            "`/cron add \"0 8 * * *\" Check the weather`",
            parse_mode='Markdown'
        )
    
    async def _list_jobs(self, update: Update) -> None:
        """List all cron jobs."""
        jobs = self.manager.list_jobs()
        
        if not jobs:
            await update.message.reply_text(
                "📋 *No scheduled jobs*\n\n"
                "Create one by sending a message like:\n"
                "\"Every morning at 8am, check the weather\"",
                parse_mode='Markdown'
            )
            return
        
        lines = ["⏰ *Scheduled Jobs*\n"]
        
        for job in jobs:
            status = "▶️" if job.active else "⏸️"
            next_run = job.next_run()
            next_str = next_run.strftime("%a %b %d, %H:%M") if next_run and job.active else "paused"
            runs = f"({job.run_count} runs)" if job.run_count > 0 else ""
            
            lines.append(
                f"{status} *#{job.job_id}* — {job.label}\n"
                f"   📅 {job.human_schedule()} | Next: {next_str} {runs}"
            )
        
        lines.append(f"\n_Total: {len(jobs)} job(s)_")
        
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode='Markdown'
        )
    
    async def _delete_job(self, update: Update, job_id_str: str) -> None:
        """Delete a cron job."""
        try:
            job_id = int(job_id_str)
        except ValueError:
            await update.message.reply_text("❌ Invalid job ID. Use a number.")
            return
        
        job = self.manager.delete_job(job_id)
        if job:
            await update.message.reply_text(
                f"🗑️ Deleted job *#{job_id}*: {job.label}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Job #{job_id} not found.")
    
    async def _pause_job(self, update: Update, job_id_str: str) -> None:
        """Pause a cron job."""
        try:
            job_id = int(job_id_str)
        except ValueError:
            await update.message.reply_text("❌ Invalid job ID.")
            return
        
        job = self.manager.pause_job(job_id)
        if job:
            await update.message.reply_text(
                f"⏸️ Paused job *#{job_id}*: {job.label}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Job #{job_id} not found.")
    
    async def _resume_job(self, update: Update, job_id_str: str) -> None:
        """Resume a paused cron job."""
        try:
            job_id = int(job_id_str)
        except ValueError:
            await update.message.reply_text("❌ Invalid job ID.")
            return
        
        job = self.manager.resume_job(job_id)
        if job:
            next_run = job.next_run()
            next_str = next_run.strftime("%a %b %d, %H:%M") if next_run else "unknown"
            await update.message.reply_text(
                f"▶️ Resumed job *#{job_id}*: {job.label}\n"
                f"⏭️ Next run: {next_str}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Job #{job_id} not found.")
    
    async def _add_job_explicit(self, update: Update, args: list) -> None:
        """Add a job with explicit cron expression.
        
        Usage: /cron add "0 8 * * *" Check the weather
        """
        # First arg should be the cron expression (possibly in quotes)
        raw = ' '.join(args)
        
        # Try to find a quoted cron expression
        quoted_match = re.match(r'"([^"]+)"\s+(.*)', raw)
        if quoted_match:
            schedule = quoted_match.group(1)
            prompt = quoted_match.group(2)
        else:
            # Try first 5 space-separated tokens as cron expression
            parts = raw.split()
            if len(parts) >= 6:
                schedule = ' '.join(parts[:5])
                prompt = ' '.join(parts[5:])
            else:
                await update.message.reply_text(
                    "❌ Usage: `/cron add \"0 8 * * *\" Your prompt here`",
                    parse_mode='Markdown'
                )
                return
        
        job = self.manager.add_job(
            schedule=schedule,
            prompt=prompt,
            label=prompt[:50],
            use_mcp=True
        )
        
        if not job:
            await update.message.reply_text(
                f"❌ Invalid cron expression: `{schedule}`\n\n"
                "Format: `minute hour day-of-month month day-of-week`\n"
                "Example: `0 8 * * *` = daily at 8am",
                parse_mode='Markdown'
            )
            return
        
        next_run = job.next_run()
        next_run_str = next_run.strftime("%a, %b %d at %H:%M") if next_run else "unknown"
        
        await update.message.reply_text(
            f"✅ *Scheduled job created!*\n\n"
            f"📋 *#{job.job_id}* — {job.label}\n"
            f"🔄 Schedule: {job.human_schedule()}\n"
            f"⏭️ Next run: {next_run_str}",
            parse_mode='Markdown'
        )
    
    # --- Scheduler Callbacks ---
    
    async def _on_execute(self, job: CronJob) -> Optional[str]:
        """Execute a cron job's prompt via Gemini CLI.
        
        This is called by the scheduler when a job is due.
        """
        try:
            logger.info(f"Cron: Executing job #{job.job_id}: '{job.label}'")
            
            # Get conversation context
            context = conversation_history.get_context_for_gemini()
            
            # Prefix the prompt so Gemini knows this is a scheduled job
            full_prompt = (
                f"[This is a scheduled/cron job that fires automatically. "
                f"Job: '{job.label}'. "
                f"Please execute the following task and provide a helpful response.]\n\n"
                f"{job.prompt}"
            )
            
            response = await self.gemini.send_message(
                full_prompt,
                context=context,
                use_mcp=job.use_mcp
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Cron: Error executing job #{job.job_id}: {e}")
            return f"❌ Cron job error: {str(e)}"
    
    async def _on_message(self, job: CronJob, message: str) -> None:
        """Send a cron job's result to the user via Telegram."""
        if not self.user_id:
            logger.error("Cron: No user ID configured")
            return
        
        try:
            header = f"⏰ *Scheduled: {job.label}*\n\n"
            full_message = header + message
            
            # Handle long messages (Telegram limit ~4096 chars)
            if len(full_message) <= 4096:
                try:
                    await self.application.bot.send_message(
                        chat_id=self.user_id,
                        text=full_message,
                        parse_mode='Markdown'
                    )
                except Exception:
                    # Markdown parse failed — send as plain text
                    await self.application.bot.send_message(
                        chat_id=self.user_id,
                        text=f"⏰ Scheduled: {job.label}\n\n{message}"
                    )
            else:
                # Send header, then chunk the response
                await self.application.bot.send_message(
                    chat_id=self.user_id,
                    text=header,
                    parse_mode='Markdown'
                )
                # Send response in chunks (plain text to avoid parse errors)
                for i in range(0, len(message), 4000):
                    chunk = message[i:i+4000]
                    await self.application.bot.send_message(
                        chat_id=self.user_id,
                        text=chunk
                    )
            
            # Log to conversation history
            conversation_history.add_message(
                'ASSISTANT',
                f"[Cron #{job.job_id}: {job.label}] {message}"
            )
            
        except Exception as e:
            logger.error(f"Cron: Error sending message for job #{job.job_id}: {e}")
    
    # --- Status ---
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the cron automation."""
        status = super().get_status()
        
        jobs = self.manager.list_jobs()
        active_jobs = [j for j in jobs if j.active]
        
        status.update({
            "total_jobs": len(jobs),
            "active_jobs": len(active_jobs),
            "scheduler_running": self.scheduler.is_running,
            "jobs": [
                {
                    "id": j.job_id,
                    "label": j.label,
                    "schedule": j.human_schedule(),
                    "active": j.active,
                    "run_count": j.run_count
                }
                for j in jobs
            ]
        })
        
        return status
