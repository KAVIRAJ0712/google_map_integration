"""Endpoints for the tracker page. The agent is always the logged-in user: no endpoint accepts a
user, employee or team from the browser."""

import frappe
from frappe import _

from google_map_integration.tracking import resolutions, sessions


@frappe.whitelist(methods=["GET"])
def get_tracking_status() -> dict:
	"""The tracker page's state, including recent ticket resolutions that need a fresh location."""
	user = frappe.session.user
	return sessions.get_status(user) | {"capture_requests": resolutions.get_capture_requests(user)}


@frappe.whitelist(methods=["POST"])
def check_in(log_type: str, point: dict | str | None = None) -> dict:
	"""Check in ("IN") or out ("OUT") through HRMS from the tracker page. `point` is shaped like a
	ping: the location read when the agent tapped the button, or empty when none could be read."""
	sessions.check_in(frappe.session.user, log_type, parse(point) if point else None)
	return get_tracking_status()


@frappe.whitelist(methods=["POST"])
def start_tracking() -> dict:
	"""Start tracking in an open window without a session. Check-ins start tracking on their own;
	the tracker page calls this for the cases they do not cover."""
	day = sessions.start_session(frappe.session.user)
	return get_tracking_status() | {"session_id": day.session_id}


@frappe.whitelist(methods=["POST"])
def submit_locations(session_id: str, points: list[dict] | str) -> dict:
	"""`points`: [{client_event_id, latitude, longitude, accuracy, recorded_at}], where recorded_at
	is milliseconds since 1970 and client_event_id is unique per reading."""
	points = parse(points)
	if not isinstance(points, list):
		frappe.throw(_("points must be a list."))
	result = sessions.record_points(frappe.session.user, session_id, points)
	if result["session_active"]:
		result["capture_requests"] = resolutions.get_capture_requests(frappe.session.user)
	return result


@frappe.whitelist(methods=["POST"])
def report_location_blocked(session_id: str) -> dict:
	"""The browser blocked location, so this device cannot send readings. Tracking stays on."""
	return sessions.report_location_blocked(frappe.session.user, session_id)


@frappe.whitelist(methods=["POST"])
def take_over_tracking() -> dict:
	"""Send the agent's readings from this device instead of their other one."""
	sessions.take_over(frappe.session.user)
	return get_tracking_status()


@frappe.whitelist(methods=["POST"])
def attach_resolution_location(event: int, point: dict | str) -> dict:
	"""A location read just after the agent resolved a ticket; `point` is shaped like a ping."""
	return resolutions.attach_fresh_fix(frappe.session.user, event, parse(point))


def parse(value):
	return frappe.parse_json(value) if isinstance(value, str) else value
