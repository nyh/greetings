// node --test tests/*.test.mjs
//
// Copyright (C) 2026 Nadav Har'El
// SPDX-License-Identifier: AGPL-3.0-or-later

import test from "node:test";
import assert from "node:assert/strict";
import { Rotation } from "../greetings/static/rotation.js";

const S = 1000;
const opts = { cards: 3, changeSecs: 6, minSecs: 12, newSecs: 120 };
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
const shown = (r) => r.slots.map((s) => (s ? s.id : null));

// Run the screen for `secs` seconds, ticking every half second, and return
// how long each greeting was on screen.
function run(r, from, secs) {
  const time = new Map();
  for (let t = from; t < from + secs * S; t += S / 2) {
    r.tick(t);
    for (const s of r.slots) if (s) time.set(s.id, (time.get(s.id) || 0) + S / 2);
  }
  return time;
}

test("fills the cards at once, newest first", () => {
  const r = new Rotation(opts);
  assert.deepEqual(r.update(range(1, 10), 0).sort(), [0, 1, 2]);
  assert.deepEqual(shown(r), [10, 9, 8]);
});

test("fewer greetings than cards: no rotation", () => {
  const r = new Rotation(opts);
  r.update([1, 2], 0);
  assert.deepEqual(shown(r), [2, 1, null]);
  for (let t = 0; t < 100 * S; t += S) assert.deepEqual(r.tick(t), []);
});

test("rotates every changeSecs, replacing the longest-shown card", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  assert.deepEqual(r.tick(5 * S), []);            // cards not up minSecs yet
  assert.deepEqual(r.tick(12 * S), [0]);          // all equal: first slot
  assert.equal(r.at(0), 7);
  assert.deepEqual(r.tick(13 * S), []);           // not changeSecs since
  assert.deepEqual(r.tick(18 * S), [1]);
});

test("equal share of screen time in the long run", () => {
  const r = new Rotation(opts);
  r.update(range(1, 9), 0);
  const time = run(r, 0, 3600);
  const values = [...time.values()];
  assert.equal(time.size, 9);
  // A turn is 18 s (3 cards x 6 s), except the very first turns, which run
  // 12 to 24 s because all the cards went up together. Over an hour every
  // greeting is within two turns of every other, about 3%.
  assert.ok(Math.max(...values) - Math.min(...values) <= 2 * 18 * S, values);
});

test("a new greeting appears at once", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 100);
  r.update(range(1, 11), 100 * S);
  const changed = r.tick(100.5 * S);
  assert.equal(changed.length, 1);
  assert.equal(r.at(changed[0]), 11);
});

test("a burst of new greetings queues, in order of arrival", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 100);
  r.update(range(1, 13), 100 * S);
  const order = [];
  for (let t = 100 * S; t < 110 * S; t += S / 2) {
    for (const i of r.tick(t)) order.push([r.at(i), t]);
  }
  assert.deepEqual(order.map(([id]) => id), [11, 12, 13]);
  // Check that they come one at a time, FRESH_GAP apart.
  assert.ok(order[1][1] - order[0][1] >= 2 * S);
});

test("a new greeting waits for a card that has been up minSecs", () => {
  const r = new Rotation({ ...opts, cards: 1 });
  r.update([1, 2], 0);
  r.update([1, 2, 3], 1 * S);
  assert.deepEqual(r.tick(2 * S), []);
  assert.deepEqual(r.tick(12 * S), [0]);
  assert.equal(r.at(0), 3);
});

test("deleting a shown greeting refills its card at once", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  const slot = r.slots.findIndex((s) => s.id === 9);
  const changed = r.update([1, 2, 3, 4, 5, 6, 7, 8, 10], 1 * S);
  assert.deepEqual(changed, [slot]);
  assert.equal(r.at(slot), 7);
});

test("an edit does not bring a greeting back early", () => {
  // The rotation only sees ids, so the same list after an edit changes
  // nothing on screen.
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 60);
  const before = JSON.stringify(r.slots);
  assert.deepEqual(r.update(range(1, 10), 60 * S), []);
  assert.equal(JSON.stringify(r.slots), before);
});

test("after a reload nothing is fresh, and the rotation continues", () => {
  const r = new Rotation(opts);
  r.update(range(1, 6), 0);
  run(r, 0, 30);              // 4 and 5 shown; 1..3 maybe not
  const saved = JSON.parse(JSON.stringify(r.saved()));
  const r2 = new Rotation(opts, saved);
  r2.update(range(1, 6), 31 * S);
  // The never-shown ones go up first, rather than those just shown.
  const never = range(1, 6).filter((id) => !(String(id) in saved.lastShown));
  for (const id of never) assert.ok(shown(r2).includes(id), `${id} ${shown(r2)}`);
  assert.equal(r2.baseline, 6);
});

test("a greeting sent while the screen was off is not lost", () => {
  const r = new Rotation(opts);
  r.update(range(1, 6), 0);
  run(r, 0, 120);
  const saved = r.saved();
  const r2 = new Rotation(opts, saved);
  r2.update(range(1, 7), 200 * S);       // 7 arrived while it was closed
  assert.ok(shown(r2).includes(7));
});

// Tick every half second from `from` for `secs` seconds; call f(t) after each.
function each(r, from, secs, f) {
  for (let t = from; t < from + secs * S; t += S / 2) {
    r.tick(t);
    f(t);
  }
}

test("a new greeting stays up newSecs while the old ones rotate", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 100);
  r.update(range(1, 11), 100 * S);
  const slot = r.tick(100 * S)[0];
  assert.equal(r.at(slot), 11);
  assert.ok(r.isNew(slot, 100 * S));
  const others = new Set();
  each(r, 100.5 * S, 119, () => {
    assert.equal(r.at(slot), 11);
    r.slots.forEach((s, i) => i !== slot && others.add(s.id));
  });
  // Check that the other two cards kept rotating meanwhile.
  assert.ok(others.size >= 10, [...others]);
  // Once the two minutes are up it is an old card, and the oldest: next out.
  let gone = null;
  each(r, 220 * S, 10, (t) => { if (gone === null && r.at(slot) !== 11) gone = t; });
  assert.ok(gone !== null && gone <= 226 * S, gone);
});

test("when every card is new, an even newer one replaces the oldest new one", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 100);
  r.update(range(1, 14), 100 * S);       // 11..14: one more than the cards
  const up = new Map();
  each(r, 100 * S, 60, (t) => {
    for (const s of r.slots) if (!up.has(s.id)) up.set(s.id, t);
  });
  assert.deepEqual(shown(r).sort(), [12, 13, 14]);
  // 11 went up first, and gave way to 14 only after minSecs.
  assert.equal(up.get(14) - up.get(11), 12 * S);
});

test("a fresh greeting waits for an old card rather than take a new one", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 100);
  r.update(range(1, 12), 100 * S);       // 11 and 12 take two cards
  each(r, 100 * S, 4, () => {});
  const old = r.slots.findIndex((s) => s.id <= 10);
  // The old card was replaced by the regular rotation just now...
  r.slots[old].since = 104 * S;
  r.update(range(1, 13), 104 * S);
  each(r, 104 * S, 11.5, () => assert.ok(!shown(r).includes(13)));
  // ...so 13 goes up when that card has been up minSecs, in its place.
  r.tick(116 * S);
  assert.equal(r.at(old), 13);
});

test("no rotation while every card is new", () => {
  const r = new Rotation(opts);
  r.update(range(1, 10), 0);
  run(r, 0, 100);
  r.update(range(1, 13), 100 * S);
  each(r, 100 * S, 10, () => {});
  const before = shown(r).join();
  assert.deepEqual(before.split(",").map(Number).sort(), [11, 12, 13]);
  each(r, 110 * S, 100, () => assert.equal(shown(r).join(), before));
});
