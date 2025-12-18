// background.js - vidarebefordrar data till lokal server (Flask)

let SERVER_URL = "http://127.0.0.1:51234";
const NAME_EXCLUDE_KEYWORDS = ["förening", "holding"];

// Safety check: NEVER send enskild URLs to server
function urlContainsEnskild(url) {
  return url && url.toLowerCase().includes("/enskild/");
}

function normalizeCompanyName(name) {
  if (typeof name !== "string") return "";
  return name.replace(/\s+/g, "").replace(/\d+/g, "").toLowerCase();
}

function shouldSkipCompany(name) {
  if (typeof name !== "string") return false;
  const lowered = name.toLowerCase();
  return NAME_EXCLUDE_KEYWORDS.some((kw) => lowered.includes(kw));
}

function sanitizeCompanyList(items) {
  if (!Array.isArray(items)) return items;

  const seenIds = new Set();
  const seenNames = new Set();
  const cleaned = [];

  for (const entry of items) {
    if (!entry || typeof entry !== "object") {
      cleaned.push(entry);
      continue;
    }

    const rawName =
      entry.namn || entry.company_name || entry.companyName || entry.title;
    if (shouldSkipCompany(rawName)) {
      continue;
    }

    const rawId = entry.kungorelseid || entry.kungorelseId;
    const normalizedId =
      typeof rawId === "string"
        ? rawId.trim().toUpperCase().replace("/", "-")
        : "";
    if (normalizedId && seenIds.has(normalizedId)) {
      continue;
    }

    const normalizedName = normalizeCompanyName(rawName);
    if (normalizedName && seenNames.has(normalizedName)) {
      continue;
    }

    cleaned.push(entry);
    if (normalizedId) seenIds.add(normalizedId);
    if (normalizedName) seenNames.add(normalizedName);
  }

  return cleaned;
}

function sanitizePayload(payload) {
  if (!payload || typeof payload !== "object") return payload;
  const cloned = { ...payload };

  if (Array.isArray(cloned.data)) {
    cloned.data = sanitizeCompanyList(cloned.data);
  } else if (
    cloned.data &&
    typeof cloned.data === "object" &&
    Array.isArray(cloned.data.data)
  ) {
    cloned.data = {
      ...cloned.data,
      data: sanitizeCompanyList(cloned.data.data),
    };
  }

  return cloned;
}

async function postToLocal(payload) {
  try {
    const cleanPayload = sanitizePayload(payload);
    const res = await fetch(`${SERVER_URL}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cleanPayload),
    });
    // Läs/svälj svar för att tömma streamen
    await res.text().catch(() => "");
  } catch (e) {
    console.error(`[PoIT] Failed to post to ${SERVER_URL}/save:`, e);
  }
}

async function postKungorelseToLocal(payload) {
  // SAFETY CHECK: Never send enskild URLs to server
  if (payload && payload.url && urlContainsEnskild(payload.url)) {
    console.log(
      "[PoIT] BLOCKED in background.js: URL contains 'enskild':",
      payload.url
    );
    return;
  }

  try {
    const res = await fetch(`${SERVER_URL}/save_kungorelse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await res.text().catch(() => "");
  } catch (e) {
    console.error(`[PoIT] Failed to post to ${SERVER_URL}/save_kungorelse:`, e);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  try {
    if (!msg || typeof msg !== "object") {
      return;
    }

    // API-responslista från söksidan
    if (msg.type === "KV_SAVE_JSON" && msg.payload) {
      (async () => {
        await postToLocal(msg.payload);
        sendResponse({ ok: true });
      })();
      return true; // behåll message channel öppen
    }

    // Full kungörelsesida (text + html)
    if (msg.type === "KV_SAVE_KUNGORELSE" && msg.payload) {
      (async () => {
        await postKungorelseToLocal(msg.payload);
        sendResponse({ ok: true });
      })();
      return true;
    }
  } catch (e) {
    console.error("[PoIT] onMessage handler error:", e);
  }
});

console.log("[PoIT Listener] Background worker ready - data forwarding only");
