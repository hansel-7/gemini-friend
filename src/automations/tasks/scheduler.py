"""Task reminder scheduler.

Handles periodic checking and sending of task reminders.

Reminder Strategy:
1. Daily digest at configured time (default 7 AM) - lists all pending tasks
2. Individual reminder 1 hour before each task's deadline
"""

import json
from datetime import datetime, timedelta, time
from typing import Callable, Optional, Awaitable, List
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger
from src.automations.tasks.manager import TaskManager, Task

# File to persist scheduler state
SCHEDULER_STATE_FILE = Path(__file__).parent / "scheduler_state.json"


class TaskScheduler:
    """Scheduler for task reminders.
    
    Implements two types of reminders:
    1. Daily digest at a configured time (e.g., 7 AM)
    2. Individual reminders 1 hour before task deadlines
    """
    
    def __init__(
        self,
        task_manager: TaskManager,
        check_interval: int = 60,
        daily_digest_hour: int = 7,
        daily_digest_minute: int = 0,
        hours_before_deadline: int = 1,
        on_daily_digest: Optional[Callable[[List[Task]], Awaitable[None]]] = None,
        on_deadline_reminder: Optional[Callable[[Task], Awaitable[None]]] = None
    ):
        """Initialize the scheduler.
        
        Args:
            task_manager: TaskManager instance
            check_interval: Seconds between reminder checks
            daily_digest_hour: Hour for daily digest (0-23, default 7 AM)
            daily_digest_minute: Minute for daily digest (0-59, default 0)
            hours_before_deadline: Hours before deadline to send reminder
            on_daily_digest: Callback for daily digest (receives list of pending tasks)
            on_deadline_reminder: Callback for deadline reminder (receives single task)
        """
        self.task_manager = task_manager
        self.check_interval = check_interval
        self.daily_digest_hour = daily_digest_hour
        self.daily_digest_minute = daily_digest_minute
        self.hours_before_deadline = hours_before_deadline
        self.on_daily_digest = on_daily_digest
        self.on_deadline_reminder = on_deadline_reminder
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_daily_digest_date: Optional[datetime] = self._load_last_digest_date()
    
    async def start(self) -> None:
        """Start the reminder scheduler."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._reminder_loop())
        logger.info(
            f"Task scheduler started - "
            f"Daily digest at {self.daily_digest_hour:02d}:{self.daily_digest_minute:02d}, "
            f"Deadline reminders {self.hours_before_deadline}h before"
        )
    
    async def stop(self) -> None:
        """Stop the reminder scheduler."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("Task scheduler stopped")
    
    async def _reminder_loop(self) -> None:
        """Main loop that checks for reminders."""
        while self._running:
            try:
                await self._check_daily_digest()
                await self._check_deadline_reminders()
            except Exception as e:
                logger.error(f"Error in reminder loop: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    async def _check_daily_digest(self) -> None:
        """Check if it's time for the daily digest."""
        if not self.on_daily_digest:
            return
        
        now = datetime.now()
        
        # Already sent today?
        if self._last_daily_digest_date and self._last_daily_digest_date.date() == now.date():
            return
        
        # Build target time for today
        target_datetime = now.replace(
            hour=self.daily_digest_hour,
            minute=self.daily_digest_minute,
            second=0,
            microsecond=0
        )
        
        # Only send if we're within a 10-minute window AFTER the target time
        # This prevents blasting if bot restarts hours after the target time
        time_since_target = (now - target_datetime).total_seconds()
        grace_period_seconds = 10 * 60  # 10 minutes
        
        if time_since_target < 0:
            # Before target time, not yet
            return
        
        if time_since_target > grace_period_seconds:
            # Past the grace window, skip for today (mark as sent)
            logger.debug(f"Daily digest time passed ({time_since_target/60:.0f}m ago), skipping until tomorrow")
            self._last_daily_digest_date = now
            self._save_last_digest_date(now)
            return
        
        # Within the window, send the digest
        pending_tasks = self.task_manager.get_pending_tasks()
        
        if pending_tasks:
            try:
                await self.on_daily_digest(pending_tasks)
                self._last_daily_digest_date = now
                self._save_last_digest_date(now)
                logger.info(f"Sent daily digest with {len(pending_tasks)} tasks")
            except Exception as e:
                logger.error(f"Error sending daily digest: {e}")
        else:
            # No tasks, but mark as sent so we don't keep checking
            self._last_daily_digest_date = now
            self._save_last_digest_date(now)
    
    async def _check_deadline_reminders(self) -> None:
        """Check for tasks approaching their deadline."""
        if not self.on_deadline_reminder:
            return
        
        now = datetime.now()
        reminder_threshold = now + timedelta(hours=self.hours_before_deadline)
        
        # Get all pending tasks
        pending_tasks = self.task_manager.get_pending_tasks()
        
        for task in pending_tasks:
            # Skip tasks without due dates
            if not task.due_at:
                continue
            
            # Check if deadline is within threshold and reminder not sent
            if task.due_at <= reminder_threshold and not task.deadline_reminder_sent:
                # Don't remind if deadline already passed
                if task.due_at < now:
                    continue
                
                try:
                    await self.on_deadline_reminder(task)
                    self.task_manager.mark_deadline_reminded(task.id)
                    logger.info(f"Sent deadline reminder for task #{task.id}")
                except Exception as e:
                    logger.error(f"Error sending deadline reminder for task #{task.id}: {e}")
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
    
    def _load_last_digest_date(self) -> Optional[datetime]:
        """Load the last digest date from persistent storage."""
        try:
            if SCHEDULER_STATE_FILE.exists():
                with open(SCHEDULER_STATE_FILE, 'r') as f:
                    state = json.load(f)
                    if 'last_daily_digest_date' in state and state['last_daily_digest_date']:
                        loaded_date = datetime.fromisoformat(state['last_daily_digest_date'])
                        logger.info(f"Loaded last digest date: {loaded_date}")
                        return loaded_date
        except Exception as e:
            logger.warning(f"Could not load scheduler state: {e}")
        return None
    
    def _save_last_digest_date(self, dt: datetime) -> None:
        """Save the last digest date to persistent storage."""
        try:
            state = {}
            if SCHEDULER_STATE_FILE.exists():
                with open(SCHEDULER_STATE_FILE, 'r') as f:
                    state = json.load(f)
            
            state['last_daily_digest_date'] = dt.isoformat()
            
            with open(SCHEDULER_STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
            
            logger.debug(f"Saved last digest date: {dt}")
        except Exception as e:
            logger.error(f"Could not save scheduler state: {e}")
