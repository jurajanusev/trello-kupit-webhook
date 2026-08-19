(function () {
  "use strict";
  const Rest = window.ShowChecklistRest;
  const t = window.TrelloPowerUp.iframe(Rest.OPTIONS);
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

  function renderAuthorization() {
    document.getElementById("summary").textContent = "Trello neposkytlo položky checklistov.";
    const content = document.getElementById("content");
    content.innerHTML = '<div class="empty"><p>Na zobrazenie položiek a presných počtov povoľ Power-Upu prístup iba na čítanie.</p>' +
      '<button type="button" id="authorize-trello">Povoliť čítanie checklistov</button></div>';
    document.getElementById("authorize-trello").addEventListener("click", function (event) {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "Otváram povolenie…";
      Rest.authorize(t)
        .then(loadAndRender)
        .catch(function () {
          button.disabled = false;
          button.textContent = "Povoliť čítanie checklistov";
        });
    });
  }

  function loadAndRender(token) {
    return Rest.load(t, undefined, token).then(function (result) {
      if (!result.authorized) {
        renderAuthorization();
      } else {
        render(result.checklists);
      }
      return t.sizeTo("#checklists");
    });
  }

  t.render(function () {
    return loadAndRender()
      .catch(renderError)
      .then(function () { return t.sizeTo("#checklists"); });
  });
})();
