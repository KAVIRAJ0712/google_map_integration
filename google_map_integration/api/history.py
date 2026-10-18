"""Endpoints for the map page. Filters are applied on the server and limited to what the
logged-in user may see; the browser never receives everyone's data to filter itself."""

import frappe

from google_map_integration.tracking import history


@frappe.whitelist(methods=["GET"])
def get_filter_options() -> dict:
	return history.get_filter_options(frappe.session.user)


@frappe.whitelist(methods=["GET"])
def get_location_logs(
	from_date: str,
	to_date: str,
	team: str | None = None,
	agent: str | None = None,
	ticket: str | None = None,
	event_type: str | None = None,
	daily_tracking: int | None = None,
	session_id: str | None = None,
	include_low_accuracy: bool = True,
	page: int = 1,
	page_length: int = 200,
) -> dict:
	return history.get_location_logs(
		frappe.session.user,
		from_date,
		to_date,
		team=team,
		agent=agent,
		ticket=ticket,
		event_type=event_type,
		daily_tracking=daily_tracking,
		session_id=session_id,
		include_low_accuracy=include_low_accuracy,
		page=page,
		page_length=page_length,
	)


@frappe.whitelist(methods=["GET"])
def get_tracking_days(agent: str, from_date: str, to_date: str) -> list:
	return history.get_tracking_days(frappe.session.user, agent, from_date, to_date)


@frappe.whitelist(methods=["GET"])
def get_day_summary(daily_tracking: int) -> dict:
	return history.get_day_summary(frappe.session.user, daily_tracking)
