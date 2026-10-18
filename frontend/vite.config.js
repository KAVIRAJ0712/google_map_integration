import path from "path";
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [
		frappeui({
			frappeProxy: true,
			jinjaBootData: true,
			// the code editor's languages are not used here, and their packages are not installed
			codeLanguages: false,
			buildConfig: {
				outDir: "../google_map_integration/public/frontend",
				emptyOutDir: true,
				indexHtmlPath: "../google_map_integration/www/agent-tracking.html",
			},
		}),
		vue(),
	],
	resolve: {
		alias: { "@": path.resolve(__dirname, "src") },
	},
});
