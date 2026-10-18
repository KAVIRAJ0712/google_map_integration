# Copyright (c) 2026, Kaviraj and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from google_map_integration.tracking.config import MAX_INTERVAL, MIN_INTERVAL, get_map_options


class GoogleMapsSettings(Document):
	def validate(self):
		self.validate_map_defaults()
		self.validate_tracking()
		self.validate_stop_detection()
		self.validate_retention()
		self.update_notice_version()

	def validate_map_defaults(self):
		if not 0 <= cint(self.default_zoom) <= 22:
			frappe.throw(_("Default Zoom must be between 0 and 22."))
		if not -90 <= flt(self.default_latitude) <= 90:
			frappe.throw(_("Default Latitude must be between -90 and 90."))
		if not -180 <= flt(self.default_longitude) <= 180:
			frappe.throw(_("Default Longitude must be between -180 and 180."))

	def validate_tracking(self):
		interval = cint(self.location_tracking_interval)
		if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
			frappe.throw(
				_("Tracking Interval must be between {0} and {1} seconds.").format(MIN_INTERVAL, MAX_INTERVAL)
			)
		if flt(self.max_accuracy_meters) <= 0:
			frappe.throw(_("Maximum Accuracy Radius must be more than 0 meters."))
		if cint(self.tracking_gap_minutes) * 60 < 2 * interval:
			frappe.throw(
				_(
					"Gap Before Interruption must be at least twice the Tracking Interval, so one late ping does not interrupt a session."
				)
			)
		if cint(self.last_known_max_age_minutes) < 1:
			frappe.throw(_("Last Known Location Age must be at least 1 minute."))

	def validate_stop_detection(self):
		if cint(self.stop_radius_meters) < 1 or cint(self.stop_min_dwell_minutes) < 1:
			frappe.throw(_("Stop Radius and Minimum Stop Duration must be at least 1."))

	def validate_retention(self):
		if cint(self.location_retention_days) < 1:
			frappe.throw(_("Keep Location Logs must be at least 1 day."))

	def update_notice_version(self):
		"""Agents acknowledge the notice again whenever its text changes."""
		previous = self.get_doc_before_save()
		if previous and (previous.tracking_notice or "") != (self.tracking_notice or ""):
			self.notice_version = cint(previous.notice_version) + 1


@frappe.whitelist(methods=["GET"])
def get_preview_options() -> dict:
	"""Map options for the preview on this form, which only System Managers can open."""
	frappe.only_for("System Manager")
	return get_map_options(frappe.get_cached_doc("Google Maps Settings"))
