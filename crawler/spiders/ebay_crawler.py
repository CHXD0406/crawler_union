"""
eBay 商品爬虫
搜索 URL 格式: https://www.ebay.com/sch/i.html?_nkw=keyword&_sacat=0&_from=R40&_pgn=page
无需登录即可爬取搜索结果
"""
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup

# 搜索页基础 URL（参考: skirt 第7页 https://www.ebay.com/sch/i.html?_nkw=skirt&_sacat=0&_from=R40&_pgn=7）
EBAY_SEARCH_BASE = "https://www.ebay.com/sch/i.html"


def build_search_url(keyword, page=1):
    """构建 eBay 搜索 URL"""
    params = {
        "_nkw": keyword,
        "_sacat": 0,
        "_from": "R40",
        "_pgn": page,
    }
    return f"{EBAY_SEARCH_BASE}?{urlencode(params)}"


class EbayCrawler:
    """eBay 爬虫类"""

    def __init__(self, headless=True, save_html=False, browser_channel=None):
        """
        headless: 是否无头模式（云服务器必须 True）
        save_html: 是否保存 HTML
        browser_channel: 浏览器通道。None 使用 Chromium（适合 Linux 云服务器），"msedge" 使用 Edge（本地 Windows）
        """
        self.headless = headless
        self.save_html = save_html
        self.browser_channel = browser_channel
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def init_browser(self):
        """初始化浏览器（channel=None 时用 Chromium，适合云服务器；channel='msedge' 时用 Edge）"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
        launch_opts = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-software-rasterizer",
            ],
        }
        if self.browser_channel:
            launch_opts["channel"] = self.browser_channel
        self.browser = await self.playwright.chromium.launch(**launch_opts)
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        )
        self.page = await self.context.new_page()
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

    async def close(self):
        """关闭浏览器"""
        if self.page:
            try:
                await self.page.close()
            except:
                pass
        if self.context:
            try:
                await self.context.close()
            except:
                pass
        if self.browser:
            try:
                await self.browser.close()
            except:
                pass
        if getattr(self, "playwright", None):
            try:
                await self.playwright.stop()
            except:
                pass

    async def scroll_to_load(self, scroll_times=3):
        """滚动页面以加载动态内容"""
        for _ in range(scroll_times):
            await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(0.5)
        await self.page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)

    def extract_products(self, html_content, page_num, category):
        """
        从 eBay 搜索结果 HTML 中提取商品
        eBay 常见结构: ul.srp-results li.s-item, .s-item__title, .s-item__price, .s-item__link, .s-item__image
        输出: title, price, image, link, Category, Platform
        """
        soup = BeautifulSoup(html_content, "html.parser")
        products = []
        # 商品列表项: li.s-item
        containers = soup.select("li.s-item")
        if not containers:
            containers = soup.find_all("li", class_=re.compile(r"s-item", re.I))
        if not containers:
            # 备用: 包含 s-item__title 的父元素
            for elem in soup.select(".s-item__title"):
                parent = elem.find_parent("li")
                if parent and parent not in containers:
                    containers.append(parent)

        for idx, container in enumerate(containers, 1):
            try:
                # 跳过“Shop on eBay”等广告占位
                link_elem = container.select_one("a.s-item__link")
                if not link_elem:
                    link_elem = container.find("a", href=re.compile(r"ebay\.com/itm/"))
                href = (link_elem.get("href", "") or "").strip() if link_elem else ""
                if not href or "itm/" not in href:
                    continue

                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.ebay.com" + href
                href = href.replace("&amp;", "&")

                title_elem = container.select_one(".s-item__title")
                title = (title_elem.get_text(strip=True) or "").strip() if title_elem else ""
                if title == "Shop on eBay":
                    continue

                price_elem = container.select_one(".s-item__price")
                price = ""
                if price_elem:
                    price_text = price_elem.get_text(strip=True) or ""
                    price_match = re.search(r"[\d,]+\.?\d*", price_text.replace(",", ""))
                    if price_match:
                        price = price_match.group().replace(",", "")

                img_elem = container.select_one(".s-item__image img")
                if not img_elem:
                    img_elem = container.select_one(".s-item__img img")
                if not img_elem:
                    img_elem = container.find("img", src=True)
                image = ""
                if img_elem:
                    image = (
                        img_elem.get("src")
                        or img_elem.get("data-src")
                        or img_elem.get("data-imgurl")
                        or ""
                    )
                    if image and image.startswith("//"):
                        image = "https:" + image
                    elif image and image.startswith("/"):
                        image = "https://www.ebay.com" + image

                record = {
                    "title": title,
                    "price": price,
                    "image": image,
                    "link": href,
                    "Category": category,
                    "Platform": "ebay",
                }
                if title or href:
                    products.append(record)
            except Exception as e:
                continue

        return products


async def crawl_products_automated(
    keywords,
    num_pages_per_keyword,
    headless=False,
    save_html=False,
    output_dir="ebay_data",
    browser_channel=None,
):
    """
    按关键词列表爬取 eBay 搜索结果
    keywords: 关键词列表，如 ['skirt', 'dress']
    num_pages_per_keyword: 每个关键词爬取的页数
    browser_channel: None=Chromium（云服务器），"msedge"=Edge（本地）
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    crawler = EbayCrawler(
        headless=headless, save_html=save_html, browser_channel=browser_channel
    )
    all_products = []

    try:
        await crawler.init_browser()
        for kw_idx, keyword in enumerate(keywords, 1):
            print(f"\n{'='*60}")
            print(f"关键词 {kw_idx}/{len(keywords)}: {keyword}")
            print(f"{'='*60}")
            keyword_products = []
            for page in range(1, num_pages_per_keyword + 1):
                url = build_search_url(keyword, page)
                print(f"  第 {page}/{num_pages_per_keyword} 页: {url}")
                try:
                    await crawler.page.goto(
                        url, wait_until="domcontentloaded", timeout=60000
                    )
                    await asyncio.sleep(2)
                    await crawler.scroll_to_load(scroll_times=3)
                    html_content = await crawler.page.content()
                    if save_html:
                        safe_name = re.sub(r'[<>:"/\\|?*]', "_", keyword)[:50]
                        html_path = output_dir / f"{safe_name}_page_{page}.html"
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(html_content)
                    items = crawler.extract_products(html_content, page, keyword)
                    keyword_products.extend(items)
                    print(f"    提取 {len(items)} 条")
                except Exception as e:
                    print(f"    错误: {e}")
                await asyncio.sleep(1)
            # 按 link 去重
            seen = set()
            unique = []
            for p in keyword_products:
                link = (p.get("link") or "").strip()
                if link and link in seen:
                    continue
                if link:
                    seen.add(link)
                unique.append(p)
            if unique:
                all_products.extend(unique)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = re.sub(r'[<>:"/\\|?*]', "_", keyword)[:50]
                json_path = output_dir / f"{safe_name}_products_{ts}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(unique, f, ensure_ascii=False, indent=2)
                print(f"  已保存: {json_path.name}, 共 {len(unique)} 条")
    finally:
        await crawler.close()

    if all_products:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        all_path = output_dir / f"all_products_{ts}.json"
        with open(all_path, "w", encoding="utf-8") as f:
            json.dump(all_products, f, ensure_ascii=False, indent=2)
        print(f"\n全部保存: {all_path}, 共 {len(all_products)} 条")
    return all_products


def get_crawled_products(data_dir="ebay_data", check_html=True):
    """从数据目录中提取已爬取的关键词（对应商品名）"""
    data_path = Path(data_dir)
    if not data_path.exists():
        return set()
    crawled = set()
    for f in data_path.glob("*_products_*.json"):
        if f.name.startswith("all_products"):
            continue
        m = re.match(r"^(.+?)_products_\d{8}_\d{6}\.json$", f.name)
        if m:
            crawled.add(m.group(1))
    if check_html:
        for f in data_path.glob("*_page_*.html"):
            m = re.match(r"^(.+?)_page_\d+\.html$", f.name)
            if m:
                crawled.add(m.group(1))
    return crawled


def filter_products(products_list, crawled_products):
    """从列表中移除已爬取的关键词"""
    uncrawled = [p for p in products_list if p not in crawled_products]
    crawled = [p for p in products_list if p in crawled_products]
    return uncrawled, crawled


if __name__ == "__main__":
    script_dir = Path(__file__).parent
    data_dir = script_dir.parent / "ebay_data"
    if not data_dir.exists():
        data_dir = script_dir / "ebay_data"
    data_dir = str(data_dir)
    print("eBay 商品爬虫")
    print("=" * 60)
    print(f"数据目录: {data_dir}")
    keywords_list = ['Salwar Suit Sets', 'Dupattas', 'Half Sarees', 'Lehenga Cholis', 'Salwar Suit Sets', 'Sarees', 'Safari Suits', 'Salwar Suit Sets', 'Sherwanis', 'Anarkali Suits', 'Cholis', 'Dupattas', 'Lehenga Cholis', 'Maternity Churidar Bottoms', 'Maternity Kurtas & Kurtis', 'Maternity Salwar Bottoms', 'Maternity Salwar Suit Sets', 'Salwar Suit Sets', 'Sarees', 'Ghillie Shirts', 'Headwear', 'Kilt Pins & Brooches', 'Sock Flashes', 'Sporrans', 'Lederhosen', 'Trachten Hats', 'Trachten Neckerchiefs', 'Trachten Jackets', 'Trachten Shirts', 'Trachten Waistcoats', 'Dirndl Aprons', 'Dirndl Bras', 'Dirndl Dresses', 'Lederhosen', 'Trachten Cardigans', 'Traditional German Blouses', 'Serapes & Ponchos', 'Huipiles', 'Keffiyeh & Shemagh', 'Kufi Caps', 'Shalwar Kemeez', 'Thobes & Dishdasha', 'Abayas', 'Burqas', 'Hijabs', 'Modest Swimwear', 'Niqabs', 'Ridas', 'Cords', 'Hoods', 'Stoles', 'Tassel Charms', 'Tassels', 'Cap & Gown Sets', 'Gowns', 'Scrub Dresses', 'Folding Fans', 'Paddle Fans', 'Handbag Hangers', 'Handbag Organizers', 'Keyrings, Keychains & Charms', 'Cold Weather Scarves & Wraps', 'Wraps & Pashminas', 'Bridal Veils', 'Fascinators', 'Checkbook Covers', 'Active Sweatsuits', 'Insulated Shells', 'Jackets by Sport', 'Casual Jackets', 'Denim Jackets', 'Faux Fur', 'Fur', 'Quilted Lightweight Jackets', 'Anoraks', 'Trench Coats', 'Pea Coats', 'Jumpsuits', 'Bra Extenders', 'Breast Lift Tape', 'Breast Petals', 'Lingerie Bags', 'Lingerie Tape', 'Pads & Enhancers', 'Straps', 'Adhesive Bras', 'Everyday Bras', 'Mastectomy Bras', 'Minimizers', 'Maternity Bras', 'Nursing Bras', 'Bustiers', 'Corsets', 'Camisoles & Tanks', 'Tangas', 'Control Panties', 'Full Slips', 'Half Slips', 'Thigh Slimmers', 'Full Slips', 'Half Slips', 'Pant Liner Slips', 'Onesies', 'Sheers', 'Blazers', 'Separates', 'Dress Suits', 'Pantsuits', 'Skirt Suits', 'Tunics', 'Clutches', 'Evening Bags', 'Crossbody Bags', 'Fashion Backpacks', 'Hobo Bags', 'Satchels', 'Wristlets', 'Body Chains', 'Italian Style', 'Snake', 'Bead', 'Clasp', 'Italian Style', 'Strand', 'Stretch', 'Wrap', 'Clip-Ons', 'Cuffs & Wraps', 'Earring Jackets', 'Jewelry Sets', 'Chokers', 'Pearl Strands', 'Pendant Necklaces', 'Strands', 'Torque', 'Y-Necklaces', 'Pendant Enhancers', 'Pendants Only', 'Bands', 'Semi-Mounted', 'Stacking', 'Statement', 'Anniversary Rings', 'Bridal Sets', 'Engagement Rings', 'Eternity Rings', 'Promise Rings', 'Ring Enhancers', 'Wedding Bands', 'Ankle & Bootie', 'Knee-High', 'Mid-Calf', 'Over-the-Knee', 'Flats', 'Flip-Flops', 'Gladiator Sandals', 'Heeled Sandals', 'Outdoor', 'Platforms', 'Wedges', 'Slides', 'Active Pants', 'Active Shirts & Tees', 'Coats, Jackets & Vests', 'Abdominal Support', 'Belly Bands', 'Maternity Bras', 'Nursing Bras', 'Sleepshirts', 'Henleys', 'Knits & Tees', 'Tunics', 'Sleepshirts', 'Henleys', 'Tunics', 'Scrub Dresses']
    num_pages = 5
    crawled = get_crawled_products(data_dir, check_html=True)
    keywords_list, _ = filter_products(keywords_list, crawled)
    if keywords_list:
        asyncio.run(
            crawl_products_automated(
                keywords=keywords_list,
                num_pages_per_keyword=num_pages,
                headless=False,
                save_html=True,
                output_dir=data_dir,
            )
        )
    else:
        print("当前没有待爬取的关键词")
