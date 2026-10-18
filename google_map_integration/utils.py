import functools
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import convert_utc_to_system_timezone, get_datetime, get_system_timezone


def never_block(fn):
	"""For hooks on HRMS and Helpdesk documents. Attendance and ticket resolution must keep working
	when location tracking fails, so errors are logged instead of raised."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		frappe.db.savepoint("google_map_integration")
		try:
			return fn(*args, **kwargs)
		except Exception:
			frappe.db.rollback(save_point="google_map_integration")
			frappe.log_error(title=f"Google Maps integration: {fn.__name__} failed")

	return wrapper


def from_epoch_ms(value: int | float) -> datetime:
	"""A browser timestamp (milliseconds since 1970, UTC) as a naive datetime in the site's timezone,
	which is how Frappe stores datetimes."""
	utc = datetime.fromtimestamp(float(value) / 1000, tz=UTC)
	return convert_utc_to_system_timezone(utc).replace(tzinfo=None)


def to_epoch_ms(value) -> int:
	"""The reverse of `from_epoch_ms`, for sending server times to the browser."""
	local = get_datetime(value).replace(tzinfo=ZoneInfo(get_system_timezone()))
	return int(local.timestamp() * 1000)
