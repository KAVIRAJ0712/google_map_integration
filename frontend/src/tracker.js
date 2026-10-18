// The agent's side of location tracking: browser permission, GPS readings, an offline queue and
// sending readings to the server. Tracking runs from the HRMS check-in to the check-out, and this
// page sends readings whenever it is open in that time, without being asked. What the page shows
// comes from what the server has received, so it never claims tracking works while readings are
// not arriving.

import { computed, onBeforeUnmount, reactive } from "vue";
import { get, post } from "./api";

const API = "google_map_integration.api.tracking";
const BATCH_SIZE = 50;
const QUEUE_PREFIX = `google-map-integration:queue:${window.session_user}:`;
const NOTICE_KEY = `google-map-integration:notice:${window.session_user}`;

export function useTracker() {
	const state = reactive({
		loading: true,
		status: null,
		error: "",
		gpsWarning: "",
		permission: "unknown",
		watching: false,
		busy: false,
		sending: false,
		lastFix: null,
		serverOffset: 0,
		queue: [],
		keepAwake: false,
		noticeSeen: readNoticeSeen(),
	});
	let watchId = null;
	let tickTimer = null;
	let statusTimer = null;
	let lastQueuedAt = 0;
	let wakeLock = null;
	let starting = false;
	const handledCaptures = new Set();

	const tracking = computed(() => state.status?.tracking || null);
	const day = computed(() => state.status?.day || null);
	const sessionId = computed(() => day.value?.session_id || null);
	const otherDevice = computed(() => Boolean(state.status?.other_device));
	const intervalMs = computed(() => (tracking.value?.interval_seconds || 60) * 1000);
	const noticeAcknowledged = computed(() => state.noticeSeen >= (tracking.value?.notice_version || 0));
	const serverNow = () => Date.now() + state.serverOffset;
	const health = computed(() => {
		if (!sessionId.value) return "off";
		const last = day.value.last_location_at;
		if (!last) return "waiting";
		return serverNow() - last > intervalMs.value * 2 ? "stale" : "ok";
	});

	async function refresh() {
		try {
			applyStatus(await get(`${API}.get_tracking_status`));
			state.error = "";
		} catch (error) {
			state.error = error.message;
		} finally {
			state.loading = false;
		}
		await reconcile();
		await sendCaptures(state.status?.capture_requests || []);
	}

	function applyStatus(status) {
		state.status = status;
		state.serverOffset = status.server_time - Date.now();
		loadQueue();
	}

	// Bring this page in line with the server: send readings whenever tracking runs and this is the
	// device sending them
	async function reconcile() {
		if (state.permission === "denied" && sessionId.value && !otherDevice.value) await reportBlocked();
		if (!tracking.value?.enabled || state.permission !== "granted" || otherDevice.value) {
			return stopWatching();
		}
		if (!sessionId.value && state.status.can_start) await startSession();
		if (sessionId.value && !state.watching) startWatching();
		if (!sessionId.value && state.watching) stopWatching();
	}

	// A check-in starts tracking on the server. The server says when the page has to start it
	// instead: an open window without a session, or a site that does not require a check-in.
	async function startSession() {
		if (starting) return;
		starting = true;
		try {
			applyStatus(await post(`${API}.start_tracking`));
			lastQueuedAt = 0;
		} catch (error) {
			state.error = error.message;
		} finally {
			starting = false;
		}
	}

	async function reportBlocked() {
		if (day.value.interruption_reason === "Location Permission Denied") return;
		try {
			const result = await post(`${API}.report_location_blocked`, { session_id: sessionId.value });
			if (result.reported) {
				day.value.status = result.status;
				day.value.interruption_reason = "Location Permission Denied";
			}
		} catch {
			// the server marks the session interrupted when readings stop anyway
		}
	}

	async function checkPermission() {
		if (!window.isSecureContext) return (state.permission = "insecure");
		if (!("geolocation" in navigator)) return (state.permission = "unsupported");
		try {
			const result = await navigator.permissions.query({ name: "geolocation" });
			state.permission = result.state;
			result.onchange = () => {
				state.permission = result.state;
				if (result.state === "denied") onPermissionDenied();
				else reconcile();
			};
		} catch {
			state.permission = "prompt"; // browsers without the Permissions API ask on the first reading
		}
	}

	// The agent's taps. The first tap on a device is also when the browser asks for location.
	async function allowLocation() {
		state.busy = true;
		state.error = "";
		try {
			const fix = await readLocation();
			state.permission = "granted";
			await reconcile();
			acceptFix(fix);
		} catch (error) {
			handleLocationError(error);
			await reconcile();
		} finally {
			state.busy = false;
		}
	}

	async function checkIn(logType) {
		state.busy = true;
		state.error = "";
		let fix = null;
		try {
			fix = await readLocation(30000);
			state.permission = "granted";
		} catch (error) {
			// HRMS decides whether a check-in needs a location, so try without one
			handleLocationError(error);
		}
		try {
			if (logType === "OUT") await flush();
			const point = fix ? toPoint(fix) : null;
			applyStatus(await post(`${API}.check_in`, { log_type: logType, point }));
			await reconcile();
			if (fix) acceptFix(fix);
		} catch (error) {
			state.error = error.message;
		} finally {
			state.busy = false;
		}
	}

	async function takeOver() {
		state.busy = true;
		state.error = "";
		try {
			applyStatus(await post(`${API}.take_over_tracking`));
			await reconcile();
		} catch (error) {
			state.error = error.message;
		} finally {
			state.busy = false;
		}
	}

	function acknowledgeNotice() {
		state.noticeSeen = tracking.value?.notice_version || 0;
		try {
			localStorage.setItem(NOTICE_KEY, String(state.noticeSeen));
		} catch {
			// private browsing: the notice shows again next time
		}
	}

	async function onPermissionDenied() {
		handleLocationError({ code: 1 });
		await reconcile();
	}

	function handleLocationError(error) {
		if (error?.code === 1) {
			state.permission = "denied";
			stopWatching();
		} else {
			state.gpsWarning = geolocationMessage(error) || error?.message || "";
		}
	}

	function startWatching() {
		if (state.watching || !navigator.geolocation) return;
		watchId = navigator.geolocation.watchPosition(acceptFix, onWatchError, {
			enableHighAccuracy: true,
			maximumAge: 10000,
			timeout: 60000,
		});
		state.watching = true;
		tickTimer = setInterval(tick, 15000);
		if (state.keepAwake) requestWakeLock();
	}

	function stopWatching() {
		if (watchId !== null) navigator.geolocation.clearWatch(watchId);
		watchId = null;
		state.watching = false;
		clearInterval(tickTimer);
		tickTimer = null;
		releaseWakeLock();
	}

	function onWatchError(error) {
		if (error.code === 1) onPermissionDenied();
		else state.gpsWarning = geolocationMessage(error);
	}

	// Browsers only report movement, so a device standing still is read again every interval
	async function tick() {
		if (!sessionId.value) return;
		if (Date.now() - lastQueuedAt >= intervalMs.value) {
			try {
				acceptFix(await readLocation());
			} catch (error) {
				if (error.code === 1) return onPermissionDenied();
				state.gpsWarning = geolocationMessage(error);
			}
		}
		flush();
	}

	function acceptFix(position) {
		state.lastFix = position;
		state.gpsWarning = "";
		if (!sessionId.value || position.timestamp - lastQueuedAt < intervalMs.value * 0.9) return;
		lastQueuedAt = position.timestamp;
		state.queue.push(toPoint(position));
		saveQueue();
		flush();
	}

	async function flush() {
		if (state.sending || !state.queue.length || !sessionId.value || !navigator.onLine) return;
		state.sending = true;
		const batch = state.queue.slice(0, BATCH_SIZE);
		try {
			const result = await post(`${API}.submit_locations`, {
				session_id: sessionId.value,
				points: batch,
			});
			if (result.other_device) {
				// another device sends the readings, and this one's would only be refused
				state.queue = [];
				saveQueue();
				state.status.other_device = true;
				stopWatching();
				return;
			}
			// every reading in the batch got a final answer: stored, duplicate, too close or rejected
			state.queue.splice(0, batch.length);
			saveQueue();
			if (!result.session_active) {
				stopWatching();
				await refresh();
				return;
			}
			day.value.status = result.status;
			if (result.accepted) {
				day.value.last_location_at = Math.max(...batch.map((point) => point.recorded_at));
			}
			state.serverOffset = result.server_time - Date.now();
			state.gpsWarning = result.rejected?.length
				? `${result.rejected.length} reading(s) not accepted: ${result.rejected[0].reason}`
				: "";
			state.error = "";
			await sendCaptures(result.capture_requests || []);
		} catch (error) {
			state.error = error.status
				? error.message
				: "Offline. Readings are kept on this device and sent when the connection returns.";
		} finally {
			state.sending = false;
		}
		if (state.queue.length && navigator.onLine) setTimeout(flush, 1000);
	}

	// A ticket was just resolved: attach a location read now, labelled with its own time
	async function sendCaptures(requests) {
		const pending = requests.filter((request) => !handledCaptures.has(request.event));
		if (!pending.length || state.permission !== "granted") return;
		pending.forEach((request) => handledCaptures.add(request.event));
		try {
			const point = toPoint(await readLocation(15000));
			for (const request of pending) {
				await post(`${API}.attach_resolution_location`, { event: request.event, point });
			}
		} catch {
			// the resolution keeps its last known or unavailable location
		}
	}

	function readLocation(maximumAge = 5000) {
		return new Promise((resolve, reject) =>
			navigator.geolocation.getCurrentPosition(resolve, reject, {
				enableHighAccuracy: true,
				timeout: 30000,
				maximumAge,
			})
		);
	}

	function queueKey() {
		return sessionId.value ? QUEUE_PREFIX + sessionId.value : null;
	}

	function loadQueue() {
		const key = queueKey();
		try {
			state.queue = key ? JSON.parse(localStorage.getItem(key) || "[]") : [];
			// readings of ended sessions can no longer be sent
			for (const stored of Object.keys(localStorage)) {
				if (stored.startsWith(QUEUE_PREFIX) && stored !== key) localStorage.removeItem(stored);
			}
		} catch {
			state.queue = state.queue || [];
		}
	}

	function saveQueue() {
		const key = queueKey();
		try {
			if (key) localStorage.setItem(key, JSON.stringify(state.queue));
		} catch {
			// private browsing: the queue lives in memory only
		}
	}

	async function setKeepAwake(on) {
		state.keepAwake = on;
		if (on && state.watching) await requestWakeLock();
		else await releaseWakeLock();
	}

	async function requestWakeLock() {
		try {
			wakeLock = await navigator.wakeLock?.request("screen");
		} catch {
			wakeLock = null;
		}
	}

	async function releaseWakeLock() {
		await wakeLock?.release().catch(() => {});
		wakeLock = null;
	}

	function onVisibilityChange() {
		if (document.visibilityState !== "visible") return;
		refresh();
		flush();
		if (state.keepAwake && state.watching) requestWakeLock();
	}

	async function init() {
		await checkPermission();
		await refresh();
		document.addEventListener("visibilitychange", onVisibilityChange);
		window.addEventListener("online", flush);
		statusTimer = setInterval(refresh, 60000);
	}

	onBeforeUnmount(() => {
		stopWatching();
		clearInterval(statusTimer);
		document.removeEventListener("visibilitychange", onVisibilityChange);
		window.removeEventListener("online", flush);
	});

	init();
	return {
		state,
		day,
		sessionId,
		otherDevice,
		intervalMs,
		health,
		noticeAcknowledged,
		serverNow,
		checkIn,
		allowLocation,
		takeOver,
		acknowledgeNotice,
		refresh,
		setKeepAwake,
	};
}

function readNoticeSeen() {
	try {
		return Number(localStorage.getItem(NOTICE_KEY)) || 0;
	} catch {
		return 0;
	}
}

function toPoint(position) {
	return {
		client_event_id: crypto.randomUUID(),
		latitude: position.coords.latitude,
		longitude: position.coords.longitude,
		accuracy: position.coords.accuracy,
		recorded_at: position.timestamp,
	};
}

function geolocationMessage(error) {
	switch (error?.code) {
		case 1:
			return "Location access is blocked for this site. Allow it in your browser's site settings.";
		case 2:
			return "Your device cannot find its location right now. Check that GPS or location services are on.";
		case 3:
			return "Reading your location is taking too long. Tracking keeps trying.";
		default:
			return "";
	}
}
