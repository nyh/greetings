# Installing on a server

For putting greetings on a public server, at its own host name with TLS. To
run it on your own machine, ignore all of this and see [README.md](README.md).

Assumed here: Rocky Linux 9 with python3.12, and an Apache `httpd` already
running other sites with `mod_ssl` and certbot, as set up by
[harelphotos' INSTALL.md](https://github.com/nyh/harelphotos/blob/main/INSTALL.md),
which explains each of those in more detail. `greetings.example.org` stands for
your host name throughout.

| what | where |
|---|---|
| the code | `~/greetings`, a git clone plus a venv |
| the config | `/etc/greetings/config.toml` |
| the database, the secret key | `/var/lib/greetings` |
| the service | gunicorn on `127.0.0.1:8098` |


## 1. DNS

Add an `A` record for your host name, pointing at the server. Check before
going on:

```sh
dig +short greetings.example.org      # must print the server's address
```


## 2. Code and configuration

```sh
cd ~ && git clone https://github.com/nyh/greetings.git && cd greetings
python3.12 -m venv .venv
.venv/bin/pip install -e .

sudo mkdir -p /etc/greetings /var/lib/greetings
sudo chown $USER: /etc/greetings /var/lib/greetings
.venv/bin/greetings --config /etc/greetings/config.toml init --state-dir /var/lib/greetings
```

Then edit `/etc/greetings/config.toml`:

```toml
base_url     = "https://greetings.example.org"    # exactly, no trailing slash
behind_proxy = true
title        = "מזל טוב הילה!"
form_heading = "כתבו ברכה להילה"
admins       = ["you@gmail.com", "..."]           # who may see /screen and /admin

[google]
enabled       = true
client_id     = "....apps.googleusercontent.com"
client_secret = "..."
```

`behind_proxy = true` matters: without it every guest seems to come from
`127.0.0.1`, and the limit on new greetings per address would count them all
together.


## 3. Google sign-in

You need a Google OAuth client. If you already have one for another site, such
as harelphotos, reuse it: there is nothing new to register. Otherwise create
one as harelphotos' INSTALL.md describes (scopes `openid` and `email` only, and
"Publish app" so that you do not have to list test users).

In <https://console.cloud.google.com/> → **APIs & Services → Credentials** →
your OAuth client, add:

- Authorized redirect URI: `https://greetings.example.org/auth/google/callback`
- Authorized JavaScript origin: `https://greetings.example.org`

and save. Put its client ID and secret in the `[google]` section above. It can
take a few minutes for Google to accept the new address; until then sign-in
fails with `redirect_uri_mismatch`.


## 4. The service

Edit `User=`, `Group=` and the path in `ExecStart=` in
`contrib/greetings.service` to match your account, then:

```sh
sudo cp contrib/greetings.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now greetings
curl -s http://127.0.0.1:8098/healthz           # expect: ok
```

If it does not say `ok`, `journalctl -u greetings -n 30` says why.


## 5. Apache and the certificate

```sh
sudo mkdir -p /var/www/greetings-acme
sudo cp contrib/greetings-vhost.conf /etc/httpd/conf.d/greetings.conf
sudo sed -i 's/greetings\.example\.org/YOUR.HOST.NAME/g' /etc/httpd/conf.d/greetings.conf
sudo apachectl configtest && sudo systemctl reload httpd
sudo certbot certonly --webroot -w /var/www/greetings-acme -d YOUR.HOST.NAME
sudo systemctl reload httpd
```

The host name must be replaced everywhere in that file, including inside the
certificate paths: those are what the `<IfFile>` guards test, so a missed one
leaves the TLS vhost off forever while `configtest` still passes. The second
reload is what turns on the TLS vhost, which waits for the certificate. Use
`certonly --webroot`, not `--apache`: the file already has the TLS vhost.

Check from anywhere:

```sh
curl -sI https://greetings.example.org/ | head -1                  # 200
curl -sI https://greetings.example.org/admin | grep -i ^location   # .../login?next=...
```

Then sign in at `https://greetings.example.org/admin` with a Google address
from `admins`.


## Updating

```sh
cd ~/greetings && git pull
.venv/bin/pip install -e .          # only needed if pyproject.toml changed
sudo systemctl restart greetings
```

A restart loses nothing. Guests' cookies and the family's sign-ins survive it.


## Backup

Everything is in `/var/lib/greetings/greetings.sqlite`. To copy it safely while
the site is running:

```sh
python3 -c 'import sqlite3; sqlite3.connect("/var/lib/greetings/greetings.sqlite").backup(sqlite3.connect("greetings-backup.sqlite"))'
```

`greetings export > greetings.csv` writes all the greetings as CSV as well.
