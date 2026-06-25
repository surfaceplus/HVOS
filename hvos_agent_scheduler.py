"""HVOS V10.2 - Agent Scheduler (Deterministic Priority Queue)"""
from __future__ import annotations
import sqlite3, json, uuid, threading, logging, os, heapq
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
SCHED_DB = rf"{HVOS_ROOT}\knowledge-graph\scheduler.db"

class AgentPriority(int, Enum):
    CRITICAL = 1; HIGH = 2; NORMAL = 3; LOW = 4

class AgentStatus(str, Enum):
    PENDING = "pending"; RUNNING = "running"; COMPLETED = "completed"
    FAILED = "failed"; CANCELLED = "cancelled"

@dataclass
class AgentTask:
    task_id: str; agent_id: str; agent_type: str; action: str; payload: dict
    priority: AgentPriority = AgentPriority.NORMAL
    status: AgentStatus = AgentStatus.PENDING
    scheduled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None; completed_at: Optional[str] = None
    result: Optional[dict] = None; error: Optional[str] = None
    causation_event_id: Optional[str] = None; correlation_id: Optional[str] = None
    attempt: int = 1; max_attempts: int = 3
    def to_dict(self) -> dict:
        d = asdict(self)
        d["priority"] = int(d["priority"]) if isinstance(d["priority"], Enum) else d["priority"]
        d["status"] = d["status"].value if isinstance(d["status"], Enum) else d["status"]
        return d

class PriorityQueue:
    def __init__(self):
        self._heap: List = []; self._lock = threading.Lock(); self._counter = 0
    def enqueue(self, task: AgentTask) -> AgentTask:
        with self._lock:
            self._counter += 1
            heapq.heappush(self._heap, (task.priority.value, self._counter, task))
        return task
    def dequeue(self) -> Optional[AgentTask]:
        with self._lock:
            if not self._heap: return None
            _, _, task = heapq.heappop(self._heap); return task
    def peek(self) -> Optional[AgentTask]:
        with self._lock:
            return self._heap[0][2] if self._heap else None
    def size(self) -> int:
        with self._lock: return len(self._heap)
    def clear(self):
        with self._lock: self._heap.clear(); self._counter = 0

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
    "CREATE TABLE IF NOT EXISTS agents ("
    "agent_id TEXT PRIMARY KEY,"
    "agent_type TEXT NOT NULL,"
    "name TEXT NOT NULL,"
    "status TEXT NOT NULL DEFAULT 'idle',"
    "registered_at TEXT NOT NULL,"
    "metadata TEXT);"
)

class SchedulerStore:
    def __init__(self, db_path: str = SCHED_DB):
        self.db_path = db_path; self._lock = threading.Lock(); self._ensure_db()
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL"); return conn
    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._lock:
            conn = self._conn(); cur = conn.cursor()
            for stmt in SQL_SCHEMA.split(";"):
                stmt = stmt.strip()
                if stmt: cur.execute(stmt)
            conn.commit(); conn.close()
    def save_task(self, task: AgentTask) -> AgentTask:
        with self._lock:
            conn = self._conn(); cur = conn.cursor()
            pri = int(task.priority.value if isinstance(task.priority, Enum) else task.priority)
            sta = task.status.value if isinstance(task.status, Enum) else task.status
            cur.execute(
                "INSERT OR REPLACE INTO tasks (task_id,agent_id,agent_type,action,payload,priority,status,scheduled_at,started_at,completed_at,result,error,causation_event_id,correlation_id,attempt,max_attempts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task.task_id, task.agent_id, task.agent_type, task.action,
                 json.dumps(task.payload, ensure_ascii=False), pri, sta,
                 task.scheduled_at, task.started_at, task.completed_at,
                 json.dumps(task.result, ensure_ascii=False) if task.result else None,
                 task.error, task.causation_event_id, task.correlation_id,
                 task.attempt, task.max_attempts))
            conn.commit(); conn.close()
        return task
    def load_task(self, task_id: str) -> Optional[AgentTask]:
        conn = self._conn(); conn.row_factory = sqlite3.Row; cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        row = cur.fetchone(); conn.close()
        if not row: return None
        d = dict(row)
        payload = json.loads(d["payload"]) if isinstance(d["payload"], str) else d["payload"]
        result = json.loads(d["result"]) if d.get("result") and isinstance(d["result"], str) else d.get("result")
        return AgentTask(
            task_id=d["task_id"], agent_id=d["agent_id"], agent_type=d["agent_type"],
            action=d["action"], payload=payload,
            priority=AgentPriority(d["priority"]),
            status=AgentStatus(d["status"]),
            scheduled_at=d["scheduled_at"], started_at=d.get("started_at"),
            completed_at=d.get("completed_at"), result=result,
            error=d.get("error"), causation_event_id=d.get("causation_event_id"),
            correlation_id=d.get("correlation_id"),
            attempt=d.get("attempt", 1), max_attempts=d.get("max_attempts", 3))
    def register_agent(self, agent_type: str, name: str, metadata: Optional[dict] = None) -> dict:
        with self._lock:
            agent_id = f"agent_{uuid.uuid4().hex[:12]}"
            conn = self._conn(); cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO agents (agent_id,agent_type,name,status,registered_at,metadata) VALUES (?,?,?,?,?,?)",
                (agent_id, agent_type, name, "idle", datetime.now(timezone.utc).isoformat(),
                 json.dumps(metadata or {}, ensure_ascii=False)))
            conn.commit(); conn.close()
        return {"agent_id": agent_id, "agent_type": agent_type, "name": name}
    def get_agents(self, agent_type: Optional[str] = None) -> List[dict]:
        conn = self._conn(); conn.row_factory = sqlite3.Row; cur = conn.cursor()
        if agent_type: cur.execute("SELECT * FROM agents WHERE agent_type=?", (agent_type,))
        else: cur.execute("SELECT * FROM agents")
        rows = cur.fetchall(); conn.close()
        return [dict(r) for r in rows]

class AgentScheduler:
    def __init__(self, store: Optional[SchedulerStore] = None):
        self.store = store or SchedulerStore()
        self._queue = PriorityQueue()
        self._running: Dict[str, AgentTask] = {}
        self._lock = threading.RLock()
    def submit(self, agent_id: str, agent_type: str, action: str, payload: dict,
              priority=AgentPriority.NORMAL,
              causation_event_id: Optional[str] = None,
              correlation_id: Optional[str] = None,
              task_id: Optional[str] = None) -> AgentTask:
        task = AgentTask(
            task_id=task_id or f"task_{uuid.uuid4().hex[:12]}",
            agent_id=agent_id, agent_type=agent_type, action=action, payload=payload,
            priority=priority, causation_event_id=causation_event_id, correlation_id=correlation_id)
        self.store.save_task(task)
        self._queue.enqueue(task)
        return task
    def dispatch(self) -> Optional[AgentTask]:
        with self._lock:
            task = self._queue.dequeue()
            if not task: return None
            task.status = AgentStatus.RUNNING
            task.started_at = datetime.now(timezone.utc).isoformat()
            self.store.save_task(task)
            self._running[task.task_id] = task
            return task
    def complete(self, task_id: str, result: dict) -> AgentTask:
        with self._lock:
            task = self._running.pop(task_id, None)
            if not task: task = self.store.load_task(task_id)
            if task:
                task.status = AgentStatus.COMPLETED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.result = result
                self.store.save_task(task)
            return task
    def fail(self, task_id: str, error: str) -> AgentTask:
        with self._lock:
            task = self._running.pop(task_id, None)
            if not task: task = self.store.load_task(task_id)
            if task:
                if task.attempt < task.max_attempts:
                    task.attempt += 1; task.status = AgentStatus.PENDING; task.started_at = None
                else:
                    task.status = AgentStatus.FAILED; task.completed_at = datetime.now(timezone.utc).isoformat(); task.error = error
                self.store.save_task(task)
            return task
    def cancel(self, task_id: str) -> Optional[AgentTask]:
        task = self.store.load_task(task_id)
        if task and task.status == AgentStatus.PENDING:
            task.status = AgentStatus.CANCELLED; self.store.save_task(task); return task
        return None
    def get_queue_size(self) -> int: return self._queue.size()
    def get_running(self) -> List[AgentTask]:
        with self._lock: return list(self._running.values())
    def peek_next(self) -> Optional[AgentTask]: return self._queue.peek()
    def register_agent(self, agent_type: str, name: str, metadata: Optional[dict] = None) -> dict:
        return self.store.register_agent(agent_type, name, metadata)
    def get_agents(self, agent_type: Optional[str] = None) -> List[dict]:
        return self.store.get_agents(agent_type)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["submit","dispatch","complete","queue","agents"], required=True)
    p.add_argument("--agent_id", default="test")
    p.add_argument("--agent_type", default="specialist")
    p.add_argument("--task_id")
    args = p.parse_args()
    sched = AgentScheduler()
    if args.action == "submit":
        t = sched.submit(args.agent_id, args.agent_type, "analyze", {}, priority=AgentPriority.HIGH)
        print(f"Submitted: {t.task_id}")
    elif args.action == "dispatch":
        t = sched.dispatch()
        if t: print(f"Dispatched: {t.task_id}")
        else: print("Queue empty")
    elif args.action == "complete":
        t = sched.complete(args.task_id, {"result": "ok"})
        print(f"Completed: {t.task_id}")
    elif args.action == "queue":
        print(f"Queue: {sched.get_queue_size()}")
    elif args.action == "agents":
        for a in sched.get_agents(): print(f"  {a['agent_id']} {a['agent_type']} {a['name']}")
