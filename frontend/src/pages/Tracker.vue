<template>
	<div class="mx-auto flex max-w-2xl flex-col gap-4 p-4">
		<p v-if="state.loading" class="text-sm text-ink-gray-6">Loading…</p>
		<template v-else>
			<p v-if="state.error" class="notice-error">{{ state.error }}</p>

			<section v-if="!tracking?.enabled" class="card">
				<h2 class="mb-1 font-semibold">Location tracking is not available</h2>
				<p class="text-sm text-ink-gray-7">{{ tracking?.message }}</p>
			</section>

			<template v-else>
				<section v-if="!tracker.noticeAcknowledged.value" class="card flex flex-col gap-3">
					<h3 class="font-semibold">About location tracking</h3>
					<p class="whitespace-pre-line text-sm text-ink-gray-8">{{ tracking.notice }}</p>
					<Button label="Got it" class="self-start" @click="tracker.acknowledgeNotice()" />
				</section>

				<section class="card flex flex-col gap-3">
					<div class="flex items-center gap-2">
						<h2 class="font-semibold">Location tracking</h2>
						<Badge :label="badge.label" :theme="badge.theme" size="md" class="ml-auto" />
					</div>
					<p v-if="day" class="text-sm text-ink-gray-7">
						Checked in at {{ formatTime(day.checkin_time) || "–" }}
						<span v-if="day.shift">· {{ day.shift }} ends at {{ formatTime(day.shift_end) }}</span>
					</p>
					<p v-else-if="tracking.require_hrms_checkin" class="text-sm text-ink-gray-7">
						You are not checked in. Tracking starts when you check in{{
							status.can_check_in ? "" : " through HRMS"
						}}.
						<a v-if="!status.can_check_in && hasHrms" href="/hrms" class="text-ink-gray-9 underline">
							Open HRMS
						</a>
					</p>

					<dl v-if="state.watching" class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
						<dt class="text-ink-gray-6">Last location received</dt>
						<dd>{{ timeAgo(day.last_location_at, tracker.serverNow()) }}</dd>
						<dt class="text-ink-gray-6">Readings waiting to send</dt>
						<dd>{{ state.queue.length }}</dd>
						<dt class="text-ink-gray-6">GPS accuracy</dt>
						<dd>{{ state.lastFix ? `±${Math.round(state.lastFix.coords.accuracy)} m` : "–" }}</dd>
						<dt class="text-ink-gray-6">Interval</dt>
						<dd>every {{ tracking.interval_seconds }} seconds</dd>
					</dl>
					<p v-if="state.watching && tracker.health.value === 'stale'" class="notice-warning">
						No location has reached the server for
						{{ timeAgo(day.last_location_at, tracker.serverNow()).replace(" ago", "") }}. Keep this page
						open, and check your connection and location services.
					</p>
					<p v-if="state.gpsWarning" class="notice-warning">{{ state.gpsWarning }}</p>

					<template v-if="day">
						<div v-if="tracker.otherDevice.value" class="flex flex-col gap-2">
							<p class="text-sm text-ink-gray-7">
								Your location is being sent from another device where Agent Tracking is open.
							</p>
							<Button
								label="Track on this device"
								class="self-start"
								:loading="state.busy"
								@click="tracker.takeOver()"
							/>
						</div>
						<div v-else-if="state.permission === 'prompt'" class="flex flex-col gap-2">
							<p class="text-sm text-ink-gray-7">Allow location so this device can send it.</p>
							<Button
								variant="solid"
								label="Allow location"
								class="self-start"
								:loading="state.busy"
								@click="tracker.allowLocation()"
							/>
						</div>
					</template>

					<Button
						v-if="status.can_check_in"
						size="md"
						:variant="day ? 'subtle' : 'solid'"
						:label="day ? 'Check out' : 'Check in'"
						:loading="state.busy"
						@click="tracker.checkIn(day ? 'OUT' : 'IN')"
					/>

					<template v-if="day">
						<label v-if="wakeLockSupported && state.watching" class="flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								:checked="state.keepAwake"
								@change="tracker.setKeepAwake($event.target.checked)"
							/>
							Keep the screen on while tracking
						</label>
						<p class="text-xs text-ink-gray-6">
							Tracking runs until you check out. Keep this page open while you work: phones can pause
							location when the screen is off or the browser is in the background, and readings
							resume when you come back to this page.
						</p>
					</template>
				</section>

				<p v-if="permissionHelp" class="notice-error">{{ permissionHelp }}</p>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue";
import { Badge, Button } from "frappe-ui";
import { formatTime, timeAgo } from "@/format";
import { useTracker } from "@/tracker";

const tracker = useTracker();
const state = tracker.state;
const hasHrms = Boolean(window.has_hrms);
const wakeLockSupported = "wakeLock" in navigator;

const status = computed(() => state.status || {});
const tracking = computed(() => state.status?.tracking);
const day = computed(() => tracker.day.value);

const badge = computed(() => {
	if (!day.value) return { label: "Not checked in", theme: "gray" };
	if (tracker.otherDevice.value) return { label: "On another device", theme: "blue" };
	if (state.permission !== "granted") return { label: "Location needed", theme: "amber" };
	if (day.value.status === "Interrupted") return { label: "Interrupted", theme: "amber" };
	if (!tracker.sessionId.value) return { label: "Starting…", theme: "gray" };
	if (tracker.health.value === "stale") return { label: "No recent location", theme: "amber" };
	return { label: "Tracking", theme: "green" };
});

const permissionHelp = computed(() => {
	switch (state.permission) {
		case "insecure":
			return "Location only works on a secure (https) address. Ask your administrator for the https link.";
		case "unsupported":
			return "This browser cannot share your location.";
		case "denied":
			return "Location access is blocked for this site. Allow it in your browser's site settings, then reload this page. Your managers can see that location was blocked.";
		default:
			return "";
	}
});
</script>
