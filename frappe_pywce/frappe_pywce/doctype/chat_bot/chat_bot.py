# Copyright (c) 2026, donnc and contributors
# For license information, please see license.txt

import re
import frappe
from frappe.model.document import Document


class ChatBot(Document):
    def before_insert(self):
        self.created_by = frappe.session.user
        self._generate_slug()
    
    def before_save(self):
        self._generate_slug()
        self._validate_trigger_patterns()
        self._update_template_count()
        
        # Ensure only one default bot
        if self.is_default:
            frappe.db.set_value(
                "Chat Bot",
                {"is_default": 1, "name": ("!=", self.name)},
                "is_default",
                0
            )
    
    def _generate_slug(self):
        """Generate URL-safe slug from bot name"""
        if self.bot_name and not self.bot_slug:
            # Convert to lowercase, replace spaces with hyphens, remove special chars
            slug = self.bot_name.lower().strip()
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'[\s_-]+', '-', slug)
            slug = slug.strip('-')
            
            # Ensure uniqueness
            base_slug = slug
            counter = 1
            while frappe.db.exists("Chat Bot", {"bot_slug": slug, "name": ("!=", self.name or "")}):
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            self.bot_slug = slug
    
    def _validate_trigger_patterns(self):
        """Validate trigger patterns are valid regex"""
        if self.trigger_patterns:
            import json
            try:
                patterns = json.loads(self.trigger_patterns) if isinstance(self.trigger_patterns, str) else self.trigger_patterns
                if isinstance(patterns, list):
                    for pattern in patterns:
                        try:
                            re.compile(pattern)
                        except re.error as e:
                            frappe.throw(f"Invalid regex pattern '{pattern}': {str(e)}")
            except json.JSONDecodeError:
                frappe.throw("Trigger patterns must be a valid JSON array")
    
    def _update_template_count(self):
        """Update total templates count from flow_json"""
        if self.flow_json:
            import json
            try:
                flow = json.loads(self.flow_json) if isinstance(self.flow_json, str) else self.flow_json
                templates = flow.get('templates', [])
                self.total_templates = len(templates)
            except (json.JSONDecodeError, AttributeError):
                self.total_templates = 0
    
    def get_templates(self):
        """Get all templates from flow_json"""
        import json
        if not self.flow_json:
            return []
        
        try:
            flow = json.loads(self.flow_json) if isinstance(self.flow_json, str) else self.flow_json
            return flow.get('templates', [])
        except (json.JSONDecodeError, AttributeError):
            return []
    
    def get_template_by_id(self, template_id):
        """Get a specific template by ID"""
        templates = self.get_templates()
        for template in templates:
            if template.get('id') == template_id:
                return template
        return None
    
    def get_start_template(self):
        """Get the start template for this bot"""
        if self.start_template_id:
            return self.get_template_by_id(self.start_template_id)
        
        # Find template marked as start
        templates = self.get_templates()
        for template in templates:
            settings = template.get('settings', {})
            if settings.get('isStart'):
                return template
        
        # Return first template as fallback
        return templates[0] if templates else None
    
    def matches_trigger(self, text):
        """Check if input text matches any trigger pattern"""
        import json
        if not self.trigger_patterns:
            return False
        
        try:
            patterns = json.loads(self.trigger_patterns) if isinstance(self.trigger_patterns, str) else self.trigger_patterns
            if isinstance(patterns, list):
                for pattern in patterns:
                    try:
                        if re.search(pattern, text, re.IGNORECASE):
                            return True
                    except re.error:
                        continue
        except (json.JSONDecodeError, TypeError):
            pass
        
        return False
