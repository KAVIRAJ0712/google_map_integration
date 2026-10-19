"""Location history for the map page. Every query is limited on the server to what the user may
see: agents see their own data, managers and HR see the agents of teams with the map turned on."""

from datetime import datetime, time

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from google_map_integration.tracking import analytics, config
from google_map_integration.utils import to_epoch_ms

DAY = "Agent Daily Tracking"
LOG = "Agent Location Log"
MAX_DAYS = 31
MAX_PAGE_LENGTH = 500
LOG_FIELDS = [
	"name",
	"event_type",
	"recorded_at",
	"agent",
	"hd_team",
	"daily_tracking",
	"session_id",
	"location_status",
	"latitude",
	"longitude",
	"accuracy_meters",
	"validation_status",
	"ticket",
	"ticket_resolved_at",
	"note",
]


def get_scope(user: str) -> frappe._dict:
	"""The teams and agents whose history `user` may see."""
	effective = config.get_effective_config(user)
	if not effective.map.enabled:
		frappe.throw(config.reason_message(effective.map.reason), frappe.PermissionError)
	teams = effective.map.teams
	agents = team_members(teams) if effective.can_view_all else [user]
	return frappe._dict(teams=teams, agents=agents, can_view_all=effective.can_view_all)


def team_members(teams: list[str]) -> list[str]:
	if not teams:
		return []
	return sorted(
		set(
			frappe.get_all(
				"HD Team Member", filters={"parenttype": "HD Team", "parent": ["in", teams]}, pluck="user"
			)
		)
	)


def get_filter_options(user: str) -> dict:
	scope = get_scope(user)
	return {
		"teams": scope.teams,
		"agents": [{"value": name, "label": label} for name, label in full_names(scope.agents).items()],
		"event_types": frappe.get_meta(LOG).get_field("event_type").options.split("\n"),
		"can_view_all": scope.can_view_all,
		"max_days": MAX_DAYS,
	}


def get_location_logs(
	user: str,
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
	"""One page of location logs matching the filters, oldest first."""
	scope = get_scope(user)
	start, end = date_range(from_date, to_date)
	filters = {
		"recorded_at": ["between", [start, end]],
		"hd_team": ["in", [allowed(team, scope.teams, _("team"))] if team else scope.teams],
		"agent": allowed(agent, scope.agents, _("agent")) if agent else ["in", scope.agents],
	}
	for fieldname, value in (
		("ticket", ticket),
		("event_type", event_type),
		("daily_tracking", daily_tracking),
		("session_id", session_id),
	):
		if value:
			filters[fieldname] = value
	if not include_low_accuracy:
		filters["validation_status"] = "Valid"

	page_length = min(max(cint(page_length), 1), MAX_PAGE_LENGTH)
	page = max(cint(page), 1)
	rows = frappe.get_list(
		LOG,
		filters=filters,
		fields=LOG_FIELDS,
		order_by="recorded_at asc",
		limit=page_length + 1,
		offset=(page - 1) * page_length,
	)
	return {
		"rows": [serialize_log(row) for row in rows[:page_length]],
		"page": page,
		"page_length": page_length,
		"has_more": len(rows) > page_length,
		"agent_names": full_names({row.agent for row in rows}),
	}


def get_tracking_days(user: str, agent: str, from_date: str, to_date: str) -> list[dict]:
	"""An agent's tracking days in the range, newest first."""
	scope = get_scope(user)
	allowed(agent, scope.agents, _("agent"))
	date_range(from_date, to_date)
	days = frappe.get_list(
		DAY,
		filters={
			"user": agent,
			"attendance_date": ["between", [getdate(from_date), getdate(to_date)]],
			"hd_team": ["in", scope.teams],
		},
		fields=["name", "attendance_date", "status", "shift", "checkin_time", "checkout_time"],
		order_by="attendance_date desc",
		limit=MAX_DAYS * 2,
	)
	return [
		{
			"name": day.name,
			"attendance_date": str(day.attendance_date),
			"status": day.status,
			"shift": day.shift,
			"checkin_time": epoch(day.checkin_time),
			"checkout_time": epoch(day.checkout_time),
		}
		for day in days
	]


def get_team_routes(user: str, date: str, team: str | None = None, agent: str | None = None) -> list[dict]:
	"""The route of every agent the user may see on one day, to draw them on one map."""
	scope = get_scope(user)
	days = frappe.get_list(
		DAY,
		filters={
			"attendance_date": getdate(date),
			"hd_team": ["in", [allowed(team, scope.teams, _("team"))] if team else scope.teams],
			"user": allowed(agent, scope.agents, _("agent")) if agent else ["in", scope.agents],
		},
		fields=["name", "user"],
		order_by="user asc",
	)
	if not days:
		return []

	pings = {}
	for log in frappe.get_all(
		LOG,
		filters={
			"daily_tracking": ["in", [day.name for day in days]],
			"event_type": "Location Ping",
			"validation_status": "Valid",
		},
		fields=LOG_FIELDS,
	):
		pings.setdefault(cint(log.daily_tracking), []).append(log)
	gap_seconds = cint(config.get_settings().tracking_gap_minutes) * 60
	names = full_names(day.user for day in days)

	routes = []
	for day in days:
		points = analytics.drop_spikes(analytics.route_points(pings.get(cint(day.name), [])))
		if not points:
			continue
		routes.append(
			{
				"agent": day.user,
				"agent_name": names.get(day.user),
				"daily_tracking": cint(day.name),
				"segments": [
					[{"lat": point.lat, "lng": point.lng, "t": epoch(point.t)} for point in segment]
					for segment in analytics.split_segments(points, gap_seconds)
				],
			}
		)
	return routes


def get_day_summary(user: str, daily_tracking: int) -> dict:
	"""The route, stops, gaps, events and figures of one tracking day."""
	scope = get_scope(user)
	day = frappe.get_doc(DAY, daily_tracking)
	if day.user not in scope.agents or day.hd_team not in scope.teams:
		frappe.throw(_("You cannot view this tracking day."), frappe.PermissionError)
	day.check_permission("read")

	logs = frappe.get_all(
		LOG,
		filters={"daily_tracking": day.name},
		fields=[*LOG_FIELDS, "employee"],
		order_by="recorded_at asc",
	)
	attendance_hours = (
		flt(frappe.db.get_value("Attendance", day.attendance, "working_hours")) if day.attendance else None
	)
	summary = analytics.summarize_day(day, logs, config.get_settings(), attendance_hours)
	return {
		"day": {
			"name": day.name,
			"agent": day.user,
			"agent_name": full_names([day.user]).get(day.user),
			"employee": day.employee,
			"attendance_date": str(day.attendance_date),
			"status": day.status,
			"shift": day.shift,
			"checkin_time": epoch(day.checkin_time),
			"checkout_time": epoch(day.checkout_time),
			"interruption_reason": day.interruption_reason,
		},
		"segments": [
			[{"lat": point.lat, "lng": point.lng, "t": epoch(point.t)} for point in segment]
			for segment in summary.segments
		],
		"stops": [
			{**stop, "arrival": epoch(stop.arrival), "departure": epoch(stop.departure)}
			for stop in summary.stops
		],
		"gaps": [{**gap, "start": epoch(gap.start), "end": epoch(gap.end)} for gap in summary.gaps],
		"events": [serialize_log(log) for log in logs if log.event_type != "Location Ping"],
		"metrics": {
			**summary.metrics,
			"first_ping_at": epoch(summary.metrics.first_ping_at),
			"last_ping_at": epoch(summary.metrics.last_ping_at),
		},
	}


def serialize_log(row) -> dict:
	"""A log for the browser. Logs without a location get no coordinates, so nothing is drawn at
	the 0, 0 placeholder."""
	located = row.location_status != "Unavailable"
	return {
		"name": row.name,
		"event_type": row.event_type,
		"recorded_at": epoch(row.recorded_at),
		"agent": row.agent,
		"hd_team": row.hd_team,
		"daily_tracking": cint(row.daily_tracking) or None,
		"session_id": row.session_id,
		"location_status": row.location_status,
		"latitude": flt(row.latitude) if located else None,
		"longitude": flt(row.longitude) if located else None,
		"accuracy_meters": flt(row.accuracy_meters) if located else None,
		"location_age_seconds": location_age(row),
		"validation_status": row.validation_status,
		"ticket": row.ticket,
		"ticket_resolved_at": epoch(row.ticket_resolved_at),
		"note": row.note,
	}


def location_age(row) -> int:
	"""How old a last known location was when the ticket was resolved, in seconds."""
	if row.location_status != "Last Known" or not row.ticket_resolved_at:
		return 0
	return max(0, int((get_datetime(row.ticket_resolved_at) - get_datetime(row.recorded_at)).total_seconds()))


def date_range(from_date: str, to_date: str) -> tuple[datetime, datetime]:
	start, end = getdate(from_date), getdate(to_date)
	if end < start:
		frappe.throw(_("The end date is before the start date."))
	if (end - start).days + 1 > MAX_DAYS:
		frappe.throw(_("Choose at most {0} days.").format(MAX_DAYS))
	return datetime.combine(start, time.min), datetime.combine(end, time.max)


def allowed(value: str, permitted: list[str], label: str) -> str:
	if value not in permitted:
		frappe.throw(_("You cannot view this {0}.").format(label), frappe.PermissionError)
	return value


def full_names(users) -> dict[str, str]:
	users = [user for user in users if user]
	if not users:
		return {}
	return dict(
		frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"], as_list=True)
	)


def epoch(value) -> int | None:
	return to_epoch_ms(value) if value else None
