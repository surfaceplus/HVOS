"""HVOS V10.2 - Event Backbone Engine"""
from __future__ import annotations
import sqlite3, json, uuid, threading, time, logging, os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable, Dict, List, Any, Protocol
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
EVENTS_DB = rf"{HVOS_ROOT}\reality\events.db"


class EventStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    COMPENSATED = "compensated"


@dataclass
class EventEnvelope:
    event_type: str
    payload: dict
    partition_key: str = "default"
    source: str = "unknown"
    causation_id: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    sequence: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: EventStatus = EventStatus.PENDING
    schema_version: str = "1.0"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, EventStatus) else self.status
        return d

    @classmethod
    def from_row(cls, row) -> "EventEnvelope":
        pl = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        md = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else {}
        return cls(
            event_id=row["event_id"], sequence=row["sequence"], timestamp=row["timestamp"],
            event_type=row["event_type"], payload=pl,
            causation_id=row["causation_id"], correlation_id=row["correlation_id"],
            partition_key=row["partition_key"], source=row["source"], metadata=md,
            status=EventStatus(row["status"]),
            schema_version='1.0',
        )


@dataclass
class ProjectionState:
    partition_key: str
    projection_name: str
    version: int
    state: dict
    last_sequence: int
    computed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EventHandler(Protocol):
    def handle(self, event: EventEnvelope) -> None: ...


class NullHandler:
    def handle(self, event: EventEnvelope): pass


class EventBus:
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._global_handlers: List[EventHandler] = []
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, handler: EventHandler):
        with self._lock:
            self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler):
        with self._lock:
            self._global_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler):
        with self._lock:
            if handler in self._handlers.get(event_type, []):
                self._handlers[event_type].remove(handler)

    def publish(self, event: EventEnvelope):
        with self._lock:
            for h in list(self._global_handlers):
                try:
                    h.handle(event)
                except Exception as e:
                    logger.error(f"[EventBus] global error: {e}")
            for h in list(self._handlers.get(event.event_type, [])):
                try:
                    h.handle(event)
                except Exception as e:
                    logger.error(f"[EventBus] handler error for {event.event_type}: {e}")


_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


SQL_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS event_log ("
    "event_id TEXT PRIMARY KEY,"
    "sequence INTEGER NOT NULL UNIQUE,"
    "timestamp TEXT NOT NULL,"
    "event_type TEXT NOT NULL,"
    "payload TEXT NOT NULL,"
    "causation_id TEXT,"
    "correlation_id TEXT,"
    "partition_key TEXT NOT NULL,"
    "source TEXT NOT NULL,"
    "metadata TEXT NOT NULL DEFAULT '{}',"
    "status TEXT NOT NULL DEFAULT 'pending',"
    "schema_version TEXT NOT NULL DEFAULT '1.0',"
    "applied_at TEXT);"
    "CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type);"
    "CREATE INDEX IF NOT EXISTS idx_partition ON event_log(partition_key);"
    "CREATE INDEX IF NOT EXISTS idx_sequence ON event_log(sequence);"
    "CREATE INDEX IF NOT EXISTS idx_causation ON event_log(causation_id);"
    "CREATE INDEX IF NOT EXISTS idx_correlation ON event_log(correlation_id);"
    "CREATE TABLE IF NOT EXISTS projections ("
    "partition_key TEXT NOT NULL,"
    "projection_name TEXT NOT NULL,"
    "version INTEGER NOT NULL DEFAULT 1,"
    "state TEXT NOT NULL,"
    "last_sequence INTEGER NOT NULL,"
    "computed_at TEXT NOT NULL,"
    "PRIMARY KEY (partition_key, projection_name));"
)


class EventStore:
    def __init__(self, db_path: str = EVENTS_DB):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            for stmt in SQL_SCHEMA.split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            conn.commit()
            conn.close()

    def append(self, envelope: EventEnvelope) -> EventEnvelope:
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            for attempt in range(3):
                cur.execute("SELECT COALESCE(MAX(sequence), 0) FROM event_log")
                last_seq = cur.fetchone()[0]
                new_seq = last_seq + 1
                envelope.sequence = new_seq
                try:
                    cur.execute(
                        "INSERT INTO event_log (event_id,sequence,timestamp,event_type,payload,causation_id,correlation_id,partition_key,source,metadata,status,schema_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            envelope.event_id, envelope.sequence, envelope.timestamp, envelope.event_type,
                            json.dumps(envelope.payload, ensure_ascii=False),
                            envelope.causation_id, envelope.correlation_id, envelope.partition_key, envelope.source,
                            json.dumps(envelope.metadata, ensure_ascii=False),
                            envelope.status.value if isinstance(envelope.status, EventStatus) else envelope.status,
                            envelope.schema_version,
                        ),
                    )
                    conn.commit()
                    break
                except sqlite3.IntegrityError:
                    conn.rollback()
                    time.sleep(0.01 * (attempt + 1))
                    continue
            conn.close()
            return envelope

    def append_many(self, envelopes: List[EventEnvelope]) -> List[EventEnvelope]:
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(sequence), 0) FROM event_log")
            next_seq = cur.fetchone()[0] + 1
            for env in envelopes:
                env.sequence = next_seq
                next_seq += 1
                cur.execute(
                    "INSERT INTO event_log (event_id,sequence,timestamp,event_type,payload,causation_id,correlation_id,partition_key,source,metadata,status,schema_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        env.event_id, env.sequence, env.timestamp, env.event_type,
                        json.dumps(env.payload, ensure_ascii=False),
                        env.causation_id, env.correlation_id, env.partition_key, env.source,
                        json.dumps(env.metadata, ensure_ascii=False),
                        env.status.value if isinstance(env.status, EventStatus) else env.status,
                        env.schema_version,
                    ),
                )
            conn.commit()
            conn.close()
            return envelopes

    def get_by_partition(self, partition_key: str, from_seq: int = 0, limit: int = 1000) -> List[EventEnvelope]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM event_log WHERE partition_key=? AND sequence>? ORDER BY sequence ASC LIMIT ?",
            (partition_key, from_seq, limit),
        )
        rows = cur.fetchall()
        conn.close()
        return [EventEnvelope.from_row(r) for r in rows]

    def get_from_sequence(self, from_seq: int = 0, limit: int = 1000) -> List[EventEnvelope]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM event_log WHERE sequence>? ORDER BY sequence ASC LIMIT ?",
            (from_seq, limit),
        )
        rows = cur.fetchall()
        conn.close()
        return [EventEnvelope.from_row(r) for r in rows]

    def get_by_correlation(self, correlation_id: str) -> List[EventEnvelope]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM event_log WHERE correlation_id=? ORDER BY sequence ASC",
            (correlation_id,),
        )
        rows = cur.fetchall()
        conn.close()
        return [EventEnvelope.from_row(r) for r in rows]

    def replay(
        self,
        from_seq: int = 0,
        event_types: Optional[List[str]] = None,
        partition_key: Optional[str] = None,
        handler: Optional[Callable[[EventEnvelope], None]] = None,
    ) -> List[EventEnvelope]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        sql = "SELECT * FROM event_log WHERE sequence>?"
        params: List[Any] = [from_seq]
        if event_types:
            placeholders = ",".join(["?"] * len(event_types))
            sql += f" AND event_type IN ({placeholders})"
            params.extend(event_types)
        if partition_key:
            sql += " AND partition_key=?"
            params.append(partition_key)
        sql += " ORDER BY sequence ASC"
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        events = [EventEnvelope.from_row(r) for r in rows]
        if handler:
            for ev in events:
                handler(ev)
        return events

    def current_sequence(self) -> int:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(sequence), 0) FROM event_log")
        seq = cur.fetchone()[0]
        conn.close()
        return seq if seq else 0

    def get_stats(self) -> dict:
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM event_log")
        total = cur.fetchone()[0]
        cur.execute("SELECT MAX(sequence) FROM event_log")
        max_seq = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(DISTINCT event_type) FROM event_log")
        n_types = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT partition_key) FROM event_log")
        n_parts = cur.fetchone()[0]
        conn.close()
        return {
            "total_events": total,
            "max_sequence": max_seq,
            "event_types": n_types,
            "partitions": n_parts,
        }

    def save_projection(self, proj: ProjectionState):
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO projections (partition_key,projection_name,version,state,last_sequence,computed_at) VALUES (?,?,?,?,?,?)",
                (
                    proj.partition_key,
                    proj.projection_name,
                    proj.version,
                    json.dumps(proj.state, ensure_ascii=False),
                    proj.last_sequence,
                    proj.computed_at,
                ),
            )
            conn.commit()
            conn.close()

    def load_projection(self, partition_key: str, projection_name: str) -> Optional[ProjectionState]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM projections WHERE partition_key=? AND projection_name=?",
            (partition_key, projection_name),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            state = json.loads(row["state"]) if isinstance(row["state"], str) else row["state"]
            return ProjectionState(
                partition_key=row["partition_key"],
                projection_name=row["projection_name"],
                version=row["version"],
                state=state,
                last_sequence=row["last_sequence"],
                computed_at=row["computed_at"],
            )
        return None


class HvosEventSystem:
    def __init__(self, db_path: str = EVENTS_DB):
        self.store = EventStore(db_path)
        self.bus = get_event_bus()

    def emit(
        self,
        event_type: str,
        payload: dict,
        partition_key: str = "default",
        causation_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        source: str = "HvosEventSystem",
        metadata: Optional[dict] = None,
    ) -> EventEnvelope:
        envelope = EventEnvelope(
            event_type=event_type,
            payload=payload,
            partition_key=partition_key,
            causation_id=causation_id,
            correlation_id=correlation_id,
            source=source,
            metadata=metadata or {},
        )
        saved = self.store.append(envelope)
        self.bus.publish(saved)
        return saved

    def emit_many(self, envelopes: List[EventEnvelope]) -> List[EventEnvelope]:
        saved = self.store.append_many(envelopes)
        for ev in saved:
            self.bus.publish(ev)
        return saved

    def subscribe(self, event_type: str, handler: EventHandler):
        self.bus.subscribe(event_type, handler)

    def subscribe_all(self, handler: EventHandler):
        self.bus.subscribe_all(handler)

    def get_events(self, partition_key: str, from_seq: int = 0) -> List[EventEnvelope]:
        return self.store.get_by_partition(partition_key, from_seq)

    def replay_from(
        self,
        from_seq: int = 0,
        event_types: Optional[List[str]] = None,
        partition_key: Optional[str] = None,
        handler: Optional[Callable[[EventEnvelope], None]] = None,
    ) -> List[EventEnvelope]:
        return self.store.replay(
            from_seq=from_seq,
            event_types=event_types,
            partition_key=partition_key,
            handler=handler,
        )

    def current_sequence(self) -> int:
        return self.store.current_sequence()

    def stats(self) -> dict:
        return self.store.get_stats()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS Event Backbone CLI")
    parser.add_argument("--action", choices=["emit", "replay", "stats", "peek"], required=True)
    parser.add_argument("--event_type", default="CLI_EVENT")
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--partition", default="default")
    parser.add_argument("--correlation", default=None)
    parser.add_argument("--from_seq", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--source", default="CLI")
    args = parser.parse_args()
    eb = HvosEventSystem()

    if args.action == "emit":
        payload = json.loads(args.payload)
        ev = eb.emit(
            args.event_type,
            payload,
            partition_key=args.partition,
            correlation_id=args.correlation,
            source=args.source,
        )
        print(f"Emitted: {ev.event_id} seq={ev.sequence} type={ev.event_type} part={ev.partition_key}")

    elif args.action == "replay":
        events = eb.replay_from(from_seq=args.from_seq)
        print(f"Events from seq {args.from_seq}: {len(events)} total")
        for ev in events:
            print(f"  [{ev.sequence}] {ev.event_type} part={ev.partition_key}")

    elif args.action == "stats":
        s = eb.stats()
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif args.action == "peek":
        evs = eb.store.get_from_sequence(args.from_seq, limit=args.limit)
        print(f"Events from seq {args.from_seq}:")
        for ev in evs:
            print(f"  [{ev.sequence}] {ev.event_type} part={ev.partition_key} id={ev.event_id}")
