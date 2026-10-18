"""Where a tracked agent was when they resolved a ticket.

The server only knows the agent's last ping, so the event first gets that location, labelled
Last Known with its age, or Unavailable. If the agent's tracker page is open it reads a fresh
location and attaches it within a few minutes; the event then keeps both times, so the gap between
resolving and reading the location stays visible."""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, now_datetime

from google_map_integration.tracking import config, sessions
from google_map_integration.utils import from_epoch_ms, to_epoch_ms

LOG = "Agent Location Log"
RESOLVED = "Ticket Resolved"
FRESH_FIX_WINDOW = timedelta(minutes=5)


def log_resolution(ticket, user: str) -> str | None:
	"""Log a tracked agent's ticket resolution. Customers, the auto-close job and agents whose
	teams do not track get no event."""
	tracking = config.get_effective_config(user).tracking
	if not tracking.enabled:
		return None
	resolved_at = get_datetime(ticket.resolution_date or now_datetime())
	event_id = f"ticket:{ticket.name}:{resolved_at.isoformat()}"
	if frappe.db.exists(LOG, {"agent": user, "client_event_id": event_id}):
		return None

	day = sessions.get_open_day(user)
	fix = last_known_fix(day.name, resolved_at) if day else None
	location = (
		{
			"location_status": "Last Known",
			"recorded_at": fix.recorded_at,
			"latitude": fix.latitude,
			"longitude": fix.longitude,
			"accuracy_meters": fix.accuracy_meters,
			"source": "Browser GPS",
		}
		if fix
		else {"location_status": "Unavailable", "recorded_at": resolved_at}
	)
	event = frappe.get_doc(
		{
			"doctype": LOG,
			"event_type": RESOLVED,
			"agent": user,
			"employee": tracking.employee,
			"daily_tracking": day.name if day else None,
			"session_id": day.session_id if day else None,
			"hd_team": day.hd_team if day else tracking.teams[0],
			"ticket": ticket.name,
			"ticket_resolved_at": resolved_at,
			"client_event_id": event_id,
			**location,
		}
	).insert(ignore_permissions=True)
	return event.name


def last_known_fix(day: str, resolved_at):
	"""The latest valid ping of the day, if it is recent enough to stand for the resolution."""
	max_age = timedelta(minutes=cint(config.get_settings().last_known_max_age_minutes))
	return frappe.db.get_value(
		LOG,
		{
			"daily_tracking": day,
			"event_type": "Location Ping",
			"location_status": "GPS",
			"validation_status": "Valid",
			"recorded_at": ["between", [resolved_at - max_age, resolved_at]],
		},
		["recorded_at", "latitude", "longitude", "accuracy_meters"],
		as_dict=True,
		order_by="recorded_at desc",
	)


def get_capture_requests(user: str) -> list[dict]:
	"""Resolutions from the last few minutes still waiting for a fresh location."""
	return [
		{"event": row.name, "ticket": row.ticket, "resolved_at": to_epoch_ms(row.ticket_resolved_at)}
		for row in frappe.get_all(
			LOG,
			filters={
				"agent": user,
				"event_type": RESOLVED,
				"location_status": ["!=", "GPS"],
				"ticket_resolved_at": [
					">=",
					add_to_date(now_datetime(), seconds=-FRESH_FIX_WINDOW.total_seconds()),
				],
			},
			fields=["name", "ticket", "ticket_resolved_at"],
		)
	]


def attach_fresh_fix(user: str, event: int, point: dict) -> dict:
	"""Attach a location the tracker page read just after the agent resolved a ticket."""
	log = frappe.get_doc(LOG, event)
	if log.agent != user or log.event_type != RESOLVED:
		frappe.throw(_("This is not one of your ticket resolutions."), frappe.PermissionError)
	if log.location_status == "GPS":
		return {"attached": False, "reason": _("A location is already attached.")}

	resolved_at = get_datetime(log.ticket_resolved_at)
	if now_datetime() - resolved_at > FRESH_FIX_WINDOW:
		return {
			"attached": False,
			"reason": _("Too late: locations can be attached for 5 minutes after resolving."),
		}
	read_at = from_epoch_ms(point["recorded_at"])
	if not resolved_at - timedelta(minutes=1) <= read_at <= resolved_at + FRESH_FIX_WINDOW:
		return {"attached": False, "reason": _("The location was not read when the ticket was resolved.")}

	seconds = int((read_at - resolved_at).total_seconds())
	log.update(
		{
			"location_status": "GPS",
			"latitude": flt(point.get("latitude")),
			"longitude": flt(point.get("longitude")),
			"accuracy_meters": flt(point.get("accuracy")),
			"recorded_at": read_at,
			"source": "Browser GPS",
			"note": _("Read {0} seconds after the ticket was resolved.").format(seconds)
			if seconds >= 0
			else _("Read {0} seconds before the ticket was resolved.").format(-seconds),
		}
	)
	log.flags.allow_update = True
	log.save(ignore_permissions=True)
	return {"attached": True}
