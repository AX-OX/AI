"""Local, independent alert receiver: it survives model server outages."""
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field


class Alert(BaseModel):
    status: Literal['firing', 'resolved']
    labels: dict[str, str] = Field(max_length=30)
    annotations: dict[str, str] = Field(default_factory=dict, max_length=30)
    startsAt: str = Field(max_length=100)
    endsAt: str = Field(default='', max_length=100)


class Notification(BaseModel):
    status: Literal['firing', 'resolved']
    alerts: list[Alert] = Field(max_length=50)


def create_app(database: Path | None = None):
    path = database or Path(os.getenv('ALERT_DATABASE', '/data/alerts.sqlite'))

    @asynccontextmanager
    async def lifespan(app):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, received_at TEXT, body TEXT)')
        yield

    app = FastAPI(title='Local Alert Inbox', lifespan=lifespan)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/webhook', status_code=202)
    def receive(body: Notification):
        with sqlite3.connect(path) as db:
            db.execute('INSERT INTO notifications (received_at, body) VALUES (?, ?)',
                       (datetime.now(timezone.utc).isoformat(), body.model_dump_json()))
            db.execute('DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY id DESC LIMIT 200)')
        return {'accepted': True, 'alerts': len(body.alerts)}

    @app.get('/alerts')
    def inbox():
        with sqlite3.connect(path) as db:
            rows = db.execute('SELECT id, received_at, body FROM notifications ORDER BY id DESC LIMIT 100').fetchall()
        return [{'id': row[0], 'received_at': row[1], **json.loads(row[2])} for row in rows]

    return app


app = create_app()
