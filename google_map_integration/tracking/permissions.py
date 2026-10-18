"""Who may read agent location data: agents see their own records, managers and HR see all.

Role permissions on the DocTypes grant read access; these hooks narrow it for agents."""

import frappe

LOCATION_MANAGER_ROLES = frozenset(("System Manager", "Agent Manager", "HR Manager", "HR User"))
OWNER_FIELDS = {"Agent Daily Tracking": "user", "Agent Location Log": "agent"}


def can_view_all_locations(user: str | None = None) -> bool:
	"""Whether `user` may see every agent's location data."""
	user = user or frappe.session.user
	return user == "Administrator" or bool(LOCATION_MANAGER_ROLES.intersection(frappe.get_roles(user)))


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""Deny access to other agents' records. Frappe only lets this hook deny, never grant."""
	user = user or frappe.session.user
	if can_view_all_locations(user):
		return True
	return doc.get(OWNER_FIELDS[doc.doctype]) == user


def daily_tracking_query(user: str | None = None) -> str:
	return own_records_condition("Agent Daily Tracking", user)


def location_log_query(user: str | None = None) -> str:
	return own_records_condition("Agent Location Log", user)


def own_records_condition(doctype: str, user: str | None = None) -> str:
	"""List filter that keeps agents to their own records."""
	user = user or frappe.session.user
	if can_view_all_locations(user):
		return ""
	return f"`tab{doctype}`.`{OWNER_FIELDS[doctype]}` = {frappe.db.escape(user)}"
