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


class TemplateSender:
    """
    Handles sending matched templates via WhatsApp API and saving to database.
    """
    
    def __init__(self, phone_number: str):
        """
        Initialize the template sender.
        
        Args:
            phone_number: The recipient's phone number
        """
        self.phone_number = self._normalize_phone(phone_number)
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalize phone number - remove non-numeric characters"""
        return ''.join(filter(str.isdigit, str(phone)))
    
    def send_template(self, template: Dict) -> Optional[Dict]:
        """
        Send the matched template to the user.
        
        Handles all template types:
        - text: Simple text message
        - button: Interactive button message (max 3 buttons)
        - list: Interactive list message with sections
        - cta: Call-to-action URL button
        - request-location: Request user's location
        
        Args:
            template: The matched template dict from the flow
            
        Returns:
            Response dict with success status and message_id, or None on failure
        """
        if not template:
            logger.warning("No template provided to send")
            return None
        
        template_type = template.get('type', 'text')
        template_id = template.get('id', '')
        template_name = template.get('name', '')
        message_data = template.get('message', {})
        settings = template.get('settings', {})
        
        logger.info(f"Sending template '{template_name}' (type: {template_type}) to {self.phone_number}")
        
        try:
            # Get the appropriate send function and call it
            response = self._dispatch_by_type(template_type, message_data, settings)
            
            # Save message to WhatsApp Chat Message if successful
            if response and response.get('success'):
                self._save_outgoing_message(
                    template=template,
                    message_id=response.get('message_id'),
                    message_text=self._extract_message_text(template_type, message_data)
                )
                logger.info(f"Successfully sent template '{template_name}' to {self.phone_number}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error sending template '{template_name}': {str(e)}")
            frappe.log_error(
                title=f"Template Send Error: {template_name}",
                message=f"Phone: {self.phone_number}\nTemplate ID: {template_id}\nError: {str(e)}"
            )
            return None
    
    def _dispatch_by_type(self, template_type: str, message_data: Any, settings: Dict) -> Optional[Dict]:
        """Dispatch to the appropriate send function based on template type"""
        
        if template_type == 'text':
            return self._send_text(message_data)
        
        elif template_type == 'button':
            return self._send_button(message_data)
        
        elif template_type == 'list':
            return self._send_list(message_data)
        
        elif template_type == 'cta':
            return self._send_cta(message_data)
        
        elif template_type == 'request-location':
            return self._send_location_request(message_data)
        
        elif template_type == 'media':
            return self._send_media(message_data)
        
        elif template_type == 'location':
            return self._send_location(message_data)
        
        elif template_type == 'contacts':
            return self._send_contacts(message_data)
        
        elif template_type == 'template':
            return self._send_wa_template(message_data)
        
        elif template_type == 'flow':
            return self._send_flow(message_data)
        
        else:
            # Default to text message
            logger.warning(f"Unknown template type '{template_type}', defaulting to text")
            return self._send_text(message_data)
    
    def _send_text(self, message_data: Any) -> Optional[Dict]:
        """Send a text message"""
        if isinstance(message_data, dict):
            message_text = message_data.get('body', '')
        else:
            message_text = str(message_data) if message_data else ''
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_text_message')
        return send_func(self.phone_number, message_text)
    
    def _send_button(self, message_data: Dict) -> Optional[Dict]:
        """Send a button message"""
        body_text = message_data.get('body', '')
        buttons_data = message_data.get('buttons', [])
        header_text = message_data.get('title', None)
        footer_text = message_data.get('footer', None)
        
        # Format buttons - handle both string arrays and object arrays
        buttons = []
        for i, btn in enumerate(buttons_data[:3]):  # WhatsApp allows max 3 buttons
            if isinstance(btn, str):
                buttons.append({"id": f"btn_{i}", "title": btn})
            elif isinstance(btn, dict):
                buttons.append({
                    "id": btn.get("id", f"btn_{i}"),
                    "title": btn.get("title", f"Button {i+1}")
                })
            else:
                buttons.append({"id": f"btn_{i}", "title": str(btn)})
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_button_message')
        return send_func(self.phone_number, body_text, buttons, header_text, footer_text)
    
    def _send_list(self, message_data: Dict) -> Optional[Dict]:
        """Send a list message"""
        body_text = message_data.get('body', '')
        button_text = message_data.get('button', 'Select')  # This is list_title parameter
        sections = message_data.get('sections', [])
        header_text = message_data.get('title', None)
        footer_text = message_data.get('footer', None)
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_list_message')
        return send_func(self.phone_number, body_text, button_text, sections, header_text, footer_text)
    
    def _send_cta(self, message_data: Dict) -> Optional[Dict]:
        """Send a CTA URL button message"""
        body_text = message_data.get('body', '')
        button_text = message_data.get('button', 'Open')
        url = message_data.get('url', '')
        header_text = message_data.get('title', None)
        footer_text = message_data.get('footer', None)
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_cta_url_message')
        return send_func(self.phone_number, body_text, button_text, url, header_text, footer_text)
    
    def _send_location_request(self, message_data: Any) -> Optional[Dict]:
        """Send a location request message"""
        if isinstance(message_data, dict):
            message_text = message_data.get('body', message_data.get('text', ''))
        else:
            message_text = str(message_data) if message_data else 'Please share your location'
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.request_location_message')
        return send_func(self.phone_number, message_text)
    
    def _send_media(self, message_data: Dict) -> Optional[Dict]:
        """Send a media message"""
        media_type = message_data.get('media_type', 'image')
        media_url = message_data.get('media_url', '')
        caption = message_data.get('caption', '')
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_media_message')
        return send_func(self.phone_number, media_type, media_url, caption)
    
    def _send_location(self, message_data: Dict) -> Optional[Dict]:
        """Send a location message"""
        latitude = message_data.get('latitude', 0)
        longitude = message_data.get('longitude', 0)
        name = message_data.get('name', '')
        address = message_data.get('address', '')
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_location_message')
        return send_func(self.phone_number, latitude, longitude, name, address)
    
    def _send_contacts(self, message_data: Dict) -> Optional[Dict]:
        """Send a contacts message"""
        contact_data = message_data.get('contact_data', message_data)
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_contact_message')
        return send_func(self.phone_number, contact_data)
    
    def _send_wa_template(self, message_data: Dict) -> Optional[Dict]:
        """Send a WhatsApp template message"""
        template_name = message_data.get('template_name', '')
        language_code = message_data.get('language_code', 'en')
        components = message_data.get('components', [])
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_template_message')
        return send_func(self.phone_number, template_name, language_code, components)
    
    def _send_flow(self, message_data: Dict) -> Optional[Dict]:
        """Send a flow message"""
        flow_token = message_data.get('flow_token', '')
        flow_data = message_data.get('flow_data', {})
        
        send_func = frappe.get_attr('frappe_pywce.frappe_pywce.api.whatsapp_api.send_flow_message')
        return send_func(self.phone_number, flow_token, flow_data)
    
    def _extract_message_text(self, template_type: str, message_data: Any) -> str:
        """Extract the main message text for logging/saving"""
        if isinstance(message_data, str):
            return message_data
        
        if isinstance(message_data, dict):
            return message_data.get('body', message_data.get('text', ''))
        
        return str(message_data) if message_data else ''
    
    def _save_outgoing_message(self, template: Dict, message_id: str, message_text: str):
        """Save outgoing message to WhatsApp Chat Message doctype"""
        try:
            settings = template.get('settings', {})
            
            message_doc = frappe.get_doc({
                "doctype": "WhatsApp Chat Message",
                "phone_number": self.phone_number,
                "message_id": message_id,
                "timestamp": frappe.utils.now_datetime(),
                "direction": "Outgoing",
                "message_type": template.get('type', 'text'),
                "message_text": message_text[:65535] if message_text else '',  # Truncate if too long
                "status": "sent",
                "template_id": template.get('id', ''),
                "template_name": template.get('name', ''),
                "message_level": settings.get('message_level', ''),
                "next_level": settings.get('next_level', '')
            })
            message_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            
            logger.debug(f"Saved outgoing message {message_id} for template {template.get('id')}")
            
        except Exception as e:
            logger.error(f"Failed to save outgoing message: {str(e)}")
            frappe.log_error(title="Save Outgoing Message Error", message=str(e))


def send_matched_template(phone_number: str, template: Dict) -> Optional[Dict]:
    """
    Convenience function to send a matched template.
    
    Args:
        phone_number: Recipient's phone number
        template: The matched template dict
        
    Returns:
        Response dict with success status and message_id, or None
    """
    sender = TemplateSender(phone_number)
    return sender.send_template(template)
