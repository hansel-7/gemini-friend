"""Gaming News Scraper

Fetches latest news from gaming industry websites via RSS feeds.
Run standalone to test: python src/automations/news/scraper.py
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict
from pathlib import Path
import xml.etree.ElementTree as ET
import re

import httpx

# RSS feeds for all sources
FEEDS = {
    "gamesindustry": "https://www.gamesindustry.biz/feed",
    "mobilegamer": "https://mobilegamer.biz/feed",
    "pocketgamer": "https://www.pocketgamer.biz/rss",
    "gamedeveloper": "https://www.gamedeveloper.com/rss.xml",
}

# Data directory for news archives and state (outside of code repo)
NEWS_DATA_DIR = Path("D:/Gemini CLI/News")
NEWS_DATA_DIR.mkdir(parents=True, exist_ok=True)

# File to track seen articles (prevents duplicates across days)
SEEN_ARTICLES_FILE = NEWS_DATA_DIR / "seen_articles.json"


@dataclass
class NewsArticle:
    """Represents a single news article."""
    title: str
    link: str
    source: str
    published: Optional[str] = None
    summary: Optional[str] = None


class SeenArticlesTracker:
    """Tracks which articles have been sent to avoid duplicates.
    
    Stores article links with timestamps, auto-cleans entries older than retention_days.
    """
    
    def __init__(self, retention_days: int = 7):
        self.retention_days = retention_days
        self.seen: Dict[str, str] = {}  # link -> timestamp ISO format
        self._load()
    
    def _load(self) -> None:
        """Load seen articles from disk."""
        try:
            if SEEN_ARTICLES_FILE.exists():
                with open(SEEN_ARTICLES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.seen = data.get('seen', {})
                    self._cleanup_old()
        except Exception as e:
            print(f"Warning: Could not load seen articles: {e}")
            self.seen = {}
    
    def _save(self) -> None:
        """Save seen articles to disk."""
        try:
            with open(SEEN_ARTICLES_FILE, 'w', encoding='utf-8') as f:
                json.dump({'seen': self.seen}, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save seen articles: {e}")
    
    def _cleanup_old(self) -> None:
        """Remove entries older than retention_days."""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        to_remove = []
        for link, timestamp in self.seen.items():
            try:
                if datetime.fromisoformat(timestamp) < cutoff:
                    to_remove.append(link)
            except:
                to_remove.append(link)  # Invalid timestamp, remove it
        
        for link in to_remove:
            del self.seen[link]
    
    def is_seen(self, link: str) -> bool:
        """Check if an article has already been sent."""
        return link in self.seen
    
    def mark_seen(self, links: List[str]) -> None:
        """Mark articles as seen."""
        now = datetime.now().isoformat()
        for link in links:
            self.seen[link] = now
        self._save()
    
    def filter_new(self, articles: List['NewsArticle']) -> List['NewsArticle']:
        """Filter out articles that have already been seen."""
        return [a for a in articles if not self.is_seen(a.link)]


class NewsScraper:
    """Scrapes gaming news from multiple sources."""
    
    def __init__(self, max_articles_per_source: int = 50, track_seen: bool = True):
        self.max_articles = max_articles_per_source
        self.track_seen = track_seen
        self.seen_tracker = SeenArticlesTracker() if track_seen else None
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,  # Important for MobileGamer redirect
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
    
    async def close(self):
        await self.client.aclose()
    
    async def fetch_all(self, filter_seen: bool = False) -> List[NewsArticle]:
        """Fetch news from all sources.
        
        Args:
            filter_seen: If True, exclude articles that have been previously sent
        """
        tasks = [
            self._fetch_rss(source, url) 
            for source, url in FEEDS.items()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        articles = []
        for result in results:
            if isinstance(result, Exception):
                print(f"Error fetching source: {result}")
            else:
                articles.extend(result)
        
        # Filter out seen articles if requested
        if filter_seen and self.seen_tracker:
            original_count = len(articles)
            articles = self.seen_tracker.filter_new(articles)
            filtered_count = original_count - len(articles)
            if filtered_count > 0:
                print(f"Filtered out {filtered_count} previously seen articles")
        
        return articles
    
    async def fetch_new_for_digest(self) -> List[NewsArticle]:
        """Fetch only new articles for daily digest, then mark them as seen.
        
        This is the main method to use for daily digests - it:
        1. Fetches all articles
        2. Filters out previously sent ones
        3. Marks the new ones as seen for next time
        """
        articles = await self.fetch_all(filter_seen=True)
        
        # Mark these articles as seen so they won't appear in tomorrow's digest
        if articles and self.seen_tracker:
            self.seen_tracker.mark_seen([a.link for a in articles])
            print(f"Marked {len(articles)} articles as seen")
        
        return articles
    
    async def _fetch_rss(self, source: str, url: str) -> List[NewsArticle]:
        """Fetch articles from an RSS feed."""
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            
            # Parse RSS XML
            root = ET.fromstring(response.text)
            articles = []
            
            # Handle both RSS 2.0 and Atom formats
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            
            for item in items[:self.max_articles]:
                # RSS 2.0 format
                title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title")
                link = item.findtext("link") or item.findtext("{http://www.w3.org/2005/Atom}link")
                if link is None:
                    link_elem = item.find("{http://www.w3.org/2005/Atom}link")
                    if link_elem is not None:
                        link = link_elem.get("href")
                
                pub_date = item.findtext("pubDate") or item.findtext("{http://www.w3.org/2005/Atom}published")
                description = item.findtext("description") or item.findtext("{http://www.w3.org/2005/Atom}summary")
                
                # Clean up description (remove HTML tags)
                if description:
                    description = re.sub(r'<[^>]+>', '', description)
                    description = description[:300] + "..." if len(description) > 300 else description
                
                if title and link:
                    articles.append(NewsArticle(
                        title=title.strip(),
                        link=link.strip(),
                        source=source,
                        published=pub_date,
                        summary=description.strip() if description else None
                    ))
            
            print(f"✓ {source}: {len(articles)} articles")
            return articles
            
        except Exception as e:
            print(f"✗ {source}: {e}")
            return []


async def main():
    """Test the scraper and output JSON."""
    print("=" * 50)
    print("Gaming News Scraper - Test Run")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()
    
    scraper = NewsScraper()  # Uses default of 50 per source
    
    try:
        # Use --digest flag to simulate daily digest behavior
        import sys
        use_digest = '--digest' in sys.argv
        
        if use_digest:
            print("Mode: DIGEST (filtering seen articles, will mark as seen)")
            articles = await scraper.fetch_new_for_digest()
        else:
            print("Mode: ALL (no filtering, won't mark as seen)")
            articles = await scraper.fetch_all(filter_seen=False)
        
        print()
        print(f"Total articles: {len(articles)}")
        print()
        
        if not articles:
            print("No new articles to show!")
            return
        
        # Convert to JSON-friendly format
        output = {
            "fetched_at": datetime.now().isoformat(),
            "total_articles": len(articles),
            "mode": "digest" if use_digest else "all",
            "articles": [asdict(a) for a in articles]
        }
        
        # Save to file with date stamp
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_file = NEWS_DATA_DIR / f"news_{date_str}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"Saved to: {output_file}")
        print()
        
        # Preview first few articles
        print("Preview (first 3 articles):")
        print("-" * 40)
        for article in articles[:3]:
            print(f"[{article.source}] {article.title}")
            print(f"  → {article.link}")
            if article.summary:
                print(f"  {article.summary[:100]}...")
            print()
        
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
