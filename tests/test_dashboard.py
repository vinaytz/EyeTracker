import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from eyetracker.cli import cmd_dashboard
from eyetracker.config import Config, Paths
from eyetracker.dashboard import serve


@pytest.fixture
def server(tmp_path):
    paths = Paths(tmp_path / "config.toml", tmp_path / "data", tmp_path / "run")
    paths.ensure()
    httpd = serve(paths, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def get(server, path, host=None):
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}")
    if host:
        request.add_header("Host", host)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def test_listens_only_on_this_machine(server):
    assert server.server_address[0] == "127.0.0.1"


def test_serves_the_page_with_a_locked_down_policy(server):
    status, headers, body = get(server, "/")
    assert status == 200
    assert b"<title>Eye Tracker</title>" in body
    policy = headers["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy


def test_page_loads_nothing_from_the_network(server):
    _, _, body = get(server, "/")
    assert b"https://" not in body
    assert b"http://www.w3.org" in body  # SVG namespaces are identifiers, not requests
    assert b"src=\"http" not in body


def test_data_endpoint_shape(server):
    status, _, body = get(server, "/api/data?day=2026-03-10")
    data = json.loads(body)
    assert status == 200
    assert data["summary"]["day"] == "2026-03-10"
    assert data["timeline"] == []
    assert len(data["history"]) == 14
    assert data["live"] == {"state": "not-running"}


def test_data_endpoint_defaults_to_today(server):
    _, _, body = get(server, "/api/data")
    data = json.loads(body)
    assert data["summary"]["day"] == data["today"]


def test_bad_day_is_rejected(server):
    assert get(server, "/api/data?day=yesterday")[0] == 400


def test_unknown_path_is_not_found(server):
    assert get(server, "/../../etc/passwd")[0] == 404


def test_requests_from_another_hostname_are_refused(server):
    assert get(server, "/api/data", host="evil.example:8765")[0] == 403
    assert get(server, "/", host="evil.example")[0] == 403


def test_a_busy_port_gives_a_clear_message(server, capsys):
    args = SimpleNamespace(port=server.server_port, no_browser=True)
    assert cmd_dashboard(Config(), None, args) == 1
    assert "eyetracker dashboard --port" in capsys.readouterr().out
