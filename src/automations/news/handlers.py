"""Telegram handlers for news automation."""

from typing import Dict, Any, List

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.base import BaseAutomation
from src.automations.news.scheduler import NewsScheduler
from src.automations.news.scraper import NewsArticle
from src.automations.news.summarizer import summarize_articles
from src.bot.security import authorized_only
from src.utils.logger import logger
from config.settings import settings


class NewsAutomation(BaseAutomation):
    """News digest automation with Gemini summarization."""
    
    name = "news"
    description = "Daily gaming news digest with AI summarization"
    version = "1.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        super().__init__(application, config)
        
        # Store bot reference for sending messages
        self._bot = None
        
        # Initialize scheduler
        self.scheduler = NewsScheduler(
            send_message=self._send_message,
            summarize_with_gemini=self._summarize_articles,
            digest_hour=config.get('digest_hour', 7),
            digest_minute=config.get('digest_minute', 0),
            check_interval=config.get('check_interval', 60),
            send_on_startup=config.get('send_on_startup', False),
            max_articles_per_source=config.get('max_articles_per_source', 50),
        )
    
    def register_handlers(self) -> None:
        """Register news-related command handlers."""
        handlers = [
            CommandHandler("news", self._news_command),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
            self._handlers.append(handler)
        
        logger.info(f"Registered {len(handlers)} news command handlers")
    
    async def start(self) -> None:
        """Start the news scheduler."""
        await super().start()
        self._bot = self.application.bot
        await self.scheduler.start()
    
    async def stop(self) -> None:
        """Stop the news scheduler."""
        await self.scheduler.stop()
        await super().stop()
    
    async def _send_message(self, message: str) -> None:
        """Send a message to all authorized users."""
        if not self._bot:
            logger.error("News: Bot not initialized")
            return
        
        for user_id in settings.ALLOWED_USER_IDS:
            try:
                await self._bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"News: Sent digest to user {user_id}")
            except Exception as e:
                logger.error(f"News: Failed to send to {user_id}: {e}")
    
    async def _summarize_articles(self, articles: List[NewsArticle]) -> str:
        """Summarize articles using Gemini."""
        return await summarize_articles(articles)
    
    @authorized_only
    async def _news_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /news command to trigger a manual news digest.
        
        Usage: /news
        """
        await update.message.reply_text(
            "📰 *Fetching news digest...*\n\n"
            "_This may take a moment while Gemini summarizes the articles._",
            parse_mode='Markdown'
        )
        
        # Trigger the digest
        await self.scheduler.send_digest_now()
