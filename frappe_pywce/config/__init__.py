import frappe

from frappe_pywce.managers import FrappeRedisSessionManager, FrappeStorageManager
from frappe_pywce.util import bot_settings, frappe_recursive_renderer
from frappe_pywce.pywce_logger import app_logger

from pywce import Engine, client, EngineConfig, HookArg


LOCAL_EMULATOR_URL = "http://localhost:3001/send-to-emulator"

def on_hook_listener(arg: HookArg) -> None:
    """Save hook to local

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
        wa = get_wa_config(settings)
        app_logger.info(f"   ✅ WhatsApp client ready")
        
        # Create engine config
        app_logger.info("4️⃣ Creating Engine Configuration...")
        _eng_config = EngineConfig(
            whatsapp=wa,
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
        app_logger.info("✅ PYWCE ENGINE READY")
        app_logger.info("=" * 80)
        
        return engine

    except Exception as e:
        app_logger.error("=" * 80)
        app_logger.error("❌ FAILED TO LOAD ENGINE CONFIG")
        app_logger.error("=" * 80)
        app_logger.error(f"Error: {str(e)}", exc_info=True)
        frappe.throw("Failed to load engine config", exc=e)