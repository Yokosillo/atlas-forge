# Operación de atlas-forge-api

Este documento está dirigido al operador humano. No es contexto permanente de los agentes de rol.

## Reinicio seguro

### Paso 0 — registrar sesiones

```bash
tmux -L atlas-forge list-sessions
```

Registrar el número de sesiones antes de tocar el servicio.

### Paso 1 — detener primero

```bash
sudo systemctl stop atlas-forge-api
```

Nunca arrancar una segunda instancia antes de detener la anterior.

La unit activa debe utilizar `KillMode=process` para que reiniciar atlas-forge-api no destruya el servidor tmux que aloja a los agentes.

### Paso 2 — comprobar puerto

```bash
systemctl status atlas-forge-api
sudo ss -tlnp | grep :8000
```

No continuar si queda un proceso escuchando inesperadamente.

### Paso 3 — arrancar

```bash
sudo systemctl start atlas-forge-api
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

### Reinicio desde la web (T-AF037-US05)

El botón "Reiniciar Atlas Forge" de la pantalla Configuración llama a
`POST /system/restart`, que ejecuta exactamente este comando:

```bash
sudo /usr/bin/systemctl restart atlas-forge-api
```

Para que funcione sin contraseña, el usuario del servicio
(`secure_ai_atlas`) necesita la siguiente regla sudoers, instalada como
requisito de despliegue:

```bash
sudo visudo -f /etc/sudoers.d/atlas-forge-restart
```

Contenido del fichero:

```
secure_ai_atlas ALL=(root) NOPASSWD: /usr/bin/systemctl restart atlas-forge-api
```

La regla está acotada a ese único comando (ruta absoluta y argumentos
fijos): no usar `NOPASSWD: ALL` ni una regla genérica de `systemctl`, que
abriría una escalación de privilegios. Verificar que el fichero es legible
por sudo:

```bash
sudo visudo -c -f /etc/sudoers.d/atlas-forge-restart
```

Si la regla no está instalada, el endpoint responde 500 con un mensaje que
apunta a esta sección.

## Instancia duplicada

Revisar:

```bash
journalctl -u atlas-forge-api -n 50 | grep "Detectada otra instancia"
```

Una alerta de instancia duplicada requiere detenerse e investigar.

## Unit systemd

La copia del repositorio es la fuente versionada.

La copia activa puede estar en:

`/etc/systemd/system/atlas-forge-api.service`

Después de modificar la unit versionada:

```bash
sudo cp deploy/systemd/atlas-forge-api.service /etc/systemd/system/atlas-forge-api.service
sudo systemctl daemon-reload
```

No editar directamente la copia activa sin propagar después el cambio al repositorio.

## Nota de mantenimiento

Las rutas, puertos y nombres de unit son estado de despliegue. Si cambian, actualizar este documento; no convertir esos valores en invariantes de metodología.
