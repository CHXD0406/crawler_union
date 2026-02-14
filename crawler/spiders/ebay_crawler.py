import asyncio
import json
import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# 适配导入路径：尝试从同级或父级导入 crawler_base
try:
    from crawler_base import BaseCrawler, MultiCrawlerManager
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from crawler.crawler_base import BaseCrawler, MultiCrawlerManager

# eBay 基础配置
EBAY_SEARCH_BASE = "https://www.ebay.com/sch/i.html"

class EbayCrawler(BaseCrawler):
    def extract_products(self, html_content, keyword, page_num):
        """
        eBay 专属 HTML 解析逻辑
        ✅ 关键点：将 page_num 写入每条数据，用于精准断点续传
        """
        soup = BeautifulSoup(html_content, "html.parser")
        products = []
        
        # 容器选择器策略
        containers = soup.select("li.s-item")
        if not containers:
            containers = soup.find_all("li", class_=re.compile(r"s-item", re.I))
        # 兜底策略
        if not containers:
            for elem in soup.select(".s-item__title"):
                parent = elem.find_parent("li")
                if parent and parent not in containers:
                    containers.append(parent)

        print(f"🔍 [Port {self.port}] 解析页面 (Page {page_num})，找到容器: {len(containers)} 个")

        for container in containers:
            try:
                # 1. 提取链接
                link_elem = container.select_one("a.s-item__link")
                if not link_elem:
                    link_elem = container.find("a", href=re.compile(r"ebay\.com/itm/"))
                href = (link_elem.get("href", "") or "").strip() if link_elem else ""
                
                # 过滤无效链接
                if not href or "itm/" not in href: continue

                # 格式化链接
                if href.startswith("//"): href = "https:" + href
                elif href.startswith("/"): href = "https://www.ebay.com" + href
                href = href.replace("&amp;", "&")

                # 2. 提取标题
                title_elem = container.select_one(".s-item__title")
                title = (title_elem.get_text(strip=True) or "").strip() if title_elem else ""
                
                # 过滤广告
                if title == "Shop on eBay": continue

                # 3. 提取价格
                price_elem = container.select_one(".s-item__price")
                price = ""
                if price_elem:
                    price_text = price_elem.get_text(strip=True) or ""
                    price_match = re.search(r"[\d,]+\.?\d*", price_text.replace(",", ""))
                    if price_match:
                        price = price_match.group().replace(",", "")

                # 4. 提取图片
                img_elem = container.select_one(".s-item__image img")
                if not img_elem: img_elem = container.select_one(".s-item__img img")
                image = ""
                if img_elem:
                    image = (img_elem.get("src") or 
                             img_elem.get("data-src") or 
                             img_elem.get("data-imgurl") or "")
                    if image.startswith("//"): image = "https:" + image

                # 组装数据
                record = {
                    "title": title,
                    "price": price,
                    "image": image,
                    "link": href,
                    "keyword": keyword, 
                    "platform": "ebay",
                    "page": page_num  # ✅ 必须包含 page 字段
                }
                
                if title or href:
                    products.append(record)

            except Exception:
                continue
                
        return products

    async def crawl(self, tasks, max_count, output_dir):
        """
        eBay 爬取主循环
        tasks 格式: [(keyword, start_page), ...]
        start_page: 上次爬取的最大页码
        """
        # 简单排序任务
        tasks.sort(key=lambda x: x[1])

        try:
            # 1. 启动浏览器
            await self.init_browser()
            if not self.page: return

            # 2. 遍历任务
            for keyword, start_page in tasks:
                # 这里的 max_count 指的是目标商品条数
                print(f"\n{'='*40}\n[Port {self.port}] 爬取: {keyword} (上次断点: Page {start_page})\n{'='*40}")
                
                current_count = 0 
                keyword_products = []
                
                # ✅ 关键逻辑：直接从断点页的下一页开始，不使用 item count 估算
                page_num = start_page + 1
                
                # 循环条件：直到抓够数量或无数据
                while current_count < max_count:
                    # 构建 URL
                    encoded_kw = urllib.parse.quote(keyword)
                    url = f"{EBAY_SEARCH_BASE}?_nkw={encoded_kw}&_sacat=0&_from=R40&_pgn={page_num}"
                    
                    print(f"  🌍 [Port {self.port}] 访问第 {page_num} 页... (本轮已抓: {current_count})")
                    
                    try:
                        await self.page.goto(url)
                        try: await self.page.wait_for_load_state('domcontentloaded', timeout=15000)
                        except: pass
                        
                        # 滚动触发懒加载
                        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                        await asyncio.sleep(1)
                        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(2)

                        # 提取数据
                        html = await self.page.content()
                        items = self.extract_products(html, keyword, page_num)
                        
                        if not items:
                            print(f"  ⚠️ [Port {self.port}] 第 {page_num} 页无数据，结束当前关键词。")
                            break
                        
                        keyword_products.extend(items)
                        current_count += len(items)
                        print(f"  ✓ [Port {self.port}] 提取 {len(items)} 条")
                        
                        # 翻页
                        page_num += 1
                        await asyncio.sleep(2) # 礼貌等待

                    except Exception as e:
                        print(f"  ❌ [Port {self.port}] 页面出错: {e}")
                        break
                    
                    # 防止无限翻页的安全阈值 (可选)
                    if page_num > 100: break

                # 3. 保存数据
                if keyword_products:
                    # 传入 start_page 作为断点标识，_save_data 会处理合并
                    self._save_data(keyword, keyword_products, start_page, output_dir)
                else:
                    print(f"⚠️ [Port {self.port}] {keyword} 未提取到新数据")

        except Exception as e:
            print(f"❌ [Port {self.port}] 进程错误: {e}")
        finally:
            await self.close()

    def _save_data(self, product_name, new_data, start_index, output_dir):
        """
        通用保存逻辑 (符合 README 标准)
        支持根据 page 字段自动判断翻页逻辑并合并数据
        """
        final_data = new_data
        files_to_remove = []
        
        # 文件名清洗
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", product_name)[:50]
        
        if start_index > 0:
            print(f"\n🔄 [Port {self.port}] 检测到续传 (Start: {start_index})，合并旧文件...")
            try:
                from pathlib import Path
                data_path = Path(output_dir)
                candidate_files = []
                for f in data_path.glob(f'{safe_name}_products_*.json'):
                    candidate_files.append(f)
                candidate_files.sort(key=lambda x: x.name, reverse=True)

                if candidate_files:
                    latest_json = candidate_files[0]
                    with open(latest_json, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)

                    if isinstance(old_data, list) and len(old_data) > 0:
                        # 核心检测：是翻页逻辑(eBay) 还是 滚动逻辑(Depop)
                        is_page_logic = 'page' in old_data[0]

                        if is_page_logic:
                            # 翻页逻辑：直接追加数据
                            print(f"    📄 [翻页模式] 上次进度 Page {start_index}，追加数据...")
                        else:
                            # 滚动逻辑：检查长度
                            if len(old_data) != start_index:
                                print(f"    ⚠️ 长度校验不一致: 旧({len(old_data)}) vs 标记({start_index})")
                        
                        final_data = old_data + new_data
                        print(f"    ➕ 合并成功: 旧({len(old_data)}) + 新({len(new_data)}) = 总({len(final_data)})")
                        
                        files_to_remove.append(latest_json)
                        old_csv = latest_json.with_suffix('.csv')
                        if old_csv.exists(): files_to_remove.append(old_csv)
            except Exception as e:
                print(f"    ❌ 合并失败: {e}")

        # 持久化
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if not os.path.exists(output_dir): os.makedirs(output_dir)
        
        json_path = os.path.join(output_dir, f"{safe_name}_products_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"  💾 [Port {self.port}] JSON: {os.path.basename(json_path)}")
        
        # CSV 保存
        import csv
        if final_data:
            csv_path = os.path.join(output_dir, f"{safe_name}_products_{timestamp}.csv")
            try:
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    keys = final_data[0].keys()
                    writer = csv.DictWriter(f, fieldnames=keys)
                    writer.writeheader()
                    writer.writerows(final_data)
            except: pass

        # 清理
        if files_to_remove:
            for f in files_to_remove:
                try: os.remove(f)
                except: pass

# ==================== 标准任务获取逻辑 ====================
def get_tasks_from_file(name_file, max_count, data_dir):
    """
    符合 README 标准的任务初始化函数
    自动识别 page 断点或 index 断点
    """
    import json
    from pathlib import Path

    try:
        if not os.path.exists(name_file):
            print(f"❌ 任务文件不存在: {name_file}")
            return []
        with open(name_file, 'r', encoding='utf-8') as f:
            names = json.load(f)
        product_names = list(set(names))
    except Exception as e:
        print(f"❌ 读取任务失败: {e}")
        return []

    tasks_progress = {name: 0 for name in product_names}
    data_path = Path(data_dir)

    if data_path.exists():
        print(f"🔍 扫描 {data_dir} 断点...")
        for json_file in data_path.glob('*_products_*.json'):
            if json_file.name.startswith('all_products'): continue
            
            # 文件名匹配
            match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
            if not match: continue
            
            # 注意：文件名是 safe_name，需要简单匹配回原名 (此处简化处理)
            # 实际项目中建议在文件名中保留更精确的 ID 或哈希，或者在这里做模糊匹配
            p_safe_name = match.group(1)
            
            # 反向查找对应的原始 task name
            target_task = None
            for name in product_names:
                if re.sub(r'[<>:"/\\|?*]', "_", name)[:50] == p_safe_name:
                    target_task = name
                    break
            
            if target_task and target_task in tasks_progress:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data and isinstance(data, list):
                        last_item = data[-1]
                        # 优先取 page，没有则取 index
                        current = int(last_item.get('page', 0))
                        if not current:
                            current = int(last_item.get('index', len(data)))
                        
                        if current > tasks_progress[target_task]:
                            tasks_progress[target_task] = current
                except: pass

    final_tasks = []
    for name, progress in tasks_progress.items():
        # eBay 的 max_count 是条数，progress 是页数。
        # 这里只要 progress > 0 就打印恢复信息，具体是否爬完由 crawl 内部 current_count 判断
        if progress > 0:
            print(f"  🔄 恢复任务: {name} (从 Page {progress} 继续)")
        final_tasks.append((name, progress))

    return sorted(final_tasks, key=lambda x: x[0])

# ==================== 主入口 ====================
if __name__ == "__main__":
    print("eBay 爬虫 (标准版)")
    print("="*60)

    WORKER_COUNT = 2      # eBay 建议低并发
    BASE_PORT = 9333      # 独立端口段
    MAX_CRAWL = 100       # 目标抓取条数
    OUTPUT_DIR = 'ebay_data'
    TASK_FILE = 'clothing_leaf_names.json'

    all_tasks = get_tasks_from_file(TASK_FILE, MAX_CRAWL, OUTPUT_DIR)
    
    if all_tasks:
        print(f"📦 任务数: {len(all_tasks)}")
        manager = MultiCrawlerManager(
            crawler_class=EbayCrawler, 
            base_port=BASE_PORT, 
            workers=WORKER_COUNT
        )
        try:
            asyncio.run(manager.run(all_tasks, MAX_CRAWL, OUTPUT_DIR))
        except KeyboardInterrupt:
            print("🛑 停止")
    else:
        print("🎉 无任务")
