"""Owned local observer client: retain intent, call server collector, verify retained evidence."""

import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import httpx

API = "http://127.0.0.1:8062"
ENDPOINT = "/v1/ontology/runtime-observations"
ROOT = Path(__file__).resolve().parents[1]


class Refused(Exception):
    """Only constant, non-sensitive diagnostics may leave the client."""


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def save(path, state):
    temporary = path.with_suffix(".pending-write")
    check_paths(path, temporary)
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(state, stream, sort_keys=True, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load(path, config):
    check_paths(path)
    configuration_hash = digest(config)
    if not path.exists():
        return {
            "contract": "runtime-observer-checkpoint/1",
            "config_hash": configuration_hash,
            "pending": None,
            "last_ack": None,
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state["contract"] != "runtime-observer-checkpoint/1":
            raise ValueError()
        if state["config_hash"] != configuration_hash:
            if state["pending"] is not None:
                raise Refused("PENDING_CONFIGURATION_MISMATCH")
            return {
                "contract": state["contract"],
                "config_hash": configuration_hash,
                "pending": None,
                "last_ack": None,
            }
        if state["pending"] is not None:
            pending = state["pending"]
            UUID(pending["request_id"])
            if (
                set(pending) != {"request_id", "desired_state"}
                or pending["desired_state"] != config["desired_state"]
            ):
                raise ValueError()
        return state
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused("INVALID_CHECKPOINT") from exc


def check_paths(*paths):
    for path in paths:
        for component in [path, *path.parents]:
            if component.is_symlink() or component.is_junction():
                raise Refused("REPARSE_STATE_PATH_REFUSED")


def verify(envelope, pending, config):
    try:
        output = envelope["reported_state"]
        pin = {
            key: output["desired_state"][key] for key in ("resource_id", "version_id")
        }
        payload_hash = digest(
            {key: value for key, value in output.items() if key != "run_id"}
        )
        if (
            envelope["request_id"] != pending["request_id"]
            or output["request_id"] != pending["request_id"]
            or pin != pending["desired_state"]
            or output["scope"] != config["scope"]
            or output["contract"] != "runtime-observation/1"
            or output["calculation_runtime"] != "local-api-observer/1"
            or envelope["proof_hash"] != payload_hash
            or envelope["run_id"] != "fcr_" + payload_hash
            or output["run_id"] != envelope["run_id"]
            or output["deployment_authorized"] is not False
            or output["current_use_authorized"] is not False
        ):
            raise ValueError()
        return {
            key: envelope[key]
            for key in ("request_id", "run_id", "proof_hash", "recorded_at")
        }
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused("RECEIPT_MISMATCH") from exc


def cycle(path, config, client):
    state = load(path, config)
    if state["pending"] is None:
        state["pending"] = {
            "request_id": str(uuid4()),
            "desired_state": config["desired_state"],
        }
        save(path, state)  # Durable request identity precedes any network call.
    pending = state["pending"]
    response = client.post(ENDPOINT, json=pending)
    response.raise_for_status()
    received = response.json()
    ack = verify(received, pending, config)
    readback = client.get(ENDPOINT + "/" + pending["request_id"])
    readback.raise_for_status()
    retained = readback.json()
    if (
        verify(retained, pending, config) != ack
        or retained["reported_state"] != received["reported_state"]
    ):
        raise Refused("RECEIPT_READBACK_MISMATCH")
    state["last_ack"], state["pending"] = ack, None
    save(path, state)
    return ack


@contextmanager
def owned_lock(path):
    import msvcrt

    check_paths(path)
    with path.open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise Refused("OBSERVER_ALREADY_RUNNING") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired-resource", required=True, type=UUID)
    parser.add_argument("--desired-version", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true")
    modes.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--api-port", type=int, default=8062)
    args = parser.parse_args()
    if not 30 <= args.interval <= 86400:
        raise Refused("INTERVAL_OUT_OF_BOUNDS")
    if not 1024 <= args.api_port <= 65535:
        raise Refused("API_PORT_OUT_OF_BOUNDS")
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", args.actor_id):
        raise Refused("INVALID_OBSERVER_ACTOR")
    directory = ROOT / ".finai" / "runtime-observer"
    for component in [directory, *directory.parents]:
        if component.is_symlink() or component.is_junction():
            raise Refused("REPARSE_STATE_PATH_REFUSED")
    directory = directory.resolve()
    if ROOT.drive.upper() != "D:" or not directory.is_relative_to(ROOT / ".finai"):
        raise Refused("D_ONLY_STATE_REQUIRED")
    grants = json.loads(os.environ.get("FINAI_ACCESS_TOKENS", "{}"))
    matching = [
        (token, grant)
        for token, grant in grants.items()
        if grant.get("actor_id") == args.actor_id
        and {"ontology_admin", "ontology_read"}.issubset(grant.get("permissions", []))
    ]
    if len(matching) != 1:
        raise Refused("EXACT_OBSERVER_GRANT_REQUIRED")
    token, grant = matching[0]
    api = f"http://127.0.0.1:{args.api_port}"
    config = {
        "api": api,
        "actor_id": args.actor_id,
        "scope": grant["scope"],
        "desired_state": {
            "resource_id": str(args.desired_resource),
            "version_id": str(args.desired_version),
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    with (
        owned_lock(directory / "observer.lock"),
        httpx.Client(
            base_url=api,
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client,
    ):
        while True:
            try:
                cycle(directory / "checkpoint.json", config, client)
                print("OBSERVATION_ACKNOWLEDGED", flush=True)
            except Refused:
                raise
            except Exception:  # noqa: BLE001 - never expose transport or credential diagnostics
                print("OBSERVATION_UNACKNOWLEDGED_PENDING_RETAINED", flush=True)
                if not args.loop:
                    return 1
            if not args.loop:
                return 0
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:  # noqa: BLE001 - configuration may contain credentials
        print("OBSERVER_CONFIGURATION_OR_STORAGE_UNAVAILABLE", file=sys.stderr)
        sys.exit(2)
