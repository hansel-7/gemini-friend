"""Gemini-powered news summarization."""

from typing import List

from src.automations.news.scraper import NewsArticle
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.logger import logger


async def summarize_articles(articles: List[NewsArticle]) -> str:
    """Summarize a list of news articles using Gemini CLI.
    
    Args:
        articles: List of NewsArticle objects to summarize
        
    Returns:
        A formatted summary string
    """
    if not articles:
        return "No articles to summarize."
    
    # Use GeminiCLI wrapper
    gemini = GeminiCLI()
    
    # Build the prompt with article data
    # Format: **Title** (Source)\nSummary...
    article_text = "\n\n".join([
        f"**{a.title}** ({a.source})\n{a.summary or 'No summary available.'}"
        for a in articles[:50]  # Limit to avoid token limits
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
• **Headline 1**: Brief summary (1-2 sentences).
• **Headline 2**: Brief summary.

**BUSINESS & FUNDING**
• **Company**: Details of deal/funding ($Amount).

**MARKET TRENDS**
• Trend or data point.

**QUICK HITS**
• Brief item.

**Rules:**
- Use "• " (bullet point + space) for every item.
- **Bold** the company name or main subject at the start of each bullet.
- Leave an empty line between sections.
- Keep it concise and scannable. Avoid long paragraphs.

---
ARTICLES:
{article_text}
"""
    
    try:
        # fast mode (use_mcp=False) since we just need text summarization, no tools
        response = await gemini.send_message(prompt, use_mcp=False)
        return response
    except Exception as e:
        logger.error(f"Gemini summarization error: {e}")
        # Fallback: just list the top headlines
        fallback = "⚠️ *Could not generate AI summary. Top headlines:*\n\n"
        for a in articles[:10]:
            fallback += f"• **{a.title}** ({a.source})\n"
        return fallback
