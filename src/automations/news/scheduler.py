"""News Digest Scheduler.

Sends a daily digest of gaming industry news with Gemini summarization.
"""

import asyncio
from datetime import datetime
from typing import Callable, Optional, Awaitable, List
from pathlib import Path

from src.utils.logger import logger
from src.automations.news.scraper import NewsScraper, NewsArticle, NEWS_DATA_DIR

# State file to track when we last sent a digest
NEWS_STATE_FILE = NEWS_DATA_DIR / "news_scheduler_state.json"


class NewsScheduler:
    """Scheduler for daily news digests."""
    
    def __init__(
        self,
        send_message: Callable[[str], Awaitable[None]],
        summarize_with_gemini: Callable[[List[NewsArticle]], Awaitable[str]],
        digest_hour: int = 7,
        digest_minute: int = 0,
        check_interval: int = 60,
        send_on_startup: bool = False,  # For testing: send immediately on startup
    ):
        """Initialize the news scheduler.
        
        Args:
            send_message: Callback to send a message to the user
            summarize_with_gemini: Callback to summarize articles with Gemini
            digest_hour: Hour to send daily digest (0-23)
            digest_minute: Minute to send daily digest (0-59)
            check_interval: Seconds between checks
            send_on_startup: If True, send digest immediately on startup (for testing)
        """
        self.send_message = send_message
        self.summarize_with_gemini = summarize_with_gemini
        self.digest_hour = digest_hour
        self.digest_minute = digest_minute
        self.check_interval = check_interval
        self.send_on_startup = send_on_startup
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_digest_date: Optional[datetime] = None
        self._startup_digest_sent = False
        
        self._load_state()
    
    def _load_state(self) -> None:
        """Load scheduler state from disk."""
        try:
            import json
            if NEWS_STATE_FILE.exists():
                with open(NEWS_STATE_FILE, 'r') as f:
                    data = json.load(f)
                    if data.get('last_digest_date'):
                        self._last_digest_date = datetime.fromisoformat(data['last_digest_date'])
                        logger.debug(f"News: Loaded last digest date: {self._last_digest_date}")
        except Exception as e:
            logger.warning(f"News: Could not load state: {e}")
    
    def _save_state(self) -> None:
        """Save scheduler state to disk."""
        try:
            import json
            data = {
                'last_digest_date': self._last_digest_date.isoformat() if self._last_digest_date else None
            }
            with open(NEWS_STATE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"News: Could not save state: {e}")
    
    async def start(self) -> None:
        """Start the news scheduler."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("News scheduler started")
    
    async def stop(self) -> None:
        """Stop the news scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("News scheduler stopped")
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop."""
        # Handle startup digest for testing
        if self.send_on_startup and not self._startup_digest_sent:
            logger.info("News: Sending startup digest (testing mode)")
            await asyncio.sleep(5)  # Small delay for bot to fully initialize
            await self._send_digest()
            self._startup_digest_sent = True
        
        while self._running:
            try:
                await self._check_digest_time()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"News scheduler error: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _check_digest_time(self) -> None:
        """Check if it's time to send the daily digest."""
        now = datetime.now()
        
        # Check if we already sent today
        if self._last_digest_date and self._last_digest_date.date() == now.date():
            return
        
        # Check if it's the right time
        if now.hour == self.digest_hour and now.minute >= self.digest_minute:
            # Within a 10-minute window
            if now.minute <= self.digest_minute + 10:
                await self._send_digest()
    
    async def _send_digest(self) -> None:
        """Fetch news and send the digest."""
        logger.info("News: Preparing daily digest...")
        
        scraper = NewsScraper()
        try:
            # Fetch only NEW articles (not seen before)
            articles = await scraper.fetch_new_for_digest()
            
            if not articles:
                # No new articles
                await self.send_message(
                    "📰 **Daily Gaming News Digest**\n\n"
                    "No new articles today! You're all caught up. 🎮"
                )
                logger.info("News: No new articles to report")
            else:
                # Summarize with Gemini
                logger.info(f"News: Summarizing {len(articles)} articles with Gemini...")
                summary = await self.summarize_with_gemini(articles)
                
                # Send the digest
                message = (
                    f"📰 **Daily Gaming News Digest**\n"
                    f"*{len(articles)} new articles from {len(set(a.source for a in articles))} sources*\n\n"
                    f"{summary}"
                )
                await self.send_message(message)
                logger.info(f"News: Sent digest with {len(articles)} articles")
            
            # Update state
            self._last_digest_date = datetime.now()
            self._save_state()
            
        except Exception as e:
            logger.error(f"News: Error sending digest: {e}")
            await self.send_message(f"❌ Error fetching news digest: {str(e)}")
        finally:
            await scraper.close()
    
    async def send_digest_now(self) -> None:
        """Manually trigger a digest (for testing or on-demand)."""
        await self._send_digest()
