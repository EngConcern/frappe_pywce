import time
import frappe

from frappe_pywce.managers import FrappeRedisSessionManager, FrappeStorageManager
from frappe_pywce.util import bot_settings, frappe_recursive_renderer
from frappe_pywce.pywce_logger import app_logger

from pywce import Engine, client, EngineConfig, HookArg


LOCAL_EMULATOR_URL = "http://localhost:3001/send-to-emulator"

def on_hook_listener(arg: HookArg) -> None:
    """Save hook to local and apply message controls (delay, typing, ack)

    arg = getattr(frappe.local, "hook_arg", None)
    
    Args:
        arg (HookArg): Hook argument
    """
    app_logger.info("=" * 80)
    app_logger.info("🎣 HOOK LISTENER TRIGGERED")
    app_logger.info("=" * 80)
    
    # Log hook details
    app_logger.info(f"Hook Type: {type(arg)}")
    app_logger.info(f"Hook Attributes: {dir(arg)}")
    
    # Try to log specific hook data
    try:
        if hasattr(arg, '__dict__'):
            app_logger.info(f"Hook Data: {arg.__dict__}")
    except Exception as e:
        app_logger.warning(f"Could not log hook data: {e}")
    
    # APPLY MESSAGE CONTROLS HERE (before message is sent)
    try:
        # Get storage manager from frappe.local if available
        storage_manager = getattr(frappe.local, 'storage_manager', None)
        wa_client = getattr(frappe.local, 'wa_client', None)
        
        if storage_manager and hasattr(arg, 'template_name') and hasattr(arg, 'recipient'):
            template_name = arg.template_name
            recipient = arg.recipient
            
            # Get template settings
            settings = storage_manager.get_template_settings(template_name)
            
            if settings:
                app_logger.info("=" * 80)
                app_logger.info(f"📋 APPLYING MESSAGE CONTROLS FOR: {template_name}")
                app_logger.info("=" * 80)
                
                # Apply typing indicator
                if settings.get('typing', False) and wa_client:
                    try:
                        app_logger.info("⌨️ Sending typing indicator...")
                        wa_client.mark_typing(recipient)
                        app_logger.info("✅ Typing indicator sent")
                    except Exception as e:
                        app_logger.error(f"❌ Failed to send typing indicator: {e}")
                
                # Apply delay
                delay_time = settings.get('delay_time', 0)
                app_logger.info(f"============================Delaying message by {delay_time} seconds...")
                if delay_time > 0:
                    app_logger.info(f"⏳ Delaying message by {delay_time} seconds...")
                    time.sleep(delay_time)
                    app_logger.info(f"✅ Delay complete ({delay_time}s)")
                
                # Apply read receipt (before sending - marks conversation as read)
                if settings.get('ack', False) and wa_client:
                    try:
                        app_logger.info("✓✓ Marking as read...")
                        wa_client.mark_read(recipient)
                        app_logger.info("✅ Read receipt sent")
                    except Exception as e:
                        app_logger.error(f"❌ Failed to send read receipt: {e}")
                
                app_logger.info("=" * 80)
            else:
                app_logger.info(f"No specific message controls for template: {template_name}")
    except Exception as e:
        app_logger.error(f"❌ Failed to apply message controls: {e}")
    
    frappe.local.hook_arg = arg
    app_logger.info('✅ Updated hook arg in frappe.local')
    app_logger.info("=" * 80)

def on_client_send_listener() -> None:
    """Reset hook_arg to None - CALLED AFTER MESSAGE IS SENT"""
    app_logger.info("=" * 80)
    app_logger.info("📤 CLIENT SEND LISTENER TRIGGERED")
    app_logger.info("=" * 80)
    app_logger.info("✉️ MESSAGE HAS BEEN SENT TO WHATSAPP!")
    
    # Log what was sent if available
    hook_arg = getattr(frappe.local, "hook_arg", None)
    if hook_arg:
        app_logger.info(f"Sent Hook Arg: {hook_arg}")
    else:
        app_logger.warning("No hook_arg found in frappe.local")
    
    frappe.local.hook_arg = None
    app_logger.info("🧹 Cleared hook_arg from frappe.local")
    app_logger.info("=" * 80)

def get_wa_config(settings) -> client.WhatsApp:
    """Configure WhatsApp client"""
    app_logger.info("🔧 Configuring WhatsApp Client")
    app_logger.info(f"  - Phone ID: {settings.phone_id}")
    app_logger.info(f"  - Environment: {settings.env}")
    app_logger.info(f"  - Use Emulator: {settings.env == 'local'}")
    
    if settings.env == "local":
        app_logger.warning(f"⚠️ EMULATOR MODE - Messages will be sent to: {LOCAL_EMULATOR_URL}")
    else:
        app_logger.info("📡 PRODUCTION MODE - Messages will be sent to WhatsApp API")
    
    _wa_config = client.WhatsAppConfig(
        token=settings.access_token,
        phone_number_id=settings.phone_id,
        hub_verification_token=settings.webhook_token,
        app_secret=settings.get_password('app_secret', raise_exception=False),
        use_emulator=settings.env == "local",
        emulator_url=LOCAL_EMULATOR_URL
    )

    wa_client = client.WhatsApp(_wa_config, on_send_listener=on_client_send_listener)
    app_logger.info("✅ WhatsApp client configured successfully")
    
    return wa_client


def get_engine_config() -> Engine:
    """
    Initialize and configure the PyWCE Engine.
    
    This is the MAIN ENGINE that:
    1. Loads templates via FrappeStorageManager
    2. Manages sessions via FrappeRedisSessionManager  
    3. Sends messages via WhatsApp client
    4. Applies message controls (delay, typing, ack) in hook listener
    """
    try:
        app_logger.info("=" * 80)
        app_logger.info("🚀 INITIALIZING PYWCE ENGINE")
        app_logger.info("=" * 80)
        
        # Load bot settings
        app_logger.info("1️⃣ Loading bot settings...")
        settings = bot_settings()
        app_logger.info(f"   ✅ Bot settings loaded")
        
        # Initialize storage manager (templates)
        app_logger.info("2️⃣ Initializing Storage Manager...")
        storage_manager = FrappeStorageManager(settings.flow_json)
        app_logger.info(f"   ✅ Storage Manager initialized")
        app_logger.info(f"   - START_MENU: {storage_manager.START_MENU}")
        app_logger.info(f"   - REPORT_MENU: {storage_manager.REPORT_MENU}")
        app_logger.info(f"   - Total Templates: {len(storage_manager._TEMPLATES)}")
        
        # Initialize WhatsApp client
        app_logger.info("3️⃣ Initializing WhatsApp Client...")
        wa_client = get_wa_config(settings)
        app_logger.info(f"   ✅ WhatsApp client ready")
        
        # Store in frappe.local for hook listener access
        frappe.local.storage_manager = storage_manager
        frappe.local.wa_client = wa_client
        app_logger.info("   ✅ Stored storage_manager and wa_client in frappe.local")
        
        # Create engine config
        app_logger.info("4️⃣ Creating Engine Configuration...")
        _eng_config = EngineConfig(
            whatsapp=wa_client,
            storage_manager=storage_manager,
            start_template_stage=storage_manager.START_MENU,
            report_template_stage=storage_manager.REPORT_MENU,
            session_manager=FrappeRedisSessionManager(),
            external_renderer=frappe_recursive_renderer,
            on_hook_arg=on_hook_listener
        )
        app_logger.info(f"   ✅ Engine config created")
        
        # Initialize engine
        app_logger.info("5️⃣ Initializing Engine...")
        engine = Engine(config=_eng_config)
        app_logger.info(f"   ✅ Engine initialized successfully")
        
        app_logger.info("=" * 80)
        app_logger.info("✅ PYWCE ENGINE READY WITH MESSAGE CONTROLS IN HOOK")
        app_logger.info("=" * 80)
        
        return engine

    except Exception as e:
        app_logger.error("=" * 80)
        app_logger.error("❌ FAILED TO LOAD ENGINE CONFIG")
        app_logger.error("=" * 80)
        app_logger.error(f"Error: {str(e)}", exc_info=True)
        frappe.throw("Failed to load engine config", exc=e)