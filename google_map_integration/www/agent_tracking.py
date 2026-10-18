import frappe
from frappe.utils import get_system_timezone

no_cache = 1


def get_context(context):
	"""The page for agent-tracking.html, which the frontend build writes."""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/agent-tracking"
		raise frappe.Redirect
	context.boot = frappe._dict(
		csrf_token=frappe.sessions.get_csrf_token(),
		session_user=frappe.session.user,
		site_name=frappe.local.site,
		timezone=get_system_timezone(),
		has_hrms="hrms" in frappe.get_installed_apps(),
	)
	return context
