# Copyright (c) 2026, donnc and contributors
# For license information, please see license.txt

import json
import frappe
from frappe.model.document import Document


class UserBotSession(Document):
    def before_insert(self):
        self.session_start = frappe.utils.now_datetime()
        self.last_activity = frappe.utils.now_datetime()
        self.message_count = 0
    
    def before_save(self):
        self.last_activity = frappe.utils.now_datetime()
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = frappe.utils.now_datetime()
        self.message_count = (self.message_count or 0) + 1
        self.save(ignore_permissions=True)
    
    def set_level(self, level_id, template_name=None):
        """Update current level"""
        self.current_level = level_id
        if template_name:
            # Find template by level_id
            template = frappe.db.get_value(
                "Bot Template",
                {"level_id": level_id},
                "name"
            )
            if template:
                self.current_template = template
        self.save(ignore_permissions=True)
    
    def get_session_data(self):
        """Get parsed session data"""
        if not self.session_data:
            return {}
        try:
            return json.loads(self.session_data) if isinstance(self.session_data, str) else self.session_data
        except json.JSONDecodeError:
            return {}
    
    def set_session_data(self, key, value):
        """Set a key in session data"""
        data = self.get_session_data()
        data[key] = value
        self.session_data = json.dumps(data)
        self.save(ignore_permissions=True)
    
    def get_context_data(self):
        """Get parsed context data"""
        if not self.context_data:
            return {}
        try:
            return json.loads(self.context_data) if isinstance(self.context_data, str) else self.context_data
        except json.JSONDecodeError:
            return {}
    
    def end_session(self):
        """End the current session"""
        self.is_active = 0
        self.save(ignore_permissions=True)
    
    @staticmethod
    def get_active_session(phone_number):
        """Get active session for a phone number"""
        session_name = frappe.db.get_value(
            "User Bot Session",
            {"phone_number": phone_number, "is_active": 1},
            "name",
            order_by="last_activity desc"
        )
        if session_name:
            return frappe.get_doc("User Bot Session", session_name)
        return None
    
    @staticmethod
    def create_session(phone_number, bot_slug, start_level=None):
        """Create a new session for a phone number"""
        # End any existing active sessions
        frappe.db.set_value(
            "User Bot Session",
            {"phone_number": phone_number, "is_active": 1},
            "is_active",
            0
        )
        
        # Create new session
        session = frappe.get_doc({
            "doctype": "User Bot Session",
            "phone_number": phone_number,
            "current_bot": bot_slug,
            "current_level": start_level,
            "is_active": 1,
            "session_data": "{}",
            "context_data": "{}"
        })
        session.insert(ignore_permissions=True)
        frappe.db.commit()
        return session
