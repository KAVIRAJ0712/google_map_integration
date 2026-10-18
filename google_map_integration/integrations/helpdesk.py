"""Helpdesk data this app reads, and the hooks on Helpdesk documents. Kept in one module so a
Helpdesk upgrade only needs changes here."""

import frappe

from google_map_integration.utils import never_block

TEAM_MAP_FIELD = "custom_enable_google_map"
TEAM_TRACKING_FIELD = "custom_enable_agent_location_tracking"
TEAM_INTERVAL_FIELD = "custom_location_tracking_interval"
TEAM_SETTINGS_FIELDS = (TEAM_MAP_FIELD, TEAM_TRACKING_FIELD, TEAM_INTERVAL_FIELD)


def is_active_agent(user: str) -> bool:
	"""Whether `user` has an active HD Agent record. Unlike Helpdesk's `is_agent`, Administrator
	does not count, since only real agents are tracked."""
	return bool(frappe.db.exists("HD Agent", {"user": user, "is_active": 1}))


@never_block
def on_ticket_update(doc, method: str | None = None) -> None:
	"""HD Ticket on_update: log where a tracked agent resolved the ticket. Uses the same signal as
	Helpdesk's own "ticket resolved" event, so moving from Resolved to Closed does not log again."""
	if not (doc.has_value_changed("status_category") and doc.status_category == "Resolved"):
		return
	from google_map_integration.tracking import resolutions  # resolutions imports this module

	resolutions.log_resolution(doc, frappe.session.user)


def is_team_member(user: str, team: str) -> bool:
	return bool(frappe.db.exists("HD Team Member", {"parent": team, "parenttype": "HD Team", "user": user}))


def get_teams(user: str | None = None) -> list[frappe._dict]:
	"""Enabled HD Teams with their map and tracking switches, only `user`'s teams when given."""
	Team = frappe.qb.DocType("HD Team")
	query = (
		frappe.qb.from_(Team)
		.select(
			Team.name,
			getattr(Team, TEAM_MAP_FIELD).as_("map_enabled"),
			getattr(Team, TEAM_TRACKING_FIELD).as_("tracking_enabled"),
			getattr(Team, TEAM_INTERVAL_FIELD).as_("interval"),
		)
		.where(Team.disabled == 0)
		.orderby(Team.name)
	)
	if user:
		Member = frappe.qb.DocType("HD Team Member")
		query = (
			query.join(Member)
			.on((Member.parent == Team.name) & (Member.parenttype == "HD Team"))
			.where(Member.user == user)
			.distinct()
		)
	return query.run(as_dict=True)
