# Copia proyecto a la Pi + reinicio (sin tar por tuberia: falla en Windows CMD)
param(
    [string]$PiHost = "raspberrypi.local",
    [string]$PiUser = "admin",
    [switch]$RunUpdate
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RemoteDir = "/home/$PiUser/MetavideoToText_bot"
$RemoteArchive = "/tmp/metavideo_deploy.tar.gz"

if (Test-Path "$env:USERPROFILE\.ssh\config") {
    if (Select-String -Path "$env:USERPROFILE\.ssh\config" -Pattern "Host pi-bot" -Quiet) {
        $SshTarget = "pi-bot"
    } else {
        $SshTarget = "${PiUser}@${PiHost}"
    }
} else {
    $SshTarget = "${PiUser}@${PiHost}"
}

$KeyFile = "$env:USERPROFILE\.ssh\id_ed25519_metavideo"
$SshBase = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=30")
if (Test-Path $KeyFile) {
    $SshBase += @("-i", $KeyFile)
}

function Invoke-Ssh([string]$RemoteCmd) {
    & ssh @SshBase $SshTarget $RemoteCmd
    return $LASTEXITCODE
}

function Invoke-Scp([string]$Local, [string]$Remote) {
    & scp @SshBase $Local "${SshTarget}:${Remote}"
    return $LASTEXITCODE
}

Set-Location -LiteralPath $ProjectDir
Write-Host "[*] Origen: $ProjectDir"
Write-Host "[*] Destino: ${PiUser}@${PiHost}:$RemoteDir"

& ssh @($SshBase + @("-o", "BatchMode=yes")) pi-bot "echo ok" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    & ssh @($SshBase + @("-o", "BatchMode=yes")) $SshTarget "echo ok" 2>$null | Out-Null
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[*] Sin clave SSH. Configurando automaticamente (admin / 1234)..."
    $setup = Join-Path $PSScriptRoot "setup_ssh_key.ps1"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $setup -PiHost $PiHost -PiUser $PiUser -PiPassword "1234"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] SSH sin clave. Ejecuta CONFIGURAR_SSH_PI.cmd o: winget install PuTTY.PuTTY"
        exit 1
    }
    if (Select-String -Path "$env:USERPROFILE\.ssh\config" -Pattern "Host pi-bot" -Quiet) {
        $SshTarget = "pi-bot"
    }
    & ssh @($SshBase + @("-o", "BatchMode=yes")) $SshTarget "echo ok" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Tras configurar SSH sigue fallando."
        exit 1
    }
}
Write-Host "[*] Clave SSH OK."
$SshOpts = $SshBase

$afterExtract = @(
    "cd $RemoteDir",
    "find deploy bot -type f \( -name '*.sh' -o -name '*.py' \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true"
) -join " && "
if ($RunUpdate) {
    $afterExtract += " && bash deploy/update_on_pi.sh"
}

$archive = Join-Path $env:TEMP "metavideo_deploy_$([Guid]::NewGuid().ToString('N')).tar.gz"
$copyOk = $false

try {
    if (Get-Command tar -ErrorAction SilentlyContinue) {
        Write-Host "[*] Empaquetando (tar.gz local)..."
        & tar -czf $archive `
            --exclude=".venv" `
            --exclude="temp" `
            --exclude="__pycache__" `
            --exclude="*.pyc" `
            -C $ProjectDir .
        if ($LASTEXITCODE -eq 0 -and (Test-Path $archive) -and ((Get-Item $archive).Length -gt 1000)) {
            Write-Host "[*] Subiendo a la Pi..."
            if ((Invoke-Scp $archive $RemoteArchive) -eq 0) {
                Write-Host "[*] Descomprimiendo en la Pi..."
                $cmd = "mkdir -p $RemoteDir && tar -xzf $RemoteArchive -C $RemoteDir && rm -f $RemoteArchive && $afterExtract"
                if ((Invoke-Ssh $cmd) -eq 0) { $copyOk = $true }
            }
        } else {
            Write-Host "[AVISO] tar local fallo o archivo vacio."
        }
    }

    if (-not $copyOk) {
        Write-Host "[*] Copia por carpetas (scp)..."
        if ((Invoke-Ssh "mkdir -p $RemoteDir") -ne 0) { exit 1 }
        $items = @("bot", "run.py", "requirements.txt", "BOT_VERSION.txt", "deploy", "LANZAR_BOT.sh", "DETENER_BOT.sh")
        foreach ($item in $items) {
            if (-not (Test-Path $item)) { continue }
            Write-Host "  scp $item ..."
            if (Test-Path $item -PathType Container) {
                & scp @SshOpts -r $item "${SshTarget}:${RemoteDir}/"
            } else {
                & scp @SshOpts $item "${SshTarget}:${RemoteDir}/"
            }
            if ($LASTEXITCODE -ne 0) { exit 1 }
        }
        if (Test-Path ".env") {
            & scp @SshOpts ".env" "${SshTarget}:${RemoteDir}/.env"
        }
        if ($RunUpdate) {
            if ((Invoke-Ssh "sed -i 's/\r$//' $RemoteDir/deploy/update_on_pi.sh && bash $RemoteDir/deploy/update_on_pi.sh") -ne 0) {
                exit 1
            }
        } else {
            Invoke-Ssh "find $RemoteDir/deploy $RemoteDir/bot -type f \( -name '*.sh' -o -name '*.py' \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true" | Out-Null
        }
        $copyOk = $true
    }
}
finally {
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
}

if (-not $copyOk) {
    Write-Host "[ERROR] No se pudo copiar el codigo a la Pi."
    exit 1
}

Write-Host "[*] Verificando parche en la Pi..."
$verifyOut = & ssh @SshOpts $SshTarget "cd $RemoteDir && grep -q force_end_heavy_job bot/services/user_busy.py && grep -q _JOB_INVALID bot/services/user_busy.py && echo DEPLOY_OK || echo DEPLOY_FAIL" 2>&1
$verifyOut | ForEach-Object { Write-Host $_ }
if ($verifyOut -notmatch "DEPLOY_OK") {
    Write-Host "[ERROR] La Pi NO tiene el codigo nuevo."
    exit 1
}

Write-Host "[OK] Codigo copiado y verificado."
exit 0
