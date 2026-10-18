// Replays a day's recorded route. Across a gap in readings the marker waits at the last reading
// instead of moving through time the route has no data for.

import { computed, onBeforeUnmount, ref, watch } from "vue";

export function usePlayback(segments) {
	const playing = ref(false);
	const speed = ref(60);
	const time = ref(0);
	let frame = null;
	let lastFrameAt = 0;

	const points = computed(() =>
		segments.value.flatMap((segment, index) => segment.map((point) => ({ ...point, segment: index })))
	);
	const start = computed(() => points.value[0]?.t || 0);
	const end = computed(() => points.value.at(-1)?.t || 0);
	const position = computed(() => locate(points.value, time.value));

	function play() {
		if (!points.value.length) return;
		if (time.value >= end.value) time.value = start.value;
		playing.value = true;
		lastFrameAt = performance.now();
		frame = requestAnimationFrame(step);
	}

	function pause() {
		playing.value = false;
		cancelAnimationFrame(frame);
	}

	function seek(value) {
		time.value = Math.min(Math.max(Number(value), start.value), end.value);
	}

	function step(now) {
		time.value = Math.min(end.value, time.value + (now - lastFrameAt) * speed.value);
		lastFrameAt = now;
		if (time.value >= end.value) return pause();
		frame = requestAnimationFrame(step);
	}

	watch(points, () => {
		pause();
		time.value = start.value;
	});
	onBeforeUnmount(pause);

	return { playing, speed, time, start, end, position, play, pause, seek };
}

// Where the agent was at time `t`: between two readings of a segment, or held at the last reading
// when `t` falls in a gap
export function locate(points, t) {
	if (!points.length) return null;
	if (t <= points[0].t) return { lat: points[0].lat, lng: points[0].lng, gap: false };
	for (let i = 1; i < points.length; i++) {
		const [a, b] = [points[i - 1], points[i]];
		if (t > b.t) continue;
		if (a.segment !== b.segment) return { lat: a.lat, lng: a.lng, gap: true };
		const fraction = (t - a.t) / (b.t - a.t || 1);
		return { lat: a.lat + (b.lat - a.lat) * fraction, lng: a.lng + (b.lng - a.lng) * fraction, gap: false };
	}
	const last = points.at(-1);
	return { lat: last.lat, lng: last.lng, gap: false };
}
