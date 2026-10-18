<template>
	<div class="flex h-full flex-col">
		<form
			class="flex flex-wrap items-end gap-3 border-b border-outline-gray-2 bg-surface-base p-3"
			@submit.prevent="load()"
		>
			<label v-if="options.can_view_all" class="field-label">
				Team
				<select v-model="filters.team" class="field-input">
					<option value="">All teams</option>
					<option v-for="team in options.teams" :key="team" :value="team">{{ team }}</option>
				</select>
			</label>
			<label class="field-label">
				Agent
				<select v-model="filters.agent" class="field-input" :disabled="!options.can_view_all">
					<option v-if="options.can_view_all" value="">All agents</option>
					<option v-for="agent in options.agents" :key="agent.value" :value="agent.value">
						{{ agent.label }}
					</option>
				</select>
			</label>
			<label class="field-label">
				From
				<input v-model="filters.from_date" type="date" class="field-input" />
			</label>
			<label class="field-label">
				To
				<input v-model="filters.to_date" type="date" class="field-input" />
			</label>
			<label class="field-label">
				Event
				<select v-model="filters.event_type" class="field-input">
					<option value="">All events</option>
					<option v-for="type in options.event_types" :key="type" :value="type">{{ type }}</option>
				</select>
			</label>
			<label class="field-label">
				Ticket
				<input v-model.trim="filters.ticket" class="field-input w-24" placeholder="ID" />
			</label>
			<label class="field-label">
				Tracking day
				<select v-model="filters.daily_tracking" class="field-input" :disabled="!days.length">
					<option value="">{{ days.length ? "Choose a day for its route" : "Choose an agent" }}</option>
					<option v-for="day in days" :key="day.name" :value="day.name">
						{{ day.attendance_date }} · {{ day.status }}
					</option>
				</select>
			</label>
			<label class="flex h-8 items-center gap-1 text-sm text-ink-gray-7">
				<input v-model="filters.include_low_accuracy" type="checkbox" />
				Low accuracy
			</label>
			<Button type="submit" variant="solid" label="Show" :loading="loading" />
		</form>

		<p v-if="error" class="notice-error m-3">{{ error }}</p>

		<div class="flex min-h-0 flex-1 flex-col lg:flex-row">
			<div class="relative min-h-[360px] flex-1">
				<div ref="mapElement" class="absolute inset-0" />
				<p v-if="mapError" class="notice-error absolute inset-x-3 top-3">{{ mapError }}</p>
			</div>
			<aside
				class="max-h-[50vh] w-full overflow-y-auto border-outline-gray-2 bg-surface-base lg:max-h-none lg:w-[26rem] lg:border-l"
			>
				<DayPanel
					v-if="summary"
					:summary="summary"
					:playback="playback"
					:road-route-available="Boolean(config.data?.map?.show_estimated_road_route)"
					:road-route-shown="roadRouteShown"
					@focus="focus"
					@toggle-road-route="toggleRoadRoute"
				/>
				<LogTable
					v-else
					:result="logs"
					:loaded="logsLoaded"
					@page="load"
					@focus="(row) => focus(row, logHtml(row))"
				/>
			</aside>
		</div>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { Button } from "frappe-ui";
import { get } from "@/api";
import { config } from "@/config";
import { formatDateTime, formatDuration, today } from "@/format";
import { escapeHtml, loadGoogleMaps, markerElement, onMapsAuthFailure } from "@/maps";
import { usePlayback } from "@/playback";
import DayPanel from "@/components/DayPanel.vue";
import LogTable from "@/components/LogTable.vue";

const API = "google_map_integration.api.history";
const mapElement = ref(null);
const options = ref({ teams: [], agents: [], event_types: [], can_view_all: false });
const filters = reactive({
	team: "",
	agent: "",
	from_date: today(),
	to_date: today(),
	event_type: "",
	ticket: "",
	daily_tracking: "",
	include_low_accuracy: true,
});
const days = ref([]);
const logs = ref({ rows: [], page: 1, has_more: false, agent_names: {} });
const logsLoaded = ref(false);
const summary = ref(null);
const loading = ref(false);
const error = ref("");
const mapError = ref("");
const roadRouteShown = ref(false);
const playback = usePlayback(computed(() => summary.value?.segments || []));

let maps = null;
let map = null;
let infoWindow = null;
let overlays = [];
let roadRoute = [];
let playbackMarker = null;
const stopListening = onMapsAuthFailure((message) => (mapError.value = message));

onMounted(async () => {
	await Promise.all([initMap(), loadOptions()]);
	await load();
});
onBeforeUnmount(stopListening);

async function initMap() {
	const settings = config.data?.map;
	try {
		await loadGoogleMaps(settings.api_key);
		const [core, mapsLibrary, marker] = await Promise.all([
			google.maps.importLibrary("core"),
			google.maps.importLibrary("maps"),
			google.maps.importLibrary("marker"),
		]);
		maps = { ...core, ...mapsLibrary, ...marker };
		map = new maps.Map(mapElement.value, {
			center: settings.default_center || { lat: 0, lng: 0 },
			zoom: settings.default_center ? settings.default_zoom : 2,
			mapId: settings.map_id,
			mapTypeId: settings.map_type,
			streetViewControl: false,
		});
		infoWindow = new maps.InfoWindow();
	} catch (e) {
		mapError.value = e.message;
	}
}

async function loadOptions() {
	try {
		options.value = await get(`${API}.get_filter_options`);
		if (!options.value.can_view_all) filters.agent = options.value.agents[0]?.value || "";
	} catch (e) {
		error.value = e.message;
	}
}

watch(() => [filters.agent, filters.from_date, filters.to_date], loadDays);

async function loadDays() {
	filters.daily_tracking = "";
	days.value = [];
	if (!filters.agent || !filters.from_date || !filters.to_date) return;
	try {
		days.value = await get(`${API}.get_tracking_days`, {
			agent: filters.agent,
			from_date: filters.from_date,
			to_date: filters.to_date,
		});
	} catch (e) {
		error.value = e.message;
	}
}

async function load(page = 1) {
	loading.value = true;
	error.value = "";
	try {
		if (filters.daily_tracking) {
			summary.value = await get(`${API}.get_day_summary`, { daily_tracking: filters.daily_tracking });
			drawDay();
		} else {
			summary.value = null;
			const { daily_tracking, ...rest } = filters;
			logs.value = await get(`${API}.get_location_logs`, { ...rest, page, page_length: 200 });
			logsLoaded.value = true;
			drawLogs();
		}
	} catch (e) {
		error.value = e.message;
	} finally {
		loading.value = false;
	}
}

function drawLogs() {
	if (!map) return;
	clearMap();
	const located = logs.value.rows.filter((row) => row.latitude !== null);
	for (const row of located) {
		addMarker(position(row), row.event_type, {
			lastKnown: row.location_status === "Last Known",
			html: logHtml(row),
			zIndex: row.event_type === "Location Ping" ? 1 : 10,
		});
	}
	fit(located.map(position));
}

function drawDay() {
	if (!map) return;
	clearMap();
	const { segments, stops, events } = summary.value;
	for (const segment of segments) {
		const line = new maps.Polyline({
			map,
			path: segment.map(position),
			strokeColor: "#2563eb",
			strokeOpacity: 0.85,
			strokeWeight: 4,
		});
		overlays.push(() => line.setMap(null));
	}
	stops.forEach((stop, index) =>
		addMarker(position(stop), "Stop", { text: String(index + 1), html: stopHtml(stop, index), zIndex: 20 })
	);
	const located = events.filter((event) => event.latitude !== null);
	for (const event of located) {
		addMarker(position(event), event.event_type, {
			lastKnown: event.location_status === "Last Known",
			html: logHtml(event),
			zIndex: 30,
		});
	}
	const first = segments[0]?.[0];
	if (first) {
		const element = markerElement("Location Ping");
		element.style.cssText += ";width:16px;height:16px;background:#111827;box-shadow:0 0 0 2px #fff";
		playbackMarker = new maps.AdvancedMarkerElement({ map, position: position(first), content: element, zIndex: 40 });
		overlays.push(() => (playbackMarker.map = null));
	}
	fit([...segments.flat().map(position), ...located.map(position)]);
}

watch(
	() => playback.position.value,
	(point) => {
		if (playbackMarker && point) playbackMarker.position = { lat: point.lat, lng: point.lng };
	}
);

async function toggleRoadRoute() {
	if (roadRoute.length) return clearRoadRoute();
	const points = summary.value.segments.flat();
	if (points.length < 2) return;
	try {
		const { Route } = await google.maps.importLibrary("routes");
		const { routes } = await Route.computeRoutes({
			origin: position(points[0]),
			destination: position(points.at(-1)),
			intermediates: summary.value.stops.slice(0, 25).map((stop) => ({ location: position(stop) })),
			travelMode: "DRIVING",
			fields: ["path"],
		});
		if (!routes?.length) {
			error.value = "Google could not find a road route through this day's stops.";
			return;
		}
		roadRoute = routes[0].createPolylines({
			polylineOptions: {
				strokeOpacity: 0,
				icons: [
					{
						icon: { path: "M 0,-1 0,1", strokeOpacity: 0.9, strokeColor: "#ea580c", scale: 3 },
						offset: "0",
						repeat: "14px",
					},
				],
			},
		});
		roadRoute.forEach((line) => line.setMap(map));
		roadRouteShown.value = true;
	} catch (e) {
		error.value = `The estimated road route is unavailable: ${e.message}`;
	}
}

function clearRoadRoute() {
	roadRoute.forEach((line) => line.setMap(null));
	roadRoute = [];
	roadRouteShown.value = false;
}

function clearMap() {
	overlays.forEach((remove) => remove());
	overlays = [];
	playbackMarker = null;
	clearRoadRoute();
	infoWindow?.close();
}

function addMarker(at, kind, { lastKnown = false, text = "", html = "", zIndex = 1 } = {}) {
	const marker = new maps.AdvancedMarkerElement({
		map,
		position: at,
		content: markerElement(kind, { lastKnown, text }),
		title: kind,
		zIndex,
		gmpClickable: Boolean(html),
	});
	if (html) marker.addListener("click", () => openInfo(marker, html));
	overlays.push(() => (marker.map = null));
	return marker;
}

function openInfo(anchor, html) {
	infoWindow.setContent(html);
	infoWindow.open({ anchor, map });
}

function focus(item, html = "") {
	if (!map || item.latitude === null) return;
	map.panTo(position(item));
	map.setZoom(Math.max(map.getZoom(), 16));
	if (html) {
		infoWindow.setContent(html);
		infoWindow.setPosition(position(item));
		infoWindow.open({ map });
	}
}

function fit(points) {
	if (!points.length) return;
	const bounds = new maps.LatLngBounds();
	points.forEach((point) => bounds.extend(point));
	map.fitBounds(bounds, 48);
	if (points.length === 1) map.setZoom(16);
}

function position(item) {
	return { lat: item.lat ?? item.latitude, lng: item.lng ?? item.longitude };
}

function agentName(user) {
	return logs.value.agent_names?.[user] || summary.value?.day?.agent_name || user;
}

function logHtml(log) {
	const lines = [
		`<strong>${escapeHtml(log.event_type)}</strong>`,
		escapeHtml(agentName(log.agent)),
		formatDateTime(log.recorded_at),
	];
	if (log.location_status === "Last Known") {
		lines.push(`Last known location, read ${formatDuration(log.location_age_seconds)} before the event`);
	}
	if (log.accuracy_meters) {
		const low = log.validation_status === "Low Accuracy" ? " (low accuracy)" : "";
		lines.push(`Accuracy ±${Math.round(log.accuracy_meters)} m${low}`);
	}
	if (log.ticket) {
		const ticket = escapeHtml(log.ticket);
		lines.push(
			`<a href="/helpdesk/tickets/${encodeURIComponent(log.ticket)}" target="_blank" rel="noopener">Ticket #${ticket}</a>, resolved ${formatDateTime(log.ticket_resolved_at)}`
		);
	}
	if (log.note) lines.push(escapeHtml(log.note));
	return `<div style="font-size:13px;line-height:1.5">${lines.join("<br>")}</div>`;
}

function stopHtml(stop, index) {
	const certainty = stop.uncertain ? "<br>Uncertain: readings are missing during this stop" : "";
	return `<div style="font-size:13px;line-height:1.5"><strong>Stop ${index + 1}</strong><br>${formatDateTime(
		stop.arrival
	)} to ${formatDateTime(stop.departure)}<br>About ${formatDuration(stop.seconds)}${certainty}</div>`;
}
</script>
