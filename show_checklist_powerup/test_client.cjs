const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const Core = require("./core.js");

function loadCapabilities() {
  let capabilities;
  const context = {
    console: { error() {}, log: console.log },
    Promise,
    URL,
    ShowChecklistCore: Core,
    location: { href: "https://example.test/powerup/" },
    TrelloPowerUp: {
      initialize(value) { capabilities = value; },
    },
  };
  context.window = context;
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "client.js"), "utf8"),
    context,
    { filename: "client.js" },
  );
  return capabilities;
}

test("card-badges žiada iba checklists a zvládne desať checklistov", async () => {
  const capabilities = loadCapabilities();
  const calls = [];
  const checklists = Array.from({ length: 10 }, (_, index) => ({
    name: `LIST ${index + 1}`,
    checkItems: [{ name: `Položka ${index + 1}`, state: "incomplete" }],
  }));
  const t = {
    card(...fields) {
      calls.push(fields);
      return Promise.resolve({ checklists });
    },
    get() { return Promise.resolve({ maxChecklists: 6 }); },
  };

  const badges = await capabilities["card-badges"](t);
  assert.deepEqual(calls, [["checklists"]]);
  assert.equal(badges.length, 7);
  assert.match(badges.at(-1).text, /^\+4/);
  assert.equal(badges[0].icon, "https://example.test/powerup/icon.svg");
});

test("chyba načítania sa zobrazí ako červený odznak", async () => {
  const capabilities = loadCapabilities();
  const t = {
    card() { return Promise.reject(new Error("test failure")); },
    get() { return Promise.resolve(Core.DEFAULT_SETTINGS); },
  };
  const badges = await capabilities["card-badges"](t);
  assert.equal(badges.length, 1);
  assert.equal(badges[0].color, "red");
});
