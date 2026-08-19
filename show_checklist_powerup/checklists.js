(function () {
  "use strict";
  const t = window.TrelloPowerUp.iframe();
  const Core = window.ShowChecklistCore;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[character];
    });
  }

  function render(checklists) {
    const normalized = Core.normalizeChecklists(checklists);
    const summary = Core.summarize(checklists);
    document.getElementById("summary").textContent = summary.checklists + " checklistov · " +
      summary.completeItems + "/" + summary.items + " hotových položiek";

    const content = document.getElementById("content");
    if (!normalized.length) {
      content.innerHTML = '<div class="empty">Táto karta nemá žiadny checklist.</div>';
      return;
    }
    content.innerHTML = normalized.map(function (checklist) {
      const items = !checklist.itemsAvailable
        ? '<li class="item"><span class="item-mark">?</span><span>Položky Trello neposkytlo</span></li>'
        : checklist.items.length ? checklist.items.map(function (item) {
        return '<li class="item ' + (item.complete ? "complete" : "") + '">' +
          '<span class="item-mark">' + (item.complete ? "✓" : "○") + "</span>" +
          "<span>" + escapeHtml(item.name) + "</span></li>";
      }).join("") : '<li class="item"><span class="item-mark">–</span><span>Bez položiek</span></li>';
      return '<section class="checklist"><div class="checklist-head">' +
        '<span class="checklist-title">' + escapeHtml(checklist.name) + "</span>" +
        '<span class="progress">' + (checklist.itemsAvailable
          ? checklist.completeCount + "/" + checklist.totalCount : "–") + "</span>" +
        '</div><ul class="items">' + items + "</ul></section>";
    }).join("");
  }

  function renderError(error) {
    console.error(error);
    document.getElementById("summary").textContent = "";
    document.getElementById("content").innerHTML =
      '<div class="error">Checklisty sa nepodarilo načítať. Skús kartu znovu otvoriť.</div>';
  }

  t.render(function () {
    return t.card("id", "checklists")
      .then(function (card) {
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
      })
      .then(render)
      .catch(renderError)
      .then(function () { return t.sizeTo("#checklists"); });
  });
})();
