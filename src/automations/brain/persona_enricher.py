"""Persona enrichment module.

Analyzes conversations and suggests updates to persona.txt.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from typing import Optional, Tuple
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.conversation import conversation_history
from src.utils.logger import logger


class PersonaEnricher:
    """Analyzes conversations and generates persona update suggestions."""
    
    PERSONA_FILE = Path("D:/Gemini CLI/persona.txt")
    
    ENRICHMENT_PROMPT = """You are analyzing a week of conversations to learn new things about the user.

CURRENT PERSONA FILE:
{current_persona}

CONVERSATION HISTORY (summary + recent):
{conversation_context}

YOUR TASK:
1. Identify NEW information about the user that is NOT already in the persona file
2. Focus on: interests, preferences, projects, goals, habits, opinions
3. Only include things that seem like stable traits/facts, not one-off mentions

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

NEW LEARNINGS:
- [Learning 1]
- [Learning 2]
- [etc.]

SUGGESTED ADDITIONS TO PERSONA:
[Write the exact lines to add to persona.txt, formatted to match the existing style]

If there is nothing significant to add (e.g., conversations were too brief or didn't reveal new information), respond with exactly:
[NO_UPDATES]

Remember: Only suggest things that would genuinely help personalize future interactions. Don't pad with obvious or trivial observations."""

    def __init__(self):
        """Initialize the enricher."""
        self.gemini = GeminiCLI()
    
    def get_current_persona(self) -> str:
        """Read the current persona file."""
        try:
            if self.PERSONA_FILE.exists():
                return self.PERSONA_FILE.read_text(encoding='utf-8')
            return "(No persona file found)"
        except Exception as e:
            logger.error(f"PersonaEnricher: Error reading persona: {e}")
            return "(Error reading persona)"
    
    async def analyze_for_updates(self) -> Tuple[Optional[str], Optional[str]]:
        """Analyze conversations and suggest persona updates.
        
        Returns:
            Tuple of (learnings_summary, suggested_additions) or (None, None) if no updates
        """
        try:
            current_persona = self.get_current_persona()
            conversation_context = conversation_history.get_context_for_gemini()
            
            if not conversation_context or len(conversation_context.strip()) < 200:
                logger.info("PersonaEnricher: Not enough conversation to analyze")
                return None, None
            
            # Build the prompt
            prompt = self.ENRICHMENT_PROMPT.format(
                current_persona=current_persona,
                conversation_context=conversation_context
            )
            
            # Ask Gemini to analyze (no MCP needed)
            logger.info("PersonaEnricher: Analyzing conversations for persona updates...")
            response = await self.gemini.send_message(prompt, use_mcp=False)
            
            # Check for no updates
            if not response or "[NO_UPDATES]" in response.upper():
                logger.info("PersonaEnricher: No significant updates to suggest")
                return None, None
            
            # Parse the response
            learnings = self._extract_section(response, "NEW LEARNINGS:")
            suggestions = self._extract_section(response, "SUGGESTED ADDITIONS TO PERSONA:")
            
            if not learnings or not suggestions:
                logger.info("PersonaEnricher: Could not parse update suggestions")
                return None, None
            
            logger.info(f"PersonaEnricher: Generated update suggestion ({len(suggestions)} chars)")
            return learnings, suggestions
            
        except Exception as e:
            logger.error(f"PersonaEnricher: Error analyzing: {e}")
            return None, None
    
    def _extract_section(self, text: str, header: str) -> Optional[str]:
        """Extract a section from the response."""
        try:
            if header not in text:
                return None
            
            start = text.index(header) + len(header)
            
            # Find next section or end
            next_headers = ["NEW LEARNINGS:", "SUGGESTED ADDITIONS"]
            end = len(text)
            for h in next_headers:
                if h != header and h in text[start:]:
                    end = min(end, start + text[start:].index(h))
            
            return text[start:end].strip()
        except:
            return None
    
    def apply_update(self, additions: str) -> bool:
        """Append the suggested additions to persona.txt.
        
        Args:
            additions: The text to append
            
        Returns:
            True if successful
        """
        try:
            current = self.get_current_persona()
            
            # Add a separator and the new content
            updated = (
                f"{current}\n\n"
                f"## LEARNED FROM CONVERSATIONS (Auto-updated)\n"
                f"{additions}"
            )
            
            self.PERSONA_FILE.write_text(updated, encoding='utf-8')
            logger.info("PersonaEnricher: Successfully updated persona.txt")
            return True
            
        except Exception as e:
            logger.error(f"PersonaEnricher: Error applying update: {e}")
            return False
