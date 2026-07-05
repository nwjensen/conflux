"use strict";

// Conflux Family Command Hub — read-only, facts-only, spouse-first.
// Polls the read endpoints and renders. No maps, no diagnostics, no advice.

const POLL_MS = 4000;
let selected = null; // subject_id of the open detail view, or null for home

const $ = (sel) => document.querySelector(sel);
const api = (path) => fetch(path).then((r) => r.json());

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

// ---- Detail: reachability + messages + timeline + override ----
async function renderDetail(id) {
  const [state, pos, reach, msgs, tl] = await Promise.all([
    api(`/api/state/${id}`),
    api(`/api/last_position/${id}`),
    api(`/api/reachability/${id}`),
    api(`/api/recent_messages/${id}`),
    api(`/api/timeline/${id}`),
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

  $("#detailBody").innerHTML = `
    <h1>${state.name ?? "Subject " + id}</h1>
    <div class="chip s-${state.state}">${state.emoji} ${state.label.toUpperCase()}</div>
    <div class="state-detail">${state.details}</div>
    <div class="reason">${state.reason ?? ""}</div>
    <div class="meta" style="margin-top:8px">
      <div>Last known location: <b>${pos.known ? pos.location : "Unknown"}</b></div>
      <div>Movement: <b>${pos.movement ?? "Unknown"}</b> · Updated ${stamp(pos.at)}</div>
    </div>

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
