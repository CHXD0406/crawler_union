# 文件名: depop_crawler.py
import asyncio
import json
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup
from crawler_base import BaseCrawler, MultiCrawlerManager
import re

class DepopCrawler(BaseCrawler):
    def extract_products(self, html_content, skip_count=0):
        """
        Depop 专属的 HTML 解析逻辑
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        new_products = []
        all_containers = soup.select('li[class*="styles_listItem"]')

        containers_to_process = all_containers[skip_count:]
        if not containers_to_process: return []

        print(f"🔍 [Port {self.port}] 解析新增数据: {len(containers_to_process)} 条...")

        local_index = skip_count
        for container in containers_to_process:
            try:
                local_index += 1
                product = {'index': local_index}

                # 提取图片
                img_tag = container.select_one('img[class*="_mainImage"]')
                if not img_tag: img_tag = container.select_one('img[src]')
                img_src = ""
                if img_tag:
                    img_src = img_tag.get('src') or img_tag.get('data-src') or ""
                    if not img_src and img_tag.get('srcset'):
                        img_src = img_tag.get('srcset').split(' ')[0]
                product['image'] = img_src

                # 提取价格
                price_tag = container.select_one('p[aria-label="Discounted price"]')
                if not price_tag: price_tag = container.select_one('p[aria-label="Price"]')
                if not price_tag: price_tag = container.select_one('p[aria-label="Full price"]')
                product['price'] = price_tag.get_text(strip=True) if price_tag else "0"

                # 提取链接/标题
                link_tag = container.select_one('a[class*="styles_unstyledLink"]')
                href, merchant, title = "", "", ""
                if link_tag:
                    href = link_tag.get('href', '')
                    if href.startswith('/'): href = 'https://www.depop.com' + href
                    try:
                        clean_path = href.split('?')[0].strip('/')
                        if 'products/' in clean_path: clean_path = clean_path.split('products/')[-1]
                        parts = clean_path.split('-')
                        if len(parts) >= 2:
                            merchant = parts[0]
                            title = " ".join(parts[1:-1]).capitalize() if len(parts) > 2 else parts[1]
                        else:
                            title = clean_path
                    except:
                        title = "Parse Error"

                product['link'] = href;
                product['title'] = title;
                product['seller'] = merchant
                if product['link']: new_products.append(product)

            except Exception as e:
                continue
        return new_products

    async def crawl(self, tasks, max_count, output_dir):
        """
        Depop 专属的爬取循环逻辑 (覆盖父类方法)
        """
        # 按进度排序
        tasks.sort(key=lambda x: x[1])

        try:
            # 1. 调用父类方法启动浏览器
            await self.init_browser()

            if not self.page:
                print(f"❌ [Port {self.port}] 浏览器未就绪")
                return

            # 2. 调整缩放 (Depop 专属优化)
            try:
                await self.page.evaluate("document.body.style.zoom = '0.3'")
            except:
                pass

            # 3. 开始遍历任务
            for product_name, start_index in tasks:
                print(f"\n{'=' * 40}\n[Port {self.port}] 正在爬取: {product_name} (Index {start_index})\n{'=' * 40}")

                # 构造搜索URL
                search_query = product_name.strip().replace(' ', '+')
                search_url = f"https://www.depop.com/search/?q={search_query}"

                try:
                    await self.page.goto(search_url)
                    try:
                        await self.page.wait_for_load_state('networkidle', timeout=15000)
                    except:
                        pass
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"❌ [Port {self.port}] 页面跳转失败: {e}")
                    continue

                # --- 智能无限滚动 (Depop 需要) ---
                current_count = 0
                retry_count = 0
                item_selector = 'li[class*="styles_listItem"]'

                while current_count < max_count:
                    await self.page.keyboard.press("End")
                    await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                    # 等待新元素出现
                    try:
                        await self.page.wait_for_function(
                            f"document.querySelectorAll('{item_selector}').length > {current_count}",
                            timeout=20000
                        )
                        await asyncio.sleep(2)
                    except:
                        pass

                    try:
                        new_count = await self.page.evaluate(f"document.querySelectorAll('{item_selector}').length")
                    except:
                        new_count = current_count

                    if new_count > current_count:
                        current_count = new_count
                        retry_count = 0
                        print(f"  📉 [Port {self.port}] 滚动加载中... (当前: {current_count})", end='\r')
                    else:
                        retry_count += 1
                        print(f"  ⚠️ [Port {self.port}] 无新内容 ({retry_count}/5)...")
                        await self.page.evaluate("window.scrollBy(0, -500)")
                        await asyncio.sleep(2)
                        await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        if retry_count >= 5: break

                # --- 提取与保存 ---
                print(f"\n[Port {self.port}] 提取数据...")
                try:
                    html = await self.page.content()
                    data = self.extract_products(html, skip_count=start_index)
                    if data:
                        self._save_data(product_name, data, start_index, output_dir)
                        print(f"  ✓ [Port {self.port}] 保存成功: {len(data)} 条")
                    else:
                        print(f"  ⚠️ [Port {self.port}] 未提取到数据")
                except Exception as e:
                    print(f"  ❌ [Port {self.port}] 处理失败: {e}")

        except Exception as e:
            print(f"❌ [Port {self.port}] 进程崩溃: {e}")
        finally:
            await self.close()  # 调用父类清理

    def _save_data(self, product_name, new_data, start_index, output_dir):
        """保存数据辅助函数"""
        final_data = new_data

        print(f"📊 准备保存 {len(final_data)} 条数据...")


        files_to_remove = []

        if start_index > 0:
            print(f"\n🔄 [合并模式] 检测到续传 (起始 Index {start_index})，检索旧文件...")
            try:
                from pathlib import Path
                data_path = Path(output_dir)
                candidate_files = []
                for f in data_path.glob('*_products_*.json'):
                    match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', f.name)
                    if match and match.group(1) == product_name:
                        candidate_files.append(f)
                candidate_files.sort(key=lambda x: x.name, reverse=True)

                if candidate_files:
                    latest_json = candidate_files[0]
                    with open(latest_json, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)

                    if isinstance(old_data, list):
                        if len(old_data) != start_index:
                            print(
                                f"   ⚠️ 警告: 旧数据长度 ({len(old_data)}) 与 start_index ({start_index}) 不一致")

                        final_data = old_data + final_data
                        print(
                            f"   ➕ 合并成功: 旧({len(old_data)}) + 新({len(final_data )}) = 总({len(final_data)})")
                        files_to_remove.append(latest_json)
                        old_csv = latest_json.with_suffix('.csv')
                        if old_csv.exists(): files_to_remove.append(old_csv)
                else:
                    print("   ⚠️ 未找到旧文件")
            except Exception as e:
                print(f"   ❌ 合并出错: {e}")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        new_json_name = os.path.join(output_dir, f"{product_name}_products_{timestamp}.json")
        new_csv_name = os.path.join(output_dir, f"{product_name}_products_{timestamp}.csv")

        if not os.path.exists(output_dir): os.makedirs(output_dir)

        with open(new_json_name, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON保存: {os.path.basename(new_json_name)}")

        import csv
        with open(new_csv_name, 'w', encoding='utf-8', newline='') as f:
            if final_data:
                keys = final_data[0].keys()
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(final_data)
        print(f"💾 CSV保存: {os.path.basename(new_csv_name)}")

        if files_to_remove:
            print(f"🧹 清理旧版本文件...")
            for f in files_to_remove:
                try:
                    os.remove(f);
                    print(f"   🗑️ 删除: {f.name}")
                except:
                    pass


# ==================== 核心工具: 任务获取与断点检测 ====================
def get_tasks_from_file(name_file, max_count, data_dir):
    """
    读取任务列表，并扫描数据目录，检查是否有已爬取的进度。
    返回格式: [(product_name, start_index), ...]
    """
    import json
    from pathlib import Path

    # 1. 读取原始任务列表
    try:
        if not os.path.exists(name_file):
            print(f"❌ 未找到任务文件: {name_file}")
            return []
        with open(name_file, 'r', encoding='utf-8') as f:
            names = json.load(f)
        # 去重
        product_names = list(set(names))
    except Exception as e:
        print(f"❌ 读取任务文件失败: {e}")
        return []

    # 2. 扫描现有的 JSON 文件，获取进度
    tasks_progress = {name: 0 for name in product_names}
    data_path = Path(data_dir)

    if data_path.exists():
        print(f"🔍 正在扫描 {data_dir} 目录下的断点信息...")
        for json_file in data_path.glob('*_products_*.json'):
            # 排除汇总文件
            if json_file.name.startswith('all_products'): continue

            # 解析文件名: name_products_timestamp.json
            match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
            if not match: continue

            p_name = match.group(1)

            # 如果这个商品在我们的任务列表中
            if p_name in tasks_progress:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if data and isinstance(data, list):
                        # 获取最后一条数据的 index 作为当前进度
                        # 假设每条数据都有 'index' 字段，如果没有则使用列表长度
                        last_item = data[-1]
                        current_index = int(last_item.get('index', len(data)))

                        # 更新最大进度（防止有多个旧文件，取最大的那个）
                        if current_index > tasks_progress[p_name]:
                            tasks_progress[p_name] = current_index
                except Exception as e:
                    print(f"  ⚠️ 读取文件 {json_file.name} 失败: {e}")
                    continue

    # 3. 生成最终任务列表
    final_tasks = []
    for name, progress in tasks_progress.items():
        if progress < max_count:
            if progress > 0:
                print(f"  🔄 恢复任务: {name} (从 {progress} 开始)")
            final_tasks.append((name, progress))
        else:
            # print(f"  ✅ 跳过已完成: {name}") # 可选：打印已完成的任务
            pass

    # 按名称排序，保证每次运行顺序一致
    return sorted(final_tasks, key=lambda x: x[0])



# ==================== 主入口 ====================
if __name__ == "__main__":
    print("Depop 爬虫 (基于 CrawlerBase)")
    print("=" * 60)

    # 1. 配置参数
    WORKER_COUNT = 4
    BASE_PORT = 9222
    MAX_CRAWL = 400
    OUTPUT_DIR = 'depop_data'

    # 2. 获取任务
    all_tasks = get_tasks_from_file('clothing_leaf_names.json', MAX_CRAWL)

    if all_tasks:
        print(f"📦 任务总数: {len(all_tasks)}")

        # 3. 初始化通用管理器，传入 DepopCrawler 类
        manager = MultiCrawlerManager(
            crawler_class=DepopCrawler,
            base_port=BASE_PORT,
            workers=WORKER_COUNT
        )

        # 4. 运行
        asyncio.run(manager.run(all_tasks, MAX_CRAWL, OUTPUT_DIR))
    else:
        print("未找到任务文件或任务为空")
