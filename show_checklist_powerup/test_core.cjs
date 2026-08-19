const test = require("node:test");
const assert = require("node:assert/strict");
const Core = require("./core.js");

function checklist(index, complete = false) {
  return {
    id: `checklist-${index}`,
    name: `CHECKLIST ${index}`,
    pos: index,
    checkItems: [
      { id: `a-${index}`, name: `Hotová položka ${index}`, state: "complete", pos: 1 },
      { id: `b-${index}`, name: `Ďalšia položka ${index}`, state: complete ? "complete" : "incomplete", pos: 2 },
    ],
  };
}

test("spracuje viac checklistov bez výnimky a pridá súhrnný odznak", () => {
  const source = Array.from({ length: 12 }, (_, index) => checklist(index + 1));
  const badges = Core.buildBadges(source, { maxChecklists: 6 });
  assert.equal(badges.length, 7);
  assert.equal(badges.at(-1).text, "+6 ďalšie checklisty");
  assert.match(badges[0].text, /CHECKLIST 1 · 1\/2 · Ďalšia položka 1/);
});

test("dokáže skryť hotové checklisty", () => {
  const badges = Core.buildBadges(
    [checklist(1, true), checklist(2, false)],
    { showCompleteChecklists: false, maxChecklists: 10 },
  );
  assert.equal(badges.length, 1);
  assert.match(badges[0].text, /CHECKLIST 2/);
});

test("hotový checklist dostane zelenú farbu", () => {
  const badges = Core.buildBadges([checklist(1, true)], {});
  assert.equal(badges[0].color, "green");
  assert.match(badges[0].text, /2\/2/);
});

test("poškodené a prázdne vstupy sa normalizujú", () => {
  assert.deepEqual(Core.normalizeChecklists(null), []);
  const badges = Core.buildBadges([{ name: "", checkItems: [{ name: "", state: "x" }] }], {
    maxChecklists: 500,
    itemsPerChecklist: -10,
    completeColor: "neplatná",
  });
  assert.equal(badges.length, 1);
  assert.match(badges[0].text, /Checklist · 0\/1/);
});

test("súhrn spočíta checklisty aj položky", () => {
  assert.deepEqual(Core.summarize([checklist(1), checklist(2, true)]), {
    checklists: 2,
    items: 4,
    completeItems: 3,
  });
});
