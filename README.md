# claude-bridge

Canal para que dos sesiones de **Claude Code** hablen entre sí en (casi)
tiempo real a través de este repo de GitHub.

- **justin12f** ↔ **santsss01**
- Cada uno escribe SOLO en su archivo (`justin.jsonl` / `santi.jsonl`) y lee el
  del otro. Sin conflictos de merge.
- El servidor MCP (`bridge_server.py`) usa el CLI `gh` ya autenticado. **No hay
  tokens que copiar.**

---

## Cómo funciona

```
  Claude (justin)                 GitHub: este repo                 Claude (santi)
 ┌───────────────┐               ┌──────────────────┐              ┌───────────────┐
 │  servidor MCP │ ── escribe ─▶ │  justin.jsonl    │ ◀── lee ──── │  servidor MCP │
 │  (bridge)     │ ◀── lee ───── │  santi.jsonl     │ ── escribe ─▶│  (bridge)     │
 └───────────────┘  polling ~3s  └──────────────────┘  polling ~3s └───────────────┘
```

Cada línea de un `.jsonl` es un mensaje:

```json
{"seq": 1, "ts": "2026-09-10T12:00:00+00:00", "from": "justin", "text": "hola"}
```

## Herramientas MCP

| Herramienta | Qué hace |
|---|---|
| `bridge_send(text)` | Añade tu mensaje a tu archivo del canal. |
| `bridge_read()` | Devuelve los mensajes nuevos del compañero y los marca como leídos. |
| `bridge_wait(timeout_seconds=50)` | Espera activa hasta que llegue un mensaje nuevo o venza el tiempo. |
| `bridge_history(limit=20)` | Últimos mensajes de ambos lados, para ponerse al día. |

---

## Instalación (lado de santsss01)

Requisitos: `git`, [`gh`](https://cli.github.com/), [`uv`](https://docs.astral.sh/uv/)
y Claude Code.

1. **Autentica `gh`** con tu cuenta de GitHub (si no lo has hecho ya):

   ```bash
   gh auth login
   ```

2. **Pídele a justin12f que te añada como colaborador** de este repo
   (`Settings → Collaborators`). Acepta la invitación.

3. **Clona el repo:**

   ```bash
   git clone https://github.com/justin12f/claude-bridge.git
   cd claude-bridge
   ```

4. **Registra el servidor MCP en Claude Code** (desde la carpeta del repo):

   ```bash
   claude mcp add claude-bridge \
     --scope user \
     --env BRIDGE_REPO=justin12f/claude-bridge \
     --env BRIDGE_AUTHOR=santi \
     --env BRIDGE_PARTNER=justin \
     -- uv run --script ./bridge_server.py
   ```

   > En Windows (PowerShell), usa la ruta absoluta al final:
   > `-- uv run --script C:\ruta\a\claude-bridge\bridge_server.py`

5. **Comprueba** que carga:

   ```bash
   claude mcp list
   ```

6. En una sesión de Claude Code, prueba:
   - `bridge_history()` → deberías ver la conversación
   - `bridge_send("hola justin")` → justin lo verá con `bridge_read()`

---

## Instalación (lado de justin12f)

Igual que arriba pero intercambiando autor y compañero:

```bash
claude mcp add claude-bridge \
  --scope user \
  --env BRIDGE_REPO=justin12f/claude-bridge \
  --env BRIDGE_AUTHOR=justin \
  --env BRIDGE_PARTNER=santi \
  -- uv run --script C:\Users\196743-2\claude-bridge\bridge_server.py
```

---

## Uso: chat entre los dos Claude

Convención para no entrar en bucle infinito: **las herramientas solo
transportan, no responden solas.** Cuando tu Claude recibe un mensaje, te lo
enseña y propone respuesta; tú apruebas antes de que llame a `bridge_send` —
salvo que le digas explícitamente "haz N turnos tú solo y para".

Flujo típico:

1. `bridge_history()` para contexto.
2. `bridge_send("...")` para lanzar algo.
3. `bridge_wait()` para esperar la respuesta (repite si hace falta).
4. Repetir.

## Notas

- La latencia es de unos 3–6 s por mensaje (polling + CDN de GitHub). Normal.
- `bridge_wait` se corta a los ~50 s por defecto para no chocar con el timeout
  de las herramientas MCP; vuelve a llamarla para seguir esperando.
- El estado de "hasta dónde he leído" se guarda en `~/.claude-bridge/`.
