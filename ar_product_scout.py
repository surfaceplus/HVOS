"""
HVOS x Agent Reach 多渠道选品侦察
"""
import sys, os, json, time, subprocess

PYTHON = r"C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
AGENT_REACH_PKG = r"D:\PythonPackages"
os.environ["PYTHONPATH"] = AGENT_REACH_PKG
sys.path.insert(0, AGENT_REACH_PKG)

from agent_reach.channels.v2ex import V2EXChannel
from agent_reach.channels.bilibili import BilibiliChannel

def jina_read(url):
    try:
        cmd = [PYTHON, "-c",
               f"import urllib.request; r=urllib.request.urlopen('{url}',timeout=15); print(r.read().decode('utf-8','replace')[:2000])"]
        r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r2.stdout[:2000] if r2.returncode == 0 else ""
    except Exception as e:
        return str(e)[:200]

def v2ex_search(keyword):
    try:
        v = V2EXChannel()
        return v.get_node_topics(keyword, limit=10)
    except Exception as e:
        return []

def v2ex_hot():
    try:
        v = V2EXChannel()
        return v.get_hot_topics(limit=20)
    except Exception as e:
        return []

def bilibili_search(keyword):
    try:
        b = BilibiliChannel()
        return b.search(keyword, max_results=10)
    except Exception as e:
        return []

def score_results(v2_list, bili_list, web_text):
    score = 0
    if v2_list:
        score += len(v2_list) * 3
    if bili_list:
        score += len(bili_list) * 2
    if web_text and len(web_text) > 100:
        score += 5
    return score

QUERIES = [
    ("礼品", "礼物"),
    ("厨房", "kitchen gadget"),
    ("宠物", "pet"),
    ("户外", "outdoor"),
    ("家居", "home decor"),
    ("个护", "beauty"),
    ("3C配件", "3C accessory"),
    ("节庆", "holiday"),
    ("创意", "unique gift"),
    ("科技", "tech gadget"),
]

def main():
    print("=== HVOS x Agent Reach 选品侦察 ===\n")
    all_results = []
    for kw, query in QUERIES:
        print(f"[{kw}]...", end=" ", flush=True)
        v2 = v2ex_search(query)
        bili = bilibili_search(query)
        web = jina_read(f"https://r.jina.ai/ai/search?q={query}+trending+product&num=5")
        score = score_results(v2, bili, web)
        titles_v2 = [t.get("title","")[:70] for t in v2[:3]]
        titles_bili = [t.get("title","")[:70] for t in bili[:3]]
        all_results.append({
            "keyword": kw,
            "query": query,
            "score": score,
            "v2ex": titles_v2,
            "bilibili": titles_bili,
            "web": web[:150],
        })
        print(f"分:{score} V2EX:{len(v2)} B站:{len(bili)}")
        time.sleep(0.5)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    print("\n=== TOP 5 选品关键词 ===")
    for i, r in enumerate(all_results[:5], 1):
        print(f"\n{i}. [{r['keyword']}] 分数:{r['score']}")
        if r["v2ex"]:
            print(f"   V2EX: {r['v2ex'][0]}")
        if r["bilibili"]:
            print(f"   B站: {r['bilibili'][0]}")

    path = r"C:\Users\Administrator\AppData\Local\hermes\hvos\ar_trending_signals.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"signals": all_results, "top5": all_results[:5]}, f, ensure_ascii=False, indent=2)
    print(f"\n报告: {path}")
    return all_results

if __name__ == "__main__":
    main()
