"""Gemini-powered news summarization."""

import re
from typing import List

from src.automations.news.scraper import NewsArticle
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.logger import logger


def _replace_refs_with_links(text: str, articles: List[NewsArticle]) -> str:
    """Replace [1], [2], or bare numbers like '1, 2' with clickable links.
    
    Args:
        text: The Gemini output containing [1], [2], or bare numbers like "1, 2"
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
            # Escape parentheses in URL for Telegram markdown
            url = url_map[num].replace('(', '%28').replace(')', '%29')
            return f"[{num}]({url})"
        return str(num)
    
    # First: replace bracketed [N] references
    def replace_bracketed(match):
        num = int(match.group(1))
        return make_link(num)
    
    result = re.sub(r'\[(\d+)\]', replace_bracketed, text)
    
    # Second: process each line and replace trailing bare numbers
    lines = result.split('\n')
    processed_lines = []
    
    for line in lines:
        # Check if line ends with numbers like "1" or "1, 2" or "3, 20"
        # Pattern: one or more numbers separated by ", " at end of line
        match = re.search(r'(\d+(?:\s*,\s*\d+)*)\s*$', line)
        if match:
            refs_str = match.group(1)
            prefix = line[:match.start()]
            
            # Only process if there's content before the numbers (not just a bare number line)
            if prefix.strip():
                # Split by comma and process each number
                parts = re.split(r'\s*,\s*', refs_str)
                linked_parts = []
                for part in parts:
                    if part.isdigit():
                        num = int(part)
                        if 1 <= num <= max_num:
                            linked_parts.append(make_link(num))
                        else:
                            linked_parts.append(part)
                    else:
                        linked_parts.append(part)
                
                line = prefix + ', '.join(linked_parts)
        
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
