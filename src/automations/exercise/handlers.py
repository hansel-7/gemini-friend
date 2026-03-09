"""Exercise automation handlers.

Simple state-based workout tracker via Telegram.
Flow: /exercise → area → exercise name → sets (reps x weight) → /next or /finish

Uses internal state tracking instead of ConversationHandler to avoid
handler ordering issues with the general message handler.
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.base import BaseAutomation
from src.automations.exercise.manager import WorkoutManager
from src.bot.security import authorized_only
from src.utils.logger import logger
from config.settings import settings


# Session states
STATE_AREA = "area"
STATE_EXERCISE_NAME = "exercise_name"
STATE_SET_DATA = "set_data"


def _parse_set_input(text: str) -> tuple:
    """Parse set input in flexible formats.
    
    Supported formats:
        10x60       → 10 reps, 60 kg
        10 x 60     → 10 reps, 60 kg
        10 60       → 10 reps, 60 kg
        10x60kg     → 10 reps, 60 kg
        10          → 10 reps, bodyweight (0 kg)
    
    Returns:
        Tuple of (reps, weight_kg) or (None, None) if unparseable
    """
    text = text.strip().lower()
    
    # Remove units
    text = re.sub(r'\s*(kg|lbs?|pounds?|kilos?)\s*', ' ', text)
    text = re.sub(r'\s*reps?\s*', ' ', text)
    text = text.strip()
    
    # Format: 10x60 or 10 x 60
    match = re.match(r'^(\d+)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*$', text)
    if match:
        return int(match.group(1)), float(match.group(2))
    
    # Format: 10 60 (two numbers separated by space)
    match = re.match(r'^(\d+)\s+(\d+(?:\.\d+)?)\s*$', text)
    if match:
        return int(match.group(1)), float(match.group(2))
    
    # Format: just a number (bodyweight exercise)
    match = re.match(r'^(\d+)\s*$', text)
    if match:
        return int(match.group(1)), 0
    
    return None, None


class ExerciseAutomation(BaseAutomation):
    """Exercise/workout tracking automation.
    
    Features:
    1. /exercise command to start a workout session
    2. Simple text input: area → exercise → sets
    3. /next to switch exercises within a session
    4. /finish to end and save the workout
    5. /workouts to view recent history
    
    State is tracked internally per user. During an active session,
    text messages are routed here by _process_text_message instead of Gemini.
    """
    
    name = "exercise"
    description = "Workout/exercise tracker"
    version = "1.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        """Initialize the exercise automation."""
        super().__init__(application, config)
        
        # Initialize workout manager
        data_file = config.get('data_file', 'workouts.json')
        if not Path(data_file).is_absolute():
            data_file = str(settings.DATA_DIR / data_file)
        self.manager = WorkoutManager(data_file=data_file)
        
        # Active sessions: {user_id: session_data}
        self._sessions: Dict[int, Dict[str, Any]] = {}
    
    def has_active_session(self, user_id: int) -> bool:
        """Check if a user has an active exercise session."""
        return user_id in self._sessions
    
    def register_handlers(self) -> None:
        """Register exercise command handlers."""
        handlers = [
            CommandHandler("exercise", self._start_exercise),
            CommandHandler("next", self._next_exercise),
            CommandHandler("finish", self._finish_workout),
            CommandHandler("workouts", self._workouts_command),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
            self._handlers.append(handler)
        
        logger.info("Exercise: Registered command handlers")
    
    async def handle_session_input(self, update: Update) -> None:
        """Handle a text message during an active exercise session.
        
        Called by _process_text_message when user has an active session.
        Routes to the appropriate handler based on current state.
        """
        user_id = update.effective_user.id
        session = self._sessions.get(user_id)
        
        if not session:
            return
        
        text = update.message.text.strip()
        state = session.get('state')
        
        if state == STATE_AREA:
            await self._receive_area(update, text, session)
        elif state == STATE_EXERCISE_NAME:
            await self._receive_exercise_name(update, text, session)
        elif state == STATE_SET_DATA:
            await self._receive_set(update, text, session)
    
    # --- Command Handlers ---
    
    @authorized_only
    async def _start_exercise(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /exercise — start a new workout session."""
        user_id = update.effective_user.id
        
        # Create a new session
        self._sessions[user_id] = {
            'state': STATE_AREA,
            'start_time': datetime.now(),
            'area': None,
            'exercises': [],
            'current_exercise': None,
        }
        
        await update.message.reply_text(
            "🏋️ *Workout Started!*\n\n"
            "What area are you training today?\n"
            "_(e.g., chest, back, legs, shoulders, arms)_",
            parse_mode='Markdown'
        )
    
    @authorized_only
    async def _next_exercise(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /next — save current exercise, ask for next one."""
        user_id = update.effective_user.id
        session = self._sessions.get(user_id)
        
        if not session:
            await update.message.reply_text("No active workout. Use /exercise to start.")
            return
        
        # Save the current exercise if it has sets
        current = session.get('current_exercise')
        if current and current['sets']:
            session['exercises'].append(current)
            
            # Show summary of completed exercise
            summary = self._format_exercise_summary(current)
            await update.message.reply_text(
                f"✅ *{current['name']}* done!\n\n{summary}\n\n"
                "What's your next exercise?",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "⚠️ No sets logged for current exercise.\n\n"
                "What's your next exercise?"
            )
        
        session['current_exercise'] = None
        session['state'] = STATE_EXERCISE_NAME
    
    @authorized_only
    async def _finish_workout(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /finish — save the workout and show summary."""
        user_id = update.effective_user.id
        session = self._sessions.get(user_id)
        
        if not session:
            await update.message.reply_text("No active workout. Use /exercise to start.")
            return
        
        # Save the current exercise if it has sets
        current = session.get('current_exercise')
        if current and current.get('sets'):
            session['exercises'].append(current)
        
        exercises = session.get('exercises', [])
        
        if not exercises:
            await update.message.reply_text(
                "⚠️ No exercises logged. Workout cancelled."
            )
            self._sessions.pop(user_id, None)
            return
        
        # Build the final workout record
        start_time = session['start_time']
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() / 60
        
        workout_record = {
            'id': start_time.strftime('%Y%m%d_%H%M%S'),
            'date': start_time.strftime('%Y-%m-%d'),
            'start_time': start_time.strftime('%H:%M:%S'),
            'end_time': end_time.strftime('%H:%M:%S'),
            'area': session.get('area', 'unknown'),
            'exercises': exercises,
            'duration_minutes': round(duration, 1),
        }
        
        # Save to file
        saved = self.manager.save_workout(workout_record)
        
        # Build summary message
        summary = self._format_workout_summary(workout_record)
        
        if saved:
            await update.message.reply_text(
                f"🎉 *Workout Complete!*\n\n{summary}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"⚠️ Workout finished but failed to save.\n\n{summary}",
                parse_mode='Markdown'
            )
        
        # Clean up session
        self._sessions.pop(user_id, None)
    
    # --- Text Input Handlers (called by handle_session_input) ---
    
    async def _receive_area(
        self, update: Update, text: str, session: Dict[str, Any]
    ) -> None:
        """Receive the muscle group area."""
        session['area'] = text
        session['state'] = STATE_EXERCISE_NAME
        
        await update.message.reply_text(
            f"💪 *{text.title()}* day!\n\n"
            "What's your first exercise?",
            parse_mode='Markdown'
        )
    
    async def _receive_exercise_name(
        self, update: Update, text: str, session: Dict[str, Any]
    ) -> None:
        """Receive an exercise name and prepare for set logging."""
        session['current_exercise'] = {
            'name': text,
            'sets': [],
        }
        session['state'] = STATE_SET_DATA
        
        await update.message.reply_text(
            f"📝 *{text}* — enter weight and reps for each set\n"
            "_(e.g., `10x60`, `10 60`, or just `10` for bodyweight)_\n\n"
            "/next — move to next exercise\n"
            "/finish — end workout",
            parse_mode='Markdown'
        )
    
    async def _receive_set(
        self, update: Update, text: str, session: Dict[str, Any]
    ) -> None:
        """Receive and log a set (reps x weight)."""
        reps, weight = _parse_set_input(text)
        
        if reps is None:
            await update.message.reply_text(
                "❓ Couldn't parse that. Try:\n"
                "• `10x60` (10 reps × 60kg)\n"
                "• `10 60` (10 reps, 60kg)\n"
                "• `12` (12 reps, bodyweight)",
                parse_mode='Markdown'
            )
            return
        
        current = session['current_exercise']
        set_num = len(current['sets']) + 1
        
        current['sets'].append({
            'set': set_num,
            'reps': reps,
            'weight_kg': weight,
        })
        
        # Format weight display
        weight_str = f"{weight:g}kg" if weight > 0 else "BW"
        
        await update.message.reply_text(
            f"✅ Set {set_num}: {reps} reps × {weight_str}\n\n"
            "_Enter next set, /next for new exercise, or /finish to end_",
            parse_mode='Markdown'
        )
    
    # --- History Command ---
    
    @authorized_only
    async def _workouts_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /workouts — show recent workout history."""
        recent = self.manager.get_recent(5)
        
        if not recent:
            await update.message.reply_text(
                "📋 No workouts logged yet.\n"
                "Use /exercise to start your first workout!"
            )
            return
        
        total = self.manager.get_total_count()
        lines = [f"📋 *Recent Workouts* ({total} total)\n"]
        
        for w in recent:
            date = w.get('date', '?')
            area = w.get('area', '?').title()
            duration = w.get('duration_minutes', 0)
            num_exercises = len(w.get('exercises', []))
            total_sets = sum(len(e.get('sets', [])) for e in w.get('exercises', []))
            
            lines.append(
                f"• *{date}* — {area} "
                f"({num_exercises} exercises, {total_sets} sets, "
                f"{duration:.0f} min)"
            )
        
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode='Markdown'
        )
    
    # --- Helpers ---
    
    def _format_exercise_summary(self, exercise: Dict[str, Any]) -> str:
        """Format a single exercise into a readable summary."""
        sets = exercise.get('sets', [])
        set_strs = []
        for s in sets:
            reps = s.get('reps', 0)
            weight = s.get('weight_kg', 0)
            if weight > 0:
                set_strs.append(f"{reps}×{weight:g}kg")
            else:
                set_strs.append(f"{reps} reps")
        
        return " | ".join(set_strs)
    
    def _format_workout_summary(self, workout: Dict[str, Any]) -> str:
        """Format a workout record into a readable summary."""
        area = workout.get('area', '?').title()
        duration = workout.get('duration_minutes', 0)
        exercises = workout.get('exercises', [])
        
        lines = [
            f"📍 *Area:* {area}",
            f"⏱ *Duration:* {duration:.0f} min",
            f"🏋️ *Exercises:* {len(exercises)}",
            "",
        ]
        
        total_sets = 0
        total_volume = 0
        
        for ex in exercises:
            sets = ex.get('sets', [])
            total_sets += len(sets)
            
            set_strs = []
            for s in sets:
                reps = s.get('reps', 0)
                weight = s.get('weight_kg', 0)
                total_volume += reps * weight
                
                if weight > 0:
                    set_strs.append(f"{reps}×{weight:g}kg")
                else:
                    set_strs.append(f"{reps} reps")
            
            lines.append(f"*{ex['name']}:* {' | '.join(set_strs)}")
        
        lines.append("")
        lines.append(f"📊 *Total:* {total_sets} sets")
        if total_volume > 0:
            lines.append(f"📦 *Volume:* {total_volume:,.0f} kg")
        
        return "\n".join(lines)
    
    # --- Status ---
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the exercise automation."""
        status = super().get_status()
        status.update({
            "total_workouts": self.manager.get_total_count(),
            "active_sessions": len(self._sessions),
            "data_file": str(self.manager.data_file),
        })
        return status
