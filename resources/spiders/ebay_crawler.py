import asyncio
import json
import re
import argparse
import urllib
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import quote

## ==================== 修复后的导入逻辑 ====================
import sys
import os

# 1. 优先尝试直接导入 (服务器平铺模式 / PYTHONPATH 已设置模式)
try:
    from crawler_base import BaseCrawler, MultiCrawlerManager
except ImportError:
    # 2. 尝试从资源包导入 (本地打包 EXE 模式)
    try:
        from resources.spiders.crawler_base import BaseCrawler, MultiCrawlerManager
    except ImportError:
        # 3. 本地开发模式 (相对路径兜底)
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            from crawler.spiders.crawler_base import BaseCrawler, MultiCrawlerManager
        except ImportError:
            # 最后的倔强：添加当前目录
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            from crawler_base import BaseCrawler, MultiCrawlerManager
# =========================================================

# 尝试导入基类
try:
    from resources.spiders.crawler_base import BaseCrawler, MultiCrawlerManager
except ImportError:
    import sys

    # 如果在子目录，尝试添加父目录到路径
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from resources.spiders.crawler_base import BaseCrawler, MultiCrawlerManager

# eBay 基础配置
EBAY_SEARCH_BASE = "https://www.ebay.com/sch/i.html"


class EbayCrawler(BaseCrawler):
    def extract_products(self, html_content, keyword, page_num):
        """
        eBay 专属 HTML 解析逻辑
        """
        soup = BeautifulSoup(html_content, "html.parser")
        products = []

        # 1. 定位容器
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
                # 2. 提取链接
                link_elem = container.select_one("a.s-item__link")
                if not link_elem:
                    link_elem = container.find("a", href=re.compile(r"ebay\.com/itm/"))

                href = (link_elem.get("href", "") or "").strip() if link_elem else ""

                # 过滤无效链接
                if not href or "itm/" not in href: continue

                # 格式化链接
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.ebay.com" + href
                href = href.replace("&amp;", "&")

                # 3. 提取标题
                title_elem = container.select_one(".s-item__title")
                title = (title_elem.get_text(strip=True) or "").strip() if title_elem else ""

                # 过滤广告
                if title == "Shop on eBay": continue

                # 4. 提取价格
                price_elem = container.select_one(".s-item__price")
                price = ""
                if price_elem:
                    price_text = price_elem.get_text(strip=True) or ""
                    # 简单清洗价格
                    price_match = re.search(r"[\d,]+\.?\d*", price_text.replace(",", ""))
                    if price_match:
                        price = price_match.group().replace(",", "")

                # 5. 提取图片
                img_elem = container.select_one(".s-item__image img")
                if not img_elem: img_elem = container.select_one(".s-item__img img")
                image = ""
                if img_elem:
                    image = (img_elem.get("src") or
                             img_elem.get("data-src") or
                             img_elem.get("data-imgurl") or "")
                    if image.startswith("//"): image = "https:" + image

                # 6. 组装数据 (包含 page 字段)
                record = {
                    "title": title,
                    "price": price,
                    "image": image,
                    "link": href,
                    "keyword": keyword,
                    "platform": "ebay",
                    "page": page_num  # ✅ 关键：写入页码用于断点
                }

                if title or href:
                    products.append(record)

            except Exception:
                continue

        return products

    async def crawl(self, tasks, max_count, output_dir):
        """
        eBay 主爬取循环 (翻页逻辑)
        """
        # 按进度排序
        tasks.sort(key=lambda x: x[1])

        try:
            # 1. 启动浏览器 (使用 BaseCrawler 的方法)
            await self.init_browser()
            if not self.page: return

            # 2. 遍历任务
            for keyword, start_page in tasks:
                print(f"\n{'=' * 40}\n[Port {self.port}] 爬取: {keyword} (上次断点: Page {start_page})\n{'=' * 40}")

                current_count = 0
                keyword_products = []

                # ✅ 翻页逻辑：直接从下一页开始
                page_num = start_page + 1

                # 循环直到达到数量
                while current_count < max_count:
                    # 构建搜索 URL
                    encoded_kw = urllib.parse.quote(keyword)
                    url = f"{EBAY_SEARCH_BASE}?_nkw={encoded_kw}&_sacat=0&_from=R40&_pgn={page_num}"

                    print(f"  🌍 [Port {self.port}] 访问第 {page_num} 页... (本轮已抓: {current_count})")

                    try:
                        await self.page.goto(url)
                        try:
                            await self.page.wait_for_load_state('domcontentloaded', timeout=15000)
                        except:
                            pass

                        # 简单滚动触发懒加载
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
                        print(f"  ✓ [Port {self.port}] 本页提取 {len(items)} 条")

                        # 准备下一页
                        page_num += 1
                        await asyncio.sleep(2)

                    except Exception as e:
                        print(f"  ❌ [Port {self.port}] 页面出错: {e}")
                        break

                    # 安全阈值，防止无限翻页
                    if page_num > 50: break

                # 3. 保存数据 (start_page 用于合并)
                if keyword_products:
                    self._save_data(keyword, keyword_products, start_page, output_dir)
                else:
                    print(f"⚠️ [Port {self.port}] {keyword} 未提取到新数据")

        except Exception as e:
            print(f"❌ [Port {self.port}] 进程错误: {e}")
        finally:
            await self.close()

    def _save_data(self, product_name, new_data, start_index, output_dir):
        """
        通用保存逻辑 (标准版)
        """
        final_data = new_data
        files_to_remove = []
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
                        # 翻页模式检测
                        is_page_logic = 'page' in old_data[0]
                        if is_page_logic:
                            print(f"    📄 [翻页模式] 上次进度 Page {start_index}，追加数据...")

                        final_data = old_data + new_data
                        print(f"    ➕ 合并成功: 旧({len(old_data)}) + 新({len(new_data)}) = 总({len(final_data)})")

                        files_to_remove.append(latest_json)

            except Exception as e:
                print(f"    ❌ 合并失败: {e}")

        # 保存
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if not os.path.exists(output_dir): os.makedirs(output_dir)

        json_path = os.path.join(output_dir, f"{safe_name}_products_{timestamp}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"  💾 [Port {self.port}] JSON: {os.path.basename(json_path)}")




        # 清理
        if files_to_remove:
            for f in files_to_remove:
                try:
                    os.remove(f)
                except:
                    pass


# ==================== 标准任务获取逻辑 ====================
def get_tasks_from_file(name_file, max_count, data_dir):
    """
    任务初始化函数 (标准版)
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

            # 文件名简单匹配
            match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
            if not match: continue

            p_safe_name = match.group(1)

            # 反向查找原名
            target_task = None
            for name in product_names:
                if re.sub(r'[<>:"/\\|?*]', "_", name)[:50] == p_safe_name:
                    target_task = name
                    break

            if target_task and target_task in tasks_progress:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data and isinstance(data, list) and len(data) > 0:
                        last_item = data[-1]
                        # 优先取 page (翻页模式)，否则取 index (滚动模式)
                        current = int(last_item.get('page', 0))
                        if not current:
                            current = int(last_item.get('index', len(data)))

                        if current > tasks_progress[target_task]:
                            tasks_progress[target_task] = current
                except:
                    pass

    final_tasks = []
    for name, progress in tasks_progress.items():
        if progress > 0:
            print(f"  🔄 恢复任务: {name} (从进度 {progress} 继续)")
        final_tasks.append((name, progress))

    return sorted(final_tasks, key=lambda x: x[0])


# ==================== 主入口 ====================
# 将这段代码复制替换 depop_crawler.py 和 ebay_crawler.py 最底部的 if __name__ == "__main__": 部分
# 注意：要把 crawler_class=... 那一行改成对应的类名（DepopCrawler 或 EbayCrawler）

# ... (get_tasks_from_file 函数保持不变) ...

if __name__ == "__main__":
    # 1. 定义命令行参数 (与 backend_final.py 完美对接)
    parser = argparse.ArgumentParser(description="分布式爬虫节点")
    parser.add_argument("--workers", type=int, default=2, help="并发窗口数")
    parser.add_argument("--base_port", type=int, default=9222, help="起始端口")
    parser.add_argument("--max_count", type=int, default=100, help="爬取数量")
    parser.add_argument("--output_dir", type=str, required=True, help="数据保存绝对路径")
    parser.add_argument("--task_file", type=str, required=True, help="任务文件路径")

    # 接收额外参数 (如 cookies_file)
    parser.add_argument("--cookies_file", type=str, default=None, help="Cookie文件路径")

    args = parser.parse_args()

    print(f"🚀 启动爬虫任务 (PID: {os.getpid()}):")
    print(f"   - Workers: {args.workers}")
    print(f"   - Target: {args.max_count}")
    print(f"   - Output: {args.output_dir}")
    print(f"   - Task File: {args.task_file}")
    print("=" * 60)

    # 2. 获取任务
    all_tasks = get_tasks_from_file(args.task_file, args.max_count, args.output_dir)

    if all_tasks:
        print(f"📦 任务总数: {len(all_tasks)}")

        # 3. 启动管理器
        # [!] 请确保这里的类名是当前文件的爬虫类 (如 DepopCrawler, EbayCrawler)
        manager = MultiCrawlerManager(
            crawler_class=EbayCrawler,  # <--- 修改这里！！！
            base_port=args.base_port,
            workers=args.workers,
            cookies_file=args.cookies_file  # 传递 cookie 参数
        )

        try:
            asyncio.run(manager.run(all_tasks, args.max_count, args.output_dir))
        except KeyboardInterrupt:
            print("\n🛑 用户停止")
    else:
        print("🎉 无待处理任务或任务文件为空")