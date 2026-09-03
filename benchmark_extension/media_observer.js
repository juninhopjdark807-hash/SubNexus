"use strict";

(() => {
  if (globalThis.__SUBNEXUS_BENCHMARK_MEDIA_OBSERVER__) return;
  globalThis.__SUBNEXUS_BENCHMARK_MEDIA_OBSERVER__ = true;

  const attached = new WeakSet();
  const readySent = new WeakSet();

  function nowMs() {
    return performance.timeOrigin + performance.now();
  }

  function send(name, media, extra = {}) {
    try {
      const response = chrome.runtime.sendMessage({
        channel: "subnexus-benchmark-media",
        name,
        source: "media_content_script",
        source_timestamp_ms: nowMs(),
        data: {
          page_url: `${location.origin}${location.pathname}`,
          media_tag: media.tagName.toLowerCase(),
          duration_seconds: Number.isFinite(media.duration)
            ? Math.round(media.duration * 1000) / 1000
            : null,
          current_time_seconds: Number.isFinite(media.currentTime)
            ? Math.round(media.currentTime * 1000) / 1000
            : null,
          ready_state: media.readyState,
          paused: media.paused,
          ...extra,
        },
      });
      if (response && typeof response.catch === "function") {
        response.catch(() => {});
      }
    } catch (_) {
      // Contexto da extensão invalidado durante atualização/desinstalação.
    }
  }

  function ready(media) {
    if (readySent.has(media)) return;
    readySent.add(media);
    send("player.ready", media);
  }

  function attach(media) {
    if (!(media instanceof HTMLMediaElement) || attached.has(media)) return;
    attached.add(media);
    media.addEventListener("loadedmetadata", () => ready(media), { passive: true });
    media.addEventListener("canplay", () => ready(media), { passive: true });
    media.addEventListener("play", () => send("player.play", media), { passive: true });
    media.addEventListener("pause", () => send("player.pause", media), { passive: true });
    media.addEventListener("seeking", () => send("player.seeking", media), { passive: true });
    media.addEventListener("seeked", () => send("player.seeked", media), { passive: true });
    media.addEventListener("ended", () => send("player.ended", media), { passive: true });
    media.addEventListener(
      "error",
      () => send("player.error", media, { media_error_code: media.error?.code || null }),
      { passive: true }
    );
    if (media.readyState >= HTMLMediaElement.HAVE_METADATA) ready(media);
  }

  function scan(root) {
    if (root instanceof HTMLMediaElement) attach(root);
    if (root?.querySelectorAll) {
      for (const media of root.querySelectorAll("video,audio")) attach(media);
    }
  }

  function install() {
    if (!document.documentElement) {
      setTimeout(install, 10);
      return;
    }
    scan(document);
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node instanceof Element) scan(node);
        }
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  install();
})();
