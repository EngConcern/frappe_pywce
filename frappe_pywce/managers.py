import json
from typing import Dict, Any, List, Optional, Type, TypeVar

import frappe

from pywce import ISessionManager, VisualTranslator, storage, template

from frappe_pywce.pywce_logger import app_logger as logger

T = TypeVar("T")

CACHE_KEY_PREFIX = "fpw:"

def create_cache_key(k:str):
    return f'{CACHE_KEY_PREFIX}{k}'

class FrappeStorageManager(storage.IStorageManager):
    """
    Implements the IStorageManager interface for a live Frappe backend.

    This class is responsible for:
    1. Fetching the "active" chatbot flow.
    2. Caching the *translated* pywce-compatible dictionary.
    3. Invalidating the cache when the bot is saved in Frappe.
    """
    _TEMPLATES: Dict = {}
    _TRIGGERS: List[template.EngineRoute] = {}

    START_MENU: Optional[str] = None
    REPORT_MENU: Optional[str] = None
    
    def __init__(self, flow_json, chatbot_name=None):
        self.flow_json = flow_json
        self.chatbot_name = chatbot_name
        self._ensure_templates_loaded()
    
    def _extract_all_templates_from_flow(self, flow_data):
        """
        Extract ALL templates from all chatbots, regardless of chatbot_name.
        Returns a dict with merged 'templates' and 'version' keys.
        """
        all_templates = []
        
        # Check if it's the new multi-chatbot format
        if isinstance(flow_data, dict) and 'chatbots' in flow_data:
            chatbots = flow_data.get('chatbots', [])
            
            if not chatbots:
                logger.error("No chatbots found in flow_json")
                raise Exception("No chatbots found in flow_json")
            
            logger.info(f"Found {len(chatbots)} chatbot(s) in flow_json")
            
            # Merge templates from ALL chatbots
            for bot in chatbots:
                bot_name = bot.get('name', 'Unknown')
                templates = bot.get('templates', [])
                
                if not templates:
                    logger.warning(f"Chatbot '{bot_name}' has no templates, skipping")
                    continue
                
                logger.info(f"Extracting {len(templates)} templates from chatbot '{bot_name}'")
                
                # Log template IDs for debugging
                template_ids = [t.get('id', 'NO_ID') for t in templates]
                logger.debug(f"Template IDs from '{bot_name}': {template_ids}")
                
                all_templates.extend(templates)
            
            if not all_templates:
                logger.warning("No templates found in any chatbot!")
                return {
                    'templates': [],
                    'version': flow_data.get('version', '1.0')
                }
            
            logger.info(f"Total templates extracted from all chatbots: {len(all_templates)}")
            
            # Check for duplicate template IDs
            template_ids = [t.get('id') for t in all_templates]
            duplicates = [tid for tid in template_ids if template_ids.count(tid) > 1]
            if duplicates:
                logger.warning(f"Duplicate template IDs found: {set(duplicates)}")
            
            # Return the flow in the old format that VisualTranslator expects
            return {
                'templates': all_templates,
                'version': flow_data.get('version', '1.0')
            }
        
        # Old format (already has 'templates' at root level)
        elif isinstance(flow_data, dict) and 'templates' in flow_data:
            logger.info(f"Using old format, found {len(flow_data.get('templates', []))} templates")
            return flow_data
        
        else:
            logger.error(f"Invalid flow_json format. Keys found: {flow_data.keys() if isinstance(flow_data, dict) else 'not a dict'}")
            raise Exception("Invalid flow_json format: missing 'chatbots' or 'templates' key")
    
    def _validate_and_fix_template(self, template_name: str, template_data: dict) -> dict:
        """
        Validate and fix common template issues before they cause errors.
        
        Args:
            template_name: Name of the template
            template_data: The template dictionary
            
        Returns:
            Fixed template dictionary
        """
        template_type = template_data.get('type', 'unknown')
        
        # Fix button templates missing 'buttons' field
        if template_type == 'button':
            message = template_data.get('message', {})
            if 'buttons' not in message or not message.get('buttons'):
                logger.warning(f"Template '{template_name}' is type 'button' but has no buttons!")
                
                # Option 1: Convert to text template
                if not message.get('buttons'):
                    logger.info(f"Converting '{template_name}' from 'button' to 'text' template")
                    template_data['type'] = 'text'
                # Option 2: Add empty buttons array
                else:
                    logger.info(f"Adding empty buttons array to '{template_name}'")
                    message['buttons'] = []
                    template_data['message'] = message
        
        # Fix list templates missing 'sections' field
        elif template_type == 'list':
            message = template_data.get('message', {})
            if 'sections' not in message:
                logger.warning(f"Template '{template_name}' is type 'list' but has no sections!")
                message['sections'] = []
                template_data['message'] = message
        
        # Fix CTA templates missing 'url' field
        elif template_type == 'cta':
            message = template_data.get('message', {})
            if 'url' not in message:
                logger.warning(f"Template '{template_name}' is type 'cta' but has no url!")
                message['url'] = ''
                template_data['message'] = message
        
        return template_data


    def _load_templates_from_db(self):
        """Load templates from database and translate them."""
        try:
            if not self.flow_json:
                raise Exception("No flow json found or is empty.")
            
            logger.info(f"Loading templates from flow_json (fetching all chatbots)")
            
            # Parse the flow_json if it's a string
            if isinstance(self.flow_json, str):
                flow_data = json.loads(self.flow_json)
            else:
                flow_data = self.flow_json
            
            # Extract ALL templates from all chatbots
            extracted_flow = self._extract_all_templates_from_flow(flow_data)
            
            logger.info(f"Extracted flow structure: templates={len(extracted_flow.get('templates', []))}, version={extracted_flow.get('version')}")
            
            if not extracted_flow.get('templates'):
                logger.warning("No templates to translate!")
                self._TEMPLATES = {}
                self._TRIGGERS = []
                return
            
            # Convert to JSON string for translator
            ui_translator = VisualTranslator()
            extracted_flow_json = json.dumps(extracted_flow)
            
            # Translate templates
            raw_templates, self._TRIGGERS = ui_translator.translate(extracted_flow_json)
            
            self.START_MENU = ui_translator.START_MENU
            self.REPORT_MENU = ui_translator.REPORT_MENU
            
            logger.info(f"Translation complete: {len(raw_templates)} templates, {len(self._TRIGGERS)} triggers")
            
            # Validate and fix templates before storing
            self._TEMPLATES = {}
            validation_errors = []
            
            for template_name, template_data in raw_templates.items():
                try:
                    # Validate and fix common issues
                    fixed_template = self._validate_and_fix_template(template_name, template_data)
                    
                    # Try to validate with pydantic
                    validated = template.Template.as_model(fixed_template)
                    
                    # Store validated template
                    self._TEMPLATES[template_name] = fixed_template
                    
                except Exception as e:
                    logger.error(f"Validation failed for template '{template_name}': {e}")
                    logger.error(f"Template data: {json.dumps(template_data, indent=2)}")
                    validation_errors.append({
                        'name': template_name,
                        'error': str(e),
                        'data': template_data
                    })
                    
                    # Don't store invalid templates
                    continue
            
            logger.info(f"Validation complete: {len(self._TEMPLATES)} valid templates")
            logger.info(f"Template IDs after validation: {list(self._TEMPLATES.keys())}")
            logger.info(f"START_MENU: {self.START_MENU}, REPORT_MENU: {self.REPORT_MENU}")
            
            if validation_errors:
                logger.warning(f"{len(validation_errors)} templates failed validation:")
                for error in validation_errors:
                    logger.warning(f"  - {error['name']}: {error['error']}")
                
                # Log to Frappe error log for visibility
                frappe.log_error(
                    title="Template Validation Errors",
                    message=json.dumps(validation_errors, indent=2)
                )

        except Exception as e:
            frappe.log_error(title="FrappeStorageManager Load Error", message=str(e))
            logger.error(f"Error loading templates: {str(e)}", exc_info=True)
            self._TEMPLATES = {}
            self._TRIGGERS = []


    def get(self, name: str) -> template.EngineTemplate:    
        """Get a template by name with enhanced error handling."""
        try:
            self._ensure_templates_loaded()
            
            logger.info(f"Attempting to fetch template: '{name}'")
            
            if not self._TEMPLATES:
                logger.error("No templates loaded! _TEMPLATES is empty")
                return None
            
            if name is None or name == "None":
                logger.error(f"Template name is None or 'None' string - routing issue detected")
                return None
            
            template_data = self._TEMPLATES.get(name)
            
            if template_data is None:
                logger.error(f"Template '{name}' not found in _TEMPLATES")
                logger.error(f"Available template IDs: {list(self._TEMPLATES.keys())}")
                return None
            
            # Validate before returning
            try:
                return template.Template.as_model(template_data)
            except Exception as validation_error:
                logger.critical(f"Template '{name}' failed runtime validation: {validation_error}")
                logger.critical(f"Template data: {json.dumps(template_data, indent=2)}")
                
                # Try to fix and re-validate
                fixed_template = self._validate_and_fix_template(name, template_data)
                try:
                    return template.Template.as_model(fixed_template)
                except Exception as second_error:
                    logger.critical(f"Template '{name}' still invalid after fix attempt: {second_error}")
                    return None
                
        except Exception as e:
            frappe.log_error(title="Get Template Error", message=f"Template: {name}, Error: {str(e)}")
            logger.critical(f"Error fetching template '{name}': {str(e)}", exc_info=True)
            return None

    def _ensure_templates_loaded(self):
        """
        Ensures self._TEMPLATES is populated,
        respecting the lazy-load approach.
        """
        if not self._TEMPLATES:
            self._load_templates_from_db()

    def load_templates(self) -> None:
        self._load_templates_from_db()

    def load_triggers(self) -> None:
        pass

    def exists(self, name: str) -> bool:
        self._ensure_templates_loaded()
        exists = name in self._TEMPLATES
        
        if not exists:
            logger.warning(f"Template '{name}' does not exist. Available: {list(self._TEMPLATES.keys())}")
        
        return exists

    def get(self, name: str) -> template.EngineTemplate:    
        try:
            self._ensure_templates_loaded()
            
            logger.info(f"Attempting to fetch template: '{name}'")
            
            # Check if templates were loaded
            if not self._TEMPLATES:
                logger.error("No templates loaded! _TEMPLATES is empty")
                return None
             
            logger.debug(f"Available templates: {list(self._TEMPLATES.keys())}")
            
            # Special handling for None template name
            if name is None or name == "None":
                logger.error(f"Template name is None or 'None' string. This indicates a routing issue.")
                logger.error(f"Check your template routes - one of them might be pointing to a non-existent template")
                return None
            
            template_data = self._TEMPLATES.get(name)
            
            if template_data is None:
                logger.error(f"Template '{name}' not found in _TEMPLATES")
                logger.error(f"Available template IDs: {list(self._TEMPLATES.keys())}")
                logger.error(f"This could mean:")
                logger.error(f"  1. A route is pointing to a template ID that doesn't exist")
                logger.error(f"  2. Template IDs changed but routes weren't updated")
                logger.error(f"  3. The template was removed but routes still reference it")
                return None
            
            logger.debug(f"Template data found, type: {type(template_data)}")
            
            if isinstance(template_data, dict):
                logger.debug(f"Template data keys: {template_data.keys()}")
            
            return template.Template.as_model(template_data)
            
        except Exception as e:
            frappe.log_error(title="Get Template Error", message=f"Template: {name}, Error: {str(e)}")
            logger.critical(f"Error fetching template '{name}': {str(e)}", exc_info=True)
            return None

    def triggers(self) -> List[template.EngineRoute]:
        return self._TRIGGERS
    
    def __repr__(self):
        return f"FrappeStorageManager(start_menu={self.START_MENU}, report_menu={self.REPORT_MENU}, \
            templates_count={len(self._TEMPLATES.keys())}, triggers_count={len(self._TRIGGERS)})"


class FrappeRedisSessionManager(ISessionManager):
    """
    Redis-based session manager for PyWCE in Frappe.
    
    Uses Frappe's Redis cache to store user session data.

    user data has default expiry set to 10 mins
    global data has default expiry set to 30 mins
    """
    _global_expiry = 86400
    _global_key_ = create_cache_key("global")

    def __init__(self, ttl=1800):
        """Initialize session manager with default expiry time.
        TODO: take the configured ttl in app settings
        """
        self.ttl = ttl

    def _get_prefixed_key(self, session_id, key=None):
        """Helper to create prefixed cache keys."""
        k = create_cache_key(session_id)

        if key is None:
            return k
        
        return f"{k}:{key}"
    
    def _set_data(self, session_id:str=None, session_data:dict=None, is_global=False):
        """
            set session data under 1 key for user
        """
        if session_data is None: return
        
        if is_global:
            frappe.cache.set_value(
                key=self._get_prefixed_key(self._global_key_), 
                val=json.dumps(session_data), 
                expires_in_sec=self._global_expiry
            )
            
        else:
            frappe.cache.set_value(
                key=self._get_prefixed_key(session_id), 
                val=json.dumps(session_data), 
                expires_in_sec=self.ttl
        )

    def _get_data(self, session_id:str=None, is_global=False) -> dict:
        raw = frappe.cache.get_value(
            key=self._get_prefixed_key(self._global_expiry), 
            expires=True
        ) if is_global else frappe.cache.get_value(
            key=self._get_prefixed_key(session_id), 
            expires=True
        )

        if raw is None:
            return {}
        
        return json.loads(raw)

    @property
    def prop_key(self) -> str:
        return create_cache_key("props")

    def session(self, session_id: str) -> "FrappeRedisSessionManager":
        """Initialize session in Redis if it doesn't exist."""
        return self

    def save(self, session_id: str, key: str, data: Any) -> None:
        """Save a key-value pair into the session."""
        d = self._get_data(session_id=session_id)
        d[key] = data
        self._set_data(session_id=session_id, session_data=d)

    def save_global(self, key: str, data: Any) -> None:
        """Save global key-value pair."""
        g = self._get_data(is_global=True)
        g[key] = data
        self._set_data(session_data=g, is_global=True)

    def get(self, session_id: str, key: str, t: Type[T] = None):
        """Retrieve a specific key from session."""
        d = self._get_data(session_id=session_id)
        return d.get(key)

    def get_global(self, key: str, t: Type[T] = None):
        """Retrieve global data."""
        g = self._get_data(is_global=True)
        return g.get(key)

    def fetch_all(self, session_id: str, is_global: bool = False) -> Dict[str, Any]:
        """Retrieve all session data."""
        return self._get_data(session_id=session_id, is_global=is_global)

    def evict(self, session_id: str, key: str) -> None:
        """Remove a key from session."""
        d = self._get_data(session_id=session_id)
        d.pop(key, -1)
        self._set_data(session_id= session_id, session_data=d)

    def save_all(self, session_id: str, data: Dict[str, Any]) -> None:
        """Save multiple key-value pairs at once."""
        for k, d in data.items():
            self.save(session_id, k, d)

    def evict_all(self, session_id: str, keys: List[str]) -> None:
        """Remove multiple keys from session."""
        for key in keys:
            self.evict(session_id, key)

    def evict_global(self, key: str) -> None:
        """Remove a key from global storage."""
        g = self._get_data(is_global=True)
        g.pop(key, -1)
        self._set_data(session_data=g, is_global=True)

    def clear(self, session_id: str, retain_keys: List[str] = None) -> None:
        """Clear the entire session.
        """
        if retain_keys is None or retain_keys == []:
            frappe.cache().delete_keys(self._get_prefixed_key(session_id))
            return
        
        for retain_key in retain_keys:
            data = self.fetch_all(session_id)
            for k, v in data.items():
                if retain_key in k:
                    continue

                self.evict(session_id, k)

    def clear_global(self) -> None:
        """Clear all global data."""
        frappe.cache().delete_keys(self._get_prefixed_key(self._global_key_))

    def key_in_session(self, session_id: str, key: str, check_global: bool = True) -> bool:
        """Check if a key exists in session or global storage."""
        if check_global is True:
            return self.get_global(key) is not None
        
        return self.get(session_id, key) is not None

    def get_user_props(self, session_id: str) -> Dict[str, Any]:
        """Retrieve user properties."""
        return self.get(session_id, self.prop_key) or {}

    def evict_prop(self, session_id: str, prop_key: str) -> bool:
        """Remove a property from user props."""
        current_props = self.get_user_props(session_id)
        if prop_key not in current_props:
            return False
        
        current_props.pop(prop_key, -1)
        self.save(session_id, self.prop_key, current_props)
        return True

    def get_from_props(self, session_id: str, prop_key: str, t: Type[T] = None):
        """Retrieve a property from user props."""
        props = self.get_user_props(session_id)
        return props.get(prop_key)

    def save_prop(self, session_id: str, prop_key: str, data: Any) -> None:
        """Save a property in user props."""
        current_props = self.get_user_props(session_id)
        current_props[prop_key] = data
        self.save(session_id, self.prop_key, current_props)