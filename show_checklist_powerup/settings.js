(function () {
  "use strict";
  const t = window.TrelloPowerUp.iframe();
  const Core = window.ShowChecklistCore;
  const KEY = "showChecklistSettingsV1";
  const COLORS = [
    ["", "Bez farby"], ["green", "Zelená"], ["orange", "Oranžová"],
    ["blue", "Modrá"], ["red", "Červená"], ["yellow", "Žltá"],
    ["purple", "Fialová"], ["pink", "Ružová"], ["sky", "Svetlomodrá"],
    ["lime", "Limetková"], ["light-gray", "Sivá"],
  ];
  const ids = ["completeColor", "incompleteColor"];

  function element(id) { return document.getElementById(id); }

  function fillColors(id) {
    element(id).innerHTML = COLORS.map(function (entry) {
      return '<option value="' + entry[0] + '">' + entry[1] + "</option>";
    }).join("");
  }

  function render(settings) {
    ids.forEach(function (id) {
      const node = element(id);
      if (node.type === "checkbox") node.checked = Boolean(settings[id]);
      else node.value = settings[id] === null ? "" : settings[id];
    });
  }

  function collect() {
    const value = {};
    ids.forEach(function (id) {
      const node = element(id);
      value[id] = node.type === "checkbox" ? node.checked : node.value;
    });
    return Core.normalizeSettings(value);
  }

  fillColors("completeColor");
  fillColors("incompleteColor");
  [
    "showCompleteChecklists", "showChecklistName", "showProgress", "showCompleteItems",
    "maxChecklists", "itemsPerChecklist",
  ].forEach(function (id) {
    const label = element(id).closest("label");
    if (label) label.hidden = true;
  });

  t.render(function () {
    return t.get("board", "private", KEY, Core.DEFAULT_SETTINGS)
      .then(function (settings) {
        render(Core.normalizeSettings(settings));
        return t.sizeTo("#settings");
      });
  });

  element("save").addEventListener("click", function () {
    const button = element("save");
    const status = element("status");
    button.disabled = true;
    status.textContent = "Ukladám…";
    t.set("board", "private", KEY, collect())
      .then(function () {
        status.textContent = "Uložené";
        return t.closePopup();
      })
      .catch(function (error) {
        console.error(error);
        status.textContent = "Nastavenia sa nepodarilo uložiť.";
        button.disabled = false;
      });
  });
})();
