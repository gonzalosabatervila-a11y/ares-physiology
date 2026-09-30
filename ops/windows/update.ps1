<#
  Actualiza ARES en el HP desde GitHub, con red de seguridad.

    1. Enseña los cambios que llegan y no toca nada si no hay ninguno.
    2. Se niega a seguir si hay cambios locales sin guardar (para no perderlos).
    3. Trae el código (solo avance limpio), instala dependencias y pasa las pruebas.
    4. Si algo falla ANTES de reiniciar, vuelve a la versión anterior y no toca el servicio.
    5. Reinicia el servicio y espera a que la app responda; si no responde, vuelve atrás.

  Uso (PowerShell como administrador: reinicia un servicio):
    powershell -ExecutionPolicy Bypass -File C:\ares\ops\windows\update.ps1
    powershell -ExecutionPolicy Bypass -File C:\ares\ops\windows\update.ps1 -Check   # solo mira

  Requisito: la clave de despliegue de solo lectura de GitHub (ver README de este directorio).
#>
param(
    [switch]$Check,
    [string]$Repo = "C:\ares",
    [string]$Health = "http://127.0.0.1:8443/api/lab",
    [int]$HealthTries = 30,
    [int]$HealthWait = 2
)

$Service = "ARESPhysiology"
$Branch = "master"

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Rollback($why, $restart) {
    Write-Host "Vuelvo a la version anterior ($($before.Substring(0,7))): $why" -ForegroundColor Yellow
    git reset --hard $before | Out-Null
    uv sync | Out-Null
    if ($restart) { nssm restart $Service | Out-Null }
    exit 1
}

Set-Location $Repo
$before = (git rev-parse HEAD).Trim()

git fetch origin
if ($LASTEXITCODE -ne 0) { Fail "no puedo hablar con GitHub (git fetch). Revisa la clave de despliegue." }
$remote = (git rev-parse "origin/$Branch").Trim()

if ($before -eq $remote) {
    Write-Host "Ya estas en la ultima version ($($before.Substring(0,7)))."
    exit 0
}

git merge-base --is-ancestor $before $remote
if ($LASTEXITCODE -ne 0) {
    Fail "el HP tiene commits que no estan en GitHub, asi que no se puede avanzar limpiamente. Si son solo el commit local del zip, alinealo con: git reset --hard origin/$Branch"
}

Write-Host "Cambios que llegan:"
git log --oneline "$before..$remote"

if ($Check) {
    Write-Host "(solo comprobacion: no se ha cambiado nada)"
    exit 0
}

$dirty = git status --porcelain --untracked-files=no
if ($dirty) { Fail "hay cambios locales sin guardar en $Repo; no actualizo para no perderlos." }

git merge --ff-only "origin/$Branch"
if ($LASTEXITCODE -ne 0) { Fail "no se pudo avanzar limpiamente." }

uv sync
if ($LASTEXITCODE -ne 0) { Rollback "uv sync ha fallado" $false }

uv run pytest -q
if ($LASTEXITCODE -ne 0) { Rollback "las pruebas fallan" $false }

nssm restart $Service
$ok = $false
for ($i = 0; $i -lt $HealthTries; $i++) {
    Start-Sleep -Seconds $HealthWait
    try {
        $r = Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { Rollback "la app no responde tras reiniciar" $true }

Write-Host "Actualizado a $(git rev-parse --short HEAD). Servicio en marcha." -ForegroundColor Green
