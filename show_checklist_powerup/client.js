(function () {
  "use strict";

  const ICON = new URL("./icon.svg", window.location.href).href;
  const SETTINGS_KEY = "showChecklistSettingsV1";
  const Core = window.ShowChecklistCore;

  function readSettings(t) {
    return t.get("board", "private", SETTINGS_KEY, Core.DEFAULT_SETTINGS)
      .then(Core.normalizeSettings)
      .catch(function () { return Core.normalizeSettings(); });
  }

  function readChecklists(t) {
    // Request only checklists. Asking Trello for card('all') is unnecessary and
    // can fail on cards containing many checklists.
    return t.card("checklists").then(function (card) {
      return Array.isArray(card && card.checklists) ? card.checklists : [];
    });
  }

  function errorBadge(error) {
    console.error("Show Checklist:", error);
    return [{ text: "Checklisty sa nepodarilo načítať", color: "red" }];
  }

  window.TrelloPowerUp.initialize({
    "card-badges": function (t) {
      return Promise.all([readChecklists(t), readSettings(t)])
        .then(function (result) {
          return Core.buildBadges(result[0], result[1]).map(function (badge) {
            return Object.assign({ icon: ICON, monochrome: true }, badge);
          });
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
  }, {
    appName: "Dunaj Show Checklist",
  });
})();
