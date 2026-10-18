"""The tracking window and sessions of an agent's working day.

An HRMS check-in opens the window and starts tracking, the tracker page sends pings while it is
open on the agent's device, and the check-out ends tracking and closes the window. Scheduled jobs
handle sessions that go quiet and days that never get a check-out."""

import uuid
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, cstr, flt, get_datetime, getdate, now_datetime, today
from frappe.utils.data import sha256_hash
from frappe.utils.messages import clear_messages

from google_map_integration.integrations import hrms
from google_map_integration.tracking import config
from google_map_integration.tracking.validation import CLOCK_SKEW, has_coordinates, validate_coordinates
from google_map_integration.utils import from_epoch_ms, to_epoch_ms

DAY = "Agent Daily Tracking"
LOG = "Agent Location Log"
# HRMS check-ins and check-outs are logged as these events, with the time and location HRMS sent
HRMS_EVENTS = ("Check-in", "Check-out")
OPEN_STATUSES = ("Not Started", "Active", "Interrupted")
RUNNING_STATUSES = ("Active", "Interrupted")
CLOSED_STATUSES = ("Completed", "Missing Checkout")
MAX_POINTS_PER_REQUEST = 100
# One device sends an agent's readings at a time: the browser login session that sent last, kept in
# the cache. Losing the cache only means the next device to send takes over.
DEVICE_CACHE_KEY = "google_map_integration:tracking_device:{}"


def make_tracking_key(employee: str, attendance_date, shift: str | None) -> str:
	"""One tracking record per employee, attendance date and shift."""
	return "|".join((employee, str(getdate(attendance_date)), shift or ""))


# HRMS check-in and check-out


def open_day_from_checkin(checkin) -> str | None:
	"""An HRMS check-in opens the tracking window for the shift and starts tracking, unless the
	window has already passed. Agents whose teams do not track get no record at all."""
	user = hrms.get_user(checkin.employee)
	tracking = config.get_effective_config(user).tracking if user else None
	if not (tracking and tracking.enabled):
		return None

	day = get_or_new_day(checkin, user, tracking.teams[0])
	# the shift's first check-in, also when a device syncs check-ins out of order
	if not day.checkin_time or get_datetime(checkin.time) < get_datetime(day.checkin_time):
		day.checkin_time = checkin.time
	if day.status in ("Completed", "Missing Checkout"):
		# back from a break within the same shift
		day.status = "Not Started"
		day.interruption_reason = None
	day.save(ignore_permissions=True)
	log_hrms_event(day, "Check-in", checkin)
	if not day.session_id and now_datetime() <= window_deadline(day, config.get_settings()):
		begin_session(day, hrms_time(checkin))
		day.save(ignore_permissions=True)
	notify(day)
	return day.name


def close_day_from_checkout(checkout) -> str | None:
	"""An HRMS check-out ends the running session and closes the window."""
	day = find_day_for_checkout(checkout)
	if not day:
		return None

	if day.session_id:
		end_session(day, hrms_time(checkout))
	if not day.checkout_time or get_datetime(checkout.time) >= get_datetime(day.checkout_time):
		day.checkout_time = checkout.time
	day.status = "Completed"
	day.interruption_reason = None
	day.save(ignore_permissions=True)
	log_hrms_event(day, "Check-out", checkout)
	notify(day)
	return day.name


def remove_checkin(checkin_name: str) -> None:
	"""HR deleted a check-in: remove its event and take the day's times from the events left. A day
	left without a check-in closes as a check-out would; one without its last check-out is open
	again until the hourly job closes it."""
	for event in frappe.get_all(
		LOG, filters={"client_event_id": f"checkin:{checkin_name}"}, fields=["name", "daily_tracking"]
	):
		frappe.db.delete(LOG, {"name": event.name})
		remaining = frappe.get_all(
			LOG,
			filters={"daily_tracking": event.daily_tracking, "event_type": ["in", HRMS_EVENTS]},
			fields=["event_type", "recorded_at"],
			order_by="recorded_at asc",
		)
		checkins = [row.recorded_at for row in remaining if row.event_type == "Check-in"]
		checkouts = [row.recorded_at for row in remaining if row.event_type == "Check-out"]
		day = frappe.get_doc(DAY, event.daily_tracking)
		day.checkin_time = checkins[0] if checkins else None
		day.checkout_time = checkouts[-1] if checkouts else None
		if not checkins:
			# an open window would start tracking again, with no check-in behind it
			if day.session_id:
				end_session(day, now_datetime())
			day.status = "Completed"
			day.interruption_reason = None
		elif day.status == "Completed" and remaining[-1].event_type != "Check-out":
			day.status = "Not Started"
		day.save(ignore_permissions=True)
		notify(day)


def check_in(user: str, log_type: str, point: dict | None) -> str:
	"""An HRMS check-in or check-out from the tracker page, with the location read when the agent
	tapped it. HRMS's check-in hook then starts or ends tracking, as for any other check-in."""
	if log_type not in ("IN", "OUT"):
		frappe.throw(_("Log Type must be IN or OUT."))
	tracking = config.get_effective_config(user).tracking
	if not tracking.enabled:
		frappe.throw(config.reason_message(tracking.reason), frappe.PermissionError)
	if not hrms.can_check_in_from_app():
		frappe.throw(
			_("HR Settings do not allow checking in from an app. Check in through HRMS."),
			frappe.PermissionError,
		)
	latitude = longitude = None
	if point and has_coordinates(point.get("latitude"), point.get("longitude")):
		validate_coordinates(point["latitude"], point["longitude"], _("The location"))
		latitude, longitude = flt(point["latitude"]), flt(point["longitude"])
	return hrms.create_checkin(tracking.employee, log_type, latitude, longitude)


def hrms_time(checkin) -> datetime:
	"""When a check-in happened, for this app's logs. HRMS can take the time from the device, whose
	clock may run ahead of the server's, and logs cannot be in the future."""
	return min(get_datetime(checkin.time), now_datetime())


def infer_log_type(checkin) -> str:
	"""Shift types set to alternate IN and OUT leave the log type blank: an open window means OUT."""
	key = make_tracking_key(checkin.employee, attendance_date_of(checkin), checkin.shift)
	status = frappe.db.get_value(DAY, {"tracking_key": key}, "status")
	return "OUT" if status in OPEN_STATUSES else "IN"


def get_or_new_day(checkin, user: str, team: str):
	attendance_date = attendance_date_of(checkin)
	key = make_tracking_key(checkin.employee, attendance_date, checkin.shift)
	if name := frappe.db.get_value(DAY, {"tracking_key": key}):
		return frappe.get_doc(DAY, name)
	return frappe.get_doc(
		{
			"doctype": DAY,
			"employee": checkin.employee,
			"user": user,
			"hd_team": team,
			"attendance_date": attendance_date,
			"shift": checkin.shift,
			"shift_start": checkin.shift_start,
			"shift_end": checkin.shift_end,
			"status": "Not Started",
		}
	)


def find_day_for_checkout(checkout):
	key = make_tracking_key(checkout.employee, attendance_date_of(checkout), checkout.shift)
	name = frappe.db.get_value(DAY, {"tracking_key": key})
	if not name:
		# a check-out outside the shift closes the employee's latest open day
		name = frappe.db.get_value(
			DAY,
			{"employee": checkout.employee, "status": ["in", (*OPEN_STATUSES, "Missing Checkout")]},
			"name",
			order_by="attendance_date desc",
		)
	return frappe.get_doc(DAY, name) if name else None


def attendance_date_of(checkin):
	"""HRMS dates attendance by the shift's start, so a night shift belongs to the day it starts."""
	return getdate(checkin.shift_start or checkin.time)


# Tracking sessions


def get_open_day(user: str, settings=None):
	"""The user's day whose window is open now: checked in, not checked out, and not past the shift
	end plus the grace period."""
	settings = settings or config.get_settings()
	now = now_datetime()
	for name in frappe.get_all(
		DAY,
		filters={"user": user, "status": ["in", OPEN_STATUSES]},
		pluck="name",
		order_by="attendance_date desc",
		limit=5,
	):
		day = frappe.get_doc(DAY, name)
		if now <= window_deadline(day, settings):
			return day
	return None


def window_deadline(day, settings) -> datetime:
	"""When an open window counts as abandoned: the shift end, or the end of the day without a
	shift, plus the grace period."""
	end = (
		get_datetime(day.shift_end)
		if day.shift_end
		else datetime.combine(getdate(day.attendance_date), time.max)
	)
	return end + timedelta(minutes=cint(settings.missing_checkout_grace_minutes))


def start_session(user: str):
	"""Start tracking in the user's open window, for a window that has no session (tracking was
	turned back on for the team, or a check-out was deleted) or a site that does not require an
	HRMS check-in. The tracker page calls this itself. Starting again replaces the running session."""
	effective = config.get_effective_config(user)
	if not effective.tracking.enabled:
		frappe.throw(config.reason_message(effective.tracking.reason), frappe.PermissionError)
	settings = config.get_settings()
	day = get_open_day(user, settings)
	if not day:
		if settings.require_hrms_checkin:
			frappe.throw(_("Check in through HRMS before you start tracking."))
		if checked_out_today(user):
			frappe.throw(_("You have checked out for today."))
		day = get_or_new_manual_day(user, effective.tracking)

	now = now_datetime()
	if day.session_id:
		end_session(day, now)
	begin_session(day, now)
	day.save(ignore_permissions=True)
	notify(day)
	return day


def can_start_session(user: str, day, settings) -> bool:
	"""Whether the tracker page should start tracking itself: in an open window without a session,
	or, on a site that does not require a check-in, until the agent checks out for the day."""
	if day:
		return not day.session_id
	return not settings.require_hrms_checkin and not checked_out_today(user)


def checked_out_today(user: str) -> bool:
	return bool(
		frappe.db.exists(DAY, {"user": user, "attendance_date": today(), "status": ["in", CLOSED_STATUSES]})
	)


def begin_session(day, at) -> None:
	"""Start a new tracking session on `day` at `at`. The caller saves `day`. Times are the
	session's own, so a session after a break is not judged by readings from before it."""
	day.update(
		{
			"session_id": uuid.uuid4().hex,
			"status": "Active",
			"tracking_started_at": at,
			"tracking_ended_at": None,
			"last_location_at": None,
			"interruption_reason": None,
		}
	)


def get_or_new_manual_day(user: str, tracking):
	"""A day without an HRMS check-in, for sites that do not require one."""
	key = make_tracking_key(tracking.employee, today(), None)
	if name := frappe.db.get_value(DAY, {"tracking_key": key}):
		return frappe.get_doc(DAY, name)
	return frappe.get_doc(
		{
			"doctype": DAY,
			"employee": tracking.employee,
			"user": user,
			"hd_team": tracking.teams[0],
			"attendance_date": today(),
			"status": "Not Started",
		}
	).insert(ignore_permissions=True)


def report_location_blocked(user: str, session_id: str) -> dict:
	"""The agent's browser blocked location. Tracking runs until check-out, so the session stays
	open and readings resume as soon as location is allowed again."""
	day = get_running_day(user, session_id)
	if not day:
		return {"reported": False}
	if (day.status, day.interruption_reason) != ("Interrupted", "Location Permission Denied"):
		day.status = "Interrupted"
		day.interruption_reason = "Location Permission Denied"
		day.save(ignore_permissions=True)
		notify(day)
	return {"reported": True, "status": day.status}


def take_over(user: str) -> None:
	"""Send the agent's readings from this device; their other device stops at its next send."""
	day = get_open_day(user)
	if day and day.status in RUNNING_STATUSES:
		claim_device(day)


def get_running_day(user: str, session_id: str):
	if not session_id:
		return None
	name = frappe.db.get_value(
		DAY, {"user": user, "session_id": session_id, "status": ["in", RUNNING_STATUSES]}
	)
	return frappe.get_doc(DAY, name) if name else None


def end_session(day, at) -> None:
	"""Stop the running session on `day`. The caller saves `day`."""
	# HRMS times have whole seconds, so a check-out can land a moment before the session start
	at = max(get_datetime(at), get_datetime(day.tracking_started_at or at))
	day.session_id = None
	day.tracking_ended_at = at


# Location pings


def record_points(user: str, session_id: str, points: list[dict]) -> dict:
	"""Store a batch of pings from the tracker page. Duplicates are skipped, pings closer together
	than half the interval are dropped, and each rejected ping comes back with its reason. Pings
	from a device other than the one sending the agent's readings are refused as a whole."""
	if len(points) > MAX_POINTS_PER_REQUEST:
		frappe.throw(_("Send at most {0} locations at a time.").format(MAX_POINTS_PER_REQUEST))
	day = get_running_day(user, session_id)
	if not day:
		return {"session_active": False}

	tracking = config.get_effective_config(user).tracking
	if not tracking.enabled:
		end_session(day, now_datetime())
		day.status = "Not Started"
		day.interruption_reason = "Tracking Turned Off"
		day.save(ignore_permissions=True)
		return {"session_active": False}
	if sending_elsewhere(day, tracking.interval):
		return {"session_active": True, "other_device": True}
	claim_device(day)

	result = {"accepted": 0, "duplicates": 0, "throttled": 0, "rejected": []}
	ids = [cstr(point.get("client_event_id")).strip() for point in points]
	known_ids = set(
		frappe.get_all(LOG, filters={"agent": user, "client_event_id": ["in", ids]}, pluck="client_event_id")
		if any(ids)
		else ()
	)
	min_spacing = timedelta(seconds=tracking.interval / 2)
	last_at = frappe.db.get_value(
		LOG,
		{"session_id": session_id, "event_type": "Location Ping"},
		"recorded_at",
		order_by="recorded_at desc",
	)
	latest = None

	for point in sorted(points, key=lambda point: flt(point.get("recorded_at"))):
		event_id = cstr(point.get("client_event_id")).strip()
		if event_id in known_ids:
			result["duplicates"] += 1
			continue
		if event_id:
			known_ids.add(event_id)
		recorded_at, reason = read_point_time(point, day)
		if not reason and last_at and recorded_at - get_datetime(last_at) < min_spacing:
			result["throttled"] += 1
			continue
		reason = reason or insert_point(day, session_id, event_id, recorded_at, point)
		if reason:
			result["rejected"].append({"client_event_id": event_id, "reason": reason})
			continue
		result["accepted"] += 1
		last_at = latest = recorded_at

	if latest:
		save_last_location(day, latest)
	return {
		**result,
		"session_active": True,
		"status": day.status,
		"interval_seconds": tracking.interval,
		"server_time": to_epoch_ms(now_datetime()),
	}


def read_point_time(point: dict, day) -> tuple[datetime | None, str | None]:
	"""The ping's time in the site's timezone, or why it cannot be used."""
	if not cstr(point.get("client_event_id")).strip():
		return None, _("Missing client_event_id.")
	try:
		recorded_at = from_epoch_ms(point["recorded_at"])
	except (KeyError, TypeError, ValueError, OverflowError):
		return None, _("recorded_at must be milliseconds since 1970.")
	if day.tracking_started_at and recorded_at < get_datetime(day.tracking_started_at) - CLOCK_SKEW:
		return None, _("Recorded before tracking started.")
	return recorded_at, None


def insert_point(day, session_id: str, event_id: str, recorded_at: datetime, point: dict) -> str | None:
	"""Store one ping; returns the reason when it is rejected, so one bad ping does not fail the batch."""
	frappe.db.savepoint("google_map_integration_point")
	try:
		frappe.get_doc(
			{
				"doctype": LOG,
				"event_type": "Location Ping",
				"agent": day.user,
				"daily_tracking": day.name,
				"session_id": session_id,
				"client_event_id": event_id,
				"recorded_at": recorded_at,
				"latitude": flt(point.get("latitude")),
				"longitude": flt(point.get("longitude")),
				"accuracy_meters": flt(point.get("accuracy")),
				"location_status": "GPS",
				"source": "Browser GPS",
			}
		).insert(ignore_permissions=True)
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point="google_map_integration_point")
		clear_messages()
		return cstr(error) or error.__class__.__name__
	return None


def save_last_location(day, latest: datetime) -> None:
	"""A ping brings an interrupted session back. Otherwise only the time is stored, without a new
	version of the record for every ping."""
	if day.last_location_at and get_datetime(day.last_location_at) >= latest:
		return
	if day.status == "Interrupted":
		day.status = "Active"
		day.interruption_reason = None
		day.last_location_at = latest
		day.save(ignore_permissions=True)
		notify(day)
	else:
		day.db_set("last_location_at", latest, update_modified=False)


def this_device() -> str:
	"""The browser making this request, as a hash of its login session."""
	return sha256_hash(cstr(frappe.session.sid))


def sending_elsewhere(day, interval: int) -> bool:
	"""Whether another of the agent's devices is sending this day's readings. A device that has sent
	nothing for two intervals gives way, so tracking moves to whichever device is still open."""
	owner = frappe.cache.get_value(DEVICE_CACHE_KEY.format(day.name))
	if not owner or owner == this_device() or not day.last_location_at:
		return False
	return now_datetime() - get_datetime(day.last_location_at) <= timedelta(seconds=2 * interval)


def claim_device(day) -> None:
	frappe.cache.set_value(DEVICE_CACHE_KEY.format(day.name), this_device(), expires_in_sec=24 * 3600)


# Scheduled jobs


def mark_interrupted_sessions() -> None:
	"""Every 5 minutes: a running session with no ping for the configured gap is interrupted."""
	cutoff = add_to_date(now_datetime(), minutes=-cint(config.get_settings().tracking_gap_minutes))
	for row in frappe.get_all(
		DAY, filters={"status": "Active"}, fields=["name", "last_location_at", "tracking_started_at"]
	):
		last = row.last_location_at or row.tracking_started_at
		if last and get_datetime(last) < cutoff:
			update_safely(row.name, interrupt)


def close_missing_checkouts() -> None:
	"""Hourly: a window still open after the shift end plus the grace period is closed as a missing
	check-out. A late HRMS check-out still completes it."""
	settings = config.get_settings()
	now = now_datetime()
	for name in frappe.get_all(DAY, filters={"status": ["in", OPEN_STATUSES]}, pluck="name"):
		day = frappe.get_doc(DAY, name)
		deadline = window_deadline(day, settings)
		if now > deadline:
			update_safely(name, close_missing_checkout, deadline)


def interrupt(day) -> None:
	day.status = "Interrupted"
	day.interruption_reason = "No Location Received"


def close_missing_checkout(day, deadline: datetime) -> None:
	if day.session_id:
		ended = get_datetime(day.last_location_at or deadline)
		end_session(day, max(ended, get_datetime(day.tracking_started_at)))
	day.status = "Missing Checkout"
	day.interruption_reason = "No Check-out"


def update_safely(name: str, change, *args) -> None:
	"""Apply `change` to one day in a scheduled job, so one bad record does not stop the others.
	The scheduler commits when the job ends."""
	frappe.db.savepoint("google_map_integration_job")
	try:
		day = frappe.get_doc(DAY, name)
		change(day, *args)
		day.save(ignore_permissions=True)
		notify(day)
	except Exception:
		frappe.db.rollback(save_point="google_map_integration_job")
		frappe.log_error(title=f"Google Maps integration: could not update {DAY} {name}")


# Shared helpers


def log_event(day, event_type: str, recorded_at, **values) -> None:
	"""Log an event of `day`. Events have no location unless `values` give one."""
	frappe.get_doc(
		{
			"doctype": LOG,
			"event_type": event_type,
			"agent": day.user,
			"daily_tracking": day.name,
			"recorded_at": recorded_at,
			"location_status": "Unavailable",
			**values,
		}
	).insert(ignore_permissions=True)


def log_hrms_event(day, event_type: str, checkin) -> None:
	"""Log a check-in or check-out with the location HRMS recorded, if any. Biometric devices send
	none."""
	located = has_coordinates(checkin.latitude, checkin.longitude)
	log_event(
		day,
		event_type,
		hrms_time(checkin),
		client_event_id=f"checkin:{checkin.name}",
		location_status="GPS" if located else "Unavailable",
		latitude=flt(checkin.latitude) if located else 0,
		longitude=flt(checkin.longitude) if located else 0,
		source="HRMS Check-in" if located else None,
	)


def notify(day) -> None:
	"""Tell the agent's open tracker pages that their day changed."""
	frappe.publish_realtime(
		"google_map_integration:tracking",
		{"day": day.name, "status": day.status},
		user=day.user,
		after_commit=True,
	)


def get_status(user: str) -> dict:
	"""What the tracker page shows and does: whether tracking is allowed, the open day if any,
	whether the page should start tracking itself or check in, and whether another of the agent's
	devices is sending their readings."""
	tracking = config.get_client_config(user)["tracking"]
	settings = config.get_settings()
	day = get_open_day(user, settings) if tracking["enabled"] else None
	running = bool(day) and day.status in RUNNING_STATUSES
	return {
		"tracking": tracking,
		"window_open": bool(day),
		"day": day_summary(day) if day else None,
		"can_start": tracking["enabled"] and can_start_session(user, day, settings),
		"can_check_in": tracking["enabled"] and hrms.can_check_in_from_app(),
		"other_device": running and sending_elsewhere(day, tracking["interval_seconds"]),
		"server_time": to_epoch_ms(now_datetime()),
	}


def day_summary(day) -> dict:
	def epoch(value):
		return to_epoch_ms(value) if value else None

	return {
		"name": day.name,
		"status": day.status,
		"attendance_date": str(day.attendance_date),
		"shift": day.shift,
		"session_id": day.session_id if day.status in RUNNING_STATUSES else None,
		"checkin_time": epoch(day.checkin_time),
		"shift_end": epoch(day.shift_end),
		"tracking_started_at": epoch(day.tracking_started_at),
		"last_location_at": epoch(day.last_location_at),
		"interruption_reason": day.interruption_reason,
	}
