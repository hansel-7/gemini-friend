"""Natural language task parser.

Uses Gemini to extract task details from conversational messages.
Supports multiple tasks separated by semicolons or "and".
"""

import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger


# Phrases that indicate task/reminder intent
TASK_PHRASES = [
    r'\bremind me\b',
    r'\bremember to\b',
    r'\bdon\'?t let me forget\b',
    r'\bdon\'?t forget to\b',
    r'\bi need to\b',
    r'\bi have to\b',
    r'\bi should\b',
    r'\bi must\b',
    r'\badd task\b',
    r'\bnew task\b',
    r'\btask:\s',
    r'\btodo:\s',
    r'\bto-?do:\s',
    r'\bschedule\b.*\bfor\b',
    r'\bset a reminder\b',
]

# Compile patterns for efficiency
TASK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in TASK_PHRASES]


def looks_like_task(message: str) -> bool:
    """Check if a message looks like a task/reminder request.
    
    Args:
        message: The user's message
        
    Returns:
        True if the message appears to be a task request
    """
    for pattern in TASK_PATTERNS:
        if pattern.search(message):
            return True
    return False


def get_task_extraction_prompt(message: str) -> str:
    """Generate a prompt for Gemini to extract task details.
    
    Supports extracting multiple tasks from a single message.
    Tasks can be separated by semicolons (;) or the word "and".
    
    Args:
        message: The user's natural language task request
        
    Returns:
        A prompt string for Gemini
    """
    current_time = datetime.now()
    
    return f"""Extract ALL task details from the following message. The message may contain MULTIPLE tasks separated by semicolons (;) or the word "and".

IMPORTANT: DO NOT use any tools, file operations, or external resources. This is a pure text parsing task.
Return ONLY a JSON object with no additional text, no code, no explanations.

Current date/time: {current_time.strftime('%Y-%m-%d %H:%M')} ({current_time.strftime('%A')})

Message: "{message}"

Extract and return JSON with this structure:
{{
  "is_task": true/false,
  "tasks": [
    {{"description": "task 1", "due_date": "YYYY-MM-DDTHH:MM:SS or null"}},
    {{"description": "task 2", "due_date": "YYYY-MM-DDTHH:MM:SS or null"}}
  ]
}}

Rules:
- Set "is_task" to true if the message contains at least one valid task request
- Each task should have a clear, concise description (without time references)
- Parse due dates/times relative to the current date/time
- If no due date is specified for a task, set due_date to null
- Separate tasks that are joined by "and" or ";" into individual items
- If the message is not a task request, return {{"is_task": false, "tasks": []}}

Examples:
- "remind me to call mom and buy groceries" -> {{"is_task": true, "tasks": [{{"description": "Call mom", "due_date": null}}, {{"description": "Buy groceries", "due_date": null}}]}}
- "remind me to call mom tomorrow; finish report by friday 5pm; buy groceries" -> {{"is_task": true, "tasks": [{{"description": "Call mom", "due_date": "2026-01-29T09:00:00"}}, {{"description": "Finish report", "due_date": "2026-01-31T17:00:00"}}, {{"description": "Buy groceries", "due_date": null}}]}}
- "what's the weather" -> {{"is_task": false, "tasks": []}}

Return ONLY the JSON object, no markdown, no explanation:"""


def _clean_json_response(response: str) -> str:
    """Clean up a response that may contain markdown or extra text.
    
    Args:
        response: Raw response from Gemini
        
    Returns:
        Cleaned JSON string
    """
    response = response.strip()
    
    # Remove markdown code blocks if present
    if '```' in response:
        lines = response.split('\n')
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith('```'):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        if json_lines:
            response = '\n'.join(json_lines)
    
    return response.strip()


def parse_gemini_response(response: str) -> Optional[List[Dict[str, Any]]]:
    """Parse Gemini's response to extract task details.
    
    Supports both single task and multiple task responses.
    
    Args:
        response: Gemini's response text
        
    Returns:
        List of parsed task dicts, or None if parsing failed
    """
    try:
        response = _clean_json_response(response)
        
        # Try to parse JSON
        data = json.loads(response)
        
        # Validate required fields
        if not isinstance(data, dict):
            return None
        
        if not data.get('is_task', False):
            return None
        
        # Handle new multi-task format
        if 'tasks' in data and isinstance(data['tasks'], list):
            tasks = []
            for task_data in data['tasks']:
                if isinstance(task_data, dict) and task_data.get('description'):
                    tasks.append({
                        'description': task_data['description'],
                        'due_date': task_data.get('due_date'),
                        'is_task': True
                    })
            return tasks if tasks else None
        
        # Handle legacy single-task format for backwards compatibility
        if data.get('description'):
            return [{
                'description': data['description'],
                'due_date': data.get('due_date'),
                'is_task': True
            }]
        
        return None
        
    except json.JSONDecodeError:
        # Try to extract JSON from mixed content
        # First try to find object with "tasks" array
        json_match = re.search(r'\{[^{}]*"tasks"\s*:\s*\[[^\]]*\][^{}]*\}', response, re.DOTALL)
        if not json_match:
            # Try simpler single-object pattern
            json_match = re.search(r'\{[^{}]*\}', response)
        
        if json_match:
            try:
                data = json.loads(json_match.group())
                
                # Try multi-task format
                if 'tasks' in data and isinstance(data['tasks'], list):
                    tasks = []
                    for task_data in data['tasks']:
                        if isinstance(task_data, dict) and task_data.get('description'):
                            tasks.append({
                                'description': task_data['description'],
                                'due_date': task_data.get('due_date'),
                                'is_task': True
                            })
                    return tasks if tasks else None
                
                # Try single-task format
                if data.get('is_task') and data.get('description'):
                    return [{
                        'description': data['description'],
                        'due_date': data.get('due_date'),
                        'is_task': True
                    }]
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"Failed to parse task extraction response: {response[:200]}")
        return None
    except Exception as e:
        logger.error(f"Error parsing task extraction: {e}")
        return None


def parse_due_date(due_date_str: Optional[str]) -> Optional[datetime]:
    """Parse a due date string to datetime.
    
    Args:
        due_date_str: ISO format date string or None
        
    Returns:
        datetime object or None
    """
    if not due_date_str:
        return None
    
    try:
        return datetime.fromisoformat(due_date_str.replace('Z', '+00:00').replace('+00:00', ''))
    except ValueError:
        try:
            # Try parsing without timezone
            return datetime.strptime(due_date_str[:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            logger.warning(f"Could not parse due date: {due_date_str}")
            return None
