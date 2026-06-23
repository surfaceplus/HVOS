"""
WeChat Pusher Tool
==================
Pushes messages to WeChat via iLink Bot API.

Uses the correct iLink sendmessage API format:
- POST /ilink/bot/sendmessage
- Payload: {"msg": {"from_user_id":"","to_user_id":"...","client_id":"...","message_type":2,"message_state":2,"item_list":[{"type":1,"text_item":{"text":"..."}}]}}
- Context token: echo the latest context_token from peer (stored by Hermes gateway)
- On errcode=-14: retry without context_token (iLink accepts tokenless fallback)

Supports text messages only.
"""

import os
import json
import sys
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from pathlib import Path


# iLink API constants (from Hermes gateway weixin.py)
ITEM_TEXT = 1
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2
SESSION_EXPIRED_ERRCODE = -14


# Hermes home
HERMES_HOME = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))


def _find_bot_accounts() -> list[dict]:
    """Find all weixin bot accounts from Hermes account files"""
    accounts_dir = Path(HERMES_HOME) / "weixin" / "accounts"
    if not accounts_dir.exists():
        return []
    accounts = []
    for f in sorted(accounts_dir.glob("*@im.bot.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            account_id = f.stem  # e.g. "4e7f0f305d5a@im.bot"
            data["account_id"] = account_id
            accounts.append(data)
        except Exception:
            pass
    return accounts


def _load_context_token(account_id: str, user_id: str) -> Optional[str]:
    """Load context_token for (account_id, user_id) from Hermes token store"""
    token_path = (
        Path(HERMES_HOME) / "weixin" / "accounts" / f"{account_id}.context-tokens.json"
    )
    if not token_path.exists():
        return None
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
        return data.get(user_id)
    except Exception:
        return None


def _save_context_token(account_id: str, user_id: str, token: str) -> None:
    """Persist context_token for future use (match Hermes gateway format)"""
    token_path = (
        Path(HERMES_HOME) / "weixin" / "accounts" / f"{account_id}.context-tokens.json"
    )
    try:
        data = {}
        if token_path.exists():
            data = json.loads(token_path.read_text(encoding="utf-8"))
        data[user_id] = token
        token_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class WeChatPusher:
    """
    WeChat Pusher Tool.

    Pushes messages to WeChat via iLink Bot webhook.

    Matches the Hermes gateway's iLink API format for sendmessage,
    including context_token handling and session-expiry retry.

    Usage:
        pusher = WeChatPusher()
        result = pusher.push(message="Hello from HVOS")
    """

    def __init__(
        self,
        bot_token: str = None,
        bot_url: str = None,
        account_id: str = None,
        to_user_id: str = None,
    ):
        """
        Initialize WeChat Pusher.

        Args:
            bot_token: iLink bot token (auto-detected from Hermes accounts)
            bot_url: iLink base URL
            account_id: Bot account ID (auto-detected from first available)
            to_user_id: Target WeChat user ID
        """
        # Auto-find bot accounts from Hermes
        accounts = _find_bot_accounts()

        if bot_token:
            self.bot_token = bot_token
        elif accounts:
            # Use the most recently saved account
            self.bot_token = accounts[-1].get("token", "")

        if bot_url:
            self.bot_url = bot_url.rstrip("/")
        elif accounts:
            self.bot_url = accounts[-1].get("base_url", "https://ilinkai.weixin.qq.com").rstrip("/")

        # Account and user IDs
        self.account_id = account_id or (accounts[-1]["account_id"] if accounts else "")
        self.to_user_id = to_user_id or os.getenv(
            "WEIXIN_ALLOWED",
            accounts[-1].get("user_id", "") if accounts else "",
        )

        # Load context_token if available
        self._context_token = _load_context_token(self.account_id, self.to_user_id)

    def push(
        self,
        message: str,
        msg_type: str = "text",
        reference_id: str = None,
    ) -> Dict[str, Any]:
        """
        Push a message to WeChat via iLink Bot API.

        Uses the correct iLink sendmessage protocol:
        1. Sends with context_token if available
        2. On errcode=-14 (session expired), retries WITHOUT context_token
        3. On success, stores any returned context_token

        Args:
            message: Message content to send
            msg_type: Ignored (iLink only supports text via bot API)
            reference_id: Optional reference ID for tracking

        Returns:
            Result of push operation
        """
        if not self.bot_token:
            return {
                "success": False,
                "tool": "wechat_pusher",
                "error": "No iLink bot token found. Configure a WeChat bot via Hermes gateway first.",
            }

        if not self.to_user_id:
            return {
                "success": False,
                "tool": "wechat_pusher",
                "error": "No target user ID. Set WEIXIN_ALLOWED env var or pass to_user_id.",
            }

        send_url = f"{self.bot_url}/ilink/bot/sendmessage"
        retried_without_token = False
        context_token = self._context_token
        last_error = None

        for attempt in range(2):  # Max 2 attempts: first with token, retry without
            try:
                # Build the iLink msg payload (matching Hermes gateway format)
                msg_payload = {
                    "from_user_id": "",
                    "to_user_id": self.to_user_id,
                    "client_id": self.account_id,
                    "message_type": MSG_TYPE_BOT,
                    "message_state": MSG_STATE_FINISH,
                    "item_list": [
                        {
                            "type": ITEM_TEXT,
                            "text_item": {"text": message},
                        }
                    ],
                }
                if context_token:
                    msg_payload["context_token"] = context_token

                payload = {"msg": msg_payload}
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

                req = urllib.request.Request(
                    send_url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self.bot_token}",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=15) as response:
                    response_data = response.read().decode("utf-8")

                resp_json = json.loads(response_data)
                ret = resp_json.get("ret", 0)
                errcode = resp_json.get("errcode", 0)

                # Check for session expiry
                is_expired = (
                    ret == SESSION_EXPIRED_ERRCODE
                    or errcode == SESSION_EXPIRED_ERRCODE
                    or (ret == -2 and errcode == -2 and "unknown error" in resp_json.get("errmsg", "").lower())
                )

                if is_expired and not retried_without_token and context_token:
                    # Session expired — retry once without context_token
                    retried_without_token = True
                    context_token = None
                    self._context_token = None
                    # Clear stored token
                    _save_context_token(self.account_id, self.to_user_id, "")
                    continue

                if ret not in {0, None} or errcode not in {0, None}:
                    return {
                        "success": False,
                        "tool": "wechat_pusher",
                        "error": f"iLink API error: ret={ret} errcode={errcode} errmsg={resp_json.get('errmsg','')}",
                        "response": response_data,
                    }

                # Success — save any context_token from response
                returned_token = resp_json.get("context_token")
                if returned_token:
                    self._context_token = returned_token
                    _save_context_token(self.account_id, self.to_user_id, returned_token)

                return {
                    "success": True,
                    "tool": "wechat_pusher",
                    "msg_type": msg_type,
                    "reference_id": reference_id,
                    "response": json.dumps(resp_json, ensure_ascii=False),
                }

            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace") if e.fp else ""
                last_error = f"HTTP Error {e.code}: {body[:200]}"
                if attempt == 0 and context_token:
                    # Try without context_token
                    retried_without_token = True
                    context_token = None
                    self._context_token = None
                    _save_context_token(self.account_id, self.to_user_id, "")
                    continue
                break
            except urllib.error.URLError as e:
                last_error = f"URL Error: {e.reason}"
                break
            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:200]}"
                if attempt == 0 and context_token:
                    retried_without_token = True
                    context_token = None
                    self._context_token = None
                    continue
                break

        return {
            "success": False,
            "tool": "wechat_pusher",
            "error": last_error or "All attempts failed",
        }

    def push_opportunity_alert(
        self,
        product_name: str,
        alpha_score: float,
        recommendation: str,
        category: str = "",
        opportunity_id: str = None,
    ) -> Dict[str, Any]:
        """
        Push an opportunity alert in formatted style.

        Args:
            product_name: Name of the product
            alpha_score: Alpha score (0-10)
            recommendation: INVEST/WATCH/SKIP
            category: Product category
            opportunity_id: HVOS opportunity ID

        Returns:
            Result of push operation
        """
        emoji_map = {
            "INVEST": "✅",
            "WATCH": "👀",
            "SKIP": "⏭️",
        }
        emoji = emoji_map.get(recommendation, "📌")

        message = f"""【HVOS 机会警报】
{emoji} 产品: {product_name}
📊 Alpha Score: {alpha_score:.1f}/10
🎯 推荐: {recommendation}
🏷️ 品类: {category or '通用'}"""

        if opportunity_id:
            message += f"\n🔖 ID: {opportunity_id}"

        return self.push(
            message=message,
            msg_type="text",
            reference_id=opportunity_id,
        )

    def push_roi_report(
        self,
        product_name: str,
        predicted_revenue: float,
        roi_pct: float,
        payback_days: float,
        gross_margin_pct: float,
        opportunity_id: str = None,
    ) -> Dict[str, Any]:
        """
        Push an ROI report in formatted style.

        Args:
            product_name: Name of the product
            predicted_revenue: Predicted revenue
            roi_pct: ROI percentage
            payback_days: Payback period in days
            gross_margin_pct: Gross margin percentage
            opportunity_id: HVOS opportunity ID

        Returns:
            Result of push operation
        """
        message = f"""【HVOS ROI 报告】
📦 产品: {product_name}
💰 预测收入: ${predicted_revenue:,.0f}
📈 ROI: {roi_pct:.1f}%
⏱️ 回本周期: {payback_days:.0f} 天
💵 毛利率: {gross_margin_pct:.1f}%"""

        if opportunity_id:
            message += f"\n🔖 ID: {opportunity_id}"

        return self.push(
            message=message,
            msg_type="text",
            reference_id=opportunity_id,
        )
