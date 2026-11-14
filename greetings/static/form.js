// The guest form's character counter. The form works without it; the server
// checks the same limits.
//
// Copyright (C) 2026 Nadav Har'El
// SPDX-License-Identifier: AGPL-3.0-or-later

const body = document.getElementById("body");
const counter = document.getElementById("counter");
const max = Number(body.dataset.max);

function update() {
  // Code points, as the server counts: an emoji is one character.
  const left = max - [...body.value.trim()].length;
  counter.textContent = left >= 0 ? `נשארו ${left} תווים` : `${-left} תווים יותר מדי`;
  counter.classList.toggle("over", left < 0);
}

body.addEventListener("input", update);
update();
