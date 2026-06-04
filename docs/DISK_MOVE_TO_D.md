# Move disk usage from C: to D: (safe)

C: was ~10 GB free; D: has ~1 TB free. Heavy folders on C: (typical):

| Folder | ~Size | Risk if deleted |
|--------|-------|-----------------|
| `%USERPROFILE%\.cache` | ~130 GB | pip/HF/npm caches — **move**, do not delete |
| `%USERPROFILE%\.cursor` | ~100 GB | IDE state — **move**, do not delete |
| Docker WSL VHD | grows with builds | **relocate via Docker Desktop UI** |

Projects (`D:\MCP Mods\worldbase`) already live on D:.

## Automated move (recommended)

Uses **directory junctions** (apps keep the same path; data sits on D:). No admin required in most cases.

```powershell
cd "D:\MCP Mods\worldbase"

# 1) Preview only
.\scripts\move-dev-data-to-d.ps1

# 2) Close Cursor + Docker Desktop (tray quit)

# 3) Apply
.\scripts\move-dev-data-to-d.ps1 -Execute

# Optional: one folder only
.\scripts\move-dev-data-to-d.ps1 -Execute -Only cache
```

**Rollback:** If `-Execute` fails mid-run, the script moves data back. If you need manual rollback after success:

```powershell
# Example for .cache — only if junction exists and D:\DevData\cache is intact
Remove-Item "$env:USERPROFILE\.cache" -Force   # removes junction only
Move-Item "D:\DevData\cache" "$env:USERPROFILE\.cache"
```

## Docker (manual, safest)

Do **not** delete `%LOCALAPPDATA%\Docker` by hand.

1. Quit Docker Desktop.
2. **Settings → Resources → Advanced → Disk image location** → `D:\Docker\wsl-data`
3. **Apply & Restart** and wait until **Engine running**.

Then:

```powershell
docker system prune -a   # optional, only if old images unneeded
.\scripts\start-flowsint.ps1 -Build
```

## After move

Target: **≥30 GB free on C:** before large Flowsint builds.

```powershell
Get-PSDrive C,D | Format-Table Name, @{N='FreeGB';E={[math]::Round($_.Free/1GB,2)}}
```

## What we avoid

- Deleting `.cache` or `.cursor` without moving
- Moving folders while Cursor/Docker are running
- Editing `C:\Windows` or `Program Files`
