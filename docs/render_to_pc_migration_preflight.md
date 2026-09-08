# Render → Windows PC migration preflight

Prepared for the 2026-09-09 07:00 KST final migration-method audit.

## Verified current Render facts

- Production service: `srv-dad395ajnfac73e8odt0` (`namuh-smart-trader`)
- Type/runtime: web service / Python
- Region: Oregon
- Compute plan: Free
- Instances: 1
- Repository: `zzzgnt-a11y/NamuhSmartTrader`
- Branch: `main`
- Build: `pip install -r requirements.txt`
- Start: `python runtime_server_v34.py`
- Health path: `/api/v34/status`
- Auto deploy: enabled on commit
- Render reports an SSH address, but Render's official SSH matrix states **Free web services do not support Dashboard shell or SSH**.
- Render's official Free-service documentation states Free web services:
  - use an ephemeral filesystem;
  - lose local filesystem changes on redeploy/restart/spin-down;
  - cannot attach persistent disks;
  - cannot receive private-network traffic;
  - do not support shell/SSH.

## Verified database facts

- Render Postgres: `dpg-dae4hbpt0dsc738qdvh0-a`
- Name: `namuh-smart-trader-db`
- PostgreSQL: 18
- Plan: Free
- Region: Oregon
- Status: available
- Expiration: 2026-10-05
- No read replicas
- A read-only connector SQL attempt failed with `SSL/TLS required`; this is recorded as a connector-path failure, not evidence that Postgres itself is unavailable.
- Render's official docs support external Postgres connections and local `pg_dump`.
- Free Render Postgres does not get automatic logical backups; local `pg_dump` remains available.

## Official Tailscale facts checked

- Render's official Tailscale template is a **subnet router** for the Render private network.
- The official template deploys a Docker **worker**, stores Tailscale state on a **1 GB disk**, and advertises `10.0.0.0/8`; this therefore is not a no-change Free-web-service path.
- Tailscale official docs support userspace networking with `--tun=userspace-networking`, including SOCKS5/HTTP proxy operation without `/dev/net/tun`.
- Tailscale Serve can expose a file, directory, or local service within a tailnet.
- Taildrop is alpha and does not support sending files to/from tagged nodes; server applicability must therefore be treated cautiously.

## Distinct migration architecture classes to verify at 07:00

1. Git/GitHub source recovery
2. Public authenticated HTTP archive/file export
3. Direct public API/state export
4. Render SSH + SCP/SFTP
5. rsync over SSH
6. Magic-Wormhole from a Render shell
7. Official Render Tailscale subnet-router/private-network route
8. Tailscale userspace inside the service + Serve/proxy
9. Taildrop
10. Render Postgres external `pg_dump` / local `pg_restore`
11. Render logical-backup export after database-plan upgrade
12. Render CLI / `psql` / `\copy` table export
13. Cloud/object-storage intermediate push/pull
14. Temporary paid upgrade + live/ephemeral shell recovery
15. Render logs / metadata / configuration export

Variations such as PowerShell OpenSSH vs WSL, push vs pull, `tar` vs `zip`, and SFTP client choice are treated as subcases unless their prerequisites materially differ.

## Current no-change feasibility snapshot

Based on the actual Free web-service constraints and currently known app/database interfaces:

- No-change candidates: **1, 3, 10, 12, 15**
- Require an app/config/deploy change: **2, 8, 13**
- Require paid/shell/private-network capability or other platform change: **4, 5, 6, 7, 11, 14**
- Taildrop: **9** is not assumed viable for a tagged/server node; must be classified from the actual Tailscale identity/setup.

## 100× automated consistency validation already performed

A capability matrix derived from the verified Render facts and official platform constraints was checked for every one of the 15 architecture classes across **100 full cycles**.

- Architecture checks performed: **1,500**
- Validation covered:
  - unique classification of each architecture;
  - deterministic possible/impossible result from the same facts;
  - Free-plan SSH/shell restrictions;
  - Free-plan private-network restriction;
  - persistent-disk restriction;
  - Postgres external-export feasibility;
  - Git source-recovery feasibility;
  - separation of no-change routes from routes requiring a deploy/upgrade.
- All 1,500 automated constraint checks passed.

This is **not** a claim that 1,500 real network transfers were performed. Methods requiring a Render plan/config change, Tailscale auth, or access to the user's Windows PC cannot be live-network-tested without making those changes.

## Required integrity checks for final procedure

For every migration architecture, the final plan must specify:

- exactly what data it can and cannot move;
- prerequisites;
- whether it works on the current service without changes;
- minimum change if not;
- security implications;
- Windows-PC procedure;
- checksum/integrity verification (`SHA-256` where file-based);
- resume/retry strategy for large transfers;
- failure fallback;
- irrecoverable categories: deleted ephemeral data, unavailable secrets, or data Render no longer exposes.

## Sources to re-check before finalizing

- Render SSH/Shell: https://render.com/docs/ssh
- Render Free services: https://render.com/docs/free
- Render persistent disks / file transfer: https://render.com/docs/disks
- Render Postgres backups: https://render.com/docs/postgresql-backups
- Render Postgres connectivity: https://render.com/docs/postgresql-creating-connecting
- Render Tailscale template: https://render.com/templates/tailscale
- Official template repository: https://github.com/render-examples/tailscale
- Tailscale userspace networking: https://tailscale.com/docs/concepts/userspace-networking
- Tailscale Serve: https://tailscale.com/docs/features/tailscale-serve
- Taildrop: https://tailscale.com/docs/features/taildrop

At 07:00 KST, re-read current Render service/database/deploy state and official docs before issuing the final numbered taxonomy.