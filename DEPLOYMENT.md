# Deploying Chips publicly

This is for the **optional** public-internet mode: the frontend published
to GitHub Pages, the backend reachable through nginx + Cloudflare Tunnel on
this machine. It's useful mainly to route around flaky guest-WiFi/client
isolation (common on home routers, which blocks phones on the same WiFi
from reaching each other directly) by giving every player a stable public
URL instead of a LAN IP, while everyone is still expected to be physically
at the table with a real deck of cards -- this doesn't change what the app
is for.

If you just want to run a game night on your own WiFi with no public
exposure at all, you don't need any of this -- use `./run.sh` and see the
main `README.md` instead. Nothing below changes how that mode works.

## Architecture

```
Players' phones
      │  HTTPS/WSS
      ▼
Cloudflare edge (TLS)
      │  encrypted tunnel
      ▼
cloudflared (this machine)
      │  plain HTTP, loopback only
      ▼
nginx  127.0.0.1:8080        <- CORS, rate limiting, WS upgrade handling
      │  plain HTTP, loopback only
      ▼
FastAPI backend  127.0.0.1:8000   (scripts/run-prod.sh)

Frontend: published separately to GitHub Pages, talks to the backend's
public origin directly (VITE_API_BASE) -- not served by the backend at all
in this mode.
```

Two real differences from the LAN quick-start mode:

1. **Split origins.** The frontend (GitHub Pages) and backend (your own
   domain) are different origins, so the backend needs CORS -- handled at
   the nginx layer (`deploy/nginx-chips.conf`), not in the app itself. The
   app stays exactly as simple as the LAN mode; nginx owns every
   cross-cutting public-deployment concern.
2. **The passphrase is now internet-brute-forceable.** On your own WiFi,
   an attacker needs to already be on your network. Reachable from the
   whole internet, that's no longer true -- `deploy/nginx-chips.conf`
   rate-limits `/api/auth/passphrase` specifically (far tighter than every
   other route), and **you should pick a real, non-trivial passphrase**
   (not the `pokernight` default) before going live. `scripts/run-prod.sh`
   refuses to start without `CHIPS_PASSPHRASE` set, specifically to catch
   this.

Everything else -- the in-memory-only game state, the trust-based
showdown, the equal-information design -- is unchanged.

## One-time setup

### 1. A domain on Cloudflare

You need at least one domain with its DNS hosted on Cloudflare (point its
nameservers at Cloudflare, or add it as a site there) for the backend's
public hostname. The frontend doesn't need one -- GitHub Pages' default
`https://<your-github-username>.github.io/chips/` URL works fine without
owning a domain.

### 2. Backend: nginx + Cloudflare Tunnel

1. Generate `scripts/run-prod.sh`'s virtualenv and confirm it runs once
   manually: `CHIPS_PASSPHRASE=test ./scripts/run-prod.sh` (Ctrl-C after
   confirming `curl 127.0.0.1:8000/api/health` returns `{"ok":true}`).
2. Copy `deploy/nginx-chips.conf` in (as a traditional
   `/etc/nginx/sites-enabled/` file, or adapted into a NixOS
   `services.nginx.virtualHosts` block's `extraConfig`), with your real
   backend hostname and frontend origin substituted in place of the
   placeholders. It listens on `127.0.0.1:8080` only.
3. Pick a backend hostname that's a **sibling** subdomain of your
   frontend's (e.g. frontend `chips.your-domain.com`, backend
   `chips-api.your-domain.com`), **not** a child of it (e.g.
   `api.chips.your-domain.com`) -- that's two subdomain levels below the
   zone apex, which Cloudflare's free Universal SSL cert doesn't cover
   (only the apex and one wildcard level, `*.your-domain.com`). A
   hostname that deep gets a TLS handshake failure, not a clean error.
4. Set up the tunnel:
   ```
   cloudflared tunnel login
   cloudflared tunnel create chips
   cloudflared tunnel route dns chips your-chips-api.example.com
   ```
   Copy `deploy/cloudflared-config.yml` to wherever `cloudflared` expects
   it, filling in the tunnel ID, credentials-file path, and hostname
   `tunnel create`/`route dns` printed. Run it (`cloudflared tunnel run
   chips`, or a systemd unit / the NixOS `services.cloudflared` module for
   anything longer-running than a manual test).
5. Install `deploy/chips-backend.service` (see its header comment) so the
   backend itself survives a reboot, or fold the equivalent into a NixOS
   `systemd.services` block.
6. Confirm end to end: `curl https://your-chips-api.example.com/api/health`
   should return `{"ok":true}` -- not a connection error, not a TLS
   failure.

### Keeping your real deploy config

`deploy/*.conf` / `deploy/*.yml` / `deploy/*.service` are generic
templates, not your actual production config -- substitute your own
values rather than editing the tracked files in place. Keep your real,
filled-in copies under `deploy/local/`, which `.gitignore` excludes
entirely, so your actual hostnames/tunnel ID never touch a tracked file.

### 3. Frontend: GitHub Pages

1. Repo Settings -> Pages -> Source: set to **"GitHub Actions"** (not
   "Deploy from a branch", which would just render the README via
   GitHub's default Jekyll theme).
2. Repo Settings -> Secrets and variables -> Actions -> Variables: add
   `CHIPS_API_URL` set to your backend's public origin (step 2 above),
   e.g. `https://your-chips-api.example.com` -- no trailing slash. This
   isn't a secret (it's a public hostname), a repo *variable* is the
   right place for it, not a secret.
3. Push to `main` with a change under `frontend/` (or run the workflow
   manually from the Actions tab) -- `.github/workflows/pages.yml` builds
   and publishes automatically from there.
4. If you later set up a custom domain for the frontend instead of the
   default `github.io` URL, add a `CNAME` file and change
   `VITE_BASE_PATH` in `.github/workflows/pages.yml` from `/chips/` to
   `/` (GitHub Pages serves a custom domain from the root, not a
   repo-name subpath).

## Deployment checklist

1. Set a real `CHIPS_PASSPHRASE` -- `scripts/run-prod.sh` won't start
   without one, but double check it's not something guessable.
2. Confirm `scripts/run-prod.sh` binds `127.0.0.1` only -- **never**
   change this to `0.0.0.0`. nginx (itself only listening on
   `127.0.0.1:8080`, reached only via `cloudflared`'s local connection) is
   the only thing in this chain with any path from the public internet,
   and even it has no direct public-facing socket.
3. Make sure the machine's firewall doesn't expose port 8000 (the
   backend) or 8080 (nginx) directly -- neither needs to be, or should
   be, reachable from outside this machine; `cloudflared` is the only
   process that talks to the outside world, and it does so via an
   outbound connection, not a listening socket.
4. Substitute real hostnames into your untracked `deploy/local/` copies
   of the nginx config and cloudflared config -- not the tracked
   templates.
5. Set the `CHIPS_API_URL` repo variable before the Pages workflow runs,
   or the published frontend will fall back to same-origin requests
   against `github.io` itself and fail.

## Known limitations (unchanged from the LAN mode, worth restating here)

- **Everything is still in-memory.** A backend restart (crash, deploy,
  machine reboot) ends every room, same as the LAN mode -- this public
  mode doesn't add persistence, it just changes how players reach the
  same process.
- **Single process, single worker, by design.** Room state is a Python
  dict in one process's memory; there's no reason to run more than one
  worker and several reasons not to (state wouldn't be shared across
  them). This app was never built to scale past one physical game's worth
  of concurrent rooms on one machine.
