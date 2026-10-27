"""Database-backed task queue with retries and backoff.

Workers claim tasks atomically (UPDATE ... WHERE status='queued'), so several worker
processes can run safely. Every task carries tenant_id and handlers load rows filtered by it.
"""
import logging
import threading
from datetime import timedelta
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import new_session, utcnow
from app.models import Task

log = logging.getLogger("talentmatch.tasks")


class PermanentTaskError(Exception):
    """Do not retry (e.g. missing record, invalid configuration)."""


class TransientTaskError(Exception):
    """Retry with backoff (e.g. provider timeout)."""


Handler = Callable[[Session, Task], None]
FailureHook = Callable[[Session, Task, str], None]
_HANDLERS: dict[str, Handler] = {}
_FAILURE_HOOKS: dict[str, FailureHook] = {}


def register(task_type: str, on_failure: FailureHook | None = None):
    def deco(fn: Handler) -> Handler:
        _HANDLERS[task_type] = fn
        if on_failure:
            _FAILURE_HOOKS[task_type] = on_failure
        return fn

    return deco


def enqueue(db: Session, tenant_id: str, task_type: str, payload: dict, max_attempts: int = 3) -> Task:
    task = Task(tenant_id=tenant_id, type=task_type, payload=payload, max_attempts=max_attempts)
    db.add(task)
    return task


def _claim_next(db: Session, respect_schedule: bool) -> Task | None:
    for _ in range(5):
        q = select(Task.id).where(Task.status == "queued")
        if respect_schedule:
            q = q.where(Task.run_after <= utcnow())
        tid = db.scalar(q.order_by(Task.created_at).limit(1))
        if tid is None:
            return None
        res = db.execute(
            update(Task)
            .where(Task.id == tid, Task.status == "queued")
            .values(status="running", attempts=Task.attempts + 1, updated_at=utcnow())
        )
        db.commit()
        if res.rowcount == 1:
            return db.get(Task, tid)
    return None


def _safe_error(e: Exception) -> str:
    # Our own exceptions carry operator-safe messages; never include document text.
    return f"{type(e).__name__}: {str(e)[:300]}"


def run_one(respect_schedule: bool = True) -> bool:
    _ensure_handlers_loaded()
    db = new_session()
    try:
        task = _claim_next(db, respect_schedule)
        if task is None:
            return False
        handler = _HANDLERS.get(task.type)
        try:
            if handler is None:
                raise PermanentTaskError(f"No handler for task type {task.type}")
            handler(db, task)
            task.status = "done"
            task.last_error = None
            db.commit()
        except Exception as e:  # noqa: BLE001 - every failure is recorded on the task
            db.rollback()
            task = db.get(Task, task.id)
            task.last_error = _safe_error(e)
            permanent = isinstance(e, PermanentTaskError)
            if not permanent and task.attempts < task.max_attempts:
                delay = get_settings().task_retry_base_seconds * (2 ** (task.attempts - 1))
                task.status = "queued"
                task.run_after = utcnow() + timedelta(seconds=delay)
                log.warning("task %s (%s) attempt %s failed: %s; retrying", task.id, task.type, task.attempts, type(e).__name__)
            else:
                task.status = "failed"
                log.error("task %s (%s) failed permanently: %s", task.id, task.type, type(e).__name__)
                hook = _FAILURE_HOOKS.get(task.type)
                if hook:
                    hook(db, task, task.last_error)
            db.commit()
        return True
    finally:
        db.close()


def drain(max_tasks: int = 500, respect_schedule: bool = True) -> int:
    n = 0
    while n < max_tasks and run_one(respect_schedule):
        n += 1
    return n


def _ensure_handlers_loaded() -> None:
    # Importing registers handlers via @register.
    from app.services import email_service, ingestion_tasks, pipeline  # noqa: F401


class WorkerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="talentmatch-worker")
        self._stop_event = threading.Event()

    def run(self) -> None:
        poll = get_settings().worker_poll_seconds
        while not self._stop_event.is_set():
            try:
                if drain(max_tasks=25) == 0:
                    self._stop_event.wait(poll)
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("worker loop error")
                self._stop_event.wait(poll)

    def stop(self) -> None:
        self._stop_event.set()
