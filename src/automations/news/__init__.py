"""News automation module."""

from src.automations.news.scraper import NewsScraper, NewsArticle
from src.automations.news.scheduler import NewsScheduler
from src.automations.news.summarizer import summarize_articles
from src.automations.news.handlers import NewsAutomation

__all__ = ['NewsScraper', 'NewsArticle', 'NewsScheduler', 'summarize_articles', 'NewsAutomation']

# Export the automation class for the loader
automation_class = NewsAutomation
