// Times arrive as milliseconds since 1970 and are shown in the site's timezone, the same one HRMS
// uses for check-ins.

const timeZone = window.timezone || undefined;

export function formatTime(ms) {
	if (!ms) return "";
	return new Intl.DateTimeFormat(undefined, { timeZone, hour: "2-digit", minute: "2-digit" }).format(ms);
}

export function formatDateTime(ms) {
	if (!ms) return "";
	return new Intl.DateTimeFormat(undefined, {
		timeZone,
		day: "numeric",
		month: "short",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	}).format(ms);
}

export function formatDuration(seconds) {
	if (seconds === null || seconds === undefined) return "–";
	const total = Math.round(seconds);
	if (total < 60) return `${total} s`;
	const hours = Math.floor(total / 3600);
	const minutes = Math.floor((total % 3600) / 60);
	return hours ? `${hours} h ${minutes} min` : `${minutes} min`;
}

export function formatDistance(meters) {
	if (!meters) return "0 m";
	return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function timeAgo(ms, now = Date.now()) {
	if (!ms) return "never";
	const seconds = Math.max(0, Math.round((now - ms) / 1000));
	return seconds < 60 ? "just now" : `${formatDuration(seconds)} ago`;
}

export function today() {
	return new Intl.DateTimeFormat("en-CA", { timeZone }).format(Date.now());
}
