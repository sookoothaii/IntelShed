# Docker repair (Windows) — WorldBase / Flowsint

## Clean reinstall (recommended if repair never worked)

**Why repair failed:** DISM hung at 62 %; `/LimitAccess` returned `0x800f0915` (no repair source). Partial installs since Nov 2025 never got a working WSL engine.

**Clean slate** removes Docker + docker-desktop WSL distros + `%LOCALAPPDATA%\Docker`, then installs fresh via `wsl --install` + winget (no DISM required if that works).

```powershell
# Administrator PowerShell
Set-Location "D:\MCP Mods\worldbase"
.\scripts\docker-clean-reinstall.ps1
# REBOOT
wsl --install --no-distribution
# REBOOT if asked
winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
```

Start **Docker Desktop**, wait for **Engine running**, then `docker version` and `.\scripts\start-flowsint.ps1 -Build`.

**Keep:** Other WSL distros (Ubuntu etc.) are only removed if named `docker-desktop` / `docker-desktop-data`. Check with `wsl -l -v` before running the script.

**Nuclear option (only if `wsl --install` still fails):** Windows Settings -> System -> Recovery -> **Reset this PC** (keep my files) — last resort, not in the script.

## Blocker: `WSL_E_INSTALL_COMPONENT_FAILED` / DISM `14098` / Komponentenspeicher

`wsl --install` cannot enable **VirtualMachinePlatform** until the Windows component store is healthy.

**Check BIOS + firmware:**

```powershell
.\scripts\docker-preflight.ps1
# or: msinfo32 -> "Virtualisierung im Firmware aktiviert" = Ja
```

If **Nein**: reboot into BIOS/UEFI, enable **Intel VT-x** / **AMD-V** / **SVM**.

**Fix component store (pick one):**

1. **Online DISM** (internet, no `/LimitAccess`):

   ```powershell
   DISM /Online /Cleanup-Image /RestoreHealth
   ```

   Reboot, then `wsl --install --no-distribution`.

2. **GUI optional features:** Settings -> Apps -> Optional features -> More Windows features -> enable **Virtual Machine Platform** -> reboot. If it fails, the store is still corrupt.

3. **In-place repair upgrade** (keeps apps/files): download Windows 11 ISO, run `setup.exe` from ISO, choose **Upgrade this PC**. Heavy but fixes CBS often when DISM cannot.

4. **DISM with ISO source** — see Microsoft link in DISM `0x800f0915` message; mount ISO, use `/Source:WIM:...`.

Until **VirtualMachinePlatform** shows `Enabled`, Docker Desktop and Flowsint **cannot** run on this PC.

---

## Diagnosis (2026-06-03)

| Finding | Detail |
|---------|--------|
| `docker` CLI | **Not on PATH** — no install under `C:\Program Files\Docker` |
| Leftover data | `%LOCALAPPDATA%\Docker` (installer logs Nov 2025) |
| **WslService** | **Disabled**, Stopped |
| Docker log error | `Wsl/0x80070422` — service disabled or no enabled devices |

Docker Desktop 4.50 was started once; the **Linux/WSL engine never started** because WSL was disabled.

## Fix (requires Administrator)

1. Open **PowerShell as Administrator** (not normal Cursor terminal).

2. Run:

```powershell
Set-Location "D:\MCP Mods\worldbase"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\docker-repair-admin.ps1
```

3. **Reboot** Windows when the script finishes (WSL features often need it).

4. After reboot: start **Docker Desktop** from the Start menu; wait until the whale icon shows **Engine running**.

5. Verify:

```powershell
docker version
wsl --status
```

6. Start Flowsint:

```powershell
Set-Location "D:\MCP Mods\worldbase"
.\scripts\start-flowsint.ps1 -Build
```

## Component store corrupt (`Komponentenspeicher wurde beschädigt`)

If `VirtualMachinePlatform` fails but `WslService` started OK:

1. Admin PowerShell:

```powershell
Set-Location "D:\MCP Mods\worldbase"
.\scripts\docker-repair-component-store.ps1
```

2. **Reboot** (mandatory after DISM/SFC).

3. Re-run:

```powershell
.\scripts\docker-repair-admin.ps1
```

4. Reboot again if prompted, then Docker Desktop + `docker version`.

`Microsoft-Windows-Subsystem-Linux` may already be enabled from the first run; WSL2 needs **both** features + **VirtualMachinePlatform**.

## DISM error 0x800f0915 (`Der Reparaturinhalt wurde nirgends gefunden`)

Often after `/LimitAccess`: DISM cannot use Windows Update and has no local source.

**Try A — online repair (needs internet, no LimitAccess):**

```powershell
DISM /Online /Cleanup-Image /RestoreHealth
```

**Try B — enable WSL2 without waiting for DISM (after reboot):**

```powershell
wsl --install --no-distribution
# or
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All
```

**Try C — repair from Windows ISO** (if A fails): mount ISO, then:

```powershell
# Adjust drive letter and index (often 1 for Windows 11 Pro)
DISM /Online /Cleanup-Image /RestoreHealth /Source:WIM:X:\sources\install.wim:1 /LimitAccess
```

Download matching ISO from Microsoft (same build family as `winver`).

## Manual alternative (if script fails)

1. `Win + R` → `services.msc` → find **WSL Service** → Startup type **Automatic** → **Start**.

2. Settings → Apps → Optional features → enable **Windows Subsystem for Linux** and **Virtual Machine Platform**.

3. Admin PowerShell: `wsl --update` then `wsl --set-default-version 2`.

4. Install: https://www.docker.com/products/docker-desktop/ or `winget install Docker.DockerDesktop`.

## Bitdefender / hypervisor

If Docker still fails after reboot, check Bitdefender exclusions for `Docker Desktop.exe` and ensure **Hyper-V / WSL2** is not blocked in antivirus “Advanced Threat Defense”.

## Log file

`worldbase/docker-repair.log` after running the admin script.
