"use strict";

// Conflux Family Command Hub — read-only, facts-only, spouse-first.
// Polls the read endpoints and renders. No diagnostics, no advice.
//
// The map shows received position reports and nothing else: points are fixes
// that actually arrived, and the dashed line only joins them in order. It is
// not a travelled route — Conflux never saw the ground between two fixes.

const POLL_MS = 4000;
let selected = null; // subject_id of the open detail view, or null for home

const $ = (sel) => document.querySelector(sel);
const api = (path) => fetch(path).then((r) => r.json());
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

function relTime(iso) {
  if (!iso) return "unknown";
  const then = new Date(iso).getTime();
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs} sec ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  return `${hrs} hr ago`;
}
function localTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function stamp(iso) {
  return iso ? `${localTime(iso)} (${relTime(iso)})` : "—";
}

// ---- Home: one card per subject ----
async function renderHome() {
  const states = await api("/api/state");
  const positions = {};
  await Promise.all(
    states.map(async (s) => (positions[s.subject_id] = await api(`/api/last_position/${s.subject_id}`)))
  );

  const home = $("#home");
  home.innerHTML = "";
  for (const s of states) {
    const pos = positions[s.subject_id] || {};
    const card = document.createElement("article");
    card.className = `card s-${s.state}`;
    card.innerHTML = `
      <h2>${s.name ?? "Subject " + s.subject_id}</h2>
      <div class="callsign">${s.callsign ?? ""}</div>
      <div class="chip">${s.emoji} ${s.label.toUpperCase()}</div>
      <div class="state-detail">${s.details}</div>
      <div class="reason">${s.reason ?? ""}</div>
      <div class="meta">
        <div>Updated: <b>${stamp(s.since)}</b></div>
        <div>Last known: <b>${pos.known ? pos.location : "Unknown"}</b></div>
        <div>Movement: <b>${pos.movement ?? "Unknown"}</b></div>
      </div>`;
    card.onclick = () => openDetail(s.subject_id);
    home.appendChild(card);
  }
  $("#lastRefreshed").textContent = `Updated ${localTime(new Date().toISOString())}`;
}

// ---- Map: observed position fixes ----
const STATE_COLOR = {
  OK: "#2ecc71", DELAYED: "#f1c40f", NEED_CONTACT: "#e67e22",
  NEED_HELP: "#e74c3c", EMERGENCY: "#ff2d2d",
};
// Drawn in place of a tile Conflux has neither cached nor been able to fetch,
// so an uncovered area reads as "no basemap here", not as a broken page.
const OFFLINE_TILE =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">
       <rect width="256" height="256" fill="#141922"/>
       <path d="M0 0L256 256M256 0L0 256" stroke="#1e242e" stroke-width="1"/>
     </svg>`
  );

let map = null;
let trackLayer = null;
let mapFitFor = null;  // subject the view was last auto-fitted to
let mapDrawnKey = null; // last (subject, fix count, newest fix) actually drawn

function ensureMap() {
  if (map) return map;
  map = L.map("map", { attributionControl: true }).setView([39.5, -98.35], 3);
  L.tileLayer("/api/tiles/{z}/{x}/{y}.png", {
    maxZoom: 19,
    errorTileUrl: OFFLINE_TILE,
    attribution: "© OpenStreetMap contributors · cached locally",
  }).addTo(map);
  trackLayer = L.layerGroup().addTo(map);
  return map;
}

function fixPopup(f, isLatest) {
  const when = `${localTime(f.at)} (${relTime(f.at)})`;
  const speed = f.speed_kmh === null || f.speed_kmh === undefined
    ? "" : `<br/>Speed reported: ${esc(f.speed_kmh)} km/h`;
  const place = f.place ? `<br/>Comment: “${esc(f.place)}”` : "";
  return `<b>${isLatest ? "Latest fix" : "Fix"}</b><br/>${esc(when)}
    <br/>${esc(f.lat.toFixed(5))}, ${esc(f.lon.toFixed(5))}
    <br/>${f.moving ? "Moving" : "Stopped"} · ${esc(f.source)}${speed}${place}`;
}

function updateMap(id, trk, stateName) {
  const block = $("#mapBlock"), empty = $("#mapEmpty"), note = $("#mapNote");
  const fixes = (trk && trk.fixes) || [];

  if (!fixes.length) {
    $("#map").classList.add("hidden");
    empty.classList.remove("hidden");
    note.textContent = "";
    mapDrawnKey = null;
    return;
  }
  $("#map").classList.remove("hidden");
  empty.classList.add("hidden");

  const latest = fixes[fixes.length - 1];
  const key = `${id}:${trk.count}:${latest.at}`;
  ensureMap();
  map.invalidateSize();          // the block was hidden until the drawer opened
  if (key === mapDrawnKey) return; // nothing new arrived; keep the user's view

  trackLayer.clearLayers();
  const points = fixes.map((f) => [f.lat, f.lon]);
  if (trk.distinct_points > 1) {
    // Dashed on purpose: the segments join reports in order, they are not a
    // path anyone observed being travelled.
    L.polyline(points, { color: "#6c7a89", weight: 2, dashArray: "4 6", opacity: 0.8 })
      .addTo(trackLayer);
  }
  fixes.forEach((f, i) => {
    const isLatest = i === fixes.length - 1;
    L.circleMarker([f.lat, f.lon], {
      radius: isLatest ? 8 : 4,
      color: isLatest ? "#0e1116" : "#6c7a89",
      weight: isLatest ? 2 : 1,
      fillColor: isLatest ? (STATE_COLOR[stateName] || "#9aa7b4") : "#9aa7b4",
      fillOpacity: isLatest ? 1 : 0.55,
    }).addTo(trackLayer).bindPopup(fixPopup(f, isLatest));
  });

  if (mapFitFor !== id) {  // fit once per subject, then leave the view alone
    if (trk.distinct_points > 1) {
      map.fitBounds(L.latLngBounds(points).pad(0.25));
    } else {
      map.setView(points[points.length - 1], 15);
    }
    mapFitFor = id;
  }
  mapDrawnKey = key;

  const where = trk.distinct_points === 1
    ? "all at one location"
    : `at ${trk.distinct_points} distinct locations`;
  note.textContent =
    `${trk.count} received position ${trk.count === 1 ? "report" : "reports"} ${where}. ` +
    `Points are reports Conflux received; the dashed line joins them in order ` +
    `and is not an observed route.`;
  block.classList.remove("hidden");
}

// ---- Detail: map + reachability + messages + timeline + override ----
async function renderDetail(id) {
  const [state, pos, reach, msgs, tl, trk] = await Promise.all([
    api(`/api/state/${id}`),
    api(`/api/last_position/${id}`),
    api(`/api/reachability/${id}`),
    api(`/api/recent_messages/${id}`),
    api(`/api/timeline/${id}`),
    api(`/api/track/${id}`).catch(() => null),
  ]);

  const reachRows = reach.channels
    .map((c) => `<div class="row"><span>${c.channel}</span>
      <span>${c.status} <span class="t">${c.last_at ? localTime(c.last_at) : ""}</span></span></div>`)
    .join("");

  const msgRows = msgs.messages.length
    ? msgs.messages
        .map((m) => `<div class="row">
          <span class="${m.direction === "Sent" ? "sent" : "recv"}">${m.direction} (${m.transport})</span>
          <span>“${m.text}” <span class="t">${localTime(m.at)}</span></span></div>
          ${m.note ? `<div class="note">${m.note}</div>` : ""}`)
        .join("")
    : `<div class="note">No messages yet.</div>`;

  const tlRows = tl.events
    .map((e) => `<div class="row"><span class="t">${localTime(e.at)}</span>
      <span>${e.text}${e.detail ? `<div class="note">${e.detail}</div>` : ""}</span></div>`)
    .join("");

  $("#detailHead").innerHTML = `
    <h1>${state.name ?? "Subject " + id}</h1>
    <div class="chip s-${state.state}">${state.emoji} ${state.label.toUpperCase()}</div>
    <div class="state-detail">${state.details}</div>
    <div class="reason">${state.reason ?? ""}</div>
    <div class="meta" style="margin-top:8px">
      <div>Last known location: <b>${pos.known ? pos.location : "Unknown"}</b></div>
      <div>Movement: <b>${pos.movement ?? "Unknown"}</b> · Updated ${stamp(pos.at)}</div>
    </div>`;

  updateMap(id, trk, state.state);

  $("#detailBody").innerHTML = `
    <div class="block"><h3>Reachability</h3>${reachRows}
      <div class="note">${reach.note}</div></div>
    <div class="block"><h3>Latest messages</h3>${msgRows}</div>
    <div class="block"><h3>Timeline</h3>${tlRows}</div>

    <div class="btnbar">
      <button class="action" onclick="toggleMoving(${id})" id="mvBtn">Toggle movement (sim)</button>
      <button class="action" onclick="injectMsg(${id})">Inject inbound message (sim)</button>
      <button class="action danger" onclick="openOverride(${id}, '${(state.name ?? "").replace(/'/g, "")}')">Override…</button>
    </div>`;
}

function openDetail(id) {
  selected = id;
  // Re-fit and redraw on every open; only *polls* preserve the user's view.
  mapFitFor = null;
  mapDrawnKey = null;
  $("#home").classList.add("hidden");
  $("#detail").classList.remove("hidden");
  renderDetail(id);
}
function closeDetail() {
  selected = null;
  $("#detail").classList.add("hidden");
  $("#home").classList.remove("hidden");
  renderHome();
}

// ---- Simulator + override controls ----
async function toggleMoving(id) {
  const status = await api("/api/sim");
  const cur = status.subjects[id];
  await fetch(`/api/sim/${id}/moving`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ moving: !cur }),
  });
  renderDetail(id);
}
async function injectMsg(id) {
  await fetch(`/api/sim/${id}/inbound_message`, { method: "POST" });
  setTimeout(() => renderDetail(id), 300);
}

function openOverride(id, name) {
  $("#ovName").textContent = name || `Subject ${id}`;
  $("#overrideDialog").returnValue = "";
  $("#overrideDialog").dataset.subject = id;
  $("#overrideDialog").showModal();
}
$("#overrideForm").addEventListener("submit", async (e) => {
  const btn = e.submitter;
  if (!btn || btn.value !== "ok") return;
  const id = $("#overrideDialog").dataset.subject;
  await fetch(`/api/override/${id}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      state: $("#ovState").value,
      pin: $("#ovPin").value,
      immediate: $("#ovImmediate").checked,
    }),
  });
  $("#ovPin").value = "";
  setTimeout(() => renderDetail(id), 300);
});

$("#backBtn").addEventListener("click", closeDetail);

// ---- Manage profiles (edit name + APRS callsign) ----
function showManageError(msg) {
  $("#manageErr").textContent = msg || "";
}

async function renderManageList() {
  const subjects = await api("/api/subjects?all=true");
  const list = $("#manageList");
  list.innerHTML = "";
  for (const s of subjects) {
    const row = document.createElement("div");
    row.className = "manage-item" + (s.active ? "" : " inactive");
    row.innerHTML = `
      <input class="m-name" value="${(s.name ?? "").replace(/"/g, "&quot;")}" maxlength="80" aria-label="Name" />
      <input class="m-call" value="${(s.callsign ?? "").replace(/"/g, "&quot;")}" placeholder="Callsign" maxlength="16" aria-label="Callsign" />
      <label class="m-active"><input type="checkbox" class="m-act" ${s.active ? "checked" : ""} /> active</label>
      <button type="button" class="m-save">Save</button>`;
    row.querySelector(".m-save").onclick = () => saveSubject(s.id, row);
    list.appendChild(row);
  }
}

async function saveSubject(id, row) {
  showManageError("");
  const body = {
    name: row.querySelector(".m-name").value,
    callsign: row.querySelector(".m-call").value,
    active: row.querySelector(".m-act").checked,
  };
  const res = await fetch(`/api/subjects/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showManageError(err.detail || "Could not save.");
    return;
  }
  const btn = row.querySelector(".m-save");
  btn.textContent = "Saved ✓";
  setTimeout(() => (btn.textContent = "Save"), 1200);
  renderManageList();
}

async function addSubject() {
  showManageError("");
  const name = $("#addName").value.trim();
  if (!name) { showManageError("Name is required."); return; }
  const res = await fetch("/api/subjects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, callsign: $("#addCallsign").value, active: true }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showManageError(err.detail || "Could not add.");
    return;
  }
  $("#addName").value = "";
  $("#addCallsign").value = "";
  renderManageList();
}

$("#manageBtn").addEventListener("click", () => {
  showManageError("");
  renderManageList();
  $("#manageDialog").showModal();
});
$("#addBtn").addEventListener("click", addSubject);
// When the dialog closes, reflect any name/callsign changes on the home cards.
$("#manageDialog").addEventListener("close", () => { if (selected === null) renderHome(); });

// ---- Poll loop ----
async function refresh() {
  try {
    if (selected === null) await renderHome();
    else await renderDetail(selected);
  } catch (err) {
    console.error(err);
  }
}
refresh();
setInterval(refresh, POLL_MS);
