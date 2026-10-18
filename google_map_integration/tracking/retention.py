"""Deletes location data older than the retention period in Google Maps Settings."""

import frappe
from frappe.utils import add_days, cint, getdate, now_datetime

from google_map_integration.tracking import config

DAY = "Agent Daily Tracking"
LOG = "Agent Location Log"
BATCH_SIZE = 5000
CLOSED_STATUSES = ("Completed", "Missing Checkout")


def purge_old_locations() -> dict:
	"""Daily: delete location logs older than the retention period, and closed tracking days from
	before it with their change history. Deletes in batches and commits each one, so a large
	backlog never holds a long lock."""
	days = cint(config.get_settings().location_retention_days)
	if days < 1:
		return {"logs": 0, "days": 0}
	cutoff = add_days(now_datetime(), -days)

	deleted_logs = delete_in_batches(LOG, {"recorded_at": ["<", cutoff]})
	deleted_days = 0
	while names := frappe.get_all(
		DAY,
		filters={"attendance_date": ["<", getdate(cutoff)], "status": ["in", CLOSED_STATUSES]},
		pluck="name",
		limit=BATCH_SIZE,
	):
		frappe.db.delete(LOG, {"daily_tracking": ["in", names]})
		frappe.db.delete("Version", {"ref_doctype": DAY, "docname": ["in", [str(name) for name in names]]})
		frappe.db.delete(DAY, {"name": ["in", names]})
		deleted_days += len(names)
		frappe.db.commit()
	return {"logs": deleted_logs, "days": deleted_days}


def delete_in_batches(doctype: str, filters: dict) -> int:
	deleted = 0
	while names := frappe.get_all(doctype, filters=filters, pluck="name", limit=BATCH_SIZE):
		frappe.db.delete(doctype, {"name": ["in", names]})
		deleted += len(names)
		frappe.db.commit()
	return deleted
