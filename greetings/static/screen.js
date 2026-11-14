// The screen: polls for greetings, lets Rotation pick, draws the cards.
//
// Copyright (C) 2026 Nadav Har'El
// SPDX-License-Identifier: AGPL-3.0-or-later

import { Rotation } from "./rotation.js";

const settings = JSON.parse(document.getElementById("settings").textContent);
const wall = document.getElementById("wall");
const emptyNote = document.getElementById("empty");
const statusNote = document.getElementById("status");
const STORE = "greetings-rotation";
const FADE_MS = 700;

function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}

function save() {
  try {
    localStorage.setItem(STORE, JSON.stringify(rotation.saved()));
  } catch {
    // Private window or storage full: the rotation just restarts on reload.
  }
}

const rotation = new Rotation(settings, loadSaved());
const greetings = new Map(); // id -> {id, name, body}
let version = null;

// ------------------------------------------------------------------ cards

const cards = [];
for (let i = 0; i < settings.cards; i++) {
  const card = document.createElement("article");
  card.className = "card empty";
  card.innerHTML = '<div class="inner"><p class="body" dir="auto"></p><p class="name" dir="auto"></p></div>';
  wall.appendChild(card);
  cards.push({ el: card, id: null, name: null, body: null });
}

// Largest font size at which the text fits in its card, by bisection.
function fit(card) {
  const inner = card.el.querySelector(".inner");
  const box = card.el;
  const max = box.clientHeight / 6;
  let lo = 10, hi = Math.max(max, 12);
  for (let k = 0; k < 12; k++) {
    const mid = (lo + hi) / 2;
    inner.style.fontSize = mid + "px";
    if (inner.scrollHeight <= box.clientHeight * 0.92 && inner.scrollWidth <= box.clientWidth) lo = mid;
    else hi = mid;
  }
  inner.style.fontSize = lo + "px";
}

function fill(card, g) {
  card.el.querySelector(".body").textContent = g ? g.body : "";
  card.el.querySelector(".name").textContent = g ? g.name : "";
  card.id = g ? g.id : null;
  card.name = g ? g.name : null;
  card.body = g ? g.body : null;
  card.el.classList.toggle("empty", !g);
  if (g) fit(card);
}

// Show slot i's greeting: in place if it is the same greeting (an edit),
// with a fade if it is a different one.
function draw(i) {
  const card = cards[i];
  const id = rotation.at(i);
  const g = id === null ? null : greetings.get(id);
  if (g && card.id === g.id) {
    if (card.name !== g.name || card.body !== g.body) fill(card, g);
    return;
  }
  if (card.id === null) {
    fill(card, g);
    card.el.classList.add("entering");
    requestAnimationFrame(() => requestAnimationFrame(() => card.el.classList.remove("entering")));
    return;
  }
  card.el.classList.add("leaving");
  setTimeout(() => {
    // The slot may have changed again while fading out.
    const latest = rotation.at(i);
    fill(card, latest === null ? null : greetings.get(latest));
    card.el.classList.remove("leaving");
  }, FADE_MS);
}

function drawAll() {
  for (let i = 0; i < cards.length; i++) draw(i);
  emptyNote.hidden = greetings.size > 0;
}

// ------------------------------------------------------------------ polling

let failures = 0;

function showStatus(text) {
  statusNote.textContent = text || "";
  statusNote.hidden = !text;
}

async function poll() {
  try {
    const headers = version === null ? {} : { "If-None-Match": `"${version}"` };
    const resp = await fetch(settings.api, { headers, cache: "no-store", credentials: "same-origin" });
    if (resp.status === 401) {
      showStatus("נדרשת התחברות מחדש. יש לטעון את הדף מחדש.");
      return;
    }
    if (resp.status === 304) {
      failures = 0;
      showStatus("");
      return;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    failures = 0;
    showStatus("");
    version = data.version;
    greetings.clear();
    for (const g of data.greetings) greetings.set(g.id, g);
    rotation.update([...greetings.keys()], Date.now());
    save();
    drawAll();
  } catch (e) {
    // Keep rotating what we have; say so only if it lasts.
    if (++failures >= 5) showStatus("אין חיבור לשרת. מנסים שוב…");
  }
}

function tick() {
  const changed = rotation.tick(Date.now());
  if (changed.length) {
    save();
    changed.forEach(draw);
  }
}

async function loop() {
  await poll();
  setTimeout(loop, settings.pollSecs * 1000);
}

loop();
setInterval(tick, 500);

// Refit everything if the window changes size (e.g. entering full screen).
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => cards.forEach((c) => c.id !== null && fit(c)), 200);
});

// Double click toggles full screen.
document.addEventListener("dblclick", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
});
