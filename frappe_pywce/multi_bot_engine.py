"""
Multi-Bot Routing Engine for Frappe Pywce

This engine supports multiple chatbots using the studio's chatbots array format.
Reads from ChatBot Config.flow_json which contains:
{
    "chatbots": [
        {"name": "Bot1", "templates": [...]},
        {"name": "Bot2", "templates": [...]}
    ],
    "version": "1.0"
}

Routing Priority:
1. Check if user has active session → get current_level and bot
2. Match input against current template's routes
3. If no match, check next_level fallback from last message
4. If no session, find bot by trigger patterns (from template settings)
5. If still no match, use default bot (first in array) or global fallback
"""

import re
import json
from typing import Optional, Dict, Any, List, Tuple

import frappe

from frappe_pywce.pywce_logger import app_logger as logger


class MultiBotEngine:
    """
    Multi-bot routing engine using studio's chatbots array format.
    
    Reads bots from ChatBot Config.flow_json chatbots array.
    Level Format: Uses template settings.message_level or template id/name.
    """
    
    def __init__(self):
        self._flow_data: Optional[Dict] = None
        self._bots_cache: Optional[List[Dict]] = None
        self._template_map: Dict[str, Tuple[Dict, str]] = {}  # template_id -> (template, bot_name)
    
    def _load_flow_data(self) -> Dict:
        """Load flow data from ChatBot Config"""
        if self._flow_data is not None:
            return self._flow_data
        
        try:
            flow_json = frappe.db.get_single_value("ChatBot Config", "flow_json")
            if flow_json:
                self._flow_data = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
            else:
                self._flow_data = {"chatbots": [], "version": "1.0"}
        except Exception as e:
            logger.error(f"Error loading flow data: {e}")
            self._flow_data = {"chatbots": [], "version": "1.0"}
        
        return self._flow_data
    
    # ========== Bot Management ==========
    
    def get_all_bots(self) -> List[Dict]:
        """Get all chatbots from flow_json"""
        if self._bots_cache is not None:
            return self._bots_cache
        
        flow_data = self._load_flow_data()
        
        # Handle both old and new formats
        if "chatbots" in flow_data and isinstance(flow_data["chatbots"], list):
            self._bots_cache = flow_data["chatbots"]
        elif "templates" in flow_data:
            # Old single-bot format - wrap in chatbots array
            chatbot_name = frappe.db.get_single_value("ChatBot Config", "chatbot_name") or "Default Bot"
            self._bots_cache = [{"name": chatbot_name, "templates": flow_data["templates"]}]
        else:
            self._bots_cache = []
        
        # Build template map for quick lookup
        self._build_template_map()
        
        return self._bots_cache
    
    def _build_template_map(self):
        """Build a map of template_id -> (template, bot_name) for quick lookup"""
        self._template_map = {}
        for bot in (self._bots_cache or []):
            bot_name = bot.get("name", "")
            for template in bot.get("templates", []):
                template_id = template.get("id", "")
                if template_id:
                    self._template_map[template_id] = (template, bot_name)
                # Also map by name if different
                template_name = template.get("name", "")
                if template_name and template_name != template_id:
                    self._template_map[template_name] = (template, bot_name)
    
    def get_bot(self, bot_name: str) -> Optional[Dict]:
        """Get bot by name"""
        bots = self.get_all_bots()
        for bot in bots:
            if bot.get("name", "").lower() == bot_name.lower():
                return bot
        return None
    
    def get_default_bot(self) -> Optional[Dict]:
        """Get the default bot (first in the chatbots array)"""
        bots = self.get_all_bots()
        if bots:
            return bots[0]
        return None
    
    def find_bot_by_trigger(self, input_text: str) -> Optional[Dict]:
        """Find bot whose template has a matching trigger pattern"""
        text = (input_text or "").strip().lower()
        
        bots = self.get_all_bots()
        for bot in bots:
            templates = bot.get("templates", [])
            for template in templates:
                settings = template.get("settings", {})
                trigger = settings.get("trigger")
                if trigger:
                    try:
                        if re.search(trigger, text, re.IGNORECASE):
                            logger.info(f"Bot '{bot.get('name')}' matched trigger '{trigger}'")
                            return bot
                    except re.error:
                        # Try exact match if regex fails
                        if trigger.lower() == text:
                            return bot
        
        return None
    
    # ========== Session Management ==========
    
    def get_user_session(self, phone_number: str) -> Optional[Dict]:
        """Get active session for phone number from cache/db"""
        session = frappe.cache().hget("multi_bot_session", phone_number)
        if session:
            try:
                return json.loads(session) if isinstance(session, str) else session
            except:
                pass
        return None
    
    def create_session(self, phone_number: str, bot_name: str, start_level: str = None) -> Dict:
        """Create new session for phone number using Redis cache"""
        session = {
            "phone_number": phone_number,
            "bot_name": bot_name,
            "current_level": start_level,
            "is_active": True,
            "created_at": frappe.utils.now()
        }
        frappe.cache().hset("multi_bot_session", phone_number, json.dumps(session))
        return session
    
    def update_session_level(self, phone_number: str, new_level: str):
        """Update user's current level in session"""
        session = self.get_user_session(phone_number)
        if session:
            session["current_level"] = new_level
            session["last_activity"] = frappe.utils.now()
            frappe.cache().hset("multi_bot_session", phone_number, json.dumps(session))
            logger.debug(f"Updated session for {phone_number} to level: {new_level}")
    
    def end_session(self, phone_number: str):
        """End user's current session"""
        frappe.cache().hdel("multi_bot_session", phone_number)
        logger.info(f"Ended session for {phone_number}")
    
    # ========== Template Management ==========
    
    def get_bot_templates(self, bot_name: str) -> List[Dict]:
        """Get all templates for a bot"""
        bot = self.get_bot(bot_name)
        if not bot:
            return []
        return bot.get("templates", [])
    
    def get_template_by_id(self, bot_name: str, template_id: str) -> Optional[Dict]:
        """Get template by ID from bot's templates"""
        # First check the pre-built template map
        if template_id in self._template_map:
            template, mapped_bot = self._template_map[template_id]
            if mapped_bot.lower() == bot_name.lower():
                return template
        
        # Fallback to searching
        bot = self.get_bot(bot_name)
        if not bot:
            return None
        
        for template in bot.get("templates", []):
            if template.get("id") == template_id or template.get("name") == template_id:
                return template
        return None
    
    def get_template_by_level(self, bot_name: str, level_id: str) -> Optional[Dict]:
        """Get template by message_level setting"""
        bot = self.get_bot(bot_name)
        if not bot:
            return None
        
        for template in bot.get("templates", []):
            settings = template.get("settings", {})
            if settings.get("message_level") == level_id:
                return template
            # Also check template id/name as fallback
            if template.get("id") == level_id or template.get("name") == level_id:
                return template
        
        return None
    
    def get_start_template(self, bot_name: str) -> Optional[Dict]:
        """Get start template for a bot (marked with isStart setting)"""
        bot = self.get_bot(bot_name)
        if not bot:
            return None
        
        templates = bot.get("templates", [])
        
        # Find template with isStart=True
        for template in templates:
            settings = template.get("settings", {})
            if settings.get("isStart"):
                return template
        
        # Fallback to first template
        if templates:
            return templates[0]
        
        return None
    
    # ========== Route Matching ==========
    
    def find_route_match(self, bot_name: str, from_template_id: str, input_text: str) -> Optional[Dict]:
        """
        Find matching route from a template based on input.
        Returns the connected template if match found.
        """
        template = self.get_template_by_id(bot_name, from_template_id)
        if not template:
            return None
        
        routes = template.get("routes", [])
        text = (input_text or "").strip()
        
        for route in routes:
            pattern = route.get("pattern", "")
            is_regex = route.get("isRegex", True)
            connected_to = route.get("connectedTo")
            
            if not connected_to:
                continue
            
            matched = False
            
            # Handle "any" pattern (match everything)
            if pattern == ".*" or pattern == "":
                matched = True
            elif is_regex:
                try:
                    if re.search(pattern, text, re.IGNORECASE):
                        matched = True
                except re.error:
                    # Fallback to exact match
                    if text.lower() == pattern.lower():
                        matched = True
            else:
                # Exact match
                if text.lower() == pattern.lower():
                    matched = True
            
            if matched:
                connected_template = self.get_template_by_id(bot_name, connected_to)
                if connected_template:
                    logger.info(f"Route match: '{text}' matched pattern '{pattern}' -> {connected_to}")
                    return connected_template
        
        return None
    
    # ========== Main Routing Logic ==========
    
    def find_response_template(self, phone_number: str, input_text: str) -> Optional[Tuple[str, Dict]]:
        """
        Main routing method. Finds appropriate response template.
        
        Returns tuple of (bot_name, template) or None
        
        Routing Priority:
        1. Get active session → find routes from current template
        2. Check next_level fallback
        3. No session → find bot by trigger pattern
        4. No trigger match → use default bot's start template
        """
        text = (input_text or "").strip()
        
        # Step 1: Check if user has active session
        session = self.get_user_session(phone_number)
        
        if session and session.get("bot_name") and session.get("is_active"):
            bot_name = session["bot_name"]
            current_level = session.get("current_level")
            
            logger.info(f"Active session for {phone_number}: bot={bot_name}, level={current_level}")
            
            # Find current template from level
            if current_level:
                current_template = self.get_template_by_level(bot_name, current_level)
                if current_template:
                    template_id = current_template.get("id")
                    
                    # Try to find route match
                    matched_template = self.find_route_match(bot_name, template_id, text)
                    if matched_template:
                        return (bot_name, matched_template)
                    
                    # Check next_level fallback
                    settings = current_template.get("settings", {})
                    next_level = settings.get("next_level")
                    if next_level:
                        next_template = self.get_template_by_level(bot_name, next_level)
                        if next_template:
                            logger.info(f"Using next_level fallback: {next_level}")
                            return (bot_name, next_template)
            
            # Check if input re-triggers any bot
            triggered_bot = self.find_bot_by_trigger(text)
            if triggered_bot:
                new_bot_name = triggered_bot.get("name")
                start_template = self.get_start_template(new_bot_name)
                if start_template:
                    logger.info(f"Re-triggering to bot {new_bot_name} from trigger")
                    return (new_bot_name, start_template)
            
            # Return fallback message
            return self._create_fallback_template(bot_name, text)
        
        # Step 2: No active session - find bot by trigger
        triggered_bot = self.find_bot_by_trigger(text)
        if triggered_bot:
            bot_name = triggered_bot.get("name")
            
            # Create new session
            start_template = self.get_start_template(bot_name)
            if start_template:
                start_level = start_template.get("settings", {}).get("message_level") or start_template.get("id")
                self.create_session(phone_number, bot_name, start_level)
                logger.info(f"Created session for {phone_number} with bot {bot_name}")
                return (bot_name, start_template)
        
        # Step 3: No trigger match - use default bot
        default_bot = self.get_default_bot()
        if default_bot:
            bot_name = default_bot.get("name")
            start_template = self.get_start_template(bot_name)
            if start_template:
                start_level = start_template.get("settings", {}).get("message_level") or start_template.get("id")
                self.create_session(phone_number, bot_name, start_level)
                logger.info(f"Using default bot {bot_name} for {phone_number}")
                return (bot_name, start_template)
        
        logger.warning(f"No matching bot or template found for {phone_number}")
        return None
    
    def _create_fallback_template(self, bot_name: str, input_text: str) -> Optional[Tuple[str, Dict]]:
        """Create a fallback text template when no route matches"""
        fallback_template = {
            "id": f"{bot_name}_fallback",
            "name": "Fallback",
            "type": "text",
            "message": {"body": "Sorry, I didn't understand that. Please try again."},
            "settings": {},
            "routes": []
        }
        
        return (bot_name, fallback_template)
    
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
        
        bot_name, template = result
        
        # Send the template
        from frappe_pywce.multi_bot_sender import MultiBotSender
        sender = MultiBotSender(phone_number, bot_name)
        response = sender.send_template(template)
        
        # Update session level
        if response and response.get("success"):
            settings = template.get("settings", {})
            new_level = settings.get("message_level") or template.get("id")
            if new_level:
                self.update_session_level(phone_number, new_level)
        
        return response


def process_multi_bot_message(phone_number: str, input_text: str) -> Optional[Dict]:
    """
    Process incoming message with multi-bot support.
    Returns response data or None.
    """
    engine = MultiBotEngine()
    return engine.process_and_send(phone_number, input_text)


def get_chatbots_list() -> List[Dict]:
    """Get list of all chatbots from flow_json"""
    engine = MultiBotEngine()
    bots = engine.get_all_bots()
    return [{"name": bot.get("name"), "template_count": len(bot.get("templates", []))} for bot in bots]
