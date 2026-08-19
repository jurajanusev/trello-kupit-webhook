const test = require("node:test");
const assert = require("node:assert/strict");
const Core = require("./core.js");

function checklist(index, complete = false) {
  return { id: `checklist-${index}`, name: `CHECKLIST ${index}`, pos: index, checkItems: [
    { id: `a-${index}`, name: `Completed item ${index}`, state: "complete", pos: 1 },
    { id: `b-${index}`, name: `Next item ${index}`, state: complete ? "complete" : "incomplete", pos: 2 },
  ] };
}

test("summaries can limit visible checklists", () => {
  const badges = Core.buildBadges(Array.from({ length: 12 }, (_, index) => checklist(index + 1)), { maxChecklists: 6 });
  assert.equal(badges.length, 7);
  assert.match(badges.at(-1).text, /^\+6 /);
  assert.match(badges[0].text, /CHECKLIST 1/);
});

test("completed checklists can be hidden", () => {
  const badges = Core.buildBadges([checklist(1, true), checklist(2, false)], { showCompleteChecklists: false, maxChecklists: 10 });
  assert.equal(badges.length, 1);
  assert.match(badges[0].text, /CHECKLIST 2/);
});

test("completed checklist is green", () => {
  const badges = Core.buildBadges([checklist(1, true)], {});
  assert.equal(badges[0].color, "green");
  assert.match(badges[0].text, /2\/2/);
});

test("invalid and empty inputs are normalized", () => {
  assert.deepEqual(Core.normalizeChecklists(null), []);
  const badges = Core.buildBadges([{ name: "", checkItems: [{ name: "", state: "x" }] }], { maxChecklists: 500, itemsPerChecklist: -10, completeColor: "invalid" });
  assert.equal(badges.length, 1);
  assert.match(badges[0].text, /Checklist/);
});

test("checklist without checkItems reports unavailable state", () => {
  const normalized = Core.normalizeChecklists([{ name: "Props" }]);
  assert.equal(normalized[0].itemsAvailable, false);
  const badges = Core.buildBadges([{ name: "Props" }], {});
  assert.match(badges[0].text, /Props/);
  assert.equal(badges[0].color, "light-gray");
});

test("summary counts checklists and items", () => {
  assert.deepEqual(Core.summarize([checklist(1), checklist(2, true)]), { checklists: 2, items: 4, completeItems: 3 });
});

test("expanded badges group all items beneath checklist headers", () => {
  const badges = Core.buildExpandedBadges([checklist(1), checklist(2, true), checklist(3)], { maxChecklists: 1, itemsPerChecklist: 1 });
  assert.equal(badges.length, 9);
  assert.equal(badges[0].text, "1/2 CHECKLIST 1");
  assert.equal(badges[0].color, "orange");
  assert.match(badges[1].text, /^☑ /);
  assert.equal(badges[1].color, null);
  assert.match(badges[2].text, /^☐ /);
  assert.equal(badges[3].text, "2/2 CHECKLIST 2");
  assert.equal(badges[3].color, "green");
  assert.match(badges[8].text, /^☐ /);
});
