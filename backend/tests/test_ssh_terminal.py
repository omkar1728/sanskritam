"""SSH terminal relay tests against a local asyncssh server with throwaway keys (FIXTURES)."""
import asyncio, json, threading
import asyncssh, pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app import config as C, ssh_terminal

SIZES = []


class LocalServer:
    def __init__(self, host_key, client_pub):
        self.host_key, self.client_pub = host_key, client_pub
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True).start()
        ready.wait(10)

    def _run(self, ready):
        asyncio.set_event_loop(self.loop)

        async def handle(proc):
            SIZES.append(proc.get_terminal_size())
            proc.stdout.write(b"hello\r\n")
            while True:
                try:
                    d = await proc.stdin.read(1024)
                except asyncssh.TerminalSizeChanged as e:
                    SIZES.append((e.width, e.height, 0, 0))
                    continue
                if not d:
                    break
                if b"exit" in d:
                    proc.exit(0)
                    return
                proc.stdout.write(b"echo:" + d)

        async def start():
            self.srv = await asyncssh.listen(
                "127.0.0.1", 0, server_host_keys=[self.host_key],
                authorized_client_keys=self.client_pub, process_factory=handle, encoding=None)
            self.port = self.srv.sockets[0].getsockname()[1]
            ready.set()
        self.loop.run_until_complete(start())
        self.loop.run_forever()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "STORAGE", tmp_path / "store")
    ck, hk = asyncssh.generate_private_key("ssh-ed25519"), asyncssh.generate_private_key("ssh-ed25519")
    keyfile = tmp_path / "id_test"
    ck.write_private_key(str(keyfile))
    pub = tmp_path / "authorized"
    ck.write_public_key(str(pub))
    srv = LocalServer(hk, str(pub))
    app = FastAPI()
    app.include_router(ssh_terminal.router)
    yield TestClient(app), srv, keyfile, tmp_path
    srv.loop.call_soon_threadsafe(srv.srv.close)


def req(srv, keyfile, **kw):
    d = {"type": "connect", "host": "127.0.0.1", "username": "tester",
         "key_path": str(keyfile), "cols": 100, "rows": 30, "port": srv.port}
    d.update(kw)
    return d


def first_reply(client, msg, **kw):
    with client.websocket_connect("/api/ssh/terminal", **kw) as ws:
        ws.send_text(json.dumps(msg))
        return json.loads(ws.receive_text())


def test_bad_origin(env):
    client, srv, kf, _ = env
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/api/ssh/terminal", headers={"origin": "http://evil.com"}):
            pass
    assert e.value.code == 1008


@pytest.mark.parametrize("kw", [{"host": "bad host"}, {"host": "-oProxy"}, {"username": "Root"},
                                {"username": "a b"}, {"key_path": ""}])
def test_validation(env, kw):
    client, srv, kf, _ = env
    r = first_reply(client, req(srv, kf, **kw))
    assert r["type"] == "error" and r["message"]


def test_missing_key(env, tmp_path):
    client, srv, kf, _ = env
    r = first_reply(client, req(srv, kf, key_path=str(tmp_path / "nope")))
    assert r["type"] == "error" and "not found" in r["message"]


def test_not_connect_first(env):
    client, *_ = env
    assert first_reply(client, {"type": "input", "data": "x"})["type"] == "error"


def test_round_trip_resize_and_exit(env):
    client, srv, kf, _ = env
    SIZES.clear()
    with client.websocket_connect("/api/ssh/terminal", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_text(json.dumps(req(srv, kf)))
        assert json.loads(ws.receive_text()) == {"type": "status", "state": "connected"}
        buf = b""
        while b"hello" not in buf:
            buf += ws.receive_bytes()
        ws.send_bytes(b"abc")
        while b"echo:abc" not in buf:
            buf += ws.receive_bytes()
        ws.send_text(json.dumps({"type": "input", "data": "xyz"}))
        while b"echo:xyz" not in buf:
            buf += ws.receive_bytes()
        ws.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
        ws.send_bytes(b"ping")
        while buf.count(b"echo:") < 3:
            buf += ws.receive_bytes()
        assert SIZES[0][:2] == (100, 30) and SIZES[-1][:2] == (120, 40)
        ws.send_bytes(b"exit")
        while True:
            m = ws.receive()
            if m.get("text"):
                assert json.loads(m["text"]) == {"type": "status", "state": "closed"}
                break
    assert (C.STORAGE / "ssh_known_hosts").read_text().startswith(f"[127.0.0.1]:{srv.port} ssh-ed25519")


def test_host_key_changed(env):
    client, srv, kf, tmp = env
    kh = C.STORAGE / "ssh_known_hosts"
    kh.parent.mkdir(parents=True, exist_ok=True)
    other = asyncssh.generate_private_key("ssh-ed25519")
    kh.write_text(f"[127.0.0.1]:{srv.port} {other.export_public_key().decode()}")
    r = first_reply(client, req(srv, kf))
    assert r["type"] == "error" and "Host key changed" in r["message"]


def test_auth_failed(env, tmp_path):
    client, srv, kf, _ = env
    other = tmp_path / "other"
    asyncssh.generate_private_key("ssh-ed25519").write_private_key(str(other))
    r = first_reply(client, req(srv, other))
    assert r["type"] == "error" and "Authentication failed" in r["message"]


def test_connection_refused(env):
    client, srv, kf, _ = env
    r = first_reply(client, req(srv, kf, port=1))
    assert r["type"] == "error" and "refused" in r["message"].lower()


def test_passphrase_key(env, tmp_path):
    client, srv, kf, _ = env
    pk = tmp_path / "enc"
    asyncssh.generate_private_key("ssh-ed25519").write_private_key(str(pk), passphrase="pw", format_name="pkcs8-pem")
    r = first_reply(client, req(srv, pk))
    assert "Passphrase" in r["message"]
