"""
Bot Management API

Provides REST API endpoints for managing chatbots in the multi-bot system.
"""

import json
from typing import Optional, List, Dict, Any

import frappe
from frappe import _

from frappe_pywce.pywce_logger import app_logger as logger


# ========== Bot CRUD Operations ==========

@frappe.whitelist()
def get_bots(include_inactive: bool = False) -> List[Dict]:
    """
    Get all chatbots.
    
    Args:
        include_inactive: If True, include inactive bots
        
    Returns:
        List of bot dictionaries
    """
    filters = {}
    if not include_inactive:
        filters["is_active"] = 1
    
    bots = frappe.get_all(
        "Chat Bot",
        filters=filters,
        fields=[
            "name", "bot_name", "bot_slug", "description",
            "is_active", "is_default", "trigger_patterns",
            "start_template_id", "total_templates", "total_conversations",
            "creation", "modified"
        ],
        order_by="creation desc"
    )
    
    return bots


@frappe.whitelist()
def get_bot(bot_slug: str) -> Optional[Dict]:
    """
    Get a specific bot by slug.
    
    Args:
        bot_slug: The bot's slug identifier
        
    Returns:
        Bot dictionary or None
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    return bot.as_dict()


@frappe.whitelist()
def create_bot(
    bot_name: str,
    description: str = "",
    trigger_patterns: str = "[]",
    is_default: bool = False,
    flow_json: str = "{}"
) -> Dict:
    """
    Create a new chatbot.
    
    Args:
        bot_name: Name of the bot
        description: Bot description
        trigger_patterns: JSON array of regex trigger patterns
        is_default: Whether this is the default bot
        flow_json: Initial flow JSON
        
    Returns:
        Created bot dictionary
    """
    # Validate bot name uniqueness
    if frappe.db.exists("Chat Bot", {"bot_name": bot_name}):
        frappe.throw(_("A bot with name '{0}' already exists").format(bot_name))
    
    bot = frappe.get_doc({
        "doctype": "Chat Bot",
        "bot_name": bot_name,
        "description": description,
        "trigger_patterns": trigger_patterns,
        "is_default": 1 if is_default else 0,
        "is_active": 1,
        "flow_json": flow_json,
        "fallback_message": "Sorry, I didn't understand that. Please try again."
    })
    bot.insert()
    frappe.db.commit()
    
    logger.info(f"Created new bot: {bot.bot_slug}")
    return bot.as_dict()


@frappe.whitelist()
def update_bot(
    bot_slug: str,
    bot_name: str = None,
    description: str = None,
    trigger_patterns: str = None,
    is_active: bool = None,
    is_default: bool = None,
    fallback_message: str = None,
    start_template_id: str = None,
    flow_json: str = None
) -> Dict:
    """
    Update an existing chatbot.
    
    Args:
        bot_slug: The bot's slug identifier
        Other args: Fields to update (None = don't update)
        
    Returns:
        Updated bot dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    
    if bot_name is not None:
        bot.bot_name = bot_name
    if description is not None:
        bot.description = description
    if trigger_patterns is not None:
        bot.trigger_patterns = trigger_patterns
    if is_active is not None:
        bot.is_active = 1 if is_active else 0
    if is_default is not None:
        bot.is_default = 1 if is_default else 0
    if fallback_message is not None:
        bot.fallback_message = fallback_message
    if start_template_id is not None:
        bot.start_template_id = start_template_id
    if flow_json is not None:
        bot.flow_json = flow_json
    
    bot.save()
    frappe.db.commit()
    
    logger.info(f"Updated bot: {bot_slug}")
    return bot.as_dict()


@frappe.whitelist()
def delete_bot(bot_slug: str) -> Dict:
    """
    Delete a chatbot and all related data.
    
    Args:
        bot_slug: The bot's slug identifier
        
    Returns:
        Status dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    # Delete related templates
    frappe.db.delete("Bot Template", {"bot": bot_slug})
    
    # Delete related routes
    frappe.db.delete("Bot Route", {"bot": bot_slug})
    
    # End related sessions
    frappe.db.set_value(
        "User Bot Session",
        {"current_bot": bot_slug},
        "is_active",
        0
    )
    
    # Delete the bot
    frappe.delete_doc("Chat Bot", bot_slug)
    frappe.db.commit()
    
    logger.info(f"Deleted bot: {bot_slug}")
    return {"success": True, "message": f"Bot '{bot_slug}' deleted successfully"}


@frappe.whitelist()
def duplicate_bot(bot_slug: str, new_name: str) -> Dict:
    """
    Duplicate a chatbot with a new name.
    
    Args:
        bot_slug: The source bot's slug
        new_name: Name for the new bot
        
    Returns:
        New bot dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    source_bot = frappe.get_doc("Chat Bot", bot_slug)
    
    new_bot = frappe.get_doc({
        "doctype": "Chat Bot",
        "bot_name": new_name,
        "description": f"Copy of {source_bot.bot_name}",
        "trigger_patterns": source_bot.trigger_patterns,
        "is_default": 0,
        "is_active": 1,
        "flow_json": source_bot.flow_json,
        "fallback_message": source_bot.fallback_message
    })
    new_bot.insert()
    frappe.db.commit()
    
    logger.info(f"Duplicated bot {bot_slug} as {new_bot.bot_slug}")
    return new_bot.as_dict()


# ========== Flow Management ==========

@frappe.whitelist()
def get_bot_flow(bot_slug: str) -> Dict:
    """
    Get the flow JSON for a bot.
    
    Args:
        bot_slug: The bot's slug identifier
        
    Returns:
        Flow JSON as dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    flow_json = bot.flow_json or "{}"
    
    try:
        return json.loads(flow_json) if isinstance(flow_json, str) else flow_json
    except json.JSONDecodeError:
        return {}


@frappe.whitelist()
def save_bot_flow(bot_slug: str, flow_json: str) -> Dict:
    """
    Save the flow JSON for a bot.
    
    Args:
        bot_slug: The bot's slug identifier
        flow_json: The flow JSON string
        
    Returns:
        Status dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    # Validate JSON
    try:
        flow_data = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
    except json.JSONDecodeError:
        frappe.throw(_("Invalid JSON format"))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    bot.flow_json = json.dumps(flow_data) if isinstance(flow_data, dict) else flow_json
    bot.save()
    frappe.db.commit()
    
    logger.info(f"Saved flow for bot: {bot_slug}")
    return {"success": True, "message": "Flow saved successfully"}


# ========== Template Management ==========

@frappe.whitelist()
def get_bot_templates(bot_slug: str) -> List[Dict]:
    """
    Get all templates for a bot from its flow_json.
    
    Args:
        bot_slug: The bot's slug identifier
        
    Returns:
        List of template dictionaries
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    return bot.get_templates()


@frappe.whitelist()
def add_template_to_flow(
    bot_slug: str,
    template_id: str,
    template_name: str,
    template_type: str,
    message_data: str,
    settings: str = "{}",
    position_x: float = 0,
    position_y: float = 0
) -> Dict:
    """
    Add a new template to a bot's flow.
    
    Args:
        bot_slug: The bot's slug identifier
        template_id: Unique template ID
        template_name: Display name
        template_type: Type (text, button, list, etc.)
        message_data: JSON message content
        settings: JSON settings
        position_x: X position in visual builder
        position_y: Y position in visual builder
        
    Returns:
        Updated flow dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    flow = get_bot_flow(bot_slug)
    
    if "templates" not in flow:
        flow["templates"] = []
    
    # Parse JSON strings
    try:
        msg_data = json.loads(message_data) if isinstance(message_data, str) else message_data
        settings_data = json.loads(settings) if isinstance(settings, str) else settings
    except json.JSONDecodeError:
        frappe.throw(_("Invalid JSON in message_data or settings"))
    
    # Generate level_id
    level_name = template_name.lower().replace(" ", "_")
    level_id = f"{bot_slug}::{level_name}"
    
    new_template = {
        "id": template_id,
        "name": template_name,
        "type": template_type,
        "message": msg_data,
        "routes": [],
        "settings": {
            **settings_data,
            "message_level": level_id
        },
        "position": {
            "x": position_x,
            "y": position_y
        }
    }
    
    flow["templates"].append(new_template)
    
    bot.flow_json = json.dumps(flow)
    bot.save()
    frappe.db.commit()
    
    return new_template


@frappe.whitelist()
def add_route_to_template(
    bot_slug: str,
    from_template_id: str,
    to_template_id: str,
    pattern: str,
    is_regex: bool = True
) -> Dict:
    """
    Add a route between two templates.
    
    Args:
        bot_slug: The bot's slug identifier
        from_template_id: Source template ID
        to_template_id: Target template ID
        pattern: Pattern to match
        is_regex: Whether pattern is regex
        
    Returns:
        Status dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    flow = get_bot_flow(bot_slug)
    
    templates = flow.get("templates", [])
    
    for template in templates:
        if template.get("id") == from_template_id:
            if "routes" not in template:
                template["routes"] = []
            
            template["routes"].append({
                "pattern": pattern,
                "connectedTo": to_template_id,
                "is_regex": is_regex
            })
            break
    
    flow["templates"] = templates
    bot.flow_json = json.dumps(flow)
    bot.save()
    frappe.db.commit()
    
    return {"success": True, "message": "Route added successfully"}


# ========== Session Management ==========

@frappe.whitelist()
def get_active_sessions(bot_slug: str = None) -> List[Dict]:
    """
    Get active user sessions.
    
    Args:
        bot_slug: Optional filter by bot
        
    Returns:
        List of session dictionaries
    """
    filters = {"is_active": 1}
    if bot_slug:
        filters["current_bot"] = bot_slug
    
    sessions = frappe.get_all(
        "User Bot Session",
        filters=filters,
        fields=[
            "name", "phone_number", "current_bot", "current_level",
            "is_active", "last_activity", "session_start", "message_count"
        ],
        order_by="last_activity desc"
    )
    
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
    frappe.db.set_value(
        "User Bot Session",
        {"phone_number": phone_number, "is_active": 1},
        "is_active",
        0
    )
    frappe.db.commit()
    
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
    session = frappe.db.get_value(
        "User Bot Session",
        {"phone_number": phone_number, "is_active": 1},
        ["name", "current_bot", "current_level", "session_data", "context_data"],
        as_dict=True
    )
    
    if session:
        try:
            session["session_data"] = json.loads(session["session_data"] or "{}")
            session["context_data"] = json.loads(session["context_data"] or "{}")
        except json.JSONDecodeError:
            pass
    
    return session


# ========== Statistics ==========

@frappe.whitelist()
def get_bot_stats(bot_slug: str) -> Dict:
    """
    Get statistics for a bot.
    
    Args:
        bot_slug: The bot's slug identifier
        
    Returns:
        Statistics dictionary
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    # Count templates
    bot = frappe.get_doc("Chat Bot", bot_slug)
    templates = bot.get_templates()
    
    # Count active sessions
    active_sessions = frappe.db.count(
        "User Bot Session",
        {"current_bot": bot_slug, "is_active": 1}
    )
    
    # Count total messages
    total_messages = frappe.db.count(
        "WhatsApp Chat Message",
        {"metadata": ("like", f'%"bot_slug": "{bot_slug}"%')}
    )
    
    return {
        "bot_slug": bot_slug,
        "total_templates": len(templates),
        "active_sessions": active_sessions,
        "total_messages": total_messages
    }


# ========== Import/Export ==========

@frappe.whitelist()
def export_bot(bot_slug: str) -> Dict:
    """
    Export a bot's complete configuration.
    
    Args:
        bot_slug: The bot's slug identifier
        
    Returns:
        Complete bot configuration
    """
    if not frappe.db.exists("Chat Bot", bot_slug):
        frappe.throw(_("Bot not found: {0}").format(bot_slug))
    
    bot = frappe.get_doc("Chat Bot", bot_slug)
    
    return {
        "version": "1.0",
        "bot": {
            "bot_name": bot.bot_name,
            "description": bot.description,
            "trigger_patterns": bot.trigger_patterns,
            "fallback_message": bot.fallback_message,
            "start_template_id": bot.start_template_id
        },
        "flow": get_bot_flow(bot_slug)
    }


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
    
    bot_config = config.get("bot", {})
    flow = config.get("flow", {})
    
    return create_bot(
        bot_name=bot_name,
        description=bot_config.get("description", ""),
        trigger_patterns=json.dumps(bot_config.get("trigger_patterns", [])),
        flow_json=json.dumps(flow)
    )
