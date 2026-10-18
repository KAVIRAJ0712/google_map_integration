### Google Map Integration

Location tracking and a route map for Frappe Helpdesk agents, tied to HRMS attendance.

An agent checks in through HRMS, starts tracking on the **Agent Tracking** page, and their browser
sends a GPS reading at a set interval until they stop or check out. When they resolve a ticket, the
app records where they were. Managers and HR see each agent's route, stops, ticket resolutions and
daily figures on a Google Map.

### Requirements

- Frappe and HRMS (with ERPNext) version 16, and Frappe Helpdesk. Built and tested against Frappe
  16.36, HRMS 16.50 and Helpdesk `develop` as of October 2026.
- HTTPS in production. Browsers only share location with secure pages (`localhost` is allowed for
  development).
- A Google Cloud project with billing enabled.

### Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app google_map_integration
bench build --app google_map_integration
```

### Google Cloud setup

1. Enable the **Maps JavaScript API**. For the optional estimated road route, also enable the
   **Routes API**. The legacy Directions API can no longer be enabled on new projects and is not used.
2. Create an API key and restrict it:
   - Application restriction: **Websites**, listing your site's URL (and `http://localhost:8000/*`
     for development).
   - API restriction: the Maps JavaScript API, plus the Routes API if you use the road route.

   The key is sent to the browser of users who may open the map, so these restrictions are what
   protect it.
3. Create a **Map ID** (Map Management). Markers need one; `DEMO_MAP_ID` works for development only.

Each map load is billed as a Dynamic Maps event, and road routes as Routes API requests. Google gives
a free monthly allowance per product; check the current price list before rolling out widely.

### Configuration

1. **Google Maps Settings** (`/desk/google-maps-settings`): turn it on, add the key and Map ID, and
   set the tracking interval, accuracy limit, gap and grace times, stop detection, retention period
   and the notice agents read before tracking. **Preview Map** checks the key in your browser.
2. **HD Team** (`/desk/hd-team/<team>`): each team has its own switches for the map and for tracking,
   and can set its own interval. Agents are tracked only on teams with both switches on, so every
   tracked day shows on the map. Only Agent Managers and System Managers can change them.
3. **HRMS**: each tracked agent needs an active Employee linked to their user. Use Shift Types set to
   "Strictly based on Log Type in Employee Checkin" for tracked staff, so check-in and check-out are
   always known.

Agents open the app from Helpdesk's sidebar (**Apps → Agent Tracking**) or at `/agent-tracking`.

### How tracking works

1. An HRMS check-in opens the agent's tracking window for that shift, creates their
   **Agent Daily Tracking** record and starts tracking. A night shift belongs to the day it starts,
   as in HRMS. Agents can check in on the Agent Tracking page itself, which creates the HRMS check-in
   with the phone's location, when HR Settings allow check-ins from an app.
2. While the Agent Tracking page is open on the agent's device, it sends a reading every interval,
   with no button to press. The first time on a device, the browser asks for location permission.
   Tracking runs until check-out; agents cannot pause it. If the page is open on two devices, one
   sends the readings and the other offers to take over.
3. Readings are sent also when the device stands still, and kept on the device while offline. Each
   reading is an **Agent Location Log**. Duplicates are ignored, readings closer together than half
   the interval are dropped, and imprecise ones are kept but marked Low Accuracy. A blocked browser
   permission marks the day Interrupted with that reason.
4. When a tracked agent resolves a ticket, a Ticket Resolved event records the last reading of the
   last few minutes, labelled with its age, or "Unavailable". If the tracker page is open, it reads a
   fresh location and attaches it within 5 minutes. The ticket's own resolution time is stored
   separately from when the location was read.
5. The HRMS check-out ends tracking. Scheduled jobs mark a session Interrupted when readings stop,
   including when an agent checks in but never opens the page, and close a day as Missing Checkout
   when the shift ends without a check-out; a late check-out still completes it.

Location tracking never blocks attendance or ticket resolution: if it fails, the error is logged and
the check-in or ticket saves as usual.

### Who sees what

| Role | Sees |
|---|---|
| Agent | Their own tracking, on teams with the map turned on |
| Agent Manager, HR Manager, HR User, System Manager | Every agent of teams with the map turned on |
| Customers and other users | Nothing |

Tracking records are written only by the app. Location logs can never be edited.

### Privacy

- The Agent Tracking page shows the notice the first time an agent opens it on a device, and again
  when the notice changes. Which version an agent saw is remembered on the device, not stored.
- Location is only collected between check-in and check-out, while the Agent Tracking page is open.
- A daily job deletes location logs and closed tracking days older than the retention period.
- Employee location is personal data. Agree the notice and retention period with HR and, where
  needed, legal counsel before going live.

### Known limits

- Phones can pause a web page's location when the screen is off or the browser is in the background.
  Readings resume when the agent returns to the page, and the gap is shown on the map. Reliable
  background tracking needs a native mobile app.
- Coordinates come from the device and can be faked, as with any browser location.
- Distances and stop times are estimates from readings taken at the set interval.

### Development

```bash
# frontend
cd apps/google_map_integration/frontend
yarn install
yarn dev     # dev server, proxied to the bench
yarn build   # writes public/frontend and www/agent-tracking.html
```

This app uses `pre-commit` for formatting and linting (ruff, eslint, prettier):

```bash
cd apps/google_map_integration
pre-commit install
```

### License

mit
