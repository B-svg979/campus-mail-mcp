from __future__ import annotations

import json
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime

from .config import MailError, Settings
from .content import UTC, Snapshot, utc_text


def folded(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings.data_dir.chmod(0o700)
        self.path = settings.data_dir / "mail.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mail (
                    id TEXT PRIMARY KEY, subject TEXT NOT NULL, sender TEXT NOT NULL,
                    recipients TEXT NOT NULL, received_at TEXT, body_text TEXT NOT NULL,
                    message_id TEXT NOT NULL, folder TEXT NOT NULL, is_read INTEGER,
                    body_truncated INTEGER NOT NULL, search_text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS mail_received ON mail(received_at DESC,id);
                CREATE TABLE IF NOT EXISTS attachment (
                    id TEXT PRIMARY KEY, mail_id TEXT NOT NULL REFERENCES mail(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL,
                    content BLOB, unavailable_reason TEXT
                );
            """)
            row = db.execute("SELECT value FROM state WHERE id=1").fetchone()
            if row:
                if json.loads(row[0])["source_key"] != settings.source_key:
                    raise MailError(
                        "CONFIG_ERROR",
                        "此数据目录已绑定其他邮箱/模式。请为新配置选择另一个 CAMPUS_DATA_DIR。",
                    )
            else:
                self.write_state(
                    db,
                    {
                        "source_key": settings.source_key,
                        "revision": uuid.uuid4().hex,
                        "last_success_at": None,
                        "last_attempt_at": None,
                        "syncing": False,
                        "error": None,
                        "coverage_from": None,
                        "coverage_to": None,
                        "source_complete": False,
                        "warnings": [],
                        "message_count": 0,
                    },
                )
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def write_state(db, state):
        db.execute(
            "INSERT OR REPLACE INTO state(id,value) VALUES(1,?)",
            (json.dumps(state, ensure_ascii=False),),
        )

    def state(self):
        with self.connect() as db:
            return json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])

    def begin_sync(self):
        with self.connect() as db:
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            state.update(syncing=True, last_attempt_at=utc_text(datetime.now(UTC)))
            self.write_state(db, state)

    def fail_sync(self, error: MailError):
        with self.connect() as db:
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            state.update(syncing=False, error=error.as_dict())
            self.write_state(db, state)

    def replace(self, snapshot: Snapshot):
        # Readers see the old snapshot or the complete new transaction, never half a sync.
        with self.connect() as db:
            db.execute("DELETE FROM mail")
            for mail in snapshot.mails:
                db.execute(
                    "INSERT INTO mail VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        mail.id,
                        mail.subject,
                        mail.sender,
                        json.dumps(mail.recipients),
                        mail.received_at,
                        mail.body_text,
                        mail.message_id,
                        mail.folder,
                        mail.is_read,
                        mail.body_truncated,
                        folded(f"{mail.subject}\n{mail.sender}\n{mail.body_text}"),
                    ),
                )
                for item in mail.attachments:
                    db.execute(
                        "INSERT INTO attachment VALUES(?,?,?,?,?,?,?)",
                        (
                            item.id,
                            mail.id,
                            item.filename,
                            item.content_type,
                            item.size,
                            item.content,
                            item.unavailable_reason,
                        ),
                    )
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            state.update(
                syncing=False,
                error=None,
                last_success_at=utc_text(datetime.now(UTC)),
                revision=uuid.uuid4().hex,
                coverage_from=snapshot.coverage_from,
                coverage_to=snapshot.coverage_to,
                source_complete=snapshot.complete,
                warnings=snapshot.warnings,
                message_count=len(snapshot.mails),
            )
            self.write_state(db, state)

    @staticmethod
    def attachments(db, mail_id):
        return [
            dict(row)
            for row in db.execute(
                "SELECT id,filename,content_type,size,unavailable_reason FROM attachment WHERE mail_id=? ORDER BY id",
                (mail_id,),
            )
        ]

    def search(
        self,
        query: str,
        start: str | None,
        end: str | None,
        limit: int,
        offset: int,
        revision: str | None = None,
    ):
        clauses, params = [], []
        for term in folded(query).split():
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("search_text LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")
        if start:
            clauses.append("received_at>=?")
            params.append(start)
        if end:
            clauses.append("received_at<?")
            params.append(end)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            db.execute("BEGIN")
            state = json.loads(db.execute("SELECT value FROM state WHERE id=1").fetchone()[0])
            if revision and revision != state["revision"]:
                raise MailError("CURSOR_EXPIRED", "同步已更新邮件快照，请从第一页重新搜索。")
            count = db.execute("SELECT COUNT(*) FROM mail" + where, params).fetchone()[0]
            rows = db.execute(
                "SELECT id,subject,sender,received_at,substr(body_text,1,350) AS snippet,"
                "is_read,body_truncated FROM mail"
                + where
                + " ORDER BY received_at DESC,id DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["is_read"] = None if item["is_read"] is None else bool(item["is_read"])
                item["body_truncated"] = bool(item["body_truncated"])
                item["attachments"] = self.attachments(db, item["id"])
                items.append(item)
            return items, count, state

    def get_mail(self, mail_id):
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM mail WHERE id=?", (mail_id,)).fetchone()
            if row is None:
                raise MailError("NOT_FOUND", "邮件不在当前缓存中；请重新搜索获取邮件 ID。")
            mail = dict(row)
            mail.pop("search_text")
            mail["recipients"] = json.loads(mail["recipients"])
            mail["is_read"] = None if mail["is_read"] is None else bool(mail["is_read"])
            mail["body_truncated"] = bool(mail["body_truncated"])
            mail["attachments"] = self.attachments(db, mail_id)
            mail["_snapshot"] = json.loads(
                db.execute("SELECT value FROM state WHERE id=1").fetchone()[0]
            )
            return mail

    def get_attachment(self, mail_id, attachment_id):
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT * FROM attachment WHERE mail_id=? AND id=?", (mail_id, attachment_id)
            ).fetchone()
            if row is None:
                raise MailError("NOT_FOUND", "附件不在当前邮件缓存中。")
            result = dict(row)
            result["_snapshot"] = json.loads(
                db.execute("SELECT value FROM state WHERE id=1").fetchone()[0]
            )
            return result

    def export_metadata(self):
        """Local diagnostic without subjects, addresses, bodies or credentials."""
        state = self.state()
        return {key: value for key, value in state.items() if key not in {"source_key", "revision"}}
