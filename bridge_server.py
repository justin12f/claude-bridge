# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2,<3"]
# ///
"""
claude-bridge: servidor MCP para comunicacion en "tiempo real" entre dos
sesiones de Claude Code a traves de un repo de GitHub compartido.

Cada participante escribe SOLO en su propio archivo (<author>.jsonl) y lee
SOLO el del companero, asi que nunca hay conflictos de merge.

Transporte: el CLI `gh` (ya autenticado). No se manejan tokens aqui.

Configuracion por variables de entorno:
  BRIDGE_REPO     owner/repo del canal          (ej. justin12f/claude-bridge)
  BRIDGE_AUTHOR   tu identidad                  (ej. justin)
  BRIDGE_PARTNER  identidad del companero       (ej. santi)
  BRIDGE_POLL     segundos entre sondeos        (opcional, def. 3)
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer

REPO = os.environ.get("BRIDGE_REPO", "").strip()
AUTHOR = os.environ.get("BRIDGE_AUTHOR", "").strip()
PARTNER = os.environ.get("BRIDGE_PARTNER", "").strip()
POLL_SECONDS = float(os.environ.get("BRIDGE_POLL", "3"))

if not (REPO and AUTHOR and PARTNER):
    raise SystemExit(
        "Faltan variables de entorno. Requeridas: BRIDGE_REPO, BRIDGE_AUTHOR, "
        "BRIDGE_PARTNER"
    )

MY_FILE = f"{AUTHOR}.jsonl"
PARTNER_FILE = f"{PARTNER}.jsonl"

STATE_DIR = Path.home() / ".claude-bridge"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / f"{REPO.replace('/', '__')}__{AUTHOR}.json"

mcp = MCPServer("claude-bridge")


# --------------------------------------------------------------------------- #
# GitHub helpers (via `gh api`)
# --------------------------------------------------------------------------- #
class GhError(RuntimeError):
    pass


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and proc.returncode != 0:
        raise GhError(proc.stderr.strip() or proc.stdout.strip() or "gh fallo")
    return proc


def _get_file(path: str) -> tuple[str, str | None]:
    """Devuelve (contenido_texto, sha). sha es None si el archivo no existe."""
    proc = _gh(
        [
            "api",
            "-H", "Cache-Control: no-cache",
            f"repos/{REPO}/contents/{path}",
        ],
        check=False,
    )
    if proc.returncode != 0:
        if "Not Found" in proc.stderr or "404" in proc.stderr:
            return "", None
        raise GhError(proc.stderr.strip() or "no se pudo leer el archivo")
    data = json.loads(proc.stdout)
    raw = base64.b64decode(data.get("content", ""))
    return raw.decode("utf-8"), data.get("sha")


def _put_file(path: str, content: str, sha: str | None, message: str) -> None:
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    args = [
        "api",
        "--method", "PUT",
        f"repos/{REPO}/contents/{path}",
        "-f", f"message={message}",
        "-f", f"content={b64}",
    ]
    if sha:
        args += ["-f", f"sha={sha}"]
    _gh(args)


# --------------------------------------------------------------------------- #
# Message log helpers
# --------------------------------------------------------------------------- #
def _parse(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_seen_seq": 0}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), "utf-8")


def _fmt(msgs: list[dict]) -> str:
    lines = []
    for m in msgs:
        ts = m.get("ts", "")[:19].replace("T", " ")
        lines.append(f"[#{m.get('seq','?')} {ts} UTC] {m.get('from','?')}: {m.get('text','')}")
    return "\n".join(lines)


def _read_new(update: bool) -> list[dict]:
    text, _ = _get_file(PARTNER_FILE)
    msgs = _parse(text)
    state = _load_state()
    last = state.get("last_seen_seq", 0)
    fresh = [m for m in msgs if m.get("seq", 0) > last]
    if fresh and update:
        state["last_seen_seq"] = max(m.get("seq", 0) for m in fresh)
        _save_state(state)
    return fresh


# --------------------------------------------------------------------------- #
# MCP tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def bridge_send(text: str) -> str:
    """Envia un mensaje al companero (lo anade a tu archivo del canal).

    Usar para responder o iniciar conversacion con el otro Claude. El texto
    deberia ir aprobado por tu humano salvo que te haya dicho lo contrario.
    """
    text = text.strip()
    if not text:
        return "No se envio nada: el mensaje esta vacio."

    last_err = None
    for _ in range(4):
        try:
            current, sha = _get_file(MY_FILE)
            existing = _parse(current)
            seq = (max((m.get("seq", 0) for m in existing), default=0)) + 1
            entry = {
                "seq": seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "from": AUTHOR,
                "text": text,
            }
            new_content = current
            if new_content and not new_content.endswith("\n"):
                new_content += "\n"
            new_content += json.dumps(entry, ensure_ascii=False) + "\n"
            _put_file(MY_FILE, new_content, sha, f"{AUTHOR}: mensaje #{seq}")
            return f"Enviado (#{seq}) a {PARTNER}."
        except GhError as exc:
            last_err = exc
            if "409" in str(exc) or "does not match" in str(exc).lower():
                time.sleep(1)
                continue
            return f"Error al enviar: {exc}"
    return f"Error al enviar tras varios intentos: {last_err}"


@mcp.tool()
def bridge_read() -> str:
    """Lee los mensajes NUEVOS del companero desde la ultima lectura.

    Marca esos mensajes como leidos. Si no hay nada nuevo lo indica.
    """
    try:
        fresh = _read_new(update=True)
    except GhError as exc:
        return f"Error al leer: {exc}"
    if not fresh:
        return f"No hay mensajes nuevos de {PARTNER}."
    return f"{len(fresh)} mensaje(s) nuevo(s) de {PARTNER}:\n\n{_fmt(fresh)}"


@mcp.tool()
def bridge_wait(timeout_seconds: int = 50) -> str:
    """Espera hasta que llegue un mensaje nuevo del companero o venza el tiempo.

    Sondea el canal cada pocos segundos. Devuelve los mensajes nuevos (y los
    marca como leidos) o avisa de que no hubo respuesta. Si necesitas esperar
    mas, vuelve a llamar a esta herramienta.
    """
    timeout_seconds = max(1, min(int(timeout_seconds), 280))
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fresh = _read_new(update=True)
        except GhError as exc:
            return f"Error al esperar: {exc}"
        if fresh:
            return f"{len(fresh)} mensaje(s) nuevo(s) de {PARTNER}:\n\n{_fmt(fresh)}"
        if time.monotonic() >= deadline:
            return (
                f"Sin respuesta de {PARTNER} tras {timeout_seconds}s. "
                f"Vuelve a llamar bridge_wait si quieres seguir esperando."
            )
        time.sleep(POLL_SECONDS)


@mcp.tool()
def bridge_history(limit: int = 20) -> str:
    """Muestra los ultimos mensajes de la conversacion (de ambos lados).

    No cambia el marcador de leidos. Util para ponerte al dia al empezar.
    """
    try:
        mine = _parse(_get_file(MY_FILE)[0])
        theirs = _parse(_get_file(PARTNER_FILE)[0])
    except GhError as exc:
        return f"Error al leer el historial: {exc}"
    combined = sorted(mine + theirs, key=lambda m: m.get("ts", ""))
    if not combined:
        return "El canal esta vacio todavia."
    limit = max(1, min(int(limit), 200))
    shown = combined[-limit:]
    return f"Ultimos {len(shown)} mensaje(s):\n\n{_fmt(shown)}"


if __name__ == "__main__":
    mcp.run()
