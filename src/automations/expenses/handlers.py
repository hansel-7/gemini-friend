"""Expense automation handlers.

Main automation class that integrates expense tracking
with Telegram commands and email scanning.
"""

import asyncio
import re
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.automations.base import BaseAutomation
from src.automations.expenses.manager import ExpenseManager, Expense
from src.automations.expenses.scanner import ExpenseScanner
from src.gemini.cli_wrapper import GeminiCLI
from src.utils.logger import logger
from src.bot.security import authorized_only
from config.settings import settings


# Prompt for Gemini to parse manual /expense input
PARSE_EXPENSE_PROMPT = """Parse this expense input into structured data.

Input: "{input}"

The user is entering a manual expense. Extract:
- amount: the number (e.g., "250k" = 250000, "50" = 50000 if no unit, "1.5m" = 1500000)
- description: what the expense was for

Rules:
- "k" or "K" means thousands (250k = 250,000)
- "m" or "M" means millions (1.5m = 1,500,000)
- If no unit is specified and the number is small (< 1000), assume thousands (e.g., "50 coffee" = 50,000)
- Currency is always VND unless explicitly stated otherwise

Return ONLY valid JSON:
{{
    "amount": <number>,
    "currency": "VND",
    "description": "<what they bought>"
}}"""


class ExpenseAutomation(BaseAutomation):
    """Expense tracking automation.
    
    Features:
    1. /expense command for manual expense entry
    2. /expenses for viewing summaries
    3. /describe to add descriptions to auto-detected transactions
    4. /delexpense to delete expenses
    5. Hourly email scanning for credit card alerts
    """
    
    name = "expenses"
    description = "Expense tracking with auto email scanning"
    version = "1.0.0"
    
    def __init__(self, application: Application, config: Dict[str, Any]):
        """Initialize the expense automation."""
        super().__init__(application, config)
        
        # Manager for expense CRUD
        data_file = config.get('data_file', 'D:/Gemini CLI/expenses.json')
        self.manager = ExpenseManager(data_file=data_file)
        
        # Gemini CLI for parsing and categorizing
        self.gemini = GeminiCLI.get_instance()
        
        # Scanner for email alerts
        self.scanner = ExpenseScanner(
            manager=self.manager,
            gemini=self.gemini,
            sender_email=config.get('alert_sender_email', 'unialerts@uobgroup.com'),
            scan_interval_minutes=config.get('scan_interval_minutes', 60),
            currency=config.get('currency', 'VND'),
            on_new_expenses=self._on_new_expenses
        )
        
        # User ID for sending notifications
        self.user_id = next(iter(settings.ALLOWED_USER_IDS)) if settings.ALLOWED_USER_IDS else None
    
    def register_handlers(self) -> None:
        """Register expense command handlers."""
        handlers = [
            CommandHandler("expense", self._expense_command),
            CommandHandler("expenses", self._expenses_command),
            CommandHandler("describe", self._describe_command),
            CommandHandler("delexpense", self._delete_command),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
            self._handlers.append(handler)
        
        logger.info(f"Registered {len(handlers)} expense command handlers")
    
    async def start(self) -> None:
        """Start the expense scanner."""
        await super().start()
        await self.scanner.start()
    
    async def stop(self) -> None:
        """Stop the expense scanner."""
        await self.scanner.stop()
        await super().stop()
    
    # --- Telegram Command Handlers ---
    
    @authorized_only
    async def _expense_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /expense command.
        
        Usage:
            /expense 250k coffee     — add a manual expense
            /expense                 — show today's expenses
        """
        args = context.args if context.args else []
        
        if not args:
            # Show today's expenses
            await self._show_today(update)
            return
        
        # Parse manual expense input
        raw_input = ' '.join(args)
        
        try:
            processing_msg = await update.message.reply_text("💰 Recording expense...")
            
            # Use Gemini to parse the input
            parse_prompt = PARSE_EXPENSE_PROMPT.format(input=raw_input)
            response = await self.gemini.send_message(parse_prompt, use_mcp=False)
            
            # Extract JSON
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if not json_match:
                await processing_msg.edit_text("❌ Couldn't parse that. Try: /expense 250k coffee")
                return
            
            parsed = json.loads(json_match.group())
            
            amount = float(parsed.get("amount", 0))
            currency = parsed.get("currency", "VND")
            description = parsed.get("description", raw_input)
            
            if amount <= 0:
                await processing_msg.edit_text("❌ Invalid amount. Try: /expense 250k coffee")
                return
            
            # Auto-categorize
            category = await ExpenseScanner.categorize_expense(
                self.gemini, description, amount
            )
            
            # Record the expense
            expense = self.manager.add_expense(
                amount=amount,
                currency=currency,
                date=datetime.now(),
                description=description,
                category=category,
                source="manual"
            )
            
            if expense:
                await processing_msg.edit_text(
                    f"✅ Expense recorded!\n\n"
                    f"#{expense.id} — {expense.format_amount()}\n"
                    f"📝 {description}\n"
                    f"🏷️ {category}"
                )
            else:
                await processing_msg.edit_text("❌ Failed to save expense.")
                
        except Exception as e:
            logger.error(f"Expense command error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _show_today(self, update: Update) -> None:
        """Show today's expenses."""
        expenses = self.manager.get_today()
        
        if not expenses:
            await update.message.reply_text(
                "💰 No expenses today.\n\n"
                "Add one with: /expense 250k coffee"
            )
            return
        
        total = sum(e.amount for e in expenses)
        
        lines = ["💰 *Today's Expenses*\n"]
        for e in expenses:
            desc = e.description or "_(no description)_"
            cat = f" — {e.category}" if e.category else ""
            source_icon = "💳" if e.source == "auto" else "✏️"
            lines.append(f"{source_icon} *#{e.id}* — {e.format_amount()} — {desc}{cat}")
        
        lines.append(f"\n*Total: {Expense(0, total, 'VND', datetime.now()).format_amount()}*")
        
        # Check for undescribed
        undescribed = [e for e in expenses if not e.has_description]
        if undescribed:
            ids = ', '.join(f"#{e.id}" for e in undescribed)
            lines.append(f"\n⚠️ Missing descriptions: {ids}")
            lines.append("Use /describe <id> <text> to add")
        
        try:
            await update.message.reply_text(
                '\n'.join(lines),
                parse_mode='Markdown'
            )
        except Exception:
            await update.message.reply_text('\n'.join(lines))
    
    @authorized_only
    async def _expenses_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /expenses command — show summary.
        
        Usage:
            /expenses          — this month's summary
            /expenses week     — this week's summary
        """
        args = context.args if context.args else []
        period = args[0].lower() if args else "month"
        
        if period in ("week", "w"):
            expenses = self.manager.get_this_week()
            period_label = "This Week"
        else:
            expenses = self.manager.get_this_month()
            period_label = "This Month"
        
        if not expenses:
            await update.message.reply_text(f"📊 No expenses for {period_label.lower()}.")
            return
        
        total = sum(e.amount for e in expenses)
        summary = self.manager.get_summary(expenses)
        
        lines = [f"📊 *Expense Summary — {period_label}*\n"]
        
        for category, cat_total in summary.items():
            pct = (cat_total / total * 100) if total > 0 else 0
            formatted = Expense(0, cat_total, 'VND', datetime.now()).format_amount()
            lines.append(f"• {category}: {formatted} ({pct:.0f}%)")
        
        total_formatted = Expense(0, total, 'VND', datetime.now()).format_amount()
        lines.append(f"\n💰 *Total: {total_formatted}*")
        lines.append(f"📝 {len(expenses)} transaction(s)")
        
        # Show undescribed across all time
        undescribed = self.manager.get_undescribed()
        if undescribed:
            lines.append(f"\n⚠️ {len(undescribed)} expense(s) missing descriptions")
        
        try:
            await update.message.reply_text(
                '\n'.join(lines),
                parse_mode='Markdown'
            )
        except Exception:
            await update.message.reply_text('\n'.join(lines))
    
    @authorized_only
    async def _describe_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /describe command.
        
        Usage:
            /describe 12 GrabFood dinner
        """
        args = context.args if context.args else []
        
        if len(args) < 2:
            # Show undescribed expenses
            undescribed = self.manager.get_undescribed()
            if not undescribed:
                await update.message.reply_text("✅ All expenses have descriptions!")
                return
            
            lines = ["📝 *Expenses needing descriptions:*\n"]
            for e in undescribed:
                lines.append(f"*#{e.id}* — {e.format_amount()} — {e.date.strftime('%b %d, %H:%M')}")
            lines.append("\nUse: /describe <id> <description>")
            
            try:
                await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
            except Exception:
                await update.message.reply_text('\n'.join(lines))
            return
        
        # Parse ID and description
        try:
            expense_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid ID. Use: /describe <id> <description>")
            return
        
        description = ' '.join(args[1:])
        
        # Auto-categorize
        expense = self.manager.get_expense(expense_id)
        if not expense:
            await update.message.reply_text(f"❌ Expense #{expense_id} not found.")
            return
        
        category = await ExpenseScanner.categorize_expense(
            self.gemini, description, expense.amount
        )
        
        # Update the expense
        updated = self.manager.describe_expense(expense_id, description, category)
        
        if updated:
            await update.message.reply_text(
                f"✅ Updated #{expense_id}\n\n"
                f"💰 {updated.format_amount()}\n"
                f"📝 {description}\n"
                f"🏷️ {category}"
            )
        else:
            await update.message.reply_text(f"❌ Expense #{expense_id} not found.")
    
    @authorized_only
    async def _delete_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /delexpense command.
        
        Usage:
            /delexpense 12
        """
        args = context.args if context.args else []
        
        if not args:
            await update.message.reply_text("Usage: /delexpense <id>")
            return
        
        try:
            expense_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid ID.")
            return
        
        if self.manager.delete_expense(expense_id):
            await update.message.reply_text(f"🗑️ Deleted expense #{expense_id}")
        else:
            await update.message.reply_text(f"❌ Expense #{expense_id} not found.")
    
    # --- Scanner Callback ---
    
    async def _on_new_expenses(self, expenses: List[Expense]) -> None:
        """Send Telegram notification when new expenses are auto-detected."""
        if not self.user_id or not expenses:
            return
        
        try:
            if len(expenses) == 1:
                e = expenses[0]
                text = (
                    f"💳 New credit card transaction detected:\n\n"
                    f"*#{e.id}* — {e.format_amount()} — {e.date.strftime('%b %d, %H:%M')}\n\n"
                    f"Use `/describe {e.id} <description>` to add details."
                )
            else:
                lines = [f"💳 {len(expenses)} new credit card transactions detected:\n"]
                for e in expenses:
                    lines.append(f"*#{e.id}* — {e.format_amount()} — {e.date.strftime('%b %d, %H:%M')}")
                lines.append(f"\nUse `/describe <id> <description>` to add details.")
                text = '\n'.join(lines)
            
            try:
                await self.application.bot.send_message(
                    chat_id=self.user_id,
                    text=text,
                    parse_mode='Markdown'
                )
            except Exception:
                # Fallback to plain text
                plain_text = text.replace('*', '').replace('`', '')
                await self.application.bot.send_message(
                    chat_id=self.user_id,
                    text=plain_text
                )
            
        except Exception as e:
            logger.error(f"Expenses: Error sending notification: {e}")
    
    # --- Status ---
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the expense automation."""
        status = super().get_status()
        
        today = self.manager.get_today()
        undescribed = self.manager.get_undescribed()
        
        status.update({
            "today_count": len(today),
            "today_total": sum(e.amount for e in today),
            "undescribed_count": len(undescribed),
            "scanner_running": self.scanner.is_running
        })
        
        return status
