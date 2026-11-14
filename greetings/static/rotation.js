// Which greeting goes in which card on the screen, and when.
//
// Pure logic: no DOM, no clock, no network. The page feeds it the list of
// greetings and the time, and it says which cards changed. That is what lets
// tests/rotation.test.mjs check it with node.
//
// The rules:
//
// * A greeting that arrived while the screen was running, and has not been
//   shown yet, is "fresh". Fresh greetings go up as soon as possible, in the
//   order they arrived, one every FRESH_GAP.
//
// * A fresh greeting's first turn is long: it is "new" for newSecs (say two
//   minutes), so that whoever wrote it has time to show it to people. While
//   any card holds an old greeting, a new card is never replaced: the next
//   fresh greeting, and the regular rotation, take the old cards.
//
// * Only when every card is new, because more greetings arrived together
//   than there are cards, does an even newer one replace a new card: the one
//   that has been up longest.
//
// * Otherwise, every changeSecs the old card that has been up longest is
//   replaced by the greeting shown least recently (never-shown ones first,
//   newest first). Every such turn lasts the same time, so in the long run
//   every greeting gets an equal share, counted from when it arrived.
//
// * No card is replaced before it has been up minSecs, for any reason but a
//   deletion: a greeting that disappears from the list leaves its card at
//   once, and the card is refilled at once.
//
// * Edits change nothing here: a card shows whatever text its greeting has
//   now, and an edited greeting keeps its place in the rotation.
//
// Copyright (C) 2026 Nadav Har'El
// SPDX-License-Identifier: AGPL-3.0-or-later

export const FRESH_GAP_SECS = 2;

export class Rotation {
  // saved: {baseline, lastShown} from a previous run of the page, so that a
  // reload neither treats every greeting as fresh nor forgets who was shown.
  constructor({ cards, changeSecs, minSecs, newSecs = 120 }, saved = {}) {
    this.cards = cards;
    this.changeMs = changeSecs * 1000;
    this.minMs = minSecs * 1000;
    this.newMs = newSecs * 1000;
    this.freshGapMs = FRESH_GAP_SECS * 1000;
    this.slots = new Array(cards).fill(null); // {id, since, fresh} or null
    this.lastShown = new Map(Object.entries(saved.lastShown || {}).map(
      ([k, v]) => [Number(k), v]));
    // Greetings with ids above this arrived while the screen was running.
    this.baseline = saved.baseline ?? null;
    this.ids = [];        // current greetings, ascending id
    this.lastChange = -Infinity;
  }

  // What to keep across a reload.
  saved() {
    return { baseline: this.baseline, lastShown: Object.fromEntries(this.lastShown) };
  }

  // A new list of greeting ids from the server. Returns the slots that changed.
  update(ids, now) {
    this.ids = [...ids].sort((a, b) => a - b);
    if (this.baseline === null) {
      this.baseline = this.ids.length ? this.ids[this.ids.length - 1] : 0;
    }
    const present = new Set(this.ids);
    const changed = [];
    this.slots.forEach((s, i) => {
      if (s && !present.has(s.id)) {
        this.slots[i] = null;
        changed.push(i);
      }
    });
    return [...new Set([...changed, ...this._fill(now)])];
  }

  // Called often (say twice a second). Returns the slots that changed.
  tick(now) {
    const changed = this._fill(now);
    if (changed.length) return changed;

    const fresh = this._fresh();
    if (fresh.length) {
      if (now - this.lastChange < this.freshGapMs) return [];
      // An old card if there is one, even if it must first wait out minSecs;
      // a new card only when every card is new.
      let victim = this._oldestSlot((s) => !this._isNew(s, now));
      if (victim < 0) victim = this._oldestSlot(() => true);
      if (victim < 0 || now - this.slots[victim].since < this.minMs) return [];
      this._place(victim, fresh[0], now);
      return [victim];
    }

    if (now - this.lastChange < this.changeMs) return [];
    const victim = this._oldestSlot((s) => !this._isNew(s, now));
    if (victim < 0 || now - this.slots[victim].since < this.minMs) return [];
    const next = this._candidates()[0];
    if (next === undefined) return [];
    this._place(victim, next, now);
    return [victim];
  }

  // Whether slot i holds a greeting still in its long first turn.
  isNew(i, now) {
    return this._isNew(this.slots[i], now);
  }

  // The greeting id in a slot, or null.
  at(i) {
    return this.slots[i] ? this.slots[i].id : null;
  }

  // ---------------------------------------------------------------- inside

  _onScreen() {
    return new Set(this.slots.filter(Boolean).map((s) => s.id));
  }

  _fresh() {
    const on = this._onScreen();
    return this.ids.filter((id) => id > this.baseline && !this.lastShown.has(id) && !on.has(id));
  }

  // Everything not on screen, best first: fresh in order of arrival, then
  // never shown (newest first), then least recently shown.
  _candidates() {
    const on = this._onScreen();
    const fresh = this._fresh();
    const freshSet = new Set(fresh);
    const rest = this.ids.filter((id) => !on.has(id) && !freshSet.has(id));
    rest.sort((a, b) => {
      const ta = this.lastShown.get(a), tb = this.lastShown.get(b);
      if (ta === undefined && tb === undefined) return b - a;
      if (ta === undefined) return -1;
      if (tb === undefined) return 1;
      return ta - tb || a - b;
    });
    return [...fresh, ...rest];
  }

  _isNew(s, now) {
    return Boolean(s && s.fresh && now - s.since < this.newMs);
  }

  // The occupied slot up longest among those for which pred is true, or -1.
  _oldestSlot(pred) {
    let best = -1;
    this.slots.forEach((s, i) => {
      if (s && pred(s) && (best < 0 || s.since < this.slots[best].since)) best = i;
    });
    return best;
  }

  _fill(now) {
    const changed = [];
    const empty = this.slots.map((s, i) => (s ? -1 : i)).filter((i) => i >= 0);
    if (!empty.length) return changed;
    const cands = this._candidates();
    for (const i of empty) {
      const id = cands.shift();
      if (id === undefined) break;
      this._place(i, id, now);
      changed.push(i);
    }
    return changed;
  }

  _place(i, id, now) {
    const fresh = id > this.baseline && !this.lastShown.has(id);
    this.slots[i] = { id, since: now, fresh };
    this.lastShown.set(id, now);
    this.lastChange = now;
  }
}
