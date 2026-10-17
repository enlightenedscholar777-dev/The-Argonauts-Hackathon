"""Durable audit and versioned JSON state. No pickle or in-memory dedup history."""

import asyncio
import json
import os
from pathlib import Path

import aiosqlite


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Storage:
    def __init__(self, path):
        self.path = path
        self.db = None
        self.lock = asyncio.Lock()
        self.owner_file = None

    async def open(self):
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self.owner_file = open(self.path + ".owner", "a+b")
            self.owner_file.seek(0)
            if os.fstat(self.owner_file.fileno()).st_size == 0:
                self.owner_file.write(b"1")
                self.owner_file.flush()
            self.owner_file.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.owner_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.owner_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.owner_file.close()
                self.owner_file = None
                raise RuntimeError("Database already owned: use exactly one server worker") from None
        self.db = await aiosqlite.connect(self.path)
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA synchronous=FULL;
            PRAGMA busy_timeout=3000;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO metadata VALUES('schema_version','1.0');
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, state TEXT NOT NULL, stopped INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS events(session_id TEXT REFERENCES sessions(id), id TEXT, hash TEXT NOT NULL,
                source TEXT, boot TEXT, sequence INTEGER, body TEXT, response TEXT, received_at TEXT,
                PRIMARY KEY(session_id,id), UNIQUE(session_id,source,boot,sequence));
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, hash TEXT NOT NULL, response TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history(cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT REFERENCES sessions(id), kind TEXT, record TEXT);
            CREATE INDEX IF NOT EXISTS history_session ON history(session_id,cursor);
            CREATE TABLE IF NOT EXISTS tracks(session_id TEXT REFERENCES sessions(id), id TEXT, state TEXT,
                PRIMARY KEY(session_id,id));
            CREATE TABLE IF NOT EXISTS identity_bindings(session_id TEXT REFERENCES sessions(id), track_id TEXT, record TEXT,
                PRIMARY KEY(session_id,track_id));
            CREATE TABLE IF NOT EXISTS incidents(session_id TEXT REFERENCES sessions(id), id TEXT, record TEXT,
                PRIMARY KEY(session_id,id));
            CREATE TABLE IF NOT EXISTS ai_jobs(id TEXT PRIMARY KEY, session_id TEXT, state TEXT, record TEXT);
        """)
        await self.db.execute("UPDATE ai_jobs SET state='CANCELED_RESTART' WHERE state='PENDING'")
        await self.db.commit()

    async def one(self, sql, args=()):
        async with self.lock:
            async with self.db.execute(sql, args) as cursor:
                return await cursor.fetchone()

    async def recover(self):
        row = await self.one("SELECT state FROM sessions WHERE stopped=0 ORDER BY rowid DESC LIMIT 1")
        return json.loads(row[0]) if row else None

    async def session(self, session_id):
        row = await self.one("SELECT state FROM sessions WHERE id=?", (session_id,))
        return json.loads(row[0]) if row else None

    async def duplicate(self, kind, session_id, identifier):
        if kind == "event":
            row = await self.one(
                "SELECT hash,response FROM events WHERE session_id=? AND id=?", (session_id, identifier)
            )
        else:
            row = await self.one("SELECT hash,response FROM commands WHERE id=?", (identifier,))
        return (row[0], json.loads(row[1])) if row else None

    async def commit(self, state, kind, response, command=None, event=None, changed=(), ai_job=None):
        async with self.lock:
            await self._commit(state, kind, response, command, event, changed, ai_job)

    async def _commit(self, state, kind, response, command=None, event=None, changed=(), ai_job=None):
        try:
            await self.db.execute("BEGIN IMMEDIATE")
            await self.db.execute(
                "INSERT INTO sessions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,stopped=excluded.stopped",
                (state["session_id"], encode(state), int(state["stopped"])),
            )
            if command:
                await self.db.execute(
                    "INSERT INTO commands VALUES(?,?,?)", (command[0], command[1], encode(response))
                )
            if event:
                body, digest, received = event
                await self.db.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        state["session_id"],
                        body["event_id"],
                        digest,
                        body["source_id"],
                        body["source_boot_id"],
                        body["source_sequence"],
                        encode(body),
                        encode(response),
                        received,
                    ),
                )
            for track_id in changed:
                track = state["tracks"][track_id]
                await self.db.execute(
                    "INSERT OR REPLACE INTO tracks VALUES(?,?,?)",
                    (state["session_id"], track_id, encode(track)),
                )
                if track.get("binding"):
                    await self.db.execute(
                        "INSERT OR REPLACE INTO identity_bindings VALUES(?,?,?)",
                        (state["session_id"], track_id, encode(track["binding"])),
                    )
                if track.get("incident"):
                    await self.db.execute(
                        "INSERT OR REPLACE INTO incidents VALUES(?,?,?)",
                        (state["session_id"], track["incident"]["incident_id"], encode(track["incident"])),
                    )
                await self.db.execute(
                    "INSERT INTO history(session_id,kind,record) VALUES(?,?,?)",
                    (state["session_id"], "assessment", encode(track["assessment"])),
                )
            await self.db.execute(
                "INSERT INTO history(session_id,kind,record) VALUES(?,?,?)",
                (
                    state["session_id"],
                    kind,
                    encode(
                        {
                            "schema_version": "1.0",
                            "receipt": response,
                            "event": event[0],
                            "received_at": event[2],
                        }
                        if event
                        else response
                    ),
                ),
            )
            if ai_job:
                await self.db.execute(
                    "INSERT OR REPLACE INTO ai_jobs VALUES(?,?,?,?)",
                    (ai_job["job_id"], state["session_id"], ai_job["state"], encode(ai_job)),
                )
            if state["stopped"]:
                await self.db.execute(
                    "UPDATE ai_jobs SET state='CANCELED_STOP' WHERE session_id=? AND state='PENDING'",
                    (state["session_id"],),
                )
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            raise

    async def history(self, session_id, after, limit):
        async with self.lock:
            async with self.db.execute(
                "SELECT cursor,kind,record FROM history WHERE session_id=? AND cursor>? ORDER BY cursor LIMIT ?",
                (session_id, after, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [{"cursor": row[0], "kind": row[1], "record": json.loads(row[2])} for row in rows]

    async def close(self):
        if self.db:
            await self.db.close()
        if self.owner_file:
            self.owner_file.close()
