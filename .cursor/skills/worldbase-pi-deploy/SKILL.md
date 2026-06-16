---
name: worldbase-pi-deploy
description: Deploy the WorldBase synchronization scripts to the Raspberry Pi edge node safely. Use when modifying Pi-sync code (worldbase_push.py, worldbase_pull.py) or when the operator requests an edge deployment.
disable-model-invocation: true
---

# WorldBase Edge Node Deployment

This skill handles the safe deployment of Python synchronization scripts to the Off-Grid Node (OGN) Raspberry Pi.

## Instructions

When modifications are made to the edge scripts in `offgrid-raspi/scripts/`, follow this deployment protocol strictly:

### 1. Line-Ending Enforcement (CRLF to LF)
Windows `scp` will transfer `\r\n` (CRLF) line endings, which corrupts the `#!/usr/bin/env python3` shebang on Linux.
**Never** use `tr -d '\r'` on the Pi to fix this. Instead, rely solely on the official deploy script which handles encoding safely during transfer.

### 2. Deployment Execution
Run the deploy script from the project root. You must explicitly ask the user if they want to deploy just the sync scripts, or also update the portal UI:
```powershell
# Basic sync script update
.\scripts\deploy-pi-sync.ps1

# Full update including the portal UI
.\scripts\deploy-pi-sync.ps1 -Portal
```

### 3. Verification
After deployment, advise the operator to check the Pi's systemd journal to ensure the services restarted smoothly:
```bash
# Execute via SSH on the Pi:
sudo journalctl -u offgrid-world-sync -n 20 --no-pager
```

## Quality Standards
- Do not edit `worldbase_push.py` or `worldbase_pull.py` without testing the PC-side endpoints (`/api/node/ingest` and `/api/node/pull`) first.
- Always warn the user before executing the deploy script, as it requires SSH access and potentially passwords/keys loaded in their environment.