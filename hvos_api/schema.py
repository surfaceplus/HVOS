"""
HVOS Tool Schemas
=================
OpenAI/Codex-compatible tool schema definitions for HVOS tools.

Each tool follows the tool_calls format:
{
    "name": "tool_name",
    "description": "...",
    "parameters": {
        "type": "object",
        "properties": {...},
        "required": [...]
    }
}

Tools:
1. product_selector   - Select products from opportunity engine
2. roi_calculator     - Calculate ROI/economics for a product
3. wechat_pusher      - Push message to WeChat via iLink Bot
4. wc_writer          - Write product to WooCommerce
"""

# Product Selector Schema
PRODUCT_SELECTOR_SCHEMA = {
    "name": "product_selector",
    "description": "Select top products from HVOS opportunity engine based on category, score thresholds, and limit. Returns ranked list of product opportunities with alpha scores and recommendations.",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Product category filter (e.g., 'kitchen', 'gift', 'pet', 'outdoor', 'beauty', 'home', 'tech', 'fitness'). Empty string returns all categories.",
                "enum": ["kitchen", "gift", "pet", "outdoor", "beauty", "home", "tech", "fitness", ""]
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of products to return",
                "default": 10,
                "minimum": 1,
                "maximum": 50
            },
            "min_alpha_score": {
                "type": "number",
                "description": "Minimum alpha score threshold (0.0-10.0)",
                "default": 0.0,
                "minimum": 0.0,
                "maximum": 10.0
            },
            "recommendation": {
                "type": "string",
                "description": "Filter by recommendation type",
                "enum": ["INVEST", "WATCH", "SKIP", ""],
                "default": ""
            }
        },
        "required": []
    }
}

# ROI Calculator Schema
ROI_CALCULATOR_SCHEMA = {
    "name": "roi_calculator",
    "description": "Calculate full economics breakdown (revenue, COGS,毛利, 净利, ROI, 回本周期) for a product opportunity. Uses HVOS EconomicsEngine with DTC gift industry benchmarks.",
    "parameters": {
        "type": "object",
        "properties": {
            "predicted_revenue": {
                "type": "number",
                "description": "Predicted revenue for the forecast period (in USD)",
            },
            "horizon_days": {
                "type": "integer",
                "description": "Forecast horizon in days",
                "default": 90,
                "minimum": 1,
                "maximum": 365
            },
            "currency": {
                "type": "string",
                "description": "Currency code",
                "default": "USD",
                "enum": ["USD", "CNY", "EUR", "GBP"]
            },
            "cogs_pct": {
                "type": "number",
                "description": "COGS as percentage of revenue (0.0-1.0, default 0.28 for DTC gift)",
                "default": 0.28
            },
            "advertising_cost_pct": {
                "type": "number",
                "description": "Advertising cost as percentage of revenue (0.0-1.0, default 0.15)",
                "default": 0.15
            },
            "investment_amount": {
                "type": "number",
                "description": "Override investment amount (auto-calculated as 50% of revenue if not provided)"
            }
        },
        "required": ["predicted_revenue"]
    }
}

# WeChat Pusher Schema
WECHAT_PUSHER_SCHEMA = {
    "name": "wechat_pusher",
    "description": "Push a formatted message to WeChat via iLink Bot API. Used for sending opportunity alerts, ROI reports, and decision notifications to WeChat.",
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message content to send to WeChat (supports markdown-like formatting)"
            },
            "msg_type": {
                "type": "string",
                "description": "Message type",
                "default": "text",
                "enum": ["text", "markdown", "news"]
            },
            "reference_id": {
                "type": "string",
                "description": "Optional reference ID (e.g., opportunity_id) for tracking"
            }
        },
        "required": ["message"]
    }
}

# WooCommerce Writer Schema
WC_WRITER_SCHEMA = {
    "name": "wc_writer",
    "description": "Write or update a product listing in WooCommerce via direct MySQL connection. Creates new product or updates existing one with name, price, stock, and metadata.",
    "parameters": {
        "type": "object",
        "properties": {
            "product_name": {
                "type": "string",
                "description": "Product name/title"
            },
            "price": {
                "type": "number",
                "description": "Product price in USD"
            },
            "stock_quantity": {
                "type": "integer",
                "description": "Stock quantity (0 for out of stock)",
                "default": 0
            },
            "product_status": {
                "type": "string",
                "description": "Product status in WooCommerce",
                "default": "publish",
                "enum": ["publish", "draft", "private", "pending"]
            },
            "categories": {
                "type": "string",
                "description": "Category names (comma-separated, e.g., 'Gift, Kitchen')"
            },
            "opportunity_id": {
                "type": "string",
                "description": "Linked HVOS opportunity ID for tracking"
            },
            "metadata": {
                "type": "object",
                "description": "Additional product metadata as key-value pairs",
                "properties": {}
            }
        },
        "required": ["product_name", "price"]
    }
}


# Workflow Schema
WORKFLOW_SCHEMA = {
    "name": "workflow_pipeline",
    "description": "Run the full HVOS automatic product selection + advertising workflow. Scan opportunities → filter by Alpha Score → calculate ROI → send WeChat alert → optionally create WooCommerce listing. Returns pass/fail breakdown for each product.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Workflow action to run",
                "enum": ["full_pipeline", "scan_only", "silent_scan"]
            },
            "category": {
                "type": "string",
                "description": "Product category filter (e.g., 'kitchen', 'gift', 'pet'). Empty string = all categories.",
                "default": ""
            },
            "min_alpha_score": {
                "type": "number",
                "description": "Minimum Alpha Score threshold (0-100, default 60)",
                "default": 60.0
            },
            "min_net_margin": {
                "type": "number",
                "description": "Minimum net margin percentage (0.0-1.0, default 0.25)",
                "default": 0.25
            },
            "min_roi_pct": {
                "type": "number",
                "description": "Minimum ROI percentage (default 50.0%)",
                "default": 50.0
            },
            "send_alert": {
                "type": "boolean",
                "description": "Send WeChat alert for passing products (default true)",
                "default": True
            },
            "create_listing": {
                "type": "boolean",
                "description": "Auto-create WooCommerce listings for passing products (default false)",
                "default": False
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of products to scan (default 20)",
                "default": 20
            }
        },
        "required": ["action"]
    }
}


# All tool schemas in OpenAI tool_calls format
ALL_TOOL_SCHEMAS = [
    PRODUCT_SELECTOR_SCHEMA,
    ROI_CALCULATOR_SCHEMA,
    WECHAT_PUSHER_SCHEMA,
    WC_WRITER_SCHEMA,
    WORKFLOW_SCHEMA,
]


def get_tool_schema(tool_name: str) -> dict:
    """Get schema for a specific tool by name"""
    for schema in ALL_TOOL_SCHEMAS:
        if schema["name"] == tool_name:
            return schema
    raise ValueError(f"Unknown tool: {tool_name}")


def get_all_tool_schemas() -> list:
    """Get all tool schemas"""
    return ALL_TOOL_SCHEMAS