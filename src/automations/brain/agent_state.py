"""Agent state manager — persistent state for the autonomous brain agent.

Stores backlog, observations, and adaptive scheduling state in a JSON file.
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import threading

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger
from config.settings import settings


class AgentTask:
    """A single item in the agent's backlog."""
    
    def __init__(
        self,
        task: str,
        priority: str = "medium",
        source: str = "self",
        status: str = "queued",
        task_id: str = "",
        created_at: str = "",
        notes: List[str] = None,
        progress: int = 0
    ):
        self.id = task_id or uuid.uuid4().hex[:8]
        self.task = task
        self.priority = priority  # high, medium, low
        self.source = source      # conversation, news, self, user_task
        self.status = status       # queued, in_progress, done
        self.created_at = created_at or datetime.now().isoformat()
        self.notes = notes or []
        self.progress = progress   # number of cycles spent on this
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "priority": self.priority,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "notes": self.notes,
            "progress": self.progress
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTask":
        return cls(
            task_id=data.get("id", ""),
            task=data.get("task", ""),
            priority=data.get("priority", "medium"),
            source=data.get("source", "self"),
            status=data.get("status", "queued"),
            created_at=data.get("created_at", ""),
            notes=data.get("notes", []),
            progress=data.get("progress", 0)
        )


class AgentState:
    """Persistent state for the autonomous agent.
    
    Manages a backlog of tasks, observations, and adaptive scheduling.
    All state is persisted to a JSON file in DATA_DIR.
    """
    
    MAX_BACKLOG = 20
    MAX_OBSERVATIONS = 50
    
    def __init__(self, state_file: str = None):
        if state_file is None:
            state_file = str(settings.DATA_DIR / "agent_state.json")
        
        self.state_file = Path(state_file)
        self._lock = threading.Lock()
        
        # In-memory state
        self.backlog: List[AgentTask] = []
        self.observations: List[Dict[str, str]] = []
        self.next_cycle_at: Optional[datetime] = None
        self.last_cycle_at: Optional[datetime] = None
        self.cycle_count: int = 0
        
        self._load()
    
    # --- Persistence ---
    
    def _load(self) -> None:
        """Load state from disk."""
        if not self.state_file.exists():
            logger.info("Agent: No state file found, starting fresh")
            self._save()
            return
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.backlog = [
                AgentTask.from_dict(t) for t in data.get("backlog", [])
            ]
            self.observations = data.get("observations", [])
            
            next_cycle = data.get("next_cycle_at")
            self.next_cycle_at = datetime.fromisoformat(next_cycle) if next_cycle else None
            
            last_cycle = data.get("last_cycle_at")
            self.last_cycle_at = datetime.fromisoformat(last_cycle) if last_cycle else None
            
            self.cycle_count = data.get("cycle_count", 0)
            
            logger.info(
                f"Agent: Loaded state — {len(self.backlog)} backlog items, "
                f"{len(self.observations)} observations, {self.cycle_count} cycles"
            )
        except Exception as e:
            logger.error(f"Agent: Failed to load state: {e}")
    
    def _save(self) -> None:
        """Save state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "backlog": [t.to_dict() for t in self.backlog],
                "observations": self.observations,
                "next_cycle_at": self.next_cycle_at.isoformat() if self.next_cycle_at else None,
                "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
                "cycle_count": self.cycle_count,
                "last_saved": datetime.now().isoformat()
            }
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Agent: Failed to save state: {e}")
    
    # --- Backlog Management ---
    
    def add_task(
        self,
        task: str,
        priority: str = "medium",
        source: str = "self"
    ) -> AgentTask:
        """Add a task to the agent's backlog."""
        with self._lock:
            # Check for duplicates (fuzzy — same first 50 chars)
            task_prefix = task[:50].lower()
            for existing in self.backlog:
                if existing.task[:50].lower() == task_prefix and existing.status != "done":
                    logger.debug(f"Agent: Skipping duplicate task: {task[:50]}")
                    return existing
            
            new_task = AgentTask(task=task, priority=priority, source=source)
            self.backlog.append(new_task)
            
            # Trim if over max
            active = [t for t in self.backlog if t.status != "done"]
            done = [t for t in self.backlog if t.status == "done"]
            if len(active) > self.MAX_BACKLOG:
                # Remove oldest low-priority items
                active.sort(key=lambda t: (
                    {"high": 0, "medium": 1, "low": 2}.get(t.priority, 1),
                    t.created_at
                ))
                active = active[:self.MAX_BACKLOG]
            
            self.backlog = active + done[-10:]  # Keep last 10 done for context
            
            self._save()
            logger.info(f"Agent: Added task '{task[:50]}' (priority={priority}, source={source})")
            return new_task
    
    def get_next_task(self) -> Optional[AgentTask]:
        """Get the highest-priority queued or in-progress task."""
        with self._lock:
            # Prefer in-progress tasks (continue what we started)
            in_progress = [t for t in self.backlog if t.status == "in_progress"]
            if in_progress:
                return in_progress[0]
            
            # Then highest priority queued
            queued = [t for t in self.backlog if t.status == "queued"]
            if not queued:
                return None
            
            priority_order = {"high": 0, "medium": 1, "low": 2}
            queued.sort(key=lambda t: priority_order.get(t.priority, 1))
            return queued[0]
    
    def update_task(self, task_id: str, note: str = "", status: str = "") -> bool:
        """Update a task's notes and/or status."""
        with self._lock:
            for task in self.backlog:
                if task.id == task_id:
                    if note:
                        task.notes.append(note)
                    if status:
                        task.status = status
                    task.progress += 1
                    self._save()
                    return True
            return False
    
    def complete_task(self, task_id: str) -> bool:
        """Mark a task as done."""
        return self.update_task(task_id, status="done")
    
    def get_active_tasks(self) -> List[AgentTask]:
        """Get all queued and in-progress tasks."""
        return [t for t in self.backlog if t.status in ("queued", "in_progress")]
    
    # --- Observations ---
    
    def add_observation(self, text: str) -> None:
        """Add an observation (lightweight, no API call)."""
        with self._lock:
            self.observations.append({
                "text": text,
                "timestamp": datetime.now().isoformat()
            })
            
            # Trim old observations
            if len(self.observations) > self.MAX_OBSERVATIONS:
                self.observations = self.observations[-self.MAX_OBSERVATIONS:]
            
            self._save()
    
    def get_recent_observations(self, count: int = 20) -> List[Dict[str, str]]:
        """Get the most recent observations."""
        return self.observations[-count:]
    
    def clear_observations(self) -> None:
        """Clear all observations (called after triage processes them)."""
        with self._lock:
            self.observations = []
            self._save()
    
    # --- Adaptive Scheduling ---
    
    def set_next_cycle(self, minutes_from_now: int) -> None:
        """Set when the next agent cycle should fire."""
        with self._lock:
            self.next_cycle_at = datetime.now() + timedelta(minutes=minutes_from_now)
            self._save()
            logger.debug(f"Agent: Next cycle at {self.next_cycle_at.strftime('%H:%M')}")
    
    def bump_next_cycle(self, minutes_from_now: int = 5) -> None:
        """Bump the next cycle to fire sooner (e.g., on new observation).
        
        Only bumps if the new time is sooner than the current schedule.
        """
        with self._lock:
            new_time = datetime.now() + timedelta(minutes=minutes_from_now)
            if self.next_cycle_at is None or new_time < self.next_cycle_at:
                self.next_cycle_at = new_time
                self._save()
                logger.info(f"Agent: Bumped next cycle to {self.next_cycle_at.strftime('%H:%M')}")
    
    def is_cycle_due(self) -> bool:
        """Check if it's time for a cycle."""
        if self.next_cycle_at is None:
            return True
        return datetime.now() >= self.next_cycle_at
    
    def mark_cycle_complete(self) -> None:
        """Record that a cycle just ran."""
        with self._lock:
            self.last_cycle_at = datetime.now()
            self.cycle_count += 1
            self._save()
    
    def seconds_until_next_cycle(self) -> float:
        """Get seconds until next scheduled cycle."""
        if self.next_cycle_at is None:
            return 0
        delta = (self.next_cycle_at - datetime.now()).total_seconds()
        return max(0, delta)
    
    # --- Context for Prompts ---
    
    def get_state_summary(self) -> str:
        """Get a formatted summary of agent state for inclusion in prompts."""
        lines = []
        
        # Active backlog
        active = self.get_active_tasks()
        if active:
            lines.append("=== YOUR AGENT BACKLOG ===")
            for t in active:
                status_icon = "🔄" if t.status == "in_progress" else "📋"
                notes_str = f" | Notes: {'; '.join(t.notes[-3:])}" if t.notes else ""
                lines.append(
                    f"{status_icon} ID={t.id} [{t.priority.upper()}] {t.task}{notes_str}"
                )
        else:
            lines.append("=== YOUR AGENT BACKLOG ===\n(empty)")
        
        # Recent observations
        recent_obs = self.get_recent_observations(10)
        if recent_obs:
            lines.append("\n=== RECENT OBSERVATIONS ===")
            for obs in recent_obs:
                lines.append(f"• {obs['text']}")
        
        lines.append(f"\n[Cycle #{self.cycle_count}]")
        
        return "\n".join(lines)
