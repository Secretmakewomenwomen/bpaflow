from pathlib import Path

import alibabacloud_oss_v2 as oss

from app.core.config import Settings


class OssService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _create_client(self) -> oss.Client:
        credentials_provider = oss.credentials.StaticCredentialsProvider(
            access_key_id=self.settings.oss_access_key_id,
            access_key_secret=self.settings.oss_access_key_secret,
        )
        cfg = oss.config.load_default()
        cfg.credentials_provider = credentials_provider
        cfg.region = self.settings.oss_region
        cfg.endpoint = self.settings.oss_endpoint
        return oss.Client(cfg)

    def upload_from_path(self, file_path: str, object_key: str) -> dict[str, str]:
        client = self._create_client()
        client.put_object_from_file(
            oss.PutObjectRequest(
                bucket=self.settings.oss_bucket,
                key=object_key,
            ),
            file_path,
        )

        base_url = self.settings.oss_public_base_url.rstrip("/")
        return {
            "bucket": self.settings.oss_bucket,
            "key": object_key,
            "public_url": f"{base_url}/{object_key}",
            "file_name": Path(file_path).name,
        }

    def delete_object(self, object_key: str) -> None:
        client = self._create_client()
        client.delete_object(
            oss.DeleteObjectRequest(
                bucket=self.settings.oss_bucket,
                key=object_key,
            )
        )

    def get_object_bytes(self, object_key: str) -> bytes:
        client = self._create_client()
        result = client.get_object(
            oss.GetObjectRequest(
                bucket=self.settings.oss_bucket,
                key=object_key,
            )
        )
        body = getattr(result, "body", None)
        if isinstance(body, bytes):
            return body
        if hasattr(body, "read"):
            return body.read()
        if hasattr(result, "read"):
            return result.read()
        raise RuntimeError("OSS get_object returned an unreadable response body.")
