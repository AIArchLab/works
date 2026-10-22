"""Google Drive transport for the injected object-store contract.

This module contains no credential, store id, or provider SDK. The operator
injects two callables:

* ``http(method, url, headers, body) -> (status, payload_bytes)``
* ``token_provider() -> str`` (a bearer token for the authorized principal)

Only documented Drive v3 REST endpoints are used. Drive does not expose
SHA-256, so every digest is computed from a complete independent read-back of
the stored bytes; the upload acknowledgement is never treated as evidence.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Callable
from urllib.parse import quote

from ..storage import StoredFile

API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"

Http = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]


class GDriveError(RuntimeError):
    """A non-success Drive response. Never converted into a successful result."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = body
        super().__init__(f"Drive HTTP {status}: {body[:200]!r}")


class GDriveClient:
    """`ObjectStoreClient` backed by the Drive v3 REST API.

    ``store_id`` is the Drive folder id of the configured store; it is passed
    per call by ``ObjectStoreAdapter`` and is not stored on the client.
    """

    def __init__(self, http: Http, token_provider: Callable[[], str]):
        if not callable(http) or not callable(token_provider):
            raise ValueError("http and token_provider must be callable")
        self._http = http
        self._token = token_provider

    # -- transport -------------------------------------------------------
    def _request(self, method: str, url: str, *, body: bytes | None = None,
                 content_type: str | None = None,
                 expect: tuple[int, ...] = (200,)) -> bytes:
        token = self._token()
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token_provider returned no token")
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        status, payload = self._http(method, url, headers, body)
        if status not in expect:
            raise GDriveError(status, payload)
        return payload

    # -- ObjectStoreClient ----------------------------------------------
    def put_object(self, store_id: str, name: str, data: bytes) -> StoredFile:
        if not isinstance(store_id, str) or not store_id.strip():
            raise ValueError("store_id is required")
        if not isinstance(name, str) or not name.strip() or not isinstance(data, bytes):
            raise ValueError("put_object requires a nonempty name and bytes")

        boundary = "skytale-" + uuid.uuid4().hex
        meta = json.dumps({"name": name, "parents": [store_id]}).encode("utf-8")
        body = b"".join([
            b"--", boundary.encode(), b"\r\n",
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
            meta, b"\r\n",
            b"--", boundary.encode(), b"\r\n",
            b"Content-Type: application/octet-stream\r\n\r\n",
            data, b"\r\n",
            b"--", boundary.encode(), b"--\r\n",
        ])
        created = json.loads(self._request(
            "POST",
            f"{UPLOAD}/files?uploadType=multipart&fields=id,name,parents,size&supportsAllDrives=true",
            body=body,
            content_type=f"multipart/related; boundary={boundary}",
            expect=(200, 201),
        ))
        file_id = created.get("id")
        if not file_id:
            raise GDriveError(0, b"upload response has no file id")
        return self.stat_object(store_id, file_id)

    def get_object(self, store_id: str, file_id: str) -> bytes:
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("file_id is required")
        return self._request(
            "GET",
            f"{API}/files/{quote(file_id)}?alt=media&supportsAllDrives=true",
        )

    def stat_object(self, store_id: str, file_id: str) -> StoredFile:
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("file_id is required")
        meta = json.loads(self._request(
            "GET",
            f"{API}/files/{quote(file_id)}?fields=id,name,parents,size&supportsAllDrives=true",
        ))
        data = self.get_object(store_id, file_id)
        parents = meta.get("parents") or []
        parent = parents[0] if parents else ""
        return StoredFile(
            file_id=meta["id"],
            name=meta["name"],
            parent_id=parent,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def list_objects(self, store_id: str, query: str) -> list[StoredFile]:
        if not isinstance(store_id, str) or not store_id.strip():
            raise ValueError("store_id is required")
        escaped = (query or "").replace("\\", "\\\\").replace("'", "\\'")
        q = f"'{store_id}' in parents and trashed=false"
        if escaped:
            q += f" and name contains '{escaped}'"
        results: list[StoredFile] = []
        page_token: str | None = None
        while True:
            url = (f"{API}/files?q={quote(q)}"
                   "&fields=nextPageToken,files(id,name,parents,size)"
                   "&pageSize=1000&supportsAllDrives=true")
            if page_token:
                url += f"&pageToken={quote(page_token)}"
            page = json.loads(self._request("GET", url))
            for item in page.get("files") or []:
                parents = item.get("parents") or []
                results.append(StoredFile(
                    file_id=item["id"],
                    name=item["name"],
                    parent_id=parents[0] if parents else "",
                    size=int(item.get("size") or 0),
                    # Listing is discovery only. A raw hash needs stat()/get(),
                    # so it is deliberately left empty here.
                    sha256="",
                ))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return results
