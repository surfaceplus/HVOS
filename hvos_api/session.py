"""
HVOS Session Manager
====================
Manages session context and memory for HVOS API.

Each session is identified by conversation_id/session_id and maintains:
- Message history (context window)
- Tool execution results
- Short-term memory

Session data is stored in JSON files per session.
"""

import os
import json
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path


@dataclass
class SessionMessage:
    """A single message in the session"""
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SessionContext:
    """Session context containing messages and metadata"""
    session_id: str
    messages: List[SessionMessage] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Short-term memory
    memory: Dict[str, Any] = field(default_factory=dict)
    
    def add_message(self, role: str, content: str, tool_calls: Optional[List[Dict]] = None,
                   tool_call_id: Optional[str] = None):
        """Add a message to the session"""
        msg = SessionMessage(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id
        )
        self.messages.append(msg)
        self.updated_at = datetime.now().isoformat()
    
    def add_memory(self, key: str, value: Any):
        """Store value in short-term memory"""
        self.memory[key] = value
        self.updated_at = datetime.now().isoformat()
    
    def get_memory(self, key: str, default: Any = None) -> Any:
        """Retrieve value from short-term memory"""
        return self.memory.get(key, default)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            "session_id": self.session_id,
            "messages": [asdict(m) for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "memory": self.memory,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "SessionContext":
        """Reconstruct from dictionary"""
        messages = [SessionMessage(**m) for m in d.get("messages", [])]
        return cls(
            session_id=d["session_id"],
            messages=messages,
            created_at=d.get("created_at", datetime.now().isoformat()),
            updated_at=d.get("updated_at", datetime.now().isoformat()),
            metadata=d.get("metadata", {}),
            memory=d.get("memory", {}),
        )


class SessionManager:
    """
    Session Manager for HVOS API.
    
    Manages session context windows and memory persistence.
    
    Usage:
        sm = SessionManager()
        
        # Create or get session
        ctx = sm.get_or_create_session("conv_123")
        
        # Add messages
        ctx.add_message("user", "帮我选一个厨房产品")
        ctx.add_message("assistant", "", tool_calls=[...])
        
        # Store results in memory
        ctx.add_memory("last_selected_products", [...])
        
        # Save session
        sm.save_session(ctx)
    """
    
    MAX_CONTEXT_MESSAGES = 100  # Max messages per session
    SESSION_TTL_HOURS = 24     # Session TTL in hours
    
    def __init__(self, session_dir: str = None):
        """
        Initialize Session Manager.
        
        Args:
            session_dir: Directory to store session JSON files.
                        Defaults to HVOS memory directory.
        """
        if session_dir is None:
            session_dir = "C:/Users/Administrator/AppData/Local/hermes/hvos/memory"
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache of active sessions
        self._sessions: Dict[str, SessionContext] = {}
    
    def _session_file_path(self, session_id: str) -> Path:
        """Get file path for session JSON file"""
        return self.session_dir / f"session_{session_id}.json"
    
    def get_or_create_session(self, session_id: str, metadata: Dict[str, Any] = None) -> SessionContext:
        """
        Get existing session or create new one.
        
        Args:
            session_id: Unique session/conversation ID
            metadata: Optional initial metadata
            
        Returns:
            SessionContext for the session
        """
        # Check memory cache first
        if session_id in self._sessions:
            ctx = self._sessions[session_id]
            # Check TTL
            updated = datetime.fromisoformat(ctx.updated_at)
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            if age_hours < self.SESSION_TTL_HOURS:
                return ctx
            # Expired, remove from cache
            del self._sessions[session_id]
        
        # Check disk
        path = self._session_file_path(session_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ctx = SessionContext.from_dict(data)
                self._sessions[session_id] = ctx
                return ctx
            except (json.JSONDecodeError, KeyError) as e:
                # Corrupted file, create new
                pass
        
        # Create new session
        ctx = SessionContext(
            session_id=session_id,
            metadata=metadata or {}
        )
        self._sessions[session_id] = ctx
        self.save_session(ctx)
        return ctx
    
    def save_session(self, ctx: SessionContext):
        """Save session to disk"""
        # Truncate messages if too long
        if len(ctx.messages) > self.MAX_CONTEXT_MESSAGES:
            ctx.messages = ctx.messages[-self.MAX_CONTEXT_MESSAGES:]
        
        path = self._session_file_path(ctx.session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ctx.to_dict(), f, ensure_ascii=False, indent=2)
    
    def delete_session(self, session_id: str):
        """Delete a session"""
        # Remove from cache
        if session_id in self._sessions:
            del self._sessions[session_id]
        
        # Remove from disk
        path = self._session_file_path(session_id)
        if path.exists():
            path.unlink()
    
    def list_sessions(self) -> List[str]:
        """List all session IDs"""
        sessions = []
        for f in self.session_dir.glob("session_*.json"):
            session_id = f.stem.replace("session_", "")
            sessions.append(session_id)
        return sessions
    
    def cleanup_expired(self):
        """Remove expired sessions from disk"""
        for session_id in self.list_sessions():
            ctx = self.get_or_create_session(session_id)
            updated = datetime.fromisoformat(ctx.updated_at)
            age_hours = (datetime.now() - updated).total_seconds() / 3600
            if age_hours >= self.SESSION_TTL_HOURS:
                self.delete_session(session_id)


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager(session_dir: str = None) -> SessionManager:
    """Get or create global session manager"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager(session_dir)
    return _session_manager