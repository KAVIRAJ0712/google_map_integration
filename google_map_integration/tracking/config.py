"""What the map and location tracking allow for a user: the site-wide switch in Google Maps
Settings combined with the switches on the user's HD Teams."""

import frappe
from frappe import _
from frappe.utils import cint, flt
from frappe.utils.password import get_decrypted_password

from google_map_integration.integrations import helpdesk, hrms
from google_map_integration.tracking.permissions import can_view_all_locations

SETTINGS = "Google Maps Settings"
DEFAULT_INTERVAL = 60
MIN_INTERVAL = 15
MAX_INTERVAL = 3600
TEAM_SETTINGS_ROLES = frozenset(("System Manager", "Agent Manager"))


def reason_message(reason: str | None) -> str | None:
	"""Why a feature is unavailable, in words the agent can act on."""
	messages = {
		"integration_disabled": _("Google Maps is turned off in Google Maps Settings."),
		"not_an_agent": _("Only active Helpdesk agents can use the map and location tracking."),
		"no_team_with_map": _("The map is not turned on for any team you can view."),
		"no_team_with_tracking": _(
			"Location tracking is not turned on for any of your teams. A team needs both the map and location tracking turned on."
		),
		"no_employee": _("Location tracking needs an active Employee linked to your user."),
	}
	return messages.get(reason)


def get_settings():
	return frappe.get_cached_doc(SETTINGS)


def get_api_key() -> str | None:
	return get_decrypted_password(SETTINGS, SETTINGS, "google_maps_api_key", raise_exception=False)


def get_effective_config(user: str | None = None) -> frappe._dict:
	"""Map and tracking access for `user`, with the reason when a feature is unavailable."""
	user = user or frappe.session.user
	settings = get_settings()
	view_all = can_view_all_locations(user)
	is_agent = helpdesk.is_active_agent(user)
	own_teams = helpdesk.get_teams(user) if is_agent else []
	visible_teams = helpdesk.get_teams() if view_all else own_teams
	map_teams = [team.name for team in visible_teams if team.map_enabled]
	# tracking needs the map on the same team, so every tracked day can be seen on the map
	tracking_teams = [team for team in own_teams if team.map_enabled and team.tracking_enabled]
	employee = hrms.get_active_employee(user) if tracking_teams else None

	if not settings.enabled:
		map_reason = tracking_reason = "integration_disabled"
	else:
		map_reason = get_map_reason(is_agent or view_all, map_teams)
		tracking_reason = get_tracking_reason(is_agent, tracking_teams, employee)

	return frappe._dict(
		integration_enabled=bool(settings.enabled),
		can_view_all=view_all,
		map=frappe._dict(enabled=map_reason is None, reason=map_reason, teams=map_teams),
		tracking=frappe._dict(
			enabled=tracking_reason is None,
			reason=tracking_reason,
			teams=[team.name for team in tracking_teams],
			employee=employee,
			interval=get_tracking_interval(settings, tracking_teams),
		),
	)


def get_map_reason(may_view: bool, map_teams: list) -> str | None:
	if not may_view:
		return "not_an_agent"
	if not map_teams:
		return "no_team_with_map"
	return None


def get_tracking_reason(is_agent: bool, tracking_teams: list, employee: str | None) -> str | None:
	if not is_agent:
		return "not_an_agent"
	if not tracking_teams:
		return "no_team_with_tracking"
	if not employee:
		return "no_employee"
	return None


def get_tracking_interval(settings, teams: list) -> int:
	"""Seconds between pings: the shortest interval among the teams, where a team's 0 means the
	site default."""
	default = cint(settings.location_tracking_interval) or DEFAULT_INTERVAL
	interval = min((cint(team.interval) or default for team in teams), default=default)
	return max(MIN_INTERVAL, min(MAX_INTERVAL, interval))


def get_map_options(settings) -> dict:
	"""Everything the browser needs to draw a map, including the browser key."""
	return {
		"api_key": get_api_key(),
		"map_id": settings.map_id,
		"map_type": settings.map_type or "roadmap",
		"show_estimated_road_route": bool(settings.enable_estimated_road_route),
	}


def get_client_config(user: str | None = None) -> dict:
	"""The effective configuration as sent to the browser. Map options, including the key, are only
	included for users who may open the map."""
	effective = get_effective_config(user)
	settings = get_settings()
	map_access, tracking = effective.map, effective.tracking

	result = {
		"integration_enabled": effective.integration_enabled,
		"can_view_all": effective.can_view_all,
		"map": {
			"enabled": map_access.enabled,
			"reason": map_access.reason,
			"message": reason_message(map_access.reason),
			"teams": map_access.teams,
		},
		"tracking": {
			"enabled": tracking.enabled,
			"reason": tracking.reason,
			"message": reason_message(tracking.reason),
			"teams": tracking.teams,
		},
	}
	if map_access.enabled:
		result["map"].update(get_map_options(settings))
	if tracking.enabled:
		result["tracking"].update(
			{
				"employee": tracking.employee,
				"interval_seconds": tracking.interval,
				"max_accuracy_meters": flt(settings.max_accuracy_meters),
				"require_hrms_checkin": bool(settings.require_hrms_checkin),
				"notice": settings.tracking_notice,
				"notice_version": cint(settings.notice_version),
			}
		)
	return result


def can_manage_team_settings(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(TEAM_SETTINGS_ROLES.intersection(frappe.get_roles(user)))


def validate_team_settings(doc, method: str | None = None) -> None:
	"""HD Team validate hook. Helpdesk lets every agent edit teams, so only managers may change
	the map and tracking switches."""
	if not any(value_changed(doc, field) for field in helpdesk.TEAM_SETTINGS_FIELDS):
		return
	if not can_manage_team_settings():
		frappe.throw(
			_("Only an Agent Manager can change a team's Google Maps settings."), frappe.PermissionError
		)
	interval = cint(doc.get(helpdesk.TEAM_INTERVAL_FIELD))
	if interval and not MIN_INTERVAL <= interval <= MAX_INTERVAL:
		frappe.throw(
			_("Location Tracking Interval must be between {0} and {1} seconds, or 0 for the default.").format(
				MIN_INTERVAL, MAX_INTERVAL
			)
		)


def value_changed(doc, fieldname: str) -> bool:
	"""Whether a numeric field changed in this save. New documents compare against 0."""
	previous = doc.get_doc_before_save()
	return cint(doc.get(fieldname)) != cint(previous.get(fieldname) if previous else 0)
