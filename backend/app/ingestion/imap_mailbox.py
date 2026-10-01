"""Read-only IMAP client for a recruitment mailbox.

Works with any IMAP server (Google Workspace, Titan, Microsoft 365 with IMAP enabled). The
mailbox is opened with EXAMINE (read-only) and messages are fetched with BODY.PEEK[], so nothing
is marked read, moved or deleted.

STATUS: implemented and unit-tested against a fake IMAP server only. It has NOT been tested
against a real mailbox. Google Workspace generally requires OAuth 2.0 (XOAUTH2) or an app
password for IMAP; OAuth is not implemented yet.
"""
import imaplib
import re
from dataclasses import dataclass
from datetime import date

from app.ingestion.base import PermanentSourceError, TransientSourceError


@dataclass
class ImapSettings:
    host: str
    port: int
    username: str
    folder: str = "INBOX"
    since_days: int = 30
    max_messages: int = 200


def _connect(s: ImapSettings, password: str, timeout: int = 30) -> imaplib.IMAP4_SSL:
    try:
        conn = imaplib.IMAP4_SSL(s.host, s.port, timeout=timeout)
    except OSError as e:
        raise TransientSourceError(f"Could not connect to {s.host}:{s.port} ({type(e).__name__})")
    try:
        conn.login(s.username, password)
    except imaplib.IMAP4.error:
        raise PermanentSourceError("IMAP login was rejected. Check the username, password/app password and IMAP access.")
    return conn


def fetch_messages(s: ImapSettings, password: str, since: date) -> tuple[str, list[tuple[str, bytes]]]:
    """Return (uidvalidity, [(record_key, raw_message)]) for messages SINCE `since`, newest last."""
    conn = _connect(s, password)
    try:
        typ, _ = conn.select(f'"{s.folder}"', readonly=True)
        if typ != "OK":
            raise PermanentSourceError(f"Mailbox folder '{s.folder}' could not be opened.")
        uidvalidity = "0"
        typ, data = conn.status(f'"{s.folder}"', "(UIDVALIDITY)")
        if typ == "OK" and data and data[0]:
            m = re.search(rb"UIDVALIDITY (\d+)", data[0])
            if m:
                uidvalidity = m.group(1).decode()
        typ, data = conn.uid("SEARCH", None, f'(SINCE "{since.strftime("%d-%b-%Y")}")')
        if typ != "OK":
            raise TransientSourceError("IMAP search failed")
        uids = (data[0] or b"").split()[-s.max_messages:]
        out: list[tuple[str, bytes]] = []
        for uid in uids:
            typ, fetched = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = next((part[1] for part in fetched if isinstance(part, tuple) and len(part) > 1), None)
            if raw:
                out.append((f"{uidvalidity}:{uid.decode()}", raw))
        return uidvalidity, out
    except (imaplib.IMAP4.abort, OSError) as e:
        raise TransientSourceError(f"IMAP connection dropped ({type(e).__name__})")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
