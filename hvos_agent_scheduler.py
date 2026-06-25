"""HVOS V10.2 - Agent Scheduler (Deterministic Priority Queue)"""
from __future__ import annotations
import sqlite3, json, uuid, threading, logging, os, heapq
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
SCHED_DB = rf"{HVOS_ROOT}\knowledge-graph\scheduler.db"


class AgentPriority(int, Enum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentTask:
    task_id: str
    agent_id: str
    agent_type: str
    action: str
    payload: dict
    priority: AgentPriority = AgentPriority.NORMAL
    status: AgentStatus = AgentStatus.PENDING
    scheduled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    causation_event_id: Optional[str] = None
    correlation_id: Optional[str] = None
    attempt: int = 1
    max_attempts: int = 3

    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = self.priority.value if isinstance(self.priority, AgentPriority) else int(self.priority)
        d["status"] = self.status.value if isinstance(self.status, AgentStatus) else self.status
        return d


class PriorityQueue:
    """
    Deterministic priority queue backed by heapq.
    Tie-break: earliest scheduled first (FIFO within same priority).
    """

    def __init__(self):
        self._heap: List[tuple] = []
        self._lock = threading.Lock()
        self._counter = 0

    def enqueue(self, task: AgentTask) -> AgentTask:
        with self._lock:
            self._counter += 1
            entry = (task.priority.value, self._counter, task)
            heapq.heappush(self._heap, entry)
        return task

    def dequeue(self) -> Optional[AgentTask]:
        with self._lock:
            if not self._heap:
                return None
            _, _, task = heapq.heappop(self._heap)
            return task

    def peek(self) -> Optional[AgentTask]:
        with self._lock:
            if not self._heap:
                return None
            _, _, task = self._heap[0]
            return task

    def size(self) -> int:
        with self._lock:
            return len(self._heap)

    def clear(self):
        with self._lock:
            self._heap.clear()
            self._counter = 0


SQL_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS tasks ("
    "task_id TEXT PRIMARY KEY,"
    "agent_id TEXT NOT NULL,"
    "agent_type TEXT NOT NULL,"
    "action TEXT NOT NULL,"
    "payload TEXT NOT NULL,"
    "priority INTEGER DEFAULT 3,"
    "status TEXT NOT NULL DEFAULT 'pending',"
    "scheduled_at TEXT NOT NULL,"
    "started_at TEXT,"
    "completed_at TEXT,"
    "result TEXT,"
    "error TEXT,"
    "causation_event_id TEXT,"
    "correlation_id TEXT,"
    "attempt INTEGER DEFAULT 1,"
    "max_attempts INTEGER DEFAULT 3);"
    "CREATE INDEX IF NOT EXISTS idx_agent ON tasks(agent_id);"
    "CREATE INDEX IF NOT EXISTS idx_status ON tasks(status);"
    "CREATE INDEX IF NOT EXISTS idx_priority_status ON tasks(priority, status);"
    "CREATE TABLE IF NOT EXISTS agents ("
    "agent_id TEXT PRIMARY KEY,"
    "agent_type TEXT NOT NULL,"
    "name TEXT NOT NULL,"
    "status TEXT NOT NULL DEFAULT 'idle',"
    "current_task_id TEXT,"
    "registered_at TEXT NOT NULL,"
    "last_heartbeat TEXT,"
    "metadata TEXT);"
    "CREATE INDEX IF NOT EXISTS idx_agent_type ON agents(agent_type);"
)


class SchedulerStore:
    def __init__(self, db_path: str = SCHED_DB):
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

    def save_task(self, task: AgentTask) -> AgentTask:
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO tasks (task_id,agent_id,agent_type,action,payload,priority,status,scheduled_at,started_at,completed_at,result,error,causation_event_id,correlation_id,attempt,max_attempts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task.task_id, task.agent_id, task.agent_type, task.action,
                    json.dumps(task.payload, ensure_ascii=False),
                    int(task.priority.value if isinstance(task.priority, AgentPriority) else task.priority),
                    task.status.value if isinstance(task.status, AgentStatus) else task.status,
                    task.scheduled_at, task.started_at, task.completed_at,
                    json.dumps(task.result, ensure_ascii=False) if task.result else None,
                    task.error,
                    task.causation_event_id, task.correlation_id,
                    task.attempt, task.max_attempts,
                ),
            )
            conn.commit()
            conn.close()
        return task

    def load_task(self, task_id: str) -> Optional[AgentTask]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_task(row)

    def _row_to_task(self, row) -> AgentTask:
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        result = json.loads(row["result"]) if row["result"] and isinstance(row["result"], str) else row["result"]
        return AgentTask(
            task_id=row["task_id"], agent_id=row["agent_id"], agent_type=row["agent_type"],
            action=row["action"], payload=payload,
            priority=AgentPriority(row["priority"]),
            status=AgentStatus(row["status"]),
            scheduled_at=row["scheduled_at"], started_at=row["started_at"],
            completed_at=row["completed_at"], result=result,
            error=row["error"],
            causation_event_id=row["causation_event_id"],
            correlation_id=row["correlation_id"],
            attempt=row["attempt"], max_attempts=row["max_attempts"],
        )

    def get_pending_tasks(self, limit: int = 100) -> List[AgentTask]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY priority ASC, scheduled_at ASC LIMIT ?",
            (AgentStatus.PENDING.value, limit),
        )
        rows = cur.fetchall()
        conn.close()
        return [self._row_to_task(r) for r in rows]

    def register_agent(self, agent_id: str, agent_type: str, name: str, metadata: Optional[dict] = None) -> dict:
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO agents (agent_id,agent_type,name,status,registered_at,metadata) VALUES (?,?,?,?,?,?)",
                (agent_id, agent_type, name, "idle", datetime.now(timezone.utc).isoformat(), json.dumps(metadata or {}, ensure_ascii=False)),
            )
            conn.commit()
            conn.close()
        return {"agent_id": agent_id, "type": agent_type, "name": name}

    def get_agents(self, agent_type: Optional[str] = None) -> List[dict]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if agent_type:
            cur.execute("SELECT * FROM agents WHERE agent_type=?", (agent_type,))
        else:
            cur.execute("SELECT * FROM agents")
        rows = cur.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "agent_id": r["agent_id"],
                "agent_type": r["agent_type"],
                "name": r["name"],
                "status": r["status"],
                "current_task_id": r["current_task_id"],
                "registered_at": r["registered_at"],
            })
        return result


class AgentScheduler:
    """
    Deterministic agent task scheduler.

    Design:
      - Priority queue (heapq) for in-memory ordering
      - Persistent task store (SQLite) for durability
      - Each agent has ONE task at a time
      - Deterministic: same inputs -> same execution order (priority + FIFO)
      - Causation linkage: each task tagged with causation_event_id

    Each AgentProcess:
      - state: idle / running / done
      - mailbox: queue of incoming tasks
      - lifecycle: registered -> working -> (success | fail) -> re-registered
    """

    def __init__(self, store: Optional[SchedulerStore] = None):
        self.store = store or SchedulerStore()
        self._queue = PriorityQueue()
        self._running: Dict[str, AgentTask] = {}
        self._lock = threading.RLock()

    def submit(
        self,
        agent_id: str,
        agent_type: str,
        action: str,
        payload: dict,
        priority: AgentPriority = AgentPriority.NORMAL,
        causation_event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> AgentTask:
        task = AgentTask(
            task_id=task_id or f"task_{uuid.uuid4().hex[:12]}",
            agent_id=agent_id,
            agent_type=agent_type,
            action=action,
            payload=payload,
            priority=priority,
            causation_event_id=causation_event_id,
            correlation_id=correlation_id,
        )
        self.store.save_task(task)
        self._queue.enqueue(task)
        return task

    def dispatch(self) -> Optional[AgentTask]:
        """
        Pop the highest-priority pending task and mark it RUNNING.
        Returns None if queue is empty.
        """
        with self._lock:
            task = self._queue.dequeue()
            if not task:
                return None
            task.status = AgentStatus.RUNNING
            task.started_at = datetime.now(timezone.utc).isoformat()
            self.store.save_task(task)
            self._running[task.task_id] = task
            return task

    def complete(self, task_id: str, result: dict) -> AgentTask:
        with self._lock:
            task = self._running.pop(task_id, None)
            if task:
                task.status = AgentStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.result = result
                self.store.save_task(task)
            else:
                task = self.store.load_task(task_id)
                if task:
                    task.status = AgentStatus.COMPLETED
                    task.completed_at = datetime.now(timezone.utc).isoformat()
                    task.result = result
                    self.store.save_task(task)
            return task

    def fail(self, task_id: str, error: str) -> AgentTask:
        with self._lock:
            task = self._running.pop(task_id, None)
            if task:
                task.status = AgentStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.error = error
                if task.attempt < task.max_attempts:
                    task.attempt += 1
                    task.status = AgentStatus.PENDING
                    task.started_at = None
                    task.error = None
                    self.store.save_task(task)
                    self._queue.enqueue(task)
                else:
                    self.store.save_task(task)
            else:
                task = self.store.load_task(task_id)
                if task:
                    task.status = AgentStatus.FAILED
                    task.completed_at = datetime.now(timezone.utc).isoformat()
                    task.error = error
                    self.store.save_task(task)
            return task

    def cancel(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            task = self.store.load_task(task_id)
            if task and task.status == AgentStatus.PENDING:
                task.status = AgentStatus.CANCELLED
                self.store.save_task(task)
                return task
            return None

    def get_queue_size(self) -> int:
        return self._queue.size()

    def get_running(self) -> List[AgentTask]:
        with self._lock:
            return list(self._running.values())

    def peek_next(self) -> Optional[AgentTask]:
        return self._queue.peek()

    def register_agent(self, agent_type: str, name: str, metadata: Optional[dict] = None) -> dict:
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        return self.store.register_agent(agent_id, agent_type, name, metadata)

    def get_agents(self, agent_type: Optional[str] = None) -> List[dict]:
        return self.store.get_agents(agent_type)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS Agent Scheduler CLI")
    parser.add_argument("--action", choices=["submit", "dispatch", "complete", "fail", "queue", "agents"], required=True)
    parser.add_argument("--agent_id", default="agent_test")
    parser.add_argument("--agent_type", default="category_specialist")
    parser.add_argument("--action_name", default="analyze")
    parser.add_argument("--task_id")
    parser.add_argument("--priority", type=int, default=3)
    args = parser.parse_args()
    sched = AgentScheduler()
    if args.action == "submit":
        t = sched.submit(args.agent_id, args.agent_type, args.action_name, {"test": 1}, priority=AgentPriority(args.priority))
        print(f"Submitted: {t.task_id} priority={t.priority.value}")
    elif args.action == "dispatch":
        t = sched.dispatch()
        if t:
            print(f"Dispatched: {t.task_id} agent={t.agent_id} action={t.action}")
        else:
            print("Queue empty")
    elif args.action == "complete":
        t = sched.complete(args.task_id, {"result": "ok"})
        print(f"Completed: {t.task_id}")
    elif args.action == "fail":
        t = sched.fail(args.task_id, "test error")
        print(f"Failed: {t.task_id} attempt={t.attempt}/{t.max_attempts}")
    elif args.action == "queue":
        print(f"Queue size: {sched.get_queue_size()}")
    elif args.action == "agents":
        for a in sched.get_agents():
            print(f"  {a['agent_id']} {a['agent_type']} {a['status']}")
