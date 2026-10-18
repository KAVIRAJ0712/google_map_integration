<template>
	<div class="flex flex-col">
		<p v-if="loaded && !result.rows.length" class="p-4 text-sm text-ink-gray-6">
			No location logs match these filters.
		</p>
		<table v-else-if="result.rows.length" class="w-full text-left text-sm">
			<thead class="sticky top-0 bg-surface-gray-1 text-xs text-ink-gray-6">
				<tr>
					<th class="px-3 py-2 font-medium">Time</th>
					<th class="px-3 py-2 font-medium">Agent</th>
					<th class="px-3 py-2 font-medium">Event</th>
					<th class="px-3 py-2 font-medium">Location</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="row in result.rows"
					:key="row.name"
					class="cursor-pointer border-t border-outline-gray-1 hover:bg-surface-gray-1"
					@click="emit('focus', row)"
				>
					<td class="whitespace-nowrap px-3 py-2">{{ formatDateTime(row.recorded_at) }}</td>
					<td class="px-3 py-2">{{ result.agent_names[row.agent] || row.agent }}</td>
					<td class="px-3 py-2">
						{{ row.event_type }}
						<span v-if="row.ticket" class="text-ink-gray-6">#{{ row.ticket }}</span>
					</td>
					<td class="px-3 py-2">
						<span :class="row.location_status === 'Unavailable' ? 'text-ink-gray-5' : ''">
							{{ locationLabel(row) }}
						</span>
					</td>
				</tr>
			</tbody>
		</table>
		<div v-if="result.page > 1 || result.has_more" class="flex items-center justify-between p-3">
			<Button label="Previous" :disabled="result.page <= 1" @click="emit('page', result.page - 1)" />
			<span class="text-xs text-ink-gray-6">Page {{ result.page }}</span>
			<Button label="Next" :disabled="!result.has_more" @click="emit('page', result.page + 1)" />
		</div>
	</div>
</template>

<script setup>
import { Button } from "frappe-ui";
import { formatDateTime, formatDuration } from "@/format";

defineProps({
	result: { type: Object, required: true },
	loaded: { type: Boolean, default: false },
});
const emit = defineEmits(["page", "focus"]);

function locationLabel(row) {
	if (row.location_status === "Unavailable") return "Unavailable";
	const accuracy = row.accuracy_meters ? ` ±${Math.round(row.accuracy_meters)} m` : "";
	const low = row.validation_status === "Low Accuracy" ? ", low accuracy" : "";
	if (row.location_status === "Last Known") {
		return `Last known, ${formatDuration(row.location_age_seconds)} old${accuracy}`;
	}
	return `GPS${accuracy}${low}`;
}
</script>
