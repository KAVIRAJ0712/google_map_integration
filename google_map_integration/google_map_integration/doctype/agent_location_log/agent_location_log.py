# Copyright (c) 2026, Kaviraj and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from google_map_integration.tracking import config
from google_map_integration.tracking.validation import (
	has_coordinates,
	validate_coordinates,
	validate_not_in_future,
)


class AgentLocationLog(Document):
	def before_insert(self):
		# blank ids must be NULL, or every event without one would collide in the unique index
		self.client_event_id = (self.client_event_id or "").strip() or None

	def validate(self):
		self.prevent_changes()
		self.validate_daily_tracking()
		self.validate_event()
		self.validate_location()
		self.set_validation_status()

	def prevent_changes(self):
		"""Location logs are a record of what happened: they are added and deleted, never edited."""
		if not self.is_new() and not self.flags.allow_update:
			frappe.throw(_("Location logs cannot be changed."))

	def validate_daily_tracking(self):
		if not self.daily_tracking:
			return
		tracking = frappe.db.get_value(
			"Agent Daily Tracking", self.daily_tracking, ["user", "employee", "hd_team"], as_dict=True
		)
		if not tracking or tracking.user != self.agent:
			frappe.throw(_("Daily Tracking {0} belongs to another agent.").format(self.daily_tracking))
		if self.employee and self.employee != tracking.employee:
			frappe.throw(_("Employee {0} does not match the daily tracking record.").format(self.employee))
		self.employee = tracking.employee
		self.hd_team = self.hd_team or tracking.hd_team

	def validate_event(self):
		validate_not_in_future(self.recorded_at, _("Recorded At"))
		if self.event_type == "Location Ping":
			if not (self.daily_tracking and self.session_id):
				frappe.throw(_("A location ping needs a daily tracking record and a session."))
			if self.location_status == "Unavailable":
				frappe.throw(_("A location ping must have a location."))
		if self.event_type == "Ticket Resolved" and not (self.ticket and self.ticket_resolved_at):
			frappe.throw(_("A ticket resolution event needs the ticket and its resolution time."))

	def validate_location(self):
		if self.location_status == "Unavailable":
			if has_coordinates(self.latitude, self.longitude):
				frappe.throw(_("A log without a location cannot have coordinates."))
			self.accuracy_meters = 0
			return

		if not has_coordinates(self.latitude, self.longitude):
			frappe.throw(_("Latitude and longitude are required unless the location is unavailable."))
		validate_coordinates(self.latitude, self.longitude, _("The location"))
		if flt(self.accuracy_meters) < 0:
			frappe.throw(_("Accuracy cannot be negative."))

	def set_validation_status(self):
		"""Imprecise readings are kept for the record but left out of routes."""
		if self.validation_status == "Rejected" or self.location_status == "Unavailable":
			return
		limit = flt(config.get_settings().max_accuracy_meters)
		self.validation_status = "Low Accuracy" if limit and flt(self.accuracy_meters) > limit else "Valid"


def on_doctype_update():
	frappe.db.add_index("Agent Location Log", ["daily_tracking", "recorded_at"])
	frappe.db.add_index("Agent Location Log", ["agent", "recorded_at"])
	frappe.db.add_index("Agent Location Log", ["hd_team", "recorded_at"])
	frappe.db.add_index("Agent Location Log", ["recorded_at"])
	frappe.db.add_unique(
		"Agent Location Log", ["agent", "client_event_id"], constraint_name="unique_agent_client_event"
	)
