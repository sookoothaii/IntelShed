# fix_vnc_via_ssh.ps1 — Diagnose und Fix VNC-Probleme auf dem Pi via SSH
# Run on Windows PC

$PI_IP   = "192.168.1.121"
$PI_USER = "user0"
$PI_KEY  = "$env:USERPROFILE\.ssh\offgrid-pi"
$SshExe  = "C:\Program Files\Git\usr\bin\ssh.exe"

Write-Host "=== VNC Fix via SSH ===" -ForegroundColor Cyan
Write-Host "Pi: ${PI_USER}@${PI_IP}" -ForegroundColor Gray
Write-Host ""

# SSH-Befehl Helper
function Invoke-PiSSH($cmd, $desc) {
    Write-Host "[$desc]..." -NoNewline -ForegroundColor Yellow
    $result = & $SshExe -o StrictHostKeyChecking=no -o ConnectTimeout=10 `
        -i $PI_KEY "${PI_USER}@${PI_IP}" $cmd 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-Host " OK" -ForegroundColor Green
        return $result
    } else {
        Write-Host " FAIL (exit $exitCode)" -ForegroundColor Red
        Write-Host "  Error: $result" -ForegroundColor Red
        return $null
    }
}

# 1. Verbindungstest
Write-Host "1. SSH-Verbindungstest..." -ForegroundColor Cyan
$test = Invoke-PiSSH "echo PONG" "SSH Connect"
if (-not $test -or $test -notmatch "PONG") {
    Write-Host "`nSSH-Verbindung fehlgeschlagen!" -ForegroundColor Red
    Write-Host "Pruefen Sie:" -ForegroundColor Yellow
    Write-Host "  - Ist der Pi eingeschaltet?" -ForegroundColor Yellow
    Write-Host "  - Ping: ping $PI_IP" -ForegroundColor Yellow
    Write-Host "  - SSH-Key existiert: $PI_KEY" -ForegroundColor Yellow
    exit 1
}

# 2. IP-Adresse bestätigen
Write-Host "`n2. Pi Netzwerk-Info:" -ForegroundColor Cyan
$ipInfo = Invoke-PiSSH "hostname -I" "IP Address"
Write-Host "   Pi IP: $ipInfo" -ForegroundColor Gray

# 3. VNC Service Status
Write-Host "`n3. VNC Service Status:" -ForegroundColor Cyan
$vncStatus = Invoke-PiSSH "systemctl is-active vncserver-x11-serviced" "VNC Active"
if ($vncStatus -match "active") {
    Write-Host "   VNC Server: LAUFEND" -ForegroundColor Green
} else {
    Write-Host "   VNC Server: NICHT AKTIV" -ForegroundColor Red
    Write-Host "   Starte VNC Server..." -ForegroundColor Yellow
    Invoke-PiSSH "sudo systemctl enable vncserver-x11-serviced && sudo systemctl start vncserver-x11-serviced" "VNC Start"
}

# 4. Port 5900 Check
Write-Host "`n4. Port 5900 Check:" -ForegroundColor Cyan
$portStatus = Invoke-PiSSH "ss -tlnp | grep 5900" "Port Check"
if ($portStatus) {
    Write-Host "   Port 5900: BELEGT" -ForegroundColor Green
    Write-Host "   $portStatus" -ForegroundColor Gray
} else {
    Write-Host "   Port 5900: NICHT BELEGT" -ForegroundColor Red
}

# 5. UFW Firewall Status
Write-Host "`n5. Firewall Status (UFW):" -ForegroundColor Cyan
$ufwStatus = Invoke-PiSSH "sudo ufw status | grep -E '(5900|vnc)'" "UFW VNC Rules"
if ($ufwStatus) {
    Write-Host "   UFW Regeln fuer VNC:" -ForegroundColor Green
    Write-Host "   $ufwStatus" -ForegroundColor Gray
} else {
    Write-Host "   KEINE UFW-Regel fuer Port 5900 gefunden!" -ForegroundColor Red
    Write-Host "   Fuege Firewall-Regel hinzu..." -ForegroundColor Yellow
    
    # UFW Regel hinzufuegen
    $lanSubnet = Invoke-PiSSH "hostname -I | awk '{print \$1}' | sed 's/\.[0-9]*\$/.0\/24/'" "LAN Subnet"
    Write-Host "   LAN Subnet: $lanSubnet" -ForegroundColor Gray
    
    Invoke-PiSSH "sudo ufw allow from $lanSubnet to any port 5900 proto tcp comment 'offgrid-vnc-lan'" "Add UFW Rule"
    Invoke-PiSSH "sudo ufw reload" "Reload UFW"
}

# 6. Full UFW Status anzeigen
Write-Host "`n6. Komplette UFW Konfiguration:" -ForegroundColor Cyan
$fullUfw = Invoke-PiSSH "sudo ufw status numbered" "Full UFW"
Write-Host $fullUfw

# 7. VNC Service Details
Write-Host "`n7. VNC Service Details:" -ForegroundColor Cyan
$vncDetails = Invoke-PiSSH "systemctl status vncserver-x11-serviced --no-pager 2>&1 | head -20" "VNC Details"
Write-Host $vncDetails

# 8. Test von PC aus
Write-Host "`n8. VNC-Verbindungstest von PC:" -ForegroundColor Cyan
Write-Host "   Teste Port 5900..." -NoNewline -ForegroundColor Yellow
$tcpTest = Test-NetConnection -ComputerName $PI_IP -Port 5900 -WarningAction SilentlyContinue
if ($tcpTest.TcpTestSucceeded) {
    Write-Host " ERREICHBAR" -ForegroundColor Green
    Write-Host "`n=== VNC IST JETZT VERFUEGBAR ===" -ForegroundColor Green
    Write-Host "Verbinden mit: ${PI_IP}:5900" -ForegroundColor Cyan
    Write-Host "Oder starten: .\scripts\pi_remote_desktop.ps1" -ForegroundColor Cyan
} else {
    Write-Host " NICHT ERREICHBAR" -ForegroundColor Red
    Write-Host "`n=== VNC NOCH IMMER BLOCKIERT ===" -ForegroundColor Red
    Write-Host "Moegliche Gruende:" -ForegroundColor Yellow
    Write-Host "  - UFW nicht aktiv: sudo ufw enable" -ForegroundColor Yellow
    Write-Host "  - Anderer Firewall-Block (Router?)" -ForegroundColor Yellow
    Write-Host "  - VNC Server nicht richtig gestartet" -ForegroundColor Yellow
}

Write-Host "`nFertig." -ForegroundColor Cyan
