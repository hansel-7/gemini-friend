"""Cron automation module.

Provides dynamic scheduled jobs via cron expressions.
"""

from .handlers import CronAutomation

# Export the automation class for the loader
automation_class = CronAutomation
