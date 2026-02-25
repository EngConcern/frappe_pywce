# Copyright (c) 2026, donnc and contributors
# For license information, please see license.txt

import re
import frappe
from frappe.model.document import Document


class BotRoute(Document):
    def before_insert(self):
        self._generate_route_id()
    
    def before_save(self):
        self._populate_levels()
        self._validate_pattern()
        self._validate_same_bot()
    
    def _generate_route_id(self):
        """Generate unique route ID"""
        if not self.route_id:
            random_part = frappe.generate_hash(length=8)
            self.route_id = f"route_{random_part}"
    
    def _populate_levels(self):
        """Auto-populate level IDs from linked templates"""
        if self.from_template:
            from_doc = frappe.get_doc("Bot Template", self.from_template)
            self.from_level = from_doc.level_id
        
        if self.to_template:
            to_doc = frappe.get_doc("Bot Template", self.to_template)
            self.to_level = to_doc.level_id
    
    def _validate_pattern(self):
        """Validate pattern is valid regex if is_regex is checked"""
        if self.is_regex and self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as e:
                frappe.throw(f"Invalid regex pattern: {str(e)}")
    
    def _validate_same_bot(self):
        """Ensure from_template and to_template belong to same bot"""
        if self.from_template and self.to_template:
            from_doc = frappe.get_doc("Bot Template", self.from_template)
            to_doc = frappe.get_doc("Bot Template", self.to_template)
            
            if from_doc.bot != to_doc.bot:
                frappe.throw("From Template and To Template must belong to the same bot")
            
            # Auto-set bot if not set
            if not self.bot:
                self.bot = from_doc.bot
    
    def matches(self, input_text):
        """Check if input matches this route's pattern"""
        if not self.pattern:
            return False
        
        text = input_text.strip().lower() if input_text else ""
        pattern = self.pattern.strip()
        
        if self.is_regex:
            try:
                return bool(re.search(pattern, text, re.IGNORECASE))
            except re.error:
                return False
        else:
            # Exact match (case-insensitive)
            return text == pattern.lower()
