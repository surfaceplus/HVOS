"""
HVOS Executor
=============
Routes Codex-format tool_calls to specific HVOS tools and returns structured results.

The executor receives Codex-style JSON with tool_calls and:
1. Parses the tool call format
2. Routes to appropriate tool implementation
3. Returns Results API compatible output format
"""

import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from .schema import get_tool_schema, get_all_tool_schemas
from .tools import ProductSelector, ROICalculator, WeChatPusher, WCWriter
from .config import get_config


@dataclass
class ToolResult:
    """Result of a tool execution"""
    tool_name: str
    success: bool
    result: Dict[str, Any]
    error: Optional[str] = None
    
    def to_codex_format(self) -> dict:
        """Convert to Codex/OpenAI Responses API tool result format"""
        content = json.dumps(self.result, ensure_ascii=False, indent=2)
        
        return {
            "type": "tool_result",
            "tool_name": self.tool_name,
            "content": content,
            "success": self.success,
        }


class HVOSExecutor:
    """
    HVOS Executor - Routes Codex tool_calls to HVOS tools.
    
    Accepts Codex-format tool_calls JSON:
    {
        "tool_calls": [
            {
                "id": "call_abc123",
                "name": "product_selector",
                "arguments": {"category": "kitchen", "limit": 5}
            }
        ]
    }
    
    Returns Results API compatible output:
    {
        "results": [
            {
                "type": "tool_result",
                "tool_name": "product_selector",
                "content": "{...json result...}",
                "success": true
            }
        ]
    }
    
    Usage:
        executor = HVOSExecutor()
        result = executor.execute(tool_calls_json)
    """
    
    def __init__(self, config: dict = None):
        """
        Initialize executor with tools.
        
        Args:
            config: Optional configuration overrides
        """
        self.config = config or get_config()
        
        # Initialize tools
        self._tools: Dict[str, callable] = {}
        self._init_tools()
    
    def _init_tools(self):
        """Initialize all HVOS tools"""
        from .workflows import HVOSWorkflow, WorkflowConfig

        self._workflow_config = WorkflowConfig(
            min_alpha_score=60.0,
            min_net_margin=0.25,
            min_roi_pct=50.0,
            max_payback_days=60.0,
            alert_on_strict_pass=True,
            create_listing_on_pass=False,
        )

        self._tools = {
            "product_selector": ProductSelector(config=self.config.opportunity_config),
            "roi_calculator": ROICalculator(),
            "wechat_pusher": WeChatPusher(
                bot_token=self.config.weixin_bot_token,
                bot_url=self.config.weixin_bot_url,
            ),
            "wc_writer": WCWriter(
                db_host=self.config.wc_db_host,
                db_port=self.config.wc_db_port,
                db_user=self.config.wc_db_user,
                db_password=self.config.wc_db_password,
                db_name=self.config.wc_db_name,
            ),
            "workflow_pipeline": HVOSWorkflow(config=self._workflow_config),
        }
    
    def get_available_tools(self) -> List[dict]:
        """Get list of available tool schemas"""
        return get_all_tool_schemas()
    
    def execute(self, tool_calls: List[Dict]) -> List[ToolResult]:
        """
        Execute a list of tool calls.
        
        Args:
            tool_calls: List of Codex-format tool calls
            [
                {
                    "id": "call_abc123",
                    "name": "tool_name",
                    "arguments": {...}
                }
            ]
            
        Returns:
            List of ToolResult objects
        """
        results = []
        
        for call in tool_calls:
            tool_name = call.get("name", "")
            arguments = call.get("arguments", {})
            call_id = call.get("id", f"call_{id(call)}")
            
            # Get tool
            tool = self._tools.get(tool_name)
            if not tool:
                results.append(ToolResult(
                    tool_name=tool_name,
                    success=False,
                    result={},
                    error=f"Unknown tool: {tool_name}. Available tools: {list(self._tools.keys())}"
                ))
                continue
            
            # Execute tool
            try:
                result = self._execute_tool(tool_name, tool, arguments)
                results.append(result)
            except Exception as e:
                results.append(ToolResult(
                    tool_name=tool_name,
                    success=False,
                    result={},
                    error=f"Execution error: {str(e)}"
                ))
        
        return results
    
    def _execute_tool(self, tool_name: str, tool, arguments: dict) -> ToolResult:
        """Execute a single tool with given arguments"""
        
        # Product Selector
        if tool_name == "product_selector":
            result = tool.select(
                category=arguments.get("category", ""),
                limit=arguments.get("limit", 10),
                min_alpha_score=arguments.get("min_alpha_score", 0.0),
                recommendation=arguments.get("recommendation", ""),
            )
            return ToolResult(
                tool_name=tool_name,
                success=result.get("success", False),
                result=result,
            )
        
        # ROI Calculator
        elif tool_name == "roi_calculator":
            result = tool.calculate(
                predicted_revenue=arguments.get("predicted_revenue", 0),
                horizon_days=arguments.get("horizon_days", 90),
                currency=arguments.get("currency", "USD"),
                cogs_pct=arguments.get("cogs_pct", 0.28),
                advertising_cost_pct=arguments.get("advertising_cost_pct", 0.15),
                investment_amount=arguments.get("investment_amount", 0),
            )
            return ToolResult(
                tool_name=tool_name,
                success=result.get("success", False),
                result=result,
            )
        
        # WeChat Pusher
        elif tool_name == "wechat_pusher":
            result = tool.push(
                message=arguments.get("message", ""),
                msg_type=arguments.get("msg_type", "text"),
                reference_id=arguments.get("reference_id"),
            )
            return ToolResult(
                tool_name=tool_name,
                success=result.get("success", False),
                result=result,
            )
        
        # WooCommerce Writer
        elif tool_name == "wc_writer":
            metadata = arguments.get("metadata", {})

            result = tool.write(
                product_name=arguments.get("product_name", ""),
                price=arguments.get("price", 0),
                stock_quantity=arguments.get("stock_quantity", 0),
                product_status=arguments.get("product_status", "publish"),
                categories=arguments.get("categories", ""),
                opportunity_id=arguments.get("opportunity_id"),
                metadata=metadata,
            )
            return ToolResult(
                tool_name=tool_name,
                success=result.get("success", False),
                result=result,
            )

        # Workflow Pipeline
        elif tool_name == "workflow_pipeline":
            action = arguments.get("action", "full_pipeline")
            category = arguments.get("category", "")
            send_alert = arguments.get("send_alert", True)
            create_listing = arguments.get("create_listing", False)
            limit = arguments.get("limit", 20)

            # Update workflow config from arguments
            wf = tool
            if arguments.get("min_alpha_score") is not None:
                wf.config.min_alpha_score = arguments["min_alpha_score"]
            if arguments.get("min_net_margin") is not None:
                wf.config.min_net_margin = arguments["min_net_margin"]
            if arguments.get("min_roi_pct") is not None:
                wf.config.min_roi_pct = arguments["min_roi_pct"]

            if action == "scan_only":
                products = wf.scan_opportunities(category=category, limit=limit)
                result = {
                    "success": True,
                    "workflow": "scan_only",
                    "products": [
                        {"name": p.name, "category": p.category, "alpha_score": p.alpha_score}
                        for p in products
                    ],
                    "count": len(products),
                }
            elif action == "silent_scan":
                result = wf.run_silent_scan(category=category, limit=limit)
            else:
                result = wf.run_full_pipeline(
                    category=category,
                    send_alert=send_alert,
                    create_listing=create_listing,
                    limit=limit,
                )

            return ToolResult(
                tool_name=tool_name,
                success=True,
                result=result,
            )

        # Unknown tool
        else:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result={},
                error=f"Tool '{tool_name}' not implemented"
            )
    
    def execute_single(self, tool_name: str, arguments: dict) -> ToolResult:
        """
        Execute a single tool call.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments dict
            
        Returns:
            ToolResult object
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                result={},
                error=f"Unknown tool: {tool_name}"
            )
        
        return self._execute_tool(tool_name, tool, arguments)


# Convenience function
def execute_tool_calls(tool_calls: List[Dict]) -> List[Dict]:
    """
    Execute tool calls and return Codex-format results.
    
    Args:
        tool_calls: List of Codex-format tool calls
        
    Returns:
        List of Codex-format tool results
    """
    executor = HVOSExecutor()
    results = executor.execute(tool_calls)
    return [r.to_codex_format() for r in results]