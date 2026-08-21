const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const Core = require("./core.js");

function loadCapabilities() {
  let capabilities;
  const context = { console: { error() {}, log: console.log }, Promise, URL, ShowChecklistCore: Core,
    ShowChecklistConfig: { appKey: "test-api-key" }, location: { href: "https://example.test/powerup/" },
    TrelloPowerUp: { initialize(value) { capabilities = value; } } };
  context.window = context;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "trello-rest.js"), "utf8"), context, { filename: "trello-rest.js" });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "client.js"), "utf8"), context, { filename: "client.js" });
  return capabilities;
}

test("card badges load all checklists and group their items", async () => {
  const capabilities = loadCapabilities();
  const calls = [];
  const checklists = Array.from({ length: 10 }, (_, index) => ({ name: `LIST ${index + 1}`, checkItems: [{ name: `Item ${index + 1}`, state: "incomplete" }] }));
  const t = { card(...fields) { calls.push(fields); return Promise.resolve({ checklists }); }, get() { return Promise.resolve({ maxChecklists: 6 }); } };
  const badges = await capabilities["card-badges"](t);
  assert.deepEqual(calls, [["id", "checklists"]]);
  assert.equal(badges.length, 20);
  assert.match(badges[18].text, /0\/1 LIST 10/);
  assert.match(badges[19].text, /^☐ /);
  assert.equal(badges[0].icon, undefined);
  assert.equal(badges[0].text.endsWith("\u00a0"), true);
});

test("missing item data falls back to card all", async () => {
  const capabilities = loadCapabilities();
  const calls = [];
  const t = { card(...fields) { calls.push(fields); if (fields[0] === "all") return Promise.resolve({ checklists: [{ name: "Props", checkItems: [{ name: "x", state: "incomplete" }] }] }); return Promise.resolve({ checklists: [{ name: "Props" }] }); }, get() { return Promise.resolve(Core.DEFAULT_SETTINGS); } };
  const badges = await capabilities["card-badges"](t);
  assert.deepEqual(calls, [["id", "checklists"], ["all"]]);
  assert.match(badges[0].text, /0\/1/);
});

test("loading failure is shown as a red badge", async () => {
  const capabilities = loadCapabilities();
  const t = { card() { return Promise.reject(new Error("test failure")); }, get() { return Promise.resolve(Core.DEFAULT_SETTINGS); } };
  const badges = await capabilities["card-badges"](t);
  assert.equal(badges.length, 1);
  assert.equal(badges[0].color, "red");
});

test("long checklist items stay on one row and end with three dots", async () => {
  const capabilities = loadCapabilities();
  const t = {
    card() {
      return Promise.resolve({
        checklists: [{
          name: "SET",
          checkItems: [{
            name: "KOLÁŽ STOCKSHOTOV DAY NIGHT tabuľa s názvom mesta",
            state: "incomplete",
          }],
        }],
      });
    },
    get() { return Promise.resolve(Core.DEFAULT_SETTINGS); },
  };

  const badges = await capabilities["card-badges"](t);
  assert.equal(badges.length, 2);
  assert.match(badges[1].text, /^☐ /);
  assert.equal(badges[1].text.includes("..."), true);
  assert.equal(badges.every((badge) => /[\u00a0\u202f\u200a]$/.test(badge.text)), true);
  assert.equal(badges[1].text.length < badges[0].text.length + 15, true);
});
