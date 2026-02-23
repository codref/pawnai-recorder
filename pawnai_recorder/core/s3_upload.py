"""S3-compatible upload utilities for recorded audio files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config


def _normalize_segment(value: str) -> str:
    """Normalize a path segment for an S3 object key."""
    return "/".join(part for part in value.replace("\\", "/").split("/") if part)


def build_object_key(
    filename: str,
    session_id: str,
    conversation_id: Optional[str] = None,
    prefix: str = "",
) -> str:
    """Build an S3 object key using conversation/timestamp organization."""
    parts = []

    if prefix:
        normalized_prefix = _normalize_segment(prefix)
        if normalized_prefix:
            parts.append(normalized_prefix)

    if conversation_id:
        normalized_conversation = _normalize_segment(conversation_id)
        if normalized_conversation:
            parts.append(normalized_conversation)

    parts.append(_normalize_segment(session_id))
    parts.append(Path(filename).name)
    return "/".join(parts)


@dataclass
class S3Config:
    """Configuration for S3-compatible storage."""

    bucket: str
    endpoint_url: str
    access_key: str
    secret_key: str
    region: Optional[str] = None
    prefix: str = ""
    verify_ssl: bool = True
    path_style: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "S3Config":
        """Build and validate S3 config from mapping."""
        required_fields = ("bucket", "endpoint_url", "access_key", "secret_key")
        missing = [field for field in required_fields if not data.get(field)]
        if missing:
            raise ValueError(f"Missing required S3 configuration fields: {', '.join(missing)}")

        return cls(
            bucket=str(data["bucket"]),
            endpoint_url=str(data["endpoint_url"]),
            access_key=str(data["access_key"]),
            secret_key=str(data["secret_key"]),
            region=str(data["region"]) if data.get("region") else None,
            prefix=str(data.get("prefix", "")),
            verify_ssl=bool(data.get("verify_ssl", True)),
            path_style=bool(data.get("path_style", True)),
        )


class S3Uploader:
    """Uploader for S3-compatible object storage services."""

    def __init__(self, config: S3Config) -> None:
        """Initialize uploader client with S3-compatible settings."""
        self._config = config
        addressing_style = "path" if config.path_style else "virtual"

        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
            verify=config.verify_ssl,
            config=Config(s3={"addressing_style": addressing_style}),
        )

    @property
    def bucket(self) -> str:
        """Return configured bucket name."""
        return self._config.bucket

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "S3Uploader":
        """Build uploader directly from dictionary config."""
        return cls(S3Config.from_dict(data))

    def upload_file(
        self,
        local_path: str,
        session_id: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Upload local file and return uploaded object key."""
        object_key = build_object_key(
            filename=local_path,
            session_id=session_id,
            conversation_id=conversation_id,
            prefix=self._config.prefix,
        )
        self._client.upload_file(local_path, self._config.bucket, object_key)
        return object_key

    def check_bucket(self) -> bool:
        """Verify that the configured bucket is accessible.

        This makes a lightweight ``head_bucket`` call to the S3 service. It
        returns ``True`` when the bucket exists and credentials are valid. Any
        client error (not found, forbidden, etc.) is caught and ``False`` is
        returned instead.
        """
        try:
            # head_bucket does not return content, it just raises on failure
            self._client.head_bucket(Bucket=self._config.bucket)
            return True
        except Exception:  # boto3 raises botocore.exceptions.ClientError
            return False
