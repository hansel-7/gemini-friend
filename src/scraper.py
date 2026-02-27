"""Web scraper module using Scrapling.

Provides URL scraping with automatic fallback from fast HTTP
to stealth browser mode for anti-bot protected sites.
"""

import re
from typing import Dict, Any
from urllib.parse import urlparse

from src.utils.logger import logger

# Maximum content length to pass to Gemini (keep well within context limits)
MAX_CONTENT_CHARS = 15000


def _is_valid_url(url: str) -> bool:
    """Check if a string is a valid HTTP/HTTPS URL."""
    try:
        result = urlparse(url)
        return result.scheme in ('http', 'https') and bool(result.netloc)
    except Exception:
        return False


def _extract_text(page) -> str:
    """Extract clean text content from a Scrapling page response.
    
    Removes script/style tags and extracts readable text.
    """
    # Remove script and style elements
    for tag in page.css('script, style, nav, footer, header, noscript'):
        try:
            tag.remove()
        except Exception:
            pass
    
    # Try to get main content areas first
    main_content = None
    for selector in ['article', 'main', '[role="main"]', '.content', '#content', '.post-content']:
        elements = page.css(selector)
        if elements:
            main_content = elements[0]
            break
    
    # Extract text from main content or full body
    if main_content:
        text = main_content.get_all_text(separator='\n', strip=True)
    else:
        text = page.get_all_text(separator='\n', strip=True)
    
    # Clean up excessive whitespace
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)


def _get_title(page) -> str:
    """Extract the page title."""
    # Try <title> tag first
    title_el = page.css('title')
    if title_el:
        title = title_el[0].text
        if title:
            return title.strip()
    
    # Try h1
    h1 = page.css('h1')
    if h1:
        text = h1[0].text
        if text:
            return text.strip()
    
    return "Untitled Page"


async def scrape_url(url: str) -> Dict[str, Any]:
    """Scrape a URL and extract its text content.
    
    Tries fast HTTP first, falls back to stealth browser if blocked.
    
    Args:
        url: The URL to scrape
        
    Returns:
        Dict with keys: success, title, content, url, error, method
    """
    if not _is_valid_url(url):
        return {
            "success": False,
            "title": "",
            "content": "",
            "url": url,
            "error": "Invalid URL. Please provide a valid http:// or https:// URL.",
            "method": "none"
        }
    
    # Try fast HTTP fetcher first
    try:
        logger.info(f"Scraping URL with Fetcher: {url}")
        from scrapling.fetchers import Fetcher
        
        page = Fetcher.get(url, stealthy_headers=True, timeout=30)
        
        title = _get_title(page)
        content = _extract_text(page)
        
        if content and len(content) > 100:
            # Truncate if too long
            if len(content) > MAX_CONTENT_CHARS:
                content = content[:MAX_CONTENT_CHARS] + "\n\n[... content truncated ...]"
            
            logger.info(f"Successfully scraped {url} with Fetcher ({len(content)} chars)")
            return {
                "success": True,
                "title": title,
                "content": content,
                "url": url,
                "error": "",
                "method": "fetcher"
            }
        
        logger.info(f"Fetcher returned insufficient content, trying StealthyFetcher...")
        
    except Exception as e:
        logger.info(f"Fetcher failed for {url}: {e}, trying StealthyFetcher...")
    
    # Fallback to stealth browser
    try:
        logger.info(f"Scraping URL with StealthyFetcher: {url}")
        from scrapling.fetchers import StealthyFetcher
        
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        
        title = _get_title(page)
        content = _extract_text(page)
        
        if content and len(content) > 50:
            if len(content) > MAX_CONTENT_CHARS:
                content = content[:MAX_CONTENT_CHARS] + "\n\n[... content truncated ...]"
            
            logger.info(f"Successfully scraped {url} with StealthyFetcher ({len(content)} chars)")
            return {
                "success": True,
                "title": title,
                "content": content,
                "url": url,
                "error": "",
                "method": "stealthy"
            }
        
        return {
            "success": False,
            "title": title,
            "content": "",
            "url": url,
            "error": "Page returned no readable content. It may require login or be dynamically loaded.",
            "method": "stealthy"
        }
        
    except Exception as e:
        logger.error(f"StealthyFetcher also failed for {url}: {e}")
        return {
            "success": False,
            "title": "",
            "content": "",
            "url": url,
            "error": f"Could not scrape this page: {str(e)}",
            "method": "stealthy"
        }
