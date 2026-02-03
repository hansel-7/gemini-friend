"""Brain thinker module.

Core logic for generating proactive thoughts and ideas based on conversation history.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from typing import Optional
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.conversation import conversation_history
from src.utils.logger import logger


# Special marker that Gemini returns when there's nothing to say
NO_MESSAGE_MARKER = "[NO_MESSAGE]"


class BrainThinker:
    """Generates proactive thoughts based on conversation history."""
    
    # The prompt that turns Gemini into a thinking partner
    THINKING_PROMPT = """You are reviewing your conversation history with your human partner.

IMPORTANT: Your job is NOT to remind them of things they said or repeat information back.

Your job IS to:
1. Generate NEW ideas building on what was discussed
2. Make unexpected connections between different topics you've talked about
3. Suggest angles or perspectives they might not have considered
4. Be a curious, proactive thinking partner who keeps pondering their interests
5. Share relevant insights or questions that could spark interesting discussion

Guidelines:
- Be conversational and natural, like a thoughtful friend reaching out
- Don't be preachy or lecture-y
- Keep it concise - one focused thought is better than a rambling message
- Don't just summarize what they said - ADD something new
- If you reference something they mentioned, build on it with fresh thinking

If there's genuinely nothing interesting to contribute right now (e.g., the conversation was too brief, too long ago, or you can't think of anything valuable to add), respond with EXACTLY: [NO_MESSAGE]

Otherwise, write your proactive message directly. Do not explain what you're doing - just write the message you would send.

=== CONVERSATION HISTORY ===
{context}
=== END HISTORY ===

Your proactive thought (or [NO_MESSAGE] if nothing to contribute):"""

    def __init__(self, conversation_file: Optional[str] = None):
        """Initialize the thinker.
        
        Args:
            conversation_file: Path to conversation history file (uses default if None)
        """
        self.gemini = GeminiCLI()
        self.conversation_file = conversation_file
    
    async def generate_thought(self) -> Optional[str]:
        """Generate a proactive thought based on conversation history.
        
        Returns:
            A proactive message to send, or None if nothing to say
        """
        try:
            # Get conversation context
            context = conversation_history.get_context_for_gemini()
            
            if not context or len(context.strip()) < 100:
                logger.debug("Brain: Not enough conversation history to generate thoughts")
                return None
            
            # Build the thinking prompt
            prompt = self.THINKING_PROMPT.format(context=context)
            
            # Ask Gemini to think (using fast mode - no MCP needed for pure thinking)
            logger.info("Brain: Asking Gemini to generate a proactive thought...")
            response = await self.gemini.send_message(prompt, use_mcp=False)
            
            # Check for no message marker
            if not response or NO_MESSAGE_MARKER in response.upper():
                logger.info("Brain: Gemini had nothing to contribute this cycle")
                return None
            
            # Clean up the response
            thought = response.strip()
            
            # Validate it's not too short or just acknowledgment
            if len(thought) < 20:
                logger.info("Brain: Generated thought too short, skipping")
                return None
            
            logger.info(f"Brain: Generated thought ({len(thought)} chars)")
            return thought
            
        except Exception as e:
            logger.error(f"Brain: Error generating thought: {e}")
            return None
