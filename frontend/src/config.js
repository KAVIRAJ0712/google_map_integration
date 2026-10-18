// The user's map and tracking configuration, loaded once per page.

import { reactive } from "vue";
import { get } from "./api";

export const config = reactive({ loaded: false, data: null, error: "" });

let loading = null;

export function loadConfig() {
	loading ||= get("google_map_integration.api.config.get_maps_config")
		.then((data) => (config.data = data))
		.catch((error) => (config.error = error.message))
		.finally(() => (config.loaded = true));
	return loading;
}
