"""
S3 StorageBackend, with browser-direct presigned uploads.

The contract that matters most here is url_for(): it returns the SAME relative
"/uploads/{key}" string LocalDiskBackend returns, not an S3 or presigned URL.
That is deliberate and load-bearing — photo URLs are persisted in four columns
of `photos`, embedded in jobs.variations_json by the solver, read back out and
turned into a PhotoMeta again by dsa_solver.reshuffle_single_spread_engine(),
and held indefinitely in the SPA. Any expiring URL stored in those places is a
time bomb. The media route in main.py presigns per request instead, so nothing
durable ever contains a signature and the bucket can be moved by editing config.
"""

import mimetypes
import os
from contextlib import contextmanager
from typing import BinaryIO, Dict, Iterable, Iterator, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig
from loguru import logger

from app.storage.base import ObjectInfo, PresignedUpload, StorageBackend
from app.storage.keys import validate_key
from app.storage.objcache import LocalObjectCache

# Multipart above 8 MB. Originals are capped at 20 MB, so a large original
# becomes 3 parts uploaded concurrently rather than one long serial PUT.
_TRANSFER = TransferConfig(
    multipart_threshold=8 * 1024**2,
    multipart_chunksize=8 * 1024**2,
    max_concurrency=4,
    use_threads=True,
)


class _IterReader:
    """
    Minimal read()-only file object over an iterator of byte chunks.

    upload_fileobj needs read(n); it does not need seek or a known length. This
    lets put_stream_iter keep the caller's mid-copy size cap — the iterator
    raises as soon as the cap is exceeded, and nothing more is uploaded.
    """

    def __init__(self, chunks: Iterable[bytes]):
        self._it = iter(chunks)
        self._buf = b""
        self._done = False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            parts = [self._buf]
            self._buf = b""
            parts.extend(self._it)
            self._done = True
            return b"".join(parts)

        while len(self._buf) < size and not self._done:
            try:
                self._buf += next(self._it)
            except StopIteration:
                self._done = True
        out, self._buf = self._buf[:size], self._buf[size:]
        return out


class S3Backend(StorageBackend):
    supports_presigned_upload = True
    supports_presigned_get = True

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: Optional[str] = None,
        key_prefix: str = "",
        url_prefix: str = "/uploads",
        presign_mode: str = "post",
        presign_ttl: int = 900,
        get_ttl: int = 3600,
        sse: Optional[str] = None,
        sse_kms_key: Optional[str] = None,
        storage_class: Optional[str] = None,
        cache: Optional[LocalObjectCache] = None,
        max_pool_connections: int = 32,
    ):
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        # A prefix lets dev/staging/prod share one bucket without colliding.
        cleaned = (key_prefix or "").strip("/")
        self.key_prefix = f"{cleaned}/" if cleaned else ""
        self.url_prefix = url_prefix.rstrip("/")
        self.presign_mode = presign_mode
        # Only a POST policy can carry content-length-range. A presigned PUT's
        # Content-Length is supplied by the client, so signing it enforces
        # nothing — see PresignedUpload.max_bytes.
        self.enforces_upload_size = (presign_mode == "post")
        self.presign_ttl = presign_ttl
        self.get_ttl = get_ttl
        self.cache = cache

        self._extra: Dict[str, str] = {}
        if sse:
            self._extra["ServerSideEncryption"] = sse
        if sse_kms_key:
            self._extra["SSEKMSKeyId"] = sse_kms_key
        if storage_class:
            self._extra["StorageClass"] = storage_class

        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            config=BotoConfig(
                # Required for presigned POST policies and for SSE-KMS. Not the
                # default in every region/path, so it is pinned.
                signature_version="s3v4",
                # MinIO and most self-hosted gateways have no wildcard DNS, so
                # virtual-host addressing fails there in a way that looks like a
                # network outage rather than a config error.
                s3={"addressing_style": "path" if endpoint_url else "virtual"},
                # Adaptive gives client-side rate limiting on 503 SlowDown,
                # which matters because ingest fans out a whole chunk at once.
                retries={"max_attempts": 5, "mode": "adaptive"},
                # boto3 defaults to 10. With FILTER_WORKERS threads uploading
                # thumbnails plus an export downloading originals, 10 silently
                # queues on the urllib3 connection pool.
                max_pool_connections=max_pool_connections,
                connect_timeout=5,
                read_timeout=60,
                user_agent_extra="pixovo-pte/3",
            ),
        )

    # ------------------------------------------------------------------- keys

    def _k(self, key: str) -> str:
        """
        Map a storage key to a bucket key.

        validate_key is the ONLY guard here: there is no filesystem to resolve
        against, and "originals/s/../../x.jpg" is a perfectly legal S3 key that
        simply is not the one we meant to write. Keys embed client-minted photo
        ids, so this is load-bearing.
        """
        return self.key_prefix + validate_key(key)

    def _prefix(self, prefix: str) -> str:
        return self.key_prefix + prefix

    # ------------------------------------------------------------------ write

    def put_stream(self, key: str, stream: BinaryIO, content_type: str = "image/jpeg") -> str:
        bucket_key = self._k(key)
        try:
            self.client.upload_fileobj(
                stream,
                self.bucket,
                bucket_key,
                ExtraArgs={"ContentType": content_type, **self._extra},
                Config=_TRANSFER,
            )
        except Exception:
            # upload_fileobj aborts its own multipart upload on failure, but a
            # completed-then-failed single PUT can still leave an object.
            self._delete_quietly(bucket_key)
            raise
        return self.url_for(key)

    def put_stream_iter(self, key: str, chunks: Iterable[bytes], content_type: str = "image/jpeg") -> str:
        bucket_key = self._k(key)
        try:
            self.client.upload_fileobj(
                _IterReader(chunks),
                self.bucket,
                bucket_key,
                ExtraArgs={"ContentType": content_type, **self._extra},
                Config=_TRANSFER,
            )
        except Exception:
            self._delete_quietly(bucket_key)
            raise
        return self.url_for(key)

    def put_path(self, key: str, path: str, content_type: str = "image/jpeg") -> str:
        bucket_key = self._k(key)
        guessed = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        try:
            self.client.upload_file(
                path,
                self.bucket,
                bucket_key,
                ExtraArgs={"ContentType": guessed, **self._extra},
                Config=_TRANSFER,
            )
        except Exception:
            self._delete_quietly(bucket_key)
            raise
        return self.url_for(key)

    def _delete_quietly(self, bucket_key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=bucket_key)
        except Exception:
            pass

    # ------------------------------------------------------------------- read

    def get_path(self, key: str) -> Optional[str]:
        """
        Materialise `key` locally and return the path, or None if absent.

        Bytes land in the bounded LocalObjectCache rather than a temp file the
        caller must remember to delete: the PDF exporter calls this once per
        placed photo, so a naive implementation would leak ~1.6 GB per export.
        """
        info = self.head(key)
        if info is None:
            return None
        if self.cache is None:
            raise RuntimeError("S3Backend.get_path requires a LocalObjectCache")

        bucket_key = self._k(key)

        def _download(dest: str) -> None:
            self.client.download_file(self.bucket, bucket_key, dest, Config=_TRANSFER)

        path = self.cache.fetch(key, info.etag, _download)
        # Sidecar so retention can invalidate a whole session's cached bytes;
        # slots are content-addressed, so the key is not recoverable from them.
        self.cache.record_key(key, info.etag)
        return path

    @contextmanager
    def open_local(self, key: str) -> Iterator[Optional[str]]:
        # The cache owns the lifetime, so there is nothing to release. Kept as
        # an override so the intent is explicit rather than inherited.
        yield self.get_path(key)

    def url_for(self, key: str) -> str:
        """
        Durable, non-expiring URL. See the module docstring for why this is not
        an S3 URL.
        """
        return f"{self.url_prefix}/{key}"

    def key_for_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        clean = url.split("?")[0]
        # Tolerate an absolute origin so a legacy or CDN-rewritten URL still
        # round-trips to a key.
        if "://" in clean:
            clean = "/" + clean.split("://", 1)[1].split("/", 1)[-1]
        prefix = self.url_prefix + "/"
        if not clean.startswith(prefix):
            return None
        return clean[len(prefix):]

    def exists(self, key: str) -> bool:
        return self.head(key) is not None

    def head(self, key: str) -> Optional[ObjectInfo]:
        try:
            bucket_key = self._k(key)
        except ValueError:
            return None
        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=bucket_key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return None
            if status == 403:
                # A bucket policy denying HeadObject also returns 403. Treating
                # it as "absent" is the safe read, but it means IAM is wrong and
                # every upload will appear to vanish — so say so loudly.
                logger.error(
                    f"[S3] HeadObject denied (403) for {bucket_key} — check the IAM "
                    f"policy grants s3:GetObject on this prefix. Treating as absent."
                )
                return None
            raise
        return ObjectInfo(
            size=int(resp["ContentLength"]),
            content_type=resp.get("ContentType"),
            etag=(resp.get("ETag") or "").strip('"') or None,
        )

    # ----------------------------------------------------------------- delete

    def delete(self, key: str) -> None:
        try:
            bucket_key = self._k(key)
        except ValueError:
            return
        self.client.delete_object(Bucket=self.bucket, Key=bucket_key)

    def delete_prefix(self, prefix: str) -> int:
        """
        Delete every object under `prefix`. Returns the count.

        The trailing slash is mandatory, not cosmetic: without it a prefix of
        "originals/sess_a" also matches "originals/sess_abc/...", so retention
        on one session would delete another's originals. LocalDiskBackend is
        directory-based and immune to this; S3 prefixes are plain strings.
        """
        if not prefix:
            return 0
        raw = prefix.rstrip("/")
        try:
            validate_key(raw)
        except ValueError:
            return 0
        scoped = self._prefix(raw) + "/"

        removed = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=scoped):
            batch = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if not batch:
                continue
            # delete_objects caps at 1000 keys per call; the paginator already
            # yields at most 1000 per page, but slice defensively.
            for i in range(0, len(batch), 1000):
                resp = self.client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": batch[i:i + 1000], "Quiet": True},
                )
                removed += len(batch[i:i + 1000]) - len(resp.get("Errors", []))
        if self.cache is not None:
            self.cache.invalidate_prefix(raw)
        return removed

    # ------------------------------------------------------------- accounting

    def total_bytes(self, prefix: str = "") -> int:
        scoped = self._prefix(prefix.rstrip("/") + "/") if prefix else self.key_prefix
        total = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=scoped):
            for obj in page.get("Contents", []):
                total += int(obj.get("Size") or 0)
        return total

    # ---------------------------------------------------------------- presign

    def presigned_upload(
        self,
        key: str,
        *,
        content_type: str,
        max_bytes: int,
        expires_in: int,
    ) -> PresignedUpload:
        bucket_key = self._k(key)

        if self.presign_mode == "post":
            fields: Dict[str, str] = {
                "Content-Type": content_type,
                # Makes S3 return 201 with an XML body containing the ETag
                # rather than an empty 204, so the browser can surface a real
                # error and pass the ETag along (still verified server-side).
                "success_action_status": "201",
            }
            conditions = [
                {"success_action_status": "201"},
                ["starts-with", "$Content-Type", "image/"],
                # The only real size enforcement available. S3 rejects an
                # oversize body before accepting it.
                ["content-length-range", 1, int(max_bytes)],
            ]
            # SSE / storage class must appear in BOTH the fields and the
            # conditions. Omitting them from the conditions makes every upload
            # 403 under a bucket policy that denies unencrypted PutObject.
            for header, value in (
                ("x-amz-server-side-encryption", self._extra.get("ServerSideEncryption")),
                ("x-amz-server-side-encryption-aws-kms-key-id", self._extra.get("SSEKMSKeyId")),
                ("x-amz-storage-class", self._extra.get("StorageClass")),
            ):
                if value:
                    fields[header] = value
                    conditions.append({header: value})

            post = self.client.generate_presigned_post(
                self.bucket,
                bucket_key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
            return PresignedUpload(
                mode="s3_post",
                url=post["url"],
                key=key,
                expires_in=expires_in,
                max_bytes=int(max_bytes),
                fields=post["fields"],
            )

        params = {"Bucket": self.bucket, "Key": bucket_key, "ContentType": content_type}
        params.update(self._extra)
        url = self.client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in
        )
        headers = {"Content-Type": content_type}
        if self._extra.get("ServerSideEncryption"):
            headers["x-amz-server-side-encryption"] = self._extra["ServerSideEncryption"]
        return PresignedUpload(
            mode="s3_put",
            url=url,
            key=key,
            expires_in=expires_in,
            # None, not max_bytes: a presigned PUT cannot constrain the size.
            # Confirm-time head() is the only defence.
            max_bytes=None,
            headers=headers,
        )

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: int,
        download_filename: Optional[str] = None,
    ) -> str:
        params = {"Bucket": self.bucket, "Key": self._k(key)}
        if download_filename:
            safe = os.path.basename(download_filename).replace('"', "")
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_in
        )

    # ----------------------------------------------------------------- health

    def startup_check(self) -> None:
        """
        Prove the configuration works before the process serves traffic.

        Raises on anything that would make every upload fail. Called from
        config._build_storage(), so a misconfiguration is a boot crash rather
        than a running server that quietly writes photos nowhere.
        """
        import email.utils
        import time

        resp = self.client.head_bucket(Bucket=self.bucket)
        headers = resp.get("ResponseMetadata", {}).get("HTTPHeaders", {})

        # Clock skew breaks sigv4 outright: >15 minutes off and every call,
        # including every presign we hand a browser, fails with
        # RequestTimeTooSkewed. Only the server signs, so only its clock matters.
        server_date = headers.get("date")
        if server_date:
            try:
                remote = email.utils.parsedate_to_datetime(server_date).timestamp()
                skew = abs(time.time() - remote)
                if skew > 300:
                    raise RuntimeError(
                        f"Host clock is {skew:.0f}s off S3's ({server_date}). "
                        f"sigv4 fails above ~900s — fix NTP before starting."
                    )
                logger.info(f"[S3] Clock skew {skew:.1f}s (limit 300s)")
            except (TypeError, ValueError):
                logger.warning(f"[S3] Could not parse S3 Date header: {server_date!r}")

        # A missing CORS policy is invisible until the first browser upload,
        # where it surfaces as an opaque 'Failed to fetch' with no status.
        try:
            cors = self.client.get_bucket_cors(Bucket=self.bucket)
            rules = cors.get("CORSRules", [])
            origins = sorted({o for r in rules for o in r.get("AllowedOrigins", [])})
            methods = sorted({m for r in rules for m in r.get("AllowedMethods", [])})
            logger.info(f"[S3] Bucket CORS: methods={methods} origins={origins}")
            missing = {"POST", "PUT"} - set(methods)
            if missing:
                logger.warning(
                    f"[S3] Bucket CORS allows no {'/'.join(sorted(missing))} — direct "
                    f"browser uploads will fail with an opaque network error."
                )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchCORSConfiguration", "NoSuchCORSConfig"):
                logger.warning(
                    "[S3] Bucket has NO CORS configuration. Direct browser uploads "
                    "will fail. See docs/S3_SETUP.md."
                )
            else:
                logger.warning(f"[S3] Could not read bucket CORS: {exc}")

        logger.info(
            f"[S3] Ready: bucket={self.bucket} region={self.region} "
            f"prefix={self.key_prefix or '(none)'} mode={self.presign_mode} "
            f"endpoint={self.endpoint_url or 'aws'}"
        )
