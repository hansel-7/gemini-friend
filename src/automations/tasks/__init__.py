"""Tasks automation module.

Provides task/checklist management with reminders.
"""

from .handlers import TasksAutomation

# Export the automation class for the loader
automation_class = TasksAutomation
