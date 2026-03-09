"""Telegram bot message handlers.

This module contains all the handlers for different types of messages
and commands the bot can receive.
"""

import os
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import sys
sys.path.insert(0, str(__file__).replace('\\', '/').rsplit('/src/', 1)[0])

from src.bot.security import authorized_only, get_user_info
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.logger import logger
from src.utils.conversation import conversation_history
from src.scraper import scrape_url

# Initialize Gemini CLI wrapper
gemini = GeminiCLI.get_instance()

# Task automation reference (set by main.py after loading automations)
_tasks_automation = None
# Cron automation reference (set by main.py after loading automations)
_cron_automation = None
# Brain automation reference (set by main.py after loading automations)
_brain_automation = None
# Exercise automation reference (set by main.py after loading automations)
_exercise_automation = None


def set_tasks_automation(automation) -> None:
    """Set the tasks automation instance for natural language task detection.
    
    Called by main.py after loading automations.
    """
    global _tasks_automation
    _tasks_automation = automation
    if automation:
        logger.info("Natural language task detection enabled")


def set_cron_automation(automation) -> None:
    """Set the cron automation instance for natural language schedule detection.
    
    Called by main.py after loading automations.
    """
    global _cron_automation
    _cron_automation = automation
    if automation:
        logger.info("Natural language cron schedule detection enabled")


def set_brain_automation(automation) -> None:
    """Set the brain automation instance for event-driven triggers.
    
    Called by main.py after loading automations.
    """
    global _brain_automation
    _brain_automation = automation
    if automation:
        logger.info("Brain agent event triggers enabled")


def set_exercise_automation(automation) -> None:
    """Set the exercise automation instance for session routing.
    
    Called by main.py after loading automations.
    """
    global _exercise_automation
    _exercise_automation = automation
    if automation:
        logger.info("Exercise session routing enabled")


@authorized_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command.
    
    Sends a welcome message and confirms the user is authorized.
    """
    user_info = get_user_info(update)
    logger.info(f"Start command from authorized user: {user_info['id']}")
    
    welcome_message = (
        "👋 *Welcome to your Personal Assistant!*\n\n"
        "I'm connected to Gemini CLI and ready to help you with:\n"
        "• 📁 File management (workspace folder)\n"
        "• 🌐 Web browsing and research\n"
        "• 🖥️ Desktop automation\n"
        "• ☁️ Google Drive access\n\n"
        "Just send me a message and I'll process it through Gemini!\n\n"
        "Use /help to see available commands."
    )
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


@authorized_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command.
    
    Displays available commands and usage information.
    """
    help_text = (
        "📖 *Available Commands*\n\n"
        "*General:*\n"
        "/start - Welcome message\n"
        "/help - Show this help\n"
        "/status - Check Gemini CLI status\n"
        "/security - View security configuration\n"
        "/persona - Reload persona configuration\n\n"
        "*Tasks:*\n"
        "/task - Add a new task\n"
        "/tasks - List pending tasks\n"
        "/done - Mark task as complete\n"
        "/deltask - Delete a task\n"
        "/cleartasks - Clear completed tasks\n\n"
        "*Cron Jobs:*\n"
        "/cron - Show cron help\n"
        "/cron list - List all scheduled jobs\n"
        "/cron add \"<cron>\" <prompt> - Add a job\n"
        "/cron delete <id> - Delete a job\n"
        "Or just say: \"Every Monday at 9am, check the news\"\n\n"
        "*Web Scraping:*\n"
        "/scrape (url) - Scrape and summarize a webpage\n"
        "/scrape (url) (question) - Scrape and answer a question\n\n"
        "*Expenses:*\n"
        "/expense (amount) (description) - Add an expense\n"
        "/expense - Show today's expenses\n"
        "/expenses - Monthly summary\n"
        "/describe (id) (text) - Label a transaction\n"
        "/delexpense (id) - Delete an expense\n\n"
        "*Exercise:*\n"
        "/exercise - Start a workout session\n"
        "/next - Next exercise (during workout)\n"
        "/finish - End workout and save\n"
        "/workouts - View recent workout history\n\n"
        "*Context:*\n"
        "/context - Check context window usage\n"
        "/summarize - Summarize conversation\n"
        "/clear - Clear conversation history\n"
        "/clearall - Clear history AND summary\n"
        "/cancel - Cancel current operation\n\n"
        "*Natural Language:*\n"
        "• \"Remind me to call mom by Friday 8pm\"\n"
        "• \"Every weekday at 9am, summarize AI news\"\n\n"
        "*Voice:*\n"
        "🎤 Send a voice message — auto-transcribed and processed\n\n"
        "_Tasks and cron jobs can be created from natural language or voice._"
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')


@authorized_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command.
    
    Checks and reports the status of Gemini CLI.
    """
    await update.message.reply_text("🔍 Checking Gemini CLI status...")
    
    try:
        is_available = await gemini.check_status()
        if is_available:
            status_message = (
                "✅ *Gemini CLI Status: Online*\n\n"
                "• Gemini CLI is installed and accessible\n"
                "• MCP servers are configured\n"
                "• Ready to process requests"
            )
        else:
            status_message = (
                "⚠️ *Gemini CLI Status: Issues Detected*\n\n"
                "Gemini CLI may not be properly installed or authenticated.\n"
                "Please run `npx @google/gemini-cli` in a terminal to verify."
            )
    except Exception as e:
        logger.error(f"Error checking Gemini CLI status: {e}")
        status_message = f"❌ *Error checking status*\n\n{str(e)}"
    
    await update.message.reply_text(status_message, parse_mode='Markdown')


@authorized_only
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /cancel command.
    
    Cancels any ongoing operation.
    """
    # Cancel any running Gemini process
    gemini.cancel_current()
    await update.message.reply_text("🛑 Operation cancelled.")


@authorized_only
async def persona_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /persona command.
    
    Reloads the persona file and shows current status.
    """
    # Reload persona from file
    success = gemini.reload_persona()
    
    if success:
        await update.message.reply_text(
            "✅ *Persona Reloaded*\n\n"
            f"📄 Loaded from: `{gemini.PERSONA_FILE}`\n\n"
            "Your personal preferences and profile are now active. "
            "All future messages will use this persona configuration.\n\n"
            "💡 *Tip:* Edit the persona file directly and use /persona to reload.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "⚠️ *No Persona File Found*\n\n"
            f"Expected location: `{gemini.PERSONA_FILE}`\n\n"
            "Create a `persona.txt` file with your preferences to customize responses.\n\n"
            "The file should contain sections like:\n"
            "• User Profile (name, profession)\n"
            "• Communication Preferences\n"
            "• Technical Environment\n"
            "• Assistant Behavior rules",
            parse_mode='Markdown'
        )


@authorized_only
async def security_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /security command.
    
    Shows current security configuration and restrictions.
    """
    security_msg = (
        "🔒 *Security Configuration*\n\n"
        "*MCP Server Whitelist:* ✅ Enforced\n\n"
        "*Allowed MCP Servers:*\n"
        f"• `filesystem` → `{gemini.ALLOWED_DIR}`\n"
        "• `google-workspace` → Full Google Workspace access\n"
        "• `playwright` → web automation\n\n"
        "*Restrictions:*\n"
        "• Local file access ONLY in allowed directory\n"
        "• Google Workspace access via OAuth scopes\n"
        "• No system command execution\n"
        "• All other MCP servers are blocked\n\n"
        "*Flags:*\n"
        "• `--allowed-mcp-server-names` — Server whitelist enforced\n"
        "• `--yolo` — Auto-approve (restricted to allowed servers only)\n\n"
        "💡 Install Docker for additional `--sandbox` container isolation."
    )
    
    await update.message.reply_text(security_msg, parse_mode='Markdown')


@authorized_only
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clear command.
    
    Clears the conversation history.
    """
    if conversation_history.clear_history():
        await update.message.reply_text(
            "🗑️ Conversation history cleared!\n"
            "Starting fresh. (Summary preserved if any)"
        )
    else:
        await update.message.reply_text("❌ Failed to clear conversation history.")


@authorized_only
async def clearall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clearall command.
    
    Clears both conversation history and summary.
    """
    if conversation_history.clear_all():
        await update.message.reply_text(
            "🗑️ All conversation data cleared!\n"
            "History and summary both removed. Starting completely fresh."
        )
    else:
        await update.message.reply_text("❌ Failed to clear conversation data.")


@authorized_only
async def context_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /context command.
    
    Shows current context window usage.
    """
    size, percentage = conversation_history.get_context_size()
    
    # Create visual progress bar
    bar_length = 20
    filled = int(bar_length * percentage)
    bar = '█' * filled + '░' * (bar_length - filled)
    
    status_emoji = "✅" if percentage < 0.6 else "⚠️" if percentage < 0.8 else "🚨"
    
    context_msg = (
        f"{status_emoji} *Context Window Usage*\n\n"
        f"`[{bar}]` {percentage*100:.1f}%\n\n"
        f"📊 Size: {size:,} / {conversation_history.MAX_CONTEXT_CHARS:,} chars\n"
    )
    
    if percentage >= 0.8:
        context_msg += (
            "\n⚠️ *Warning: Context nearly full!*\n"
            "Use /summarize to compress history and continue."
        )
    
    await update.message.reply_text(context_msg, parse_mode='Markdown')


@authorized_only
async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /summarize command.
    
    Summarizes the conversation history to save context space.
    """
    await update.message.reply_text("📝 Generating conversation summary with Gemini...")
    
    try:
        # Get current history
        history = conversation_history.get_full_history()
        
        if len(history) < 500:
            await update.message.reply_text(
                "ℹ️ Conversation is too short to summarize.\n"
                "Keep chatting and summarize later when needed."
            )
            return
        
        # Ask Gemini to summarize with focus on personalization
        summarize_prompt = (
            "You are creating a PERSONAL MEMORY PROFILE for a user's AI assistant. "
            "Analyze the conversation history and extract information to help the AI remember and personalize future interactions.\n\n"
            
            "Create a structured summary with these sections:\n\n"
            
            "## USER PROFILE\n"
            "- Name, location, timezone (if mentioned)\n"
            "- Profession, role, or occupation\n"
            "- Technical skill level and expertise areas\n"
            "- Languages spoken\n\n"
            
            "## PREFERENCES & STYLE\n"
            "- Communication preferences (concise vs detailed, formal vs casual)\n"
            "- Preferred tools, frameworks, or technologies\n"
            "- Work habits and schedule patterns\n"
            "- How they like information presented\n\n"
            
            "## ONGOING PROJECTS & GOALS\n"
            "- Current projects being worked on\n"
            "- Short-term tasks and action items\n"
            "- Long-term goals mentioned\n"
            "- Problems they're trying to solve\n\n"
            
            "## IMPORTANT DECISIONS & CONTEXT\n"
            "- Key decisions made during conversations\n"
            "- Preferences expressed (e.g., 'I prefer X over Y')\n"
            "- Constraints or requirements mentioned\n"
            "- Things to remember for future reference\n\n"
            
            "## PERSONAL FACTS\n"
            "- Interests, hobbies, or personal details shared\n"
            "- Opinions or viewpoints expressed\n"
            "- Any other context that helps personalize interactions\n\n"
            
            "INSTRUCTIONS:\n"
            "- Only include information that was actually mentioned - don't make assumptions\n"
            "- Use bullet points for clarity\n"
            "- If a section has no relevant information, write 'Not mentioned yet'\n"
            "- Be thorough - this summary will be the AI's long-term memory of the user\n"
            "- Preserve specific details (names, dates, numbers) when relevant\n\n"
            
            f"CONVERSATION TO ANALYZE:\n{history}"
        )
        
        summary = await gemini.send_message(summarize_prompt)
        
        # Save the summary
        if conversation_history.save_summary(summary):
            size, percentage = conversation_history.get_context_size()
            await update.message.reply_text(
                "✅ *Conversation summarized successfully!*\n\n"
                f"💾 Summary saved to `conversation_summary.txt`\n"
                f"📁 History archived\n"
                f"📊 New context usage: {percentage*100:.1f}%\n\n"
                "Your conversation context is now optimized. "
                "Future messages will use the summary + new messages.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Failed to save summary. Please try again.")
            
    except Exception as e:
        logger.error(f"Error summarizing conversation: {e}")
        await update.message.reply_text(f"❌ Error generating summary: {str(e)}")


@authorized_only
async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /scrape command.
    
    Usage: /scrape <url> [optional question about the page]
    Scrapes the given URL and analyzes the content with Gemini.
    """
    user_info = get_user_info(update)
    raw_text = update.message.text or ""
    
    # Parse: /scrape <url> [question]
    parts = raw_text.split(None, 2)  # ['scrape', 'url', 'question...']
    
    if len(parts) < 2:
        await update.message.reply_text(
            "🔍 *Web Scraper*\n\n"
            "Usage: `/scrape <url> [question]`\n\n"
            "Examples:\n"
            "• `/scrape https://example.com`\n"
            "• `/scrape https://techcrunch.com/article Who raised funding?`",
            parse_mode='Markdown'
        )
        return
    
    url = parts[1]
    question = parts[2] if len(parts) > 2 else None
    
    logger.info(f"Scrape command from {user_info['id']}: {url}")
    
    # Send processing message
    processing_msg = await update.message.reply_text("🔍 Scraping page...")
    
    try:
        # Scrape the URL
        result = await scrape_url(url)
        
        if not result["success"]:
            await processing_msg.edit_text(
                f"❌ Scrape Failed\n\n{result['error']}"
            )
            return
        
        # Build prompt for Gemini
        if question:
            analysis_prompt = (
                f"I scraped the following webpage. Answer the user's question based on the content.\n\n"
                f"Page Title: {result['title']}\n"
                f"URL: {result['url']}\n\n"
                f"--- PAGE CONTENT ---\n{result['content']}\n--- END CONTENT ---\n\n"
                f"User's question: {question}"
            )
        else:
            analysis_prompt = (
                f"I scraped the following webpage. Provide a clear, structured summary of the key information.\n\n"
                f"Page Title: {result['title']}\n"
                f"URL: {result['url']}\n\n"
                f"--- PAGE CONTENT ---\n{result['content']}\n--- END CONTENT ---\n\n"
                f"Summarize the most important information from this page."
            )
        
        await processing_msg.edit_text("🧠 Analyzing content with Gemini...")
        
        # Use Gemini without MCP for fast text analysis
        response = await gemini.send_message(analysis_prompt, use_mcp=False)
        
        # Save to conversation history
        conversation_history.add_message('USER', f"[Scraped: {url}] {question or 'Summarize'}", user_info['id'])
        conversation_history.add_message('ASSISTANT', response)
        
        # Delete processing message and send response
        await processing_msg.delete()
        await send_long_message(update, response)
        
        logger.info(f"Successfully processed /scrape for {user_info['id']}")
        
    except Exception as e:
        logger.error(f"Error in scrape command: {e}")
        await processing_msg.edit_text(
            f"❌ Error scraping page:\n\n{str(e)}"
        )


async def _process_text_message(user_message: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Core message processing pipeline.
    
    Shared by handle_message (text) and handle_voice (transcribed audio).
    Checks for natural language task/cron requests, then forwards to Gemini CLI.
    """
    user_info = get_user_info(update)
    
    logger.info(f"Processing message from {user_info['id']}: {user_message[:50]}...")
    
    # Check for active exercise session (bypass Gemini entirely)
    if _exercise_automation and _exercise_automation.has_active_session(user_info['id']):
        logger.info("Routing to exercise session handler")
        await _exercise_automation.handle_session_input(update)
        return
    
    # Check for natural language cron schedule requests (check before tasks)
    if _cron_automation and _cron_automation.is_schedule_message(user_message):
        logger.info("Detected schedule-like message, attempting cron extraction...")
        
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action='typing'
        )
        
        try:
            job_created = await _cron_automation.create_job_from_natural_language(
                user_message, update
            )
            
            if job_created:
                conversation_history.add_message('USER', user_message, user_info['id'])
                conversation_history.add_message('ASSISTANT', f"[Cron job created from: {user_message}]")
                return
            
            logger.info("Cron extraction failed, falling back to task/chat")
            
        except Exception as e:
            logger.error(f"Error in cron extraction: {e}")
    
    # Check for natural language task requests
    if _tasks_automation and _tasks_automation.is_task_message(user_message):
        logger.info("Detected task-like message, attempting extraction...")
        
        # Send typing action
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action='typing'
        )
        
        try:
            # Get the extraction prompt
            extraction_prompt = _tasks_automation.get_extraction_prompt(user_message)
            
            # Ask Gemini to extract task details (no MCP needed - pure text parsing)
            # This skips MCP server initialization for much faster response (~15s vs ~4min)
            extraction_response = await gemini.send_message(extraction_prompt, use_mcp=False)
            
            # Try to create the task
            task_created = await _tasks_automation.create_task_from_parsed(
                extraction_response, 
                update
            )
            
            if task_created:
                # Task was created, we're done
                conversation_history.add_message('USER', user_message, user_info['id'])
                conversation_history.add_message('ASSISTANT', f"[Task created from: {user_message}]")
                return
            
            # If task extraction failed, fall through to normal chat
            logger.info("Task extraction failed, falling back to normal chat")
            
        except Exception as e:
            logger.error(f"Error in task extraction: {e}")
            # Fall through to normal chat
    
    # Save user message to conversation history
    conversation_history.add_message('USER', user_message, user_info['id'])
    
    # Notify brain agent of user message (event trigger)
    if _brain_automation:
        try:
            await _brain_automation.on_user_message(user_message)
        except Exception as e:
            logger.debug(f"Brain event trigger error: {e}")
    
    # Send typing action to show the bot is processing
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, 
        action='typing'
    )
    
    # Send a "processing" message
    processing_msg = await update.message.reply_text(
        "🔄 Processing your request with Gemini..."
    )
    
    try:
        # Get full conversation context (summary + history)
        context_history = conversation_history.get_context_for_gemini()
        
        # Get response from Gemini CLI (with context)
        response = await gemini.send_message(user_message, context=context_history)
        
        # Parse for image sending command (format: "SEND_IMAGE: path/to/image.png")
        image_to_send = None
        if "SEND_IMAGE:" in response:
            lines = response.split('\n')
            new_lines = []
            for line in lines:
                if "SEND_IMAGE:" in line:
                    # Extract path - handle both relative and absolute paths
                    path_str = line.split("SEND_IMAGE:", 1)[1].strip()
                    # If relative path, join with ALLOWED_DIR
                    if not os.path.isabs(path_str):
                        image_to_send = Path(gemini.ALLOWED_DIR) / path_str
                    else:
                        image_to_send = Path(path_str)
                else:
                    new_lines.append(line)
            response = '\n'.join(new_lines).strip()
        
        # Save assistant response to conversation history (without the command tag)
        conversation_history.add_message('ASSISTANT', response)
        
        # Delete the processing message
        await processing_msg.delete()
        
        # Send the response (handle long messages)
        await send_long_message(update, response)
        
        # Send image if requested
        if image_to_send:
            try:
                if image_to_send.exists():
                    logger.info(f"Sending image to user: {image_to_send}")
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='upload_photo')
                    with open(image_to_send, 'rb') as photo:
                        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo)
                else:
                    logger.warning(f"Image not found at {image_to_send}")
                    await update.message.reply_text(f"⚠️ Could not find image file: {image_to_send.name}")
            except Exception as e:
                logger.error(f"Error sending image: {e}")
                await update.message.reply_text(f"❌ Error sending image: {str(e)}")
        
        # Check if context is approaching limit
        is_near_limit, percentage = conversation_history.is_context_near_limit()
        if is_near_limit:
            await update.message.reply_text(
                f"⚠️ *Context Window Alert* ({percentage*100:.0f}% full)\n\n"
                "Your conversation history is getting long!\n\n"
                "👉 Send /summarize to compress the history and continue seamlessly.\n"
                "👉 Send /context to see detailed usage.\n"
                "👉 Send /clear to start fresh (keeps summary if any).",
                parse_mode='Markdown'
            )
        
        logger.info(f"Successfully processed message for {user_info['id']}")
        
    except TimeoutError:
        await processing_msg.edit_text(
            "⏱️ Request timed out. Gemini CLI took too long to respond.\n"
            "Try a simpler request or use /cancel if stuck."
        )
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await processing_msg.edit_text(
            f"❌ Error processing request:\n\n`{str(e)}`",
            parse_mode='Markdown'
        )


def _markdown_to_html(text: str) -> str:
    """Convert standard Markdown to Telegram HTML.
    
    Converts common Markdown syntax to HTML for reliable Telegram rendering.
    """
    import re
    
    # Escape HTML special chars first (except for our conversions)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    
    # Convert **bold** to <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    # Convert *italic* to <i>italic</i> (but not if it's a bullet point at start of line)
    text = re.sub(r'(?<!^)(?<!\n)\*(.+?)\*', r'<i>\1</i>', text)
    
    # Convert `code` to <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # Convert [text](url) to <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    return text


async def send_long_message(update: Update, text: str, max_length: int = 4000) -> None:
    """Send a long message, splitting if necessary.
    
    Telegram has a 4096 character limit per message. This function
    splits longer messages into chunks.
    
    Args:
        update: Telegram update object
        text: The text to send
        max_length: Maximum characters per message (default 4000 for safety)
    """
    if not text:
        await update.message.reply_text("(Empty response from Gemini)")
        return
    
    # Convert standard Markdown to Telegram HTML
    html_text = _markdown_to_html(text)
    
    # If message is short enough, send directly
    if len(html_text) <= max_length:
        try:
            await update.message.reply_text(html_text, parse_mode='HTML')
        except Exception:
            # Fallback to plain text if HTML is malformed
            await update.message.reply_text(text)
        return
    
    # Split into chunks
    chunks = []
    remaining = html_text
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break
        
        # Find a good split point (prefer newline, then space)
        split_point = remaining.rfind('\n', 0, max_length)
        if split_point == -1:
            split_point = remaining.rfind(' ', 0, max_length)
        if split_point == -1:
            split_point = max_length
        
        chunks.append(remaining[:split_point])
        remaining = remaining[split_point:].lstrip()
    
    # Send each chunk
    for i, chunk in enumerate(chunks, 1):
        prefix = f"📄 Part {i}/{len(chunks)}:\n\n" if len(chunks) > 1 else ""
        try:
            await update.message.reply_text(prefix + chunk, parse_mode='HTML')
        except Exception:
            # Fallback to plain text if HTML is malformed
            await update.message.reply_text(prefix + chunk)


@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages."""
    await _process_text_message(update.message.text, update, context)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors that occur during update processing."""
    logger.error(f"Update {update} caused error: {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An error occurred while processing your request. "
            "Please try again later."
        )


@authorized_only
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages.
    
    Downloads the voice file, transcribes via Groq Whisper,
    then routes the transcription through handle_message.
    """
    from groq import Groq
    from config.settings import settings
    
    user_info = get_user_info(update)
    logger.info(f"Processing voice message from {user_info['id']}")
    
    if not settings.GROQ_API_KEY:
        await update.message.reply_text(
            "❌ Voice transcription not configured. "
            "Set GROQ_API_KEY in .env to enable."
        )
        return
    
    try:
        # Show typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action='typing'
        )
        
        # Download voice file from Telegram
        voice = update.message.voice
        voice_file = await voice.get_file()
        
        # Save to temp file
        temp_path = Path(settings.DATA_DIR) / f"telegram_voice_{uuid.uuid4().hex[:8]}.ogg"
        await voice_file.download_to_drive(temp_path)
        
        logger.info(f"Voice file downloaded: {temp_path} ({voice.duration}s)")
        
        try:
            # Transcribe via Groq Whisper
            client = Groq(api_key=settings.GROQ_API_KEY)
            
            with open(temp_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3",
                    language="en",
                    temperature=0.0
                )
            
            text = transcription.text.strip()
            
            # Console logging
            logger.info(f"Voice transcription from {user_info['id']}: {text}")
            
            if not text:
                await update.message.reply_text("🎤 Couldn't understand the audio. Try again?")
                return
            
            # Show user the transcription
            await update.message.reply_text(f"🎤 I heard: \"{text}\"")
            
            # Route through the same message processing pipeline
            await _process_text_message(text, update, context)
            
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
                
    except Exception as e:
        logger.error(f"Voice handler error: {e}")
        await update.message.reply_text(f"❌ Error processing voice message: {str(e)}")


@authorized_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages.
    
    Downloads the image to the allowed directory. If caption contains 'save to X',
    saves to that subfolder. Otherwise, analyzes with Gemini CLI.
    """
    user_info = get_user_info(update)
    caption = update.message.caption or ""
    
    logger.info(f"Processing photo from {user_info['id']}: {caption[:50]}...")
    
    # Check if user wants to save to a specific folder
    save_mode = False
    target_subfolder = ""
    caption_lower = caption.lower()
    
    if "save to " in caption_lower or "save in " in caption_lower:
        save_mode = True
        if "save to " in caption_lower:
            target_subfolder = caption.split("save to ", 1)[-1].strip()
        else:
            target_subfolder = caption.split("save in ", 1)[-1].strip()
        
        # Sanitize the subfolder path (prevent directory traversal)
        target_subfolder = target_subfolder.replace("\\", "/")
        target_subfolder = "/".join(
            part for part in target_subfolder.split("/") 
            if part and part != ".." and part != "."
        )
    
    # Send typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action='typing'
    )
    
    # Determine target directory
    base_dir = Path(gemini.ALLOWED_DIR)
    if save_mode and target_subfolder:
        target_dir = base_dir / target_subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = base_dir
    
    # Generate unique filename
    image_id = uuid.uuid4().hex[:8]
    image_filename = f"telegram_image_{image_id}.jpg"
    image_path = target_dir / image_filename
    
    # Send processing message
    processing_msg = await update.message.reply_text(
        "🖼️ Downloading your image..."
    )
    
    try:
        # Get the largest photo (best quality)
        photo = update.message.photo[-1]
        
        # Download the photo directly to target location
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(str(image_path))
        
        logger.info(f"Image downloaded to: {image_path}")
        
        if save_mode:
            # Just save mode - don't analyze with Gemini
            relative_path = image_path.relative_to(base_dir)
            await processing_msg.edit_text(
                f"✅ *Image saved successfully!*\n\n"
                f"📄 `{image_filename}`\n"
                f"📁 `{gemini.ALLOWED_DIR}\\{relative_path}`",
                parse_mode='Markdown'
            )
            
            # Log to conversation history
            conversation_history.add_message(
                'USER', 
                f"[Saved photo: {image_filename} to {target_dir}]", 
                user_info['id']
            )
            conversation_history.add_message(
                'ASSISTANT', 
                f"Image saved to {image_path}"
            )
            
            logger.info(f"Saved photo for {user_info['id']} to {image_path}")
            
        else:
            # Analyze mode - keep image in root and ask Gemini to analyze
            conversation_history.add_message('USER', f"[Photo] {caption or 'What is in this image?'}", user_info['id'])
            
            await processing_msg.edit_text("🖼️ Analyzing your image with Gemini...")
            
            # Build prompt for Gemini CLI to analyze the image via filesystem MCP
            analysis_caption = caption if caption else "What is in this image?"
            image_prompt = (
                f"I've sent you an image file. Please read and analyze the image at: "
                f"'{image_path}'\n\n"
                f"User's question about the image: {analysis_caption}\n\n"
                f"First read the image file, then provide a detailed response to the user's question."
            )
            
            # Get full conversation context
            context_history = conversation_history.get_context_for_gemini()
            
            # Use Gemini CLI with MCP to analyze (filesystem server can read the image)
            response = await gemini.send_message(image_prompt, context=context_history, use_mcp=True)
            
            # Save assistant response
            conversation_history.add_message('ASSISTANT', response)
            
            # Delete processing message
            await processing_msg.delete()
            
            # Send response
            await send_long_message(update, response)
            
            logger.info(f"Successfully processed photo for {user_info['id']}")
            
            # Clean up the image file after analysis
            try:
                if image_path.exists():
                    image_path.unlink()
                    logger.debug(f"Cleaned up temp image: {image_path}")
            except Exception as e:
                logger.warning(f"Could not clean up temp image: {e}")
        
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await processing_msg.edit_text(
            f"❌ Error processing image:\n\n`{str(e)}`",
            parse_mode='Markdown'
        )



@authorized_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document/file uploads.
    
    Downloads the file and saves it to a user-specified folder within the allowed directory.
    Usage: Send a file with caption like "save to Work/Reports" or just send without caption
    to save to the root allowed directory.
    """
    user_info = get_user_info(update)
    caption = update.message.caption or ""
    document = update.message.document
    
    if not document:
        await update.message.reply_text("❌ No document found in message.")
        return
    
    original_filename = document.file_name or f"file_{uuid.uuid4().hex[:8]}"
    logger.info(f"Processing document from {user_info['id']}: {original_filename}")
    
    # Parse target folder from caption
    # Formats: "save to folder/subfolder", "folder/path", or empty for root
    target_subfolder = ""
    if caption:
        # Check for "save to X" pattern
        caption_lower = caption.lower()
        if "save to " in caption_lower:
            target_subfolder = caption.split("save to ", 1)[-1].strip()
        elif "save in " in caption_lower:
            target_subfolder = caption.split("save in ", 1)[-1].strip()
        else:
            # Treat entire caption as folder path if it looks like a path
            if "/" in caption or "\\" in caption or not " " in caption:
                target_subfolder = caption.strip()
    
    # Sanitize the subfolder path (prevent directory traversal)
    target_subfolder = target_subfolder.replace("\\", "/")
    target_subfolder = "/".join(
        part for part in target_subfolder.split("/") 
        if part and part != ".." and part != "."
    )
    
    # Build the full target path
    base_dir = Path(gemini.ALLOWED_DIR)
    if target_subfolder:
        target_dir = base_dir / target_subfolder
    else:
        target_dir = base_dir
    
    # Create directory if it doesn't exist
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Full file path
    file_path = target_dir / original_filename
    
    # Handle filename conflicts
    if file_path.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while file_path.exists():
            file_path = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    
    # Send processing message
    processing_msg = await update.message.reply_text(
        f"📥 Downloading `{original_filename}`...",
        parse_mode='Markdown'
    )
    
    try:
        # Download the file
        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(str(file_path))
        
        logger.info(f"Document saved to: {file_path}")
        
        # Success message
        relative_path = file_path.relative_to(base_dir)
        await processing_msg.edit_text(
            f"✅ *File saved successfully!*\n\n"
            f"📄 `{original_filename}`\n"
            f"📁 `{gemini.ALLOWED_DIR}\\{relative_path}`\n"
            f"💾 Size: {document.file_size:,} bytes",
            parse_mode='Markdown'
        )
        
        # Log to conversation history
        conversation_history.add_message(
            'USER', 
            f"[Uploaded file: {original_filename} to {target_dir}]", 
            user_info['id']
        )
        conversation_history.add_message(
            'ASSISTANT', 
            f"File saved to {file_path}"
        )
        
    except Exception as e:
        logger.error(f"Error saving document: {e}")
        await processing_msg.edit_text(
            f"❌ Error saving file:\n\n`{str(e)}`",
            parse_mode='Markdown'
        )

