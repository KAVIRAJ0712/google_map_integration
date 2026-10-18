import { createRouter, createWebHistory } from "vue-router";
import { config, loadConfig } from "./config";

export const router = createRouter({
	history: createWebHistory("/agent-tracking"),
	routes: [
		{ path: "/", name: "Tracker", component: () => import("./pages/Tracker.vue") },
		{ path: "/map", name: "Map", component: () => import("./pages/LocationMap.vue") },
		{ path: "/:path(.*)*", redirect: "/" },
	],
});

// Agents who can only see the map land on it; nobody reaches a page their teams have turned off
router.beforeEach(async (to) => {
	await loadConfig();
	const mapEnabled = config.data?.map?.enabled;
	const trackingEnabled = config.data?.tracking?.enabled;
	if (to.name === "Map" && !mapEnabled) return { name: "Tracker" };
	if (to.name === "Tracker" && !trackingEnabled && mapEnabled) return { name: "Map" };
});
