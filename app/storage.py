"""SQLite metadata plus normalized image files; no browser-local persistence."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        self.uploads = directory / 'uploads'
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.database = directory / 'history.sqlite3'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS scans (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
                crop TEXT NOT NULL, notes TEXT NOT NULL, report TEXT,
                predictions TEXT NOT NULL DEFAULT '[]', analysis_method TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '', error TEXT
            )''')
            db.execute("UPDATE scans SET status = 'error', error = 'The server stopped during analysis. You can retry this photo.' WHERE status = 'processing'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def serialize(row):
        if row is None:
            return None
        result = dict(row)
        result['report'] = json.loads(result['report']) if result['report'] else None
        result['predictions'] = json.loads(result['predictions'])
        result['image_url'] = f"/api/scans/{result['id']}/image"
        result['thumbnail_url'] = f"/api/scans/{result['id']}/thumbnail"
        return result

    def create(self, scan_id: str, crop: str, notes: str):
        with self.connect() as db:
            db.execute('INSERT INTO scans (id,created_at,status,crop,notes) VALUES (?,?,?,?,?)',
                       (scan_id, datetime.now(timezone.utc).isoformat(), 'processing', crop, notes))
        return self.get(scan_id)

    def get(self, scan_id: str):
        with self.connect() as db:
            return self.serialize(db.execute('SELECT * FROM scans WHERE id = ?', (scan_id,)).fetchone())

    def list(self, limit=100, offset=0):
        with self.connect() as db:
            items = db.execute('SELECT * FROM scans ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            total = db.execute('SELECT COUNT(*) FROM scans').fetchone()[0]
        return {'items': [self.serialize(row) for row in items], 'total': total}

    def update(self, scan_id: str, **values):
        allowed = {'status', 'report', 'predictions', 'analysis_method', 'model', 'error'}
        if not values or not set(values) <= allowed:
            raise ValueError('Invalid scan update')
        for key in ('report', 'predictions'):
            if key in values and values[key] is not None:
                values[key] = json.dumps(values[key])
        with self.connect() as db:
            db.execute(f"UPDATE scans SET {', '.join(key + ' = ?' for key in values)} WHERE id = ?",
                       (*values.values(), scan_id))
        return self.get(scan_id)

    def delete(self, scan_id: str):
        with self.connect() as db:
            db.execute('DELETE FROM scans WHERE id = ?', (scan_id,))
        for suffix in ('.jpg', '.thumb.jpg'):
            (self.uploads / (scan_id + suffix)).unlink(missing_ok=True)
