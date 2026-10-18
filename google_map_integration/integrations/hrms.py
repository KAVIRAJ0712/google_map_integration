"""HRMS data this app reads, and the hooks on HRMS documents. Kept in one module so an HRMS upgrade
only needs changes here."""

import frappe
from frappe.utils import now_datetime

from google_map_integration.utils import never_block

DAY = "Agent Daily Tracking"


def get_active_employee(user: str) -> str | None:
	"""The active Employee linked to `user`. ERPNext allows one Employee per user."""
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def get_user(employee: str) -> str | None:
	return frappe.db.get_value("Employee", employee, "user_id")


def can_check_in_from_app() -> bool:
	"""Whether HR Settings let employees check in from an app, as HRMS's own app does."""
	return bool(frappe.db.get_single_value("HR Settings", "allow_employee_checkin_from_mobile_app"))


def create_checkin(employee: str, log_type: str, latitude: float | None, longitude: float | None) -> str:
	"""An Employee Checkin by the logged-in user, with HRMS's permission and location checks. The
	time is the server's, in whole seconds like HRMS's own, since a device clock can be wrong."""
	checkin = frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"employee": employee,
			"log_type": log_type,
			"time": now_datetime().replace(microsecond=0),
			"latitude": latitude,
			"longitude": longitude,
		}
	).insert()
	return checkin.name


@never_block
def on_checkin_insert(doc, method: str | None = None) -> None:
	"""Employee Checkin after_insert: IN opens the tracking window, OUT closes it."""
	from google_map_integration.tracking import sessions  # sessions imports this module

	log_type = doc.log_type or sessions.infer_log_type(doc)
	if log_type == "OUT":
		sessions.close_day_from_checkout(doc)
	else:
		sessions.open_day_from_checkin(doc)


@never_block
def on_checkin_trash(doc, method: str | None = None) -> None:
	"""Employee Checkin on_trash: HR deleted a check-in."""
	from google_map_integration.tracking import sessions  # sessions imports this module

	sessions.remove_checkin(doc.name)


@never_block
def on_attendance_submit(doc, method: str | None = None) -> None:
	"""Link the day to the attendance HRMS marked for it; HRMS stays the record of attendance."""
	filters = {"employee": doc.employee, "attendance_date": doc.attendance_date}
	if doc.get("shift"):
		filters["shift"] = doc.shift
	for name in frappe.get_all(DAY, filters=filters, pluck="name"):
		frappe.db.set_value(DAY, name, "attendance", doc.name)


@never_block
def on_attendance_cancel(doc, method: str | None = None) -> None:
	for name in frappe.get_all(DAY, filters={"attendance": doc.name}, pluck="name"):
		frappe.db.set_value(DAY, name, "attendance", None)
