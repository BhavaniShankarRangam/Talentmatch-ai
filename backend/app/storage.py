"""Private document storage. Local filesystem for milestone 1 (outside any web root).

Keys are always "<tenant_id>/<random>.<ext>" and every read checks the tenant prefix, so a
document key from one tenant can never be resolved by another. Production: swap for an object
store (S3/Azure Blob) with server-side encryption behind the same interface.
"""
import uuid
from pathlib import Path

from app.config import get_settings


class StorageAccessError(Exception):
    pass


class LocalPrivateStorage:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: str, key: str) -> Path:
        if not key.startswith(f"{tenant_id}/"):
            raise StorageAccessError("Document does not belong to this tenant")
        tenant_root = (self.base / tenant_id).resolve()
        path = (self.base / key).resolve()
        # Check after resolving so "tenantA/../tenantB/x" cannot escape the tenant's directory.
        if tenant_root not in path.parents or self.base not in tenant_root.parents:
            raise StorageAccessError("Invalid document key")
        return path

    def save(self, tenant_id: str, data: bytes, ext: str) -> str:
        key = f"{tenant_id}/{uuid.uuid4().hex}{ext}"
        path = self._path(tenant_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read(self, tenant_id: str, key: str) -> bytes:
        return self._path(tenant_id, key).read_bytes()

    def delete(self, tenant_id: str, key: str) -> None:
        path = self._path(tenant_id, key)
        if path.exists():
            path.unlink()


def get_storage() -> LocalPrivateStorage:
    return LocalPrivateStorage(get_settings().storage_dir)
