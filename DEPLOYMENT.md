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
   the nginx layer (`deploy/nginx-chips.conf`), not in the app itself.
   This is the one thing that's genuinely nginx-only; rate limiting (next
   point) isn't.
2. **The app has no authentication at all, and this makes it public.**
   On your own WiFi an attacker has to already be on your network. Reachable
   from the whole internet, anyone who finds the URL can create rooms, and
   anyone who learns or guesses a room's 6-character code can take a seat at
   that table, act on its turns, and rebuy arbitrary chips. There is no
   credential to get wrong.

   What stands between a stranger and your game is: the ~10^9 room-code
   space, the fact that rooms are swept 10 minutes after the last player
   leaves, and layered rate limiting with a penalty on failed lookups
   (nginx zones here, plus the app's own tighter limits in
   `backend/app/limits.py` -- the app-level ones exist so the plain LAN
   quick-start mode, which has no nginx at all, isn't left unprotected).
   Together those make enumeration take months per code space. None of it
   helps against a botnet, which defeats per-IP limiting at every layer.

   **If you want this on the internet but not open to it, add real access
   control at the nginx layer** -- Cloudflare Access, mTLS, or an
   `auth_request` subrequest. There is nothing in the app to fall back on.

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

`deploy/local/configuration.nix.full` is a complete, ready-to-paste
replacement for `/etc/nixos/configuration.nix` -- membase's existing
`services.nginx`/`services.cloudflared` blocks with chips's pieces spliced
directly into the same attribute literals (a second `virtualHosts."..."`
key, a second `ingress."..."` key, chips's rate-limit zones appended into
the same `appendHttpConfig` string) rather than declared as separate
top-level statements. That distinction matters:
`services.nginx.appendHttpConfig = ...;` written a *second time* elsewhere
in the same file as membase's existing `services.nginx = { appendHttpConfig
= ...; };` is a plain Nix "attribute already defined" parse error --
confirmed by actually reproducing it. Extending the same literal in place,
as this file does, has no such problem. It proxies to `127.0.0.1:8001`, not
`8000` -- that port's already taken by membase's own backend on this
machine.

This exact file has been validated with a full `nixos-rebuild build`
(evaluates and builds the actual system closure, no `sudo`/activation
needed): confirmed both `chips-api.vxliu.com` and `membase-api.vxliu.com`
come out as separate, correct server blocks in the generated nginx.conf,
and both hostnames appear in the generated cloudflared ingress list on the
one shared tunnel. The `chips-backend` unit's `ExecStart` was also
actually *executed* (not just evaluated) under the exact restrictive
`PATH` NixOS generates for systemd services -- which is how an earlier
version of this file was caught failing with `exit code=127` ("env:
'bash': No such file or directory"). NixOS's default systemd service PATH
has no `bash` in it at all, so the script's own `#!/usr/bin/env bash`
shebang can't resolve; `ExecStart` now invokes `${pkgs.bash}/bin/bash`
directly instead of relying on the shebang. `nixos-rebuild build` alone
would never have caught this -- it only confirms the config evaluates and
the closure builds, not that a service actually runs once activated.

1. Replace `/etc/nixos/configuration.nix` with
   `deploy/local/configuration.nix.full`'s contents.
2. Add the new hostname to the *existing* tunnel (reuses its
   already-valid credentials on this machine, no interactive login step):
   ```
   cloudflared tunnel route dns membase chips-api.vxliu.com
   ```
3. ```
   sudo nixos-rebuild switch
   ```
4. The backend itself runs as a NixOS-managed systemd service
   (`systemd.services.chips-backend`, already in
   `deploy/local/configuration.nix.full` from step 1 above) -- it starts
   at boot and restarts on failure, matching membase's own always-on
   presence on this machine. It reads an `EnvironmentFile` at
   `/etc/chips-backend.env`. There is no secret to keep there any more, but
   the unit still references the file, so create it (empty is fine) before
   `nixos-rebuild switch` in step 3 or systemd fails to start the service
   with a missing-EnvironmentFile error. It's also where the `MAX_ROOMS` /
   `RL_*` tuning knobs from `backend/app/config.py` belong if you want to
   override any of them:
   ```
   sudo install -m 600 -o root -g root /dev/null /etc/chips-backend.env
   ```
   If you were running `scripts/run-prod.sh` manually/in a foreground
   shell to test earlier, stop that process first -- it's bound to the
   same port 8001 the systemd service will try to bind.
5. Confirm it's running and enabled for boot:
   ```
   systemctl status chips-backend
   systemctl is-enabled chips-backend   # should print "enabled"
   ```
6. Confirm end to end: `curl https://chips-api.vxliu.com/api/health`
   should return `{"ok":true}` -- not a connection error, not a TLS
   failure.

**If you'd rather keep chips's config in its own file** instead of
splicing it into the existing blocks, `deploy/local/chips.nix` is the same
config as a standalone NixOS module -- add `./chips.nix` to
`configuration.nix`'s `imports` list instead of editing the existing
`services.nginx`/`services.cloudflared` blocks at all. Equally valid
(also build-verified); purely a matter of which you'd rather maintain.

**If you're setting this up on NixOS but without an existing tunnel to
extend**, `deploy/chips.nix` is the generic version of the module
(placeholders instead of real hostnames/tunnel ID/username/path), systemd
service included -- see its header comment. **On a non-NixOS machine**,
`deploy/nginx-chips.conf` and `deploy/cloudflared-config.yml` are
standalone-nginx-site templates instead (same CORS/rate-limiting/WebSocket
logic, just not NixOS-module-shaped), and `deploy/chips-backend.service`
is a plain, portable systemd unit for the backend itself -- same
boot-start/auto-restart behavior as the NixOS `systemd.services` block,
just installed with `systemctl enable` directly instead of declared in
`configuration.nix`.

### Keeping your real deploy config

`deploy/*.conf` / `deploy/*.yml` / `deploy/*.service` / `deploy/chips.nix`
(no `local/`) are generic templates kept for reference/reuse -- not what's
actually installed. Your real, filled-in copies live under `deploy/local/`,
which `.gitignore` excludes entirely, so the real hostnames and tunnel ID
never touch a tracked file.

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

1. Decide whether you are genuinely willing to run this open to the
   internet, or whether you want access control in front of it (see the
   warning above). The app provides none.
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
