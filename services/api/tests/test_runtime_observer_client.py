"""Simulated transport failures prove durable client identity, not actual server collection."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_observer_client",
    Path(__file__).resolve().parents[3] / "scripts/g8-runtime-observer.py",
)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def config():
    return {
        "api": observer.API,
        "actor_id": "synthetic",
        "scope": {"tenant_id": str(uuid4())},
        "desired_state": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
    }


def envelope(request, configuration):
    payload = {
        "request_id": request["request_id"],
        "desired_state": request["desired_state"],
        "contract": "runtime-observation/1",
        "scope": configuration["scope"],
        "calculation_runtime": "local-api-observer/1",
        "deployment_authorized": False,
        "current_use_authorized": False,
    }
    proof = observer.digest(payload)
    payload["run_id"] = "fcr_" + proof
    return {
        "request_id": request["request_id"],
        "run_id": payload["run_id"],
        "proof_hash": proof,
        "recorded_at": "2026-09-07T00:00:00+00:00",
        "reported_state": payload,
    }


def test_lost_ack_and_process_recovery_reuse_exact_retained_body(tmp_path):
    state = tmp_path / "checkpoint.json"
    configuration = config()
    posted, retained = [], {}

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert json.loads(state.read_text())["pending"] == body
            posted.append(body)
            retained.setdefault(body["request_id"], envelope(body, configuration))
            if len(posted) == 1:
                raise httpx.ReadTimeout("Simulated lost acknowledgement")
            return httpx.Response(200, json=retained[body["request_id"]])
        return httpx.Response(200, json=retained[request.url.path.rsplit("/", 1)[1]])

    with httpx.Client(base_url=observer.API, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadTimeout):
            observer.cycle(state, configuration, client)
        pending = json.loads(state.read_text())["pending"]
        assert pending == posted[0]
        # A new invocation loads disk; no in-memory request identity is reused.
        ack = observer.cycle(state, configuration, client)
        assert posted[1] == posted[0] and ack["request_id"] == pending["request_id"]
        assert json.loads(state.read_text())["pending"] is None
        observer.cycle(state, configuration, client)
        assert posted[2]["request_id"] != posted[0]["request_id"]


def test_crash_after_server_receipt_before_checkpoint_replays(tmp_path, monkeypatch):
    state = tmp_path / "checkpoint.json"
    configuration = config()
    original = observer.save
    posted = []

    def crash(path, value):
        if value["pending"] is None:
            raise OSError("Simulated checkpoint interruption")
        original(path, value)

    def handler(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
        return httpx.Response(200, json=envelope(posted[-1], configuration))

    with httpx.Client(base_url=observer.API, transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(observer, "save", crash)
        with pytest.raises(OSError):
            observer.cycle(state, configuration, client)
        monkeypatch.setattr(observer, "save", original)
        observer.cycle(state, configuration, client)
        assert posted[0] == posted[1]


def test_pending_configuration_change_and_mismatched_readback_fail_closed(tmp_path):
    path, configuration = tmp_path / "checkpoint.json", config()
    posted = []

    def handler(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
        result = envelope(posted[-1], configuration)
        if request.method == "GET":
            result["proof_hash"] = "f" * 64
        return httpx.Response(200, json=result)

    with httpx.Client(base_url=observer.API, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(observer.Refused, match="RECEIPT_MISMATCH"):
            observer.cycle(path, configuration, client)
        pending = json.loads(path.read_text())["pending"]
        assert pending == posted[0]
        with pytest.raises(observer.Refused, match="PENDING_CONFIGURATION_MISMATCH"):
            observer.cycle(path, {**configuration, "actor_id": "changed"}, client)
        assert len(posted) == 1
