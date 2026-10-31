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
FastAPI backend  127.0.0.1:8000   (scripts/run-prod.sh; CHIPS_PORT=8001
                                    on this machine, since 8000 is already
                                    membase's)

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

This project uses `vxliu.com`, already hosted on Cloudflare (same account
as the `membase.vxliu.com` deployment) -- `chips.vxliu.com` (frontend) and
`chips-api.vxliu.com` (backend) are sibling subdomains of it, so no new
domain or DNS zone setup is needed, just the two records/settings below.

### 2. Backend: nginx + Cloudflare Tunnel

**This machine already runs nginx and Cloudflare Tunnel for `membase`, both
declared in `/etc/nixos/configuration.nix` (`services.nginx.virtualHosts`
and `services.cloudflared.tunnels."815ad8c7-1554-416e-a2f2-15a9f27bd98e"`).
Chips reuses that exact same tunnel and nginx instance instead of standing
up a second one -- no new `cloudflared tunnel create`, no new login.**

`deploy/local/configuration.nix.snippet` has the exact block to paste into
`/etc/nixos/configuration.nix` (right after the existing membase
`services.cloudflared = { ... };` block) -- it's a pure addition, it
doesn't touch any existing membase line (see the snippet's own header
comment for why that's safe: `appendHttpConfig` and the tunnel's `ingress`
set both merge additively in Nix). It proxies to `127.0.0.1:8001`, not
`8000` -- that port's already taken by membase's own backend on this
machine.

1. Add the new hostname to the *existing* tunnel (reuses its
   already-valid credentials on this machine, no interactive login step):
   ```
   cloudflared tunnel route dns membase chips-api.vxliu.com
   ```
2. Paste `deploy/local/configuration.nix.snippet`'s contents into
   `/etc/nixos/configuration.nix`, then:
   ```
   sudo nixos-rebuild switch
   ```
3. Start the backend on the non-conflicting port, with a real passphrase:
   ```
   CHIPS_PASSPHRASE=yourrealpassphrase CHIPS_PORT=8001 ./scripts/run-prod.sh
   ```
   `deploy/local/chips-backend.service` has this pre-filled (path,
   `CHIPS_PORT=8001`) if you'd rather run it as a systemd unit than a
   manual/tmux session -- edit in your real passphrase, then
   `sudo cp deploy/local/chips-backend.service /etc/systemd/system/ &&
   sudo systemctl daemon-reload && sudo systemctl enable --now
   chips-backend`. (membase's own backend process isn't systemd-managed on
   this machine, just run manually -- the unit here is an optional
   reliability upgrade, not required to match "the same way".)
4. Confirm end to end: `curl https://chips-api.vxliu.com/api/health`
   should return `{"ok":true}` -- not a connection error, not a TLS
   failure.

**If you're setting this up on a different machine** (no existing tunnel
to extend), `deploy/nginx-chips.conf` and `deploy/cloudflared-config.yml`
are generic, standalone-nginx-site templates for that case instead --
see their own header comments; same CORS/rate-limiting/WebSocket logic,
just not NixOS-module-shaped.

### Keeping your real deploy config

`deploy/*.conf` / `deploy/*.yml` / `deploy/*.service` / `deploy/*.snippet`
(no `local/`) are generic templates kept for reference/reuse -- not what's
actually installed. Your real, filled-in copies live under `deploy/local/`,
which `.gitignore` excludes entirely, so the real hostnames/tunnel
ID/passphrase never touch a tracked file.

### 3. Frontend: GitHub Pages

This project's live deployment publishes the frontend to the custom
domain `chips.vxliu.com`, with the backend reachable at
`chips-api.vxliu.com` -- `frontend/public/CNAME` and
`.github/workflows/pages.yml`'s `VITE_BASE_PATH=/` are already set up for
this (a custom domain serves from the root, not a `/chips/` repo-name
subpath, which is what you'd get on the default `github.io` URL instead).

1. **DNS**: in Cloudflare's DNS for `vxliu.com`, add a `CNAME` record:
   `chips` -> `luxkaiwalker.github.io`, proxy status **DNS only** (grey
   cloud, not orange) -- GitHub's own Let's Encrypt certificate issuance
   for the custom domain checks for a direct CNAME resolution, which an
   orange-clouded (proxied) record would interfere with. You can switch
   it to proxied later once the certificate's issued, if you want
   Cloudflare's edge features on the frontend too.
2. Repo Settings -> Pages -> Source: set to **"GitHub Actions"** (not
   "Deploy from a branch", which would just render the README via
   GitHub's default Jekyll theme).
3. Repo Settings -> Pages -> Custom domain: enter `chips.vxliu.com`, save.
   Wait for the DNS check to pass, then tick **Enforce HTTPS** once it's
   available (may take a few minutes after the DNS record propagates).
4. Repo Settings -> Secrets and variables -> Actions -> Variables: add
   `CHIPS_API_URL` set to `https://chips-api.vxliu.com` -- no trailing
   slash. This isn't a secret (it's a public hostname), a repo *variable*
   is the right place for it, not a secret.
5. Push to `main` with a change under `frontend/` (or run the workflow
   manually from the Actions tab) -- `.github/workflows/pages.yml` builds
   and publishes automatically from there. First deploy can take a few
   minutes to become reachable even after the Action finishes.

## Deployment checklist

1. Set a real `CHIPS_PASSPHRASE` -- `scripts/run-prod.sh` won't start
   without one, but double check it's not something guessable.
2. Confirm `scripts/run-prod.sh` binds `127.0.0.1` only -- **never**
   change this to `0.0.0.0`. nginx (itself only listening on
   `127.0.0.1:8080`, reached only via `cloudflared`'s local connection) is
   the only thing in this chain with any path from the public internet,
   and even it has no direct public-facing socket.
3. Make sure the machine's firewall doesn't expose the backend's port
   (8000, or 8001 on this machine) or 8080 (nginx) directly -- none of
   them need to be, or should be, reachable from outside this machine;
   `cloudflared` is the only process that talks to the outside world, and
   it does so via an outbound connection, not a listening socket.
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
