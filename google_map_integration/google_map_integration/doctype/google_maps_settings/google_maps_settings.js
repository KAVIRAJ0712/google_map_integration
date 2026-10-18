// Copyright (c) 2026, Kaviraj and contributors
// For license information, please see license.txt

const MAPS_LOADED_CALLBACK = "__google_map_integration_loaded";
const WORLD_VIEW = { center: { lat: 0, lng: 0 }, zoom: 2 };
let maps_loader = null;
let loaded_key = null;
let error_target = null;

frappe.ui.form.on("Google Maps Settings", {
	refresh(frm) {
		if (frm.doc.enabled) {
			frm.add_custom_button(__("Preview Map"), () => preview_map(frm));
		}
	},
});

function preview_map(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the settings before previewing the map."));
		return;
	}
	frappe.call({
		method: "google_map_integration.google_map_integration.doctype.google_maps_settings.google_maps_settings.get_preview_options",
		type: "GET",
		callback: (r) => r.message && show_preview(r.message),
	});
}

async function show_preview(options) {
	const dialog = new frappe.ui.Dialog({
		title: __("Map Preview"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "map_html" }],
	});
	const container = $('<div style="height: 420px"></div>');
	dialog.fields_dict.map_html.$wrapper.empty().append(container);
	dialog.show();
	error_target = container;

	try {
		await load_google_maps(options.api_key);
		const { Map } = await google.maps.importLibrary("maps");
		const { AdvancedMarkerElement } = await google.maps.importLibrary("marker");
		const center = options.default_center || WORLD_VIEW.center;
		const map = new Map(container[0], {
			center,
			zoom: options.default_center ? options.default_zoom : WORLD_VIEW.zoom,
			mapId: options.map_id,
			mapTypeId: options.map_type,
		});
		if (options.default_center) {
			new AdvancedMarkerElement({ map, position: center, title: __("Default location") });
		}
	} catch (error) {
		show_map_error(error.message);
	}
}

function load_google_maps(api_key) {
	if (!maps_loader && window.google?.maps?.importLibrary) {
		return Promise.resolve();
	}
	if (loaded_key && loaded_key !== api_key) {
		return Promise.reject(
			new Error(__("The API key has changed. Reload the page to preview the new key."))
		);
	}
	if (!maps_loader) {
		loaded_key = api_key;
		maps_loader = new Promise((resolve, reject) => {
			window[MAPS_LOADED_CALLBACK] = resolve;
			// Google calls this global when it rejects the key, for example for an unlisted website
			window.gm_authFailure = () =>
				show_map_error(
					__(
						"Google rejected the API key. In Google Cloud, check that the key allows {0} and the Maps JavaScript API, and that billing is enabled.",
						[window.location.origin]
					)
				);
			const params = new URLSearchParams({
				key: api_key,
				v: "weekly",
				loading: "async",
				callback: MAPS_LOADED_CALLBACK,
			});
			const script = document.createElement("script");
			script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
			script.async = true;
			script.onerror = () => {
				maps_loader = null;
				loaded_key = null;
				script.remove();
				reject(new Error(__("Could not load Google Maps. Check the network connection.")));
			};
			document.head.appendChild(script);
		});
	}
	return maps_loader;
}

function show_map_error(message) {
	error_target?.html(
		`<div class="text-danger" style="padding: var(--padding-md)">${frappe.utils.escape_html(
			message
		)}</div>`
	);
}
