# Copyright (c) 2026, donnc and contributors
# For license information, please see license.txt

import re
import frappe
from frappe.model.document import Document


class BotTemplate(Document):
    def before_insert(self):
        self._generate_template_id()
        self._generate_level_id()
    
    def before_save(self):
        self._validate_template_type()
        self._validate_trigger_pattern()
        
        # Ensure only one start template per bot
        if self.is_start:
            frappe.db.set_value(
                "Bot Template",
                {"bot": self.bot, "is_start": 1, "name": ("!=", self.name)},
                "is_start",
                0
            )
    
    def _generate_template_id(self):
        """Generate unique template ID"""
        if not self.template_id:
            bot_slug = ""
            if self.bot:
                bot_doc = frappe.get_doc("Chat Bot", self.bot)
                bot_slug = bot_doc.bot_slug or self.bot
            
            # Sanitize template name
            name_part = re.sub(r'[^a-z0-9]', '_', self.template_name.lower().strip())
            random_part = frappe.generate_hash(length=6)
            
            self.template_id = f"{bot_slug}_{name_part}_{random_part}"
    
    def _generate_level_id(self):
        """Generate level ID in format bot_slug::level_name"""
        if not self.level_id:
            bot_slug = ""
            if self.bot:
                bot_doc = frappe.get_doc("Chat Bot", self.bot)
                bot_slug = bot_doc.bot_slug or self.bot
            
            # Use template name as level name
            level_name = re.sub(r'[^a-z0-9_]', '_', self.template_name.lower().strip())
            self.level_id = f"{bot_slug}::{level_name}"
    
    def _validate_template_type(self):
        """Validate template type and message_data compatibility"""
        valid_types = ['text', 'button', 'list', 'cta', 'request-location', 'media', 'location', 'contacts', 'flow', 'template']
        if self.template_type not in valid_types:
            frappe.throw(f"Invalid template type: {self.template_type}")
    
    def _validate_trigger_pattern(self):
        """Validate trigger pattern is valid regex"""
        if self.trigger_pattern:
            try:
                re.compile(self.trigger_pattern)
            except re.error as e:
                frappe.throw(f"Invalid trigger pattern regex: {str(e)}")
    
    def get_message_data(self):
        """Get parsed message data"""
        import json
        if not self.message_data:
            return {}
        
        try:
            return json.loads(self.message_data) if isinstance(self.message_data, str) else self.message_data
        except json.JSONDecodeError:
            return {}
    
    def get_settings(self):
        """Get parsed settings"""
        import json
        if not self.settings:
            return {}
        
        try:
            return json.loads(self.settings) if isinstance(self.settings, str) else self.settings
        except json.JSONDecodeError:
            return {}
    
    def to_flow_template(self):
        """Convert to flow JSON template format"""
        return {
            "id": self.template_id,
            "name": self.template_name,
            "type": self.template_type,
            "message": self.get_message_data(),
            "settings": {
                **self.get_settings(),
                "isStart": self.is_start,
                "message_level": self.level_id,
                "next_level": self.next_level or "",
                "trigger": self.trigger_pattern or ""
            },
            "routes": [],  # Routes handled separately
            "position": {
                "x": self.position_x or 0,
                "y": self.position_y or 0
            }
        }
