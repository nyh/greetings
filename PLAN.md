# greetings — plan

A small web application for collecting guests' greetings (ברכות) during a family
event and showing them live on the main screen. The user interface is in
Hebrew, right to left.

## What it does

Three pages, at three URLs:

| page | who | URL | login |
|---|---|---|---|
| **Guest form** | every guest, from a QR code on the screen | `/` | none |
| **Screen** | the main display at the event | `/screen` | Google |
| **Admin** | the family | `/admin` | Google |

**Guest form.** Asks for a name (שם) and a short greeting (ברכה). After
sending, the guest gets a cookie. If they open the URL again, they see their
own greeting and can edit it; they cannot write a second one. A guest whose
greeting the family deleted, or who uses another phone or clears cookies, sees
a fresh form.

**Screen.** Full screen, landscape, for a TV or projector. Shows several
greetings at once as cards with the guest's name, and a QR code with the short
URL in a corner, so a guest who arrives late can still scan it. Rules:

- A new greeting appears **immediately**, replacing the card that has been on
  screen the longest, and then stays up for a long first turn (`new_secs`, two
  minutes) so its writer can show it to people. The rotation below works only
  on the other cards meanwhile. Only when every card holds a new greeting does
  an even newer one replace a new one: the one up longest.
- Otherwise, every few seconds the longest-shown card is replaced by the
  greeting that was **least recently shown** (never-shown ones first). Every
  greeting stays up for the same time each turn, so in the long run each one
  gets an equal share of screen time, counted from when it arrived. (Counting
  total time instead would make a greeting sent late hog the screen until it
  caught up with the early ones.)
- An **edit** to a greeting on screen changes the card at once. An edit to a
  greeting not on screen does not bring it back early; it keeps its place in
  the rotation.
- A **deleted** greeting leaves the screen at once and its card is refilled.
- If many greetings arrive together, they queue and appear one every few
  seconds, so each new card stays up for a minimum time before it is replaced.
- If the network drops, the screen keeps rotating what it has and catches up
  when the connection returns.

**Admin.** The full list, newest first, with time, name and text. Edit any
greeting (to fix an obvious typo or an unfortunate autocorrect), delete one, and
restore a deleted one. Also: a switch to close the guest form after the event,
a printable QR code page for table cards, and an export of all greetings
(HTML for printing as a keepsake, and CSV).

## Technology

Same as harelphotos, so the server already has everything:

- **Python ≥ 3.11 + Flask**, run by **gunicorn** under **systemd** on the
  server, behind the existing **Apache** with a **certbot** certificate. Rocky
  Linux 9, python3.12, as in harelphotos' INSTALL.md.
- Locally, `greetings serve` runs Flask's development server on
  `127.0.0.1:5000` with no login.
- **SQLite** (stdlib `sqlite3`, WAL mode) for storage. A few hundred greetings
  is nothing; WAL lets the screen read while guests write.
- **Google sign-in** copied from harelphotos' `google_auth.py` (authorization
  code flow, code exchanged server to server, scopes `openid email` only). An
  allowlist of email addresses in the config says who may see the screen and
  the admin page. The **same Google OAuth client** as harelphotos can be used:
  add a second redirect URI, `https://<host>/auth/google/callback`, in the
  Google console.
- **segno** (pure Python, no dependencies) to draw the QR code as SVG on the
  server.
- **No JavaScript framework.** The guest form works without JavaScript (a
  plain HTML form; JS only adds a character counter). The screen is one small
  script.

Dependencies: Flask, requests (token exchange), gunicorn, segno.

### Live updates: polling

The screen asks `GET /screen/api/greetings` every 2 seconds. The reply is the
full list (a few hundred short greetings is a few tens of KB), with an `ETag`
from a change counter in the database that every write increments, so an
unchanged list costs a `304` with no body.

Why not Server-Sent Events or WebSockets: with gunicorn's threaded workers each
open SSE connection holds a thread forever, Apache's proxy needs extra tuning
for it, and reconnection after a network drop has to be handled anyway. One
screen polling every 2 seconds is negligible load, and a 2-second delay is
invisible at a party.

### Rotation lives in the browser

The server only stores greetings; the screen page decides what to show. The
rotation logic is a pure JavaScript module (state in, decision out, no DOM)
so that it can be tested with `node --test`. Each greeting's last-shown time is
kept in the screen's `localStorage`, so reloading the screen page does not
restart the rotation from scratch.

Configurable in `config.toml`: number of cards on screen (default 6), seconds
between replacements (6), a new greeting's first turn (120), minimum time a
card stays up (12).

Card text shrinks to fit for long greetings. Font: a Hebrew font with an open
license (e.g. Rubik or Heebo, OFL) bundled in `static/`, rather than loaded
from Google Fonts at the venue.

## Data

```sql
greetings(
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  body        TEXT NOT NULL,
  owner       TEXT,      -- SHA-256 of the guest's cookie token
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  deleted_at  TEXT       -- NULL unless deleted; deletion is reversible
)
revisions(greeting_id, name, body, edited_at, edited_by)  -- every earlier version
meta(key, value)        -- change counter for the ETag; form open/closed
```

Nothing is ever really lost: a delete sets `deleted_at`, and every edit, by a
guest or by the family, first copies the old text to `revisions`.

### The guest's cookie

A random 256-bit token in a cookie (`HttpOnly`, `Secure` on the server,
`SameSite=Lax`, one year). The database stores only its hash. The token
identifies one greeting. Plain random token rather than Flask's signed session
so that it survives a change of the server's secret key.

## Protection

- **Length limits**: name ≤ 40 characters, greeting ≤ 300 (configurable),
  checked on the server; the form shows a counter. Empty and whitespace-only
  input refused. Text is shown escaped, never as HTML.
- **CSRF**: token in the form, as in harelphotos.
- **Flooding**: a loose per-IP limit on *new* greetings. Loose, because all
  guests on the venue's Wi-Fi share one IP address.
- **Bad content**: no automatic filter. Greetings appear immediately, and the
  family can delete one from the admin page in seconds.
- **Private pages**: the screen and admin page and their API require a Google
  sign-in from the allowlist. Locally, with `greetings serve` on loopback, no
  login.

## Configuration

`config.toml`, not in git, searched in the same order as harelphotos (`./`,
`~/.config/greetings/`, `/etc/greetings/`). It holds everything personal, so
nothing about the event is in the code:

```toml
base_url     = "https://<host>"
behind_proxy = true
title        = "מזל טוב הילה!"     # shown on the screen and the form
admins       = ["...@gmail.com"]
max_length   = 300

[screen]
cards       = 6
change_secs = 6
min_secs    = 12
new_secs    = 120

[google]
enabled       = true
client_id     = "..."
client_secret = "..."
```

## Layout

```
greetings/
  pyproject.toml
  greetings/
    __init__.py      create_app()
    config.py        load and validate config.toml
    db.py            schema, queries, change counter
    guest.py         the form, cookie, edit
    screen.py        the screen page and its JSON API
    admin.py         list, edit, delete, restore, close form, export, QR page
    auth.py          admin allowlist + google_auth.py from harelphotos
    qr.py            QR code SVG
    cli.py           init, serve, export
    wsgi.py
    templates/       Hebrew, dir="rtl"
    static/          screen.js, rotation.js, CSS, font
  contrib/
    greetings.service       gunicorn on 127.0.0.1:8098 (harelphotos has 8099)
    greetings-vhost.conf    Apache vhost, as harelphotos'
  tests/                    pytest (Flask test client) + node --test for rotation.js
  README.md, INSTALL.md
```

## Steps

Steps 1 to 5 (the code side) are done, except the headless-Chrome check in
step 2; see README.md to run it locally. Google sign-in is tested only with
Google mocked, until the server is set up.

1. **Skeleton**: package, config, database, `greetings init` and
   `greetings serve`. Guest form: submit, cookie, edit, one greeting per guest,
   limits, CSRF. Tests.
2. **Screen**: JSON API with ETag, `rotation.js` with its tests, the screen
   page and its layout, QR code. A headless-Chrome check that a new greeting
   appears and an edit updates in place.
3. **Admin**: list, edit, delete, restore, close the form, export, QR page.
   Tests.
4. **Google sign-in** for the screen and admin pages, adapted from harelphotos;
   loopback bypass for local use. Tests.
5. **Deployment**: systemd unit, Apache vhost, INSTALL.md. Then, on the
   server: a DNS record for the new host name, certbot, the second redirect
   URI in the Google console, `/etc/greetings/config.toml`.
6. **Rehearsal** before the event:
   - real phones: iPhone Safari and Android Chrome, Hebrew keyboard, emoji,
     the QR code scanned off the real screen from across a room;
   - the real screen and the computer that will drive it, at its resolution,
     signed in with Google (that sign-in is a one-time step to do at home, not
     at the venue);
   - a burst of a few hundred greetings from a script, to see the queueing and
     the server load;
   - a family run-through of the admin page.
7. **After the event**: close the form, export the keepsake, back up the
   SQLite file.

## Decisions (2026-11-14)

- Its own host name, on a server that already runs Apache. INSTALL.md and
  `contrib/` hold the Apache vhost and systemd unit.
- The whole interface is Hebrew and right to left: the guest form, the screen,
  the family's page, the sign-in page and the keepsake. A greeting written in
  English is shown left to right (`dir="auto"`).
- The screen is driven by a laptop, signed in with Google.
- A grid of about six greetings, in a large font. The final look (a photo,
  names, colors, font) is to be discussed later; the current screen
  is a working first version.
- Moderation after the fact: greetings appear at once, the family deletes.
- Length limit 300 characters, configurable (`max_length`).
- The form is closed by hand from the family's page.
- **The keepsake PDF**: a print-styled page (`/admin/print`, A4, two columns)
  with a button that opens the browser's print dialog, where "Save as PDF" is
  the destination. Browsers lay out Hebrew and mixed Hebrew/English correctly;
  server-side PDF libraries (ReportLab, WeasyPrint) either get right-to-left
  text wrong or need system libraries the server may not have.
- Node.js is used only on the desktop, to test `rotation.js` outside a browser.

## Still open

1. The screen's final layout and look.
