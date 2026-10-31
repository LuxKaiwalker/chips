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
# CHIPS_PASSPHRASE is read from an EnvironmentFile, not declared here --
# configuration.nix is typically world-readable, so a real secret has no
# business living in it in plaintext. Create the file with:
#   sudo install -m 600 -o root -g root /dev/null /etc/chips-backend.env
#   echo 'CHIPS_PASSPHRASE=yourrealpassphrase' | sudo tee /etc/chips-backend.env

{ config, pkgs, ... }:

{
  services.nginx.appendHttpConfig = ''
    limit_req_zone $binary_remote_addr zone=chips_general:10m rate=10r/s;
    # ~1 attempt per 10s/IP -- the one brute-forceable secret in this app.
    limit_req_zone $binary_remote_addr zone=chips_auth:10m rate=6r/m;
  '';

  services.nginx.virtualHosts."your-chips-api.example.com" = {
    listen = [ { addr = "127.0.0.1"; port = 8080; } ];
    extraConfig = ''
      set_real_ip_from 127.0.0.1;
      real_ip_header CF-Connecting-IP;
      client_max_body_size 1m;
    '';
    locations."= /api/auth/passphrase" = {
      proxyPass = "http://127.0.0.1:8001";
      extraConfig = ''
        limit_req zone=chips_auth burst=2 nodelay;

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
        add_header Access-Control-Allow-Headers "Content-Type, X-Session-Token" always;
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
  # CHIPS_PASSPHRASE comes from /etc/chips-backend.env (root:root, mode
  # 600), NOT from configuration.nix -- that file is world-readable
  # (0644), so the real passphrase has no business living there in
  # plaintext. systemd reads EnvironmentFile as root before dropping to
  # User below, so the vincent user never needs read access to it either.
  # Create it with:
  #   sudo install -m 600 -o root -g root /dev/null /etc/chips-backend.env
  #   echo 'CHIPS_PASSPHRASE=yourrealpassphrase' | sudo tee /etc/chips-backend.env
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
      ExecStart = "/REPLACE/WITH/PATH/TO/chips/scripts/run-prod.sh";
      Restart = "on-failure";
      RestartSec = 2;
    };
  };
}
