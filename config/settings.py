"""Configuration settings loader."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)


class Settings:
    """Application settings loaded from environment variables."""
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    
    # Security - Allowed user IDs (comma-separated string to set of ints)
    _allowed_ids = os.getenv('ALLOWED_USER_IDS', '')
    ALLOWED_USER_IDS: set[int] = {
        int(uid.strip()) 
        for uid in _allowed_ids.split(',') 
        if uid.strip().isdigit()
    }
    
    # Gemini CLI
    GEMINI_CLI_COMMAND: str = os.getenv('GEMINI_CLI_COMMAND', 'npx @google/gemini-cli')
    GEMINI_TIMEOUT: int = int(os.getenv('GEMINI_TIMEOUT', '300'))
    
    # Paths
    PROJECT_ROOT: Path = Path(__file__).parent.parent
    CONFIG_DIR: Path = PROJECT_ROOT / 'config'
    GEMINI_SETTINGS_PATH: Path = CONFIG_DIR / 'gemini_settings.json'
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate required settings. Returns list of errors."""
        errors = []
        
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is not set in .env")
        
        if not cls.ALLOWED_USER_IDS:
            errors.append("ALLOWED_USER_IDS is not set in .env")
        
        return errors


# Create singleton instance
settings = Settings()
