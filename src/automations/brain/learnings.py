"""Agent learnings module — persistent meta-memory for prompt self-improvement.

Stores lessons the agent learns from work cycles and injects them
into triage/work prompts so the agent avoids repeating mistakes
and builds on past insights.
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger
from config.settings import settings


class AgentLearnings:
    """Persistent learnings store for the autonomous agent.
    
    Lessons are short, reusable insights the agent discovers during
    work cycles. They get injected into future prompts so the agent
    improves over time without modifying the prompts themselves.
    """
    
    MAX_LESSONS = 30
    CONSOLIDATION_THRESHOLD = 15
    
    CONSOLIDATION_PROMPT = """You are reviewing a list of lessons that an AI agent has learned from past work cycles.

=== CURRENT LESSONS ===
{lessons_text}

=== INSTRUCTIONS ===
Consolidate these {count} lessons into 8 or fewer high-quality rules. Guidelines:
- Merge duplicates and near-duplicates into single, stronger rules
- Keep lessons that are specific and actionable
- Drop lessons that are too vague or no longer relevant
- Preserve the user's preferences and communication style insights
- Each rule should be a single clear sentence

Respond with ONLY a JSON array of strings, no other text:
["Rule 1", "Rule 2", ...]"""

    def __init__(self, learnings_file: str = None):
        """Initialize the learnings store.
        
        Args:
            learnings_file: Path to the JSON file. Defaults to DATA_DIR/agent_learnings.json
        """
        if learnings_file is None:
            learnings_file = str(settings.DATA_DIR / "agent_learnings.json")
        
        self.learnings_file = Path(learnings_file)
        self._lock = threading.Lock()
        
        # In-memory state
        self.lessons: List[Dict[str, Any]] = []
        self.last_consolidated: Optional[str] = None
        self.consolidation_count: int = 0
        
        self._load()
    
    # --- Persistence ---
    
    def _load(self) -> None:
        """Load learnings from disk."""
        if not self.learnings_file.exists():
            logger.info("AgentLearnings: No learnings file found, starting fresh")
            self._save()
            return
        
        try:
            with open(self.learnings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.lessons = data.get("lessons", [])
            self.last_consolidated = data.get("last_consolidated")
            self.consolidation_count = data.get("consolidation_count", 0)
            
            logger.info(
                f"AgentLearnings: Loaded {len(self.lessons)} lessons "
                f"({self.consolidation_count} consolidations)"
            )
        except Exception as e:
            logger.error(f"AgentLearnings: Failed to load: {e}")
    
    def _save(self) -> None:
        """Save learnings to disk."""
        try:
            self.learnings_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "lessons": self.lessons,
                "last_consolidated": self.last_consolidated,
                "consolidation_count": self.consolidation_count,
                "last_saved": datetime.now().isoformat()
            }
            
            with open(self.learnings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"AgentLearnings: Failed to save: {e}")
    
    # --- Lesson Management ---
    
    def add_lesson(self, text: str, source_task: str = "", cycle: int = 0) -> None:
        """Add a lesson learned from a work cycle.
        
        Args:
            text: The lesson text (a reusable insight)
            source_task: Description of the task that produced this lesson
            cycle: The cycle number when this was learned
        """
        with self._lock:
            # Skip near-duplicate lessons
            text_lower = text.lower().strip()
            for existing in self.lessons:
                if existing["text"].lower().strip() == text_lower:
                    logger.debug(f"AgentLearnings: Skipping duplicate lesson")
                    return
            
            self.lessons.append({
                "text": text,
                "source_task": source_task,
                "created_at": datetime.now().isoformat(),
                "cycle": cycle
            })
            
            # Prune oldest if over max
            if len(self.lessons) > self.MAX_LESSONS:
                self.lessons = self.lessons[-self.MAX_LESSONS:]
            
            self._save()
            logger.info(f"AgentLearnings: Added lesson ({len(self.lessons)} total): {text[:80]}")
    
    def get_lessons_for_prompt(self) -> str:
        """Get formatted lessons for injection into prompts.
        
        Returns:
            Formatted string, or empty string if no lessons yet
        """
        if not self.lessons:
            return ""
        
        lines = ["=== THINGS YOU'VE LEARNED ===",
                 "These are insights from your past work. Use them to make better decisions:"]
        for lesson in self.lessons:
            lines.append(f"- {lesson['text']}")
        lines.append("")
        
        return "\n".join(lines)
    
    def needs_consolidation(self) -> bool:
        """Check if lessons should be consolidated."""
        return len(self.lessons) >= self.CONSOLIDATION_THRESHOLD
    
    async def consolidate(self, gemini) -> bool:
        """Consolidate lessons by asking Gemini to distill them.
        
        Args:
            gemini: GeminiCLI instance for the consolidation call
            
        Returns:
            True if consolidation was successful
        """
        if not self.needs_consolidation():
            return False
        
        try:
            lessons_text = "\n".join(
                f"{i+1}. {l['text']}" for i, l in enumerate(self.lessons)
            )
            
            prompt = self.CONSOLIDATION_PROMPT.format(
                lessons_text=lessons_text,
                count=len(self.lessons)
            )
            
            logger.info(
                f"AgentLearnings: Consolidating {len(self.lessons)} lessons..."
            )
            response = await gemini.send_message(prompt, use_mcp=False)
            
            if not response:
                logger.warning("AgentLearnings: Consolidation returned empty response")
                return False
            
            # Parse the JSON array response
            consolidated = self._parse_consolidated(response)
            if not consolidated:
                logger.warning("AgentLearnings: Could not parse consolidation response")
                return False
            
            # Replace lessons with consolidated set
            with self._lock:
                self.lessons = [
                    {
                        "text": rule,
                        "source_task": "consolidated",
                        "created_at": datetime.now().isoformat(),
                        "cycle": 0
                    }
                    for rule in consolidated
                ]
                self.last_consolidated = datetime.now().isoformat()
                self.consolidation_count += 1
                self._save()
            
            logger.info(
                f"AgentLearnings: Consolidated into {len(consolidated)} rules "
                f"(consolidation #{self.consolidation_count})"
            )
            return True
            
        except Exception as e:
            logger.error(f"AgentLearnings: Consolidation error: {e}")
            return False
    
    def _parse_consolidated(self, text: str) -> Optional[List[str]]:
        """Parse the consolidation response (a JSON array of strings)."""
        import re
        
        # Try direct parse
        try:
            result = json.loads(text.strip())
            if isinstance(result, list):
                return [str(r) for r in result if r]
        except json.JSONDecodeError:
            pass
        
        # Try to find a JSON array in the text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return [str(r) for r in result if r]
            except json.JSONDecodeError:
                pass
        
        return None
    
    def get_lesson_count(self) -> int:
        """Get the number of stored lessons."""
        return len(self.lessons)
