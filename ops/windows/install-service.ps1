<#
  Registra ARES como servicio de Windows con NSSM, para que `ares serve`
  arranque sin sesión iniciada y se reinicie solo si cae.
  Ejecutar como administrador, una sola vez, en el HP de producción.

  Requisitos previos (ver README de este mismo directorio):
    - Repositorio en C:\ares, `uv sync` ya ejecutado.
    - NSSM instalado: winget install --id NSSM.NSSM -e
#>

$ErrorActionPreference = "Stop"

$RepoDir = "C:\ares"
$ServiceName = "ARESPhysiology"
$Python = Join-Path $RepoDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "No se encuentra $Python. Ejecuta 'uv sync' en $RepoDir primero."
}

$nssm = (Get-Command nssm -ErrorAction SilentlyContinue)
if (-not $nssm) {
    throw "nssm no está en el PATH. Instala con: winget install --id NSSM.NSSM -e"
}

nssm install $ServiceName $Python "-m ares.cli serve"
nssm set $ServiceName AppDirectory $RepoDir
nssm set $ServiceName DisplayName "ARES Physiology"
nssm set $ServiceName Description "Proceso unico de ARES: base de datos + planificador interno."
nssm set $ServiceName Start SERVICE_AUTO_START
nssm set $ServiceName AppStdout (Join-Path $RepoDir "ops\windows\service-stdout.log")
nssm set $ServiceName AppStderr (Join-Path $RepoDir "ops\windows\service-stderr.log")
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760
# Reinicia si el proceso cae, con una pequeña espera entre intentos.
nssm set $ServiceName AppExit Default Restart
nssm set $ServiceName AppRestartDelay 15000

Write-Host "Servicio '$ServiceName' registrado. Para arrancarlo: nssm start $ServiceName"
Write-Host "Para ver su estado: Get-Service $ServiceName"
Write-Host "Para desinstalarlo: nssm remove $ServiceName confirm"
