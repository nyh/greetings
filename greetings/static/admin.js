// Ask before buttons that delete or close something.
//
// Copyright (C) 2026 Nadav Har'El
// SPDX-License-Identifier: AGPL-3.0-or-later

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-confirm]");
  if (b && !confirm(b.dataset.confirm)) e.preventDefault();
});
