(function () {
  "use strict";

  const ICON = new URL("./icon.svg", window.location.href).href;
  const SETTINGS_KEY = "showChecklistSettingsV1";
  const ITEM_LINE_LENGTH = 30;
  const ROW_WIDTH_UNITS = 30;
  const Core = window.ShowChecklistCore;
  const Rest = window.ShowChecklistRest;

  function compactItemText(text) {
    const source = String(text || "").trim();
    if (!/^[☐☑]\s/.test(source) || source.length <= ITEM_LINE_LENGTH) return source;
    return source.slice(0, ITEM_LINE_LENGTH - 3).trimEnd() + "...";
  }

  function textWidthUnits(text) {
    return Array.from(text).reduce(function (width, character) {
      if (/\s/.test(character)) return width + 0.5;
      if (/[ilI1|.,:;!'`]/.test(character)) return width + 0.45;
      if (/[MW@#%&]/.test(character)) return width + 1.25;
      return width + 1;
    }, 0);
  }

  function fitToRow(text) {
    const missingUnits = Math.max(0, ROW_WIDTH_UNITS - textWidthUnits(text));
    return text + "\u00a0".repeat(Math.ceil(missingUnits / 0.5));
  }

  function layoutBadges(badges) {
    return badges.map(function (badge) {
      return Object.assign({ monochrome: true }, badge, {
        text: fitToRow(compactItemText(badge.text)),
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
