"""Brain thinker module — autonomous agent version.

Replaces the old stateless thinker with a two-phase system:
1. Triage — decide what to work on (backlog, user tasks, observations)
2. Work — execute one step of the chosen task and report findings
"""

import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from typing import Optional, Tuple
from src.automations.brain.agent_state import AgentState
from src.automations.brain.learnings import AgentLearnings
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.conversation import conversation_history
from src.utils.logger import logger


# Marker for when agent has nothing to act on
NO_ACTION_MARKER = "[NO_ACTION]"
# Marker for when agent works silently (no user-facing message)
SILENT_MARKER = "[SILENT]"


class AgentThinker:
    """Two-phase autonomous thinker: triage then work."""
    
    TRIAGE_PROMPT = """{persona_section}{capabilities_section}You are an autonomous AI agent reviewing your current state to decide what to work on.

=== INSTRUCTIONS ===
Review your backlog, your observations, the user's pending tasks, and the conversation history.
Then decide ONE of:

1. **Pick a backlog item** to work on (set action="work", pick the task ID)
2. **Create a new task** from observations or user tasks that need attention (set action="add")
3. **Do nothing** if nothing is worth acting on right now (set action="none")

Prioritize:
- User tasks with approaching deadlines
- High-priority backlog items already in progress
- Interesting observations that the user would find valuable
- Stale user tasks you can help with (research, prepare, suggest)

Do NOT create a task for trivial things (greetings, acknowledgments, simple questions).
Do NOT create a task for something the user asked that was already answered in the conversation history.
Do NOT repeat work you've already done (check your backlog notes).

IMPORTANT SAFETY RULES:
- You must NEVER modify files inside the bot's codebase (the personal_assistant project).
- You CAN create standalone scripts in the workspace folder for the user.
- You CAN read and edit data files (tasks.json, expenses.json, etc.).

{learnings_section}{state_summary}

{user_tasks_section}

=== CONVERSATION HISTORY ===
{context}
=== END HISTORY ===

Respond with ONLY valid JSON, no other text:
{{
    "action": "work" | "add" | "none",
    "task_id": "<id of backlog item to work on, if action=work>",
    "new_task": "<description of new task to add, if action=add>",
    "new_priority": "high" | "medium" | "low",
    "new_source": "conversation" | "news" | "user_task" | "self",
    "reasoning": "<one line explaining your decision>"
}}"""

    WORK_PROMPT = """{persona_section}{capabilities_section}You are an autonomous AI agent working on a task.

=== YOUR CURRENT TASK ===
{task_description}

=== PROGRESS SO FAR ===
{task_notes}

=== INSTRUCTIONS ===
Do ONE step of work on this task. You can:
- Research information using your tools and knowledge
- Analyze data or trends
- Draft suggestions or recommendations
- Prepare information the user might need
- Create standalone scripts in the workspace folder

IMPORTANT SAFETY RULES:
- You must NEVER modify files inside the bot's codebase (the personal_assistant project).
- You CAN create standalone helper scripts in the workspace folder.
- You CAN read and edit data files (tasks.json, expenses.json, etc.).

{learnings_section}After doing the work, respond with ONLY valid JSON:
{{
    "findings": "<what you found or accomplished in this step>",
    "should_report": true | false,
    "report": "<message to send to the user, if should_report=true. Be concise and practical.>",
    "status": "in_progress" | "done",
    "reasoning": "<why you chose this status>",
    "lesson": "<optional — a reusable insight you learned from this work that would help in future tasks>"
}}

Set should_report=true only if you have something genuinely useful to share.
Set status="done" if the task is complete or you've done all you can.
Keep reports conversational and natural — like a helpful assistant sharing something they found.
Only include "lesson" if you genuinely discovered something reusable — don't force it.

=== CONVERSATION HISTORY (for context) ===
{context}
=== END HISTORY ==="""

    def __init__(self, state: AgentState, learnings: AgentLearnings = None, conversation_file: Optional[str] = None):
        """Initialize the thinker.
        
        Args:
            state: The agent's persistent state
            learnings: The agent's persistent learnings store
            conversation_file: Path to conversation history file
        """
        self.state = state
        self.learnings = learnings or AgentLearnings()
        self.gemini = GeminiCLI.get_instance()
        self.conversation_file = conversation_file
    
    async def run_triage(self, user_tasks_context: str = "") -> Optional[str]:
        """Run the triage phase — decide what to work on.
        
        Args:
            user_tasks_context: Formatted string of user's pending tasks
            
        Returns:
            Task ID to work on, "new" if a task was created, or None if nothing to do
        """
        try:
            context = conversation_history.get_context_for_gemini()
            
            if not context or len(context.strip()) < 50:
                logger.debug("Agent: Not enough conversation history for triage")
                return None
            
            # Build persona section
            persona_section = ""
            if self.gemini._persona:
                persona_section = f"=== USER PERSONA ===\n{self.gemini._persona}\n\n"
            
            # Build capabilities section
            capabilities_section = ""
            if self.gemini._capabilities:
                capabilities_section = self.gemini._capabilities + "\n"
            
            # Build user tasks section
            user_tasks_section = ""
            if user_tasks_context:
                user_tasks_section = f"=== USER'S PENDING TASKS ===\n{user_tasks_context}"
            else:
                user_tasks_section = "=== USER'S PENDING TASKS ===\n(none)"
            
            # Build learnings section
            learnings_section = self.learnings.get_lessons_for_prompt()
            if learnings_section:
                learnings_section += "\n"
            
            prompt = self.TRIAGE_PROMPT.format(
                persona_section=persona_section,
                capabilities_section=capabilities_section,
                learnings_section=learnings_section,
                state_summary=self.state.get_state_summary(),
                user_tasks_section=user_tasks_section,
                context=context
            )
            
            logger.info("Agent: Running triage...")
            response = await self.gemini.send_message(prompt, use_mcp=False)
            
            if not response:
                logger.info("Agent: Triage returned empty response")
                return None
            
            # Parse JSON response
            parsed = self._parse_json(response)
            if not parsed:
                logger.warning(f"Agent: Could not parse triage response: {response[:200]}")
                return None
            
            action = parsed.get("action", "none")
            reasoning = parsed.get("reasoning", "")
            logger.info(f"Agent: Triage decision: {action} — {reasoning}")
            
            if action == "work":
                task_id = str(parsed.get("task_id", ""))
                resolved = self._resolve_task_id(task_id)
                if resolved:
                    self.state.update_task(resolved, status="in_progress")
                    return resolved
                else:
                    logger.warning(f"Agent: Could not resolve task_id '{task_id}' to a backlog item")
                    return None
                    
            elif action == "add":
                new_task = parsed.get("new_task", "")
                priority = parsed.get("new_priority", "medium")
                source = parsed.get("new_source", "self")
                if new_task:
                    added = self.state.add_task(new_task, priority=priority, source=source)
                    self.state.update_task(added.id, status="in_progress")
                    return added.id
            
            # action == "none" or unrecognized
            return None
            
        except Exception as e:
            logger.error(f"Agent: Triage error: {e}")
            return None
    
    def _resolve_task_id(self, task_id: str) -> Optional[str]:
        """Resolve a possibly fuzzy task_id to an actual backlog item ID.
        
        The LLM sometimes returns:
        - The exact hex ID (ideal)
        - A numeric index like "1"
        - A description fragment like "Migrate bot to OptiPlex server"
        
        This method handles all cases.
        """
        if not task_id:
            return None
        
        active = self.state.get_active_tasks()
        if not active:
            return None
        
        # 1. Exact ID match
        for t in active:
            if t.id == task_id:
                return t.id
        
        # 2. Numeric index (1-based)
        try:
            idx = int(task_id) - 1
            if 0 <= idx < len(active):
                return active[idx].id
        except ValueError:
            pass
        
        # 3. Substring match on task description
        task_id_lower = task_id.lower()
        for t in active:
            if task_id_lower in t.task.lower() or t.task.lower() in task_id_lower:
                return t.id
        
        # 4. If only one active task, just use it
        if len(active) == 1:
            return active[0].id
        
        return None

    async def run_work(self, task_id: str) -> Tuple[Optional[str], bool]:
        """Run the work phase — do one step on the chosen task.
        
        Args:
            task_id: ID of the task to work on
            
        Returns:
            Tuple of (report_message, is_task_done)
            report_message is None if the agent worked silently
        """
        try:
            # Find the task
            task = None
            for t in self.state.backlog:
                if t.id == task_id:
                    task = t
                    break
            
            if not task:
                logger.warning(f"Agent: Task {task_id} not found in backlog")
                return None, False
            
            context = conversation_history.get_context_for_gemini()
            
            # Build persona section
            persona_section = ""
            if self.gemini._persona:
                persona_section = f"=== USER PERSONA ===\n{self.gemini._persona}\n\n"
            
            capabilities_section = ""
            if self.gemini._capabilities:
                capabilities_section = self.gemini._capabilities + "\n"
            
            # Format task notes
            task_notes = "No previous work on this task."
            if task.notes:
                task_notes = "\n".join(f"- {note}" for note in task.notes)
            
            # Build learnings section
            learnings_section = self.learnings.get_lessons_for_prompt()
            if learnings_section:
                learnings_section += "\n"
            
            prompt = self.WORK_PROMPT.format(
                persona_section=persona_section,
                capabilities_section=capabilities_section,
                learnings_section=learnings_section,
                task_description=task.task,
                task_notes=task_notes,
                context=context
            )
            
            logger.info(f"Agent: Working on task '{task.task[:50]}' (cycle {task.progress + 1})")
            response = await self.gemini.send_message(prompt, use_mcp=True)
            
            if not response:
                logger.warning("Agent: Work prompt returned empty response")
                return None, False
            
            # Parse JSON response
            parsed = self._parse_json(response)
            if not parsed:
                logger.warning(f"Agent: Could not parse work response: {response[:200]}")
                # Treat raw response as findings
                self.state.update_task(task_id, note=response[:500])
                return None, False
            
            findings = parsed.get("findings", "")
            should_report = parsed.get("should_report", False)
            report = parsed.get("report", "")
            status = parsed.get("status", "in_progress")
            lesson = parsed.get("lesson", "")
            
            # Save findings to task notes
            if findings:
                self.state.update_task(task_id, note=findings[:500])
            
            # Save lesson if the agent learned something
            if lesson and len(lesson.strip()) > 10:
                self.learnings.add_lesson(
                    text=lesson.strip(),
                    source_task=task.task[:100],
                    cycle=self.state.cycle_count
                )
            
            # Update status
            if status == "done":
                self.state.complete_task(task_id)
                logger.info(f"Agent: Task '{task.task[:50]}' completed")
            
            # Return report if agent wants to share
            if should_report and report:
                return report, status == "done"
            
            return None, status == "done"
            
        except Exception as e:
            logger.error(f"Agent: Work error: {e}")
            return None, False
    
    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract and parse JSON from a response that may contain extra text."""
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON block
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        return None
