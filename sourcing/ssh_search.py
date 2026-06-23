"""SSH to VPS and search 1688"""
import paramiko, urllib.parse, time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect('89.117.22.200', username='root', password='QQ33945551', timeout=15)
except Exception as e:
    print(f"SSH连接失败: {e}")
    exit(1)

JINA_KEY = "jina_f6224099403c40a7bd6f65493030f84e8oPdHTuFRYLLiXr7ODjYPjxstitZ"

products = [
    ("智能猫砂盆", "智能猫砂盆 自动清洁 2025新款"),
    ("三合一充电站", "三合一无线充电器 折叠 快充"),
    ("瑜伽紧身裤", "高腰瑜伽裤 健身裤 女 2025"),
    ("空气炸锅", "空气炸锅 家用 4.5L 2025"),
    ("高压洗车枪", "高压洗车水枪 锂电池 无线"),
    ("LED台灯", "LED台灯 护眼 触控调光"),
    ("蓝牙睡眠耳机", "蓝牙睡眠耳机 头戴式 音乐"),
]

for name, kw in products:
    encoded = urllib.parse.quote(kw)
    cmd = (
        f'curl -s --max-time 15 '
        f'"https://r.jina.ai/https://s.1688.com/selloffer/offer_search.htm?keywords={encoded}" '
        f'-H "Authorization: Bearer *** '
        f'2>&1 | python3 -c "'
        f'import sys,re; '
        f'html=sys.stdin.read(); '
        f'links=re.findall(r\\\"href=\\\\\\\"/offer/(\\\\d+)\\\\\\\\.html\\\\\\\"\\\",html); '
        f'titles=re.findall(r\\\"title=\\\\\\\"([^\\\\\\\"]+)\\\\\\\"\\\",html); '
        f'for i in range(min(3,len(links))): print(f\\\\\\\"  ¥ \\\\\\\${titles[i].split()[-1] if titles else \'?\'} | detail.1688.com/offer/\\\\\${links[i]}\\\\\\\\.html\\\\\\\") '
        f'"'
    )
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    result = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode()
    print(f"=== {name} ===")
    if result.strip():
        print(result[:300])
    else:
        print(f"  无结果 (err: {err[:100]})")
    print()

client.close()
