"""Brain scheduler for proactive thinking.

Handles periodic thinking cycles with quiet hours and rate limiting.
"""

from datetime import datetime, timedelta
from typing import Callable, Optional, Awaitable
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger


class BrainScheduler:
    """Scheduler for proactive thinking cycles.
    
    Features:
    - Configurable check interval
    - Quiet hours (no messages during sleep time)
    - Rate limiting (minimum gap between messages)
    """
    
    def __init__(
        self,
        check_interval_hours: float = 2,
        quiet_hours_start: float = 23.5,  # 11:30 PM
        quiet_hours_end: float = 7,       # 7:00 AM
        min_gap_hours: float = 2,
        on_think: Optional[Callable[[], Awaitable[Optional[str]]]] = None,
        on_message: Optional[Callable[[str], Awaitable[None]]] = None
    ):
        """Initialize the scheduler.
        
        Args:
            check_interval_hours: Hours between thinking cycles
            quiet_hours_start: Hour to start quiet period (decimal, e.g. 23.5 = 11:30 PM)
            quiet_hours_end: Hour to end quiet period
            min_gap_hours: Minimum hours between proactive messages
            on_think: Callback that generates a thought (returns message or None)
            on_message: Callback to send the message
        """
        self.check_interval_seconds = int(check_interval_hours * 3600)
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.min_gap_seconds = int(min_gap_hours * 3600)
        self.on_think = on_think
        self.on_message = on_message
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_message_time: Optional[datetime] = None
    
    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        now = datetime.now()
        current_hour = now.hour + now.minute / 60
        
        # Handle overnight quiet hours (e.g., 23.5 to 7)
        if self.quiet_hours_start > self.quiet_hours_end:
            # Quiet if after start OR before end
            return current_hour >= self.quiet_hours_start or current_hour < self.quiet_hours_end
        else:
            # Normal range
            return self.quiet_hours_start <= current_hour < self.quiet_hours_end
    
    def _can_send_message(self) -> bool:
        """Check if enough time has passed since last message."""
        if self._last_message_time is None:
            return True
        
        elapsed = (datetime.now() - self._last_message_time).total_seconds()
        return elapsed >= self.min_gap_seconds
    
    async def start(self) -> None:
        """Start the thinking scheduler."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._think_loop())
        logger.info(
            f"Brain scheduler started - "
            f"Check every {self.check_interval_seconds/3600:.1f}h, "
            f"Quiet hours {self.quiet_hours_start:.1f}-{self.quiet_hours_end:.1f}, "
            f"Min gap {self.min_gap_seconds/3600:.1f}h"
        )
    
    async def stop(self) -> None:
        """Stop the thinking scheduler."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("Brain scheduler stopped")
    
    async def _think_loop(self) -> None:
        """Main loop for periodic thinking."""
        while self._running:
            try:
                await self._execute_think_cycle()
            except Exception as e:
                logger.error(f"Error in brain think loop: {e}")
            
            await asyncio.sleep(self.check_interval_seconds)
    
    async def _execute_think_cycle(self) -> None:
        """Execute a single thinking cycle."""
        # Check quiet hours
        if self._is_quiet_hours():
            logger.debug("Brain: Skipping - quiet hours")
            return
        
        # Check rate limiting
        if not self._can_send_message():
            logger.debug("Brain: Skipping - rate limited")
            return
        
        # No callbacks configured
        if not self.on_think or not self.on_message:
            return
        
        # Generate a thought
        logger.info("Brain: Starting thinking cycle...")
        thought = await self.on_think()
        
        if thought:
            logger.info("Brain: Generated proactive thought, sending...")
            await self.on_message(thought)
            self._last_message_time = datetime.now()
        else:
            logger.info("Brain: No thought to share this cycle")
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
