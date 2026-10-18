<template>
	<div class="flex flex-col gap-4 p-4 text-sm">
		<header>
			<h2 class="font-semibold">{{ summary.day.agent_name || summary.day.agent }}</h2>
			<p class="text-ink-gray-6">
				{{ summary.day.attendance_date }} · {{ summary.day.status }}
				<span v-if="summary.day.shift">· {{ summary.day.shift }}</span>
			</p>
			<p class="text-ink-gray-6">
				Check-in {{ formatTime(summary.day.checkin_time) || "–" }}, check-out
				{{ formatTime(summary.day.checkout_time) || "–" }}
			</p>
		</header>

		<dl class="grid grid-cols-2 gap-x-4 gap-y-2">
			<template v-for="item in figures" :key="item.label">
				<dt class="text-ink-gray-6">{{ item.label }}</dt>
				<dd>{{ item.value }}</dd>
			</template>
		</dl>
		<p class="text-xs text-ink-gray-6">
			Distance and stop times are estimates from GPS readings. Attendance comes from HRMS. A gap is
			time without readings, so the route is not drawn across it.
		</p>

		<section v-if="playback.end.value" class="flex flex-col gap-2 rounded-6 bg-surface-gray-1 p-3">
			<div class="flex items-center gap-2">
				<Button
					:label="playback.playing.value ? 'Pause' : 'Play route'"
					@click="playback.playing.value ? playback.pause() : playback.play()"
				/>
				<select v-model.number="playback.speed.value" class="field-input">
					<option :value="60">60×</option>
					<option :value="300">300×</option>
					<option :value="900">900×</option>
				</select>
				<span class="ml-auto tabular-nums">{{ formatTime(playback.time.value) }}</span>
			</div>
			<input
				type="range"
				class="w-full"
				:min="playback.start.value"
				:max="playback.end.value"
				:value="playback.time.value"
				@input="playback.seek($event.target.value)"
			/>
			<p v-if="playback.position.value?.gap" class="text-xs text-ink-amber-8">
				No readings at this time; the marker waits at the last known reading.
			</p>
		</section>

		<Button
			v-if="roadRouteAvailable && summary.segments.length"
			:label="roadRouteShown ? 'Hide estimated road route' : 'Show estimated road route'"
			@click="emit('toggle-road-route')"
		/>
		<p v-if="roadRouteShown" class="text-xs text-ink-gray-6">
			Dashed orange: a road route Google estimates through the stops. It is not the recorded path,
			which is the solid blue line.
		</p>

		<section>
			<h3 class="mb-2 font-semibold">Timeline</h3>
			<p v-if="!timeline.length" class="text-ink-gray-6">Nothing was recorded on this day.</p>
			<ol class="flex flex-col">
				<li
					v-for="item in timeline"
					:key="item.key"
					class="flex cursor-pointer gap-3 rounded-4 px-2 py-1.5 hover:bg-surface-gray-1"
					@click="item.focus && emit('focus', item.focus)"
				>
					<span class="w-12 shrink-0 tabular-nums text-ink-gray-6">{{ formatTime(item.time) }}</span>
					<span>
						{{ item.title }}
						<span v-if="item.detail" class="block text-xs text-ink-gray-6">{{ item.detail }}</span>
					</span>
				</li>
			</ol>
		</section>
	</div>
</template>

<script setup>
import { computed } from "vue";
import { Button } from "frappe-ui";
import { formatDistance, formatDuration, formatTime } from "@/format";

const props = defineProps({
	summary: { type: Object, required: true },
	playback: { type: Object, required: true },
	roadRouteAvailable: { type: Boolean, default: false },
	roadRouteShown: { type: Boolean, default: false },
});
const emit = defineEmits(["focus", "toggle-road-route"]);

const figures = computed(() => {
	const m = props.summary.metrics;
	return [
		{ label: "Checked in (HRMS times)", value: formatDuration(m.checked_in_seconds) },
		{
			label: "Attendance working hours",
			value: m.attendance_hours === null ? "Not marked yet" : `${m.attendance_hours} h`,
		},
		{ label: "Covered by GPS readings", value: formatDuration(m.observed_seconds) },
		{ label: "Approximate distance", value: formatDistance(m.distance_m) },
		{ label: "Valid readings", value: m.valid_pings },
		{ label: "Low accuracy readings", value: m.low_accuracy_pings },
		{ label: "Tickets resolved", value: m.resolved_tickets },
		{ label: "Estimated time at stops", value: formatDuration(m.stop_seconds) },
		{ label: "Uncertain stops", value: m.uncertain_stop_count },
		{ label: "Gaps in readings", value: `${m.gap_count} (${formatDuration(m.gap_seconds)})` },
	];
});

const timeline = computed(() => {
	const { events, stops, gaps } = props.summary;
	const items = [
		...events.map((event) => ({
			key: `event-${event.name}`,
			time: event.event_type === "Ticket Resolved" ? event.ticket_resolved_at : event.recorded_at,
			title: event.ticket ? `${event.event_type} #${event.ticket}` : event.event_type,
			detail: locationDetail(event),
			focus: event.latitude !== null ? event : null,
		})),
		...stops.map((stop, index) => ({
			key: `stop-${index}`,
			time: stop.arrival,
			title: `Stop ${index + 1}, about ${formatDuration(stop.seconds)}`,
			detail: stop.uncertain ? "Uncertain: readings are missing during this stop" : "",
			focus: stop,
		})),
		...gaps.map((gap, index) => ({
			key: `gap-${index}`,
			time: gap.start,
			title: `No readings for ${formatDuration(gap.seconds)}`,
			detail: "",
			focus: null,
		})),
	];
	return items.sort((a, b) => a.time - b.time);
});

function locationDetail(event) {
	if (event.location_status === "Unavailable") return "Location unavailable";
	if (event.location_status === "Last Known") {
		return `Last known location, ${formatDuration(event.location_age_seconds)} old`;
	}
	return event.note || "";
}
</script>
