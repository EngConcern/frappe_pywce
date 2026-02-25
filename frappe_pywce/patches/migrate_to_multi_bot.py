"""
Migration script to convert single-bot configuration to multi-bot system.

This patch:
1. Reads the existing ChatBot Config flow_json
2. Creates a new Chat Bot record with that flow
3. Sets it as the default bot
"""

import json
import frappe
from frappe_pywce.pywce_logger import app_logger as logger


def execute():
    """Migrate from single-bot to multi-bot system"""
    
    # Check if migration already done
    if frappe.db.count("Chat Bot") > 0:
        logger.info("Multi-bot migration already completed, skipping")
        return
    
    # Get existing ChatBot Config
    try:
        config = frappe.get_single("ChatBot Config")
    except Exception:
        logger.warning("No ChatBot Config found, skipping migration")
        return
    
    flow_json = config.flow_json
    if not flow_json:
        logger.warning("No flow_json in ChatBot Config, skipping migration")
        return
    
    # Parse flow JSON
    try:
        flow_data = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
    except json.JSONDecodeError:
        logger.error("Invalid flow_json in ChatBot Config")
        return
    
    # Extract chatbot info
    chatbot_name = config.chatbot_name or "Default Bot"
    
    # Check if flow has chatbots array (new format)
    if "chatbots" in flow_data:
        chatbots = flow_data.get("chatbots", [])
        
        for i, chatbot in enumerate(chatbots):
            bot_name = chatbot.get("name", f"Bot {i+1}")
            templates = chatbot.get("templates", [])
            
            # Find start template
            start_template_id = None
            trigger_patterns = []
            
            for template in templates:
                settings = template.get("settings", {})
                if settings.get("isStart"):
                    start_template_id = template.get("id")
                if settings.get("trigger"):
                    trigger_patterns.append(settings.get("trigger"))
            
            # Create Chat Bot record
            bot = frappe.get_doc({
                "doctype": "Chat Bot",
                "bot_name": bot_name,
                "description": f"Migrated from ChatBot Config",
                "is_active": 1,
                "is_default": i == 0,  # First bot is default
                "trigger_patterns": json.dumps(trigger_patterns) if trigger_patterns else "[]",
                "start_template_id": start_template_id,
                "flow_json": json.dumps({"templates": templates}),
                "fallback_message": "Sorry, I didn't understand that. Please try again.",
                "whatsapp_config": "ChatBot Config"
            })
            bot.insert(ignore_permissions=True)
            logger.info(f"Created Chat Bot: {bot.bot_slug}")
    
    else:
        # Old format with templates at root
        templates = flow_data.get("templates", [])
        
        # Find start template and triggers
        start_template_id = None
        trigger_patterns = []
        
        for template in templates:
            settings = template.get("settings", {})
            if settings.get("isStart"):
                start_template_id = template.get("id")
            if settings.get("trigger"):
                trigger_patterns.append(settings.get("trigger"))
        
        # Create single Chat Bot record
        bot = frappe.get_doc({
            "doctype": "Chat Bot",
            "bot_name": chatbot_name,
            "description": "Migrated from ChatBot Config",
            "is_active": 1,
            "is_default": 1,
            "trigger_patterns": json.dumps(trigger_patterns) if trigger_patterns else "[]",
            "start_template_id": start_template_id,
            "flow_json": flow_json,
            "fallback_message": "Sorry, I didn't understand that. Please try again.",
            "whatsapp_config": "ChatBot Config"
        })
        bot.insert(ignore_permissions=True)
        logger.info(f"Created Chat Bot: {bot.bot_slug}")
    
    frappe.db.commit()
    logger.info("Multi-bot migration completed successfully")
