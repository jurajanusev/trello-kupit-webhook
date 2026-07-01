const scriptInput = document.querySelector("#scriptInput");
const projectName = document.querySelector("#projectName");
const parseBtn = document.querySelector("#parseBtn");
const sampleBtn = document.querySelector("#sampleBtn");
const jsonBtn = document.querySelector("#jsonBtn");
const csvBtn = document.querySelector("#csvBtn");
const cardsEl = document.querySelector("#cards");
const template = document.querySelector("#cardTemplate");
const boardTitle = document.querySelector("#boardTitle");
const cardCount = document.querySelector("#cardCount");
const characterCount = document.querySelector("#characterCount");

let cards = [];

const sampleScript = `OBRAZ 1 - INT. BYT EMA - RÁNO
EMA
Kde je ten zoznam?

MARTIN
Na stole. A možno aj v mojom chaose.

Ema otvorí notebook a nájde starý odkaz od produkcie.

OBRAZ 2 - EXT. ULICA PRED DOMOM - DEŇ
Ema vybieha z domu. Martin ju dobieha s taškou a papiermi.

MARTIN
Bez toho Trella sme stratení.

OBRAZ 3 - INT. PRODUKČNÁ KANCELÁRIA - VEČER
REŽISÉR
Každý obraz musí mať vlastnú kartu.

Tím si rozdeľuje úlohy, rekvizity a lokácie.`;

sampleBtn.addEventListener("click", () => {
  scriptInput.value = sampleScript;
  scriptInput.focus();
});

parseBtn.addEventListener("click", async () => {
  parseBtn.disabled = true;
  parseBtn.textContent = "Spracúvam...";
  try {
    const response = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script: scriptInput.value }),
    });
    const data = await response.json();
    cards = data.cards || [];
    renderCards();
  } finally {
    parseBtn.disabled = false;
    parseBtn.textContent = "Spracovať obrazy";
  }
});

jsonBtn.addEventListener("click", () => {
  download(`${slug(projectName.value)}-trello-cards.json`, JSON.stringify(exportPayload(), null, 2), "application/json");
});

csvBtn.addEventListener("click", () => {
  const rows = [["Name", "Description", "Labels", "Checklist"]];
  cards.forEach((card) => {
    rows.push([
      card.name,
      card.description,
      (card.labels || []).join(", "),
      (card.checklist || []).join(" | "),
    ]);
  });
  download(`${slug(projectName.value)}-trello-cards.csv`, toCsv(rows), "text/csv");
});

function renderCards() {
  cardsEl.innerHTML = "";
  cardsEl.classList.toggle("empty", cards.length === 0);
  boardTitle.textContent = cards.length ? projectName.value || "Trello board" : "Karty zatiaľ čakajú na scenár";
  cardCount.textContent = cards.length;
  characterCount.textContent = new Set(cards.flatMap((card) => card.characters || [])).size;
  jsonBtn.disabled = cards.length === 0;
  csvBtn.disabled = cards.length === 0;

  if (!cards.length) {
    cardsEl.innerHTML = "<p>Nenašiel som žiadny obraz. Skús nadpisy ako OBRAZ 1 alebo SCÉNA 2.</p>";
    return;
  }

  cards.forEach((card, index) => {
    const node = template.content.firstElementChild.cloneNode(true);
    const title = node.querySelector(".card-title");
    const description = node.querySelector(".description");
    title.value = card.name;
    description.value = card.description;
    node.querySelector(".badge").textContent = String(index + 1).padStart(2, "0");
    node.querySelector(".meta").innerHTML = [
      card.location,
      card.timeOfDay,
      ...(card.characters || []).slice(0, 4),
    ]
      .filter(Boolean)
      .map((item) => `<span>${escapeHtml(item)}</span>`)
      .join("");
    node.querySelector(".checklist").innerHTML = (card.checklist || [])
      .map((item) => `<label><input type="checkbox"><span>${escapeHtml(item)}</span></label>`)
      .join("");

    title.addEventListener("input", () => {
      card.name = title.value;
    });
    description.addEventListener("input", () => {
      card.description = description.value;
    });
    cardsEl.appendChild(node);
  });
}

function exportPayload() {
  return {
    project: projectName.value,
    generatedAt: new Date().toISOString(),
    cards,
  };
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function toCsv(rows) {
  return rows
    .map((row) => row.map((cell) => `"${String(cell || "").replaceAll('"', '""')}"`).join(","))
    .join("\n");
}

function slug(value) {
  return (value || "projekt").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}
