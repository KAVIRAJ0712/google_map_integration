import frappe

from google_map_integration.tracking.config import get_client_config, get_effective_config


@frappe.whitelist(methods=["GET"])
def get_maps_config() -> dict:
	"""Map and tracking settings for the logged-in user. The browser key is only included when
	the user may open the map."""
	return get_client_config()


def can_open_app() -> bool:
	"""Whether the Agent Tracking app shows in the apps menu, including Helpdesk's sidebar."""
	if frappe.session.user == "Guest":
		return False
	effective = get_effective_config()
	return effective.map.enabled or effective.tracking.enabled
