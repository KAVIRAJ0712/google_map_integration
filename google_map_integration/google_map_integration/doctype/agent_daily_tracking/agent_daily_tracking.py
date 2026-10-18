# Copyright (c) 2026, Kaviraj and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from google_map_integration.integrations import helpdesk
from google_map_integration.tracking.sessions import make_tracking_key

# Stopping tracking returns to Not Started. A closed day only reopens through HRMS: a new check-in
# in the same shift, or a late check-out that completes a missing one.
STATUS_TRANSITIONS = {
	"Not Started": {"Active", "Completed", "Missing Checkout"},
	"Active": {"Not Started", "Interrupted", "Completed", "Missing Checkout"},
	"Interrupted": {"Not Started", "Active", "Completed", "Missing Checkout"},
	"Completed": {"Not Started"},
	"Missing Checkout": {"Not Started", "Completed"},
}


class AgentDailyTracking(Document):
	def validate(self):
		self.validate_employee()
		self.validate_team()
		self.validate_attendance()
		self.validate_times()
		self.validate_status_change()
		self.set_tracking_key()

	def validate_employee(self):
		if frappe.db.get_value("Employee", self.employee, "user_id") != self.user:
			frappe.throw(_("Employee {0} is not linked to user {1}.").format(self.employee, self.user))

	def validate_team(self):
		"""Checked when the day starts only; the agent may leave the team later."""
		if self.is_new() and self.hd_team and not helpdesk.is_team_member(self.user, self.hd_team):
			frappe.throw(_("{0} is not a member of team {1}.").format(self.user, self.hd_team))

	def validate_attendance(self):
		if self.attendance and frappe.db.get_value("Attendance", self.attendance, "employee") != self.employee:
			frappe.throw(_("Attendance {0} belongs to another employee.").format(self.attendance))

	def validate_times(self):
		for start, end in (
			("shift_start", "shift_end"),
			("checkin_time", "checkout_time"),
			("tracking_started_at", "tracking_ended_at"),
		):
			if (
				self.get(start)
				and self.get(end)
				and get_datetime(self.get(end)) < get_datetime(self.get(start))
			):
				frappe.throw(
					_("{0} cannot be before {1}.").format(
						_(self.meta.get_label(end)), _(self.meta.get_label(start))
					)
				)

	def validate_status_change(self):
		previous = self.get_doc_before_save()
		if not previous or previous.status == self.status:
			return
		if self.status not in STATUS_TRANSITIONS.get(previous.status, set()):
			frappe.throw(
				_("Tracking status cannot change from {0} to {1}.").format(_(previous.status), _(self.status))
			)

	def set_tracking_key(self):
		"""One record per employee, attendance date and shift. The unique key lets the database
		enforce that even when two check-ins arrive at the same moment."""
		self.tracking_key = make_tracking_key(self.employee, self.attendance_date, self.shift)


def on_doctype_update():
	frappe.db.add_index("Agent Daily Tracking", ["user", "attendance_date"])
	frappe.db.add_index("Agent Daily Tracking", ["employee", "attendance_date"])
	frappe.db.add_index("Agent Daily Tracking", ["hd_team", "attendance_date"])
