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
    
    Enhanced with:
    - Template validation and auto-fixing
    - Broken route detection
    - Error fallback templates
    - Better logging and diagnostics
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
        """Extract ALL templates from all chatbots, regardless of chatbot_name."""
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
    
    def _normalize_message_field(self, message):
        """
        Normalize message field to be compatible with pydantic validation.
        
        Handles both formats:
        - String: "message text"
        - Object: {"body": "...", "title": "...", "footer": "..."}
        """
        if isinstance(message, str):
            return message
        elif isinstance(message, dict):
            # If it's a dict, keep it as-is for now (pydantic will handle it)
            return message
        else:
            logger.warning(f"Invalid message type: {type(message)}, converting to empty string")
            return ""
    
    def _validate_and_fix_template(self, template_name: str, template_data: dict) -> dict:
        """Validate and fix common template issues before they cause errors."""
        # Handle both old 'type' and new 'kind' field names
        template_type = template_data.get('kind') or template_data.get('type', 'unknown')
        
        # Ensure we have a message field
        if 'message' not in template_data:
            logger.warning(f"Template '{template_name}' missing message field, creating empty string")
            template_data['message'] = ""
        
        # Normalize message field
        message = template_data.get('message')
        
        # For request-location templates, message should be a string
        if template_type == 'request-location':
            if isinstance(message, dict):
                # Extract meaningful text from dict
                text = message.get('body') or message.get('title') or "Please share your location"
                logger.warning(f"Template '{template_name}' (request-location) has dict message, converting to string: {text}")
                template_data['message'] = text
            elif not message:
                logger.warning(f"Template '{template_name}' (request-location) has empty message, setting default")
                template_data['message'] = "Please share your location"
        
        # For text templates, message should be a string
        elif template_type == 'text':
            if isinstance(message, dict):
                # Extract meaningful text from dict - combine title and body
                title = message.get('title', '')
                body = message.get('body', '')
                
                if title and body:
                    text = f"*{title}*\n\n{body}"
                elif title:
                    text = title
                elif body:
                    text = body
                else:
                    text = "Message content not available"
                
                logger.warning(f"Template '{template_name}' (text) has dict message, converting to string")
                template_data['message'] = text
            elif not message:
                logger.warning(f"Template '{template_name}' (text) has empty message")
                template_data['message'] = "Message content not available"
        
        # For button templates
        elif template_type == 'button':
            if isinstance(message, dict):
                buttons = message.get('buttons', [])
                if not buttons or len(buttons) == 0:
                    # No buttons - convert to text template
                    title = message.get('title', '')
                    body = message.get('body', '')
                    
                    if not body and not title:
                        logger.info(f"Template '{template_name}' appears to be empty placeholder, converting to text")
                        template_data['kind'] = 'text'
                        if 'type' in template_data:
                            template_data['type'] = 'text'
                        template_data['message'] = "No content available"
                    else:
                        logger.info(f"Converting '{template_name}' from 'button' to 'text' template (no buttons)")
                        template_data['kind'] = 'text'
                        if 'type' in template_data:
                            template_data['type'] = 'text'
                        
                        # Combine title and body for text message
                        if title and body:
                            template_data['message'] = f"*{title}*\n\n{body}"
                        elif title:
                            template_data['message'] = title
                        else:
                            template_data['message'] = body
        
        # For list templates
        elif template_type == 'list':
            if isinstance(message, dict):
                sections = message.get('sections', [])
                if not isinstance(sections, list):
                    logger.error(f"Template '{template_name}' has invalid sections (not a list)")
                    message['sections'] = []
                    template_data['message'] = message
                else:
                    # Validate and fix each section structure
                    fixed_sections = []
                    for i, section in enumerate(sections):
                        if isinstance(section, dict):
                            # Ensure rows exist and is a list
                            rows = section.get('rows', [])
                            if not isinstance(rows, list):
                                logger.warning(f"Template '{template_name}' section {i} has invalid rows (not a list)")
                                section['rows'] = []
                            else:
                                # Normalize row structure (WhatsApp uses 'id', pywce might use 'identifier')
                                fixed_rows = []
                                for j, row in enumerate(rows):
                                    if isinstance(row, dict):
                                        # Create a clean row dict
                                        fixed_row = {
                                            'title': row.get('title', f'Item {j}'),
                                            'identifier': row.get('identifier') or row.get('id', str(j)),
                                            'description': row.get('description') or row.get('desc', '')
                                        }
                                        fixed_rows.append(fixed_row)
                                    else:
                                        logger.warning(f"Template '{template_name}' section {i} row {j} is not a dict, skipping")
                                
                                section['rows'] = fixed_rows
                            
                            # Ensure section has a title
                            if 'title' not in section or not section['title']:
                                section['title'] = f'Section {i+1}'
                            
                            fixed_sections.append(section)
                        else:
                            logger.warning(f"Template '{template_name}' section {i} is not a dict, skipping")
                    
                    message['sections'] = fixed_sections
                    template_data['message'] = message
                    
                    logger.info(f"Template '{template_name}' (list) fixed with {len(fixed_sections)} sections")
        
        # Normalize routes structure
        if 'routes' in template_data:
            routes = template_data['routes']
            if isinstance(routes, list):
                # Routes are already in list format (good for pywce)
                pass
            elif isinstance(routes, dict):
                # Routes might be in dict format - keep as-is for now
                pass
            elif routes is None or routes == []:
                template_data['routes'] = []
        else:
            template_data['routes'] = []
        
        return template_data
    
    def _check_for_broken_routes(self, validation_errors: List[dict]) -> None:
        """Check if any valid templates have routes pointing to invalid templates."""
        invalid_template_names = {error['name'] for error in validation_errors}
        broken_routes = []
        
        for template_name, template_data in self._TEMPLATES.items():
            routes = template_data.get('routes', [])
            
            # Handle different route formats
            if isinstance(routes, dict):
                # Routes is a dict mapping patterns to template names
                for pattern, next_template in routes.items():
                    if isinstance(next_template, str) and next_template in invalid_template_names:
                        broken_routes.append({
                            'from_template': template_name,
                            'to_template': next_template,
                            'route_pattern': pattern
                        })
            elif isinstance(routes, list):
                # Routes is a list of route objects
                for route in routes:
                    if isinstance(route, dict):
                        # Try both possible keys for next template
                        next_template = route.get('next_stage') or route.get('connectedTo')
                        if next_template and next_template in invalid_template_names:
                            broken_routes.append({
                                'from_template': template_name,
                                'to_template': next_template,
                                'route': route
                            })
                    elif isinstance(route, str):
                        # Route is just a string (template name)
                        if route in invalid_template_names:
                            broken_routes.append({
                                'from_template': template_name,
                                'to_template': route,
                                'route': route
                            })
        
        if broken_routes:
            logger.error(f"Found {len(broken_routes)} broken routes pointing to invalid templates:")
            for broken in broken_routes:
                logger.error(f"  - '{broken['from_template']}' -> '{broken['to_template']}' (route will fail at runtime)")
            
            logger.error("Fix these by either:")
            logger.error("  1. Fixing the invalid templates in your flow builder")
            logger.error("  2. Updating routes to point to valid templates")
            logger.error("  3. Removing the broken routes")
    
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
            
            # CRITICAL: VisualTranslator.translate() expects a JSON STRING, not a dict!
            ui_translator = VisualTranslator()
            extracted_flow_json = json.dumps(extracted_flow)
            
            # Translate templates
            raw_templates, self._TRIGGERS = ui_translator.translate(extracted_flow_json)
            
            self.START_MENU = ui_translator.START_MENU
            self.REPORT_MENU = ui_translator.REPORT_MENU
            
            logger.info(f"Translation complete: {len(raw_templates)} templates, {len(self._TRIGGERS)} triggers")
            logger.info(f"Initial START_MENU from translator: {self.START_MENU}, REPORT_MENU: {self.REPORT_MENU}")
            
            # WORKAROUND: If START_MENU is incorrectly set, find the template with isStart=true in settings
            if self.START_MENU:
                start_template_data = raw_templates.get(self.START_MENU, {})
                settings = start_template_data.get('settings', {})
                if not settings.get('isStart', False):
                    logger.warning(f"START_MENU '{self.START_MENU}' does not have isStart=true, searching for correct start template")
                    # Find the correct start template
                    for template_name, template_data in raw_templates.items():
                        tmpl_settings = template_data.get('settings', {})
                        if tmpl_settings.get('isStart', False):
                            logger.info(f"Found correct START_MENU: '{template_name}' (was '{self.START_MENU}')")
                            self.START_MENU = template_name
                            break
            else:
                # No START_MENU set, find it from templates
                logger.warning("No START_MENU set by translator, searching templates")
                for template_name, template_data in raw_templates.items():
                    settings = template_data.get('settings', {})
                    if settings.get('isStart', False):
                        logger.info(f"Found START_MENU from settings: '{template_name}'")
                        self.START_MENU = template_name
                        break
            
            # Similar check for REPORT_MENU
            if self.REPORT_MENU:
                report_template_data = raw_templates.get(self.REPORT_MENU, {})
                settings = report_template_data.get('settings', {})
                if not settings.get('isReport', False):
                    logger.warning(f"REPORT_MENU '{self.REPORT_MENU}' does not have isReport=true, searching for correct report template")
                    for template_name, template_data in raw_templates.items():
                        tmpl_settings = template_data.get('settings', {})
                        if tmpl_settings.get('isReport', False):
                            logger.info(f"Found correct REPORT_MENU: '{template_name}' (was '{self.REPORT_MENU}')")
                            self.REPORT_MENU = template_name
                            break
            else:
                # No REPORT_MENU set, try to find it
                for template_name, template_data in raw_templates.items():
                    settings = template_data.get('settings', {})
                    if settings.get('isReport', False):
                        logger.info(f"Found REPORT_MENU from settings: '{template_name}'")
                        self.REPORT_MENU = template_name
                        break
            
            logger.info(f"Final START_MENU: {self.START_MENU}, REPORT_MENU: {self.REPORT_MENU}")
            
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
                    error_msg = str(e)
                    logger.error(f"Validation failed for template '{template_name}': {error_msg}")
                    logger.error(f"Template data: {json.dumps(template_data, indent=2)}")
                    
                    # Try one more fix attempt for specific errors
                    retry = False
                    
                    # Handle "list object has no attribute 'items'" error for list templates
                    if "'list' object has no attribute 'items'" in error_msg:
                        template_type = template_data.get('kind') or template_data.get('type')
                        if template_type == 'list':
                            logger.warning(f"Attempting to fix list template '{template_name}' structure")
                            # Try converting to a simpler structure or skip problematic fields
                            message = template_data.get('message', {})
                            if isinstance(message, dict) and 'sections' in message:
                                # Simplify sections structure
                                sections = message.get('sections', [])
                                simplified_sections = []
                                for section in sections:
                                    if isinstance(section, dict):
                                        simplified_section = {
                                            'title': str(section.get('title', 'Section')),
                                            'rows': []
                                        }
                                        rows = section.get('rows', [])
                                        for row in rows:
                                            if isinstance(row, dict):
                                                simplified_section['rows'].append({
                                                    'title': str(row.get('title', '')),
                                                    'identifier': str(row.get('identifier') or row.get('id', '')),
                                                    'description': str(row.get('description') or row.get('desc', ''))
                                                })
                                        simplified_sections.append(simplified_section)
                                
                                message['sections'] = simplified_sections
                                template_data['message'] = message
                                retry = True
                    
                    if retry:
                        try:
                            validated = template.Template.as_model(template_data)
                            self._TEMPLATES[template_name] = template_data
                            logger.info(f"Successfully fixed template '{template_name}' on retry")
                            continue
                        except Exception as retry_error:
                            logger.error(f"Retry failed for template '{template_name}': {retry_error}")
                    
                    validation_errors.append({
                        'name': template_name,
                        'error': error_msg,
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
                
                # Check for broken routes (routes pointing to invalid templates)
                self._check_for_broken_routes(validation_errors)
                
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

    def _ensure_templates_loaded(self):
        """Ensures self._TEMPLATES is populated, respecting the lazy-load approach."""
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

    def _get_error_template(self, template_name: str, error_message: str) -> Optional[template.EngineTemplate]:
        """
        Create a fallback error template when the requested template fails.
        This prevents the entire flow from breaking due to one bad template.
        """
        logger.warning(f"Creating error fallback template for '{template_name}'")
        
        error_template_data = {
            'kind': 'text',
            'message': f"⚠️ Template Error\n\nThe template '{template_name}' could not be loaded.\n\nError: {error_message}\n\nPlease contact the administrator to fix this template.",
            'routes': [],
            'checkpoint': False
        }
        
        try:
            return template.Template.as_model(error_template_data)
        except Exception as e:
            logger.critical(f"Even error template failed to create: {e}")
            return None

    def get(self, name: str) -> template.EngineTemplate:    
        """Get a template by name with enhanced error handling and fallback."""
        try:
            self._ensure_templates_loaded()
            
            logger.info(f"Attempting to fetch template: '{name}'")
            
            if not self._TEMPLATES:
                logger.error("No templates loaded! _TEMPLATES is empty")
                return self._get_error_template(name, "No templates loaded")
            
            if name is None or name == "None":
                logger.error(f"Template name is None or 'None' string - routing issue detected")
                return self._get_error_template(name, "Invalid template name: None")
            
            template_data = self._TEMPLATES.get(name)
            
            if template_data is None:
                logger.error(f"Template '{name}' not found in _TEMPLATES")
                logger.error(f"Available template IDs: {list(self._TEMPLATES.keys())}")
                return self._get_error_template(name, f"Template not found: {name}")
            
            # Log template data for debugging
            logger.debug(f"Retrieved template '{name}': {json.dumps(template_data, indent=2)}")
            
            # Validate before returning
            try:
                validated_template = template.Template.as_model(template_data)
                logger.info(f"Template '{name}' validated successfully (type: {template_data.get('kind')})")
                return validated_template
            except Exception as validation_error:
                logger.critical(f"Template '{name}' failed runtime validation: {validation_error}")
                logger.critical(f"Template data: {json.dumps(template_data, indent=2)}")
                
                # Try to fix and re-validate
                fixed_template = self._validate_and_fix_template(name, template_data)
                try:
                    validated = template.Template.as_model(fixed_template)
                    # Update stored template with fixed version
                    self._TEMPLATES[name] = fixed_template
                    logger.info(f"Template '{name}' fixed and validated on retry")
                    return validated
                except Exception as second_error:
                    logger.critical(f"Template '{name}' still invalid after fix attempt: {second_error}")
                    return self._get_error_template(name, f"Validation failed: {second_error}")
                
        except Exception as e:
            frappe.log_error(title="Get Template Error", message=f"Template: {name}, Error: {str(e)}")
            logger.critical(f"Error fetching template '{name}': {str(e)}", exc_info=True)
            return self._get_error_template(name, str(e))

    def triggers(self) -> List[template.EngineRoute]:
        return self._TRIGGERS
    
    def __repr__(self):
        return (f"FrappeStorageManager(start_menu={self.START_MENU}, "
                f"report_menu={self.REPORT_MENU}, "
                f"templates_count={len(self._TEMPLATES)}, "
                f"triggers_count={len(self._TRIGGERS)})")


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