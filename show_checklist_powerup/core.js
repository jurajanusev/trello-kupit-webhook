(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ShowChecklistCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const COLORS = new Set([
    "blue", "green", "orange", "red", "yellow", "purple", "pink",
    "sky", "lime", "light-gray",
  ]);

  const DEFAULT_SETTINGS = Object.freeze({
    showCompleteChecklists: true,
    showChecklistName: true,
    showProgress: true,
    showCompleteItems: false,
    maxChecklists: 6,
    itemsPerChecklist: 1,
    completeColor: "green",
    incompleteColor: "orange",
    refreshSeconds: 30,
  });

  function clampInteger(value, fallback, min, max) {
    const number = Number.parseInt(value, 10);
    if (!Number.isFinite(number)) return fallback;
    return Math.min(max, Math.max(min, number));
  }

  function normalizeColor(value, fallback) {
    if (value === "" || value === null) return null;
    return COLORS.has(value) ? value : fallback;
  }

  function normalizeSettings(value) {
    const input = value && typeof value === "object" ? value : {};
    return {
      showCompleteChecklists: input.showCompleteChecklists !== false,
      showChecklistName: input.showChecklistName !== false,
      showProgress: input.showProgress !== false,
      showCompleteItems: input.showCompleteItems === true,
      maxChecklists: clampInteger(input.maxChecklists, 6, 1, 20),
      itemsPerChecklist: clampInteger(input.itemsPerChecklist, 1, 0, 5),
      completeColor: normalizeColor(input.completeColor, "green"),
      incompleteColor: normalizeColor(input.incompleteColor, "orange"),
      refreshSeconds: clampInteger(input.refreshSeconds, 30, 10, 300),
    };
  }

  function normalizeChecklist(checklist, index) {
    const itemsAvailable = Boolean(checklist && (
      Array.isArray(checklist.checkItems) || Array.isArray(checklist.items)
    ));
    const rawItems = Array.isArray(checklist && checklist.checkItems)
      ? checklist.checkItems
      : Array.isArray(checklist && checklist.items) ? checklist.items : [];
    const items = rawItems.map(function (item, itemIndex) {
      return {
        id: String(item && item.id || itemIndex),
        name: String(item && item.name || "Bez názvu").trim() || "Bez názvu",
        complete: Boolean(item && (item.state === "complete" || item.complete === true)),
        pos: Number(item && item.pos) || itemIndex,
      };
    }).sort(function (a, b) { return a.pos - b.pos; });
    const completeCount = items.filter(function (item) { return item.complete; }).length;
    return {
      id: String(checklist && checklist.id || index),
      name: String(checklist && checklist.name || "Checklist").trim() || "Checklist",
      pos: Number(checklist && checklist.pos) || index,
      items: items,
      completeCount: completeCount,
      totalCount: items.length,
      itemsAvailable: itemsAvailable,
      complete: itemsAvailable && items.length > 0 && completeCount === items.length,
    };
  }

  function normalizeChecklists(checklists) {
    return (Array.isArray(checklists) ? checklists : [])
      .map(normalizeChecklist)
      .sort(function (a, b) { return a.pos - b.pos; });
  }

  function truncate(value, maxLength) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length <= maxLength ? text : text.slice(0, maxLength - 1).trimEnd() + "…";
  }

  function badgeText(checklist, settings) {
    const parts = [];
    if (settings.showChecklistName) parts.push(checklist.name);
    if (settings.showProgress) {
      parts.push(checklist.itemsAvailable
        ? checklist.completeCount + "/" + checklist.totalCount : "stav nedostupný");
    }

    const candidates = settings.showCompleteItems
      ? checklist.items
      : checklist.items.filter(function (item) { return !item.complete; });
    const itemNames = candidates
      .slice(0, settings.itemsPerChecklist)
      .map(function (item) { return (item.complete ? "✓ " : "") + item.name; });
    if (itemNames.length) parts.push(itemNames.join(" · "));
    return truncate(parts.join(" · ") || checklist.name, 120);
  }

  function buildBadges(checklists, rawSettings) {
    const settings = normalizeSettings(rawSettings);
    const normalized = normalizeChecklists(checklists).filter(function (checklist) {
      return settings.showCompleteChecklists || !checklist.complete;
    });
    const visible = normalized.slice(0, settings.maxChecklists);
    const badges = visible.map(function (checklist) {
      return {
        text: badgeText(checklist, settings),
        color: checklist.itemsAvailable
          ? (checklist.complete ? settings.completeColor : settings.incompleteColor)
          : "light-gray",
      };
    });
    const hiddenCount = normalized.length - visible.length;
    if (hiddenCount > 0) {
      badges.push({
        text: "+" + hiddenCount + (hiddenCount === 1 ? " ďalší checklist" : " ďalšie checklisty"),
        color: "light-gray",
      });
    }
    return badges;
  }

  function summarize(checklists) {
    const normalized = normalizeChecklists(checklists);
    return normalized.reduce(function (summary, checklist) {
      summary.checklists += 1;
      summary.items += checklist.totalCount;
      summary.completeItems += checklist.completeCount;
      return summary;
    }, { checklists: 0, items: 0, completeItems: 0 });
  }

  return {
    DEFAULT_SETTINGS: DEFAULT_SETTINGS,
    normalizeSettings: normalizeSettings,
    normalizeChecklists: normalizeChecklists,
    buildBadges: buildBadges,
    summarize: summarize,
    truncate: truncate,
  };
});
