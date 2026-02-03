"""Personal Assistant Telegram Bot - Main Entry Point.

This module initializes and runs the Telegram bot that connects to Gemini CLI.
Run this script to start the bot.
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config.settings import settings
from src.bot.handlers import (
    start_command,
    help_command,
    status_command,
    persona_command,
    security_command,
    cancel_command,
    clear_command,
    clearall_command,
    context_command,
    summarize_command,
    handle_message,
    handle_photo,
    error_handler,
    set_tasks_automation
)
from src.automations import load_automations, start_automations, stop_automations
from src.utils.logger import logger

# Global list of loaded automations for cleanup
_loaded_automations = []


async def post_init(application: Application) -> None:
    """Called after the application is initialized.
    
    Starts all automation background tasks.
    """
    global _loaded_automations
    await start_automations(_loaded_automations)
    logger.info(f"Started {len(_loaded_automations)} automation(s)")


async def post_shutdown(application: Application) -> None:
    """Called when the application is shutting down.
    
    Stops all automation background tasks.
    """
    global _loaded_automations
    await stop_automations(_loaded_automations)
    logger.info("All automations stopped")


def main() -> None:
    """Initialize and run the Telegram bot."""
    global _loaded_automations
    
    # Validate settings
    errors = settings.validate()
    if errors:
        for error in errors:
            logger.error(error)
        logger.error("Please check your .env file and try again.")
        sys.exit(1)
    
    logger.info("=" * 50)
    logger.info("Personal Assistant Bot Starting...")
    logger.info("=" * 50)
    logger.info(f"Allowed User IDs: {settings.ALLOWED_USER_IDS}")
    logger.info(f"Gemini CLI Command: {settings.GEMINI_CLI_COMMAND}")
    logger.info(f"Timeout: {settings.GEMINI_TIMEOUT}s")
    
    # Create the Application with post_init and post_shutdown hooks
    application = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("persona", persona_command))
    application.add_handler(CommandHandler("security", security_command))
    application.add_handler(CommandHandler("context", context_command))
    application.add_handler(CommandHandler("summarize", summarize_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("clearall", clearall_command))
    
    # Add message handler (for all text messages that aren't commands)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    
    # Add photo handler
    application.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Load automations (handlers registered here, background tasks start in post_init)
    _loaded_automations = load_automations(application)
    logger.info(f"Loaded {len(_loaded_automations)} automation(s)")
    
    # Wire up tasks automation for natural language detection
    for automation in _loaded_automations:
        if automation.name == "tasks":
            set_tasks_automation(automation)
            break
    
    # Start the bot
    logger.info("Bot is now running! Press Ctrl+C to stop.")
    logger.info("Send /start to your bot on Telegram to begin.")
    
    # Run the bot until Ctrl+C is pressed
    application.run_polling(allowed_updates=['message'])


if __name__ == '__main__':
    main()
