# Generic NixOS module template for Chips's nginx (CORS, rate limiting,
# WebSocket upgrade), Cloudflare Tunnel ingress, and a persistent,
# boot-starting systemd service for the backend itself -- see
# DEPLOYMENT.md "nginx + Cloudflare Tunnel" in the chips repo. Substitute
# your own hostnames, tunnel ID, local port, username, and path in place
# of the placeholders.
#
# Written as its own importable module (add `./chips.nix` to your
# configuration.nix's `imports`) rather than something to paste inline
# into an existing services.nginx/services.cloudflared block elsewhere in
# your config -- if you already declare those options anywhere else,
# NixOS's module system only merges definitions of the same option
# (appendHttpConfig's types.lines concatenation, attrsets like
# virtualHosts/ingress) when they come from SEPARATE modules/files, not
# from writing the same dotted path twice within one file. If you're
# extending an *existing* tunnel (as opposed to `cloudflared tunnel
# create`-ing a new one), this file's `services.cloudflared.tunnels.<id>`
# line only needs the `ingress` addition shown below -- the tunnel's own
# `enable`/`credentialsFile`/`default` are presumably already declared
# wherever that existing tunnel is set up.
#
# NOTE: this app has no authentication. Anyone who can reach the hostname
# below can create a room, and anyone who knows a room code can take a seat
# in it. If that isn't what you want, put real access control in front of it
# here (Cloudflare Access, mTLS, auth_request) -- there is nothing in the app
# to fall back on.

{ config, pkgs, ... }:

{
  services.nginx.appendHttpConfig = ''
    limit_req_zone $binary_remote_addr zone=chips_general:10m rate=10r/s;
    # Room create/join/rejoin. A whole table shares one NAT address here, so
    # these are per-table allowances. The app enforces its own tighter,
    # failure-penalised versions -- see backend/app/limits.py.
    limit_req_zone $binary_remote_addr zone=chips_lookup:10m rate=60r/m;
    limit_req_zone $binary_remote_addr zone=chips_create:10m rate=10r/m;
    # nginx throttles with 503 by default, which differs from the app's own
    # 429 and reads like an outage. Make both layers agree.
    limit_req_status 429;
  '';

  services.nginx.virtualHosts."your-chips-api.example.com" = {
    listen = [ { addr = "127.0.0.1"; port = 8080; } ];
    extraConfig = ''
      set_real_ip_from 127.0.0.1;
      real_ip_header CF-Connecting-IP;
      client_max_body_size 1m;
    '';
    # Separate blocks rather than one, because add_header is not inherited
    # between sibling locations -- each needs its own CORS headers and
    # OPTIONS short-circuit. Precedence: exact `=` beats regex beats the `/`
    # prefix, so each request lands in the block meant for it.
    locations."= /api/rooms" = {
      proxyPass = "http://127.0.0.1:8001";
      extraConfig = ''
        limit_req zone=chips_create burst=5 nodelay;

        add_header Access-Control-Allow-Origin "https://your-chips-frontend.example.com" always;
        add_header Access-Control-Allow-Methods "POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type" always;
        add_header Access-Control-Max-Age 600 always;

        if ($request_method = OPTIONS) {
          return 204;
        }

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
      '';
    };
    locations."~ ^/api/rooms/[^/]+/(join|rejoin)$" = {
      proxyPass = "http://127.0.0.1:8001";
      extraConfig = ''
        limit_req zone=chips_lookup burst=20 nodelay;

        add_header Access-Control-Allow-Origin "https://your-chips-frontend.example.com" always;
        add_header Access-Control-Allow-Methods "POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type" always;
        add_header Access-Control-Max-Age 600 always;

        if ($request_method = OPTIONS) {
          return 204;
        }

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
      '';
    };
    locations."/" = {
      proxyPass = "http://127.0.0.1:8001";
      proxyWebsockets = true;
      extraConfig = ''
        limit_req zone=chips_general burst=20 nodelay;

        add_header Access-Control-Allow-Origin "https://your-chips-frontend.example.com" always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type" always;
        add_header Access-Control-Max-Age 600 always;

        if ($request_method = OPTIONS) {
          return 204;
        }

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
      '';
    };
  };

  services.cloudflared.tunnels."<TUNNEL_ID>".ingress."your-chips-api.example.com" =
    "http://127.0.0.1:8080";

  # Runs the chips backend itself persistently, starting at boot.
  # The EnvironmentFile below is optional now that there is no passphrase to
  # keep out of this world-readable file; it is kept as the place to put any
  # of the MAX_ROOMS / RL_* tuning knobs from backend/app/config.py. Create
  # it (or drop the line) with:
  #   sudo install -m 600 -o root -g root /dev/null /etc/chips-backend.env
  systemd.services.chips-backend = {
    description = "Chips backend (poker chip/pot tracker)";
    after = [ "network.target" ];
    wantedBy = [ "multi-user.target" ];
    environment.CHIPS_PORT = "8001";
    serviceConfig = {
      Type = "simple";
      User = "REPLACE_WITH_YOUR_USERNAME";
      WorkingDirectory = "/REPLACE/WITH/PATH/TO/chips";
      EnvironmentFile = "/etc/chips-backend.env";
      # ${pkgs.bash}/bin/bash explicitly -- NixOS's default systemd
      # service PATH doesn't include bash, so the script's own
      # "#!/usr/bin/env bash" shebang fails with exit code 127.
      ExecStart = "${pkgs.bash}/bin/bash /REPLACE/WITH/PATH/TO/chips/scripts/run-prod.sh";
      Restart = "on-failure";
      RestartSec = 2;
    };
  };
}
