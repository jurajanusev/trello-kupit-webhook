const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadRest() {
  const context = {
    Promise,
    URL,
    ShowChecklistConfig: { appKey: "public-api-key" },
  };
  context.window = context;
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "trello-rest.js"), "utf8"),
    context,
    { filename: "trello-rest.js" },
  );
  return context.ShowChecklistRest;
}

test("autorizovaný REST fallback načíta skutočné položky", async () => {
  const Rest = loadRest();
  const calls = [];
  const t = {
    card(...fields) {
      calls.push(fields);
      return Promise.resolve({ id: "card-1", checklists: [{ id: "list-1", name: "Rekvizity" }] });
    },
    getRestApi() {
      return { getToken: () => Promise.resolve("private-token") };
    },
  };
  const fetchImpl = async function (url, options) {
    assert.match(url, /\/cards\/card-1\/checklists/);
    assert.match(url, /key=public-api-key/);
    assert.match(url, /token=private-token/);
    assert.equal(options.credentials, "omit");
    return {
      ok: true,
      json: async () => [{
        id: "list-1",
        name: "Rekvizity",
        checkItems: [{ name: "x", state: "incomplete" }],
      }],
    };
  };
  const result = await Rest.load(t, fetchImpl);
  assert.equal(result.source, "rest");
  assert.equal(result.checklists[0].checkItems.length, 1);
  assert.deepEqual(calls, [["id", "checklists"], ["all"]]);
});

test("bez tokenu vráti metadata a vyžiada autorizáciu", async () => {
  const Rest = loadRest();
  const t = {
    card() { return Promise.resolve({ id: "card-1", checklists: [{ name: "Rekvizity" }] }); },
    getRestApi() { return { getToken: () => Promise.resolve(null) }; },
  };
  const result = await Rest.load(t, async () => { throw new Error("fetch sa nemá volať"); });
  assert.equal(result.authorized, false);
  assert.equal(result.source, "metadata");
});
