"""
Multi-Bot Message Sender

Handles sending WhatsApp messages for the multi-bot system.
Supports all message types and saves messages to database with bot context.
"""

import json
from typing import Optional, Dict, Any

import frappe

from frappe_pywce.pywce_logger import app_logger as logger


class MultiBotSender:
    """
    Handles sending templates for multi-bot system.
    Similar to TemplateSender but with bot context.
    """
    
    def __init__(self, phone_number: str, bot_slug: str):
        self.phone_number = self._normalize_phone(phone_number)
        self.bot_slug = bot_slug
    
    def _normalize_phone(self, phone: str) -> str:
        """Remove all non-numeric characters from phone number"""
        return ''.join(filter(str.isdigit, str(phone)))
    
    def send_template(self, template: Dict) -> Optional[Dict]:
        """
        Send a template message based on its type.
        
        Args:
            template: Template dict with id, name, type, message, settings, routes
            
        Returns:
            Response dict with success status and message_id
        """
        if not template:
            logger.warning("No template provided to send")
            return None
        
        template_type = template.get("type", "text")
        message_data = template.get("message", {})
        
        # Normalize message_data
        if isinstance(message_data, str):
            message_data = {"body": message_data}
        
        logger.info(f"Sending {template_type} template '{template.get('name')}' to {self.phone_number}")
        
        # Dispatch to appropriate sender
        response = self._dispatch_by_type(template_type, message_data, template)
        
        # Save outgoing message
        if response and response.get("success"):
            self._save_outgoing_message(
                template=template,
                message_id=response.get("message_id"),
                message_text=self._extract_message_text(template_type, message_data)
            )
        
        return response
    
    def _dispatch_by_type(self, template_type: str, message_data: Dict, template: Dict) -> Optional[Dict]:
        """Dispatch to specific sender based on template type"""
        dispatch_map = {
            "text": self._send_text,
            "button": self._send_button,
            "list": self._send_list,
            "cta": self._send_cta,
            "request-location": self._send_location_request,
            "media": self._send_media,
            "location": self._send_location,
            "contacts": self._send_contacts,
            "template": self._send_wa_template,
            "flow": self._send_flow,
        }
        
        sender = dispatch_map.get(template_type, self._send_text)
        try:
            return sender(message_data, template)
        except Exception as e:
            logger.error(f"Error sending {template_type} message: {str(e)}")
            frappe.log_error(title=f"MultiBotSender Error ({template_type})", message=str(e))
            return {"success": False, "error": str(e)}
    
    def _send_text(self, message_data: Dict, template: Dict) -> Dict:
        """Send text message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_text_message
        
        body = message_data.get("body", "") if isinstance(message_data, dict) else str(message_data)
        body = self._render_template_variables(body)
        
        result = send_text_message(self.phone_number, body)
        return self._parse_api_response(result)
    
    def _send_button(self, message_data: Dict, template: Dict) -> Dict:
        """Send button message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_button_message
        
        body = message_data.get("body", "")
        body = self._render_template_variables(body)
        
        buttons = message_data.get("buttons", [])
        # Convert string buttons to proper format
        formatted_buttons = []
        for i, btn in enumerate(buttons[:3]):  # Max 3 buttons
            if isinstance(btn, str):
                formatted_buttons.append({"id": f"btn_{i}", "title": btn})
            elif isinstance(btn, dict):
                formatted_buttons.append({
                    "id": btn.get("id", f"btn_{i}"),
                    "title": btn.get("title", btn.get("text", f"Button {i+1}"))
                })
        
        header_text = message_data.get("title") or message_data.get("header")
        footer_text = message_data.get("footer")
        
        result = send_button_message(
            self.phone_number,
            body,
            formatted_buttons,
            header_text=header_text,
            footer_text=footer_text
        )
        return self._parse_api_response(result)
    
    def _send_list(self, message_data: Dict, template: Dict) -> Dict:
        """Send list message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_list_message
        
        body = message_data.get("body", "")
        body = self._render_template_variables(body)
        
        button_text = message_data.get("button_text", message_data.get("button", "View Options"))
        sections = message_data.get("sections", [])
        
        header_text = message_data.get("title") or message_data.get("header")
        footer_text = message_data.get("footer")
        
        result = send_list_message(
            self.phone_number,
            body,
            button_text,
            sections,
            header_text=header_text,
            footer_text=footer_text
        )
        return self._parse_api_response(result)
    
    def _send_cta(self, message_data: Dict, template: Dict) -> Dict:
        """Send CTA URL button message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_cta_url_message
        
        body = message_data.get("body", "")
        body = self._render_template_variables(body)
        
        button_text = message_data.get("button_text", message_data.get("button", "Open Link"))
        url = message_data.get("url", "")
        
        header_text = message_data.get("title") or message_data.get("header")
        footer_text = message_data.get("footer")
        
        result = send_cta_url_message(
            self.phone_number,
            body,
            button_text,
            url,
            header_text=header_text,
            footer_text=footer_text
        )
        return self._parse_api_response(result)
    
    def _send_location_request(self, message_data: Dict, template: Dict) -> Dict:
        """Send location request message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import request_location_message
        
        body = message_data.get("body", "Please share your location")
        body = self._render_template_variables(body)
        
        result = request_location_message(self.phone_number, body)
        return self._parse_api_response(result)
    
    def _send_media(self, message_data: Dict, template: Dict) -> Dict:
        """Send media message (image, video, audio, document)"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_media_message
        
        media_type = message_data.get("media_type", "image")
        media_url = message_data.get("url", message_data.get("link", ""))
        caption = message_data.get("caption", "")
        caption = self._render_template_variables(caption)
        
        result = send_media_message(self.phone_number, media_type, media_url, caption)
        return self._parse_api_response(result)
    
    def _send_location(self, message_data: Dict, template: Dict) -> Dict:
        """Send location message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_location_message
        
        latitude = message_data.get("latitude", 0)
        longitude = message_data.get("longitude", 0)
        name = message_data.get("name", "")
        address = message_data.get("address", "")
        
        result = send_location_message(self.phone_number, latitude, longitude, name, address)
        return self._parse_api_response(result)
    
    def _send_contacts(self, message_data: Dict, template: Dict) -> Dict:
        """Send contact card message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_contact_message
        
        contacts = message_data.get("contacts", [])
        result = send_contact_message(self.phone_number, contacts)
        return self._parse_api_response(result)
    
    def _send_wa_template(self, message_data: Dict, template: Dict) -> Dict:
        """Send WhatsApp template message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_template_message
        
        template_name = message_data.get("template_name", "")
        language = message_data.get("language", "en")
        components = message_data.get("components", [])
        
        result = send_template_message(self.phone_number, template_name, language, components)
        return self._parse_api_response(result)
    
    def _send_flow(self, message_data: Dict, template: Dict) -> Dict:
        """Send WhatsApp Flow message"""
        from frappe_pywce.frappe_pywce.api.whatsapp_api import send_flow_message
        
        flow_id = message_data.get("flow_id", "")
        flow_token = message_data.get("flow_token", "")
        flow_cta = message_data.get("flow_cta", "Continue")
        body = message_data.get("body", "")
        body = self._render_template_variables(body)
        
        result = send_flow_message(
            self.phone_number,
            flow_id,
            flow_token,
            flow_cta,
            body
        )
        return self._parse_api_response(result)
    
    def _parse_api_response(self, result) -> Dict:
        """Parse API response to standard format"""
        if result is None:
            return {"success": False, "error": "No response from API"}
        
        if isinstance(result, dict):
            if result.get("messages"):
                return {
                    "success": True,
                    "message_id": result["messages"][0].get("id", "")
                }
            elif result.get("error"):
                return {"success": False, "error": str(result.get("error"))}
            elif result.get("success") is not None:
                return result
        
        return {"success": True, "message_id": ""}
    
    def _render_template_variables(self, text: str) -> str:
        """Render Jinja-like template variables"""
        if not text or "{{" not in text:
            return text
        
        try:
            # Get session data for variables
            session = frappe.db.get_value(
                "User Bot Session",
                {"phone_number": self.phone_number, "is_active": 1},
                ["session_data", "context_data"],
                as_dict=True
            )
            
            context = {}
            if session:
                if session.session_data:
                    try:
                        context["s"] = json.loads(session.session_data)
                    except:
                        context["s"] = {}
                if session.context_data:
                    try:
                        context.update(json.loads(session.context_data))
                    except:
                        pass
            
            # Simple variable replacement
            import re
            def replace_var(match):
                var_path = match.group(1).strip()
                parts = var_path.split(".")
                value = context
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part, "")
                    else:
                        return ""
                return str(value) if value else ""
            
            return re.sub(r"\{\{\s*(.+?)\s*\}\}", replace_var, text)
        except Exception as e:
            logger.warning(f"Error rendering template variables: {e}")
            return text
    
    def _extract_message_text(self, template_type: str, message_data: Dict) -> str:
        """Extract readable message text for logging"""
        if isinstance(message_data, str):
            return message_data
        
        if template_type == "text":
            return message_data.get("body", "")
        elif template_type in ["button", "list", "cta"]:
            return message_data.get("body", message_data.get("title", ""))
        elif template_type == "media":
            return message_data.get("caption", f"[{message_data.get('media_type', 'media')}]")
        elif template_type == "location":
            return f"[Location: {message_data.get('name', 'Shared location')}]"
        elif template_type == "request-location":
            return message_data.get("body", "Location request")
        else:
            return str(message_data)[:200]
    
    def _save_outgoing_message(self, template: Dict, message_id: str, message_text: str):
        """Save outgoing message to WhatsApp Chat Message doctype"""
        try:
            settings = template.get("settings", {})
            
            message_doc = frappe.get_doc({
                "doctype": "WhatsApp Chat Message",
                "phone_number": self.phone_number,
                "message_id": message_id,
                "timestamp": frappe.utils.now_datetime(),
                "direction": "Outgoing",
                "message_type": template.get("type", "text"),
                "message_text": message_text[:65535] if message_text else "",
                "status": "sent",
                "template_id": template.get("id", ""),
                "template_name": template.get("name", ""),
                "message_level": settings.get("message_level", ""),
                "next_level": settings.get("next_level", ""),
                "metadata": json.dumps({
                    "bot_slug": self.bot_slug,
                    "template": template
                })
            })
            message_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            
            logger.debug(f"Saved outgoing message {message_id} for bot {self.bot_slug}")
            
        except Exception as e:
            logger.error(f"Failed to save outgoing message: {str(e)}")
            frappe.log_error(title="Save Outgoing Message Error", message=str(e))


def send_multi_bot_template(phone_number: str, bot_slug: str, template: Dict) -> Optional[Dict]:
    """Convenience function to send a template"""
    sender = MultiBotSender(phone_number, bot_slug)
    return sender.send_template(template)
