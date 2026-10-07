"use strict";
const $ = (id) => document.getElementById(id);
const LS = window.localStorage;
let quest = null;

/* ---------- tiny DOM helper (model text only ever goes through textContent) ---------- */
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return n;
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  return r.json();
}

/* ---------- screen-time meter: counts seconds this tab is actually visible, per quest ---------- */
let tick = null;
function screenKey() { return quest ? `tc_screen_${quest.id}` : null; }
function screenSeconds() { const k = screenKey(); return k ? Number(LS.getItem(k) || 0) : 0; }
function startMeter() {
  if (tick) clearInterval(tick);
  tick = setInterval(() => {
    const k = screenKey();
    if (k && document.visibilityState === "visible") LS.setItem(k, String(screenSeconds() + 1));
  }, 1000);
}

/* ---------- tabs ---------- */
function showTab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === name));
  if (name === "back") renderBack();
  if (name === "journal") loadJournal();
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

/* ---------- health ---------- */
async function loadHealth() {
  const h = $("health");
  try {
    const d = await api("/api/health");
    const fill = (id, vals) => { const s = $(id); if (!s.options.length) vals.forEach((v) => s.append(el("option", { value: v }, v))); };
    fill("habitat", d.habitats); fill("energy", d.energy);
    $("model-name").textContent = d.model;
    if (d.ok) { h.className = "health ok"; h.textContent = `Local model ready: ${d.model}`; }
    else if (d.reachable) { h.className = "health bad"; h.textContent = `Ollama is running but ${d.model} is not pulled. Run: ollama pull ${d.model}. Template cards still work.`; }
    else { h.className = "health bad"; h.textContent = "Ollama is not reachable. Template cards still work; start Ollama for model-written ones."; }
  } catch (e) { h.className = "health bad"; h.textContent = "Trailcard server error: " + e.message; }
}

/* ---------- plan ---------- */
const browserOffsetH = () => -new Date().getTimezoneOffset() / 60;
$("tz").value = browserOffsetH();
$("geo").addEventListener("click", () => {
  if (!navigator.geolocation) return ($("plan-status").textContent = "This browser has no geolocation. Type coordinates instead.");
  $("plan-status").textContent = "Asking your browser for location...";
  navigator.geolocation.getCurrentPosition(
    (p) => { $("lat").value = p.coords.latitude.toFixed(3); $("lon").value = p.coords.longitude.toFixed(3); $("tz").value = browserOffsetH(); $("plan-status").textContent = "Got it."; },
    (e) => ($("plan-status").textContent = "Could not get location (" + e.message + "). Type coordinates instead."),
    { timeout: 10000 });
});

$("plan-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("go"), st = $("plan-status");
  btn.disabled = true; st.textContent = "Your local model is writing the card (the first run loads the model and can take a minute)...";
  try {
    const q = await api("/api/quests", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        place: $("place").value, lat: parseFloat($("lat").value), lon: parseFloat($("lon").value),
        habitat: $("habitat").value, minutes: parseInt($("minutes").value, 10), energy: $("energy").value,
        use_weather: $("use_weather").checked, utc_offset_min: Math.round(parseFloat($("tz").value) * 60),
      }),
    });
    setQuest(q); renderPreview(q); st.textContent = "";
  } catch (e) { st.textContent = "Something went wrong: " + e.message; }
  finally { btn.disabled = false; }
});

function setQuest(q) { quest = q; LS.setItem("tc_active", q.id); startMeter(); }

function renderPreview(q) {
  const box = $("card-preview");
  box.hidden = false; box.replaceChildren(
    el("h2", {}, q.title),
    el("span", { class: "badge" + (q.source === "model" ? "" : " warn") }, q.source === "model" ? "written locally by " + q.meta.model : "template card (model offline)"),
    el("p", {}, q.intro),
    el("ol", { class: "preview" }, q.items.map((i) => el("li", {}, i.prompt))),
    el("p", { class: "small" }, q.meta.sunset_note),
    el("div", { class: "actions" },
      el("a", { class: "btn", href: `/card/${q.id}`, target: "_blank", rel: "noopener" }, "Open printable card"),
      el("button", { class: "ghost", onclick: () => showTab("back") }, "I'm back already")));
}

/* ---------- I'm back ---------- */
function renderBack() {
  $("back-empty").hidden = !!quest; $("back-body").hidden = !quest;
  if (!quest) return;
  $("back-title").textContent = quest.title;
  const ul = $("items"); ul.replaceChildren();
  for (const it of quest.items) ul.append(itemRow(it));
  const mins = Math.max(0, Math.round((Date.now() / 1000 - quest.created_at - screenSeconds()) / 60));
  if (!$("outside").value) $("outside").value = mins;
  $("screen-info").textContent = `Screen time on this card so far: ${fmtScreen(screenSeconds())}`;
  if (quest.journal_entry) showEntry(quest);
}
function fmtScreen(s) { return s < 90 ? `${s}s` : `${Math.round(s / 60)} min`; }

function itemRow(it) {
  const cb = el("input", { type: "checkbox", id: `f${it.id}` });
  cb.checked = it.found;
  const file = el("input", { type: "file", accept: "image/*", capture: "environment", id: `p${it.id}` });
  const verdict = el("div", { class: "verdict" });
  const photoBox = el("div", { class: "photo" });
  const show = (item) => {
    cb.checked = item.found;
    photoBox.replaceChildren(file);
    if (item.photo) photoBox.prepend(el("img", { src: `/api/photos/${quest.id}/${item.id}?t=${Date.now()}`, alt: "your photo" }));
    verdict.textContent = item.matches
      ? `Model check: ${item.matches.replace("_", " ")}. ${item.what_i_see ? "I see: " + item.what_i_see + ". " : ""}${item.ai_note || ""}` : "";
  };
  const send = async (withPhoto) => {
    const fd = new FormData();
    fd.set("item_id", it.id); fd.set("found", cb.checked ? "true" : "false");
    if (withPhoto && file.files[0]) fd.set("photo", file.files[0]);
    verdict.textContent = withPhoto ? "Checking your photo locally..." : "";
    try {
      const upd = await api(`/api/quests/${quest.id}/finds`, { method: "POST", body: fd });
      Object.assign(it, upd); show(it);
    } catch (e) { verdict.textContent = "Could not save: " + e.message; }
  };
  cb.addEventListener("change", () => send(false));
  file.addEventListener("change", () => send(true));
  show(it);
  return el("li", {}, el("div", { class: "top" }, cb, el("label", { for: `f${it.id}` }, `${it.prompt}`, el("span", { class: "badge" }, it.kind))), photoBox, verdict);
}

function showEntry(q) {
  const a = $("entry"); a.hidden = false;
  a.replaceChildren(
    el("h2", {}, "Field journal"),
    el("p", {}, q.journal_entry),
    el("p", { class: "small" }, `${q.outside_minutes} min outside, ${fmtScreen(q.screen_seconds)} on screen. ` +
      (q.journal_source === "model" ? "Written locally." : "Template entry (model offline).")));
}

$("finish").addEventListener("click", async () => {
  const btn = $("finish"), st = $("finish-status");
  btn.disabled = true; st.textContent = "Writing...";
  try {
    const q = await api(`/api/quests/${quest.id}/return`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outside_minutes: parseInt($("outside").value || "0", 10), screen_seconds: screenSeconds(), notes: $("notes").value }),
    });
    quest = q; showEntry(q); st.textContent = "";
  } catch (e) { st.textContent = "Something went wrong: " + e.message; }
  finally { btn.disabled = false; }
});

/* ---------- journal ---------- */
async function loadJournal() {
  const d = await api("/api/journal");
  const t = d.totals, ratio = t.outside_minutes ? `${(t.outside_minutes * 60 / Math.max(1, t.screen_seconds)).toFixed(0)}:1` : "-";
  $("totals").replaceChildren(
    ...[["Outings", t.outings], ["Things found", t.things_found], ["Minutes outside", t.outside_minutes], ["Outside : screen", ratio]]
      .map(([k, v]) => el("div", {}, el("b", {}, v), k)));
  $("outings").replaceChildren(...d.outings.filter((o) => o.returned_at).map((o) =>
    el("div", { class: "outing" },
      el("h2", {}, o.title),
      el("div", { class: "small" }, `${o.place || "Somewhere outside"} - ${o.meta.date} - ${o.items.filter((i) => i.found).length}/${o.items.length} found`),
      el("p", {}, o.journal_entry || ""))));
  if (!d.outings.some((o) => o.returned_at)) $("outings").replaceChildren(el("p", { class: "small" }, "Nothing logged yet. Go outside first."));
}

/* ---------- boot ---------- */
(async function boot() {
  await loadHealth();
  const id = LS.getItem("tc_active");
  if (id) { try { setQuest(await api(`/api/quests/${id}`)); renderPreview(quest); } catch { LS.removeItem("tc_active"); } }
})();
