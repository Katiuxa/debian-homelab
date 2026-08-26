# Una sola vez: clave SSH para no escribir contraseña al actualizar
param(
    [string]$PiHost = "raspberrypi.local",
    [string]$PiUser = "admin",
    [string]$PiPassword = "1234"
)

$ErrorActionPreference = "Stop"
$SshDir = Join-Path $env:USERPROFILE ".ssh"
$Key = Join-Path $SshDir "id_ed25519_metavideo"
$Target = "${PiUser}@${PiHost}"
$SshNew = @("-o", "StrictHostKeyChecking=accept-new")

function Get-PlinkExe {
    if ($env:PLINK_PATH -and (Test-Path $env:PLINK_PATH)) { return $env:PLINK_PATH }
    $candidates = @(
        (Join-Path $PSScriptRoot "plink.exe"),
        "${env:ProgramFiles}\PuTTY\plink.exe",
        "${env:ProgramFiles(x86)}\PuTTY\plink.exe"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $cmd = Get-Command plink -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-PscpExe {
    if ($env:PSCP_PATH -and (Test-Path $env:PSCP_PATH)) { return $env:PSCP_PATH }
    $candidates = @(
        (Join-Path $PSScriptRoot "pscp.exe"),
        "${env:ProgramFiles}\PuTTY\pscp.exe",
        "${env:ProgramFiles(x86)}\PuTTY\pscp.exe"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $cmd = Get-Command pscp -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

if (-not (Test-Path $SshDir)) { New-Item -ItemType Directory -Path $SshDir -Force | Out-Null }

if (-not (Test-Path $Key)) {
    Write-Host "[*] Creando clave SSH (sin frase)..."
    & ssh-keygen -t ed25519 -f $Key -N "" -C "metavideo-pi" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "ssh-keygen fallo" }
}

$pub = (Get-Content "$Key.pub" -Raw -Encoding ASCII).Trim()
if (-not $pub) { throw "No se leyo $Key.pub" }

Write-Host "[*] Copiando clave a la Pi (admin@$PiHost)..."
$tmpPub = Join-Path $env:TEMP "metavideo_setup_key.pub"
[System.IO.File]::WriteAllText($tmpPub, "$pub`n", [System.Text.UTF8Encoding]::new($false))
$remote = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat /tmp/_metavideo_setup_key.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && rm -f /tmp/_metavideo_setup_key.pub && echo OK"

try {
    $plink = Get-PlinkExe
    $pscp = Get-PscpExe
    if ($PiPassword -and $plink) {
        Write-Host "[*] Usando plink (sin pedir contraseña en pantalla)."
        $plinkArgs = @("-ssh", "-batch", "-pw", $PiPassword, $Target)
        if ($pscp) {
            & $pscp @(@("-batch", "-pw", $PiPassword) + $SshNew + @($tmpPub, "${Target}:/tmp/_metavideo_setup_key.pub"))
            if ($LASTEXITCODE -ne 0) {
                & $plink @plinkArgs "mkdir -p /tmp" | Out-Null
                $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pub))
                & $plink @plinkArgs "echo $b64 | base64 -d > /tmp/_metavideo_setup_key.pub" | Out-Null
            }
        } else {
            & scp @SshNew $tmpPub "${Target}:/tmp/_metavideo_setup_key.pub"
            if ($LASTEXITCODE -ne 0) { exit 1 }
        }
        & $plink @plinkArgs $remote
        if ($LASTEXITCODE -ne 0) { exit 1 }
    } else {
        if ($PiPassword -and -not $plink) {
            Write-Host "[AVISO] Sin PuTTY plink: escribe contraseña admin ($PiPassword) cuando SSH lo pida (2 veces max)."
            Write-Host "        Para no escribirla: winget install PuTTY.PuTTY  y vuelve a ejecutar."
        } else {
            Write-Host "[*] Te pedira contraseña de admin UNA vez si aun no hay clave."
        }
        & scp @SshNew $tmpPub "${Target}:/tmp/_metavideo_setup_key.pub"
        if ($LASTEXITCODE -ne 0) { exit 1 }
        & ssh @SshNew $Target $remote
        if ($LASTEXITCODE -ne 0) { exit 1 }
    }
}
finally {
    Remove-Item -LiteralPath $tmpPub -Force -ErrorAction SilentlyContinue
}

$cfg = Join-Path $SshDir "config"
$block = @"

# MetavideoToText bot (generado por setup_ssh_key.ps1)
Host pi-bot
    HostName $PiHost
    User $PiUser
    IdentityFile $Key
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
"@

if (-not (Test-Path $cfg) -or -not (Select-String -Path $cfg -Pattern "Host pi-bot" -Quiet)) {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::AppendAllText($cfg, $block, $utf8)
    Write-Host "[OK] Entrada pi-bot en $cfg"
}

Write-Host "[*] Probando sin contraseña..."
& ssh -o BatchMode=yes -o IdentitiesOnly=yes -i $Key pi-bot "echo sin_password_ok" 2>$null
if ($LASTEXITCODE -ne 0) {
    & ssh -o BatchMode=yes -o IdentitiesOnly=yes -i $Key $Target "echo sin_password_ok"
}
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== LISTO ==="
    Write-Host "A partir de ahora usa:  PI.cmd actualizar"
    Write-Host "No deberia pedir contraseña."
} else {
    Write-Host "[AVISO] Prueba fallo. Vuelve a ejecutar CONFIGURAR_SSH_PI.cmd"
    Write-Host "        Si sigue fallando, en la Pi revisa: ls -la ~/.ssh"
    exit 1
}
