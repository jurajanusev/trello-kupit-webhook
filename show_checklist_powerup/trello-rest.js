(function (root) {
  "use strict";

  const config = root.ShowChecklistConfig || {};
  const APP_KEY = String(config.appKey || "");
  // Trello mutates this options object during initialization (for example by
  // adding useADSTokens), so it must stay extensible.
  const OPTIONS = {
    appKey: APP_KEY,
    appName: "Dunaj Show Checklist",
    appAuthor: "Juraj Anusev",
  };

  function hasItems(checklists) {
    return (Array.isArray(checklists) ? checklists : []).every(function (checklist) {
      return Array.isArray(checklist && checklist.checkItems);
    });
  }

  function readCard(t, fields) {
    return t.card.apply(t, fields).then(function (card) {
      return {
        id: String(card && card.id || ""),
        checklists: Array.isArray(card && card.checklists) ? card.checklists : [],
      };
    });
  }

  function fetchChecklists(cardId, token, fetchImpl) {
    const url = new URL("https://api.trello.com/1/cards/" + encodeURIComponent(cardId) + "/checklists");
    url.searchParams.set("key", APP_KEY);
    url.searchParams.set("token", token);
    url.searchParams.set("checkItems", "all");
    url.searchParams.set("checkItem_fields", "name,state,pos");
    url.searchParams.set("fields", "id,name,pos");
    return fetchImpl(url.href, { credentials: "omit" }).then(function (response) {
      if (!response.ok) throw new Error("Trello API: " + response.status);
      return response.json();
    });
  }

  function load(t, fetchImpl) {
    const doFetch = fetchImpl || root.fetch;
    return readCard(t, ["id", "checklists"]).then(function (narrow) {
      if (!narrow.checklists.length || hasItems(narrow.checklists)) {
        return { checklists: narrow.checklists, authorized: true, source: "card" };
      }
      return readCard(t, ["all"]).catch(function () { return narrow; })
        .then(function (full) {
          if (full.checklists.length && hasItems(full.checklists)) {
            return { checklists: full.checklists, authorized: true, source: "card-all" };
          }
          if (!APP_KEY || typeof doFetch !== "function") {
            return { checklists: narrow.checklists, authorized: false, source: "metadata" };
          }
          return t.getRestApi().getToken().then(function (token) {
            if (!token) {
              return { checklists: narrow.checklists, authorized: false, source: "metadata" };
            }
            return fetchChecklists(narrow.id, token, doFetch).then(function (checklists) {
              return { checklists: checklists, authorized: true, source: "rest" };
            });
          }).catch(function () {
            return { checklists: narrow.checklists, authorized: false, source: "metadata" };
          });
        });
    });
  }

  function authorize(t) {
    if (!APP_KEY) return Promise.reject(new Error("Chýba Trello API key"));
    return t.getRestApi().authorize({ scope: "read", expiration: "never" });
  }

  root.ShowChecklistRest = Object.freeze({
    OPTIONS: OPTIONS,
    hasItems: hasItems,
    load: load,
    authorize: authorize,
    fetchChecklists: fetchChecklists,
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
