"""Start an isolated real evidence store; merge only S3 settings into local.json.

This is a disposable test fixture, never a command for the mounted product store.
The caller owns process lifetime. Credentials and source bytes are never logged.
"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError


def save_private(path: Path, value: dict) -> None:
    with path.open("w", encoding="utf-8") as target:
        os.chmod(path, 0o600)
        json.dump(value, target, indent=2)
    if os.name == "nt":
        # Windows chmod cannot restrict ACLs. Keep the current user and SYSTEM only.
        sid = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r",
             f"*{sid}:(F)", "*S-1-5-18:(F)"],
            check=True, capture_output=True,
        )


def denied(operation) -> None:
    try:
        operation()
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] == 403:
            return
        raise
    raise RuntimeError("Disposable storage privilege boundary was not enforced")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path(".finai"))
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9064)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    # Guard the production ports and prevent accidental writes to a mounted data path.
    if args.port in (9000, 9001, 9061, 9062) or not 1024 <= args.port <= 65535:
        raise ValueError("Choose a dedicated disposable test port")
    if os.name == "nt" and runtime.drive.upper() != "D:":
        raise ValueError("Local test artifacts must remain on D:")
    runtime.mkdir(parents=True, exist_ok=True)
    data = runtime / "data" / "minio-ci"
    if data.exists() and any(data.iterdir()):
        raise ValueError("Refusing to reuse existing evidence data; choose a fresh fixture runtime")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    endpoint = f"http://127.0.0.1:{args.port}"
    bucket = "g8-ci-evidence"
    root_key, root_secret = "ci" + secrets.token_hex(10), secrets.token_hex(32)
    environment = {
        **os.environ,
        "MINIO_ROOT_USER": root_key,
        "MINIO_ROOT_PASSWORD": root_secret,
        "MINIO_BROWSER": "off",
        "MINIO_UPDATE": "off",
    }
    data.mkdir(parents=True, exist_ok=True)
    with (runtime / "minio-ci.log").open("wb") as log:
        process = subprocess.Popen(
            [str(args.server.resolve()), "server", str(data), "--address",
             f"127.0.0.1:{args.port}"],
            env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Disposable MinIO exited before readiness")
            try:
                with urlopen(endpoint + "/minio/health/live", timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Disposable MinIO readiness timeout")
        options = {
            "endpoint_url": endpoint, "region_name": "us-east-1",
            "config": Config(s3={"addressing_style": "path"}),
        }
        admin = boto3.client("s3", **options,
                             aws_access_key_id=root_key, aws_secret_access_key=root_secret)
        admin.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
        admin.put_bucket_versioning(Bucket=bucket,
                                    VersioningConfiguration={"Status": "Enabled"})
        policy = {
            "Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetBucketLocation", "s3:GetBucketVersioning",
                 "s3:GetLifecycleConfiguration", "s3:ListBucket"],
                 "Resource": [f"arn:aws:s3:::{bucket}"]},
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion",
                 "s3:PutObject"], "Resource": [f"arn:aws:s3:::{bucket}/*"]},
            ],
        }
        policy_path = runtime / "minio-ci-policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        result = subprocess.run(
            [str(args.client.resolve()), "--json", "admin", "user", "svcacct", "add",
             "cifixture", root_key, "--policy", str(policy_path)],
            env={**os.environ, "MC_HOST_cifixture":
                 f"http://{root_key}:{root_secret}@127.0.0.1:{args.port}",
                 "MC_CONFIG_DIR": str(runtime / "mc-ci-config")},
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            # mc output can contain credential material; deliberately do not echo it.
            raise RuntimeError("Restricted MinIO application credential provisioning failed")
        credentials = json.loads(result.stdout)
        app = boto3.client("s3", **options, aws_access_key_id=credentials["accessKey"],
                           aws_secret_access_key=credentials["secretKey"])
        assert app.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
        assert admin.get_object_lock_configuration(Bucket=bucket)[
            "ObjectLockConfiguration"]["ObjectLockEnabled"] == "Enabled"
        try:
            app.get_bucket_lifecycle_configuration(Bucket=bucket)
        except ClientError as error:
            assert error.response["Error"]["Code"] == "NoSuchLifecycleConfiguration"
        else:
            raise RuntimeError("Fresh disposable evidence bucket unexpectedly has a lifecycle")
        key, content = "fixture/retention-readiness", b"private retained evidence"
        first = app.put_object(Bucket=bucket, Key=key, Body=content, IfNoneMatch="*")
        version = first["VersionId"]
        assert version and version != "null"
        retained = app.get_object(Bucket=bucket, Key=key, VersionId=version)
        assert retained["Body"].read() == content
        retained["Body"].close()
        try:
            app.put_object(Bucket=bucket, Key=key, Body=b"replacement", IfNoneMatch="*")
        except ClientError as error:
            assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 412
        else:
            raise RuntimeError("Create-only replay changed retained evidence")
        denied(lambda: app.delete_object(Bucket=bucket, Key=key, VersionId=version))
        denied(lambda: app.put_bucket_versioning(Bucket=bucket,
                                                VersioningConfiguration={"Status": "Suspended"}))
        denied(lambda: app.create_bucket(Bucket="g8-ci-forbidden"))
        anonymous = boto3.client("s3", endpoint_url=endpoint,
                                 config=Config(signature_version=UNSIGNED))
        denied(lambda: anonymous.get_object(Bucket=bucket, Key=key))
        config_path = runtime / "local.json"
        configuration = (json.loads(config_path.read_text(encoding="utf-8-sig"))
                         if config_path.exists() else {})
        configuration.update({
            "FINAI_S3_ENDPOINT": endpoint, "FINAI_S3_BUCKET": bucket,
            "FINAI_S3_REGION": "us-east-1",
            "FINAI_S3_ACCESS_KEY": credentials["accessKey"],
            "FINAI_S3_SECRET_KEY": credentials["secretKey"],
        })
        save_private(config_path, configuration)
        (runtime / "minio-ci.pid").write_text(str(process.pid), encoding="ascii")
        evidence = {
            "status": "NATIVE_PRIVATE_VERSIONED_STORAGE_PASS", "endpoint": endpoint,
            "pid": process.pid, "bucket": bucket, "data_path": str(data),
            "checks": ["versioned_write_read", "create_only_replay", "no_expiry_lifecycle",
                       "object_lock_capability", "anonymous_read_denied", "version_delete_denied",
                       "versioning_change_denied", "foreign_bucket_creation_denied"],
            "application_credentials": "restricted_service_account", "root_credentials_saved": False,
        }
        (runtime / "minio-ci-evidence.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence))
    except BaseException:
        process.terminate()
        process.wait(timeout=10)
        raise


if __name__ == "__main__":
    main()
