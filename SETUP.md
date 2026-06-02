# Code Review Bot — Documentación

## Cómo funciona

El bot se integra como una GitHub App. Cada vez que alguien abre o actualiza un Pull Request en un repo donde está instalado, GitHub le manda un webhook al servidor. El servidor analiza el diff y publica comentarios automáticos directamente en el PR.

```
Alguien abre un PR
       ↓
GitHub manda webhook → POST /webhook
       ↓
Se verifica la firma HMAC (seguridad)
       ↓
Se obtienen los archivos modificados del PR (GitHub API)
       ↓
Análisis estático: ruff (Python) / eslint (JS/TS)
       ↓
Análisis semántico: se manda el diff a Claude
       ↓
Se publican comentarios inline en el PR (GitHub API)
```

---

## Componentes

| Archivo | Responsabilidad |
|---|---|
| `app/main.py` | Servidor FastAPI — recibe webhooks en `POST /webhook` |
| `app/webhook_handler.py` | Verifica firma HMAC y extrae datos del evento |
| `app/github_client.py` | Autenticación con GitHub App (JWT + installation token) y llamadas a la API |
| `app/diff_parser.py` | Parsea el patch del PR para extraer contexto por archivo y mapa de líneas |
| `app/static_analyzer.py` | Corre `ruff` (Python) o `eslint` (JS/TS) sobre el código nuevo |
| `app/semantic_analyzer.py` | Manda el diff + issues estáticos a Claude y parsea los comentarios |
| `app/pipeline.py` | Orquesta el flujo completo de análisis y publicación |
| `config/settings.py` | Carga variables de entorno |

---

## Requisitos

- Python 3.9 o superior
- Node.js + npm (solo para análisis JS/TS con eslint)
- Una GitHub App creada y configurada
- API key de Anthropic

> **Nota de compatibilidad:** el código usa `from __future__ import annotations` para soportar sintaxis de type hints moderna (`dict | None`, `list[dict]`) en Python 3.9. El Dockerfile usa Python 3.12 sin este problema.

---

## Setup

### 1. Instalar dependencias Python

```bash
pip install -r requirements.txt
```

En macOS con Python del sistema, `uvicorn` queda en:
```
/Users/<tu-usuario>/Library/Python/3.9/bin/uvicorn
```

Si `uvicorn` no está en el PATH, corré:
```bash
/Users/<tu-usuario>/Library/Python/3.9/bin/uvicorn app.main:app --reload --port 8000
```

### 2. Crear la GitHub App

1. Ir a https://github.com/settings/apps/new
2. Configurar:
   - **GitHub App name**: nombre único (ej. `mi-code-review-bot`)
   - **Homepage URL**: `http://localhost:8000`
   - **Webhook URL**: dejar vacío por ahora (se completa en el paso 4)
   - **Webhook secret**: generá una cadena aleatoria y guardala
3. **Permisos** (Repository permissions):
   - `Pull requests`: Read & Write
   - `Contents`: Read
4. **Subscribe to events**: marcar `Pull request`
5. Crear la App → guardar el **App ID**
6. En la página de la App → `Generate a private key` → descargar el `.pem`
7. Mover el `.pem` a la raíz del proyecto y nombrarlo `private-key.pem`

### 3. Configurar variables de entorno

Crear el archivo `.env` en la raíz:

```env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=private-key.pem
GITHUB_WEBHOOK_SECRET=tu_secret_aqui
ANTHROPIC_API_KEY=sk-ant-...
PORT=8000
```

### 4. Instalar la App en un repositorio

1. En la página de tu GitHub App → `Install App`
2. Seleccionar el repo donde querés activar el bot

---

## Probar localmente

Para que GitHub pueda mandarle webhooks a tu servidor local necesitás exponerlo con ngrok.

### Instalar ngrok

```bash
brew install ngrok
```

Crear cuenta gratuita en https://ngrok.com, obtener el authtoken y configurarlo:

```bash
ngrok config add-authtoken TU_TOKEN
```

### Levantar el servidor

```bash
uvicorn app.main:app --reload --port 8000
```

Verificar que está corriendo:
```bash
curl http://localhost:8000/health
# → {"status":"ok"}
```

### Exponer con ngrok

En otra terminal:
```bash
ngrok http 8000
```

Ngrok muestra una URL pública tipo:
```
https://abc123.ngrok-free.app
```

### Actualizar la Webhook URL en GitHub

1. Ir a la configuración de tu GitHub App
2. **Webhook URL** → `https://abc123.ngrok-free.app/webhook`
3. Guardar

### Probar el flujo completo

Abrir un PR en el repo donde instalaste la App. El bot debería publicar comentarios automáticamente en los archivos modificados.

---

## Deploy en Railway

El proyecto incluye `Dockerfile` y `docker-compose.yml` listos para producción.

### Pasos

1. Subir el código a un repo de GitHub
2. Crear un nuevo proyecto en [railway.app](https://railway.app) y conectar ese repo
3. En Railway, configurar las variables de entorno (las mismas del `.env`)
4. Para la private key: copiar el contenido del `.pem` como variable `GITHUB_APP_PRIVATE_KEY` y ajustar `github_client.py` para leerla desde esa variable en lugar del archivo
5. Railway asigna una URL pública automáticamente — usarla como Webhook URL en la GitHub App

> En producción no se usa ngrok. La URL de Railway es permanente.

---

## Dependencias externas opcionales

- **ruff** — incluido en `requirements.txt`, se instala automáticamente
- **eslint** — para análisis estático JS/TS:
  ```bash
  npm install -g eslint
  ```
  Si no está instalado, el bot funciona igual pero sin análisis estático para JS/TS.
