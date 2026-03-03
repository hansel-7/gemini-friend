"""Cron scheduler — background loop that fires due jobs.

Checks every 60 seconds for jobs that need to run and sends their
prompts to Gemini CLI, relaying responses to Telegram.
"""

import asyncio
from datetime import datetime
from typing import Callable, Optional, Awaitable
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.cron.manager import CronJobManager, CronJob
from src.utils.logger import logger


class CronScheduler:
    """Background scheduler that checks and fires cron jobs.
    
    Features:
    - Checks every check_interval seconds for due jobs
    - Respects quiet hours
    - Sends prompts to Gemini CLI with MCP tool access
    - Relays responses to Telegram
    """
    
    def __init__(
        self,
        manager: CronJobManager,
        check_interval: int = 60,
        quiet_hours_start: float = 23.5,
        quiet_hours_end: float = 7,
        on_execute: Optional[Callable[[CronJob], Awaitable[Optional[str]]]] = None,
        on_message: Optional[Callable[[CronJob, str], Awaitable[None]]] = None
    ):
        """Initialize the cron scheduler.
        
        Args:
            manager: CronJobManager instance for job CRUD
            check_interval: Seconds between checks (default 60)
            quiet_hours_start: Start of quiet period (decimal hour)
            quiet_hours_end: End of quiet period (decimal hour)
            on_execute: Callback to execute a job's prompt via Gemini CLI.
                        Receives the CronJob, returns the Gemini response or None.
            on_message: Callback to send the result to the user via Telegram.
                        Receives the CronJob and the response text.
        """
        self.manager = manager
        self.check_interval = check_interval
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.on_execute = on_execute
        self.on_message = on_message
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        now = datetime.now()
        current_hour = now.hour + now.minute / 60
        
        if self.quiet_hours_start > self.quiet_hours_end:
            return current_hour >= self.quiet_hours_start or current_hour < self.quiet_hours_end
        else:
            return self.quiet_hours_start <= current_hour < self.quiet_hours_end
    
    async def start(self) -> None:
        """Start the cron scheduler loop."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            f"Cron scheduler started — "
            f"checking every {self.check_interval}s, "
            f"quiet hours {self.quiet_hours_start:.1f}-{self.quiet_hours_end:.1f}"
        )
    
    async def stop(self) -> None:
        """Stop the cron scheduler loop."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("Cron scheduler stopped")
    
    async def _scheduler_loop(self) -> None:
        """Main loop — check for due jobs every interval."""
        # Small initial delay to let bot fully start
        await asyncio.sleep(10)
        
        while self._running:
            try:
                await self._check_and_fire()
            except Exception as e:
                logger.error(f"Cron: Error in scheduler loop: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    async def _check_and_fire(self) -> None:
        """Check for due jobs and fire them."""
        if self._is_quiet_hours():
            return
        
        due_jobs = self.manager.get_due_jobs()
        
        if not due_jobs:
            return
        
        logger.info(f"Cron: {len(due_jobs)} job(s) due to fire")
        
        for job in due_jobs:
            try:
                await self._fire_job(job)
            except Exception as e:
                logger.error(f"Cron: Error firing job #{job.job_id} '{job.label}': {e}")
    
    async def _fire_job(self, job: CronJob) -> None:
        """Execute a single cron job."""
        logger.info(f"Cron: Firing job #{job.job_id}: '{job.label}'")
        
        # Mark as run immediately to prevent double-firing
        self.manager.mark_job_run(job.job_id)
        
        if not self.on_execute or not self.on_message:
            logger.warning("Cron: No execute/message callbacks configured")
            return
        
        # Execute the prompt via Gemini CLI
        response = await self.on_execute(job)
        
        if response:
            try:
                await self.on_message(job, response)
                logger.info(f"Cron: Job #{job.job_id} completed and sent to user")
            except Exception as e:
                logger.error(f"Cron: Job #{job.job_id} executed but failed to deliver: {e}")
        else:
            logger.warning(f"Cron: Job #{job.job_id} returned no response")
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
