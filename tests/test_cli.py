"""CLI `nickel serve`: o desligamento não espera para sempre por conexões SSE abertas."""
from __future__ import annotations

import signal

import uvicorn

import nickel.app as app_module
from nickel.cli import main


def test_serve_limits_graceful_shutdown_and_signals_sse(monkeypatch, tmp_path):
    monkeypatch.setenv("NICKEL_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # sem .env
    servers: list[uvicorn.Server] = []
    def fake_run(self, *args, **kwargs):
        servers.append(self)
        self.started = True

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    app_module.SHUTDOWN.clear()
    try:
        assert main(["serve"]) == 0
        assert len(servers) == 1
        server = servers[0]
        assert server.config.app == "nickel.app:main_app" and server.config.factory is True
        assert server.config.timeout_graceful_shutdown == 2
        # Ctrl+C avisa os streams SSE antes de o uvicorn esperar pelas conexões.
        server.handle_exit(signal.SIGINT, None)
        assert app_module.SHUTDOWN.is_set()
        assert server.should_exit is True
    finally:
        app_module.SHUTDOWN.clear()


def test_serve_ctrl_c_exits_cleanly(monkeypatch, tmp_path):
    """O uvicorn reenvia o SIGINT capturado depois do shutdown; `uvicorn.run` engole o KeyboardInterrupt."""
    monkeypatch.setenv("NICKEL_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # sem .env

    def interrupted_run(self, *args, **kwargs):
        self.started = True
        raise KeyboardInterrupt

    monkeypatch.setattr(uvicorn.Server, "run", interrupted_run)
    try:
        assert main(["serve"]) == 0
    finally:
        app_module.SHUTDOWN.clear()
