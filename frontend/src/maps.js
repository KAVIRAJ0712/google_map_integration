// Loads the Google Maps JavaScript API once per page, with the browser key from the server.

const LOADED_CALLBACK = "__googleMapIntegrationLoaded";
let loader = null;
let authError = "";
const authListeners = new Set();

export function loadGoogleMaps(apiKey) {
	if (!loader && window.google?.maps?.importLibrary) return Promise.resolve();
	if (!loader) {
		loader = new Promise((resolve, reject) => {
			window[LOADED_CALLBACK] = resolve;
			// Google calls this global when it rejects the key, for example for an unlisted website
			window.gm_authFailure = () => {
				authError = `Google rejected the API key. In Google Cloud, check that the key allows ${window.location.origin} and the Maps JavaScript API, and that billing is enabled.`;
				authListeners.forEach((listener) => listener(authError));
			};
			const params = new URLSearchParams({
				key: apiKey,
				v: "weekly",
				loading: "async",
				callback: LOADED_CALLBACK,
			});
			const script = document.createElement("script");
			script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
			script.async = true;
			script.onerror = () => {
				loader = null;
				script.remove();
				reject(new Error("Could not load Google Maps. Check your connection."));
			};
			document.head.appendChild(script);
		});
	}
	return loader;
}

export function onMapsAuthFailure(listener) {
	authListeners.add(listener);
	if (authError) listener(authError);
	return () => authListeners.delete(listener);
}

export const EVENT_STYLES = {
	"Check-in": { color: "#16a34a", label: "In" },
	"Check-out": { color: "#4b5563", label: "Out" },
	"Ticket Resolved": { color: "#2563eb", label: "T" },
	"Location Ping": { color: "#0891b2", label: "" },
};

// Numbered stops of a day: the first green, the last red, the ones between grey
export const STOP_COLORS = { first: "#16a34a", middle: "#64748b", last: "#dc2626" };

// One colour per agent when several agents' routes share the map
export const ROUTE_COLORS = ["#2563eb", "#ea580c", "#9333ea", "#0d9488", "#db2777", "#ca8a04", "#4f46e5", "#65a30d"];

// A teardrop pin with a short label, its tip on the location
export function pinElement(text, color) {
	const element = document.createElement("div");
	element.style.cssText = "filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))";
	element.innerHTML = `<svg width="28" height="38" viewBox="0 0 28 38" aria-hidden="true"><path d="M14 1C6.8 1 1 6.7 1 13.8 1 23.5 14 37 14 37s13-13.5 13-23.2C27 6.7 21.2 1 14 1z" fill="${color}" stroke="#fff" stroke-width="2"/><text x="14" y="18" text-anchor="middle" fill="#fff" style="font:600 12px system-ui,sans-serif">${escapeHtml(text)}</text></svg>`;
	return element;
}

// Content for an AdvancedMarkerElement. Last known locations are drawn faded and dashed, so an
// earlier reading is never mistaken for one taken at the event.
export function markerElement(kind, { lastKnown = false, text = "" } = {}) {
	const style = EVENT_STYLES[kind] || EVENT_STYLES["Location Ping"];
	const element = document.createElement("div");
	if (kind === "Location Ping") {
		element.style.cssText = `width:10px;height:10px;border-radius:50%;background:${style.color};border:2px solid #fff;box-shadow:0 0 0 1px ${style.color}`;
		return element;
	}
	element.textContent = text || style.label;
	element.style.cssText = [
		"min-width:24px",
		"height:24px",
		"padding:0 6px",
		"border-radius:12px",
		`background:${style.color}`,
		"color:#fff",
		"font:600 11px/20px system-ui, sans-serif",
		"text-align:center",
		`border:2px ${lastKnown ? "dashed" : "solid"} #fff`,
		"box-shadow:0 1px 3px rgba(0,0,0,.35)",
		lastKnown ? "opacity:.6" : "",
	].join(";");
	return element;
}

export function escapeHtml(value) {
	return String(value ?? "").replace(
		/[&<>"']/g,
		(char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]
	);
}
