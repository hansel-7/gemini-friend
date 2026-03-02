"""Expense manager for CRUD operations.

Handles reading, writing, and managing expenses in a JSON file.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import threading

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.logger import logger


class Expense:
    """Represents a single expense record."""
    
    def __init__(
        self,
        id: int,
        amount: float,
        currency: str,
        date: datetime,
        description: str = "",
        category: str = "",
        source: str = "manual",
        created_at: Optional[datetime] = None,
        email_id: Optional[str] = None
    ):
        self.id = id
        self.amount = amount
        self.currency = currency
        self.date = date
        self.description = description
        self.category = category
        self.source = source  # "auto" or "manual"
        self.created_at = created_at or datetime.now()
        self.email_id = email_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert expense to dictionary for JSON serialization."""
        data = {
            "id": self.id,
            "amount": self.amount,
            "currency": self.currency,
            "date": self.date.isoformat(),
            "description": self.description,
            "category": self.category,
            "source": self.source,
            "created_at": self.created_at.isoformat()
        }
        if self.email_id:
            data["email_id"] = self.email_id
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Expense':
        """Create an Expense from a dictionary."""
        return cls(
            id=data["id"],
            amount=data["amount"],
            currency=data.get("currency", "VND"),
            date=datetime.fromisoformat(data["date"]),
            description=data.get("description", ""),
            category=data.get("category", ""),
            source=data.get("source", "manual"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            email_id=data.get("email_id")
        )
    
    @property
    def has_description(self) -> bool:
        """Check if expense has a description."""
        return bool(self.description.strip())
    
    def format_amount(self) -> str:
        """Format amount with currency symbol."""
        if self.currency == "VND":
            return f"{self.amount:,.0f}₫"
        elif self.currency == "USD":
            return f"${self.amount:,.2f}"
        return f"{self.amount:,.2f} {self.currency}"


class ExpenseManager:
    """Manages expense storage and operations."""
    
    def __init__(self, data_file: str):
        """Initialize the expense manager.
        
        Args:
            data_file: Path to the JSON file for expense storage
        """
        self.data_file = Path(data_file)
        self._lock = threading.Lock()
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        """Create the data file if it doesn't exist."""
        if not self.data_file.exists():
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            self._save_data([], 1, [])
    
    def _load_data(self) -> tuple[List[Expense], int, List[str]]:
        """Load all data from the JSON file.
        
        Returns:
            Tuple of (expenses, next_id, processed_email_ids)
        """
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            expenses = [Expense.from_dict(e) for e in data.get("expenses", [])]
            next_id = data.get("next_id", 1)
            processed_emails = data.get("processed_email_ids", [])
            
            return expenses, next_id, processed_emails
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Expenses: Error loading data file: {e}")
            return [], 1, []
    
    def _save_data(self, expenses: List[Expense], next_id: int, processed_email_ids: List[str]):
        """Save all data to the JSON file."""
        try:
            data = {
                "expenses": [e.to_dict() for e in expenses],
                "next_id": next_id,
                "processed_email_ids": processed_email_ids
            }
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Expenses: Error saving data file: {e}")
    
    def add_expense(
        self,
        amount: float,
        currency: str = "VND",
        date: Optional[datetime] = None,
        description: str = "",
        category: str = "",
        source: str = "manual",
        email_id: Optional[str] = None
    ) -> Optional[Expense]:
        """Add a new expense.
        
        Args:
            amount: Transaction amount
            currency: Currency code (default VND)
            date: Transaction date (default now)
            description: What the expense was for
            category: Auto-categorized label
            source: "auto" or "manual"
            email_id: Gmail message ID (for dedup)
            
        Returns:
            The created Expense, or None if failed
        """
        with self._lock:
            try:
                expenses, next_id, processed_emails = self._load_data()
                
                expense = Expense(
                    id=next_id,
                    amount=amount,
                    currency=currency,
                    date=date or datetime.now(),
                    description=description,
                    category=category,
                    source=source,
                    email_id=email_id
                )
                
                expenses.append(expense)
                
                # Track processed email
                if email_id and email_id not in processed_emails:
                    processed_emails.append(email_id)
                
                self._save_data(expenses, next_id + 1, processed_emails)
                
                logger.info(f"Expenses: Added #{expense.id}: {expense.format_amount()} — {description or '(no description)'}")
                return expense
                
            except Exception as e:
                logger.error(f"Expenses: Error adding expense: {e}")
                return None
    
    def describe_expense(self, expense_id: int, description: str, category: str = "") -> Optional[Expense]:
        """Add/update description and category for an expense.
        
        Args:
            expense_id: ID of the expense
            description: Description text
            category: Category label
            
        Returns:
            The updated Expense, or None if not found
        """
        with self._lock:
            try:
                expenses, next_id, processed_emails = self._load_data()
                
                for expense in expenses:
                    if expense.id == expense_id:
                        expense.description = description
                        if category:
                            expense.category = category
                        self._save_data(expenses, next_id, processed_emails)
                        logger.info(f"Expenses: Described #{expense_id}: {description} [{category}]")
                        return expense
                
                return None
                
            except Exception as e:
                logger.error(f"Expenses: Error describing expense: {e}")
                return None
    
    def get_expense(self, expense_id: int) -> Optional[Expense]:
        """Get an expense by ID."""
        expenses, _, _ = self._load_data()
        for expense in expenses:
            if expense.id == expense_id:
                return expense
        return None
    
    def get_expenses(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Expense]:
        """Get expenses, optionally filtered by date range."""
        expenses, _, _ = self._load_data()
        
        if date_from:
            expenses = [e for e in expenses if e.date >= date_from]
        if date_to:
            expenses = [e for e in expenses if e.date <= date_to]
        
        return sorted(expenses, key=lambda e: e.date, reverse=True)
    
    def get_today(self) -> List[Expense]:
        """Get today's expenses."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.get_expenses(date_from=today_start)
    
    def get_this_week(self) -> List[Expense]:
        """Get this week's expenses (Monday to now)."""
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.get_expenses(date_from=week_start)
    
    def get_this_month(self) -> List[Expense]:
        """Get this month's expenses."""
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.get_expenses(date_from=month_start)
    
    def get_undescribed(self) -> List[Expense]:
        """Get expenses that don't have descriptions yet."""
        expenses, _, _ = self._load_data()
        return [e for e in expenses if not e.has_description]
    
    def get_summary(self, expenses: List[Expense]) -> Dict[str, float]:
        """Get spending totals by category.
        
        Args:
            expenses: List of expenses to summarize
            
        Returns:
            Dict of category -> total amount
        """
        summary = {}
        for expense in expenses:
            cat = expense.category or "Uncategorized"
            summary[cat] = summary.get(cat, 0) + expense.amount
        return dict(sorted(summary.items(), key=lambda x: x[1], reverse=True))
    
    def delete_expense(self, expense_id: int) -> bool:
        """Delete an expense by ID.
        
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            try:
                expenses, next_id, processed_emails = self._load_data()
                
                original_count = len(expenses)
                expenses = [e for e in expenses if e.id != expense_id]
                
                if len(expenses) == original_count:
                    return False
                
                self._save_data(expenses, next_id, processed_emails)
                logger.info(f"Expenses: Deleted #{expense_id}")
                return True
                
            except Exception as e:
                logger.error(f"Expenses: Error deleting expense: {e}")
                return False
    
    def is_email_processed(self, email_id: str) -> bool:
        """Check if an email has already been processed."""
        _, _, processed_emails = self._load_data()
        return email_id in processed_emails
