"""Base class for all automations.

All automation plugins should inherit from BaseAutomation and implement
the required methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from telegram.ext import Application, BaseHandler


class BaseAutomation(ABC):
    """Base class that all automations must inherit from.
    
    Provides a consistent interface for:
    - Registering Telegram command handlers
    - Starting/stopping background tasks
    - Configuration management
    """
    
    # Override these in subclasses
    name: str = "unnamed"
    description: str = "No description provided"
    version: str = "1.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        """Initialize the automation.
        
        Args:
            application: Telegram Application instance
            config: Configuration dictionary for this automation
        """
        self.application = application
        self.config = config
        self._handlers: List[BaseHandler] = []
        self._running = False
    
    @abstractmethod
    def register_handlers(self) -> None:
        """Register Telegram command/message handlers.
        
        Override this method to add handlers using:
            self.application.add_handler(handler)
            self._handlers.append(handler)  # Track for cleanup
        """
        pass
    
    async def start(self) -> None:
        """Start any background tasks (schedulers, etc).
        
        Override this method if your automation needs background processing.
        Called after all handlers are registered.
        """
        self._running = True
    
    async def stop(self) -> None:
        """Clean shutdown of the automation.
        
        Override this method to clean up resources, stop schedulers, etc.
        """
        self._running = False
    
    @property
    def is_running(self) -> bool:
        """Check if the automation is currently running."""
        return self._running
    
    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the automation.
        
        Override to provide additional status information.
        
        Returns:
            Dictionary with status information
        """
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "running": self._running,
            "config": {k: v for k, v in self.config.items() if k != 'enabled'}
        }
