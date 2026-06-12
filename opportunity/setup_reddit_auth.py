"""
Reddit OAuth 授权脚本（命令行模式）
用法：
  python setup_reddit_auth.py --client-id XXXXX --client-secret XXXXX

或只传 client-id，会生成授权 URL：
  python setup_reddit_auth.py --client-id XXXXX
"""

import os
import sys
import requests

HVOS_ROOT = r"C:\Users\Administrator\AppData\Local\hermes\hvos"
sys.path.insert(0, HVOS_ROOT)

HERMES_HOME = os.path.expanduser("~/.hermes")
os.makedirs(HERMES_HOME, exist_ok=True)
ENV_FILE = os.path.join(HERMES_HOME, ".env")


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def save_env(env: dict):
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            lines = f.readlines()

    keys_found = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            new_lines.append(line)
        elif "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in env:
                new_lines.append(f'{k}="{env[k]}"\n')
                keys_found.add(k)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for k, v in env.items():
        if k not in keys_found:
            new_lines.append(f'{k}="{v}"\n')

    with open(ENV_FILE, "w") as f:
        f.writelines(new_lines)


def generate_auth_url(client_id: str):
    """生成授权 URL"""
    scopes = ["identity", "read"]
    redirect_uri = "http://localhost:8080"
    state = "hvos_opportunity_engine"

    import urllib.parse
    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri,
        "duration": "permanent",
        "scope": " ".join(scopes)
    }
    url = "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(params)
    return url


def exchange_code(client_id: str, client_secret: str, code: str):
    """换取 access token"""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://localhost:8080"
    }
    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        data=data,
        auth=auth,
        headers={"User-Agent": "HVOS Opportunity Engine/1.0 (by /u/hvos_team)"},
        timeout=15
    )
    return r.json()


def test_token(access_token: str) -> dict:
    """测试 token 是否有效"""
    r = requests.get(
        "https://oauth.reddit.com/api/v1/me",
        headers={
            "Authorization": f"bearer {access_token}",
            "User-Agent": "HVOS Opportunity Engine/1.0"
        },
        timeout=10
    )
    if r.status_code == 200:
        return r.json()
    return None


def save_credentials(client_id: str, client_secret: str, access_token: str, refresh_token: str = None):
    """保存凭证"""
    env = {
        "REDDIT_CLIENT_ID": client_id,
        "REDDIT_CLIENT_SECRET": client_secret,
        "REDDIT_ACCESS_TOKEN": access_token,
    }
    if refresh_token:
        env["REDDIT_REFRESH_TOKEN"] = refresh_token

    save_env(env)

    # 同时写入环境变量
    os.environ["REDDIT_CLIENT_ID"] = client_id
    os.environ["REDDIT_CLIENT_SECRET"] = client_secret
    os.environ["REDDIT_ACCESS_TOKEN"] = access_token
    if refresh_token:
        os.environ["REDDIT_REFRESH_TOKEN"] = refresh_token

    print(f"✅ 凭证已保存到: {ENV_FILE}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HVOS Reddit OAuth")
    parser.add_argument("--client-id", help="Reddit App CLIENT ID")
    parser.add_argument("--client-secret", help="Reddit App CLIENT SECRET")
    parser.add_argument("--code", help="Authorization code (from callback URL)")

    args = parser.parse_args()

    print()
    print("=" * 60)
    print("HVOS Reddit OAuth 配置")
    print("=" * 60)

    # 检查已有凭证
    env = load_env()
    client_id = args.client_id or env.get("REDDIT_CLIENT_ID")
    client_secret = args.client_secret or env.get("REDDIT_CLIENT_SECRET")

    if not client_id:
        print("\n用法:")
        print("  1. 先创建 Reddit App (https://www.reddit.com/prefs/apps)")
        print("  2. 获取 CLIENT ID 和 CLIENT SECRET")
        print("  3. 运行: python setup_reddit_auth.py --client-id XXXXX --client-secret YYYYY")
        print()
        print("或:")
        print("  python setup_reddit_auth.py --client-id XXXXX")
        print("  (会生成授权 URL，让你在浏览器中授权)")
        return

    if not client_secret:
        # 只有 client_id，生成授权 URL
        url = generate_auth_url(client_id)
        print(f"\n步骤:")
        print(f"  1. 在浏览器打开: {url}")
        print(f"  2. 点击 Authorize")
        print(f"  3. 浏览器跳转到 http://localhost:8080?code=XXXXX")
        print(f"  4. 复制 URL 或只复制 code= 后面的部分")
        print()
        code = input("粘贴 code: ").strip()
        if not code:
            print("code 不能为空")
            return
    else:
        code = args.code

    if not code:
        print("需要提供 --code 参数")
        return

    print("\n正在换取 access token...")
    try:
        result = exchange_code(client_id, client_secret, code)
    except Exception as e:
        print(f"❌ 换取 token 失败: {e}")
        sys.exit(1)

    if "error" in result:
        print(f"❌ OAuth 错误: {result.get('error')}: {result.get('error_description', '')}")
        sys.exit(1)

    access_token = result.get("access_token")
    refresh_token = result.get("refresh_token")

    if not access_token:
        print(f"❌ 未获取到 access_token: {result}")
        sys.exit(1)

    print("✅ Token 获取成功!")

    # 测试
    user_info = test_token(access_token)
    if user_info:
        print(f"✅ 连接测试成功! 用户: {user_info.get('name')}")
    else:
        print("⚠️  Token 获取成功但连接测试失败")

    # 保存
    save_credentials(client_id, client_secret, access_token, refresh_token)
