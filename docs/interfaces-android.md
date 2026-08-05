# Android app

The Android app is Factory Brain's mobile client for remote control (no public IP, no Play Store — the APK is downloaded from the backend).

!!! note "Development pause"
    The Android app is **paused** since the 2026-08-04 product decision: all new functionality is exposed on the web interface. The already-implemented work (listed below) remains the current interface for those who use it today; no new capability is added until it is explicitly resumed.

## Requirements

- The `brain-api` backend running and reachable from the device.
- The device on the same network as the backend.
- **Download the APK**: `GET /apk` serves `releases/factory-brain-latest.apk` from the backend (`application/vnd.android.package-archive`). Manual install (unknown-sources permission; the app uses cleartext traffic `usesCleartextTraffic=true` for the connection).

## Code

- `10-android/` — Gradle Kotlin project, package `com.factoriasoftware.factorybrain`.
- Compose + Material 3, OkHttp + Moshi, `ReconnectingWebSocket`, minSdk 26 / target 34.
- Consumes exactly the same REST + WebSocket API as the web and the TUI (same `BackendUnavailableException`/`BackendRequestException` error taxonomy).

## Screens

The bottom navigation (`NavigationBar`) is shown **only when the session context is resolved** (connection + project):

- **Agents** — listing with state (3s polling), launch (role+runtime+model, with optional `initial_job_description`), stop, view pane.
- **Jobs** — create/dispatch, cancel, consume `WS /ws/jobs`, history.
- **Plan Critic** — ask for a plan, approve/reject, consume `WS /ws/plans`.
- **Scripts** — catalog + execution, formats `backlog_status`.
- **Backlog** — listing/detail, launch development (only Developer agents).

Also:

- **SessionContextChip** — persistent top bar with backend state + active project, opens a `ModalBottomSheet` to configure host and change project.
- **OnboardingFlow** — guided 3 steps (Nielsen Norman style) when the context is not resolved.
- **Confirmations** on critical actions (stop agent, approve plan) and **single-flight** on blocking buttons.
- Material 3 theme with a color palette verified by WCAG contrast.

## Limitations

- New functionality is not implemented here while the 2026-08-04 pause lasts.
- The APK must be rebuilt and served manually; there is no store.
