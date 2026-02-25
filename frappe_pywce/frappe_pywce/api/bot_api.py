"""
Bot Management API

Provides REST API endpoints for managing chatbots in the multi-bot system.
Works with the studio's chatbots array format stored in ChatBot Config.flow_json.

Format:
{
    "chatbots": [
        {"name": "Bot1", "templates": [...]},
        {"name": "Bot2", "templates": [...]}
    ],
    "version": "1.0"
}
"""

import json
from typing import Optional, List, Dict, Any

import frappe
from frappe import _

from frappe_pywce.pywce_logger import app_logger as logger


def _get_flow_data() -> Dict:
    """Get flow data from ChatBot Config"""
    flow_json = frappe.db.get_single_value("ChatBot Config", "flow_json")
    if flow_json:
        try:
            data = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
            # Ensure chatbots array exists
            if "chatbots" not in data:
                if "templates" in data:
                    # Convert old format
                    chatbot_name = frappe.db.get_single_value("ChatBot Config", "chatbot_name") or "Default Bot"
                    data = {"chatbots": [{"name": chatbot_name, "templates": data["templates"]}], "version": "1.0"}
                else:
                    data = {"chatbots": [], "version": "1.0"}
            return data
        except json.JSONDecodeError:
            pass
    return {"chatbots": [], "version": "1.0"}


def _save_flow_data(flow_data: Dict):
    """Save flow data to ChatBot Config"""
    flow_json = json.dumps(flow_data, indent=2)
    frappe.db.set_single_value("ChatBot Config", "flow_json", flow_json)
    frappe.db.commit()


# ========== Bot CRUD Operations ==========

@frappe.whitelist()
def get_bots() -> List[Dict]:
    """
    Get all chatbots from flow_json.
    
    Returns:
        List of bot dictionaries with name and template_count
    """
    flow_data = _get_flow_data()
    bots = []
    
    for i, bot in enumerate(flow_data.get("chatbots", [])):
        templates = bot.get("templates", [])
        
        # Find start template
        start_template = None
        for t in templates:
            if t.get("settings", {}).get("isStart"):
                start_template = t.get("id")
                break
        
        bots.append({
            "name": bot.get("name", f"Bot {i+1}"),
            "template_count": len(templates),
            "start_template_id": start_template,
            "is_default": i == 0  # First bot is default
        })
    
    return bots


@frappe.whitelist()
def get_bot(bot_name: str) -> Optional[Dict]:
    """
    Get a specific bot by name.
    
    Args:
        bot_name: The bot's name
        
    Returns:
        Bot dictionary or None
    """
    flow_data = _get_flow_data()
    
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            return bot
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


@frappe.whitelist()
def create_bot(bot_name: str, with_start_template: bool = True) -> Dict:
    """
    Create a new chatbot in the chatbots array.
    
    Args:
        bot_name: Name of the bot
        with_start_template: If True, create a default start template
        
    Returns:
        Created bot dictionary
    """
    flow_data = _get_flow_data()
    
    # Check if bot name already exists
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            frappe.throw(_("A bot with name '{0}' already exists").format(bot_name))
    
    # Create new bot
    new_bot = {
        "name": bot_name,
        "templates": []
    }
    
    # Add a default start template if requested
    if with_start_template:
        start_template = {
            "id": f"start-{frappe.utils.now_datetime().timestamp()}",
            "name": "Welcome",
            "type": "text",
            "message": f"Hello! Welcome to {bot_name}. How can I help you?",
            "routes": [],
            "settings": {
                "isStart": True
            },
            "position": {"x": 100, "y": 100}
        }
        new_bot["templates"].append(start_template)
    
    flow_data["chatbots"].append(new_bot)
    _save_flow_data(flow_data)
    
    logger.info(f"Created new bot: {bot_name}")
    return new_bot


@frappe.whitelist()
def rename_bot(old_name: str, new_name: str) -> Dict:
    """
    Rename an existing chatbot.
    
    Args:
        old_name: Current bot name
        new_name: New bot name
        
    Returns:
        Updated bot dictionary
    """
    flow_data = _get_flow_data()
    
    # Check new name doesn't exist
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == new_name.lower():
            frappe.throw(_("A bot with name '{0}' already exists").format(new_name))
    
    # Find and rename
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == old_name.lower():
            bot["name"] = new_name
            _save_flow_data(flow_data)
            logger.info(f"Renamed bot: {old_name} -> {new_name}")
            return bot
    
    frappe.throw(_("Bot not found: {0}").format(old_name))


@frappe.whitelist()
def delete_bot(bot_name: str) -> Dict:
    """
    Delete a chatbot from the chatbots array.
    
    Args:
        bot_name: The bot's name
        
    Returns:
        Status dictionary
    """
    flow_data = _get_flow_data()
    
    # Find and remove
    chatbots = flow_data.get("chatbots", [])
    for i, bot in enumerate(chatbots):
        if bot.get("name", "").lower() == bot_name.lower():
            chatbots.pop(i)
            flow_data["chatbots"] = chatbots
            _save_flow_data(flow_data)
            
            # Clear sessions for this bot
            frappe.cache().hdel("multi_bot_session", bot_name)
            
            logger.info(f"Deleted bot: {bot_name}")
            return {"success": True, "message": f"Bot '{bot_name}' deleted successfully"}
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


@frappe.whitelist()
def duplicate_bot(source_name: str, new_name: str) -> Dict:
    """
    Duplicate a chatbot with a new name.
    
    Args:
        source_name: The source bot's name
        new_name: Name for the new bot
        
    Returns:
        New bot dictionary
    """
    flow_data = _get_flow_data()
    
    # Check new name doesn't exist
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == new_name.lower():
            frappe.throw(_("A bot with name '{0}' already exists").format(new_name))
    
    # Find source bot
    source_bot = None
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == source_name.lower():
            source_bot = bot
            break
    
    if not source_bot:
        frappe.throw(_("Bot not found: {0}").format(source_name))
    
    # Deep copy the bot
    import copy
    new_bot = copy.deepcopy(source_bot)
    new_bot["name"] = new_name
    
    # Update template IDs to be unique
    timestamp = frappe.utils.now_datetime().timestamp()
    id_map = {}
    for template in new_bot.get("templates", []):
        old_id = template.get("id")
        new_id = f"{old_id}-copy-{timestamp}"
        id_map[old_id] = new_id
        template["id"] = new_id
    
    # Update route connections
    for template in new_bot.get("templates", []):
        for route in template.get("routes", []):
            old_connected = route.get("connectedTo")
            if old_connected and old_connected in id_map:
                route["connectedTo"] = id_map[old_connected]
    
    flow_data["chatbots"].append(new_bot)
    _save_flow_data(flow_data)
    
    logger.info(f"Duplicated bot {source_name} as {new_name}")
    return new_bot


# ========== Flow Management ==========

@frappe.whitelist()
def get_bot_flow(bot_name: str) -> Dict:
    """
    Get the templates for a bot.
    
    Args:
        bot_name: The bot's name
        
    Returns:
        Flow dictionary with templates array
    """
    flow_data = _get_flow_data()
    
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            return {"templates": bot.get("templates", []), "version": flow_data.get("version", "1.0")}
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


@frappe.whitelist()
def save_bot_flow(bot_name: str, templates_json: str) -> Dict:
    """
    Save the templates for a bot.
    
    Args:
        bot_name: The bot's name
        templates_json: JSON array of templates
        
    Returns:
        Status dictionary
    """
    flow_data = _get_flow_data()
    
    # Validate JSON
    try:
        templates = json.loads(templates_json) if isinstance(templates_json, str) else templates_json
    except json.JSONDecodeError:
        frappe.throw(_("Invalid JSON format"))
    
    # Find and update bot
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            bot["templates"] = templates
            _save_flow_data(flow_data)
            logger.info(f"Saved flow for bot: {bot_name}")
            return {"success": True, "message": "Flow saved successfully"}
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


# ========== Template Management ==========

@frappe.whitelist()
def get_bot_templates(bot_name: str) -> List[Dict]:
    """
    Get all templates for a bot.
    
    Args:
        bot_name: The bot's name
        
    Returns:
        List of template dictionaries
    """
    flow_data = _get_flow_data()
    
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            return bot.get("templates", [])
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


@frappe.whitelist()
def add_template(
    bot_name: str,
    template_type: str,
    template_name: str = None,
    message_data: str = "{}",
    position_x: float = 100,
    position_y: float = 100
) -> Dict:
    """
    Add a new template to a bot.
    
    Args:
        bot_name: The bot's name
        template_type: Type (text, button, list, etc.)
        template_name: Display name (auto-generated if not provided)
        message_data: JSON message content
        position_x: X position in visual builder
        position_y: Y position in visual builder
        
    Returns:
        Created template dictionary
    """
    flow_data = _get_flow_data()
    
    # Parse message data
    try:
        msg_data = json.loads(message_data) if isinstance(message_data, str) else message_data
    except json.JSONDecodeError:
        msg_data = {"body": message_data} if template_type == "text" else {}
    
    # Generate template ID and name
    timestamp = frappe.utils.now_datetime().timestamp()
    template_id = f"{template_type}-{timestamp}"
    if not template_name:
        template_name = f"{template_type.title()} {len(flow_data.get('chatbots', []))}"
    
    new_template = {
        "id": template_id,
        "name": template_name,
        "type": template_type,
        "message": msg_data,
        "routes": [],
        "settings": {},
        "position": {"x": position_x, "y": position_y}
    }
    
    # Find bot and add template
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            if "templates" not in bot:
                bot["templates"] = []
            bot["templates"].append(new_template)
            _save_flow_data(flow_data)
            logger.info(f"Added template {template_id} to bot {bot_name}")
            return new_template
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


@frappe.whitelist()
def add_route(
    bot_name: str,
    from_template_id: str,
    to_template_id: str,
    pattern: str = ".*",
    is_regex: bool = True
) -> Dict:
    """
    Add a route between two templates.
    
    Args:
        bot_name: The bot's name
        from_template_id: Source template ID
        to_template_id: Target template ID
        pattern: Pattern to match (default: .* matches anything)
        is_regex: Whether pattern is regex
        
    Returns:
        Status dictionary
    """
    flow_data = _get_flow_data()
    
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            for template in bot.get("templates", []):
                if template.get("id") == from_template_id:
                    if "routes" not in template:
                        template["routes"] = []
                    
                    route_id = f"route-{frappe.utils.now_datetime().timestamp()}"
                    template["routes"].append({
                        "id": route_id,
                        "pattern": pattern,
                        "isRegex": is_regex,
                        "connectedTo": to_template_id
                    })
                    
                    _save_flow_data(flow_data)
                    return {"success": True, "route_id": route_id}
            
            frappe.throw(_("Template not found: {0}").format(from_template_id))
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


# ========== Session Management ==========

@frappe.whitelist()
def get_active_sessions(bot_name: str = None) -> List[Dict]:
    """
    Get active user sessions from Redis cache.
    
    Args:
        bot_name: Optional filter by bot
        
    Returns:
        List of session dictionaries
    """
    sessions = []
    all_sessions = frappe.cache().hgetall("multi_bot_session")
    
    for phone, session_data in (all_sessions or {}).items():
        try:
            session = json.loads(session_data) if isinstance(session_data, str) else session_data
            if session.get("is_active"):
                if bot_name is None or session.get("bot_name", "").lower() == bot_name.lower():
                    sessions.append({
                        "phone_number": phone,
                        "bot_name": session.get("bot_name"),
                        "current_level": session.get("current_level"),
                        "created_at": session.get("created_at"),
                        "last_activity": session.get("last_activity")
                    })
        except:
            continue
    
    return sessions


@frappe.whitelist()
def end_user_session(phone_number: str) -> Dict:
    """
    End a user's active session.
    
    Args:
        phone_number: The user's phone number
        
    Returns:
        Status dictionary
    """
    frappe.cache().hdel("multi_bot_session", phone_number)
    return {"success": True, "message": f"Session ended for {phone_number}"}


@frappe.whitelist()
def get_session_data(phone_number: str) -> Optional[Dict]:
    """
    Get session data for a phone number.
    
    Args:
        phone_number: The user's phone number
        
    Returns:
        Session dictionary or None
    """
    session_data = frappe.cache().hget("multi_bot_session", phone_number)
    if session_data:
        try:
            return json.loads(session_data) if isinstance(session_data, str) else session_data
        except:
            pass
    return None


# ========== Statistics ==========

@frappe.whitelist()
def get_bot_stats(bot_name: str) -> Dict:
    """
    Get statistics for a bot.
    
    Args:
        bot_name: The bot's name
        
    Returns:
        Statistics dictionary
    """
    flow_data = _get_flow_data()
    
    # Find bot and count templates
    template_count = 0
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            template_count = len(bot.get("templates", []))
            break
    
    # Count active sessions for this bot
    active_sessions = 0
    all_sessions = frappe.cache().hgetall("multi_bot_session")
    for phone, session_data in (all_sessions or {}).items():
        try:
            session = json.loads(session_data) if isinstance(session_data, str) else session_data
            if session.get("is_active") and session.get("bot_name", "").lower() == bot_name.lower():
                active_sessions += 1
        except:
            continue
    
    return {
        "bot_name": bot_name,
        "total_templates": template_count,
        "active_sessions": active_sessions
    }


# ========== Import/Export ==========

@frappe.whitelist()
def export_bot(bot_name: str) -> Dict:
    """
    Export a bot's complete configuration.
    
    Args:
        bot_name: The bot's name
        
    Returns:
        Complete bot configuration
    """
    flow_data = _get_flow_data()
    
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            return {
                "version": "1.0",
                "name": bot.get("name"),
                "templates": bot.get("templates", [])
            }
    
    frappe.throw(_("Bot not found: {0}").format(bot_name))


@frappe.whitelist()
def import_bot(bot_name: str, config_json: str) -> Dict:
    """
    Import a bot from configuration JSON.
    
    Args:
        bot_name: Name for the imported bot
        config_json: JSON configuration string
        
    Returns:
        Created bot dictionary
    """
    try:
        config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except json.JSONDecodeError:
        frappe.throw(_("Invalid JSON configuration"))
    
    flow_data = _get_flow_data()
    
    # Check if bot name already exists
    for bot in flow_data.get("chatbots", []):
        if bot.get("name", "").lower() == bot_name.lower():
            frappe.throw(_("A bot with name '{0}' already exists").format(bot_name))
    
    # Create new bot from config
    templates = config.get("templates", [])
    if not templates and "flow" in config:
        templates = config["flow"].get("templates", [])
    
    new_bot = {
        "name": bot_name,
        "templates": templates
    }
    
    flow_data["chatbots"].append(new_bot)
    _save_flow_data(flow_data)
    
    logger.info(f"Imported bot: {bot_name}")
    return new_bot


# ========== Utility Functions ==========

@frappe.whitelist()
def clear_all_sessions() -> Dict:
    """Clear all active sessions"""
    frappe.cache().delete_key("multi_bot_session")
    return {"success": True, "message": "All sessions cleared"}


@frappe.whitelist()
def get_studio_url(bot_name: str = None) -> str:
    """
    Get the URL for the visual studio.
    
    Args:
        bot_name: Optional bot name to open in studio
        
    Returns:
        Studio URL
    """
    base_url = frappe.utils.get_url()
    if bot_name:
        return f"{base_url}/bot/studio?flow={bot_name}"
    return f"{base_url}/bot/studio"
