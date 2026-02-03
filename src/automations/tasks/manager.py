"""Task manager for CRUD operations.

Handles reading, writing, and managing tasks in a JSON file.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import threading

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger


class Task:
    """Represents a single task."""
    
    def __init__(
        self,
        id: int,
        description: str,
        created_at: datetime,
        due_at: Optional[datetime] = None,
        status: str = "pending",
        deadline_reminder_sent: bool = False,
        notes: str = ""
    ):
        self.id = id
        self.description = description
        self.created_at = created_at
        self.due_at = due_at
        self.status = status  # pending, completed, cancelled
        self.deadline_reminder_sent = deadline_reminder_sent  # True if 1-hour-before reminder sent
        self.notes = notes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "status": self.status,
            "deadline_reminder_sent": self.deadline_reminder_sent,
            "notes": self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create a Task from a dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            due_at=datetime.fromisoformat(data["due_at"]) if data.get("due_at") else None,
            status=data.get("status", "pending"),
            deadline_reminder_sent=data.get("deadline_reminder_sent", False),
            notes=data.get("notes", "")
        )
    
    def is_pending(self) -> bool:
        """Check if task is still pending."""
        return self.status == "pending"
    
    def is_overdue(self) -> bool:
        """Check if task is past its due date."""
        if not self.due_at:
            return False
        return datetime.now() > self.due_at and self.is_pending()
    
    def time_until_due(self) -> Optional[timedelta]:
        """Get time remaining until due date."""
        if not self.due_at:
            return None
        return self.due_at - datetime.now()


class TaskManager:
    """Manages task storage and operations."""
    
    def __init__(self, data_file: str):
        """Initialize the task manager.
        
        Args:
            data_file: Path to the JSON file for task storage
        """
        self.data_file = Path(data_file)
        self._lock = threading.Lock()
        self._ensure_file_exists()
    
    def _ensure_file_exists(self) -> None:
        """Create the data file if it doesn't exist."""
        if not self.data_file.exists():
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_tasks([])
            logger.info(f"Created task file at {self.data_file}")
    
    def _load_tasks(self) -> List[Task]:
        """Load all tasks from the JSON file."""
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tasks = []
            for task_data in data.get("tasks", []):
                try:
                    tasks.append(Task.from_dict(task_data))
                except Exception as e:
                    logger.error(f"Failed to parse task: {e}")
            
            return tasks
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in {self.data_file}, starting fresh")
            return []
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            return []
    
    def _save_tasks(self, tasks: List[Task]) -> bool:
        """Save all tasks to the JSON file."""
        try:
            data = {
                "tasks": [task.to_dict() for task in tasks],
                "last_updated": datetime.now().isoformat()
            }
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")
            return False
    
    def _get_next_id(self, tasks: List[Task]) -> int:
        """Get the next available task ID."""
        if not tasks:
            return 1
        return max(task.id for task in tasks) + 1
    
    def add_task(
        self,
        description: str,
        due_at: Optional[datetime] = None,
        notes: str = ""
    ) -> Optional[Task]:
        """Add a new task.
        
        Args:
            description: Task description
            due_at: Optional due date (reminder sent 1 hour before)
            notes: Optional additional notes
            
        Returns:
            The created Task, or None if failed
        """
        with self._lock:
            tasks = self._load_tasks()
            
            task = Task(
                id=self._get_next_id(tasks),
                description=description,
                created_at=datetime.now(),
                due_at=due_at,
                notes=notes
            )
            
            tasks.append(task)
            
            if self._save_tasks(tasks):
                logger.info(f"Added task #{task.id}: {description[:50]}")
                return task
            return None
    
    def get_task(self, task_id: int) -> Optional[Task]:
        """Get a task by ID."""
        with self._lock:
            tasks = self._load_tasks()
            for task in tasks:
                if task.id == task_id:
                    return task
            return None
    
    def get_all_tasks(self, include_completed: bool = False) -> List[Task]:
        """Get all tasks.
        
        Args:
            include_completed: If True, include completed tasks
            
        Returns:
            List of tasks
        """
        with self._lock:
            tasks = self._load_tasks()
            
            if include_completed:
                return tasks
            
            return [t for t in tasks if t.is_pending()]
    
    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        return self.get_all_tasks(include_completed=False)
    
    def get_tasks_due_soon(self, hours: int = 24) -> List[Task]:
        """Get all pending tasks due within the specified hours.
        
        Args:
            hours: Number of hours to look ahead
            
        Returns:
            List of tasks due within the time window
        """
        with self._lock:
            tasks = self._load_tasks()
            threshold = datetime.now() + timedelta(hours=hours)
            return [
                t for t in tasks 
                if t.is_pending() and t.due_at and t.due_at <= threshold
            ]
    
    def complete_task(self, task_id: int) -> Optional[Task]:
        """Mark a task as completed.
        
        Args:
            task_id: ID of the task to complete
            
        Returns:
            The completed Task, or None if not found
        """
        with self._lock:
            tasks = self._load_tasks()
            
            for task in tasks:
                if task.id == task_id:
                    task.status = "completed"
                    if self._save_tasks(tasks):
                        logger.info(f"Completed task #{task_id}")
                        return task
                    return None
            
            return None
    
    def update_task(
        self,
        task_id: int,
        description: Optional[str] = None,
        due_at: Optional[datetime] = None,
        notes: Optional[str] = None
    ) -> Optional[Task]:
        """Update a task.
        
        Args:
            task_id: ID of the task to update
            description: New description (optional)
            due_at: New due date (optional, resets deadline reminder if changed)
            notes: New notes (optional)
            
        Returns:
            The updated Task, or None if not found
        """
        with self._lock:
            tasks = self._load_tasks()
            
            for task in tasks:
                if task.id == task_id:
                    if description is not None:
                        task.description = description
                    if due_at is not None:
                        task.due_at = due_at
                        task.deadline_reminder_sent = False  # Reset reminder if due date changed
                    if notes is not None:
                        task.notes = notes
                    
                    if self._save_tasks(tasks):
                        logger.info(f"Updated task #{task_id}")
                        return task
                    return None
            
            return None
    
    def mark_deadline_reminded(self, task_id: int) -> bool:
        """Mark that the deadline reminder has been sent for a task.
        
        Args:
            task_id: ID of the task
            
        Returns:
            True if successful
        """
        with self._lock:
            tasks = self._load_tasks()
            
            for task in tasks:
                if task.id == task_id:
                    task.deadline_reminder_sent = True
                    return self._save_tasks(tasks)
            
            return False
    
    def delete_task(self, task_id: int) -> bool:
        """Delete a task.
        
        Args:
            task_id: ID of the task to delete
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            tasks = self._load_tasks()
            original_count = len(tasks)
            
            tasks = [t for t in tasks if t.id != task_id]
            
            if len(tasks) < original_count:
                if self._save_tasks(tasks):
                    logger.info(f"Deleted task #{task_id}")
                    return True
            
            return False
    
    def clear_completed(self) -> int:
        """Remove all completed tasks.
        
        Returns:
            Number of tasks removed
        """
        with self._lock:
            tasks = self._load_tasks()
            original_count = len(tasks)
            
            tasks = [t for t in tasks if t.is_pending()]
            removed = original_count - len(tasks)
            
            if removed > 0:
                self._save_tasks(tasks)
                logger.info(f"Cleared {removed} completed tasks")
            
            return removed
