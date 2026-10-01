"""MOCK applicant tracking system backed by local fixture files. Not a real integration."""
import json
from datetime import datetime
from pathlib import Path

from app.config import BACKEND_DIR
from app.ingestion.base import PermanentSourceError, SourceAdapter, SourceRecord, TransientSourceError

FIXTURE_DIR = BACKEND_DIR / "demo_data" / "mock_ats"


class MockATSAdapter(SourceAdapter):
    kind = "mock_ats"
    display_name = "Mock ATS (demo fixtures)"
    is_mock = True

    def __init__(self, fixture_dir: Path = FIXTURE_DIR):
        self.dir = fixture_dir

    def _raw(self) -> list[dict]:
        path = self.dir / "applications.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _to_record(self, r: dict) -> SourceRecord:
        return SourceRecord(
            record_id=r["external_application_id"],
            external_application_id=r["external_application_id"],
            external_candidate_id=r.get("external_candidate_id"),
            job_external_ref=r["job_external_ref"],
            submitted_at=datetime.fromisoformat(r["submitted_at"].replace("Z", "+00:00")).replace(tzinfo=None),
            resume_filename=r["resume_file"],
        )

    def list_records(self) -> list[SourceRecord]:
        return [self._to_record(r) for r in self._raw()]

    def get_record(self, record_id: str) -> SourceRecord:
        for r in self._raw():
            if r["external_application_id"] == record_id:
                return self._to_record(r)
        raise PermanentSourceError(f"Record {record_id} not found in mock ATS")

    def fetch_document(self, record: SourceRecord, attempt: int) -> tuple[str, bytes]:
        raw = next(r for r in self._raw() if r["external_application_id"] == record.record_id)
        if attempt <= int(raw.get("simulate_transient_failures", 0)):
            raise TransientSourceError("Mock ATS simulated timeout while downloading resume")
        path = (self.dir / "files" / record.resume_filename).resolve()
        if (self.dir / "files").resolve() not in path.parents or not path.exists():
            raise PermanentSourceError(f"Resume file for {record.record_id} is missing in the source system")
        return record.resume_filename, path.read_bytes()


ADAPTERS = {MockATSAdapter.kind: MockATSAdapter}


def get_adapter(kind: str) -> SourceAdapter:
    if kind not in ADAPTERS:
        raise PermanentSourceError(f"Unknown source adapter {kind}")
    return ADAPTERS[kind]()
