"""Automation module loader.

This module provides functionality to dynamically load and manage
automation plugins based on configuration.
"""

import importlib
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.logger import logger


def load_automation_config() -> Dict[str, Any]:
    """Load automation configuration from JSON file.
    
    Returns:
        Dictionary of automation configurations
    """
    config_path = Path(__file__).parent.parent.parent / 'config' / 'automations.json'
    
    if not config_path.exists():
        logger.warning(f"Automation config not found at {config_path}, using defaults")
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load automation config: {e}")
        return {}


def load_automations(application, config: Optional[Dict[str, Any]] = None) -> List[Any]:
    """Load all enabled automations.
    
    Args:
        application: Telegram application instance
        config: Optional config dict. If None, loads from file.
        
    Returns:
        List of loaded automation instances
    """
    if config is None:
        config = load_automation_config()
    
    loaded_automations = []
    
    for name, settings in config.items():
        if not isinstance(settings, dict):
            continue
            
        if not settings.get('enabled', False):
            logger.info(f"Automation '{name}' is disabled, skipping")
            continue
        
        try:
            # Import the automation module
            module = importlib.import_module(f'src.automations.{name}')
            
            # Get the automation class
            if not hasattr(module, 'automation_class'):
                logger.error(f"Automation '{name}' has no 'automation_class' export")
                continue
            
            # Instantiate the automation
            automation = module.automation_class(application, settings)
            
            # Register handlers
            automation.register_handlers()
            
            loaded_automations.append(automation)
            logger.info(f"Loaded automation: {automation.name}")
            
        except ImportError as e:
            logger.error(f"Failed to import automation '{name}': {e}")
        except Exception as e:
            logger.error(f"Failed to load automation '{name}': {e}")
    
    return loaded_automations


async def start_automations(automations: List[Any]) -> None:
    """Start all loaded automations.
    
    Args:
        automations: List of automation instances
    """
    for automation in automations:
        try:
            await automation.start()
            logger.info(f"Started automation: {automation.name}")
        except Exception as e:
            logger.error(f"Failed to start automation '{automation.name}': {e}")


async def stop_automations(automations: List[Any]) -> None:
    """Stop all loaded automations.
    
    Args:
        automations: List of automation instances
    """
    for automation in automations:
        try:
            await automation.stop()
            logger.info(f"Stopped automation: {automation.name}")
        except Exception as e:
            logger.error(f"Failed to stop automation '{automation.name}': {e}")
