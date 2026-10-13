# ARES · Desarrollo en Mac (octubre de 2026)

Este es el flujo de desarrollo. El Mac sirve para **programar y probar**;
GitHub conserva versiones revisadas y el HP Windows del despacho será
**producción**. No es necesario actualizar ni encender el HP durante esta fase.

## 1. Identificar el repositorio correcto (sin borrar datos)

En Terminal:

```bash
git --version
command -v uv || echo "Falta uv (https://docs.astral.sh/uv/getting-started/installation/)"
if [ -d "$HOME/ares" ]; then
  cd "$HOME/ares"
  printf '\nARES existente: %s\n' "$PWD"
  git remote -v
  git status --short --branch
else
  git clone https://github.com/gonzalosabatervila-a11y/ares-physiology.git "$HOME/ares"
  cd "$HOME/ares"
  git status --short --branch
fi
```

Si `~/ares` existe pero **no tiene** el remoto
`gonzalosabatervila-a11y/ares-physiology`, DETENERSE. No borrar, reinicializar
ni sustituir el directorio; podría contener cambios sin publicar.

Si Git pide autenticación para el repositorio privado, usar GitHub CLI
(`gh auth login`) o el método de autenticación ya configurado. Nunca guardar
tokens en ficheros del repositorio.

## 2. Preparar el entorno y pasar pruebas

Instalar `uv` siguiendo la documentación oficial si hace falta
(https://docs.astral.sh/uv/getting-started/installation/). Después:

```bash
cd ~/ares
uv sync --frozen --python 3.12
uv run pytest -q
```

Si el entorno o las pruebas fallan, **no** iniciar migraciones ni cambiar
las credenciales. Conservar el error para diagnosticarlo.

## 3. Arrancar la aplicación local

```bash
cd ~/ares
uv run ares init-db
uv run ares doctor --offline
uv run ares app
```

Abrir **http://127.0.0.1:8443**. `ares app` lee la base local y no realiza
sincronizaciones. Si no hay datos locales se verán estados vacíos: no se
fabrican métricas ni se importan automáticamente los datos del conector de
ChatGPT. No ejecutar `ares app` y `ares serve` al mismo tiempo: DuckDB
requiere un solo escritor. Detener el servidor con Ctrl+C.

Los secretos permanecen en el llavero de macOS (`ares secret set`) y los
datos en `~/ares-data`. **No subir** bases, exportaciones, datos de salud,
capturas con información sensible, `.env` ni tokens a GitHub.

## 4. Trabajo diario

```bash
cd ~/ares
git status --short --branch
# Trabajar en una rama de desarrollo, nunca experimentar en producción.
uv run pytest -q
```

Hacer propuestas mediante pull request con pruebas automáticas. No incorporar
cambios directamente a `master` sin revisión; desplegar en el HP solo una
versión aprobada y validada. La infraestructura de actualización de Windows
ya contiene pruebas, verificación HTTP y reversión, pero **todavía no hay
despliegue remoto automático verificado**. No afirmar lo contrario.

## 5. Objetivo de calidad

WHOOP es el umbral mínimo de experiencia de uso, **no** una licencia para
inventar puntuaciones propietarias o confundir estimaciones con medidas.
Antes de afirmar equivalencia hay que validar: ingestión histórica,
completitud/frescura de datos, sueño/recuperación/carga, transparencia de
algoritmos, versiones, privacidad y pruebas de UX móviles. COROS y WHOOP
requieren cada uno sus permisos y conectores propios; que funcionen dentro
de ChatGPT no demuestra que esta aplicación local tenga sus APIs autorizadas.
