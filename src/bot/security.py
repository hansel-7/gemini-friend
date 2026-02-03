"""Security module for user authentication and authorization.

This module provides the core security layer that ensures only authorized
users can interact with the bot. Unauthorized access attempts are logged
but receive no response (silent rejection).
"""

from functools import wraps
from typing import Callable, Any

from telegram import Update
from telegram.ext import ContextTypes

import sys
sys.path.insert(0, str(__file__).replace('\\', '/').rsplit('/src/', 1)[0])

from config.settings import settings
from src.utils.logger import logger


def authorized_only(func: Callable) -> Callable:
    """Decorator that restricts handler to authorized users only.
    
    This decorator checks if the user's Telegram ID is in the allowed
    list before executing the handler. Unauthorized users are silently
    rejected (no response sent) to prevent information disclosure.
    
    Works with both standalone functions and class methods.
    
    Args:
        func: The handler function to wrap
        
    Returns:
        Wrapped function that checks authorization first
    """
    @wraps(func)
    async def wrapper(*args, **kwargs) -> Any:
        # Handle both standalone functions (update, context) 
        # and methods (self, update, context)
        if len(args) >= 2:
            # Check if first arg is Update or self
            if isinstance(args[0], Update):
                update = args[0]
            elif len(args) >= 2 and isinstance(args[1], Update):
                update = args[1]
            else:
                update = kwargs.get('update')
        else:
            update = kwargs.get('update')
        
        if update is None:
            logger.warning("Could not find Update object in handler arguments")
            return None
        
        user = update.effective_user
        
        if user is None:
            logger.warning("Received update without user information")
            return None
        
        user_id = user.id
        username = user.username or "unknown"
        full_name = user.full_name or "unknown"
        
        if user_id not in settings.ALLOWED_USER_IDS:
            # Log the unauthorized attempt with details
            logger.warning(
                f"UNAUTHORIZED ACCESS ATTEMPT | "
                f"User ID: {user_id} | "
                f"Username: @{username} | "
                f"Name: {full_name}"
            )
            # Silent rejection - do not respond to unauthorized users
            # This prevents them from knowing the bot is active
            return None
        
        # User is authorized, proceed with the handler
        logger.debug(f"Authorized request from user {user_id} (@{username})")
        return await func(*args, **kwargs)
    
    return wrapper


def get_user_info(update: Update) -> dict[str, Any]:
    """Extract user information from an update.
    
    Args:
        update: Telegram update object
        
    Returns:
        Dictionary containing user information
    """
    user = update.effective_user
    if user is None:
        return {"id": None, "username": None, "full_name": None}
    
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "language_code": user.language_code,
        "is_bot": user.is_bot,
    }
