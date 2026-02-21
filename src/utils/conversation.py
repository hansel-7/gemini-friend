"""Conversation history manager.

This module handles saving and loading conversation history for context.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import threading

import sys
sys.path.insert(0, str(__file__).replace('\\', '/').rsplit('/src/', 1)[0])

from src.utils.logger import logger


class ConversationHistory:
    """Manages conversation history persistence."""
    
    # Context window limits (in characters)
    # Gemini has ~1M tokens. Using 1M chars (~250k tokens) for generous context.
    MAX_CONTEXT_CHARS = 1000000
    WARNING_THRESHOLD = 0.80  # Warn at 80% capacity
    ARCHIVE_DIR = Path("D:/Gemini CLI/Archive")
    
    def __init__(self, history_file: str = "D:/Gemini CLI/conversation.txt"):
        """Initialize the conversation history manager.
        
        Args:
            history_file: Path to the conversation history file
        """
        self.history_file = Path(history_file)
        self.summary_file = self.history_file.parent / "conversation_summary.txt"
        self._lock = threading.Lock()
        
        # Ensure directories and files exist
        self.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        if not self.history_file.exists():
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            self.history_file.write_text(
                "# Conversation History\n"
                "# Format: [TIMESTAMP] USER/ASSISTANT: message\n\n"
            )
    
    def add_message(self, role: str, message: str, user_id: Optional[int] = None) -> None:
        """Add a message to the conversation history.
        
        Args:
            role: Either 'USER' or 'ASSISTANT'
            message: The message content
            user_id: Optional user ID for tracking
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Clean up the message (remove excessive newlines, etc.)
        message_clean = message.strip().replace('\n', '\n    ')  # Indent continuation lines
        
        # Format the entry
        if user_id:
            entry = f"[{timestamp}] {role} ({user_id}): {message_clean}\n\n"
        else:
            entry = f"[{timestamp}] {role}: {message_clean}\n\n"
        
        # Thread-safe file append
        with self._lock:
            try:
                with open(self.history_file, 'a', encoding='utf-8') as f:
                    f.write(entry)
                logger.debug(f"Saved {role} message to history")
            except Exception as e:
                logger.error(f"Failed to save message to history: {e}")
    
    def get_context_size(self) -> Tuple[int, float]:
        """Get the current context size and usage percentage.
        
        Returns:
            Tuple of (character count, usage percentage 0-1)
        """
        try:
            content = self.get_full_history()
            summary = self.get_summary()
            total_size = len(content) + len(summary)
            percentage = total_size / self.MAX_CONTEXT_CHARS
            return total_size, percentage
        except Exception as e:
            logger.error(f"Failed to get context size: {e}")
            return 0, 0.0
    
    def is_context_near_limit(self) -> Tuple[bool, float]:
        """Check if context is approaching the limit.
        
        Returns:
            Tuple of (is_near_limit, current_percentage)
        """
        _, percentage = self.get_context_size()
        return percentage >= self.WARNING_THRESHOLD, percentage
    
    def get_recent_context(self, num_exchanges: int = 10) -> str:
        """Get recent conversation context for Gemini.
        
        Args:
            num_exchanges: Number of recent message exchanges to include
            
        Returns:
            Formatted conversation context string
        """
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Split into individual messages (separated by double newlines)
            lines = content.strip().split('\n\n')
            
            # Filter out header comments
            messages = [l for l in lines if l.startswith('[')]
            
            # Get the last N messages
            recent = messages[-(num_exchanges * 2):]  # *2 for user+assistant pairs
            
            if not recent:
                return ""
            
            return "\n".join(recent)
            
        except Exception as e:
            logger.error(f"Failed to read conversation history: {e}")
            return ""
    
    def get_full_history(self) -> str:
        """Get the full conversation history.
        
        Returns:
            Complete conversation history as string
        """
        try:
            return self.history_file.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to read full history: {e}")
            return ""
    
    def get_summary(self) -> str:
        """Get the saved conversation summary.
        
        Returns:
            The conversation summary, or empty string if none exists
        """
        try:
            if self.summary_file.exists():
                return self.summary_file.read_text(encoding='utf-8')
            return ""
        except Exception as e:
            logger.error(f"Failed to read summary: {e}")
            return ""
    
    def _archive_current(self, reason: str = "manual") -> bool:
        """Archive the current conversation history before clearing.
        
        Args:
            reason: Why the archive is being created (e.g. 'summarized', 'cleared')
            
        Returns:
            True if successful, False otherwise
        """
        try:
            content = self.get_full_history()
            # Skip if there's nothing meaningful to archive
            messages = [l for l in content.strip().split('\n\n') if l.startswith('[')]
            if not messages:
                return True
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = self.ARCHIVE_DIR / f"conversation_{timestamp}_{reason}.txt"
            archive_file.write_text(content, encoding='utf-8')
            logger.info(f"Archived conversation to {archive_file.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to archive conversation: {e}")
            return False
    
    def save_summary(self, summary: str) -> bool:
        """Save a conversation summary and clear the history.
        
        The summary will be prepended to future context, and the
        detailed history will be archived/cleared.
        
        Args:
            summary: The summary text to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with self._lock:
                # Archive before clearing
                self._archive_current(reason="summarized")
                
                # Append to existing summary if any
                existing_summary = self.get_summary()
                if existing_summary:
                    new_summary = (
                        f"{existing_summary}\n\n"
                        f"--- Summary Update ({timestamp}) ---\n"
                        f"{summary}"
                    )
                else:
                    new_summary = (
                        f"# Conversation Summary\n"
                        f"# Generated: {timestamp}\n\n"
                        f"{summary}"
                    )
                
                # Save the new summary
                self.summary_file.write_text(new_summary, encoding='utf-8')
                
                # Clear the main history but note the summarization
                self.history_file.write_text(
                    "# Conversation History\n"
                    "# Format: [TIMESTAMP] USER/ASSISTANT: message\n"
                    f"# Previous history summarized on: {timestamp}\n"
                    f"# See: conversation_summary.txt for context\n\n"
                )
                
            logger.info(f"Saved conversation summary and archived history")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save summary: {e}")
            return False
    
    def get_context_for_gemini(self) -> str:
        """Get the complete context for Gemini (summary + recent history).
        
        Returns:
            Combined context string optimized for Gemini
        """
        summary = self.get_summary()
        history = self.get_full_history()
        
        if summary:
            return f"=== PREVIOUS CONVERSATION SUMMARY ===\n{summary}\n\n=== RECENT CONVERSATION ===\n{history}"
        else:
            return history
    
    def clear_history(self) -> bool:
        """Clear the conversation history (archives first).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._lock:
                # Archive before clearing
                self._archive_current(reason="cleared")
                
                self.history_file.write_text(
                    "# Conversation History\n"
                    "# Format: [TIMESTAMP] USER/ASSISTANT: message\n"
                    f"# Cleared on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                )
            logger.info("Conversation history cleared (archived first)")
            return True
        except Exception as e:
            logger.error(f"Failed to clear history: {e}")
            return False
    
    def clear_all(self) -> bool:
        """Clear both history and summary (archives first).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # clear_history already archives
            self.clear_history()
            if self.summary_file.exists():
                self.summary_file.unlink()
            logger.info("Cleared all conversation data (history + summary)")
            return True
        except Exception as e:
            logger.error(f"Failed to clear all: {e}")
            return False


# Create singleton instance
conversation_history = ConversationHistory()
