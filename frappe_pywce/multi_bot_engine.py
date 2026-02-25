"""
Multi-Bot Routing Engine for Frappe Pywce

This engine supports multiple chatbots with level-based routing.
Each bot has unique levels in format: {bot_slug}::{level_name}

Routing Priority:
1. Check if user has active session → get current_level and bot
2. Match input against current template's routes
3. If no match, check next_level fallback from last message
4. If no session, find bot by trigger patterns
5. If still no match, use default bot or global fallback
"""

import re
import json
from typing import Optional, Dict, Any, List, Tuple

import frappe

from frappe_pywce.pywce_logger import app_logger as logger


class MultiBotEngine:
    """
    Multi-bot routing engine with level-based conversation state management.
    
    Level Format: "{bot_slug}::{level_name}"
    Example: "salesbot::welcome", "supportbot::ticket_created"
    """
    
    def __init__(self):
        self._bot_cache: Dict[str, Any] = {}
        self._template_cache: Dict[str, Any] = {}
    
    # ========== Bot Management ==========
    
    def get_all_active_bots(self) -> List[Dict]:
        """Get all active bots"""
        bots = frappe.get_all(
            "Chat Bot",
            filters={"is_active": 1},
            fields=["name", "bot_name", "bot_slug", "trigger_patterns", "start_template_id", "is_default", "flow_json"]
        )
        return bots
    
    def get_bot(self, bot_slug: str) -> Optional[Any]:
        """Get bot document by slug"""
        if bot_slug in self._bot_cache:
            return self._bot_cache[bot_slug]
        
        if frappe.db.exists("Chat Bot", bot_slug):
            bot = frappe.get_doc("Chat Bot", bot_slug)
            self._bot_cache[bot_slug] = bot
            return bot
        return None
    
    def get_default_bot(self) -> Optional[Any]:
        """Get the default bot"""
        bot_name = frappe.db.get_value("Chat Bot", {"is_default": 1, "is_active": 1}, "name")
        if bot_name:
            return self.get_bot(bot_name)
        
        # Fallback to first active bot
        first_bot = frappe.db.get_value("Chat Bot", {"is_active": 1}, "name", order_by="creation asc")
        if first_bot:
            return self.get_bot(first_bot)
        return None
    
    def find_bot_by_trigger(self, input_text: str) -> Optional[Any]:
        """Find bot whose trigger pattern matches input"""
        text = (input_text or "").strip().lower()
        
        bots = self.get_all_active_bots()
        for bot_data in bots:
            trigger_patterns = bot_data.get("trigger_patterns")
            if trigger_patterns:
                try:
                    patterns = json.loads(trigger_patterns) if isinstance(trigger_patterns, str) else trigger_patterns
                    if isinstance(patterns, list):
                        for pattern in patterns:
                            try:
                                if re.search(pattern, text, re.IGNORECASE):
                                    logger.info(f"Bot '{bot_data['bot_slug']}' matched trigger pattern '{pattern}'")
                                    return self.get_bot(bot_data["name"])
                            except re.error:
                                continue
                except (json.JSONDecodeError, TypeError):
                    continue
        
        return None
    
    # ========== Session Management ==========
    
    def get_user_session(self, phone_number: str) -> Optional[Any]:
        """Get active session for phone number"""
        from frappe_pywce.frappe_pywce.doctype.user_bot_session.user_bot_session import UserBotSession
        return UserBotSession.get_active_session(phone_number)
    
    def create_session(self, phone_number: str, bot_slug: str, start_level: str = None) -> Any:
        """Create new session for phone number"""
        from frappe_pywce.frappe_pywce.doctype.user_bot_session.user_bot_session import UserBotSession
        return UserBotSession.create_session(phone_number, bot_slug, start_level)
    
    def update_session_level(self, phone_number: str, new_level: str):
        """Update user's current level in session"""
        session = self.get_user_session(phone_number)
        if session:
            session.set_level(new_level)
            session.update_activity()
            logger.debug(f"Updated session for {phone_number} to level: {new_level}")
    
    def end_session(self, phone_number: str):
        """End user's current session"""
        session = self.get_user_session(phone_number)
        if session:
            session.end_session()
            logger.info(f"Ended session for {phone_number}")
    
    # ========== Template Management ==========
    
    def get_bot_templates(self, bot_slug: str) -> List[Dict]:
        """Get all templates for a bot from its flow_json"""
        bot = self.get_bot(bot_slug)
        if not bot:
            return []
        return bot.get_templates()
    
    def get_template_by_id(self, bot_slug: str, template_id: str) -> Optional[Dict]:
        """Get template by ID from bot's flow"""
        cache_key = f"{bot_slug}:{template_id}"
        if cache_key in self._template_cache:
            return self._template_cache[cache_key]
        
        bot = self.get_bot(bot_slug)
        if bot:
            template = bot.get_template_by_id(template_id)
            if template:
                self._template_cache[cache_key] = template
                return template
        return None
    
    def get_template_by_level(self, level_id: str) -> Optional[Tuple[str, Dict]]:
        """
        Get template by level ID.
        Returns tuple of (bot_slug, template) or None
        """
        if not level_id or "::" not in level_id:
            return None
        
        bot_slug = level_id.split("::")[0]
        bot = self.get_bot(bot_slug)
        if not bot:
            return None
        
        templates = bot.get_templates()
        for template in templates:
            settings = template.get("settings", {})
            if settings.get("message_level") == level_id:
                return (bot_slug, template)
        
        return None
    
    def get_start_template(self, bot_slug: str) -> Optional[Dict]:
        """Get start template for a bot"""
        bot = self.get_bot(bot_slug)
        if bot:
            return bot.get_start_template()
        return None
    
    # ========== Route Matching ==========
    
    def find_route_match(self, bot_slug: str, from_template_id: str, input_text: str) -> Optional[Dict]:
        """
        Find matching route from a template based on input.
        Returns the connected template if match found.
        """
        template = self.get_template_by_id(bot_slug, from_template_id)
        if not template:
            return None
        
        routes = template.get("routes", [])
        text = (input_text or "").strip().lower()
        
        # Sort routes by priority (if available)
        sorted_routes = sorted(routes, key=lambda r: r.get("priority", 0), reverse=True)
        
        for route in sorted_routes:
            pattern = route.get("pattern", "")
            if not pattern:
                continue
            
            # Try regex match first
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    connected_to = route.get("connectedTo")
                    if connected_to:
                        connected_template = self.get_template_by_id(bot_slug, connected_to)
                        if connected_template:
                            logger.info(f"Route match: '{text}' matched pattern '{pattern}' -> {connected_to}")
                            return connected_template
            except re.error:
                # Try exact match
                if text == pattern.lower():
                    connected_to = route.get("connectedTo")
                    if connected_to:
                        connected_template = self.get_template_by_id(bot_slug, connected_to)
                        if connected_template:
                            return connected_template
        
        return None
    
    # ========== Main Routing Logic ==========
    
    def find_response_template(self, phone_number: str, input_text: str) -> Optional[Tuple[str, Dict]]:
        """
        Main routing method. Finds appropriate response template.
        
        Returns tuple of (bot_slug, template) or None
        
        Routing Priority:
        1. Get active session → find routes from current template
        2. Check next_level fallback from last outgoing message
        3. No session → find bot by trigger pattern
        4. No trigger match → use default bot's start template
        """
        text = (input_text or "").strip()
        
        # Step 1: Check if user has active session
        session = self.get_user_session(phone_number)
        
        if session and session.current_bot and session.is_active:
            bot_slug = session.current_bot
            current_level = session.current_level
            
            logger.info(f"Active session found for {phone_number}: bot={bot_slug}, level={current_level}")
            
            # Find current template from level
            if current_level:
                result = self.get_template_by_level(current_level)
                if result:
                    _, current_template = result
                    current_template_id = current_template.get("id")
                    
                    # Try to find route match
                    matched_template = self.find_route_match(bot_slug, current_template_id, text)
                    if matched_template:
                        return (bot_slug, matched_template)
                    
                    # Check next_level fallback
                    settings = current_template.get("settings", {})
                    next_level = settings.get("next_level")
                    if next_level:
                        next_result = self.get_template_by_level(next_level)
                        if next_result:
                            logger.info(f"Using next_level fallback: {next_level}")
                            return next_result
            
            # Try to match against bot's trigger patterns for re-entry
            bot = self.get_bot(bot_slug)
            if bot and bot.matches_trigger(text):
                start_template = self.get_start_template(bot_slug)
                if start_template:
                    logger.info(f"Re-triggering bot {bot_slug} from start")
                    return (bot_slug, start_template)
            
            # Return fallback message template
            return self._create_fallback_template(bot_slug, text)
        
        # Step 2: No active session - find bot by trigger
        triggered_bot = self.find_bot_by_trigger(text)
        if triggered_bot:
            bot_slug = triggered_bot.bot_slug
            
            # Create new session
            start_template = self.get_start_template(bot_slug)
            if start_template:
                start_level = start_template.get("settings", {}).get("message_level")
                self.create_session(phone_number, bot_slug, start_level)
                logger.info(f"Created new session for {phone_number} with bot {bot_slug}")
                return (bot_slug, start_template)
        
        # Step 3: No trigger match - use default bot
        default_bot = self.get_default_bot()
        if default_bot:
            bot_slug = default_bot.bot_slug
            start_template = self.get_start_template(bot_slug)
            if start_template:
                start_level = start_template.get("settings", {}).get("message_level")
                self.create_session(phone_number, bot_slug, start_level)
                logger.info(f"Using default bot {bot_slug} for {phone_number}")
                return (bot_slug, start_template)
        
        logger.warning(f"No matching bot or template found for {phone_number}")
        return None
    
    def _create_fallback_template(self, bot_slug: str, input_text: str) -> Optional[Tuple[str, Dict]]:
        """Create a fallback text template when no route matches"""
        bot = self.get_bot(bot_slug)
        fallback_message = "Sorry, I didn't understand that. Please try again."
        
        if bot and bot.fallback_message:
            fallback_message = bot.fallback_message
        
        fallback_template = {
            "id": f"{bot_slug}_fallback",
            "name": "Fallback",
            "type": "text",
            "message": {"body": fallback_message},
            "settings": {},
            "routes": []
        }
        
        return (bot_slug, fallback_template)
    
    # ========== Template Sending ==========
    
    def process_and_send(self, phone_number: str, input_text: str) -> Optional[Dict]:
        """
        Main entry point: find template and send response.
        Returns the response data or None.
        """
        result = self.find_response_template(phone_number, input_text)
        
        if not result:
            logger.warning(f"No response template found for {phone_number}")
            return None
        
        bot_slug, template = result
        
        # Send the template
        from frappe_pywce.multi_bot_sender import MultiBotSender
        sender = MultiBotSender(phone_number, bot_slug)
        response = sender.send_template(template)
        
        # Update session level
        if response and response.get("success"):
            settings = template.get("settings", {})
            new_level = settings.get("message_level") or settings.get("next_level")
            if new_level:
                self.update_session_level(phone_number, new_level)
        
        return response


# Convenience function
def process_multi_bot_message(phone_number: str, input_text: str) -> Optional[Dict]:
    """
    Process incoming message with multi-bot support.
    Returns response data or None.
    """
    engine = MultiBotEngine()
    return engine.process_and_send(phone_number, input_text)
