"""
Amazon New Releases Scanner
数据源：Amazon New Releases 页面爬虫
采样频率：每日
覆盖维度：各类目 New Releases 榜单

注意：Amazon 有反爬机制，实际使用需要：
  方案 A：Selenium/Playwright 模拟浏览器
  方案 B：RapidAPI Amazon Scraper
  方案 C：先跑通 Reddit+Google Trends 验证，再接 Amazon

依赖：
    pip install requests beautifulsoup4
"""

import os
import re
import time
import json
from datetime import datetime
from typing import Optional, List

try:
    import requests
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


class AmazonNewReleasesScanner:
    """
    Amazon New Releases 榜单扫描器

    核心逻辑：
    1. 抓取目标类目的 New Releases 榜单（前 50 名）
    2. 识别新进入者（之前未在 KG 中记录的品牌）
    3. 计算新品的 rank 变化趋势

    信号类型：
      - New Entrant：某品牌首次出现在 New Releases
      - Rank Climber：新品在榜单位置快速上升
      - Category Shift：某个子品类新品占比异常高
    """

    NEW_RELEASES_CATEGORIES = {
        "kitchen": "https://www.amazon.com/gp/new-releases/kitchen/",
        "gift": "https://www.amazon.com/gp/new-releases/gift-cards/",
        "pet": "https://www.amazon.com/gp/new-releases/pet-supplies/",
        "beauty": "https://www.amazon.com/gp/new-releases/beauty/",
        "home": "https://www.amazon.com/gp/new-releases/home-garden/",
        "outdoor": "https://www.amazon.com/gp/new-releases/sports/",
        "toys": "https://www.amazon.com/gp/new-releases/toys/",
        "electronics": "https://www.amazon.com/gp/new-releases/electronics/",
    }

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    def __init__(self, proxy: str = None):
        """
        Args:
            proxy: HTTP 代理（可选，Amazon 有反爬，建议配置代理池）
        """
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.proxy = proxy or os.getenv("AMAZON_PROXY")
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

    def _fetch_page(self, url: str, timeout: int = 15) -> Optional[str]:
        """获取页面 HTML"""
        try:
            resp = self.session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 503:
                print(f"[AmazonScanner] 503 for {url} - likely blocked")
            else:
                print(f"[AmazonScanner] HTTP {resp.status_code} for {url}")
            return None
        except Exception as e:
            print(f"[AmazonScanner] Fetch error for {url}: {e}")
            return None

    def _parse_new_releases(self, html: str, category: str) -> List[dict]:
        """
        解析 New Releases HTML，提取产品列表

        Amazon New Releases 页面结构：
        <div class="zg-item-immersion">
          <span class="zg-badge-text">#1</span>
          <div class="p13n-sc-truncated">Product Title</div>
          ...
        </div>
        """
        if not BS4_AVAILABLE:
            print("[AmazonScanner] beautifulsoup4 not installed. Run: pip install beautifulsoup4")
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        products = []

        # 方法1：尝试找 zg-item-immersion 列表
        items = soup.select('div.zg-item-immersion')

        if not items:
            # 方法2：尝试找 li 列表
            items = soup.select('li.zg-item-immersion')

        if not items:
            # 方法3：通用的 rank item
            items = soup.select('[class*="zg-item"]')

        for item in items[:50]:  # 取前50
            try:
                # 排名
                rank_elem = item.select_one('[class*="zg-badge"]')
                rank_text = rank_elem.get_text(strip=True) if rank_elem else ""
                rank = int(re.sub(r'[^\d]', '', rank_text)) if rank_text else 0

                # 标题
                title_elem = item.select_one('[class*="p13n-sc-truncated"]') or \
                            item.select_one('a[class*="a-size"]')
                title = title_elem.get_text(strip=True) if title_elem else ""

                # 品牌（从 URL 或 Title 推断）
                brand_elem = item.select_one('[class*="a-size-small"]') or \
                            item.select_one('[class*="brand"]')
                brand = brand_elem.get_text(strip=True) if brand_elem else ""

                if not brand and title:
                    # 从标题中提取品牌（通常是第一个单词）
                    parts = title.split()
                    if parts:
                        brand = parts[0]

                # 评分
                rating_elem = item.select_one('[class*="a-icon-star"]')
                rating_text = rating_elem.get_text(strip=True) if rating_elem else ""
                rating_match = re.search(r'([\d.]+)', rating_text)
                rating = float(rating_match.group(1)) if rating_match else 0.0

                # 评论数
                reviews_elem = item.select_one('[class*="a-size-small"]')
                reviews_text = reviews_elem.get_text(strip=True) if reviews_elem else ""
                reviews_match = re.search(r'([\d,]+)', reviews_text.replace(',', ''))
                reviews = int(reviews_match.group(1).replace(',', '')) if reviews_match else 0

                if title:
                    products.append({
                        "rank": rank,
                        "title": title[:80],
                        "brand": brand,
                        "rating": rating,
                        "reviews": reviews,
                        "category": category,
                        "source": "amazon_new_releases"
                    })
            except Exception:
                continue

        return products

    def scan_category(self, category: str) -> dict:
        """
        扫描单个品类的 New Releases

        Returns:
            {
                "category": "kitchen",
                "url": "...",
                "products_found": 45,
                "new_brands": [...],
                "avg_rating": 4.2,
                "captured_at": "..."
            }
        """
        url = self.NEW_RELEASES_CATEGORIES.get(category)
        if not url:
            return {"error": f"Category '{category}' not found", "category": category}

        html = self._fetch_page(url)
        if not html:
            return {"error": "Failed to fetch page", "category": category}

        products = self._parse_new_releases(html, category)

        # 分析新品牌
        brands = [p["brand"] for p in products if p["brand"]]
        brand_counts = {}
        for b in brands:
            brand_counts[b] = brand_counts.get(b, 0) + 1

        # 评分分析
        ratings = [p["rating"] for p in products if p["rating"] > 0]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        return {
            "category": category,
            "url": url,
            "products_found": len(products),
            "products": products[:20],  # 最多返回20条
            "brand_counts": dict(sorted(brand_counts.items(),
                                        key=lambda x: x[1], reverse=True)[:10]),
            "new_brands": list(set(brands)),  # 去重品牌列表
            "avg_rating": round(avg_rating, 1),
            "captured_at": datetime.now().isoformat()
        }

    def batch_scan(self, categories: List[str] = None) -> List[dict]:
        """
        批量扫描所有品类

        Returns:
            [
                {"category": "kitchen", "products_found": 45, "new_brands": [...], ...},
                {"category": "gift", ...},
                ...
            ]
        """
        categories = categories or list(self.NEW_RELEASES_CATEGORIES.keys())
        results = []

        for cat in categories:
            result = self.scan_category(cat)
            results.append(result)
            time.sleep(2)  # 避免触发反爬

        return results

    def detect_new_entrants(self, category: str, known_brands: set) -> List[dict]:
        """
        检测 New Releases 中的新进入者

        Args:
            category: 品类
            known_brands: 已知的品牌集合（从 KG 中查询）

        Returns:
            [{"brand": "XXX", "product": "YYY", "rank": 3, "is_new": True}, ...]
        """
        result = self.scan_category(category)
        if "error" in result:
            return []

        new_entrants = []
        for p in result.get("products", []):
            if p["brand"] and p["brand"] not in known_brands:
                new_entrants.append({
                    "brand": p["brand"],
                    "product": p["title"],
                    "rank": p["rank"],
                    "rating": p["rating"],
                    "reviews": p["reviews"],
                    "is_new": True
                })

        return new_entrants


if __name__ == "__main__":
    scanner = AmazonNewReleasesScanner()

    print("[AmazonScanner] Testing kitchen category...")
    result = scanner.scan_category("kitchen")

    if "error" in result:
        print(f"Error: {result['error']}")
    else:
        print(f"Found {result['products_found']} products")
        print(f"Avg rating: {result['avg_rating']}")
        print(f"Top brands: {list(result['brand_counts'].keys())[:5]}")
