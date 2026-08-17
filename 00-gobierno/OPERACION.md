# Operación de `brain-api`

Este documento es para un **operador humano**, no para un agente de rol
(Developer/Arquitecto/etc.) — no asume que quien lo sigue ha leído
`04-src/src/brain/api/main.py` ni `app.py`. Cubre el único procedimiento
operativo crítico hoy documentado: **reiniciar `brain-api` de forma
segura**, sin repetir el incidente del 2026-08-16.

## Contexto: qué pasó el 2026-08-16 (por qué este documento existe)

Ver `07-informes/incidente-arquitecto-perdido-tras-reinicio-2026-08-16.md`
para la investigación completa. Resumen para quien no lo haya leído: se
lanzó una instancia nueva de `brain-api` en un puerto distinto (`8000`)
sin detener antes la instancia anterior (`8787`, que había quedado
colgada sin responder). El servidor tmux que alojaba a los agentes de
la instancia vieja dejó de existir por completo en el proceso — no es
que Brain perdiera de vista sesiones tmux que seguían vivas (eso sí lo
cubre `reconcile_session_agents`, `FB-031`), sino que las sesiones tmux
en sí murieron con el servidor tmux viejo. El Arquitecto que estaba
trabajando en ese momento quedó inalcanzable, sin ningún aviso previo ni
rastro posterior.

**Este documento existe para que ese escenario — instancia nueva
arrancada antes de detener la vieja — deje de poder ocurrir por
descuido.**

## Unit systemd real de este despliegue

`brain-api` corre como servicio `systemd`, definido en
`deploy/systemd/factory-brain-api.service`. **Copia autoritativa real
en este despliegue: `/etc/systemd/system/factory-brain-api.service`**
(unit de *sistema*, no de usuario) — confirmado con
`systemctl show factory-brain-api.service -p FragmentPath`. También
existe una copia en `~/.config/systemd/user/factory-brain-api.service`,
pero **no es la activa**: es distinta a la del repo (omite
`User=`/`Group=`, pensados solo para systemd de usuario) y no corre
ningún proceso real en este despliegue. Si alguna vez cambias la unit,
edita primero `deploy/systemd/factory-brain-api.service` en el repo, y
después copia ese mismo fichero a `/etc/systemd/system/` (`sudo cp` +
`sudo systemctl daemon-reload`) — nunca edites la copia de
`/etc/systemd/system/` directamente sin propagar el cambio al repo, o
la próxima persona que mire el repo verá una unit desactualizada.

Dos propiedades de esta unit ya evitan por sí solas buena parte del
incidente original, y por eso el procedimiento de abajo puede confiar
en `systemctl` en vez de matar procesos a mano:

- **`KillMode=process`** (`T-FB037-US04-01`): un `stop`/`restart` mata
  solo el proceso Python principal de `brain-api`, nunca el servidor
  tmux (`tmux -Lfactory-brain`) que aloja a los agentes vivos ni los
  procesos de esos agentes — el servidor tmux **sobrevive** al reinicio
  del backend. Antes de esta Task, el `KillMode` implícito
  (`control-group`) mataba todo el árbol de procesos del servicio,
  incluido tmux — la causa técnica exacta de que el incidente perdiera
  agentes.
- **`User=secure_ai_atlas`/`Group=secure_ai_atlas`** (`T-FB037-US04-02`):
  el proceso corre como usuario real, no como `root` — sin esto,
  `resolve_startup_session()` no encuentra `~/.local/share/brain/active_project.json`
  real tras el reinicio (`Path.home()` resolvería a `/root`), y
  `GET /agents`/`GET /project` quedan sin sesión activa aunque el
  reinicio en sí haya ido bien.

## Procedimiento de reinicio seguro

### Paso 0 — Antes de tocar nada: anota el estado actual

```bash
# Sesiones tmux vivas en el socket de Brain, ANTES de reiniciar —
# necesario para el paso de verificación final.
tmux -L factory-brain list-sessions
```

Anota el número de líneas (una por sesión = un agente potencialmente
vivo). Si el comando falla con "no server running", no hay ningún
agente vivo — el paso de verificación final esperará 0 agentes
reenganchados.

### Paso 1 — Detener la instancia anterior primero

```bash
sudo systemctl stop factory-brain-api
```

**Nunca arranques una instancia nueva antes de este paso** — es
exactamente el error que causó el incidente original. `systemctl stop`
(con `KillMode=process` ya en la unit) detiene el proceso Python, deja
el servidor tmux intacto.

### Paso 2 — Verificar que el puerto quedó libre

```bash
systemctl status factory-brain-api    # debe mostrar "inactive (dead)"
sudo ss -tlnp | grep :8000            # no debe devolver ninguna línea
```

`8000` es el puerto por defecto (`DEFAULT_PORT`,
`04-src/src/brain/api/main.py`) sobre la IP de la interfaz Tailscale de
esta VM — nunca `0.0.0.0`/`localhost` (confirmar con
`tailscale ip -4` si tienes dudas de cuál es). Si `ss` sigue mostrando
algo escuchando en ese puerto tras el `stop`, **no continúes** — hay un
proceso residual (posiblemente el mismo escenario del incidente
original: una instancia previa que nunca se detuvo del todo) que hay
que investigar antes de arrancar nada nuevo.

### Paso 3 — Arrancar la instancia nueva

```bash
sudo systemctl start factory-brain-api
```

El entry point real es `brain-api = "brain.api.main:main"`
(`04-src/pyproject.toml`), que arranca sobre el mismo puerto por
defecto (`8000`) salvo que se pase `--port` explícito — la unit no lo
pasa, así que usa el default.

### Paso 4 — Verificación final: ¿se reengancharon los agentes que había?

Este es el paso que el incidente original no tenía — sin él, un
reinicio que sí pierde agentes (p. ej. porque el servidor tmux murió
por algún motivo ajeno a `brain-api`) pasaría desapercibido hasta que
alguien intentara hablar con un agente que ya no existe.

**4a — Compara el recuento con `GET /agents`:**

```bash
curl -s http://<host-tailscale>:8000/agents | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
```

Compara este número con el recuento de sesiones tmux del Paso 0. Si
coinciden, el reinicio reenganchó todo lo que había — el mecanismo real
detrás de esta comparación es `reconcile_session_agents`
(`FB-031`), que se ejecuta automáticamente en cada arranque
(`_lifespan`, `04-src/src/brain/api/app.py`).

**4b — Si los números NO coinciden, o quieres el detalle de qué pasó
con cada sesión, consulta el log persistente de reconciliación
(`US-FB037-02`) — no repitas el error del incidente original de
reconstruir esto a mano con `ps`/`ss`:**

```bash
tail -1 <project_root>/.claude/state/<project_name>/reconciliation_log.jsonl | python3 -m json.tool
```

(`<project_root>` es la raíz del repo del proyecto activo,
`<project_name>` su nombre saneado — para este mismo proyecto,
`prod-006-factory-brain`.) Cada arranque añade una línea con
`total_sessions` (sesiones tmux vistas), `reconciled_count`/
`reconciled` (nombres de agente efectivamente reenganchados), e
`ignored_count`/`ignored` (sesiones NO reenganchadas, cada una con su
motivo explícito: `ya_reconciliada`, `nombre_no_reconocido`,
`otro_proyecto`, `rol_invalido`, o `error_reenganche: <mensaje>`) — la
propia entrada te dice si faltó algo y por qué, sin tener que cruzar
comandos de sistema a mano.

**4c — Aviso de instancia duplicada (`US-FB037-01`), por si el Paso 2
se saltó o falló:**

Si en algún momento arrancas una instancia nueva mientras otra sigue
sirviendo (el propio escenario del incidente), `run_server`
(`04-src/src/brain/api/main.py`) lo detecta automáticamente en el
arranque (`GET /projects` contra el puerto objetivo) y lo deja escrito
en el log del servicio a nivel `INFO`:

```bash
journalctl -u factory-brain-api -n 50 | grep "Detectada otra instancia"
```

Si ves esa línea tras un arranque que creías limpio, detente:
significa que el Paso 1/2 de este procedimiento no se completó
correctamente y hay dos instancias corriendo a la vez — vuelve al Paso
1. (v1 de esta detección solo avisa, no bloquea el arranque — el
operador es quien decide qué hacer con el aviso.)

## Resumen accionable (para copiar/pegar en una terminal)

```bash
# 0. Estado antes de reiniciar
tmux -L factory-brain list-sessions

# 1-2. Detener y verificar puerto libre
sudo systemctl stop factory-brain-api
sudo ss -tlnp | grep :8000   # debe estar vacío antes de seguir

# 3. Arrancar
sudo systemctl start factory-brain-api

# 4. Verificar
curl -s http://<host-tailscale>:8000/agents | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
tail -1 <project_root>/.claude/state/<project_name>/reconciliation_log.jsonl | python3 -m json.tool
journalctl -u factory-brain-api -n 50 | grep "Detectada otra instancia"
```

## Gate de arranque de la TUI (T-FB002-US04-01)

La interfaz TUI (Textual) está bloqueada por defecto — ejecutar `brain`
desde línea de comandos imprime un aviso de seguridad y termina sin
arrancar la interfaz. **Motivo**: la TUI es una superficie antigua sin
mantenimiento activo en el desarrollo actual (prioridad Web actualmente,
`FB-024`). El bloqueo evita que se arranca por accidente en un entorno de
desarrollo o producción sin saberlo explícitamente.

### Habilitar la TUI (para desarrollo o debugging)

Si necesitas trabajar con la interfaz TUI, habilítala mediante el endpoint
`PUT /system/preferences`:

```bash
curl -X PUT http://<host-tailscale>:8000/system/preferences \
  -H "Content-Type: application/json" \
  -d '{"tui_enabled": true}'
```

Después de esto, `brain` arrancará la TUI con normalidad. El cambio se
persiste en `~/.local/share/brain/system_preferences.json` (o
`$XDG_DATA_HOME/brain/` si está configurado).

### Verificar estado actual

```bash
curl -s http://<host-tailscale>:8000/system/preferences | python3 -m json.tool | grep tui_enabled
```

Debe mostrar `"tui_enabled": false` (por defecto, bloqueada) o
`"tui_enabled": true` (habilitada explícitamente).

### Deshabilitar de nuevo

```bash
curl -X PUT http://<host-tailscale>:8000/system/preferences \
  -H "Content-Type: application/json" \
  -d '{"tui_enabled": false}'
```
