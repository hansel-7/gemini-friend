"""Telegram handlers for task automation.

Provides commands for managing tasks via Telegram.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import re

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.base import BaseAutomation
from src.automations.tasks.manager import TaskManager, Task
from src.automations.tasks.scheduler import TaskScheduler
from src.automations.tasks.parser import (
    looks_like_task,
    get_task_extraction_prompt,
    parse_gemini_response,
    parse_due_date
)
from src.bot.security import authorized_only
from src.utils.logger import logger
from config.settings import settings


def parse_datetime(text: str) -> Optional[datetime]:
    """Parse a datetime from natural language.
    
    Supports formats like:
    - "tomorrow"
    - "tomorrow 3pm"
    - "friday"
    - "in 2 hours"
    - "2026-01-30 14:00"
    
    Args:
        text: Text to parse
        
    Returns:
        Parsed datetime or None
    """
    text = text.lower().strip()
    now = datetime.now()
    
    # Relative times
    if text == "tomorrow":
        return now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    
    if text.startswith("tomorrow "):
        time_part = text[9:].strip()
        base = now + timedelta(days=1)
        return _parse_time_into_date(base, time_part)
    
    if text.startswith("in "):
        match = re.match(r'in (\d+) (hour|hours|minute|minutes|day|days)', text)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            if 'hour' in unit:
                return now + timedelta(hours=amount)
            elif 'minute' in unit:
                return now + timedelta(minutes=amount)
            elif 'day' in unit:
                return now + timedelta(days=amount)
    
    # Day names
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for i, day in enumerate(days):
        if text.startswith(day):
            days_ahead = i - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)
            
            # Check for time
            if ' ' in text:
                time_part = text.split(' ', 1)[1]
                return _parse_time_into_date(target, time_part)
            return target
    
    # ISO format
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    
    # Date formats
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    
    return None


def _parse_time_into_date(base: datetime, time_str: str) -> datetime:
    """Parse a time string and apply it to a base date."""
    time_str = time_str.lower().strip()
    
    # 12-hour format with am/pm
    match = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        ampm = match.group(3)
        
        if ampm == 'pm' and hour != 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
        
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    return base


class TasksAutomation(BaseAutomation):
    """Task management automation with reminders."""
    
    name = "tasks"
    description = "Task/checklist management with reminders"
    version = "1.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        super().__init__(application, config)
        
        # Initialize task manager
        data_file = config.get('data_file', 'D:/Gemini CLI/tasks.json')
        self.task_manager = TaskManager(data_file)
        
        # Initialize scheduler with new reminder strategy
        check_interval = config.get('reminder_check_interval', 60)
        daily_digest_hour = config.get('daily_digest_hour', 7)
        daily_digest_minute = config.get('daily_digest_minute', 0)
        hours_before_deadline = config.get('hours_before_deadline', 1)
        
        self.scheduler = TaskScheduler(
            self.task_manager,
            check_interval=check_interval,
            daily_digest_hour=daily_digest_hour,
            daily_digest_minute=daily_digest_minute,
            hours_before_deadline=hours_before_deadline,
            on_daily_digest=self._send_daily_digest,
            on_deadline_reminder=self._send_deadline_reminder
        )
        
        # Store bot reference for sending messages
        self._bot = None
    
    def register_handlers(self) -> None:
        """Register task-related command handlers."""
        handlers = [
            CommandHandler("task", self._add_task_command),
            CommandHandler("tasks", self._list_tasks_command),
            CommandHandler("done", self._complete_task_command),
            CommandHandler("deltask", self._delete_task_command),
            CommandHandler("cleartasks", self._clear_tasks_command),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
            self._handlers.append(handler)
        
        logger.info(f"Registered {len(handlers)} task command handlers")
    
    async def start(self) -> None:
        """Start the task scheduler."""
        await super().start()
        self._bot = self.application.bot
        await self.scheduler.start()
    
    async def stop(self) -> None:
        """Stop the task scheduler."""
        await self.scheduler.stop()
        await super().stop()
    
    def is_task_message(self, message: str) -> bool:
        """Check if a message looks like a task/reminder request.
        
        This can be called from the main message handler to detect
        natural language task requests.
        
        Args:
            message: The user's message
            
        Returns:
            True if the message appears to be a task request
        """
        return looks_like_task(message)
    
    def get_extraction_prompt(self, message: str) -> str:
        """Get the prompt to send to Gemini for task extraction.
        
        Args:
            message: The user's natural language task request
            
        Returns:
            Prompt string for Gemini
        """
        return get_task_extraction_prompt(message)
    
    async def create_task_from_parsed(
        self,
        gemini_response: str,
        update: 'Update'
    ) -> bool:
        """Create task(s) from Gemini's parsed response.
        
        Supports creating multiple tasks from a single message.
        
        Args:
            gemini_response: Gemini's JSON response
            update: Telegram update for sending confirmation
            
        Returns:
            True if at least one task was created successfully
        """
        # Parse Gemini's response (now returns a list)
        parsed_tasks = parse_gemini_response(gemini_response)
        
        if not parsed_tasks:
            return False
        
        # Create all tasks
        created_tasks = []
        for parsed in parsed_tasks:
            due_at = parse_due_date(parsed.get('due_date'))
            
            task = self.task_manager.add_task(
                description=parsed['description'],
                due_at=due_at
            )
            
            if task:
                created_tasks.append(task)
                logger.info(f"Created task #{task.id} from natural language: {task.description}")
        
        if not created_tasks:
            return False
        
        # Build confirmation message
        if len(created_tasks) == 1:
            # Single task - detailed format
            task = created_tasks[0]
            response = f"✅ *Task Added!*\n\n📝 {task.description}"
            
            if task.due_at:
                response += f"\n📅 Due: {task.due_at.strftime('%A, %b %d at %H:%M')}"
                response += f"\n⏰ Reminder: 1 hour before"
            else:
                response += f"\n📅 No deadline set"
            
            response += f"\n\n_Task #{task.id} • Daily digest at 7 AM_"
        else:
            # Multiple tasks - summary format
            response = f"✅ *{len(created_tasks)} Tasks Added!*\n\n"
            
            for task in created_tasks:
                due_str = ""
                if task.due_at:
                    due_str = f" _(due {task.due_at.strftime('%a %m/%d %H:%M')})_"
                response += f"📝 `#{task.id}` {task.description}{due_str}\n"
            
            response += f"\n_Daily digest at 7 AM • Reminders 1h before deadlines_"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        return True
    
    async def _send_daily_digest(self, tasks: list) -> None:
        """Send the daily digest of all pending tasks."""
        if not self._bot or not tasks:
            return
        
        # Build task list
        task_lines = []
        overdue_count = 0
        due_today_count = 0
        
        for task in tasks:
            line = f"  `{task.id}.` {task.description}"
            
            if task.due_at:
                if task.is_overdue():
                    line += " ⚠️ *OVERDUE*"
                    overdue_count += 1
                elif task.due_at.date() == datetime.now().date():
                    line += f" (due today {task.due_at.strftime('%H:%M')})"
                    due_today_count += 1
                else:
                    line += f" (due {task.due_at.strftime('%m/%d')})"
            
            task_lines.append(line)
        
        # Build message
        header = "☀️ *Good Morning! Daily Task Summary*\n\n"
        
        if overdue_count > 0:
            header += f"⚠️ {overdue_count} overdue task(s)!\n"
        if due_today_count > 0:
            header += f"📅 {due_today_count} task(s) due today\n"
        
        header += f"\n*{len(tasks)} Pending Task(s):*\n"
        
        message = header + "\n".join(task_lines)
        message += "\n\n_Use /done <id> to complete a task._"
        
        # Send to all authorized users
        for user_id in settings.ALLOWED_USER_IDS:
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"Sent daily digest to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send daily digest to {user_id}: {e}")
    
    async def _send_deadline_reminder(self, task: Task) -> None:
        """Send a reminder 1 hour before task deadline."""
        if not self._bot:
            return
        
        time_left = task.time_until_due()
        if time_left:
            minutes_left = int(time_left.total_seconds() / 60)
            time_str = f"{minutes_left} minutes" if minutes_left < 60 else "~1 hour"
        else:
            time_str = "soon"
        
        message = (
            f"⏰ *Deadline Approaching!*\n\n"
            f"📝 {task.description}\n"
            f"⏱️ Due in {time_str}\n"
            f"📅 {task.due_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Reply `/done {task.id}` when complete."
        )
        
        # Send to all authorized users
        for user_id in settings.ALLOWED_USER_IDS:
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"Sent deadline reminder for task #{task.id} to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send deadline reminder to {user_id}: {e}")
    
    @authorized_only
    async def _add_task_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /task command to add a new task.
        
        Usage: /task <description> [due:<date>]
        Examples:
            /task Buy groceries
            /task Finish report due:friday
            /task Call mom due:tomorrow 8pm
        """
        if not context.args:
            await update.message.reply_text(
                "📝 *Add a Task*\n\n"
                "Usage: `/task <description> [due:<date>]`\n\n"
                "*Examples:*\n"
                "• `/task Buy groceries`\n"
                "• `/task Finish report due:friday`\n"
                "• `/task Call mom due:tomorrow 8pm`\n"
                "• `/task Meeting due:2026-01-30 14:00`\n\n"
                "*Date formats:*\n"
                "• `tomorrow`, `friday`, `monday 3pm`\n"
                "• `in 2 hours`, `in 3 days`\n"
                "• `2026-01-30 14:00`\n\n"
                "*Reminders:*\n"
                "• Daily digest at 7 AM\n"
                "• 1 hour before deadline",
                parse_mode='Markdown'
            )
            return
        
        # Parse the command
        text = ' '.join(context.args)
        
        # Extract due date
        due_at = None
        due_match = re.search(r'due:(\S+(?:\s+\d{1,2}(?::\d{2})?(?:am|pm)?)?)', text, re.IGNORECASE)
        if due_match:
            due_str = due_match.group(1)
            due_at = parse_datetime(due_str)
            text = text[:due_match.start()] + text[due_match.end():]
        
        # Clean up description
        description = ' '.join(text.split()).strip()
        
        if not description:
            await update.message.reply_text("❌ Please provide a task description.")
            return
        
        # Add the task
        task = self.task_manager.add_task(
            description=description,
            due_at=due_at
        )
        
        if task:
            response = f"✅ *Task #{task.id} Added*\n\n📝 {task.description}"
            
            if task.due_at:
                response += f"\n📅 Due: {task.due_at.strftime('%Y-%m-%d %H:%M')}"
                response += f"\n⏰ Reminder: 1 hour before deadline"
            
            response += f"\n\n_Daily summary at 7 AM_"
            
            await update.message.reply_text(response, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Failed to add task. Please try again.")
    
    @authorized_only
    async def _list_tasks_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /tasks command to list all tasks."""
        # Check for 'all' flag to include completed
        include_completed = context.args and context.args[0].lower() == 'all'
        
        tasks = self.task_manager.get_all_tasks(include_completed=include_completed)
        
        if not tasks:
            await update.message.reply_text(
                "📋 *No tasks*\n\n"
                "Your task list is empty! Add one with:\n"
                "`/task Buy groceries`",
                parse_mode='Markdown'
            )
            return
        
        # Group tasks by status
        pending = [t for t in tasks if t.status == 'pending']
        completed = [t for t in tasks if t.status == 'completed']
        
        response = "📋 *Your Tasks*\n\n"
        
        if pending:
            response += "*Pending:*\n"
            for task in pending:
                due_str = ""
                if task.due_at:
                    due_str = f" (due: {task.due_at.strftime('%m/%d')})"
                response += f"  `{task.id}.` {task.description}{due_str}\n"
        
        if completed and include_completed:
            response += "\n*Completed:*\n"
            for task in completed:
                response += f"  ✓ ~~{task.description}~~\n"
        
        response += f"\n_Total: {len(pending)} pending"
        if include_completed:
            response += f", {len(completed)} completed"
        response += "_"
        
        response += "\n\nUse `/done <id>` to complete a task."
        
        await update.message.reply_text(response, parse_mode='Markdown')
    
    @authorized_only
    async def _complete_task_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /done command to mark a task as complete."""
        if not context.args:
            await update.message.reply_text(
                "Usage: `/done <task_id>`\n"
                "Example: `/done 3`",
                parse_mode='Markdown'
            )
            return
        
        try:
            task_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid task ID. Use a number.")
            return
        
        task = self.task_manager.complete_task(task_id)
        
        if task:
            await update.message.reply_text(
                f"✅ *Task Completed!*\n\n"
                f"~~{task.description}~~\n\n"
                f"Great job! 🎉",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Task #{task_id} not found.")
    
    @authorized_only
    async def _delete_task_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /deltask command to delete a task."""
        if not context.args:
            await update.message.reply_text(
                "Usage: `/deltask <task_id>`\n"
                "Example: `/deltask 3`",
                parse_mode='Markdown'
            )
            return
        
        try:
            task_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid task ID. Use a number.")
            return
        
        # Get task first for confirmation message
        task = self.task_manager.get_task(task_id)
        
        if task and self.task_manager.delete_task(task_id):
            await update.message.reply_text(
                f"🗑️ *Task Deleted*\n\n"
                f"~~{task.description}~~",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Task #{task_id} not found.")
    
    @authorized_only
    async def _clear_tasks_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /cleartasks command to remove completed tasks."""
        removed = self.task_manager.clear_completed()
        
        if removed > 0:
            await update.message.reply_text(
                f"🗑️ Cleared {removed} completed task(s)."
            )
        else:
            await update.message.reply_text(
                "No completed tasks to clear."
            )
