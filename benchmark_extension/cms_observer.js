"use strict";

(() => {
  const config = globalThis.SUBNEXUS_BENCHMARK_DETECTORS;
  if (!config || globalThis.__SUBNEXUS_BENCHMARK_CMS_OBSERVER__) {
    return;
  }
  globalThis.__SUBNEXUS_BENCHMARK_CMS_OBSERVER__ = true;

  const seenAvailable = new WeakSet();
  const recentlySent = new Map();
  const state = {
    lastActionAt: 0,
    lastPlayAt: 0,
  };

  function nowMs() {
    return performance.timeOrigin + performance.now();
  }

  function normalize(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function pageUrl() {
    return `${location.origin}${location.pathname}`;
  }

  function extractContentId(value) {
    const text = String(value || "").trim();
    if (config.contentIdPattern.test(text)) {
      return text;
    }
    return "";
  }

  function contentIdFromPage() {
    const routeMatch = location.pathname.match(/\/contents?\/([^/?#]+)/i);
    if (routeMatch) {
      const value = extractContentId(decodeURIComponent(routeMatch[1]));
      if (value) return value;
    }
    for (const [, value] of new URLSearchParams(location.search)) {
      const candidate = extractContentId(value);
      if (candidate) return candidate;
    }
    return "";
  }

  function send(name, data = {}, dedupeMs = 100) {
    const timestamp = nowMs();
    const key = `${name}:${data.action || ""}:${data.content_id || ""}`;
    const previous = recentlySent.get(key) || 0;
    if (timestamp - previous < dedupeMs) return;
    recentlySent.set(key, timestamp);
    try {
      const response = chrome.runtime.sendMessage({
        channel: "subnexus-benchmark",
        name,
        source: "cms_content_script",
        source_timestamp_ms: timestamp,
        data: {
          ...data,
          content_id: data.content_id || contentIdFromPage(),
          page_url: pageUrl(),
        },
      });
      if (response && typeof response.catch === "function") {
        response.catch(() => {});
      }
    } catch (_) {
      // A página pode sobreviver à atualização/desativação da extensão.
    }
  }

  function interactiveFromEvent(event) {
    for (const item of event.composedPath()) {
      if (!(item instanceof Element)) continue;
      if (item.matches(config.interactiveSelector)) return item;
    }
    return event.target instanceof Element ? event.target : null;
  }

  function accessibleLabel(element) {
    if (!(element instanceof Element)) return "";
    const values = [
      element.getAttribute("aria-label"),
      element.getAttribute("title"),
      element instanceof HTMLInputElement ? element.value : "",
      element instanceof HTMLInputElement ? element.labels?.[0]?.textContent : "",
      element.textContent,
      element.getAttribute("data-testid"),
    ];
    const labels = [...new Set(values.map(normalize).filter((value) => value && value.length <= 160))];
    const semantic = labels.find(
      (label) =>
        classifyAction(label) ||
        ["search", "pesquisar", "buscar", "upload", "enviar"].includes(label) ||
        config.languageWords.some((word) => label === word || label.includes(word))
    );
    return semantic || labels[0] || "";
  }

  function classifyAction(label) {
    for (const detector of config.actions) {
      if (detector.exact.includes(label)) return detector.action;
    }
    return "";
  }

  function elementMetadata(element) {
    return {
      tag: element?.tagName?.toLowerCase() || "",
      role: normalize(element?.getAttribute?.("role")),
      input_type: element instanceof HTMLInputElement ? normalize(element.type) : "",
      in_dialog: Boolean(element?.closest?.("dialog,[role='dialog'],[aria-modal='true']")),
    };
  }

  function findContentIdNear(element) {
    const roots = [];
    const form = element?.closest?.("form");
    if (form) roots.push(form);
    roots.push(document);
    for (const root of roots) {
      const inputs = root.querySelectorAll(
        "input[type='search'],input[name*='search' i],input[placeholder*='search' i]," +
          "input[name*='content' i],input[placeholder*='content' i]," +
          "input[name*='id' i],input[placeholder*='id' i]"
      );
      for (const input of inputs) {
        const value = extractContentId(input.value);
        if (value) return value;
      }
    }
    return contentIdFromPage();
  }

  function isSearchForm(form) {
    if (!(form instanceof Element)) return false;
    const hints = normalize(
      [
        form.getAttribute("aria-label"),
        form.getAttribute("name"),
        form.getAttribute("class"),
        ...[...form.querySelectorAll("input")].flatMap((input) => [
          input.type,
          input.name,
          input.placeholder,
          input.getAttribute("aria-label"),
        ]),
      ].join(" ")
    );
    return /(search|content|buscar|pesquisar|\bid\b)/.test(hints);
  }

  function actionEventName(action) {
    if (action === "upload_open") return "cms.upload.open.intent";
    if (action === "validate_media") return "cms.validate_media.intent";
    return `cms.${action}.intent`;
  }

  document.addEventListener(
    "click",
    (event) => {
      const element = interactiveFromEvent(event);
      if (!element) return;
      const label = accessibleLabel(element);
      const metadata = elementMetadata(element);
      const trusted = Boolean(event.isTrusted);

      if (["search", "pesquisar", "buscar"].includes(label)) {
        state.lastActionAt = nowMs();
        send(
          "cms.search.intent",
          {
            trusted,
            content_id: findContentIdNear(element),
            ...metadata,
          },
          500
        );
        return;
      }

      if (["upload", "enviar"].includes(label)) {
        state.lastActionAt = nowMs();
        send(
          metadata.in_dialog ? "cms.upload.submit.intent" : "cms.upload.open.intent",
          { trusted, ...metadata },
          250
        );
        return;
      }

      if (
        metadata.role === "option" &&
        config.languageWords.some((word) => label === word || label.includes(word))
      ) {
        send(
          "cms.upload.language_selected",
          { trusted, language: label.slice(0, 80), ...metadata },
          250
        );
        return;
      }

      const action = classifyAction(label);
      if (action) {
        const timestamp = nowMs();
        state.lastActionAt = timestamp;
        if (action === "play") state.lastPlayAt = timestamp;
        send(actionEventName(action), { trusted, ...metadata }, 250);
        return;
      }

      // O nome dos players varia por projeto. Após Play, uma opção/menu/button
      // no seletor é registrada sem presumir qual player foi escolhido.
      if (
        nowMs() - state.lastPlayAt <= 15_000 &&
        (
          metadata.in_dialog ||
          ["option", "menuitem", "radio"].includes(metadata.role) ||
          metadata.input_type === "radio"
        )
      ) {
        state.lastActionAt = nowMs();
        send(
          "cms.player_select.intent",
          {
            trusted,
            player_label: label.slice(0, 100),
            ...metadata,
          },
          250
        );
      }
    },
    true
  );

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target instanceof Element ? event.target : null;
      if (!isSearchForm(form)) return;
      const contentId = findContentIdNear(form);
      if (!contentId) return;
      state.lastActionAt = nowMs();
      send(
        "cms.search.intent",
        {
          trusted: Boolean(event.isTrusted),
          content_id: contentId,
          tag: "form",
          role: "",
          in_dialog: Boolean(form?.closest?.("dialog,[role='dialog'],[aria-modal='true']")),
        },
        500
      );
    },
    true
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key !== "Enter" || !(event.target instanceof HTMLInputElement)) return;
      const input = event.target;
      const hint = normalize(
        [input.type, input.name, input.placeholder, input.getAttribute("aria-label")].join(" ")
      );
      if (!/(search|content|buscar|pesquisar|\bid\b)/.test(hint)) return;
      const contentId = extractContentId(input.value);
      if (!contentId) return;
      state.lastActionAt = nowMs();
      send(
        "cms.search.intent",
        { trusted: Boolean(event.isTrusted), content_id: contentId, tag: "input" },
        500
      );
    },
    true
  );

  document.addEventListener(
    "change",
    (event) => {
      const target = event.target;
      if (target instanceof HTMLInputElement && target.type === "file") {
        const file = target.files?.[0];
        if (!file) return;
        send(
          "cms.upload.file_selected",
          {
            trusted: Boolean(event.isTrusted),
            filename: file.name,
            size: file.size,
            mime_type: file.type,
            last_modified_ms: file.lastModified,
          },
          250
        );
        return;
      }

      if (target instanceof HTMLSelectElement) {
        const value = normalize(target.selectedOptions?.[0]?.textContent || target.value);
        if (config.languageWords.some((word) => value.includes(word))) {
          send(
            "cms.upload.language_selected",
            {
              trusted: Boolean(event.isTrusted),
              language: value.slice(0, 80),
              tag: "select",
            },
            250
          );
        } else if (nowMs() - state.lastPlayAt <= 15_000) {
          state.lastActionAt = nowMs();
          send(
            "cms.player_select.intent",
            {
              trusted: Boolean(event.isTrusted),
              player_label: value.slice(0, 100),
              tag: "select",
            },
            250
          );
        }
      }
    },
    true
  );

  function inspectAvailable(root) {
    const elements = [];
    if (root instanceof Element && root.matches(config.interactiveSelector)) elements.push(root);
    if (root?.querySelectorAll) {
      elements.push(...root.querySelectorAll(config.interactiveSelector));
    }
    for (const element of elements) {
      if (seenAvailable.has(element)) continue;
      seenAvailable.add(element);
      const label = accessibleLabel(element);
      let action = classifyAction(label);
      const metadata = elementMetadata(element);
      if (["upload", "enviar"].includes(label)) {
        action = metadata.in_dialog ? "upload_submit" : "upload_open";
      }
      if (!action) continue;
      send(
        "cms.control.available",
        {
          action,
          enabled: !element.matches(":disabled,[aria-disabled='true']"),
          ...metadata,
        },
        100
      );
    }
  }

  function notificationStatus(text) {
    if (config.failureWords.some((word) => text.includes(word))) return "failure";
    if (config.successWords.some((word) => text.includes(word))) return "success";
    return "";
  }

  function notificationActionHint(text) {
    if (/(media).*(validat)|validat.*(media)/.test(text)) return "validate_media";
    if (/(upload|subtitle|legenda|enviad)/.test(text)) return "upload";
    if (/(approv|aprov)/.test(text)) return "approve";
    if (/(validat)/.test(text)) return "validate";
    return "";
  }

  function inspectNotifications(root) {
    if (nowMs() - state.lastActionAt > 30_000) return;
    const candidates = new Set();
    if (root instanceof Element && root.matches(config.notificationSelector)) candidates.add(root);
    if (root instanceof Element) {
      const ancestor = root.closest(config.notificationSelector);
      if (ancestor) candidates.add(ancestor);
    }
    if (root?.querySelectorAll) {
      for (const element of root.querySelectorAll(config.notificationSelector)) {
        candidates.add(element);
      }
    }
    for (const element of candidates) {
      const text = normalize(element.textContent).slice(0, 500);
      const status = notificationStatus(text);
      if (!status) continue;
      const matchedWords = (status === "success" ? config.successWords : config.failureWords)
        .filter((word) => text.includes(word))
        .slice(0, 5);
      send(
        `cms.notification.${status}`,
        {
          matched_words: matchedWords,
          action_hint: notificationActionHint(text),
          role: normalize(element.getAttribute("role")),
        },
        750
      );
    }
  }

  function installObserver() {
    if (!document.documentElement) {
      setTimeout(installObserver, 10);
      return;
    }
    inspectAvailable(document);
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (!(node instanceof Element)) continue;
          inspectAvailable(node);
          inspectNotifications(node);
        }
        if (mutation.type === "characterData") {
          inspectNotifications(mutation.target.parentElement);
        } else if (mutation.type === "attributes") {
          inspectNotifications(mutation.target);
        }
      }
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["role", "aria-live"],
    });
    send("cms.observer.ready", {}, 1000);
  }

  installObserver();
})();
