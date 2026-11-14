# greetings

A small web application for collecting guests' greetings (ברכות) at a family
event and showing them live on the main screen. The whole user interface is in
Hebrew, right to left.

Guests scan a QR code shown on the screen, type their name and a greeting, and
can come back later to edit it. The screen shows a grid of greetings: new ones
appear at once, and the rest rotate so that each gets an equal share of screen
time. The family has a private page to fix or delete greetings and to download
them all as a PDF.

See [INSTALL.md](INSTALL.md) to put it on the server, [PLAN.md](PLAN.md)
for the design and the decisions behind it, and [IDEAS.md](IDEAS.md) for
ideas to consider later.


## Running it locally

Once, to set up:

```sh
cd ~/greetings
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/greetings init
```

`init` writes `./config.toml` and creates the database in `./state/`. Both are
ignored by git. Edit `config.toml` to set the headings, for example:

```toml
title        = "מזל טוב הילה!"      # the heading on the screen and the form
form_heading = "כתבו ברכה להילה"    # the line under it on the form
```

Then, each time:

```sh
.venv/bin/greetings serve           # http://127.0.0.1:5000/
```

Locally there is **no login**: the screen and the family's page open directly.
That is safe because the server listens only on this machine (127.0.0.1).
Stop it with Ctrl-C. `--port N` picks another port.

To start again from an empty list, stop the server and delete `state/`.

### Trying it out

1. Open `http://127.0.0.1:5000/screen` in one window. Double-click it for full
   screen, and again to leave.
2. Open `http://127.0.0.1:5000/` in another window and send a greeting. It
   appears on the screen within about two seconds.
3. Open `/` again: it now shows your greeting for editing instead of an empty
   form. Change it, and the card on the screen changes in place.
4. To be a second guest, use a private window or another browser. The cookie
   that remembers "your" greeting belongs to one browser.
5. Open `http://127.0.0.1:5000/admin` to see all greetings, edit or delete one
   (it leaves the screen at once), and restore it from "ברכות שנמחקו".

### From a phone

To try the form on a real phone on the same Wi-Fi:

```sh
.venv/bin/greetings serve --bind 0.0.0.0 --insecure
```

and open `http://<this desktop's address>:5000/` on the phone (`ip -4 addr`
shows the address). `--insecure` is required because then the screen and the
family's page have no login and anyone on the same network could open them.
Use it at home only, and stop the server afterwards.

The QR code on the screen encodes whatever address the screen was opened
with, so open the screen through `http://<this desktop's address>:5000/screen`
too, and the phone can scan it.


## The URLs

For guests (no login, ever):

| URL | what |
|---|---|
| `/` | the form: name and greeting. Opened again from the same browser, it edits the greeting sent before. After the family closes the form, a thank-you note. |
| `/thanks` | shown after sending: the greeting as sent, and a link to edit it |
| `/qr.svg` | the QR code for the guests' address, as an image |

For the family (on the server: Google sign-in, and only addresses in `admins`
in the config; locally: no login):

| URL | what |
|---|---|
| `/screen` | the main display: a grid of 6 greetings, the heading, the QR code |
| `/admin` | all greetings, newest first: edit, delete, restore; open or close the form; links to everything below |
| `/admin/<number>` | edit one greeting, with its earlier versions |
| `/admin/print` | all greetings laid out for A4. Its button opens the print dialog; choose "Save as PDF" as the destination. |
| `/admin/greetings.csv` | all greetings as a spreadsheet file |
| `/admin/qr` | a large QR code with the address, to print for the tables |

Behind the scenes:

| URL | what |
|---|---|
| `/screen/api/greetings` | what the screen polls every two seconds (family only) |
| `/login`, `/auth/google`, `/auth/google/callback`, `/logout` | Google sign-in |
| `/healthz` | answers "ok"; for checking the service is up |


## How the screen chooses what to show

With the default settings (6 cards):

- A **new greeting** appears within about two seconds, and stays up for **two
  minutes**, so that whoever wrote it has time to show it to people. While it
  is new, its card is never taken by the rotation or by another new greeting,
  as long as there are cards holding older greetings to take instead.
- Meanwhile the **older greetings rotate** in the remaining cards: every 6
  seconds the one up longest is replaced by the greeting shown least recently.
  With no new greetings on screen, each stays up 36 seconds; each new greeting
  on screen takes one card out of that rotation. Every turn lasts the same
  time, so in the long run each greeting gets an equal share, counted from
  when it arrived.
- If **more new greetings arrive together than there are cards**, they go up
  one every two seconds in order of arrival, and once every card is new, an
  even newer greeting replaces the new one that has been up longest, but not
  before it has been up 12 seconds. The last six of such a burst keep their
  full two minutes.
- An **edit** changes a card in place, and does not bring a greeting back
  early. A **deleted** greeting leaves the screen at once.
- If the network drops, the screen keeps rotating what it has.

All of these times are in the `[screen]` section of `config.toml`:
`cards`, `change_secs` (6), `new_secs` (120), `min_secs` (12). So is the
screen's `background`: the color at the top, as `"#rrggbb"`, which darkens
toward the bottom (default `"#4a2a6b"`, purple). The layout has
three columns, so `cards` fills the screen evenly when it is a multiple of 3.


## Tests

```sh
.venv/bin/python -m pytest -q          # the server
node --test tests/*.test.mjs           # the screen's rotation logic
```

Node.js is used only here, to run the tests of `greetings/static/rotation.js`
outside a browser. Nothing in the application or on the server uses it.
