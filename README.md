# SUNAT Login con Python + Playwright + Flask

Proyecto base para automatizar el ingreso al portal de SUNAT usando Playwright en Python y exponer el proceso por una API Flask.

Este proyecto sirve para:

1. Abrir el flujo real de login de SUNAT usando tu URL OAuth.
2. Guardar la sesion del navegador para reutilizarla luego.
3. Exponer una API Flask para disparar el login, guardar el token y reutilizarlo mientras siga vigente.

## Lo que hace hoy

- Abre la URL de login de SUNAT.
- Intenta detectar campos comunes de RUC, usuario y clave.
- Permite iniciar sesion de forma manual si SUNAT cambia selectores o muestra pantallas intermedias.
- Espera una confirmacion visual de que el login termino.
- Guarda la sesion en `playwright/.auth/storage_state.json`.
- Guarda un snapshot de autenticacion en `artifacts/auth_snapshot.json`.
- Guarda el token en `artifacts/token_store.json`.
- Valida si el token sigue vigente antes de usarlo.
- Intenta refresh si existe `refresh_token` y tienes configurado `SUNAT_REFRESH_URL`.
- Si no puede refrescar, realiza login nuevamente.
- Incluye un modo de depuracion para inspeccionar la pagina.

## Estructura

- `requirements.txt`: dependencias de Python
- `.env.example`: variables de entorno base
- `src/config.py`: carga de configuracion
- `src/login.py`: login por Playwright
- `src/api.py`: servicio Flask
- `src/selectors.py`: selectores probables del formulario
- `src/utils.py`: utilidades

## Requisitos

- Python 3.11 o superior
- Playwright con Chromium instalado

## Instalacion

```powershell
cd C:\Users\JOSE LUIS\Documents\Playground\sunat_playwright_login
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

## Configuracion

Edita `.env`:

```env
SUNAT_LOGIN_URL=https://api-seguridad.sunat.gob.pe/v1/clientessol/4f3b88b3-d9d6-402a-b85d-6a0bc857746a/oauth2/loginMenuSol?lang=es-PE&showDni=true&showLanguages=false&originalUrl=https://e-menu.sunat.gob.pe/cl-ti-itmenu/AutenticaMenuInternet.htm&state=rO0ABXNyABFqYXZhLnV0aWwuSGFzaE1hcAUH2sHDFmDRAwACRgAKbG9hZEZhY3RvckkACXRocmVzaG9sZHhwP0AAAAAAAAx3CAAAABAAAAADdAADZXhldAALMTEuNS4xMC4xLjF0AAZwYXJhbXN0AEsqJiomL2NsLXRpLWl0bWVudS9NZW51SW50ZXJuZXQuaHRtJmI2NGQyNmE4YjVhZjA5MTkyM2IyM2I2NDA3YTFjMWRiNDFlNzMzYTZ0AARleGVjcHg=
SUNAT_RUC=
SUNAT_USER=
SUNAT_PASSWORD=
HEADLESS=false
SLOW_MO_MS=250
LOGIN_SUCCESS_URL_CONTAINS=e-menu.sunat.gob.pe
FLASK_HOST=127.0.0.1
FLASK_PORT=8000
SUNAT_REFRESH_URL=
SUNAT_REFRESH_CLIENT_ID=
SUNAT_REFRESH_CLIENT_SECRET=
```

Puedes dejar vacios `SUNAT_RUC`, `SUNAT_USER` y `SUNAT_PASSWORD` si prefieres completar el login manualmente en el navegador.

## Uso por script

Login directo:

```powershell
python -m src.login
```

Modo debug:

```powershell
python -m src.login --debug
```

## Uso por API Flask

Levanta el servicio:

```powershell
python -m src.api
```

O:

```powershell
.\run_api.ps1
```

Base URL por defecto:

```text
http://127.0.0.1:8000
```

### Endpoints

`GET /health`

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

`POST /auth/login`

Abre el navegador, realiza el login y guarda la sesion.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/auth/login -ContentType "application/json" -Body '{"timeout_seconds":180,"debug":true}'
```

`GET /auth/token`

Devuelve el token guardado y si sigue vigente.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/auth/token
```

`GET /auth/session`

Devuelve el snapshot completo de autenticacion y confirma si la sesion guardada existe.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/auth/session
```

`POST /auth/ensure`

Valida el token guardado. Si sigue vigente lo reutiliza; si no, intenta refresh y si tampoco aplica, vuelve a loguearse.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/auth/ensure
```

`POST /consultacompras/xml`

Recibe los parametros base del comprobante, garantiza un token vigente, consulta SUNAT y devuelve el XML extraido del ZIP.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/consultacompras/xml -ContentType "application/json" -Body '{"ruc":"20549087681","tipo_documento":"01","serie_documento":"FA04","numero_documento":"6551"}'
```

## Sobre el "token"

Este proyecto intenta extraer un token visible desde:

- URL final
- fragmentos tipo `#access_token=...`
- query params
- cookies
- `localStorage`
- `sessionStorage`

Pero hay un detalle importante:

- si SUNAT solo crea una sesion web tradicional, el flujo puede no exponer ningun `access_token` util al navegador
- en ese caso `token_candidates` vendra vacio, pero la sesion web igual quedara guardada en `storage_state.json`

Eso significa que la automatizacion del portal puede seguir funcionando aunque no aparezca un token reutilizable por API.

## Archivos generados

- `playwright/.auth/storage_state.json`
- `artifacts/auth_snapshot.json`
- `artifacts/token_store.json`
- `artifacts/last_page.html`
- `artifacts/last_page.png`

## Consideraciones

- SUNAT puede cambiar selectores, iframes o pantallas intermedias.
- Si hay captcha o validacion adicional, el proyecto te deja terminar manualmente.
- No guardes credenciales reales en Git.
