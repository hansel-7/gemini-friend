"""Expense email scanner.

Hourly background scanner that checks Gmail for UOB credit card
transaction alerts and auto-records them.
"""

import asyncio
import re
import json
from datetime import datetime
from typing import Optional, Callable, Awaitable, List, Dict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.expenses.manager import ExpenseManager, Expense
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.logger import logger


# Prompt for Gemini to search Gmail
GMAIL_SEARCH_PROMPT = """Search Gmail for emails from "{sender}" received in the last 70 minutes that are unread.

For each email found, return the following in valid JSON format:
{{
    "emails": [
        {{
            "message_id": "<unique message ID>",
            "body": "<the full email body text>"
        }}
    ]
}}

If no emails are found, return: {{"emails": []}}

IMPORTANT: Return ONLY the JSON, no other text."""


# Prompt for Gemini to extract transaction data from email body
EXTRACT_PROMPT = """Extract the transaction amount and date from this credit card alert email.

Email body:
{body}

Return ONLY valid JSON in this exact format:
{{
    "amount": <number without currency symbol or commas>,
    "currency": "VND",
    "date": "<ISO format date, e.g. 2026-03-02T12:30:00>"
}}

If the currency is not VND, use the appropriate currency code (e.g. "USD").
If you cannot determine the exact time, use 00:00:00 for the time portion.
Return ONLY JSON, no other text."""


# Prompt for Gemini to categorize an expense
CATEGORIZE_PROMPT = """Categorize this expense into exactly ONE of these categories:
- Food & Dining
- Transport
- Shopping
- Bills & Utilities
- Entertainment
- Health
- Travel
- Education
- Other

Expense description: "{description}"
Amount: {amount}

Return ONLY the category name, nothing else."""


class ExpenseScanner:
    """Background scanner that checks Gmail for credit card alerts."""
    
    def __init__(
        self,
        manager: ExpenseManager,
        gemini: GeminiCLI,
        sender_email: str,
        scan_interval_minutes: int = 60,
        currency: str = "VND",
        on_new_expenses: Optional[Callable[[List[Expense]], Awaitable[None]]] = None
    ):
        """Initialize the expense scanner.
        
        Args:
            manager: ExpenseManager for recording expenses
            gemini: GeminiCLI instance (with MCP for Gmail access)
            sender_email: Email address to scan for (e.g. unialerts@uobgroup.com)
            scan_interval_minutes: How often to scan (default 60)
            currency: Default currency (default VND)
            on_new_expenses: Callback when new expenses are found
        """
        self.manager = manager
        self.gemini = gemini
        self.sender_email = sender_email
        self.scan_interval = scan_interval_minutes * 60  # Convert to seconds
        self.currency = currency
        self.on_new_expenses = on_new_expenses
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the scanner loop."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._scanner_loop())
        logger.info(
            f"Expense scanner started — "
            f"checking every {self.scan_interval // 60} min, "
            f"sender: {self.sender_email}"
        )
    
    async def stop(self) -> None:
        """Stop the scanner loop."""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        logger.info("Expense scanner stopped")
    
    async def _scanner_loop(self) -> None:
        """Main loop — scan for new emails at interval."""
        # Wait for bot to fully start
        await asyncio.sleep(30)
        
        while self._running:
            try:
                await self.scan_once()
            except Exception as e:
                logger.error(f"Expense scanner: Error in scan loop: {e}")
            
            await asyncio.sleep(self.scan_interval)
    
    async def scan_once(self) -> List[Expense]:
        """Run a single scan cycle.
        
        Returns:
            List of newly recorded expenses
        """
        logger.info("Expense scanner: Scanning Gmail for new transaction alerts...")
        
        # Step 1: Search Gmail via Gemini + MCP
        search_prompt = GMAIL_SEARCH_PROMPT.format(sender=self.sender_email)
        
        try:
            response = await self.gemini.send_message(search_prompt, use_mcp=True)
        except Exception as e:
            logger.error(f"Expense scanner: Gmail search failed: {e}")
            return []
        
        # Step 2: Parse email list from response
        emails = self._parse_email_list(response)
        
        if not emails:
            logger.info("Expense scanner: No new transaction emails found")
            return []
        
        logger.info(f"Expense scanner: Found {len(emails)} email(s) to process")
        
        # Step 3: Process each email
        new_expenses = []
        for email_data in emails:
            message_id = email_data.get("message_id", "")
            body = email_data.get("body", "")
            
            if not message_id or not body:
                continue
            
            # Skip already processed
            if self.manager.is_email_processed(message_id):
                logger.info(f"Expense scanner: Skipping already processed email {message_id}")
                continue
            
            # Extract transaction data
            expense = await self._extract_and_record(message_id, body)
            if expense:
                new_expenses.append(expense)
        
        # Step 4: Notify user about new expenses
        if new_expenses and self.on_new_expenses:
            await self.on_new_expenses(new_expenses)
        
        return new_expenses
    
    def _parse_email_list(self, response: str) -> List[Dict]:
        """Parse Gemini's response to extract email data."""
        try:
            # Find JSON in response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.warning("Expense scanner: No JSON found in Gmail search response")
                return []
            
            data = json.loads(json_match.group())
            emails = data.get("emails", [])
            
            return emails if isinstance(emails, list) else []
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Expense scanner: Failed to parse email list: {e}")
            return []
    
    async def _extract_and_record(self, message_id: str, body: str) -> Optional[Expense]:
        """Extract transaction data from email body and record it.
        
        Args:
            message_id: Gmail message ID
            body: Email body text
            
        Returns:
            The recorded Expense, or None if extraction failed
        """
        try:
            # Ask Gemini to extract amount + date (no MCP needed)
            extract_prompt = EXTRACT_PROMPT.format(body=body)
            response = await self.gemini.send_message(extract_prompt, use_mcp=False)
            
            # Parse JSON
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if not json_match:
                logger.warning(f"Expense scanner: Could not extract data from email {message_id}")
                return None
            
            parsed = json.loads(json_match.group())
            
            amount = float(parsed.get("amount", 0))
            currency = parsed.get("currency", self.currency)
            date_str = parsed.get("date", "")
            
            if amount <= 0:
                logger.warning(f"Expense scanner: Invalid amount from email {message_id}")
                return None
            
            try:
                date = datetime.fromisoformat(date_str) if date_str else datetime.now()
            except ValueError:
                date = datetime.now()
            
            # Record with empty description (user will /describe later)
            expense = self.manager.add_expense(
                amount=amount,
                currency=currency,
                date=date,
                description="",
                category="",
                source="auto",
                email_id=message_id
            )
            
            return expense
            
        except Exception as e:
            logger.error(f"Expense scanner: Error processing email {message_id}: {e}")
            return None
    
    @staticmethod
    async def categorize_expense(gemini: GeminiCLI, description: str, amount: float) -> str:
        """Use Gemini to auto-categorize an expense.
        
        Args:
            gemini: GeminiCLI instance
            description: Expense description
            amount: Expense amount
            
        Returns:
            Category string
        """
        try:
            prompt = CATEGORIZE_PROMPT.format(description=description, amount=amount)
            response = await gemini.send_message(prompt, use_mcp=False)
            
            # Clean up response
            category = response.strip().strip('"').strip("'")
            
            # Validate against known categories
            valid_categories = [
                "Food & Dining", "Transport", "Shopping",
                "Bills & Utilities", "Entertainment", "Health",
                "Travel", "Education", "Other"
            ]
            
            for valid in valid_categories:
                if valid.lower() in category.lower():
                    return valid
            
            return "Other"
            
        except Exception as e:
            logger.error(f"Expense scanner: Error categorizing: {e}")
            return "Other"
    
    @property
    def is_running(self) -> bool:
        """Check if scanner is running."""
        return self._running
