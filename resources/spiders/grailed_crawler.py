import asyncio
import json
import re
import argparse
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import quote

# ==================== 修复后的导入逻辑 ====================
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
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from resources.spiders.crawler_base import BaseCrawler, MultiCrawlerManager

GRAILED_SHOP_BASE = "https://www.grailed.com/shop"

class GrailedCrawler(BaseCrawler):
    def extract_products(self, html_content, skip_count=0):
        """
        Grailed 专属解析逻辑 - 基于用户提供的 HTML 结构 (UserItem_root)
        """
        soup = BeautifulSoup(html_content, "html.parser")
        products = []

        # 1. 精准定位商品容器
        # 你的 HTML: <div class="UserItem_root__8Q2R_ UserItemForFeed_feedItem__5i2tc">
        # 我们使用正则匹配 "UserItem_root" 来忽略后面的随机字符
        containers = soup.find_all("div", class_=re.compile(r"UserItem_root"))

        # 兜底：如果改版导致找不到，尝试找包含 listings 链接的父级
        if not containers:
            print(f"⚠️ [Port {self.port}] 未找到 UserItem_root，尝试兜底策略...")
            links = soup.find_all('a', href=re.compile(r'/listings/'))
            seen_parents = set()
            for link in links:
                # 在你的结构中，<a> 标签就在 UserItem_root 下面
                parent = link.find_parent('div', class_=re.compile(r"feedItem"))
                if not parent: parent = link.parent

                if parent and parent not in seen_parents:
                    containers.append(parent)
                    seen_parents.add(parent)

        containers_to_process = containers[skip_count:]
        if not containers_to_process:
            return []

        print(f"🔍 [Port {self.port}] 解析新增数据: {len(containers_to_process)} 条...")

        local_index = skip_count
        for container in containers_to_process:
            try:
                local_index += 1
                product = {'index': local_index}

                # --- 1. 提取链接 ---
                # HTML: <a href="/listings/..." ... class="UserItem_link__kgEWg">
                link_elem = container.find("a", href=re.compile(r"/listings/"))
                if not link_elem: continue

                href = link_elem.get("href", "")
                if href.startswith("/"):
                    href = "https://www.grailed.com" + href
                # 清除 tracking 参数
                product['link'] = href.split('?')[0]

                # --- 2. 提取图片 ---
                # HTML: <img ... srcset="...url 1x, ...url 2x">
                img_elem = container.find("img")
                image_url = ""
                if img_elem:
                    # 优先取 srcset 里最高清的那张（通常在最后）
                    srcset = img_elem.get("srcset", "")
                    if srcset:
                        # 分割 'url 1x, url 2x' -> 取最后一个 -> 取 url 部分
                        image_url = srcset.split(",")[-1].strip().split(" ")[0]
                    else:
                        image_url = img_elem.get("src", "")
                product['image'] = image_url

                # --- 3. 提取价格 ---
                # HTML: <span class="Money_root__uOwWV" data-testid="Current">$250</span>
                # 这是最准的定位方式
                price = "N/A"
                price_elem = container.select_one('[data-testid="Current"]')
                if price_elem:
                    price = price_elem.get_text(strip=True)
                else:
                    # 备用：暴力找 $ 符号
                    text_price = container.find(string=re.compile(r"\$"))
                    if text_price: price = text_price.strip()
                product['price'] = price

                # --- 4. 提取详情 (Brand, Title, Size) ---
                # HTML: UserItem_designer__N8CxZ, UserItem_size__QTA9F, UserItem_title__riOTf
                # 我们使用 class*= 来匹配，忽略后面的随机哈希

                designer = ""
                item_title = ""
                size = ""

                designer_elem = container.select_one('[class*="UserItem_designer"]')
                if designer_elem: designer = designer_elem.get_text(strip=True)

                title_elem = container.select_one('[class*="UserItem_title"]')
                if title_elem: item_title = title_elem.get_text(strip=True)

                size_elem = container.select_one('[class*="UserItem_size"]')
                if size_elem: size = size_elem.get_text(strip=True)

                # 拼接成一个人类可读的完整标题
                # 例: "Nike What The Kobe 8 “Protro” (Size: 10)"
                full_title_parts = []
                if designer: full_title_parts.append(designer)
                if item_title: full_title_parts.append(item_title)

                full_title = " ".join(full_title_parts)
                if size:
                    full_title += f" (Size: {size})"

                # 如果实在没提取到，回退到取全部文本
                if not full_title.strip():
                    full_title = container.get_text(separator=" ", strip=True)[:100]

                product['title'] = full_title

                # --- 5. 补充平台字段 ---
                product['Platform'] = 'grailed'
                product['Category'] = 'Clothing'

                products.append(product)

            except Exception as e:
                # print(f"解析错误: {e}") # 调试时可打开
                continue

        return products

    async def crawl(self, tasks, max_count, output_dir):
        """
        Grailed 主爬取循环
        """
        # 按进度排序
        tasks.sort(key=lambda x: x[1])

        try:
            # 1. 启动浏览器
            await self.init_browser()
            if not self.page: return

            # 2. 遍历任务
            for keyword, start_index in tasks:
                print(f"\n{'='*40}\n[Port {self.port}] 爬取: {keyword} (Index {start_index})\n{'='*40}")

                url = f"{GRAILED_SHOP_BASE}?query={quote(keyword)}"

                try:
                    await self.page.goto(url, timeout=60000)
                    try:
                        await self.page.wait_for_load_state('networkidle', timeout=15000)
                    except: pass
                except Exception as e:
                    print(f"❌ [Port {self.port}] 页面跳转失败: {e}")
                    continue

                # --- 无限滚动逻辑 ---
                current_count = 0
                retry_count = 0

                while current_count < max_count:
                    # 滚动到底部
                    await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)

                    # 实时计算当前页面已加载的商品数
                    # 使用与 extract_products 相同的逻辑计数
                    item_count = await self.page.evaluate("""() => {
                        return document.querySelectorAll('div[class*="UserItem_root"]').length
                    }""")

                    # 如果 js 计数失败，使用备用计数
                    if item_count == 0:
                         item_count = await self.page.evaluate("""() => {
                            return document.querySelectorAll('a[href*="/listings/"]').length
                        }""")

                    if item_count > current_count:
                        current_count = item_count
                        retry_count = 0
                        print(f"  📉 [Port {self.port}] 滚动加载中... (当前: {current_count})", end='\r')
                    else:
                        retry_count += 1
                        print(f"  ⚠️ [Port {self.port}] 无新内容 ({retry_count}/5)...")
                        # 尝试回滚触发懒加载
                        await self.page.evaluate("window.scrollBy(0, -800)")
                        await asyncio.sleep(1)
                        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                        if retry_count >= 5:
                            print(f"  🛑 [Port {self.port}] 已达底部，停止滚动")
                            break

                    # 检查是否已经满足数量要求（加上之前的进度）
                    # 注意：这里我们是重新跑的，所以只要当前页面的数量够了就行
                    if current_count >= (max_count - start_index) + 20: # 多抓一点余量
                        break

                    await asyncio.sleep(1)

                # --- 提取与保存 ---
                print(f"\n[Port {self.port}] 开始提取数据...")
                try:
                    html = await self.page.content()
                    data = self.extract_products(html, skip_count=start_index)

                    if data:
                        # 截断到需要的数量
                        needed = max_count - start_index
                        if len(data) > needed:
                            data = data[:needed]

                        self._save_data(keyword, data, start_index, output_dir)
                    else:
                        print(f"  ⚠️ [Port {self.port}] 未提取到有效数据")
                except Exception as e:
                    print(f"  ❌ [Port {self.port}] 处理失败: {e}")

        except Exception as e:
            print(f"❌ [Port {self.port}] 进程崩溃: {e}")
        finally:
            await self.close()

    def _save_data(self, product_name, new_data, start_index, output_dir):
        """
        保存逻辑：JSON + CSV (带BOM头)
        """
        final_data = new_data
        files_to_remove = []
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", product_name)[:50]

        # 合并逻辑
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
                        final_data = old_data + new_data
                        print(f"    ➕ 合并成功: 旧({len(old_data)}) + 新({len(new_data)}) = 总({len(final_data)})")
                        files_to_remove.append(latest_json)


            except Exception as e:
                print(f"    ❌ 合并失败: {e}")

        # 保存
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if not os.path.exists(output_dir): os.makedirs(output_dir)

        # 保存 JSON
        json_path = os.path.join(output_dir, f"{safe_name}_products_{timestamp}.json")
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(final_data, f, ensure_ascii=False, indent=2)
            print(f"  💾 [Port {self.port}] JSON: {os.path.basename(json_path)}")
        except Exception as e:
            print(f"  ❌ JSON 保存失败: {e}")

        # 保存 CSV


        # 清理旧文件
        if files_to_remove:
            for f in files_to_remove:
                try: os.remove(f)
                except: pass

# ==================== 标准任务获取逻辑 ====================
def get_tasks_from_file(name_file, max_count, data_dir):
    import json
    from pathlib import Path
    try:
        if not os.path.exists(name_file):
            return []
        with open(name_file, 'r', encoding='utf-8') as f:
            names = json.load(f)
        product_names = list(set(names))
    except Exception:
        return []

    tasks_progress = {name: 0 for name in product_names}
    data_path = Path(data_dir)

    if data_path.exists():
        print(f"🔍 扫描 {data_dir} 断点...")
        for json_file in data_path.glob('*_products_*.json'):
            if json_file.name.startswith('all_products'): continue
            match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
            if not match: continue

            p_safe_name = match.group(1)
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
                        # Grailed 是滚动逻辑，取 index
                        current = int(data[-1].get('index', len(data)))
                        if current > tasks_progress[target_task]:
                            tasks_progress[target_task] = current
                except: pass

    final_tasks = []
    for name, progress in tasks_progress.items():
        if progress < max_count:
            if progress > 0:
                print(f"  🔄 恢复任务: {name} (从 {progress} 继续)")
            final_tasks.append((name, progress))

    return sorted(final_tasks, key=lambda x: x[0])

# ==================== 主入口 ====================
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
            crawler_class=GrailedCrawler,  # <--- 修改这里！！！
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
