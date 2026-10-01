"""Source adapter interface for resume collection.

Implemented in milestone 1: manual upload (routers/applications.py) and MockATSAdapter.
Planned (not implemented; need enterprise decisions): CSV import, recruitment mailbox
(e.g. Microsoft Graph / Gmail API with an authorized service account), real ATS adapters
(e.g. Workday, Greenhouse, Lever, SuccessFactors) via their supported APIs or webhooks.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class TransientSourceError(Exception):
    """Temporary failure (timeout, rate limit). The task queue retries with backoff."""


class PermanentSourceError(Exception):
    """Record can never be ingested (missing file, unmapped job)."""


@dataclass
class SourceRecord:
    record_id: str
    external_application_id: str
    external_candidate_id: str | None
    job_external_ref: str
    submitted_at: datetime
    resume_filename: str


class SourceAdapter(ABC):
    kind: str
    display_name: str
    is_mock: bool = False

    @abstractmethod
    def list_records(self) -> list[SourceRecord]: ...

    @abstractmethod
    def get_record(self, record_id: str) -> SourceRecord: ...

    @abstractmethod
    def fetch_document(self, record: SourceRecord, attempt: int) -> tuple[str, bytes]: ...
