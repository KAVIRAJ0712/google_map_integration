// Calls to the app's whitelisted methods. The server takes the user from the session, so no
// request carries a user, employee or team.

export class ApiError extends Error {
	constructor(message, status, type) {
		super(message);
		this.status = status;
		this.type = type;
	}
}

export function get(method, params = {}) {
	const query = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined || value === null || value === "") continue;
		query.set(key, typeof value === "object" ? JSON.stringify(value) : String(value));
	}
	return request(`/api/method/${method}?${query}`, { method: "GET" });
}

export function post(method, body = {}) {
	return request(`/api/method/${method}`, {
		method: "POST",
		headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": window.csrf_token },
		body: JSON.stringify(body),
	});
}

async function request(url, options) {
	let response;
	try {
		response = await fetch(url, {
			...options,
			credentials: "same-origin",
			headers: { Accept: "application/json", ...(options.headers || {}) },
		});
	} catch {
		throw new ApiError("Cannot reach the server. Check your connection.", 0, "NetworkError");
	}
	const data = await response.json().catch(() => ({}));
	if (!response.ok) {
		throw new ApiError(errorMessage(data, response.status), response.status, data.exc_type);
	}
	return data.message;
}

function errorMessage(data, status) {
	try {
		const messages = JSON.parse(data._server_messages || "[]").map((m) => JSON.parse(m).message);
		if (messages.length) return toText(messages.join(" "));
	} catch {
		// fall through to the generic messages
	}
	if (status === 403) return "You do not have permission to do this.";
	return `The request failed (${status}).`;
}

function toText(html) {
	const element = document.createElement("div");
	element.innerHTML = html;
	return element.textContent || "";
}
