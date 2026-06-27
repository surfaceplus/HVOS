"""
Agent Reach 深度选品情报 × World Model 评分
"""
import sys, os, json, subprocess, concurrent.futures, time

PYTHON = r"C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
AGENT_PKG = r"D:\PythonPackages"
os.environ["PYTHONPATH"] = AGENT_PKG
sys.path.insert(0, AGENT_PKG)

from agent_reach.channels.v2ex import V2EXChannel
from agent_reach.channels.bilibili import BilibiliChannel
from agent_reach.channels.github import GitHubChannel

def jina_read(url):
    try:
        cmd = [PYTHON, "-c",
               f"import urllib.request; r=urllib.request.urlopen('{url}',timeout=20); print(r.read().decode('utf-8','replace')[:3000])"]
        r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        return r2.stdout[:3000] if r2.returncode == 0 else ""
    except:
        return ""

def v2ex_topic(id_or_node, node_search=None):
    try:
        v = V2EXChannel()
        if node_search:
            return v.get_node_topics(node_search, limit=10)
        return v.get_topic(id_or_node)
    except:
        return {}

def search_all(keyword):
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        v2ex_f = ex.submit(v2ex_topic, keyword)
        bilibili_f = ex.submit(lambda k=keyword: BilibiliChannel().search(k, max_results=8), keyword)
        web_f = ex.submit(jina_read, f"https://r.jina.ai/ai/search?q={keyword}+trending+product&num=8")
        time.sleep(0.1)
    results["v2ex"] = v2ex_f.result()[:10]
    results["bilibili"] = bilibili_f.result()[:10]
    results["web"] = web_f.result()[:500]
    return results

def process_topic(id_or_node_or_node_search):
    print(f"\n  研究: {id_or_node_or_node_search}")
    data = search_all(id_or_node_or_node_search)
    v2 = data["v2ex"]
    bili = data["bilibili"]
    web = data["web"]
    print(f"  V2EX: {len(v2)} 条 | B站: {len(bili)} | Web: {len(web)} 字符")
    titles_v2 = [t.get("title","") for t in v2]
    titles_bili = [b.get("title","") for b in bili]
    return {
        "topic": id_or_node_or_node_search,
        "v2ex": titles_v2,
        "bilibili": titles_bili,
        "web_snippet": web[:200],
        "signals": len(v2) * 3 + len(bili) * 2
    }

def main():
    TOPICS = [
        "宠物降温装备",
        "登山包 户外",
        "创意礼品",
        "智能小家电",
        "个性化礼品",
        "厨房神器",
    ]
    print("=== Agent Reach 深度选品情报 × World Model ===\n")
    topics_results = []
    for t in TOPICS:
        r = process_topic(t)
        topics_results.append(r)
        time.sleep(0.5)

    topics_results.sort(key=lambda x: x["signals"], reverse=True)
    print("\n=== 信号强度排序 ===")
    for r in topics_results[:5]:
        print(f"\n[{r['signals']}信号] {r['topic']}")
        if r["v2ex"]:
            print(f"  V2EX: {r['v2ex'][0][:80]}")
        if r["bilibili"]:
            print(f"  B站: {r['bilibili'][0][:80]}")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ar_deep_signals.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"topics": topics_results}, f, ensure_ascii=False, indent=2)
    print(f"\n深度报告: {path}")
    return topics_results

if __name__ == "__main__":
    main()
