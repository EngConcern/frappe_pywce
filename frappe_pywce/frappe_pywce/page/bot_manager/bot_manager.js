// Copyright (c) 2026, donnc and contributors
// For license information, please see license.txt

frappe.pages['bot-manager'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Bot Manager',
        single_column: true
    });
    
    new BotManager(page);
};

class BotManager {
    constructor(page) {
        this.page = page;
        this.bots = [];
        
        this.setup_page();
        this.load_bots();
    }
    
    setup_page() {
        // Add primary action
        this.page.set_primary_action(__('Create New Bot'), () => {
            this.create_bot_dialog();
        }, 'octicon octicon-plus');
        
        // Add secondary actions
        this.page.add_menu_item(__('Import Bot'), () => {
            this.import_bot_dialog();
        });
        
        this.page.add_menu_item(__('Refresh'), () => {
            this.load_bots();
        });
        
        // Setup page content
        this.$container = $('<div class="bot-manager-wrapper"></div>').appendTo(this.page.body);
        
        this.$container.html(`
            <div class="bot-manager-content">
                <div class="bot-list-section">
                    <div class="section-header">
                        <h4>Your Chatbots</h4>
                        <div class="bot-filters">
                            <input type="text" class="form-control input-sm bot-search" placeholder="Search bots...">
                            <label class="checkbox-inline">
                                <input type="checkbox" class="show-inactive"> Show Inactive
                            </label>
                        </div>
                    </div>
                    <div class="bot-list-container">
                        <div class="bot-list"></div>
                    </div>
                </div>
                <div class="bot-stats-section">
                    <h4>Statistics</h4>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-value" id="stat-total-bots">0</div>
                            <div class="stat-label">Total Bots</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value" id="stat-active-bots">0</div>
                            <div class="stat-label">Active Bots</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value" id="stat-active-sessions">0</div>
                            <div class="stat-label">Active Sessions</div>
                        </div>
                    </div>
                </div>
            </div>
        `);
        
        // Bind events
        this.$container.find('.bot-search').on('input', () => this.filter_bots());
        this.$container.find('.show-inactive').on('change', () => this.load_bots());
    }
    
    load_bots() {
        const include_inactive = this.$container.find('.show-inactive').is(':checked');
        
        this.$container.find('.bot-list').html(`
            <div class="text-center text-muted p-4">
                <i class="fa fa-spinner fa-spin"></i> Loading bots...
            </div>
        `);
        
        frappe.call({
            method: 'frappe_pywce.frappe_pywce.api.bot_api.get_bots',
            args: { include_inactive: include_inactive },
            callback: (r) => {
                this.bots = r.message || [];
                this.render_bots();
                this.update_stats();
            }
        });
    }
    
    render_bots() {
        const $list = this.$container.find('.bot-list');
        
        if (this.bots.length === 0) {
            $list.html(`
                <div class="empty-state text-center p-5">
                    <i class="fa fa-robot fa-3x text-muted mb-3"></i>
                    <h5>No Bots Found</h5>
                    <p class="text-muted">Create your first chatbot to get started.</p>
                    <button class="btn btn-primary btn-create-first">
                        <i class="fa fa-plus"></i> Create Bot
                    </button>
                </div>
            `);
            $list.find('.btn-create-first').on('click', () => this.create_bot_dialog());
            return;
        }
        
        let html = '<div class="bot-cards">';
        
        for (const bot of this.bots) {
            const statusClass = bot.is_active ? 'active' : 'inactive';
            const defaultBadge = bot.is_default ? '<span class="badge badge-primary">Default</span>' : '';
            
            html += `
                <div class="bot-card ${statusClass}" data-bot="${bot.bot_slug}">
                    <div class="bot-card-header">
                        <h5 class="bot-name">${bot.bot_name}</h5>
                        <div class="bot-badges">
                            ${defaultBadge}
                            <span class="badge badge-${bot.is_active ? 'success' : 'secondary'}">
                                ${bot.is_active ? 'Active' : 'Inactive'}
                            </span>
                        </div>
                    </div>
                    <div class="bot-card-body">
                        <p class="bot-description">${bot.description || 'No description'}</p>
                        <div class="bot-meta">
                            <span><i class="fa fa-puzzle-piece"></i> ${bot.total_templates || 0} templates</span>
                            <span><i class="fa fa-code"></i> ${bot.bot_slug}</span>
                        </div>
                    </div>
                    <div class="bot-card-actions">
                        <button class="btn btn-sm btn-primary btn-open-builder" title="Open Flow Builder">
                            <i class="fa fa-project-diagram"></i> Builder
                        </button>
                        <button class="btn btn-sm btn-default btn-edit-bot" title="Edit Bot">
                            <i class="fa fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-default btn-emulator" title="Launch Emulator">
                            <i class="fa fa-mobile"></i>
                        </button>
                        <div class="btn-group">
                            <button class="btn btn-sm btn-default dropdown-toggle" data-toggle="dropdown">
                                <i class="fa fa-ellipsis-v"></i>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-right">
                                <li><a class="btn-duplicate"><i class="fa fa-copy"></i> Duplicate</a></li>
                                <li><a class="btn-export"><i class="fa fa-download"></i> Export</a></li>
                                <li><a class="btn-sessions"><i class="fa fa-users"></i> View Sessions</a></li>
                                <li class="divider"></li>
                                <li><a class="btn-toggle-active">
                                    <i class="fa fa-${bot.is_active ? 'pause' : 'play'}"></i> 
                                    ${bot.is_active ? 'Deactivate' : 'Activate'}
                                </a></li>
                                <li><a class="btn-delete text-danger"><i class="fa fa-trash"></i> Delete</a></li>
                            </ul>
                        </div>
                    </div>
                </div>
            `;
        }
        
        html += '</div>';
        $list.html(html);
        
        // Bind card events
        this.bind_bot_card_events();
    }
    
    bind_bot_card_events() {
        const self = this;
        
        this.$container.find('.bot-card').each(function() {
            const $card = $(this);
            const bot_slug = $card.data('bot');
            
            $card.find('.btn-open-builder').on('click', () => {
                frappe.set_route('bot-studio', bot_slug);
            });
            
            $card.find('.btn-edit-bot').on('click', () => {
                frappe.set_route('Form', 'Chat Bot', bot_slug);
            });
            
            $card.find('.btn-emulator').on('click', () => {
                window.open(`/bot/emulator?bot=${bot_slug}`, '_blank');
            });
            
            $card.find('.btn-duplicate').on('click', () => {
                self.duplicate_bot_dialog(bot_slug);
            });
            
            $card.find('.btn-export').on('click', () => {
                self.export_bot(bot_slug);
            });
            
            $card.find('.btn-sessions').on('click', () => {
                frappe.set_route('List', 'User Bot Session', {
                    current_bot: bot_slug,
                    is_active: 1
                });
            });
            
            $card.find('.btn-toggle-active').on('click', () => {
                self.toggle_bot_active(bot_slug);
            });
            
            $card.find('.btn-delete').on('click', () => {
                self.delete_bot(bot_slug);
            });
        });
    }
    
    filter_bots() {
        const search = this.$container.find('.bot-search').val().toLowerCase();
        
        this.$container.find('.bot-card').each(function() {
            const $card = $(this);
            const name = $card.find('.bot-name').text().toLowerCase();
            const slug = $card.data('bot').toLowerCase();
            
            if (name.includes(search) || slug.includes(search)) {
                $card.show();
            } else {
                $card.hide();
            }
        });
    }
    
    update_stats() {
        const total = this.bots.length;
        const active = this.bots.filter(b => b.is_active).length;
        
        this.$container.find('#stat-total-bots').text(total);
        this.$container.find('#stat-active-bots').text(active);
        
        // Get active sessions count
        frappe.call({
            method: 'frappe_pywce.frappe_pywce.api.bot_api.get_active_sessions',
            callback: (r) => {
                const sessions = r.message || [];
                this.$container.find('#stat-active-sessions').text(sessions.length);
            }
        });
    }
    
    create_bot_dialog() {
        const dialog = new frappe.ui.Dialog({
            title: __('Create New Bot'),
            fields: [
                {
                    fieldname: 'bot_name',
                    label: __('Bot Name'),
                    fieldtype: 'Data',
                    reqd: 1
                },
                {
                    fieldname: 'description',
                    label: __('Description'),
                    fieldtype: 'Small Text'
                },
                {
                    fieldname: 'trigger_patterns',
                    label: __('Trigger Patterns'),
                    fieldtype: 'Code',
                    options: 'JSON',
                    default: '["(?i)^(hi|hello|start)$"]',
                    description: __('JSON array of regex patterns to activate this bot')
                },
                {
                    fieldname: 'is_default',
                    label: __('Set as Default Bot'),
                    fieldtype: 'Check',
                    description: __('Default bot is used when no trigger matches')
                }
            ],
            primary_action_label: __('Create'),
            primary_action: (values) => {
                frappe.call({
                    method: 'frappe_pywce.frappe_pywce.api.bot_api.create_bot',
                    args: {
                        bot_name: values.bot_name,
                        description: values.description || '',
                        trigger_patterns: values.trigger_patterns || '[]',
                        is_default: values.is_default || false
                    },
                    callback: (r) => {
                        if (r.message) {
                            dialog.hide();
                            frappe.show_alert({
                                message: __('Bot created successfully'),
                                indicator: 'green'
                            });
                            this.load_bots();
                            
                            // Ask if user wants to open builder
                            frappe.confirm(
                                __('Would you like to open the Flow Builder for this bot?'),
                                () => {
                                    frappe.set_route('bot-studio', r.message.bot_slug);
                                }
                            );
                        }
                    }
                });
            }
        });
        dialog.show();
    }
    
    duplicate_bot_dialog(bot_slug) {
        frappe.prompt({
            fieldname: 'new_name',
            label: __('New Bot Name'),
            fieldtype: 'Data',
            reqd: 1
        }, (values) => {
            frappe.call({
                method: 'frappe_pywce.frappe_pywce.api.bot_api.duplicate_bot',
                args: {
                    bot_slug: bot_slug,
                    new_name: values.new_name
                },
                callback: (r) => {
                    if (r.message) {
                        frappe.show_alert({
                            message: __('Bot duplicated successfully'),
                            indicator: 'green'
                        });
                        this.load_bots();
                    }
                }
            });
        }, __('Duplicate Bot'), __('Create'));
    }
    
    import_bot_dialog() {
        const dialog = new frappe.ui.Dialog({
            title: __('Import Bot'),
            fields: [
                {
                    fieldname: 'bot_name',
                    label: __('Bot Name'),
                    fieldtype: 'Data',
                    reqd: 1
                },
                {
                    fieldname: 'config_json',
                    label: __('Configuration JSON'),
                    fieldtype: 'Code',
                    options: 'JSON',
                    reqd: 1
                }
            ],
            primary_action_label: __('Import'),
            primary_action: (values) => {
                frappe.call({
                    method: 'frappe_pywce.frappe_pywce.api.bot_api.import_bot',
                    args: {
                        bot_name: values.bot_name,
                        config_json: values.config_json
                    },
                    callback: (r) => {
                        if (r.message) {
                            dialog.hide();
                            frappe.show_alert({
                                message: __('Bot imported successfully'),
                                indicator: 'green'
                            });
                            this.load_bots();
                        }
                    }
                });
            }
        });
        dialog.show();
    }
    
    export_bot(bot_slug) {
        frappe.call({
            method: 'frappe_pywce.frappe_pywce.api.bot_api.export_bot',
            args: { bot_slug: bot_slug },
            callback: (r) => {
                if (r.message) {
                    const dataStr = JSON.stringify(r.message, null, 2);
                    const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
                    const fileName = `${bot_slug}_export.json`;
                    
                    const link = document.createElement('a');
                    link.setAttribute('href', dataUri);
                    link.setAttribute('download', fileName);
                    link.click();
                }
            }
        });
    }
    
    toggle_bot_active(bot_slug) {
        const bot = this.bots.find(b => b.bot_slug === bot_slug);
        if (!bot) return;
        
        const new_status = !bot.is_active;
        
        frappe.call({
            method: 'frappe_pywce.frappe_pywce.api.bot_api.update_bot',
            args: {
                bot_slug: bot_slug,
                is_active: new_status
            },
            callback: (r) => {
                if (r.message) {
                    frappe.show_alert({
                        message: __('Bot {0}', [new_status ? 'activated' : 'deactivated']),
                        indicator: new_status ? 'green' : 'orange'
                    });
                    this.load_bots();
                }
            }
        });
    }
    
    delete_bot(bot_slug) {
        frappe.confirm(
            __('Are you sure you want to delete this bot? This will also delete all templates and routes.'),
            () => {
                frappe.call({
                    method: 'frappe_pywce.frappe_pywce.api.bot_api.delete_bot',
                    args: { bot_slug: bot_slug },
                    callback: (r) => {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Bot deleted successfully'),
                                indicator: 'green'
                            });
                            this.load_bots();
                        }
                    }
                });
            }
        );
    }
}
