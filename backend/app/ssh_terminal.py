"""WebSocket SSH terminal relay: /api/ssh/terminal (browser xterm.js <-> asyncssh PTY)."""
import asyncio, json, logging, re
from pathlib import Path
from urllib.parse import urlparse

import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import config as C

log = logging.getLogger(__name__)
router = APIRouter()

CONNECT_TIMEOUT = 15
_HOST_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._:\-]*$")
_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]*$")
_OK_ORIGINS = {"localhost", "127.0.0.1", "::1"}


def known_hosts_path() -> Path:
    return C.STORAGE / "ssh_known_hosts"


def _origin_ok(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        return (urlparse(origin).hostname or "") in _OK_ORIGINS
    except ValueError:
        return False


class HostKeyChanged(Exception):
    pass


def _check_host_key(host: str, port: int, key: asyncssh.SSHKey) -> None:
    """Trust on first use. Raises HostKeyChanged if the host is known with other keys."""
    path = known_hosts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    kh = asyncssh.read_known_hosts(str(path))
    trusted = kh.match(host, "", port)[0]
    if not trusted:
        with open(path, "a") as f:
            hostpat = host if port == 22 else f"[{host}]:{port}"
            f.write(f"{hostpat} {key.export_public_key().decode().strip()}\n")
        return
    fp = key.get_fingerprint()
    if not any(t.get_fingerprint() == fp for t in trusted):
        raise HostKeyChanged()


def _validate(msg: dict) -> tuple[dict | None, str | None]:
    host, user, kp = msg.get("host"), msg.get("username"), msg.get("key_path")
    if not isinstance(host, str) or not _HOST_RE.match(host) or len(host) > 255:
        return None, "Invalid host: use an IP address or hostname."
    if not isinstance(user, str) or not _USER_RE.match(user) or len(user) > 64:
        return None, "Invalid username."
    if not isinstance(kp, str) or not kp.strip():
        return None, "Key file path is required."
    try:
        port = int(msg.get("port") or 22)
        cols = int(msg.get("cols") or 80)
        rows = int(msg.get("rows") or 24)
    except (TypeError, ValueError):
        return None, "Invalid port or terminal size."
    if not 1 <= port <= 65535:
        return None, "Invalid port."
    cols, rows = max(1, min(cols, 1000)), max(1, min(rows, 1000))
    path = Path(kp.strip()).expanduser()
    if not path.is_file():
        return None, "Key file not found."
    return dict(host=host, username=user, key=path, port=port, cols=cols, rows=rows), None


async def _open(p: dict) -> asyncssh.SSHClientConnection:
    host, port = p["host"], p["port"]
    try:
        key = asyncssh.read_private_key(str(p["key"]))
    except asyncssh.KeyImportError as e:
        if "passphrase" in str(e).lower():
            raise RuntimeError("Passphrase-protected keys are not supported.")
        raise RuntimeError("Key file is not a valid private key.")
    except OSError:
        raise RuntimeError("Key file is unreadable (check permissions).")

    changed = []

    class Client(asyncssh.SSHClient):
        # Empty trusted set makes asyncssh call this for every key; it enforces TOFU.
        def validate_host_public_key(self, h, addr, pt, k):
            try:
                _check_host_key(host, port, k)
                return True
            except HostKeyChanged:
                changed.append(True)
                return False

    async def attempt():
        conn, _c = await asyncssh.create_connection(
            Client, host, port, username=p["username"], client_keys=[key],
            known_hosts=lambda h, a, pt: ([], [], []), password=None, agent_path=None,
            preferred_auth="publickey", connect_timeout=CONNECT_TIMEOUT,
            login_timeout=CONNECT_TIMEOUT, config=None)
        return conn
    try:
        return await asyncio.wait_for(attempt(), CONNECT_TIMEOUT + 2)
    except asyncssh.HostKeyNotVerifiable:
        if not changed:
            raise RuntimeError("Host key could not be verified. Connection refused.")
        raise RuntimeError("Host key changed: the server's key differs from the one "
                           "trusted earlier. Connection refused.")
    except asyncssh.PermissionDenied:
        raise RuntimeError("Authentication failed: the server rejected this key/username.")
    except (asyncio.TimeoutError, TimeoutError):
        raise RuntimeError("Connection timed out after 15 seconds.")
    except ConnectionRefusedError:
        raise RuntimeError("Connection refused by the host.")
    except asyncssh.Error as e:
        raise RuntimeError(f"SSH error: {e.reason or type(e).__name__}")
    except OSError as e:
        raise RuntimeError(f"Network error: {e.strerror or type(e).__name__}")


async def _send(ws: WebSocket, obj: dict) -> None:
    try:
        await ws.send_text(json.dumps(obj))
    except Exception:
        pass


@router.websocket("/api/ssh/terminal")
async def ssh_terminal(ws: WebSocket):
    if not _origin_ok(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    await ws.accept()
    conn = None
    try:
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), 60))
            if not isinstance(first, dict) or first.get("type") != "connect":
                raise ValueError
        except WebSocketDisconnect:
            return
        except Exception:
            await _send(ws, {"type": "error", "message": "First message must be a connect request."})
            await ws.close()
            return
        params, err = _validate(first)
        if err:
            await _send(ws, {"type": "error", "message": err})
            await ws.close()
            return
        try:
            conn = await _open(params)
            proc = await conn.create_process(
                term_type="xterm-256color", term_size=(params["cols"], params["rows"]),
                encoding=None)
        except RuntimeError as e:
            await _send(ws, {"type": "error", "message": str(e)})
            await ws.close()
            return
        except Exception as e:
            log.warning("ssh session failed: %s %s", type(e).__name__, e)
            await _send(ws, {"type": "error", "message": "Could not start a shell on the remote host."})
            await ws.close()
            return
        await _send(ws, {"type": "status", "state": "connected"})

        async def pump_out():
            while True:
                data = await proc.stdout.read(65536)
                if not data:
                    break
                await ws.send_bytes(data)

        async def pump_in():
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    return
                if m.get("bytes") is not None:
                    proc.stdin.write(m["bytes"])
                elif m.get("text") is not None:
                    try:
                        d = json.loads(m["text"])
                    except ValueError:
                        continue
                    if not isinstance(d, dict):
                        continue
                    if d.get("type") == "input" and isinstance(d.get("data"), str):
                        proc.stdin.write(d["data"].encode())
                    elif d.get("type") == "resize":
                        try:
                            c = max(1, min(int(d["cols"]), 1000))
                            r = max(1, min(int(d["rows"]), 1000))
                            proc.change_terminal_size(c, r)
                        except (KeyError, TypeError, ValueError):
                            pass

        t_out = asyncio.create_task(pump_out())
        t_in = asyncio.create_task(pump_in())
        done, pending = await asyncio.wait({t_out, t_in}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if t_out in done:
            await _send(ws, {"type": "status", "state": "closed"})
            await ws.close()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ssh relay error: %s", type(e).__name__)
    finally:
        if conn is not None:
            conn.close()
