"use strict";

const COLLECTOR_ORIGIN = "http://127.0.0.1:8765";
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const MAX_QUEUE_SIZE = 5000;
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let sessionToken = "";
let collectorSessionId = "";
let operationChain = Promise.resolve();
let recentDownloadIntentAt = 0;
const recentPlayByTab = new Map();
const cmsTabs = new Set();
const playerTabs = new Set();
const trackedDownloads = new Set();

function compactUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return `${url.origin}${url.pathname}`;
  } catch (_) {
    return String(value || "").split(/[?#]/, 1)[0].slice(0, 4096);
  }
}

function withTimeout(url, options, timeoutMs = 3500) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timeout));
}

function schedule(task) {
  const result = operationChain.then(task, task);
  operationChain = result.catch(() => {});
  return result;
}

async function setBadge(connected) {
  try {
    await chrome.action.setBadgeText({ text: connected ? "ON" : "!" });
    await chrome.action.setBadgeBackgroundColor({ color: connected ? "#16803c" : "#a61b1b" });
  } catch (_) {}
}

async function restoreTrackedState() {
  const state = await chrome.storage.session.get([
    "cmsTabs",
    "playerTabs",
    "trackedDownloads",
  ]);
  for (const id of state.cmsTabs || []) cmsTabs.add(Number(id));
  for (const id of state.playerTabs || []) playerTabs.add(Number(id));
  for (const id of state.trackedDownloads || []) trackedDownloads.add(Number(id));
}

const trackedStateReady = restoreTrackedState().catch(() => {});

function isCmsOriginRequest(details) {
  if (cmsTabs.has(details.tabId)) return true;
  return [details.initiator, details.documentUrl, details.originUrl].some((value) =>
    String(value || "").startsWith("https://dtv-cms-ui.tbxnet.com/")
  );
}

async function persistTrackedState() {
  await chrome.storage.session.set({
    cmsTabs: [...cmsTabs],
    playerTabs: [...playerTabs],
    trackedDownloads: [...trackedDownloads],
  });
}

async function helloUnlocked() {
  if (sessionToken && collectorSessionId) return true;
  try {
    const response = await withTimeout(`${COLLECTOR_ORIGIN}/api/v1/hello`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SubNexus-Benchmark": "1",
      },
      body: JSON.stringify({
        extension_id: chrome.runtime.id,
        extension_version: EXTENSION_VERSION,
      }),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`hello_http_${response.status}`);
    const payload = await response.json();
    if (!payload.session_token || !payload.session_id) throw new Error("hello_invalid");

    const storage = await chrome.storage.local.get([
      "lastCollectorSession",
      "eventQueue",
    ]);
    const previousSession = storage.lastCollectorSession || "";
    if (previousSession && previousSession !== payload.session_id) {
      // Eventos/targets de outra execução nunca são misturados com uma
      // tentativa nova. Abas CMS permanecem válidas, mas players e downloads
      // anteriores deixam de ser fontes aceitas.
      playerTabs.clear();
      trackedDownloads.clear();
      recentPlayByTab.clear();
      recentDownloadIntentAt = 0;
      await chrome.storage.local.set({
        eventQueue: [],
        droppedEvents: 0,
        playerTabs: [],
        trackedDownloads: [],
      });
    }
    sessionToken = payload.session_token;
    collectorSessionId = payload.session_id;
    await chrome.storage.local.set({ lastCollectorSession: collectorSessionId });
    await setBadge(true);
    return true;
  } catch (_) {
    sessionToken = "";
    collectorSessionId = "";
    await setBadge(false);
    return false;
  }
}

async function flushUnlocked(retryAuthentication = true) {
  if (!(await helloUnlocked())) return false;
  const storage = await chrome.storage.local.get("eventQueue");
  const queue = Array.isArray(storage.eventQueue) ? storage.eventQueue : [];
  if (!queue.length) return true;
  const batch = queue.slice(0, 200);

  try {
    const response = await withTimeout(`${COLLECTOR_ORIGIN}/api/v1/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SubNexus-Benchmark": "1",
        "X-SubNexus-Session": sessionToken,
      },
      body: JSON.stringify({
        extension_id: chrome.runtime.id,
        events: batch,
      }),
      cache: "no-store",
    });
    if (response.status === 401) {
      sessionToken = "";
      collectorSessionId = "";
      if (retryAuthentication && (await helloUnlocked())) {
        return flushUnlocked(false);
      }
      return false;
    }
    if (!response.ok) return false;
    const payload = await response.json();
    const accepted = new Set(payload.accepted_sequences || []);
    const remaining = queue.filter(
      (event) => !accepted.has(event.sequence)
    );
    await chrome.storage.local.set({ eventQueue: remaining });
    return true;
  } catch (_) {
    await setBadge(false);
    return false;
  }
}

async function enqueueUnlocked(event) {
  const storage = await chrome.storage.local.get([
    "eventQueue",
    "nextSequence",
    "lastCollectorSession",
    "droppedEvents",
  ]);
  let queue = Array.isArray(storage.eventQueue) ? storage.eventQueue : [];
  const sequence = Number(storage.nextSequence || 0) + 1;
  const enriched = {
    ...event,
    sequence,
    collector_session_id: collectorSessionId || storage.lastCollectorSession || "",
  };
  queue.push(enriched);
  let dropped = Number(storage.droppedEvents || 0);
  if (queue.length > MAX_QUEUE_SIZE) {
    const overflow = queue.length - MAX_QUEUE_SIZE;
    queue = queue.slice(overflow);
    dropped += overflow;
  }
  await chrome.storage.local.set({
    eventQueue: queue,
    nextSequence: sequence,
    droppedEvents: dropped,
  });
  return flushUnlocked();
}

function emit(name, source, sourceTimestampMs, data = {}, context = {}) {
  return schedule(() =>
    enqueueUnlocked({
      name,
      source,
      source_timestamp_ms: Number(sourceTimestampMs || Date.now()),
      data,
      ...context,
    })
  );
}

function contextFromSender(sender) {
  return {
    tab_id: sender.tab?.id ?? -1,
    window_id: sender.tab?.windowId ?? -1,
    frame_id: sender.frameId ?? -1,
    document_id: sender.documentId || "",
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return false;
  const context = contextFromSender(sender);
  const tabId = context.tab_id;

  if (message.channel === "subnexus-benchmark") {
    trackedStateReady.then(() => {
      if (tabId >= 0) {
        cmsTabs.add(tabId);
        persistTrackedState().catch(() => {});
      }
      if (message.name === "cms.download.intent") {
        recentDownloadIntentAt = Number(message.source_timestamp_ms || Date.now());
      }
      if (
        ["cms.play.intent", "cms.player_select.intent"].includes(message.name) &&
        tabId >= 0
      ) {
        recentPlayByTab.set(tabId, Number(message.source_timestamp_ms || Date.now()));
      }
      emit(
        message.name,
        message.source || "cms_content_script",
        message.source_timestamp_ms,
        message.data || {},
        context
      )
        .then(() => sendResponse({ ok: true }))
        .catch(() => sendResponse({ ok: false }));
    });
    return true;
  }

  if (message.channel === "subnexus-benchmark-media") {
    trackedStateReady.then(() => {
      const openerId = sender.tab?.openerTabId;
      const recentSameTabPlay = recentPlayByTab.get(tabId) || 0;
      const tracked =
        playerTabs.has(tabId) ||
        (Number.isInteger(openerId) && cmsTabs.has(openerId)) ||
        (cmsTabs.has(tabId) && Date.now() - recentSameTabPlay <= 30_000);
      if (!tracked) {
        sendResponse({ ok: true, ignored: true });
        return;
      }
      if (tabId >= 0 && !playerTabs.has(tabId)) {
        playerTabs.add(tabId);
        persistTrackedState().catch(() => {});
      }
      emit(
        message.name,
        message.source || "media_content_script",
        message.source_timestamp_ms,
        message.data || {},
        context
      )
        .then(() => sendResponse({ ok: true }))
        .catch(() => sendResponse({ ok: false }));
    });
    return true;
  }

  return false;
});

chrome.downloads.onCreated.addListener((item) => {
  trackedStateReady.then(() => {
    const now = Date.now();
    const fromCms = String(item.referrer || "").startsWith(
      "https://dtv-cms-ui.tbxnet.com/"
    );
    if (!fromCms && now - recentDownloadIntentAt > 20_000) return;
    trackedDownloads.add(item.id);
    persistTrackedState().catch(() => {});
    emit("browser.download.created", "chrome.downloads", Date.parse(item.startTime) || now, {
      download_id: item.id,
      url: compactUrl(item.url),
      referrer: compactUrl(item.referrer),
      filename: item.filename,
      mime_type: item.mime,
      state: item.state,
      total_bytes: item.totalBytes,
    });
  });
});

chrome.downloads.onChanged.addListener((delta) => {
  trackedStateReady.then(() => {
    if (!trackedDownloads.has(delta.id) || !delta.state?.current) return;
    const state = delta.state.current;
    if (!["complete", "interrupted"].includes(state)) return;
    chrome.downloads.search({ id: delta.id }).then((items) => {
      const item = items[0] || {};
      emit(
        state === "complete"
          ? "browser.download.completed"
          : "browser.download.interrupted",
        "chrome.downloads",
        item.endTime ? Date.parse(item.endTime) : Date.now(),
        {
          download_id: delta.id,
          url: compactUrl(item.url),
          referrer: compactUrl(item.referrer),
          filename: item.filename,
          mime_type: item.mime,
          state,
          error: item.error || "",
          total_bytes: item.totalBytes,
          file_size: item.fileSize,
        }
      );
      trackedDownloads.delete(delta.id);
      persistTrackedState().catch(() => {});
    });
  });
});

chrome.webNavigation.onCreatedNavigationTarget.addListener((details) => {
  trackedStateReady.then(() => {
    const recentPlay = recentPlayByTab.get(details.sourceTabId) || 0;
    if (!cmsTabs.has(details.sourceTabId) || Date.now() - recentPlay > 30_000) return;
    playerTabs.add(details.tabId);
    persistTrackedState().catch(() => {});
    emit(
      "browser.player_target.created",
      "chrome.webNavigation",
      details.timeStamp,
      {
        source_tab_id: details.sourceTabId,
        target_tab_id: details.tabId,
        target_url: compactUrl(details.url),
      },
      {
        tab_id: details.tabId,
        frame_id: 0,
      }
    );
  });
});

function emitTrackedNavigation(name, details) {
  if (!playerTabs.has(details.tabId)) return;
  emit(name, "chrome.webNavigation", details.timeStamp, {
    url: compactUrl(details.url),
    transition_type: details.transitionType || "",
  }, {
    tab_id: details.tabId,
    frame_id: details.frameId,
    document_id: details.documentId || "",
  });
}

chrome.webNavigation.onCommitted.addListener((details) => {
  trackedStateReady.then(() => {
    emitTrackedNavigation("browser.player_navigation.committed", details);
  });
});
chrome.webNavigation.onCompleted.addListener((details) => {
  trackedStateReady.then(() => {
    emitTrackedNavigation("browser.player_navigation.completed", details);
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  trackedStateReady.then(() => {
    cmsTabs.delete(tabId);
    playerTabs.delete(tabId);
    recentPlayByTab.delete(tabId);
    persistTrackedState().catch(() => {});
  });
});

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    trackedStateReady.then(() => {
      const method = String(details.method || "GET").toUpperCase();
      if (
        !isCmsOriginRequest(details) ||
        !MUTATING_METHODS.has(method) ||
        details.type === "ping"
      ) return;
      emit("browser.request.started", "chrome.webRequest", details.timeStamp, {
        request_id: details.requestId,
        method,
        url: compactUrl(details.url),
        resource_type: details.type,
        initiator: compactUrl(details.initiator || ""),
      }, {
        tab_id: details.tabId,
        frame_id: details.frameId,
        document_id: details.documentId || "",
      });
    });
  },
  { urls: ["https://*/*"], types: ["xmlhttprequest", "other", "ping"] }
);

chrome.webRequest.onCompleted.addListener(
  (details) => {
    trackedStateReady.then(() => {
      const method = String(details.method || "GET").toUpperCase();
      if (
        !isCmsOriginRequest(details) ||
        !MUTATING_METHODS.has(method) ||
        details.type === "ping"
      ) return;
      emit("browser.request.completed", "chrome.webRequest", details.timeStamp, {
        request_id: details.requestId,
        method,
        url: compactUrl(details.url),
        resource_type: details.type,
        status_code: details.statusCode,
        from_cache: details.fromCache,
      }, {
        tab_id: details.tabId,
        frame_id: details.frameId,
        document_id: details.documentId || "",
      });
    });
  },
  { urls: ["https://*/*"], types: ["xmlhttprequest", "other", "ping"] }
);

chrome.webRequest.onErrorOccurred.addListener(
  (details) => {
    trackedStateReady.then(() => {
      const method = String(details.method || "GET").toUpperCase();
      if (
        !isCmsOriginRequest(details) ||
        !MUTATING_METHODS.has(method) ||
        details.type === "ping"
      ) return;
      emit("browser.request.error", "chrome.webRequest", details.timeStamp, {
        request_id: details.requestId,
        method,
        url: compactUrl(details.url),
        resource_type: details.type,
        error: details.error,
      }, {
        tab_id: details.tabId,
        frame_id: details.frameId,
        document_id: details.documentId || "",
      });
    });
  },
  { urls: ["https://*/*"], types: ["xmlhttprequest", "other", "ping"] }
);

chrome.runtime.onInstalled.addListener(() => {
  sessionToken = "";
  collectorSessionId = "";
  emit("extension.installed", "extension", Date.now(), {
    extension_version: EXTENSION_VERSION,
  });
});

chrome.runtime.onStartup.addListener(() => {
  sessionToken = "";
  collectorSessionId = "";
  emit("extension.started", "extension", Date.now(), {
    extension_version: EXTENSION_VERSION,
  });
});

chrome.alarms.create("subnexus-benchmark-heartbeat", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== "subnexus-benchmark-heartbeat") return;
  chrome.storage.local.get("droppedEvents").then((state) => {
    emit("extension.heartbeat", "extension", Date.now(), {
      extension_version: EXTENSION_VERSION,
      dropped_events_total: Number(state.droppedEvents || 0),
    });
  });
});

trackedStateReady.then(() => schedule(() => flushUnlocked()));
