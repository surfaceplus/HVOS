"""
HVOS API Server
===============
Flask-based HTTP API server providing Codex/OpenAI Responses API compatible endpoints.

Endpoints:
  POST /responses    - Main Responses API endpoint (Codex compatible)
  GET  /tools        - List available tools and schemas
  GET  /health       - Health check
  GET  /sessions     - List sessions
  GET  /sessions/<id> - Get session context

Usage:
  python -m hvos_api.server
  
  or
  
  from hvos_api.server import app
  app.run(host="0.0.0.0", port=5000)
"""

import os
import sys
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify, Response

# Add HVOS paths
HVOS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [HVOS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from .config import get_config, HVOSConfig
from .schema import get_all_tool_schemas, get_tool_schema
from .session import get_session_manager, SessionContext
from .executor import HVOSExecutor


# Create Flask app
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.config["JSONIFY_PRETTYPRINT"] = True

# Global executor
_executor: Optional[HVOSExecutor] = None


def get_executor() -> HVOSExecutor:
    """Get or create global executor"""
    global _executor
    if _executor is None:
        _executor = HVOSExecutor()
    return _executor


def get_session_manager_instance():
    """Get session manager instance"""
    config = get_config()
    return get_session_manager(config.session_dir)


# =============================================================================
# Routes
# =============================================================================

@app.route("/health", methods=["GET"])
def health_check():
    """
    Health check endpoint.
    
    Returns:
        200 OK with status info
    """
    return jsonify({
        "status": "ok",
        "service": "HVOS API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    })


@app.route("/tools", methods=["GET"])
def list_tools():
    """
    List all available tools and their schemas.
    
    Returns:
        List of tool schemas in OpenAI tool_calls format
    """
    tools = get_all_tool_schemas()
    return jsonify({
        "tools": tools,
        "count": len(tools),
    })


@app.route("/tools/<tool_name>", methods=["GET"])
def get_tool(tool_name: str):
    """
    Get schema for a specific tool.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Tool schema
    """
    try:
        schema = get_tool_schema(tool_name)
        return jsonify(schema)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/sessions", methods=["GET"])
def list_sessions():
    """
    List all sessions.
    
    Returns:
        List of session IDs
    """
    sm = get_session_manager_instance()
    sessions = sm.list_sessions()
    return jsonify({
        "sessions": sessions,
        "count": len(sessions),
    })


@app.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id: str):
    """
    Get session context.
    
    Args:
        session_id: Session ID
        
    Returns:
        Session context with messages and memory
    """
    sm = get_session_manager_instance()
    ctx = sm.get_or_create_session(session_id)
    return jsonify(ctx.to_dict())


@app.route("/responses", methods=["POST"])
def handle_responses():
    """
    Main Responses API endpoint (Codex/OpenAI compatible).
    
    Accepts Codex-format JSON:
    {
        "model": "HVOS",
        "messages": [
            {"role": "user", "content": "帮我选一个厨房产品"}
        ],
        "session_id": "optional-session-id",
        "tool_calls": [
            {
                "id": "call_abc123",
                "name": "product_selector",
                "arguments": {"category": "kitchen", "limit": 5}
            }
        ],
        "stream": false
    }
    
    Returns Responses API format:
    {
        "id": "resp_abc123",
        "model": "HVOS",
        "results": [...],
        "session_id": "...",
        "usage": {...}
    }
    """
    try:
        # Parse request
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400
        
        model = data.get("model", "HVOS")
        messages = data.get("messages", [])
        session_id = data.get("session_id") or str(uuid.uuid4())[:8]
        tool_calls = data.get("tool_calls", [])
        stream = data.get("stream", False)
        
        # Get or create session
        sm = get_session_manager_instance()
        ctx = sm.get_or_create_session(
            session_id,
            metadata={"model": model}
        )
        
        # Add user messages to session
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                ctx.add_message(role, content)
        
        # Execute tool calls
        results = []
        usage = {"total_tokens": 0, "tool_calls_count": 0}
        
        if tool_calls:
            executor = get_executor()
            tool_results = executor.execute(tool_calls)
            
            for tr in tool_results:
                results.append(tr.to_codex_format())
                usage["tool_calls_count"] += 1
                
                # Add tool result to session memory
                ctx.add_memory(f"last_{tr.tool_name}_result", tr.result)
        
        # Build response
        response = {
            "id": f"resp_{uuid.uuid4().hex[:12]}",
            "model": model,
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "results": results,
            "usage": usage,
        }
        
        # If there are messages but no tool calls, generate a text response
        if not tool_calls and messages:
            last_msg = messages[-1].get("content", "") if messages else ""
            response["text"] = f"HVOS API received: {last_msg[:100]}..."
        
        # Save session
        sm.save_session(ctx)
        
        # Return appropriate response type
        if stream:
            # For streaming, we would use Server-Sent Events
            # For simplicity, return non-streamed for now
            pass
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__,
        }), 500


@app.route("/responses/stream", methods=["POST"])
def handle_responses_stream():
    """
    Streaming version of /responses endpoint.
    
    Returns Server-Sent Events (SSE) stream.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400
        
        # For now, return same as non-streaming
        # In production, implement proper SSE streaming
        return handle_responses()
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__,
        }), 500


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "path": request.path}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error", "message": str(e)}), 500


# =============================================================================
# Main Entry Point
# =============================================================================

def create_app() -> Flask:
    """Create and configure the Flask app"""
    return app


def run_server():
    """Run the HVOS API server"""
    config = get_config()
    
    print("=" * 60)
    print("HVOS API Server")
    print("=" * 60)
    print(f"Host: {config.host}")
    print(f"Port: {config.port}")
    print(f"Debug: {config.debug}")
    print(f"Session Dir: {config.session_dir}")
    print("=" * 60)
    print()
    
    app.run(
        host=config.host,
        port=config.port,
        debug=config.debug,
    )


if __name__ == "__main__":
    run_server()