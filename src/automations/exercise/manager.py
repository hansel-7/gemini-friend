"""Workout data manager.

Handles persistence of workout data to JSON file.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger


class WorkoutManager:
    """Manages workout data persistence.
    
    Reads and writes workout records to a JSON file.
    """
    
    def __init__(self, data_file: str = "workouts.json"):
        """Initialize the workout manager.
        
        Args:
            data_file: Path to the JSON data file
        """
        self.data_file = Path(data_file)
        self._ensure_file()
    
    def _ensure_file(self) -> None:
        """Ensure the data file exists."""
        if not self.data_file.exists():
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self.data_file.write_text("[]", encoding="utf-8")
    
    def load_workouts(self) -> List[Dict[str, Any]]:
        """Load all workouts from the JSON file."""
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"Could not read {self.data_file}, returning empty list")
            return []
    
    def save_workout(self, workout: Dict[str, Any]) -> bool:
        """Append a workout to the JSON file.
        
        Args:
            workout: Workout data dictionary
            
        Returns:
            True if saved successfully
        """
        try:
            workouts = self.load_workouts()
            workouts.append(workout)
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(workouts, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved workout {workout.get('id', '?')} to {self.data_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save workout: {e}")
            return False
    
    def get_recent(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get the most recent N workouts.
        
        Args:
            n: Number of workouts to return
            
        Returns:
            List of workout dictionaries, most recent first
        """
        workouts = self.load_workouts()
        return list(reversed(workouts[-n:]))
    
    def get_by_area(self, area: str) -> List[Dict[str, Any]]:
        """Get workouts filtered by muscle group area.
        
        Args:
            area: Muscle group name (case-insensitive)
            
        Returns:
            List of matching workouts
        """
        workouts = self.load_workouts()
        return [w for w in workouts if w.get("area", "").lower() == area.lower()]
    
    def get_total_count(self) -> int:
        """Get total number of workouts logged."""
        return len(self.load_workouts())
