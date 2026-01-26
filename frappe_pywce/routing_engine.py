"""
Routing Engine for Frappe Pywce Chatbot

This engine determines the appropriate response template based on:
1. Exact route match from current template's routes
2. Fallback to next_level from last sent message
3. Trigger pattern matching for entry points
"""

import re
from typing import Optional, Dict, Any, List

import frappe

from frappe_pywce.pywce_logger import app_logger as logger


class RoutingEngine:
    """
    Stateful routing engine that finds the appropriate template response
    based on user input and conversation state.
    """
    
    def __init__(self, chatbot: Dict[str, Any]):
        """
        Initialize the routing engine with a chatbot configuration.
        
        Args:
            chatbot: The chatbot dict containing 'templates' list
        """
        self.chatbot = chatbot
        self.templates = chatbot.get('templates', []) if chatbot else []
        self._template_map = self._build_template_map()
    
    def _build_template_map(self) -> Dict[str, Dict]:
        """Build a map of template_id -> template for quick lookup"""
        return {t.get('id'): t for t in self.templates if t.get('id')}
    
    def get_template_by_id(self, template_id: str) -> Optional[Dict]:
        """Get a template by its ID"""
        return self._template_map.get(template_id)
    
    def find_response_template(self, phone_number: str, incoming_message: str) -> Optional[Dict]:
        """
        Find the appropriate response template for an incoming message.
        
        Strategy:
        1. Get the current template (from last sent message's template_id or message_level)
        2. Check current template's routes for exact match → return connectedTo template
        3. If no route match, check next_level fallback
        4. If still no match, check trigger patterns for entry points
        
        Args:
            phone_number: The user's phone number (normalized)
            incoming_message: The incoming message text
            
        Returns:
            The matching template dict, or None if no match found
        """
        if not self.templates:
            logger.warning("No templates available in chatbot")
            return None
        
        incoming_text = (incoming_message or "").strip().lower()
        
        # Step 1: Get the last outgoing message info
        last_message_info = self._get_last_outgoing_message(phone_number)
        
        if last_message_info:
            # Step 2: Try exact route match from current template
            current_template_id = last_message_info.get('template_id')
            current_template = self.get_template_by_id(current_template_id) if current_template_id else None
            
            if current_template:
                route_match = self._find_route_match(current_template, incoming_text)
                if route_match:
                    connected_template_id = route_match.get('connectedTo')
                    connected_template = self.get_template_by_id(connected_template_id)
                    if connected_template:
                        logger.info(
                            f"Route match: '{incoming_text}' -> template '{connected_template.get('name', connected_template_id)}'"
                        )
                        return connected_template
            
            # Step 3: Fallback to next_level matching
            next_level = last_message_info.get('next_level')
            if next_level:
                level_template = self._find_template_by_message_level(next_level)
                if level_template:
                    logger.info(
                        f"Level match: next_level '{next_level}' -> template '{level_template.get('name', level_template.get('id'))}'"
                    )
                    return level_template
        
        # Step 4: Check trigger patterns for entry points (e.g., "hi", "start")
        trigger_template = self._find_template_by_trigger(incoming_text, incoming_message)
        if trigger_template:
            logger.info(
                f"Trigger match: '{incoming_text}' -> template '{trigger_template.get('name', trigger_template.get('id'))}'"
            )
            return trigger_template
        
        # Step 5: Find start template as last resort
        start_template = self._find_start_template()
        if start_template:
            logger.info(f"No match found, using start template: '{start_template.get('name', start_template.get('id'))}'")
            return start_template
        
        logger.warning(f"No matching template found for message: '{incoming_text}' from {phone_number}")
        return None
    
    def _get_last_outgoing_message(self, phone_number: str) -> Optional[Dict]:
        """
        Get the last outgoing message sent to this phone number.
        
        Returns dict with: template_id, message_level, next_level
        """
        try:
            last_message = frappe.get_all(
                "WhatsApp Chat Message",
                filters={
                    "phone_number": phone_number,
                    "direction": "Outgoing"
                },
                fields=["template_id", "message_level", "next_level"],
                order_by="timestamp desc",
                limit=1
            )
            
            if last_message:
                return last_message[0]
                
        except Exception as e:
            logger.error(f"Error fetching last outgoing message: {str(e)}")
        
        return None
    
    def _find_route_match(self, template: Dict, incoming_text: str) -> Optional[Dict]:
        """
        Find a matching route in the template's routes.
        
        First checks for exact match, then regex patterns.
        
        Args:
            template: The current template dict
            incoming_text: Normalized (lowercase, stripped) incoming message
            
        Returns:
            The matching route dict, or None
        """
        routes = template.get('routes', [])
        
        # First pass: exact matches (non-regex)
        for route in routes:
            pattern = (route.get('pattern') or "").strip().lower()
            is_regex = route.get('isRegex', False)
            
            if not is_regex:
                # Exact match (case-insensitive)
                if pattern == incoming_text:
                    return route
                # Partial match - pattern contained in input
                if pattern and pattern in incoming_text:
                    return route
        
        # Second pass: regex patterns
        for route in routes:
            pattern = route.get('pattern', '')
            is_regex = route.get('isRegex', False)
            
            if is_regex and pattern:
                try:
                    if re.match(pattern, incoming_text, re.IGNORECASE):
                        return route
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{pattern}': {e}")
                    continue
        
        return None
    
    def _find_template_by_message_level(self, level: str) -> Optional[Dict]:
        """Find template where settings.message_level matches the given level"""
        for template in self.templates:
            settings = template.get('settings', {})
            if settings.get('message_level') == level:
                return template
        return None
    
    def _find_template_by_trigger(self, incoming_text: str, original_message: str) -> Optional[Dict]:
        """Find template by trigger pattern in settings"""
        for template in self.templates:
            settings = template.get('settings', {})
            trigger = settings.get('trigger', '')
            
            if not trigger:
                continue
            
            try:
                # Try regex match first
                if re.match(trigger, original_message, re.IGNORECASE):
                    return template
            except re.error:
                # Fallback to simple contains check
                if trigger.lower() in incoming_text:
                    return template
        
        return None
    
    def _find_start_template(self) -> Optional[Dict]:
        """Find the template marked as start (isStart: true)"""
        for template in self.templates:
            settings = template.get('settings', {})
            if settings.get('isStart'):
                return template
        return None


def get_response_template(chatbot: Dict, phone_number: str, incoming_message: str) -> Optional[Dict]:
    """
    Convenience function to find response template.
    
    Args:
        chatbot: The chatbot configuration dict
        phone_number: User's phone number
        incoming_message: The incoming message text
        
    Returns:
        The matching template dict, or None
    """
    engine = RoutingEngine(chatbot)
    return engine.find_response_template(phone_number, incoming_message)
