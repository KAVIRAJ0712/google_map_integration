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
	Stop: { color: "#d97706", label: "P" },
};

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
