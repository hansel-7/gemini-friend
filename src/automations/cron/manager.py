"""Cron job manager — CRUD operations for dynamic scheduled jobs.

Stores jobs in a JSON file at D:/Gemini CLI/cron_jobs.json.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import threading

from croniter import croniter

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger


class CronJob:
    """Represents a single cron job."""
    
    def __init__(
        self,
        job_id: int,
        schedule: str,
        prompt: str,
        label: str = "",
        active: bool = True,
        use_mcp: bool = True,
        created_at: str = "",
        last_run: Optional[str] = None,
        run_count: int = 0
    ):
        self.job_id = job_id
        self.schedule = schedule
        self.prompt = prompt
        self.label = label or prompt[:50]
        self.active = active
        self.use_mcp = use_mcp
        self.created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.last_run = last_run
        self.run_count = run_count
    
    def next_run(self) -> Optional[datetime]:
        """Get the next scheduled run time."""
        try:
            cron = croniter(self.schedule, datetime.now())
            return cron.get_next(datetime)
        except Exception:
            return None
    
    def is_due(self) -> bool:
        """Check if this job should fire now (within the last 60 seconds)."""
        if not self.active:
            return False
        
        try:
            now = datetime.now()
            cron = croniter(self.schedule, now)
            prev_fire = cron.get_prev(datetime)
            
            # If the previous fire time is within the last 65 seconds
            # and we haven't run it yet
            seconds_since = (now - prev_fire).total_seconds()
            if seconds_since > 65:
                return False
            
            # Check if we already ran this job for this fire time
            if self.last_run:
                last = datetime.strptime(self.last_run, "%Y-%m-%d %H:%M:%S")
                # If last run was within 2 minutes of this fire time, skip
                if abs((last - prev_fire).total_seconds()) < 120:
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Cron: Error checking if job #{self.job_id} is due: {e}")
            return False
    
    def mark_run(self) -> None:
        """Mark this job as having just run."""
        self.last_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.run_count += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "job_id": self.job_id,
            "schedule": self.schedule,
            "prompt": self.prompt,
            "label": self.label,
            "active": self.active,
            "use_mcp": self.use_mcp,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "run_count": self.run_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CronJob':
        """Deserialize from dictionary."""
        return cls(**data)
    
    def human_schedule(self) -> str:
        """Return a human-readable description of the schedule."""
        parts = self.schedule.split()
        if len(parts) != 5:
            return self.schedule
        
        minute, hour, dom, month, dow = parts
        
        days = {
            '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed',
            '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun'
        }
        
        # Every minute
        if self.schedule == "* * * * *":
            return "Every minute"
        
        # Every N minutes
        if minute.startswith("*/") and hour == "*":
            return f"Every {minute[2:]} minutes"
        
        # Daily at specific time
        if dom == "*" and month == "*" and dow == "*":
            h = hour if hour != "*" else "every hour"
            m = minute.zfill(2) if minute != "*" else "00"
            return f"Daily at {h}:{m}"
        
        # Weekdays
        if dow == "1-5" and dom == "*" and month == "*":
            m = minute.zfill(2) if minute != "*" else "00"
            return f"Weekdays at {hour}:{m}"
        
        # Specific day of week
        if dow != "*" and dom == "*" and month == "*":
            day_names = []
            for d in dow.split(","):
                day_names.append(days.get(d, d))
            m = minute.zfill(2) if minute != "*" else "00"
            return f"{','.join(day_names)} at {hour}:{m}"
        
        return self.schedule


class CronJobManager:
    """Manages CRUD operations for cron jobs."""
    
    def __init__(self, data_file: str = "D:/Gemini CLI/cron_jobs.json"):
        self.data_file = Path(data_file)
        self._lock = threading.Lock()
        self._jobs: List[CronJob] = []
        self._next_id = 1
        self._load()
    
    def _load(self) -> None:
        """Load jobs from disk."""
        if not self.data_file.exists():
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._jobs = [CronJob.from_dict(j) for j in data.get("jobs", [])]
            self._next_id = data.get("next_id", 1)
            logger.info(f"Cron: Loaded {len(self._jobs)} jobs from {self.data_file}")
        except Exception as e:
            logger.error(f"Cron: Error loading jobs: {e}")
            self._jobs = []
    
    def _save(self) -> None:
        """Save jobs to disk."""
        try:
            data = {
                "jobs": [j.to_dict() for j in self._jobs],
                "next_id": self._next_id
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Cron: Error saving jobs: {e}")
    
    def add_job(
        self,
        schedule: str,
        prompt: str,
        label: str = "",
        use_mcp: bool = True
    ) -> Optional[CronJob]:
        """Add a new cron job.
        
        Args:
            schedule: Cron expression (e.g. "0 9 * * 1")
            prompt: The prompt to send to Gemini CLI when fired
            label: Optional human-readable label
            use_mcp: Whether to enable MCP tools for this job
            
        Returns:
            The created CronJob, or None if the schedule is invalid
        """
        # Validate cron expression
        if not croniter.is_valid(schedule):
            return None
        
        with self._lock:
            job = CronJob(
                job_id=self._next_id,
                schedule=schedule,
                prompt=prompt,
                label=label,
                use_mcp=use_mcp
            )
            self._next_id += 1
            self._jobs.append(job)
            self._save()
            logger.info(f"Cron: Added job #{job.job_id}: '{job.label}' [{job.schedule}]")
            return job
    
    def list_jobs(self, active_only: bool = False) -> List[CronJob]:
        """List all jobs."""
        if active_only:
            return [j for j in self._jobs if j.active]
        return list(self._jobs)
    
    def get_job(self, job_id: int) -> Optional[CronJob]:
        """Get a job by ID."""
        for job in self._jobs:
            if job.job_id == job_id:
                return job
        return None
    
    def delete_job(self, job_id: int) -> Optional[CronJob]:
        """Delete a job by ID."""
        with self._lock:
            for i, job in enumerate(self._jobs):
                if job.job_id == job_id:
                    removed = self._jobs.pop(i)
                    self._save()
                    logger.info(f"Cron: Deleted job #{job_id}: '{removed.label}'")
                    return removed
        return None
    
    def pause_job(self, job_id: int) -> Optional[CronJob]:
        """Pause a job."""
        with self._lock:
            for job in self._jobs:
                if job.job_id == job_id:
                    job.active = False
                    self._save()
                    logger.info(f"Cron: Paused job #{job_id}")
                    return job
        return None
    
    def resume_job(self, job_id: int) -> Optional[CronJob]:
        """Resume a paused job."""
        with self._lock:
            for job in self._jobs:
                if job.job_id == job_id:
                    job.active = True
                    self._save()
                    logger.info(f"Cron: Resumed job #{job_id}")
                    return job
        return None
    
    def get_due_jobs(self) -> List[CronJob]:
        """Get all jobs that are due to fire right now."""
        return [j for j in self._jobs if j.is_due()]
    
    def mark_job_run(self, job_id: int) -> None:
        """Mark a job as having run and save."""
        with self._lock:
            for job in self._jobs:
                if job.job_id == job_id:
                    job.mark_run()
                    self._save()
                    break
