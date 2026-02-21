"""Gemini-powered news summarization."""

import re
from typing import List

from src.automations.news.scraper import NewsArticle
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.logger import logger


def _replace_refs_with_links(text: str, articles: List[NewsArticle]) -> str:
    """Replace article references with clickable links.
    
    Handles multiple formats Gemini may output:
    - [1] - individual bracketed reference
    - [10, 13, 15] - grouped bracketed references  
    - 10, 13, 15 - bare trailing numbers at end of line
    
    Args:
        text: The Gemini output containing references
        articles: List of articles to map indices to URLs
        
    Returns:
        Text with references replaced by clickable markdown links
    """
    # Build a mapping of article numbers to URLs
    url_map = {i+1: a.link for i, a in enumerate(articles)}
    max_num = len(articles)
    
    # Replace function for any number reference
    def make_link(num: int) -> str:
        if num in url_map:
            # Escape parentheses in URL for markdown
            url = url_map[num].replace('(', '%28').replace(')', '%29')
            return f"[{num}]({url})"
        return str(num)
    
    def nums_to_links(nums_str: str) -> str:
        """Convert a comma-separated string of numbers to linked format."""
        parts = re.split(r'\s*,\s*', nums_str.strip())
        linked = []
        for part in parts:
            part = part.strip()
            if part.isdigit():
                num = int(part)
                if 1 <= num <= max_num:
                    linked.append(make_link(num))
                else:
                    linked.append(part)
            else:
                linked.append(part)
        return ', '.join(linked)
    
    # Step 1: Replace grouped brackets [N, N, N] with linked versions
    def replace_grouped(match):
        return nums_to_links(match.group(1))
    
    result = re.sub(r'\[(\d+(?:\s*,\s*\d+)+)\]', replace_grouped, text)
    
    # Step 2: Replace individual brackets [N]
    def replace_single(match):
        num = int(match.group(1))
        return make_link(num)
    
    result = re.sub(r'\[(\d+)\]', replace_single, result)
    
    # Step 3: Process trailing bare numbers at end of lines
    lines = result.split('\n')
    processed_lines = []
    
    for line in lines:
        # Match trailing numbers like "1, 2" or "3" at end of line
        match = re.search(r'(\d+(?:\s*,\s*\d+)*)\s*$', line)
        if match:
            refs_str = match.group(1)
            prefix = line[:match.start()]
            # Only process if there's content before the numbers
            if prefix.strip():
                line = prefix + nums_to_links(refs_str)
        
        processed_lines.append(line)
    
    return '\n'.join(processed_lines)


async def summarize_articles(articles: List[NewsArticle]) -> str:
    """Summarize a list of news articles using Gemini CLI.
    
    Args:
        articles: List of NewsArticle objects to summarize
        
    Returns:
        A formatted summary string
    """
    if not articles:
        return "No articles to summarize."
    
    # Limit articles to top 30 for faster processing
    articles = articles[:30]
    
    # Use GeminiCLI wrapper
    gemini = GeminiCLI()
    
    # Build the prompt with numbered articles (no URLs to keep it short)
    article_text = "\n\n".join([
        f"[{i+1}] **{a.title}** ({a.source})\n{a.summary or 'No summary available.'}"
        for i, a in enumerate(articles)
    ])
    
    prompt = f"""You are a gaming industry analyst providing a daily news briefing for a venture capital investor focused on games.

Summarize the following {len(articles)} gaming industry news articles into a concise, scannable digest. Focus on:
- Major business moves (funding, M&A, partnerships)
- Market trends and data
- Notable company news (especially mobile, F2P, SEA/Vietnam relevance)
- Regulatory developments

Format your response as a clean Markdown list designed for Telegram.
Use this EXACT format:

**TOP STORIES**
• **Headline 1**: Brief summary (1-2 sentences). [1]
• **Headline 2**: Brief summary. [2]

**BUSINESS & FUNDING**
• **Company**: Details of deal/funding ($Amount). [3]

**MARKET TRENDS**
• Trend or data point. [4]

**QUICK HITS**
• Brief item. [5]

**Rules:**
- Use "• " (bullet point + space) for every item.
- **Bold** the company name or main subject at the start of each bullet.
- ALWAYS end each bullet with the article number in brackets like [1], [2], etc.
- Leave an empty line between sections.
- Keep it concise and scannable. Avoid long paragraphs.

---
ARTICLES:
{article_text}
"""
    
    try:
        # fast mode (use_mcp=False) since we just need text summarization, no tools
        response = await gemini.send_message(prompt, use_mcp=False)
        
        # Post-process: replace [1], [2], etc. with clickable [→](url) links
        response = _replace_refs_with_links(response, articles)
        
        return response
        
    except Exception as e:
        logger.error(f"Gemini summarization error: {e}")
        # Fallback: just list the top headlines with links
        fallback = "⚠️ *Could not generate AI summary. Top headlines:*\n\n"
        for a in articles[:10]:
            fallback += f"• **{a.title}** [→]({a.link})\n"
        return fallback
