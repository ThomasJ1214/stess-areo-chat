"""Actual loopback listener lifecycle without requiring a desktop display."""
import socket
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.request import urlopen

import pytest
from fastapi import FastAPI

from rocket_workbench import __version__
from rocket_workbench.main import _start_local_service, _stop_local_service, main


def test_desktop_services_use_distinct_reserved_ports_and_release_them():
    app = FastAPI()

    @app.get("/ready")
    def ready():
        return {"ready": True}

    services = []
    try:
        services = [_start_local_service(app), _start_local_service(app)]
        assert services[0][3] != services[1][3]
        for _, _, _, port in services:
            with urlopen(f"http://127.0.0.1:{port}/ready", timeout=2) as response:
                assert response.status == 200
            with socket.socket() as other:
                with pytest.raises(OSError):
                    other.bind(("127.0.0.1", port))
    finally:
        for server, worker, listener, _ in services:
            _stop_local_service(server, worker, listener)
            assert not worker.is_alive()
            assert listener.fileno() == -1


def test_desktop_lifespan_failure_closes_reserved_socket(monkeypatch):
    @asynccontextmanager
    async def failed(_app):
        raise RuntimeError("Deliberate startup failure")
        yield

    real_socket, listeners = socket.socket, []

    def tracked_socket(*args, **kwargs):
        answer = real_socket(*args, **kwargs)
        if args[:2] == (socket.AF_INET, socket.SOCK_STREAM):
            listeners.append(answer)
        return answer

    monkeypatch.setattr(importlib.import_module("rocket_workbench.main"), "socket",
        SimpleNamespace(AF_INET=socket.AF_INET, SOCK_STREAM=socket.SOCK_STREAM, socket=tracked_socket))
    with pytest.raises(RuntimeError, match="could not start"):
        _start_local_service(FastAPI(lifespan=failed), timeout_seconds=2)
    assert listeners and all(listener.fileno() == -1 for listener in listeners)


def test_cli_version_is_available_without_desktop(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == f"Rocket Workbench {__version__}"
