# ARES + WHOOP 5.0 + Gonzalo OS (integración inicial)

## Qué está implementado

- Fuente oficial WHOOP API v2: `cycle`, `recovery`, `activity/sleep`, `activity/workout`.
- OAuth2 de autorización individual con `offline`, estado anti-CSRF y refresh token rotatorio.
- Sincronización paginada, incremental, con capa bruta append-only e idempotente.
- `GET /api/whoop/summary`: 30 días (máximo 90) en formato reducido, sin tokens ni identificadores.
- Métricas WHOOP conservadas como tales: Recovery %, rMSSD, RHR, Strain, sueño, pasos.
- **No hay** puntuación fisiológica propia nueva, reproducción de Pulsr ni exportación de FC minuto a minuto.
- Los 21 días/noches de modo sombra y las decisiones ARES originales no se alteran.

## 1. Registro de WHOOP

Crear una aplicación personal en [WHOOP Developer Dashboard](https://developer-dashboard.whoop.com/).

Permisos mínimos:

```
offline read:cycles read:recovery read:sleep read:workout
```

Callback exacta en el panel WHOOP:

```
https://gonzaloos.es/whoop/callback
```

Es necesario que esta ruta **ya esté publicada** en Gonzalo OS con HTTPS antes de comenzar OAuth.
La ruta solo explica cómo copiar la URL del navegador y no recoge ni guarda códigos.

Si se utiliza otro host o dirección, configurarlo en el `.env` de ARES:

```
WHOOP_REDIRECT_URI=https://HOST-REAL/whoop/callback
```

## 2. Credenciales en el equipo que ejecuta ARES

```bash
uv run ares secret set whoop_client_id
uv run ares secret set whoop_client_secret
uv run ares whoop-auth
```

En `whoop-auth`, autenticar WHOOP y pegar **la URL completa que aparece en el navegador**.
El comando comprueba `state` y la callback, canjea el código y guarda tokens en el
keyring del sistema, nunca en Git. No pegar esa URL en chats ni archivos.

Después:

```bash
uv run ares init-db
uv run ares sync whoop --days 30
uv run ares serve
```

No ejecutar `ares sync` en otro proceso mientras funciona `ares serve`: DuckDB tiene
un único escritor y WHOOP **rota** los refresh tokens. El servicio sincroniza automáticamente
junto con las fuentes ya existentes.

## 3. Conectar la parte Personal de Gonzalo OS

En el servicio **privado** de Gonzalo OS hay que configurar:

```
GONZALO_ARES_SUMMARY_URL=https://HOST-TAILSCALE-PRIVADO.ts.net/api/whoop/summary
```

O, cuando ambos servicios estén dentro de la misma red Docker interna:
```
GONZALO_ARES_SUMMARY_URL=http://ares:8443/api/whoop/summary
```

No usar una URL pública sin autenticación. La API ARES actual no es un servicio público:
por defecto escucha en `127.0.0.1:8443`, y Gonzalo OS solo puede acceder a ella si
se configura un canal privado accesible desde el servidor donde se ejecute Gonzalo OS.
**No basta con apuntar el dominio a la IP pública del equipo.**

La ruta `/api/personal/ares` de Gonzalo OS requiere sesión y MFA según la configuración
de producción. El menú ARES solo aparece en el ámbito personal.

## 4. Límites y pendientes

1. Falta autorizar con una cuenta WHOOP real y comprobar sus payloads en el entorno del usuario.
2. Falta verificar la red privada real entre el equipo ARES y OVH/gonzaloos.es.
3. No hay despliegue automático ni se han modificado DNS, VPS ni datos históricos.
4. Pulsr obtiene HRV SDNN de HealthKit; WHOOP ofrece rMSSD. No mezclar sus puntuaciones.
5. WHOOP API no expone frecuencia cardíaca continua: no hay Stress continuo equivalente a Pulsr.
6. No convertir automáticamente Recovery verde en permiso para entrenamiento de calidad.
7. Una eventual versión 2 puede añadir Journal y un motor de decisiones ARES validado.

Referencias: https://developer.whoop.com/api/ y https://developer.whoop.com/docs/developing/oauth/
