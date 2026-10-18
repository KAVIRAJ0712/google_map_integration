"""Checks for coordinates and timestamps, shared by the tracking DocTypes and the tracking API."""

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

# Device clocks drift; allow this much before calling a timestamp "in the future"
CLOCK_SKEW = timedelta(minutes=2)


def has_coordinates(latitude, longitude) -> bool:
	"""Float columns store a missing reading as 0, so (0, 0) means "no location". That point is in
	the Gulf of Guinea, where no agent will be."""
	return bool(flt(latitude) or flt(longitude))


def validate_coordinates(latitude, longitude, label: str) -> None:
	if not -90 <= flt(latitude) <= 90 or not -180 <= flt(longitude) <= 180:
		frappe.throw(
			_("{0} must have a latitude between -90 and 90 and a longitude between -180 and 180.").format(
				label
			)
		)


def validate_not_in_future(value, label: str) -> None:
	if value and get_datetime(value) > now_datetime() + CLOCK_SKEW:
		frappe.throw(_("{0} cannot be in the future.").format(label))
