"""Private create-only content-addressed evidence; no public URLs or delete operations."""

from hashlib import sha256
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope, canonical_sha256
from finai_api.domain.ingest import SourceRetention, SourceStorage


class EvidenceStoreUnavailable(RuntimeError):
    pass


def object_key(scope: ExactScope, content_hash: str) -> str:
    return f"tenant/{scope.tenant_id}/scope/{canonical_sha256(scope)}/sha256/{content_hash}"


def _client() -> Any:
    settings = get_settings()
    if not (
        settings.s3_endpoint
        and settings.s3_access_key.get_secret_value()
        and settings.s3_secret_key.get_secret_value()
        and settings.s3_bucket
    ):
        raise EvidenceStoreUnavailable("Private evidence object storage is not configured")
    try:
        return boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_region,
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )
    except (BotoCoreError, ValueError) as exc:
        raise EvidenceStoreUnavailable("Private evidence object storage is unavailable") from exc


def check_ready() -> None:
    try:
        client = _client()
        client.head_bucket(Bucket=get_settings().s3_bucket)
        _check_retention(client, get_settings().s3_bucket)
    except (BotoCoreError, ClientError, OSError) as exc:
        raise EvidenceStoreUnavailable("Private evidence object storage is unavailable") from exc


def _check_retention(client: Any, bucket: str) -> None:
    """A dedicated evidence bucket must not have automatic object deletion rules."""
    try:
        lifecycle = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchLifecycleConfiguration":
            return
        raise
    for rule in lifecycle.get("Rules", []):
        if rule.get("Status") == "Enabled" and (
            "Expiration" in rule or "NoncurrentVersionExpiration" in rule
        ):
            raise EvidenceStoreUnavailable(
                "Evidence bucket automatic expiry conflicts with governed retention"
            )


def _verified_get(client: Any, metadata: SourceStorage) -> tuple[bytes, str | None]:
    args: dict[str, Any] = {"Bucket": metadata.bucket, "Key": metadata.object_key}
    if metadata.version_id is not None:
        args["VersionId"] = metadata.version_id
    response = client.get_object(**args)
    body = response["Body"]
    try:
        content = body.read(metadata.byte_length + 1)
    finally:
        body.close()
    if (
        len(content) != metadata.byte_length
        or response.get("ContentLength") != metadata.byte_length
        or sha256(content).hexdigest() != metadata.sha256
    ):
        raise EvidenceStoreUnavailable("Retained source integrity verification failed")
    version = response.get("VersionId")
    if metadata.version_id is not None and version != metadata.version_id:
        raise EvidenceStoreUnavailable("Retained source version verification failed")
    return content, str(version) if version is not None else None


def preserve(scope: ExactScope, content: bytes, expected_hash: str) -> SourceStorage:
    if not content or len(content) > 16_000_000 or sha256(content).hexdigest() != expected_hash:
        raise EvidenceStoreUnavailable("Source integrity verification failed before retention")
    client = _client()
    metadata = SourceStorage(
        bucket=get_settings().s3_bucket,
        object_key=object_key(scope, expected_hash),
        sha256=expected_hash,
        byte_length=len(content),
        retention=SourceRetention(),
    )
    try:
        _check_retention(client, metadata.bucket)
        try:
            response = client.put_object(
                Bucket=metadata.bucket,
                Key=metadata.object_key,
                Body=content,
                ContentType="text/csv; charset=utf-8",
                IfNoneMatch="*",
                Metadata={"sha256": expected_hash},
            )
            version = response.get("VersionId")
            metadata = metadata.model_copy(
                update={"version_id": str(version) if version is not None else None}
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") not in (409, 412):
                raise
            # Concurrent create/replay: verify actual bytes, never trust object metadata alone.
        _, version = _verified_get(client, metadata)
        return metadata.model_copy(update={"version_id": version})
    except (BotoCoreError, ClientError, OSError, KeyError) as exc:
        raise EvidenceStoreUnavailable("Private evidence object storage is unavailable") from exc


def read(scope: ExactScope, metadata: SourceStorage) -> bytes:
    if metadata.object_key != object_key(scope, metadata.sha256):
        raise EvidenceStoreUnavailable("Retained source scope verification failed")
    try:
        content, _ = _verified_get(_client(), metadata)
        return content
    except (BotoCoreError, ClientError, OSError, KeyError) as exc:
        raise EvidenceStoreUnavailable("Private evidence object storage is unavailable") from exc
