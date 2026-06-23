import os, json, time
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / "AppData" / "Local" / "hermes"))
ACCOUNTS_DIR = HERMES_HOME / "weixin" / "accounts"

def get_file_age_days(path):
    return (time.time() - path.stat().st_mtime) / 86400

def find_active_bot():
    bots = []
    for f in ACCOUNTS_DIR.glob("*@im.bot.json"):
        ctx_file = ACCOUNTS_DIR / (f.stem + ".context-tokens.json")
        if not ctx_file.exists():
            continue
        try:
            ctx = json.loads(ctx_file.read_text(encoding="utf-8"))
            if "o9cq8057jvG0MFsza8CSJx8EBOos@im.wechat" in ctx:
                bots.append({
                    "bot_id": f.stem,
                    "age_days": get_file_age_days(ctx_file),
                    "mtime": datetime.fromtimestamp(ctx_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        except Exception:
            pass
    return sorted(bots, key=lambda x: -x["age_days"])

def check_session_health():
    bots = find_active_bot()
    if not bots:
        return {"status": "no_session", "message": "未找到活跃 session", "action": "需要重新扫码"}
    newest = bots[0]
    age = newest["age_days"]
    remaining = 8 - age
    if age >= 8:
        status, message, action = "expired", f"Session 已过期！需要立即重新扫码", "hermes gateway setup -> Weixin -> 重新扫码"
    elif age >= 6:
        status, message, action = "warning", f"Session 还剩 {remaining:.1f} 天过期", f"请在 {remaining:.0f} 天内重新扫码"
    else:
        status, message, action = "healthy", f"Session 健康，剩余 {remaining:.1f} 天", None
    return {
        "bot_id": newest["bot_id"], "created_at": newest["mtime"],
        "age_days": round(age, 1), "remaining_days": round(remaining, 1),
        "status": status, "message": message, "action": action
    }

if __name__ == "__main__":
    health = check_session_health()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[WeChat Session Monitor] {now}")
    print(f"  Bot: {health.get('bot_id')}")
    print(f"  创建: {health.get('created_at')}")
    print(f"  年龄: {health.get('age_days')} 天")
    print(f"  状态: {health.get('message')}")
    if health.get("action"):
        print(f"  操作: {health['action']}")
    output = HERMES_HOME / "wechat_session_status.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)
    if health["status"] in ("expired", "warning"):
        print(f"\n!! 需要操作: {health['action']}")
        exit(1)
    exit(0)
