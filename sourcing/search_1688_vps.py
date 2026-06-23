"""
1688 采购清单 — 使用 VPS 通过 SSH 带密码搜索
"""
import subprocess, json, urllib.parse, time

HOST = "root@89.117.22.200"
PASSWORD = "QQ33945551"
JINA_KEY = "jina_f6224099403c40a7bd6f65493030f84e8oPdHTuFRYLLiXr7ODjYPjxstitZ"

PRODUCTS = [
    "智能猫砂盆 自动清洁 2025新款",
    "三合一无线充电器 折叠 快充",
    "高腰瑜伽裤 健身裤 女 2025",
    "空气炸锅 家用 4.5L 2025新款",
    "高压洗车水枪 锂电池 无线 2025",
    "LED台灯 护眼 触控调光 2025",
    "蓝牙睡眠耳机 头戴式 音乐 2025",
]

script = """#!/bin/bash
JINA_KEY="%s"
for kw in "%s"; do
  ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$kw'''))" 2>/dev/null)
  URL="https://r.jina.ai/https://s.1688.com/selloffer/offer_search.htm?keywords=$ENCODED"
  echo "=== $kw ==="
  curl -s --max-time 20 "$URL" -H "Authorization: Bearer *** 2>&1 | grep -oP 'href=\"/offer/[0-9]+\.html[^\"]*\"|￥[0-9]+\.[0-9]+|title=\"[^\"]+\"' | head -20
  echo
done
echo "DONE"
""" % (JINA_KEY, '" "'.join(PRODUCTS))

# 写入临时文件
with open("/tmp/1688_vps.sh", "w") as f:
    f.write(script)

# 通过 expect 方式带密码执行
cmd = f"sshpass -p '{PASSWORD}' ssh -o ConnectTimeout=15 {HOST} 'bash -s' < /tmp/1688_vps.sh"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
print("STDOUT:", result.stdout[:3000])
print("STDERR:", result.stderr[:500])
