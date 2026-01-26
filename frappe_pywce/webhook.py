import json
from datetime import datetime

import redis
import redis.exceptions

import frappe
import frappe.utils
import re
import os

from frappe_pywce.config import get_engine_config, get_wa_config
from frappe_pywce.util import CACHE_KEY_PREFIX, LOCK_WAIT_TIME, LOCK_LEASE_TIME, bot_settings, create_cache_key
from frappe_pywce.pywce_logger import app_logger as logger
from frappe_pywce.routing_engine import RoutingEngine


def _verifier():
    """
        Verify WhatsApp webhook callback URL challenge.

        Ref:    https://discuss.frappe.io/t/returning-plain-text-from-whitelisted-method/32621
    """
    params = frappe.request.args

    mode, token, challenge = params.get("hub.mode"), params.get("hub.verify_token"), params.get("hub.challenge")

    if get_wa_config(bot_settings()).util.webhook_challenge(mode, challenge, token):
        from werkzeug.wrappers import Response
        return Response(challenge)

    frappe.throw("Webhook verification challenge failed", exc=frappe.PermissionError)


def _save_incoming_message(payload: dict):
    """
    Save incoming WhatsApp message to database for chat interface
    
    Args:
        payload (dict): WhatsApp webhook payload
    """
    try:
        # Extract message from payload
        if not payload.get('entry'):
            return
        
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                messages = value.get('messages', [])
                
                for message in messages:
                    # Normalize phone number - remove all non-numeric characters
                    raw_phone = message.get('from', '')
                    phone_number = ''.join(filter(str.isdigit, raw_phone))
                    
                    message_id = message.get('id', '')
                    timestamp = message.get('timestamp')
                    message_type = message.get('type', 'text')
                    
                    # Get message text based on type
                    message_text = ''
                    media_url = None
                    media_type = None
                    
                    if message_type == 'text':
                        message_text = message.get('text', {}).get('body', '')
                    
                    elif message_type == 'image':
                        image_data = message.get('image', {})
                        message_text = image_data.get('caption', '')
                        media_url = image_data.get('id', '')
                        media_type = 'image'
                    
                    elif message_type == 'video':
                        video_data = message.get('video', {})
                        message_text = video_data.get('caption', '')
                        media_url = video_data.get('id', '')
                        media_type = 'video'
                    
                    elif message_type == 'audio':
                        audio_data = message.get('audio', {})
                        media_url = audio_data.get('id', '')
                        media_type = 'audio'
                        message_text = f"Audio message ({audio_data.get('mime_type', 'audio')})"
                    
                    elif message_type == 'voice':
                        voice_data = message.get('voice', {})
                        media_url = voice_data.get('id', '')
                        media_type = 'voice'
                        message_text = "Voice message"
                    
                    elif message_type == 'document':
                        doc_data = message.get('document', {})
                        message_text = doc_data.get('filename', 'Document')
                        media_url = doc_data.get('id', '')
                        media_type = 'document'
                    
                    elif message_type == 'sticker':
                        sticker_data = message.get('sticker', {})
                        media_url = sticker_data.get('id', '')
                        media_type = 'sticker'
                        message_text = "Sticker"
                    
                    elif message_type == 'location':
                        location_data = message.get('location', {})
                        message_text = f"Location: {location_data.get('name', 'Shared location')}"
                    
                    elif message_type == 'contacts':
                        contacts_data = message.get('contacts', [])
                        if contacts_data:
                            contact = contacts_data[0]
                            name = contact.get('name', {}).get('formatted_name', 'Contact')
                            message_text = f"Contact: {name}"
                    
                    elif message_type == 'button':
                        button_data = message.get('button', {})
                        message_text = f"Button: {button_data.get('text', 'Button clicked')}"
                    
                    elif message_type == 'interactive':
                        interactive_data = message.get('interactive', {})
                        interactive_type = interactive_data.get('type', '')
                        
                        if interactive_type == 'button_reply':
                            button_reply = interactive_data.get('button_reply', {})
                            message_text = f"Button: {button_reply.get('title', 'Button clicked')}"
                        elif interactive_type == 'list_reply':
                            list_reply = interactive_data.get('list_reply', {})
                            message_text = f"Selected: {list_reply.get('title', 'List item')}"
                        else:
                            message_text = "Interactive message"
                    
                    else:
                        message_text = f"Unsupported message type: {message_type}"
                    
                    # Get contact name from contacts in payload
                    contact_name = ''
                    contacts = value.get('contacts', [])
                    for contact in contacts:
                        contact_wa_id = ''.join(filter(str.isdigit, contact.get('wa_id', '')))
                        if contact_wa_id == phone_number:
                            profile = contact.get('profile', {})
                            contact_name = profile.get('name', '')
                            break
                    
                    # Check if message already exists
                    existing = frappe.db.exists('WhatsApp Chat Message', {'message_id': message_id})
                    if existing:
                        continue
                    
                    # Create message document
                    msg_doc = frappe.get_doc({
                        "doctype": "WhatsApp Chat Message",
                        "phone_number": phone_number,
                        "message_id": message_id,
                        "timestamp": datetime.fromtimestamp(int(timestamp)) if timestamp else datetime.now(),
                        "direction": "Incoming",
                        "message_type": message_type,
                        "message_text": message_text,
                        "media_url": media_url,
                        "media_type": media_type,
                        "contact_name": contact_name,
                        "status": "delivered",
                        "metadata": json.dumps(message)
                    })
                    msg_doc.insert(ignore_permissions=True)
                    
                    # Publish realtime event for chat interface
                    frappe.publish_realtime(
                        event='whatsapp_message_received',
                        message={
                            'phone_number': phone_number,
                            'message_id': message_id,
                            'message_text': message_text
                        },
                        after_commit=True
                    )
                    
                    logger.info(f"Saved incoming message from {phone_number}: {message_id}")
        
        frappe.db.commit()
        
    except Exception as e:
        logger.error(f"Error saving incoming message: {str(e)}")
        frappe.log_error(title="WhatsApp Chat Message Save Error", message=str(e))


def _save_message_status(payload: dict):
    """
    Update message status from webhook status updates
    
    Args:
        payload (dict): WhatsApp webhook payload
    """
    try:
        if not payload.get('entry'):
            return
        
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                statuses = value.get('statuses', [])
                
                for status in statuses:
                    message_id = status.get('id', '')
                    new_status = status.get('status', '')
                    
                    # Map WhatsApp status to our status
                    status_map = {
                        'sent': 'sent',
                        'delivered': 'delivered',
                        'read': 'read',
                        'failed': 'failed'
                    }
                    
                    mapped_status = status_map.get(new_status, 'sent')
                    
                    # Update message status
                    frappe.db.set_value(
                        'WhatsApp Chat Message',
                        {'message_id': message_id},
                        'status',
                        mapped_status
                    )
                    
                    logger.info(f"Updated message status: {message_id} -> {mapped_status}")
        
        frappe.db.commit()
        
    except Exception as e:
        logger.error(f"Error updating message status: {str(e)}")
        frappe.log_error(title="WhatsApp Message Status Update Error", message=str(e))


def _get_message_template_type(message: dict) -> str:
    """Determine the message template type from message data
    
    Args:
        message (dict): Message data from webhook payload
        
    Returns:
        str: Message template type
    """
    message_type = message.get('type', 'text')
    
    # Map message types to template types
    template_type_map = {
        'text': 'text',
        'button': 'button',
        'list': 'list',
        'flow': 'flow',
        'image': 'media',
        'video': 'media',
        'audio': 'media',
        'voice': 'media',
        'document': 'media',
        'sticker': 'media',
        'location': 'location',
        'contacts': 'cta',
        'interactive': 'dynamic',
    }
    
    return template_type_map.get(message_type, 'template')


def _process_message_templates(payload: dict):
    """Process different message template types from webhook payload
    
    Args:
        payload (dict): WhatsApp webhook payload containing messages
    """
    try:
        if not payload.get('entry'):
            return
        
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                messages = value.get('messages', [])
                
                for message in messages:
                    # Determine template type
                    template_type = _get_message_template_type(message)
                    
                    # Route message processing based on template type
                    if template_type == 'text':
                        _process_text_template(message, payload)
                    elif template_type == 'button':
                        _process_button_template(message, payload)
                    elif template_type == 'list':
                        _process_list_template(message, payload)
                    elif template_type == 'flow':
                        _process_flow_template(message, payload)
                    elif template_type == 'media':
                        _process_media_template(message, payload)
                    elif template_type == 'location':
                        _process_location_template(message, payload)
                    elif template_type == 'cta':
                        _process_cta_template(message, payload)
                    elif template_type == 'dynamic':
                        _process_dynamic_template(message, payload)
                    else:
                        _process_generic_template(message, payload)
                    
                    logger.debug(f"Processed {template_type} template for message {message.get('id', '')}")
        
    except Exception as e:
        logger.error(f"Error processing message templates: {str(e)}")
        frappe.log_error(title="Message Template Processing Error", message=str(e))


def _process_text_template(message: dict, payload: dict):
    """Process text message template"""
    logger.debug(f"Processing text template: {message.get('id', '')}")
    
    # Extract phone number and message text
    phone_number = message.get('from', '')
    message_text = message.get('text', {}).get('body', '')
    
    # Process through chatbot logic
    _process_chatbot_message(phone_number, message_text)


def _process_button_template(message: dict, payload: dict):
    """Process button message template"""
    logger.debug(f"Processing button template: {message.get('id', '')}")
    
    # Extract phone number and button response
    phone_number = message.get('from', '')
    button_data = message.get('button', {})
    button_text = button_data.get('text', '')
    
    # Process through chatbot logic
    _process_chatbot_message(phone_number, button_text)


def _process_list_template(message: dict, payload: dict):
    """Process list message template"""
    logger.debug(f"Processing list template: {message.get('id', '')}")


def _process_flow_template(message: dict, payload: dict):
    """Process flow message template"""
    logger.debug(f"Processing flow template: {message.get('id', '')}")


def _process_media_template(message: dict, payload: dict):
    """Process media message template (image, video, audio, document, etc.)"""
    logger.debug(f"Processing media template: {message.get('id', '')}")


def _process_location_template(message: dict, payload: dict):
    """Process location message template"""
    logger.debug(f"Processing location template: {message.get('id', '')}")


def _process_cta_template(message: dict, payload: dict):
    """Process call-to-action (contacts) message template"""
    logger.debug(f"Processing CTA template: {message.get('id', '')}")


def _process_dynamic_template(message: dict, payload: dict):
    """Process dynamic/interactive message template"""
    logger.debug(f"Processing dynamic template: {message.get('id', '')}")
    
    # Extract phone number and interactive response
    phone_number = message.get('from', '')
    interactive_data = message.get('interactive', {})
    interactive_type = interactive_data.get('type', '')
    
    response_text = ''
    
    if interactive_type == 'button_reply':
        button_reply = interactive_data.get('button_reply', {})
        response_text = button_reply.get('title', '')
    elif interactive_type == 'list_reply':
        list_reply = interactive_data.get('list_reply', {})
        response_text = list_reply.get('title', '')
    
    if response_text:
        # Process through chatbot logic
        _process_chatbot_message(phone_number, response_text)


def _process_generic_template(message: dict, payload: dict):
    """Process generic/unknown message template"""
    logger.debug(f"Processing generic template: {message.get('id', '')}")


def _load_chatbot_config():
    """Load chatbot configuration from JSON file"""
    try:
        # Try to find the chatbot config file
        config_paths = [
            os.path.join(frappe.get_app_path("frappe_pywce"), "chatbot_config.json"),
            os.path.join(frappe.get_site_path(), "private", "files", "chatbot_config.json"),
            "/home/frappe/frappe-bench/sites/site1.local/private/files/chatbot_config.json"
        ]
        
        config_data = None
        for path in config_paths:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                logger.info(f"Loaded chatbot config from: {path}")
                break
        
        if not config_data:
            logger.warning("Chatbot config file not found in any of the expected locations")
            return None
            
        return config_data
    except Exception as e:
        logger.error(f"Error loading chatbot config: {str(e)}")
        return None


def _get_active_chatbot(config_data):
    """Get the active chatbot from config"""
    if not config_data or not config_data.get('chatbots'):
        return None
    
    # For now, return the first chatbot or one named "Test"
    chatbots = config_data.get('chatbots', [])
    for bot in chatbots:
        if bot.get('name') == 'Test':
            return bot
    
    # Return first chatbot if Test not found
    return chatbots[0] if chatbots else None


def _find_template_by_route(chatbot, incoming_message_text):
    """Find template by matching routes in the chatbot"""
    if not chatbot or not chatbot.get('templates'):
        return None
    
    incoming_text = incoming_message_text.lower().strip() if incoming_message_text else ""
    
    for template in chatbot.get('templates', []):
        routes = template.get('routes', [])
        settings = template.get('settings', {})
        
        # First check routes
        for route in routes:
            pattern = route.get('pattern', '').lower().strip()
            is_regex = route.get('isRegex', False)
            
            if is_regex:
                try:
                    if re.match(pattern, incoming_text, re.IGNORECASE):
                        return template
                except re.error:
                    continue
            else:
                if pattern in incoming_text:
                    return template
        
        # Then check trigger patterns in settings
        trigger = settings.get('trigger', '')
        if trigger:
            try:
                if re.match(trigger, incoming_message_text, re.IGNORECASE):
                    return template
            except re.error:
                # If trigger is not a valid regex, treat as plain text
                if trigger.lower() in incoming_text:
                    return template
    
    return None


def _find_template_by_level(chatbot, phone_number):
    """Find template by user's next level from last message"""
    if not chatbot or not chatbot.get('templates'):
        return None
    
    try:
        # Get the last message for this phone number
        last_message = frappe.get_all(
            "WhatsApp Chat Message",
            filters={
                "phone_number": phone_number,
                "direction": "Outgoing"
            },
            fields=["next_level"],
            order_by="timestamp desc",
            limit=1
        )
        
        if last_message and last_message[0].get('next_level'):
            next_level = last_message[0].get('next_level')
            
            # Find template with matching message_level
            for template in chatbot.get('templates', []):
                settings = template.get('settings', {})
                if settings.get('message_level') == next_level:
                    return template
                    
    except Exception as e:
        logger.error(f"Error finding template by level: {str(e)}")
    
    return None


def _send_template_response(phone_number, template):
    """Send response using the appropriate template function"""
    try:
        template_type = template.get('type', 'text')
        message_data = template.get('message', {})
        
        response = None
        
        if template_type == 'text':
            message_text = message_data.get('body', '') if isinstance(message_data, dict) else str(message_data)
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_text_message')
            response = send_func(phone_number, message_text)
            
        elif template_type == 'button':
            message_text = message_data.get('body', '')
            buttons_data = message_data.get('buttons', [])
            
            # Format buttons for the API - handle both string arrays and object arrays
            buttons = []
            for i, btn in enumerate(buttons_data[:3]):  # WhatsApp allows max 3 buttons
                if isinstance(btn, str):
                    # Handle string format from chatbot config
                    buttons.append({
                        "id": f"btn_{i}",
                        "title": btn
                    })
                elif isinstance(btn, dict):
                    # Handle object format
                    buttons.append({
                        "id": btn.get("id", f"btn_{i}"),
                        "title": btn.get("title", f"Button {i+1}")
                    })
                else:
                    # Fallback
                    buttons.append({
                        "id": f"btn_{i}",
                        "title": str(btn)
                    })
            
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_button_message')
            response = send_func(phone_number, message_text, buttons)
            
        elif template_type == 'list':
            # List template handling would go here
            message_text = message_data.get('body', '')
            list_title = message_data.get('title', 'Select Option')
            sections = message_data.get('sections', [])
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_list_message')
            response = send_func(phone_number, message_text, list_title, sections)
            
        elif template_type == 'flow':
            flow_token = message_data.get('flow_token', '')
            flow_data = message_data.get('flow_data', {})
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_flow_message')
            response = send_func(phone_number, flow_token, flow_data)
            
        elif template_type == 'media':
            media_type = message_data.get('media_type', 'image')
            media_url = message_data.get('media_url', '')
            caption = message_data.get('caption', '')
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_media_message')
            response = send_func(phone_number, media_type, media_url, caption)
            
        elif template_type == 'location':
            latitude = message_data.get('latitude', 0)
            longitude = message_data.get('longitude', 0)
            name = message_data.get('name', '')
            address = message_data.get('address', '')
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_location_message')
            response = send_func(phone_number, latitude, longitude, name, address)
            
        elif template_type == 'contacts':
            contact_data = message_data.get('contact_data', {})
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_contact_message')
            response = send_func(phone_number, contact_data)
            
        elif template_type == 'template':
            template_name = message_data.get('template_name', '')
            language_code = message_data.get('language_code', 'en')
            components = message_data.get('components', [])
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_template_message')
            response = send_func(phone_number, template_name, language_code, components)
            
        else:
            # Default to text message
            message_text = message_data.get('body', '') if isinstance(message_data, dict) else str(message_data)
            send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_text_message')
            response = send_func(phone_number, message_text)
        
        # Update the message record with template info
        if response and response.get('success'):
            settings = template.get('settings', {})
            template_id = template.get('id', '')
            template_name = template.get('name', '')
            message_level = settings.get('message_level', '')
            next_level = settings.get('next_level', '')
            
            # Update the last sent message with template and level info
            frappe.db.set_value(
                'WhatsApp Chat Message',
                {'message_id': response.get('message_id')},
                {
                    'template_id': template_id,
                    'template_name': template_name,
                    'message_level': message_level,
                    'next_level': next_level
                }
            )
        
        logger.info(f"Sent {template_type} template response to {phone_number}")
        return response
        
    except Exception as e:
        logger.error(f"Error sending template response: {str(e)}")
        frappe.log_error(title="Template Response Error", message=str(e))
        return None


def _process_chatbot_message(phone_number, message_text):
    """Process incoming message through chatbot logic using the RoutingEngine"""
    try:
        # Load chatbot configuration
        config_data = _load_chatbot_config()
        if not config_data:
            logger.warning("No chatbot config available")
            return
        
        # Get active chatbot
        chatbot = _get_active_chatbot(config_data)
        if not chatbot:
            logger.warning("No active chatbot found")
            return
        
        # Use the new RoutingEngine to find the appropriate template
        engine = RoutingEngine(chatbot)
        template = engine.find_response_template(phone_number, message_text)
        
        # If template found, send the response
        if template:
            logger.info(f"Found template {template.get('id')} for message from {phone_number}")
            _send_template_response(phone_number, template)
        else:
            logger.info(f"No matching template found for message from {phone_number}")
            
    except Exception as e:
        logger.error(f"Error processing chatbot message: {str(e)}")
        frappe.log_error(title="Chatbot Processing Error", message=str(e))


def _internal_webhook_handler(wa_id: str, payload: dict):
    """Process webhook data internally

    Args:
        wa_id (str): WhatsApp user ID
        payload (dict): webhook raw payload data to process
    """
    try:
        lock_key = create_cache_key(f"lock:{wa_id}")
        
        with frappe.cache().lock(lock_key, timeout=LOCK_LEASE_TIME, blocking_timeout=LOCK_WAIT_TIME):
            # Save incoming messages to chat database
            _save_incoming_message(payload)
            
            # Update message statuses
            _save_message_status(payload)
            
            # Process message templates
            _process_message_templates(payload)
            
            # Process with existing engine
            get_engine_config().process_webhook(payload)

    except redis.exceptions.LockError:
        logger.critical("FIFO Enforcement: Dropped concurrent message for %s due to lock error.", wa_id)

    except Exception:
        frappe.log_error(title="Chatbot Webhook E.Handler")


def _on_job_success(*args, **kwargs):
    logger.debug("Webhook job completed successfully, args: %s, kwargs %s", args, kwargs)


def _on_job_error(*args, **kwargs):
    logger.debug("Webhook job failed, args: %s, kwargs %s", args, kwargs)


def _handle_webhook():
    payload = frappe.request.data

    try:
        payload_dict = json.loads(payload.decode('utf-8'))
    except json.JSONDecodeError:
        frappe.throw("Invalid webhook data", exc=frappe.ValidationError)

    should_run_in_bg = frappe.db.get_single_value("ChatBot Config", "process_in_background")

    wa_user = get_wa_config(bot_settings()).util.get_wa_user(payload_dict)

    if wa_user is None:
        return "Invalid user"
    
    job_id = f"{wa_user.wa_id}:{wa_user.msg_id}"
    
    logger.debug("Starting a new webhook job id: %s", job_id)

    frappe.enqueue(
        _internal_webhook_handler,
        now=should_run_in_bg == 0,

        payload=payload_dict,
        wa_id=wa_user.wa_id,

        job_id=create_cache_key(job_id),
        on_success=_on_job_success,
        on_failure=_on_job_error
    )

    return "OK"


@frappe.whitelist()
def get_webhook():
    return frappe.utils.get_request_site_address() + '/api/method/frappe_pywce.webhook.webhook'


@frappe.whitelist()
def clear_session():
    frappe.cache.delete_keys(CACHE_KEY_PREFIX)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def webhook():
    if frappe.request.method == 'GET':
        return _verifier()
    
    if frappe.request.method == 'POST':
        return _handle_webhook()
    
    frappe.throw("Forbidden method", exc=frappe.PermissionError)