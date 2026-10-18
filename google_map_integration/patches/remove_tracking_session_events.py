import frappe


def execute():
	"""Tracking starts and stops with the HRMS check-in and check-out, which are logged already, so
	the Tracking Started and Tracking Stopped events were dropped."""
	frappe.db.delete("Agent Location Log", {"event_type": ["in", ("Tracking Started", "Tracking Stopped")]})
