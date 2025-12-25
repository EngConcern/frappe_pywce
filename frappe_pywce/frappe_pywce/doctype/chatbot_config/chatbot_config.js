// Copyright (c) 2025, donnc and contributors
// For license information, please see license.txt

frappe.ui.form.on("ChatBot Config", {
  setup: function (frm) {
    frm.trigger("setup_help");
  },

  refresh: function (frm) {
    // Original buttons
    frm.add_custom_button(__("View Webhook Url"), function () {
      frm.call({
        method: "frappe_pywce.webhook.get_webhook",
        callback: function (r) {
          frappe.msgprint(r.message);
        },
      });
    });

    frm.add_custom_button(__("Clear Cache"), function () {
      frm.call({
        method: "frappe_pywce.webhook.clear_session",
        callback: function (r) {
          frappe.show_alert("Cache Cleared");
        },
      });
    });

    // Flow Management buttons
   // frm.add_custom_button(__("Open Studio"), function () {
   //   window.open(`/bot/studio`, "_blank");
   // });

    frm.add_custom_button(__("Manage Flows"), function () {
      frappe.set_route("List", "Bot Flow");
    });

    frm.add_custom_button(__("Create New Flow"), function () {
      frappe.new_doc("Bot Flow");
    });

    // Load flows in a dropdown menu
    frm.add_custom_button(__("Open Flow"), function () {
      // Show dialog with flow selection
      frappe.call({
        method: "frappe.client.get_list",
        args: {
          doctype: "Bot Flow",
          fields: ["name", "flow_name", "description", "is_active"],
          filters: { is_active: 1 },
          order_by: "modified desc",
          limit_page_length: 50,
        },
        callback: function (r) {
          if (r.message && r.message.length > 0) {
            const flows = r.message;
            
            // Create dialog with flow list
            const dialog = new frappe.ui.Dialog({
              title: __("Select Flow to Open"),
              fields: [
                {
                  fieldname: "flow",
                  fieldtype: "Select",
                  label: __("Flow"),
                  options: flows.map((f) => f.name),
                  reqd: 1,
                },
                {
                  fieldname: "flow_info",
                  fieldtype: "HTML",
                  label: __("Flow Information"),
                },
              ],
              primary_action_label: __("Open in Studio"),
              primary_action: function (values) {
                const flowName = encodeURIComponent(values.flow);
                window.open(`/bot/studio?flow=${flowName}`, "_blank");
                dialog.hide();
              },
              secondary_action_label: __("Edit Flow"),
              secondary_action: function (values) {
                frappe.set_route("Form", "Bot Flow", values.flow);
                dialog.hide();
              },
            });

            // Update flow info on selection
            dialog.fields_dict.flow.df.onchange = function () {
              const selectedFlow = flows.find(
                (f) => f.name === dialog.get_value("flow")
              );
              if (selectedFlow) {
                const html = `
                  <div style="padding: 10px; background: #f5f5f5; border-radius: 4px;">
                    <p><strong>Name:</strong> ${selectedFlow.flow_name}</p>
                    <p><strong>Description:</strong> ${selectedFlow.description || "N/A"}</p>
                    <p><strong>Status:</strong> <span style="color: green;">Active</span></p>
                  </div>
                `;
                dialog.fields_dict.flow_info.$wrapper.html(html);
              }
            };

            dialog.show();

            // Show first flow info by default
            if (flows.length > 0) {
              dialog.set_value("flow", flows[0].name);
              dialog.fields_dict.flow.df.onchange();
            }
          } else {
            frappe.msgprint({
              title: __("No Flows Found"),
              message: __("No active flows available. Create a new flow to get started."),
              indicator: "yellow",
            });
          }
        },
      });
    });
  },

  btn_launch_emulator: function (frm) {
    frappe.warn(
      "Launch local Bot emulator",
      "Ensure you started the dev server with `yarn dev` in the app folder",
      () => {
        window.open("/bot/emulator", "_blank");
      },
      "Continue",
      true
    );
  },

  setup_help(frm) {
    frm.get_field("help").html(`
<p>A big thank you for checking out my app! </p>

<h4>Flow Management</h4>
<p>You can now manage multiple bot flows using the Bot Flow doctype. Each flow is stored separately and can be:</p>
<ul>
  <li>Created and edited independently</li>
  <li>Opened in Bot Studio for visual editing</li>
  <li>Activated or deactivated as needed</li>
  <li>Exported and imported for backup/sharing</li>
  <li>Duplicated to create variations</li>
</ul>

<p>Use the buttons above to:</p>
<ul>
  <li><strong>Manage Flows:</strong> View all bot flows in a list</li>
  <li><strong>Create New Flow:</strong> Start building a new bot flow</li>
  <li><strong>Open Flow:</strong> Select and open an existing flow in Bot Studio</li>
</ul>

<hr>

<h4>Hooks</h4>
<p>You are already familiar with this. This uses the same approach as your custom server side business logic. The hook value must be a full dotted path to the server script</p>
<p>Hooks enables you to "hook" / "attach" business logic to your template. For example, if you want to send an email, create a doctype, fetch records. You create your usual server script and reference that hook on the template</p>

Always remember, pywce supports different hook types as defined by their name, hook appropriately.

</br>
Example: Suppose your custom app name is my_app with a structure as below:
</br>
<pre><code>
my_app/
└── my_app/
    └── hook/
        └── tasks.py
</code></pre>
</br>
With a hook as below:

<pre><code>
# tasks.py
import frappe
from pywce import HookArg

def create_a_task(arg: HookArg) -> HookArg:
    # take task name from provided user input
    task_name = arg.user_input

    doc = frappe.get_doc({
            "doctype": "Task",
            "task_name": task_name
          })
    doc.insert()
    
    return arg
</code></pre>

Your hook will be like: <i>my_app.my_app.hook.tasks.create_a_task</i>

<hr>

<h4>Authentication</h4>
<p>The app comes with default hook and function to handle authentication and resuming user session on each webhook</p>

<p> You can choose to use login via a link, where user will be directed to your frappe/erpnext instance's login page and be redirected back to WhatsApp </p>
<p> or if using WhatsApp Flows, can use a helper method to perform log in</p>

frappe_pywce.frappe_pywce.hook.auth.generate_login_link
`);
  },
});