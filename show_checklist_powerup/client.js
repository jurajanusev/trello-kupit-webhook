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
    // Trello sometimes returns checklist metadata without checkItems. Try the
    // narrow request first, then card('all') only as a best-effort fallback.
    return t.card("id", "checklists").then(function (card) {
      const checklists = Array.isArray(card && card.checklists) ? card.checklists : [];
      const hasItems = checklists.every(function (checklist) {
        return Array.isArray(checklist && checklist.checkItems);
      });
      if (!checklists.length || hasItems) return checklists;
      return t.card("all").then(function (fullCard) {
        const fullChecklists = Array.isArray(fullCard && fullCard.checklists)
          ? fullCard.checklists : [];
        return fullChecklists.length ? fullChecklists : checklists;
      }).catch(function () { return checklists; });
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
