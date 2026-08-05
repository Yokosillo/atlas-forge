# App Android

La app Android es el cliente móvil de Factory Brain para control remoto a través de **Tailscale** (sin IP pública, sin Play Store — el APK se descarga desde el backend).

!!! note "Pausa de desarrollo"
    La app Android está **en pausa** desde la decisión de producto de 2026-08-04: toda funcionalidad nueva se expone en la interfaz web. El trabajo ya implementado (listado abajo) sigue siendo la interfaz vigente para quien la use hoy; ninguna capacidad nueva se añade hasta que se retome explícitamente.

## Requisitos

- Backend `brain-api` escuchando en la IP Tailscale de la VM (por defecto).
- El móvil unido a la misma red Tailscale.
- **Descargar el APK**: `GET /apk` sirve `releases/factory-brain-latest.apk` desde el backend (`application/vnd.android.package-archive`). Instalación manual (permisos de orígenes desconocidos; la app usa tráfico en claro `usesCleartextTraffic=true` para el túnel Tailscale).

## Código

- `10-android/` — proyecto Gradle Kotlin, paquete `com.factoriasoftware.factorybrain`.
- Compose + Material 3, OkHttp + Moshi, `ReconnectingWebSocket`, minSdk 26 / target 34.
- Consume exactamente la misma API REST + WebSocket que la web y la TUI (misma taxonomía de errores `BackendUnavailableException`/`BackendRequestException`).

## Pantallas

La navegación inferior (`NavigationBar`) se muestra **solo cuando el contexto de sesión está resuelto** (conexión + proyecto):

- **Agentes** — listado con estado (3s polling), lanzar (rol+runtime+modelo, con `initial_job_description` opcional), detener, ver pane.
- **Jobs** — crear/despachar, cancelar, consumir `WS /ws/jobs`, histórico.
- **Plan Critic** — pedir plan, aprobar/rechazar, consumir `WS /ws/plans`.
- **Scripts** — catálogo + ejecución, formatea `backlog_status`.
- **Backlog** — listado/detalle, lanzar desarrollo (solo agentes Developer).

Además:

- **SessionContextChip** — barra superior persistente con estado del backend + proyecto activo, abre un `ModalBottomSheet` para configurar host y cambiar de proyecto.
- **OnboardingFlow** — guiado de 3 pasos (estilo Nielsen Norman) cuando el contexto no está resuelto.
- **Confirmaciones** en acciones críticas (detener agente, aprobar plan) y **single-flight** en botones bloqueantes.
- Tema Material 3 con paleta de colores verificada por contraste WCAG.

## Limitaciones

- Funcionalidad nueva no se implementa aquí mientras dure la pausa de 2026-08-04.
- El APK debe reconstruirse y servirse manualmente; no hay tienda.
