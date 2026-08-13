<#
.SYNOPSIS
    Configura exclusiones quirúrgicas en Windows Defender para el servidor de Minecraft Bedrock.

.DESCRIPTION
    Añade las carpetas de datos (worlds, resource_packs, behavior_packs) y la carpeta de
    Backups_Minecraft a las exclusiones de Windows Defender para evitar lentitud y bloqueos
    por inspección en la nube (MAPS / Cloud Lookup) en el primer acceso a archivos.
    - Requiere elevación a Administrador (solicita UAC automáticamente).
    - Totalmente idempotente (solo añade rutas no presentes).
    - Detecta si Defender está activo o si el sistema usa otro antivirus.
#>

[CmdletBinding()]
param()

# ═══════════════════════════════════════════════════════════════
# 1. AUTO-ELEVACIÓN A ADMINISTRADOR (UAC)
# ═══════════════════════════════════════════════════════════════
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "=========================================================" -ForegroundColor Cyan
    Write-Host "  Solicitando permisos de Administrador (UAC)..." -ForegroundColor Yellow
    Write-Host "=========================================================" -ForegroundColor Cyan
    try {
        $processArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        Start-Process powershell.exe -Verb RunAs -ArgumentList $processArgs
        exit 0
    } catch {
        Write-Host "No se pudo elevar privilegios: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# ═══════════════════════════════════════════════════════════════
# 2. RESOLUCIÓN DINÁMICA DE RUTAS (Independiente de CWD)
# ═══════════════════════════════════════════════════════════════
$ScriptDir = Split-Path -Parent $PSCommandPath
$BaseDir = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$ServerName = Split-Path -Leaf $BaseDir

$WorldsDir         = Join-Path $BaseDir "worlds"
$ResourcePacksDir  = Join-Path $BaseDir "resource_packs"
$BehaviorPacksDir  = Join-Path $BaseDir "behavior_packs"
$BackupsDir        = [System.IO.Path]::GetFullPath((Join-Path $BaseDir "..\..\Backups_Minecraft"))

$TargetPaths = @(
    $WorldsDir,
    $ResourcePacksDir,
    $BehaviorPacksDir,
    $BackupsDir
)

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host "  CONFIGURACION DE EXCLUSIONES DE WINDOWS DEFENDER" -ForegroundColor White
Write-Host "  Servidor: $ServerName" -ForegroundColor Gray
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# 3. VERIFICAR ESTADO DE DEFENDER / ANTIVIRUS
# ═══════════════════════════════════════════════════════════════
$defenderAvailable = $false
try {
    $mpStatus = Get-MpComputerStatus -ErrorAction Stop
    if ($mpStatus.AntivirusEnabled -or $mpStatus.AMServiceEnabled) {
        $defenderAvailable = $true
    }
} catch {
    $defenderAvailable = $false
}

if (-not $defenderAvailable) {
    Write-Host "[AVISO] Windows Defender no parece ser el antivirus activo en este sistema" -ForegroundColor Yellow
    Write-Host "        (puede estar desactivado por directivas o sustituido por un antivirus de terceros)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Para evitar lentitud en el backup inicial, añade manualmente estas carpetas" -ForegroundColor White
    Write-Host "a la lista de exclusiones de tu antivirus:" -ForegroundColor White
    Write-Host ""
    foreach ($p in $TargetPaths) {
        Write-Host "  - $p" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Si usas Seguridad de Windows estándar, puedes añadirlas en:" -ForegroundColor Gray
    Write-Host "  Inicio > Configuración > Privacidad y seguridad > Seguridad de Windows >" -ForegroundColor Gray
    Write-Host "  Protección contra virus y amenazas > Administrar la configuración >" -ForegroundColor Gray
    Write-Host "  Exclusiones > Agregar o quitar exclusiones > Carpeta." -ForegroundColor Gray
    Write-Host ""
    Read-Host "Presiona Enter para salir..."
    exit
}

# ═══════════════════════════════════════════════════════════════
# 4. APLICACIÓN IDEMPOTENTE DE EXCLUSIONES
# ═══════════════════════════════════════════════════════════════
$currentExclusions = @()
try {
    $pref = Get-MpPreference -ErrorAction Stop
    if ($pref.ExclusionPath) {
        $currentExclusions = @($pref.ExclusionPath) | ForEach-Object { [System.IO.Path]::GetFullPath($_).TrimEnd('\') }
    }
} catch {
    Write-Host "[ADVERTENCIA] No se pudo leer la lista actual de exclusiones: $($_.Exception.Message)" -ForegroundColor Yellow
}

$addedCount = 0
$existingCount = 0

foreach ($path in $TargetPaths) {
    $normalized = [System.IO.Path]::GetFullPath($path).TrimEnd('\')
    
    # Comprobar si ya está en la lista de exclusiones
    $alreadyExcluded = $false
    foreach ($curr in $currentExclusions) {
        if ($curr -eq $normalized) {
            $alreadyExcluded = $true
            break
        }
    }

    if ($alreadyExcluded) {
        Write-Host "  [YA EXISTE] $path" -ForegroundColor DarkGray
        $existingCount++
    } else {
        try {
            Add-MpPreference -ExclusionPath $path -ErrorAction Stop
            Write-Host "  [AGREGADA]  $path" -ForegroundColor Green
            $addedCount++
        } catch {
            Write-Host "  [ERROR]     $path ($($_.Exception.Message))" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "---------------------------------------------------------" -ForegroundColor Cyan
Write-Host "Resumen: $addedCount exclusiones agregadas, $existingCount ya configuradas previamente." -ForegroundColor White
Write-Host "Los backups iniciales y arranques ahora se ejecutarán a máxima velocidad (6-10 s)." -ForegroundColor Green
Write-Host "---------------------------------------------------------" -ForegroundColor Cyan
Write-Host ""

Read-Host "Presiona Enter para cerrar..."
