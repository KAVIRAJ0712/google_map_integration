"""Route, distance, gaps and stops derived from an agent's pings.

Everything here is an estimate from GPS readings taken every few minutes. Where readings are
missing, the results report the gap or mark a stop as uncertain instead of assuming what happened."""

from itertools import pairwise
from math import asin, cos, radians, sin, sqrt

import frappe
from frappe.utils import cint, flt, get_datetime

EARTH_RADIUS_M = 6_371_000
# Two readings further apart than this speed allows are a GPS error, not travel
MAX_SPEED_KMH = 200


def distance_m(a, b) -> float:
	"""Great-circle distance in meters between two points with `lat` and `lng`."""
	lat1, lng1, lat2, lng2 = map(radians, (a.lat, a.lng, b.lat, b.lng))
	h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
	return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def seconds_between(a, b) -> float:
	return (b.t - a.t).total_seconds()


def route_points(logs: list) -> list:
	"""Valid GPS pings in time order, without exact repeats. Low accuracy and rejected readings stay
	in the log but are left out of the route."""
	points, seen = [], set()
	for log in sorted(logs, key=lambda log: (get_datetime(log.recorded_at), log.name)):
		if (log.event_type, log.location_status, log.validation_status) != ("Location Ping", "GPS", "Valid"):
			continue
		point = frappe._dict(
			name=log.name,
			t=get_datetime(log.recorded_at),
			lat=flt(log.latitude),
			lng=flt(log.longitude),
			accuracy=flt(log.accuracy_meters),
			session=log.session_id,
		)
		key = (point.t, point.lat, point.lng)
		if key not in seen:
			seen.add(key)
			points.append(point)
	return points


def too_fast(a, b, max_speed_kmh: float = MAX_SPEED_KMH) -> bool:
	seconds = seconds_between(a, b)
	meters = distance_m(a, b)
	return meters > 0 and (seconds <= 0 or meters / seconds * 3.6 > max_speed_kmh)


def drop_spikes(points: list, max_speed_kmh: float = MAX_SPEED_KMH) -> list:
	"""Remove single readings that jump away and straight back: reaching them is impossible, while
	their neighbours agree with each other."""
	if len(points) < 3:
		return list(points)
	kept = [points[0]]
	for before, point, after in zip(points, points[1:], points[2:], strict=False):
		is_spike = (
			too_fast(before, point, max_speed_kmh)
			and too_fast(point, after, max_speed_kmh)
			and not too_fast(before, after, max_speed_kmh)
		)
		if not is_spike:
			kept.append(point)
	kept.append(points[-1])
	return kept


def split_segments(points: list, gap_seconds: float) -> list[list]:
	"""Stretches of route to draw as one line. A new session or a gap in readings starts a new one,
	so the map never draws a straight line across time it has no data for."""
	segments = []
	for point in points:
		last = segments[-1][-1] if segments else None
		if last and point.session == last.session and seconds_between(last, point) <= gap_seconds:
			segments[-1].append(point)
		else:
			segments.append([point])
	return segments


def find_gaps(points: list, gap_seconds: float) -> list[frappe._dict]:
	"""Stretches longer than `gap_seconds` without any reading."""
	return [
		frappe._dict(start=a.t, end=b.t, seconds=seconds_between(a, b))
		for a, b in pairwise(points)
		if seconds_between(a, b) > gap_seconds
	]


def detect_stops(points: list, radius_m: float, min_dwell_seconds: float, gap_seconds: float) -> list:
	"""Places where consecutive readings stay within `radius_m` for at least `min_dwell_seconds`.

	Arrival is the first reading there and departure the last, so a stay can be up to one interval
	longer than reported. A stop with a gap in readings inside it is marked uncertain: the agent may
	have left and come back."""
	stops, cluster, sum_lat, sum_lng = [], [], 0.0, 0.0
	for point in points:
		if cluster:
			center = frappe._dict(lat=sum_lat / len(cluster), lng=sum_lng / len(cluster))
			if distance_m(center, point) > radius_m:
				add_stop(stops, cluster, min_dwell_seconds, gap_seconds)
				cluster, sum_lat, sum_lng = [], 0.0, 0.0
		cluster.append(point)
		sum_lat += point.lat
		sum_lng += point.lng
	add_stop(stops, cluster, min_dwell_seconds, gap_seconds)
	return stops


def add_stop(stops: list, cluster: list, min_dwell_seconds: float, gap_seconds: float) -> None:
	if len(cluster) < 2:
		return
	seconds = seconds_between(cluster[0], cluster[-1])
	if seconds < min_dwell_seconds:
		return
	stops.append(
		frappe._dict(
			lat=sum(point.lat for point in cluster) / len(cluster),
			lng=sum(point.lng for point in cluster) / len(cluster),
			arrival=cluster[0].t,
			departure=cluster[-1].t,
			seconds=seconds,
			readings=len(cluster),
			uncertain=any(seconds_between(a, b) > gap_seconds for a, b in pairwise(cluster)),
		)
	)


def summarize_day(day, logs: list, settings, attendance_hours: float | None = None) -> frappe._dict:
	"""The route and daily figures for one tracking day. Attendance time, time covered by readings
	and time at stops are reported separately because they measure different things."""
	gap_seconds = cint(settings.tracking_gap_minutes) * 60
	points = drop_spikes(route_points(logs))
	segments = split_segments(points, gap_seconds)
	stops = detect_stops(
		points, flt(settings.stop_radius_meters), cint(settings.stop_min_dwell_minutes) * 60, gap_seconds
	)
	gaps = find_gaps(points, gap_seconds)
	checked_in_seconds = (
		(get_datetime(day.checkout_time) - get_datetime(day.checkin_time)).total_seconds()
		if day.checkin_time and day.checkout_time
		else None
	)

	return frappe._dict(
		segments=segments,
		stops=stops,
		gaps=gaps,
		metrics=frappe._dict(
			checked_in_seconds=checked_in_seconds,
			attendance_hours=attendance_hours,
			observed_seconds=sum(seconds_between(segment[0], segment[-1]) for segment in segments),
			distance_m=sum(distance_m(a, b) for segment in segments for a, b in pairwise(segment)),
			valid_pings=len(points),
			low_accuracy_pings=sum(1 for log in logs if log.validation_status == "Low Accuracy"),
			resolved_tickets=len({log.ticket for log in logs if log.event_type == "Ticket Resolved"}),
			stop_count=len(stops),
			stop_seconds=sum(stop.seconds for stop in stops if not stop.uncertain),
			uncertain_stop_count=sum(1 for stop in stops if stop.uncertain),
			gap_count=len(gaps),
			gap_seconds=sum(gap.seconds for gap in gaps),
			first_ping_at=points[0].t if points else None,
			last_ping_at=points[-1].t if points else None,
		),
	)
