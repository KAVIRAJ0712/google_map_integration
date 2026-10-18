<template>
	<div class="flex h-screen flex-col bg-surface-gray-1 text-ink-gray-9">
		<header class="flex items-center gap-4 border-b border-outline-gray-2 bg-surface-base px-4 py-2">
			<img src="/logo.svg" alt="" class="size-7 rounded-4" />
			<h1 class="text-base-semibold">Agent Tracking</h1>
			<nav class="flex gap-1 text-sm">
				<RouterLink
					v-if="config.data?.tracking?.enabled"
					:to="{ name: 'Tracker' }"
					class="rounded-4 px-2 py-1 text-ink-gray-7 hover:bg-surface-gray-2"
					active-class="bg-surface-gray-2 text-ink-gray-9"
				>
					My tracking
				</RouterLink>
				<RouterLink
					v-if="config.data?.map?.enabled"
					:to="{ name: 'Map' }"
					class="rounded-4 px-2 py-1 text-ink-gray-7 hover:bg-surface-gray-2"
					active-class="bg-surface-gray-2 text-ink-gray-9"
				>
					Map
				</RouterLink>
			</nav>
			<a href="/helpdesk" class="ml-auto text-sm text-ink-gray-6 hover:text-ink-gray-9">Back to Helpdesk</a>
		</header>
		<main class="min-h-0 flex-1 overflow-auto">
			<p v-if="config.error" class="notice-error m-4">{{ config.error }}</p>
			<div
				v-else-if="config.loaded && !config.data?.map?.enabled && !config.data?.tracking?.enabled"
				class="card m-4 max-w-xl"
			>
				<h2 class="mb-1 font-semibold">Not available</h2>
				<p class="text-sm text-ink-gray-7">
					{{ config.data?.tracking?.message || config.data?.map?.message }}
				</p>
			</div>
			<RouterView v-else-if="config.loaded" />
		</main>
	</div>
</template>

<script setup>
import { config } from "./config";
</script>
