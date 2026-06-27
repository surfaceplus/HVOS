"""HVOS V10.2 - World Model Engine (State Machine Layer)"""
from __future__ import annotations
import sqlite3, json, uuid, threading, logging, os
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any
from enum import Enum

logger = logging.getLogger(__name__)

from hvos_config import HVOS_ROOT, STATE_DB


class OpportunityStage(str, Enum):
    DISCOVER = "DISCOVER"
    VALIDATE = "VALIDATE"
    SCALE = "SCALE"
    HOLD = "HOLD"
    STOP = "STOP"


class OpportunityAction(str, Enum):
    INVEST = "INVEST"
    SCALE_UP = "SCALE_UP"
    HOLD_POS = "HOLD"
    STOP_INVEST = "STOP"
    WAIT = "WAIT"


@dataclass
class OpportunityState:
    opp_id: str
    stage: OpportunityStage
    demand_score: float = 0.0
    trend_score: float = 0.0
    supply_score: float = 0.0
    margin_estimate: float = 0.0
    risk_score: float = 0.0
    confidence: float = 0.0
    roi_estimate: float = 0.0
    invested_amount: float = 0.0
    monthly_profit_low: float = 0.0
    monthly_profit_high: float = 0.0
    alpha_score: float = 0.0
    last_action: Optional[OpportunityAction] = None
    sequence: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stage"] = self.stage.value if isinstance(self.stage, OpportunityStage) else self.stage
        d["last_action"] = self.last_action.value if self.last_action and isinstance(self.last_action, OpportunityAction) else self.last_action
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OpportunityState":
        d = dict(d)
        if isinstance(d.get("stage"), str):
            d["stage"] = OpportunityStage(d["stage"])
        if isinstance(d.get("last_action"), str):
            d["last_action"] = OpportunityAction(d["last_action"]) if d["last_action"] else None
        return cls(**d)


@dataclass
class StateTransition:
    transition_id: str
    opp_id: str
    from_state: dict
    action: OpportunityAction
    to_state: dict
    causation_event_id: Optional[str] = None
    correlation_id: Optional[str] = None
    sequence: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    basis: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["action"] = self.action.value if isinstance(self.action, OpportunityAction) else self.action
        return d

    @classmethod
    def from_row(cls, row) -> "StateTransition":
        from_state = json.loads(row["from_state"]) if isinstance(row["from_state"], str) else row["from_state"]
        to_state = json.loads(row["to_state"]) if isinstance(row["to_state"], str) else row["to_state"]
        return cls(
            transition_id=row["transition_id"], opp_id=row["opp_id"],
            from_state=from_state, action=OpportunityAction(row["action"]), to_state=to_state,
            causation_event_id=row["causation_event_id"], correlation_id=row["correlation_id"],
            sequence=row["sequence"], timestamp=row["timestamp"], basis=dict(row).get('basis', ''),
        )


SQL_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS world_state ("
    "opp_id TEXT PRIMARY KEY,"
    "stage TEXT NOT NULL,"
    "demand_score REAL DEFAULT 0.0,"
    "trend_score REAL DEFAULT 0.0,"
    "supply_score REAL DEFAULT 0.0,"
    "margin_estimate REAL DEFAULT 0.0,"
    "risk_score REAL DEFAULT 0.0,"
    "confidence REAL DEFAULT 0.0,"
    "roi_estimate REAL DEFAULT 0.0,"
    "invested_amount REAL DEFAULT 0.0,"
    "monthly_profit_low REAL DEFAULT 0.0,"
    "monthly_profit_high REAL DEFAULT 0.0,"
    "alpha_score REAL DEFAULT 0.0,"
    "last_action TEXT,"
    "sequence INTEGER DEFAULT 0,"
    "updated_at TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS transitions ("
    "transition_id TEXT PRIMARY KEY,"
    "opp_id TEXT NOT NULL,"
    "from_state TEXT NOT NULL,"
    "action TEXT NOT NULL,"
    "to_state TEXT NOT NULL,"
    "causation_event_id TEXT,"
    "correlation_id TEXT,"
    "sequence INTEGER NOT NULL,"
    "timestamp TEXT NOT NULL,"
    "basis TEXT DEFAULT '',"
    "FOREIGN KEY (opp_id) REFERENCES world_state(opp_id));"
    "CREATE INDEX IF NOT EXISTS idx_trans_opp ON transitions(opp_id);"
    "CREATE INDEX IF NOT EXISTS idx_trans_seq ON transitions(sequence);"
)


class WorldModelStore:
    def __init__(self, db_path: str = STATE_DB):
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

    def save_state(self, state: OpportunityState) -> OpportunityState:
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            last_act = state.last_action.value if state.last_action and isinstance(state.last_action, OpportunityAction) else state.last_action
            cur.execute(
                "INSERT OR REPLACE INTO world_state (opp_id,stage,demand_score,trend_score,supply_score,margin_estimate,risk_score,confidence,roi_estimate,invested_amount,monthly_profit_low,monthly_profit_high,alpha_score,last_action,sequence,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    state.opp_id,
                    state.stage.value if isinstance(state.stage, OpportunityStage) else state.stage,
                    state.demand_score, state.trend_score, state.supply_score, state.margin_estimate,
                    state.risk_score, state.confidence, state.roi_estimate, state.invested_amount,
                    state.monthly_profit_low, state.monthly_profit_high, state.alpha_score,
                    last_act, state.sequence, state.updated_at,
                ),
            )
            conn.commit()
            conn.close()
        return state

    def load_state(self, opp_id: str) -> Optional[OpportunityState]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM world_state WHERE opp_id=?", (opp_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return OpportunityState(
            opp_id=row["opp_id"], stage=OpportunityStage(row["stage"]),
            demand_score=row["demand_score"], trend_score=row["trend_score"],
            supply_score=row["supply_score"], margin_estimate=row["margin_estimate"],
            risk_score=row["risk_score"], confidence=row["confidence"],
            roi_estimate=row["roi_estimate"], invested_amount=row["invested_amount"],
            monthly_profit_low=row["monthly_profit_low"], monthly_profit_high=row["monthly_profit_high"],
            alpha_score=row["alpha_score"],
            last_action=OpportunityAction(row["last_action"]) if row["last_action"] else None,
            sequence=row["sequence"], updated_at=row["updated_at"],
        )

    def log_transition(self, t: StateTransition) -> StateTransition:
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(sequence), 0) FROM transitions")
            last_seq = cur.fetchone()[0]
            t.sequence = last_seq + 1
            cur.execute(
                "INSERT INTO transitions (transition_id,opp_id,from_state,action,to_state,causation_event_id,correlation_id,sequence,timestamp,basis) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    t.transition_id, t.opp_id,
                    json.dumps(t.from_state, ensure_ascii=False),
                    t.action.value if isinstance(t.action, OpportunityAction) else t.action,
                    json.dumps(t.to_state, ensure_ascii=False),
                    t.causation_event_id, t.correlation_id,
                    t.sequence, t.timestamp, t.basis,
                ),
            )
            conn.commit()
            conn.close()
        return t

    def get_all_states(self) -> List[OpportunityState]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM world_state")
        rows = cur.fetchall()
        conn.close()
        states = []
        for row in rows:
            r = dict(row)
            states.append(OpportunityState(
                opp_id=r["opp_id"], stage=OpportunityStage(r["stage"]),
                demand_score=r["demand_score"], trend_score=r["trend_score"],
                supply_score=r["supply_score"], margin_estimate=r["margin_estimate"],
                risk_score=r["risk_score"], confidence=r["confidence"],
                roi_estimate=r["roi_estimate"], invested_amount=r["invested_amount"],
                monthly_profit_low=r["monthly_profit_low"], monthly_profit_high=r["monthly_profit_high"],
                alpha_score=r["alpha_score"],
                last_action=OpportunityAction(r["last_action"]) if r["last_action"] else None,
                sequence=r["sequence"], updated_at=r["updated_at"],
            ))
        return states
    
    def get_transitions(self, opp_id: str, limit: int = 100) -> List[StateTransition]:
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM transitions WHERE opp_id=? ORDER BY sequence ASC LIMIT ?", (opp_id, limit))
        rows = cur.fetchall()
        conn.close()
        return [StateTransition.from_row(r) for r in rows]


class WorldModelEngine:
    """
    World Model = formal state machine for each opportunity.
    T(S, A) -> S (deterministic transition function)
    Guard conditions on actions.
    Event-sourced: all transitions logged with causation_id.
    """

    VALID_ACTIONS = {
        OpportunityStage.DISCOVER: {OpportunityAction.INVEST, OpportunityAction.WAIT, OpportunityAction.STOP_INVEST},
        OpportunityStage.VALIDATE: {OpportunityAction.SCALE_UP, OpportunityAction.HOLD_POS, OpportunityAction.STOP_INVEST, OpportunityAction.WAIT},
        OpportunityStage.SCALE: {OpportunityAction.HOLD_POS, OpportunityAction.SCALE_UP, OpportunityAction.STOP_INVEST},
        OpportunityStage.HOLD: {OpportunityAction.INVEST, OpportunityAction.SCALE_UP, OpportunityAction.STOP_INVEST},
        OpportunityStage.STOP: {OpportunityAction.INVEST},
    }

    def __init__(self, store: Optional[WorldModelStore] = None):
        self.store = store or WorldModelStore()

    def compute_next_state(self, current: OpportunityState, action: OpportunityAction, metrics: Optional[dict] = None) -> OpportunityState:
        valid = self.VALID_ACTIONS.get(current.stage, set())
        if action not in valid:
            raise ValueError(f"Action {action} not valid in stage {current.stage}")
        new_state = OpportunityState(
            opp_id=current.opp_id, stage=current.stage,
            demand_score=current.demand_score, trend_score=current.trend_score,
            supply_score=current.supply_score, margin_estimate=current.margin_estimate,
            risk_score=current.risk_score, confidence=current.confidence,
            roi_estimate=current.roi_estimate, invested_amount=current.invested_amount,
            monthly_profit_low=current.monthly_profit_low, monthly_profit_high=current.monthly_profit_high,
            alpha_score=current.alpha_score,
            last_action=action, sequence=current.sequence + 1,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        if metrics:
            for k, v in metrics.items():
                if hasattr(new_state, k):
                    setattr(new_state, k, v)
        if action == OpportunityAction.INVEST:
            new_state.stage = OpportunityStage.VALIDATE
        elif action == OpportunityAction.SCALE_UP:
            new_state.stage = OpportunityStage.SCALE
        elif action == OpportunityAction.STOP_INVEST:
            new_state.stage = OpportunityStage.STOP
        elif action == OpportunityAction.HOLD_POS:
            new_state.stage = OpportunityStage.HOLD
        return new_state

    def transition(
        self,
        opp_id: str,
        action: OpportunityAction,
        metrics: Optional[dict] = None,
        causation_event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        basis: str = "",
    ) -> StateTransition:
        current = self.store.load_state(opp_id)
        if current is None:
            raise ValueError(f"No state found for opp_id: {opp_id}")
        new_state = self.compute_next_state(current, action, metrics)
        transition_record = StateTransition(
            transition_id=f"tr_{uuid.uuid4().hex[:12]}",
            opp_id=opp_id,
            from_state=current.to_dict(),
            action=action,
            to_state=new_state.to_dict(),
            causation_event_id=causation_event_id,
            correlation_id=correlation_id,
            basis=basis,
        )
        self.store.save_state(new_state)
        return self.store.log_transition(transition_record)

    def create_opportunity(self, opp_id: str, initial_metrics: Optional[dict] = None) -> OpportunityState:
        im = initial_metrics or {}
        state = OpportunityState(
            opp_id=opp_id, stage=OpportunityStage.DISCOVER,
            demand_score=im.get("demand_score", 0.0),
            trend_score=im.get("trend_score", 0.0),
            supply_score=im.get("supply_score", 0.0),
            margin_estimate=im.get("margin_estimate", 0.0),
            risk_score=im.get("risk_score", 0.0),
            confidence=im.get("confidence", 0.0),
            roi_estimate=im.get("roi_estimate", 0.0),
            monthly_profit_low=im.get("monthly_profit_low", 0.0),
            monthly_profit_high=im.get("monthly_profit_high", 0.0),
            alpha_score=im.get("alpha_score", 0.0),
            last_action=None, sequence=0,
        )
        return self.store.save_state(state)

    def get_state(self, opp_id: str) -> Optional[OpportunityState]:
        return self.store.load_state(opp_id)

    def get_transitions(self, opp_id: str) -> List[StateTransition]:
        return self.store.get_transitions(opp_id)

    def can_transition(self, opp_id: str, action: OpportunityAction) -> bool:
        state = self.store.load_state(opp_id)
        if not state:
            return False
        return action in self.VALID_ACTIONS.get(state.stage, set())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HVOS World Model CLI")
    parser.add_argument("--action", choices=["create", "transition", "state", "log", "can"], required=True)
    parser.add_argument("--opp_id", required=True)
    parser.add_argument("--action_type", help="SCALE_UP / HOLD / STOP_INVEST / WAIT / INVEST")
    args = parser.parse_args()
    wm = WorldModelEngine()
    if args.action == "create":
        s = wm.create_opportunity(args.opp_id)
        print(f"Created: {s.opp_id} stage={s.stage.value}")
    elif args.action == "state":
        s = wm.get_state(args.opp_id)
        if s:
            print(f"Stage: {s.stage.value} action={s.last_action} seq={s.sequence}")
        else:
            print("Not found")
    elif args.action == "can":
        ok = wm.can_transition(args.opp_id, OpportunityAction(args.action_type))
        print(f"Can {args.action_type}: {ok}")
    elif args.action == "transition":
        t = wm.transition(args.opp_id, OpportunityAction(args.action_type))
        print(f"Transition: {t.transition_id} seq={t.sequence} {t.action.value}")
