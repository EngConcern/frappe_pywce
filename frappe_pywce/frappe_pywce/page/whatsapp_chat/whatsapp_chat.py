import frappe
import requests
from datetime import datetime
import json


def normalize_phone_number(phone_number):
    """Normalize phone number to consistent format (digits only)"""
    if not phone_number:
        return None
    return ''.join(filter(str.isdigit, str(phone_number)))


@frappe.whitelist()
def get_conversations():
    """Get all unique phone numbers with their last message"""
    conversations = frappe.db.sql("""
        SELECT 
            phone_number,
            (SELECT contact_name 
             FROM `tabWhatsApp Chat Message` wcm2 
             WHERE wcm2.phone_number = wcm.phone_number 
             AND contact_name IS NOT NULL 
             AND contact_name != ''
             ORDER BY timestamp DESC 
             LIMIT 1) as contact_name,
            MAX(timestamp) as last_message_time,
            (SELECT message_text 
             FROM `tabWhatsApp Chat Message` wcm2 
             WHERE wcm2.phone_number = wcm.phone_number 
             ORDER BY timestamp DESC 
             LIMIT 1) as last_message,
            (SELECT COUNT(*) 
             FROM `tabWhatsApp Chat Message` wcm3 
             WHERE wcm3.phone_number = wcm.phone_number 
             AND wcm3.status != 'read' 
             AND wcm3.direction = 'Incoming') as unread_count
        FROM `tabWhatsApp Chat Message` wcm
        GROUP BY phone_number
        ORDER BY last_message_time DESC
    """, as_dict=True)
    
    return conversations


@frappe.whitelist()
def get_messages(phone_number, limit=100):
    """Get messages for a specific phone number"""
    # Normalize the phone number for querying
    normalized_phone = normalize_phone_number(phone_number)
    
    messages = frappe.get_all(
        "WhatsApp Chat Message",
        filters={"phone_number": normalized_phone},
        fields=[
            "name", "phone_number", "message_id", "timestamp", 
            "direction", "message_type", "message_text", 
            "media_url", "media_type", "status", "contact_name", "metadata"
        ],
        order_by="timestamp asc",
        limit=limit
    )
    
    # Process metadata for each message
    for msg in messages:
        if msg.metadata:
            try:
                msg.metadata = json.loads(msg.metadata) if isinstance(msg.metadata, str) else msg.metadata
            except:
                msg.metadata = {}
    
    # Mark incoming messages as read
    frappe.db.sql("""
        UPDATE `tabWhatsApp Chat Message`
        SET status = 'read'
        WHERE phone_number = %s 
        AND direction = 'Incoming'
        AND status != 'read'
    """, (normalized_phone,))
    frappe.db.commit()
    
    return messages


@frappe.whitelist()
def send_message(phone_number, message_text, message_type="text"):
    """Send a message via WhatsApp API"""
    try:
        # Normalize phone number - remove all non-numeric characters
        clean_phone = normalize_phone_number(phone_number)
        
        # Get contact name from existing messages
        contact_name = frappe.db.get_value(
            "WhatsApp Chat Message",
            {"phone_number": clean_phone},
            "contact_name",
            order_by="timestamp desc"
        )
        
        # Save message to database FIRST (optimistic save)
        message_doc = frappe.get_doc({
            "doctype": "WhatsApp Chat Message",
            "phone_number": clean_phone,
            "message_id": None,  # Will be updated when we get response
            "timestamp": datetime.now(),
            "direction": "Outgoing",
            "message_type": message_type,
            "message_text": message_text,
            "contact_name": contact_name,
            "status": "sent"
        })
        message_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        # Return immediately to UI
        frappe.enqueue(
            _send_message_async,
            queue='short',
            timeout=30,
            now=False,
            message_name=message_doc.name,
            phone_number=clean_phone,
            message_text=message_text,
            message_type=message_type
        )
        
        return {
            "success": True, 
            "message": message_doc.as_dict()
        }
    
    except Exception as e:
        frappe.log_error(
            title="WhatsApp Send Message Error",
            message=f"Phone: {phone_number}\nError: {str(e)}"
        )
        return {
            "success": False, 
            "error": str(e)
        }


def _send_message_async(message_name, phone_number, message_text, message_type):
    """Send message to WhatsApp API asynchronously"""
    try:
        # Get ChatBot Config
        config = frappe.get_single("ChatBot Config")
        
        # Prepare API request
        url = f"https://graph.facebook.com/v18.0/{config.phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {config.get_password('access_token')}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "type": "text",
            "text": {
                "body": message_text
            }
        }
        
        # Send message to WhatsApp API
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Get message ID from response
        message_id = None
        if result.get("messages") and len(result["messages"]) > 0:
            message_id = result["messages"][0].get("id")
        
        # Update message with ID and status
        frappe.db.set_value(
            "WhatsApp Chat Message",
            message_name,
            {
                "message_id": message_id,
                "status": "sent"
            }
        )
        frappe.db.commit()
        
        # Publish realtime event
        frappe.publish_realtime(
            event='whatsapp_message_status_updated',
            message={
                'phone_number': phone_number,
                'message_id': message_id,
                'message_name': message_name,
                'status': 'sent'
            }
        )
        
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                error_msg = json.dumps(error_detail, indent=2)
            except:
                error_msg = e.response.text
        
        # Update message status to failed
        frappe.db.set_value(
            "WhatsApp Chat Message",
            message_name,
            {
                "status": "failed",
                "error_message": error_msg
            }
        )
        frappe.db.commit()
        
        frappe.log_error(
            title="WhatsApp Send Message Error",
            message=f"Phone: {phone_number}\nError: {error_msg}"
        )
        
        # Publish failure event
        frappe.publish_realtime(
            event='whatsapp_message_status_updated',
            message={
                'phone_number': phone_number,
                'message_name': message_name,
                'status': 'failed',
                'error': error_msg
            }
        )
    
    except Exception as e:
        # Update message status to failed
        frappe.db.set_value(
            "WhatsApp Chat Message",
            message_name,
            {
                "status": "failed",
                "error_message": str(e)
            }
        )
        frappe.db.commit()
        
        frappe.log_error(
            title="WhatsApp Send Message Error",
            message=f"Phone: {phone_number}\nError: {str(e)}"
        )
        
        # Publish failure event
        frappe.publish_realtime(
            event='whatsapp_message_status_updated',
            message={
                'phone_number': phone_number,
                'message_name': message_name,
                'status': 'failed',
                'error': str(e)
            }
        )


@frappe.whitelist()
def mark_as_read(phone_number):
    """Mark all messages from a phone number as read"""
    normalized_phone = normalize_phone_number(phone_number)
    
    frappe.db.sql("""
        UPDATE `tabWhatsApp Chat Message`
        SET status = 'read'
        WHERE phone_number = %s 
        AND direction = 'Incoming'
    """, (normalized_phone,))
    frappe.db.commit()
    
    return {"success": True}


@frappe.whitelist()
def get_unread_count():
    """Get total unread message count across all conversations"""
    result = frappe.db.sql("""
        SELECT COUNT(*) as count
        FROM `tabWhatsApp Chat Message`
        WHERE status != 'read' 
        AND direction = 'Incoming'
    """, as_dict=True)
    
    return result[0].get('count', 0) if result else 0


@frappe.whitelist()
def search_messages(query, phone_number=None):
    """Search messages by text content"""
    filters = {
        "message_text": ["like", f"%{query}%"]
    }
    
    if phone_number:
        filters["phone_number"] = normalize_phone_number(phone_number)
    
    messages = frappe.get_all(
        "WhatsApp Chat Message",
        filters=filters,
        fields=[
            "name", "phone_number", "message_text", 
            "timestamp", "contact_name", "direction"
        ],
        order_by="timestamp desc",
        limit=50
    )
    
    return messages


@frappe.whitelist()
def delete_conversation(phone_number):
    """Delete all messages for a phone number"""
    try:
        normalized_phone = normalize_phone_number(phone_number)
        
        frappe.db.delete("WhatsApp Chat Message", {
            "phone_number": normalized_phone
        })
        frappe.db.commit()
        
        return {"success": True}
    except Exception as e:
        frappe.log_error(
            title="Delete Conversation Error",
            message=f"Phone: {phone_number}\nError: {str(e)}"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_or_create_folder(path, is_private=False):
    """Ensure a folder exists inside the File doctype."""
    parts = path.split("/")
    parent = None
    current_path = ""

    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part

        # Check if folder exists
        folder = frappe.db.get_value(
            "File",
            {"file_name": part, "folder": parent if parent else "Home", "is_folder": 1},
            "name"
        )

        if not folder:
            # Create folder
            folder_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": part,
                "is_folder": 1,
                "folder": parent if parent else "Home",
                "is_private": 1 if is_private else 0
            })
            folder_doc.insert(ignore_permissions=True)
            folder = folder_doc.name

        parent = folder

    return parent

@frappe.whitelist()
def get_media_url(media_id):
    """Get media URL from WhatsApp API and download it"""
    try:
        config = frappe.get_single("ChatBot Config")

        # Get media URL details
        url = f"https://graph.facebook.com/v18.0/{media_id}"
        headers = {
            "Authorization": f"Bearer {config.get_password('access_token')}"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()

        media_url = result.get("url")
        mime_type = result.get("mime_type")

        # Download media file
        media_response = requests.get(media_url, headers=headers, timeout=30)
        media_response.raise_for_status()

        # Ensure the folder exists
        folder_path = "Home/erpext"     # your custom folder
        folder_name = get_or_create_folder(folder_path, is_private=False)

        # Save file in Frappe
        file_name = f"whatsapp_media_{media_id}"
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "content": media_response.content,
            "is_private": 0,
            "folder": folder_name
        })
        file_doc.save(ignore_permissions=True)

        return {
            "success": True,
            "url": file_doc.file_url,
            "mime_type": mime_type
        }

    except Exception as e:
        frappe.log_error(
            title="Get Media URL Error",
            message=f"Media ID: {media_id}\nError: {str(e)}"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def normalize_existing_phone_numbers():
    """One-time utility to normalize all existing phone numbers in the database"""
    messages = frappe.get_all(
        "WhatsApp Chat Message",
        fields=["name", "phone_number"]
    )
    
    updated = 0
    for msg in messages:
        normalized = normalize_phone_number(msg.phone_number)
        if normalized != msg.phone_number:
            frappe.db.set_value(
                "WhatsApp Chat Message",
                msg.name,
                "phone_number",
                normalized,
                update_modified=False
            )
            updated += 1
    
    frappe.db.commit()
    
    return {
        "success": True,
        "message": f"Normalized {updated} phone numbers out of {len(messages)} total messages"
    }