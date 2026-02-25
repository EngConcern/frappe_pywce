// Copyright (c) 2026, donnc and contributors
// For license information, please see license.txt

frappe.ui.form.on('Chat Bot', {
    refresh: function(frm) {
        // Add custom buttons
        if (!frm.is_new()) {
            // Open Flow Builder button
            frm.add_custom_button(__('Open Flow Builder'), function() {
                frappe.set_route('bot-studio', frm.doc.bot_slug);
            }, __('Actions'));
            
            // Launch Emulator button
            frm.add_custom_button(__('Launch Emulator'), function() {
                window.open(`/bot/emulator?bot=${frm.doc.bot_slug}`, '_blank');
            }, __('Actions'));
            
            // Duplicate Bot button
            frm.add_custom_button(__('Duplicate Bot'), function() {
                frappe.prompt({
                    fieldname: 'new_name',
                    label: 'New Bot Name',
                    fieldtype: 'Data',
                    reqd: 1
                }, function(values) {
                    frappe.call({
                        method: 'frappe_pywce.frappe_pywce.api.bot_api.duplicate_bot',
                        args: {
                            bot_slug: frm.doc.bot_slug,
                            new_name: values.new_name
                        },
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint(__('Bot duplicated successfully'));
                                frappe.set_route('Form', 'Chat Bot', r.message.name);
                            }
                        }
                    });
                }, __('Duplicate Bot'), __('Create'));
            }, __('Actions'));
            
            // Export Bot button
            frm.add_custom_button(__('Export Bot'), function() {
                frappe.call({
                    method: 'frappe_pywce.frappe_pywce.api.bot_api.export_bot',
                    args: {
                        bot_slug: frm.doc.bot_slug
                    },
                    callback: function(r) {
                        if (r.message) {
                            const dataStr = JSON.stringify(r.message, null, 2);
                            const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
                            const exportFileDefaultName = `${frm.doc.bot_slug}_export.json`;
                            
                            const linkElement = document.createElement('a');
                            linkElement.setAttribute('href', dataUri);
                            linkElement.setAttribute('download', exportFileDefaultName);
                            linkElement.click();
                        }
                    }
                });
            }, __('Actions'));
            
            // View Active Sessions
            frm.add_custom_button(__('View Sessions'), function() {
                frappe.set_route('List', 'User Bot Session', {
                    current_bot: frm.doc.name,
                    is_active: 1
                });
            }, __('Actions'));
            
            // Stats section
            frappe.call({
                method: 'frappe_pywce.frappe_pywce.api.bot_api.get_bot_stats',
                args: {
                    bot_slug: frm.doc.bot_slug
                },
                callback: function(r) {
                    if (r.message) {
                        frm.dashboard.add_indicator(
                            __('Templates: {0}', [r.message.total_templates]),
                            'blue'
                        );
                        frm.dashboard.add_indicator(
                            __('Active Sessions: {0}', [r.message.active_sessions]),
                            'green'
                        );
                    }
                }
            });
        }
    },
    
    bot_name: function(frm) {
        // Auto-generate slug preview
        if (frm.doc.bot_name && !frm.doc.bot_slug) {
            let slug = frm.doc.bot_name.toLowerCase()
                .replace(/[^a-z0-9\s-]/g, '')
                .replace(/[\s_-]+/g, '-')
                .trim();
            frm.set_value('bot_slug', slug);
        }
    },
    
    is_default: function(frm) {
        if (frm.doc.is_default) {
            frappe.show_alert({
                message: __('This bot will become the default. Other bots will be un-defaulted.'),
                indicator: 'blue'
            });
        }
    }
});
