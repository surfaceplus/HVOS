"""
HVOS API Execution Layer
========================
Flask-based HTTP API server providing Codex/OpenAI Responses API compatible
endpoints for HVOS tools: product selector, ROI calculator, WeChat pusher,
WooCommerce writer.

Author: HVOS X API Layer
Version: 1.0.0
"""

__version__ = "1.0.0"
__all__ = ["server", "executor", "schema", "session", "config"]