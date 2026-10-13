# ARES en Windows — servicio con NSSM

## Requisitos

- `C:\ares` clonado, con `uv sync` ya ejecutado (ver README principal del repo).
- Los secretos ya guardados con `ares secret set ...`.
- `ares whoop-auth` autorizado previamente **en el HP**, en una sesión interactiva
  del mismo usuario que ejecutará el servicio. El Llavero del Mac no comparte
  secretos con Windows y la autorización no debe hacerse desde NSSM.
- NSSM instalado: `winget install --id NSSM.NSSM -e`

## Instalar

```powershell
cd C:\ares
.\ops\windows\install-service.ps1
nssm start ARESPhysiology
```

## Comprobar

```powershell
Get-Service ARESPhysiology
Get-Content C:\ares\ops\windows\service-stdout.log -Tail 20
uv run ares stats
```

Debe aparecer una entrada en `job_runs` con `status = ok` poco después de arrancar
(la primera pasada de sincronización se lanza al iniciar, sin esperar al próximo
tramo del planificador).

## Quién ejecuta el servicio

Por defecto, NSSM lo instala con la cuenta `Local System`. **El Administrador de
credenciales de Windows es por usuario**, así que con `Local System` el servicio
no vería las claves guardadas con tu cuenta. Dos opciones:

- Configurar el servicio para que corra con tu cuenta de usuario (pestaña *Log on*
  en `services.msc`, o `nssm set ARESPhysiology ObjectName <usuario> <contraseña>`).
  Es la opción más simple mientras el HP tenga un único usuario real.
- Mover los secretos a variables de entorno de máquina, si algún día el servicio
  necesita correr con una cuenta de servicio dedicada. No implementado en v0.3.

## Reinicio automático

`AppExit Default Restart` hace que NSSM relance el proceso si cae, con 15s de
espera. Combinado con el arranque automático (`SERVICE_AUTO_START`) y con que
Windows Update solo reinicia dentro de las horas activas configuradas (05:00–23:00),
el servicio debería quedar vivo salvo intervención manual o fallo repetido.

## Desinstalar

```powershell
nssm stop ARESPhysiology
nssm remove ARESPhysiology confirm
```


## La app dentro del servicio (v0.5)

`ares serve` lleva dentro la app local (Inicio, Progreso, Lab) en `http://127.0.0.1:8443`,
porque DuckDB solo deja abrir la base a un proceso: **con el servicio en marcha, `ares stats`,
`ares sync` y `ares app` no pueden abrirla** y avisan con un mensaje claro. Para mirar el
estado, usa la app o:

```powershell
Invoke-RestMethod http://127.0.0.1:8443/api/lab | ConvertTo-Json -Depth 5
Get-Content C:\ares\ops\windows\service-stdout.log -Tail 30
```

Si necesitas usar la línea de comandos: `nssm stop ARESPhysiology`, tus comandos y
`nssm start ARESPhysiology`.

## Verlo desde el iPhone o el Mac (Tailscale Serve)

```powershell
tailscale serve --bg 8443
tailscale serve status
```

Publica la app solo en tu red privada de Tailscale, en `https://ares-hp.<tu-tailnet>.ts.net`.
Requiere tener activados MagicDNS y los certificados HTTPS en la consola de administración de
Tailscale (DNS). Para quitarlo: `tailscale serve reset`.

## Comprobar que el servicio ve las claves

Un servicio corre en otra sesión que la tuya. Después de arrancarlo, mira en el registro que
las sincronizaciones no dicen «Falta el secreto» ni «no está autorizado»:

```powershell
Get-Content C:\ares\ops\windows\service-stdout.log -Tail 40
```


## Actualizar desde GitHub (una configuración única y después un comando)

El HP no recibe el código por zip: lo trae de GitHub con una **clave de despliegue de solo lectura**.
Es una clave atada a un único repositorio: no da acceso a tu cuenta ni permite escribir. La clave
privada se crea en el HP y no sale de él.

**Configuración única, en el HP (PowerShell normal):**

```powershell
ssh -V
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\ares_deploy" -N '""' -C "ares-hp solo lectura"
Get-Content "$env:USERPROFILE\.ssh\ares_deploy.pub"
```

Copia la línea que imprime el último comando (es la clave pública; no es secreta). En GitHub:
repositorio → Settings → Deploy keys → Add deploy key → título `ares-hp (solo lectura)`, pegas la
clave y **dejas sin marcar «Allow write access»**.

Después, en el HP, la clave del servidor de GitHub (tomada de la página oficial de huellas de GitHub,
para no tener que aceptar ningún aviso) y la configuración de SSH:

```powershell
Add-Content -Encoding ascii "$env:USERPROFILE\.ssh\known_hosts" "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
@("Host github.com", "  IdentityFile ~/.ssh/ares_deploy", "  IdentitiesOnly yes", "  StrictHostKeyChecking yes") | Add-Content -Encoding ascii "$env:USERPROFILE\.ssh\config"
ssh -T git@github.com
```

Debe responder que te has autenticado y que GitHub no da acceso a una terminal. Y alinear el HP con GitHub:

```powershell
cd C:\ares
git remote set-url origin git@github.com:gonzalosabatervila-a11y/ares-physiology.git
git fetch origin
if ($LASTEXITCODE -eq 0) { git reset --hard origin/master; nssm restart ARESPhysiology } else { Write-Host "El fetch ha fallado: NO hago reset ni reinicio" }
```

Tu `.env`, el entorno `.venv` y los datos no se tocan.

**A partir de entonces, cada cambio:** en el Mac `git push`, y en el HP (PowerShell como administrador):

```powershell
powershell -ExecutionPolicy Bypass -File C:\ares\ops\windows\update.ps1
```

Con `-Check` solo enseña qué llegaría. El script pasa las pruebas antes de reiniciar el servicio y, si
algo falla, vuelve a la versión anterior. En Lab, «código» dice qué versión corre.
