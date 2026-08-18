# Operación de brain-api

Este documento está dirigido al operador humano. No es contexto permanente de los agentes de rol.

## Reinicio seguro

### Paso 0 — registrar sesiones

```bash
tmux -L factory-brain list-sessions
```

Registrar el número de sesiones antes de tocar el servicio.

### Paso 1 — detener primero

```bash
sudo systemctl stop factory-brain-api
```

Nunca arrancar una segunda instancia antes de detener la anterior.

La unit activa debe utilizar `KillMode=process` para que reiniciar brain-api no destruya el servidor tmux que aloja a los agentes.

### Paso 2 — comprobar puerto

```bash
systemctl status factory-brain-api
sudo ss -tlnp | grep :8000
```

No continuar si queda un proceso escuchando inesperadamente.

### Paso 3 — arrancar

```bash
sudo systemctl start factory-brain-api
```

La unit autoritativa del despliegue debe mantenerse sincronizada con la copia del repositorio.

### Paso 4 — verificar agentes

```bash
curl -s http://<host-tailscale>:8000/agents | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
```

Comparar con las sesiones observadas antes del reinicio.

Consultar el log de reconciliación:

```bash
tail -1 <project_root>/.claude/state/<project_name>/reconciliation_log.jsonl | python3 -m json.tool
```

### Reinicio desde la web (T-FB037-US05)

El botón "Reiniciar Brain" de la pantalla Configuración llama a
`POST /system/restart`, que ejecuta exactamente este comando:

```bash
sudo /usr/bin/systemctl restart factory-brain-api
```

Para que funcione sin contraseña, el usuario del servicio
(`secure_ai_atlas`) necesita la siguiente regla sudoers, instalada como
requisito de despliegue:

```bash
sudo visudo -f /etc/sudoers.d/factory-brain-restart
```

Contenido del fichero:

```
secure_ai_atlas ALL=(root) NOPASSWD: /usr/bin/systemctl restart factory-brain-api
```

La regla está acotada a ese único comando (ruta absoluta y argumentos
fijos): no usar `NOPASSWD: ALL` ni una regla genérica de `systemctl`, que
abriría una escalación de privilegios. Verificar que el fichero es legible
por sudo:

```bash
sudo visudo -c -f /etc/sudoers.d/factory-brain-restart
```

Si la regla no está instalada, el endpoint responde 500 con un mensaje que
apunta a esta sección.

## Instancia duplicada

Revisar:

```bash
journalctl -u factory-brain-api -n 50 | grep "Detectada otra instancia"
```

Una alerta de instancia duplicada requiere detenerse e investigar.

## Unit systemd

La copia del repositorio es la fuente versionada.

La copia activa puede estar en:

`/etc/systemd/system/factory-brain-api.service`

Después de modificar la unit versionada:

```bash
sudo cp deploy/systemd/factory-brain-api.service /etc/systemd/system/factory-brain-api.service
sudo systemctl daemon-reload
```

No editar directamente la copia activa sin propagar después el cambio al repositorio.

## TUI

La TUI está bloqueada por defecto en el estado documentado actual.

Habilitar:

```bash
curl -X PUT http://<host-tailscale>:8000/system/preferences \
  -H "Content-Type: application/json" \
  -d '{"tui_enabled": true}'
```

Comprobar:

```bash
curl -s http://<host-tailscale>:8000/system/preferences | python3 -m json.tool | grep tui_enabled
```

Deshabilitar:

```bash
curl -X PUT http://<host-tailscale>:8000/system/preferences \
  -H "Content-Type: application/json" \
  -d '{"tui_enabled": false}'
```

## Nota de mantenimiento

Las rutas, puertos, nombres de unit y comportamiento de la TUI son estado de despliegue. Si cambian, actualizar este documento; no convertir esos valores en invariantes de metodología.
