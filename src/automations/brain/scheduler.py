"""Brain scheduler — autonomous agent version.

Replaces the fixed-interval scheduler with adaptive timing:
- Busy (has backlog) → check every 30 min
- Idle (empty backlog) → check every 4 hours
- Event-triggered → can be bumped to fire sooner
"""

from datetime import datetime
from typing import Callable, Optional, Awaitable, Tuple
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.brain.agent_state import AgentState
from src.utils.logger import logger


class AgentScheduler:
    """Adaptive scheduler for the autonomous agent.
    
    Features:
    - Adaptive cycle timing (busy vs idle)
    - Quiet hours
    - Event-driven bumping (observations trigger earlier cycles)
    """
    
    def __init__(
        self,
        state: AgentState,
        min_cycle_minutes: int = 30,
        max_cycle_minutes: int = 240,
        quiet_hours_start: float = 23.5,
        quiet_hours_end: float = 7,
        on_cycle: Optional[Callable[[], Awaitable[Optional[Tuple[Optional[str], bool]]]]] = None,
        on_message: Optional[Callable[[str], Awaitable[None]]] = None
    ):
        """Initialize the scheduler.
        
        Args:
            state: The agent's persistent state
            min_cycle_minutes: Minutes between cycles when busy
            max_cycle_minutes: Minutes between cycles when idle
            quiet_hours_start: Hour to start quiet period (decimal)
            quiet_hours_end: Hour to end quiet period
            on_cycle: Callback that runs a full triage+work cycle, returns (report, is_done)
            on_message: Callback to send a message to the user
        """
        self.state = state
        self.min_cycle_minutes = min_cycle_minutes
        self.max_cycle_minutes = max_cycle_minutes
        self.quiet_hours_start = quiet_hours_start
        self.quiet_hours_end = quiet_hours_end
        self.on_cycle = on_cycle
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
        """Start the agent scheduler."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._agent_loop())
        
        # Set initial cycle if none scheduled
        if not self.state.next_cycle_at:
            # First run: wait a bit before the first cycle
            self.state.set_next_cycle(5)  # 5 minutes after boot
        
        active = len(self.state.get_active_tasks())
        logger.info(
            f"Agent scheduler started — "
            f"Cycle range: {self.min_cycle_minutes}-{self.max_cycle_minutes}min, "
            f"Quiet hours {self.quiet_hours_start:.1f}-{self.quiet_hours_end:.1f}, "
            f"{active} active backlog items"
        )
    
    async def stop(self) -> None:
        """Stop the agent scheduler."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("Agent scheduler stopped")
    
    async def _agent_loop(self) -> None:
        """Main loop — checks every 60s if it's time for a cycle."""
        while self._running:
            try:
                # Check every 60 seconds if it's time
                await asyncio.sleep(60)
                
                if not self.state.is_cycle_due():
                    continue
                
                if self._is_quiet_hours():
                    logger.debug("Agent: Skipping cycle — quiet hours")
                    # Schedule next check for after quiet hours
                    self.state.set_next_cycle(self.max_cycle_minutes)
                    continue
                
                await self._execute_cycle()
                
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Agent loop error: {e}")
                # Don't crash the loop, wait and retry
                await asyncio.sleep(60)
    
    async def _execute_cycle(self) -> None:
        """Execute a single agent cycle (triage → work → schedule next)."""
        logger.info(f"Agent: Starting cycle #{self.state.cycle_count + 1}...")
        
        if not self.on_cycle:
            return
        
        try:
            # Run the full triage + work cycle
            result = await self.on_cycle()
            
            # Mark cycle as complete
            self.state.mark_cycle_complete()
            
            # Handle result
            report = None
            had_work = False
            
            if result:
                report, _ = result
                had_work = True
            
            # Send report to user if there's something to share
            if report and self.on_message:
                await self.on_message(report)
                logger.info(f"Agent: Sent report to user ({len(report)} chars)")
            
            # Adaptive scheduling: busy → short wait, idle → long wait
            if had_work or self.state.get_active_tasks():
                next_minutes = self.min_cycle_minutes
                logger.info(f"Agent: Has work — next cycle in {next_minutes}min")
            else:
                next_minutes = self.max_cycle_minutes
                logger.info(f"Agent: Idle — next cycle in {next_minutes}min")
            
            self.state.set_next_cycle(next_minutes)
            
            # Clear processed observations
            self.state.clear_observations()
            
        except Exception as e:
            logger.error(f"Agent cycle error: {e}")
            # On error, schedule a retry in a moderate time
            self.state.set_next_cycle(self.min_cycle_minutes * 2)
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
