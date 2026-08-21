(function () {
  "use strict";

  const ICON = new URL("./icon.svg", window.location.href).href;
  const SETTINGS_KEY = "showChecklistSettingsV1";
  const FULL_WIDTH_SPACER = "\u00a0".repeat(200);
  const ITEM_LINE_LENGTH = 32;
  const CONTINUATION_PREFIX = "\u00a0\u00a0\u00a0";
  const Core = window.ShowChecklistCore;
  const Rest = window.ShowChecklistRest;

  function wrapItemText(text) {
    const source = String(text || "").trim();
    if (!/^[☐☑]\s/.test(source) || source.length <= ITEM_LINE_LENGTH) return [source];

    const marker = source.slice(0, 2);
    const words = source.slice(2).trim().split(/\s+/);
    const lines = [];
    let line = marker;
    words.forEach(function (word) {
      const next = line + (line === marker ? "" : " ") + word;
      if (line !== marker && next.length > ITEM_LINE_LENGTH) {
        lines.push(line);
        line = CONTINUATION_PREFIX + word;
      } else {
        line = next;
      }
    });
    if (line.trim()) lines.push(line);
    return lines;
  }

  function layoutBadges(badges) {
    return badges.flatMap(function (badge) {
      return wrapItemText(badge.text).map(function (line) {
        return Object.assign({ monochrome: true }, badge, {
          text: line + FULL_WIDTH_SPACER,
        });
      });
    });
  }

  function readSettings(t) {
    return t.get("board", "private", SETTINGS_KEY, Core.DEFAULT_SETTINGS)
      .then(Core.normalizeSettings)
      .catch(function () { return Core.normalizeSettings(); });
  }

  function errorBadge(error) {
    console.error("Show Checklist:", error);
    return [{ text: "Checklisty sa nepodarilo načítať", color: "red" }];
  }

  window.TrelloPowerUp.initialize({
    "card-badges": function (t) {
      return Promise.all([Rest.load(t), readSettings(t)])
        .then(function (result) {
          return layoutBadges(Core.buildExpandedBadges(result[0].checklists, result[1]));
        })
        .catch(errorBadge);
    },

    "card-buttons": function (t) {
      return [{
        icon: ICON,
        text: "Checklisty",
        callback: function (context) {
          return context.popup({
            title: "Checklisty",
            url: "./checklists.html",
            height: 620,
          });
        },
      }];
    },

    "show-settings": function (t) {
      return t.popup({
        title: "Show Checklist – nastavenia",
        url: "./settings.html",
        height: 590,
      });
    },
  }, Rest.OPTIONS);
})();
