"""
小米有品 xiaomiyoupin.com 商品爬虫
封装成函数，输入商品名称和页数，爬取对应商品对应页数的信息
注意：小米有品无需登录即可爬取数据
"""
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup


class XiaomiYoupinCrawler:
    """小米有品爬虫类"""
    
    def __init__(self, headless=True, save_html=False):
        """
        初始化爬虫
        
        参数:
            headless: 是否无头模式（默认True）
            save_html: 是否保存HTML文件（默认False）
        """
        self.headless = headless
        self.save_html = save_html
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        
    async def init_browser(self):
        """初始化浏览器（使用 Edge）"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
        
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            channel='msedge',
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'
        )
        
        self.page = await self.context.new_page()
        
        # 隐藏webdriver特征
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
    
    async def check_verification(self):
        """
        检测页面是否需要验证
        
        返回:
            bool: True表示需要验证，False表示不需要
        """
        try:
            current_url = self.page.url
            
            verification_keywords = ['verify', 'captcha', 'challenge', 'security', 'validate', 
                                    '验证', '安全验证', '人机验证', '滑块验证']
            if any(keyword in current_url.lower() for keyword in verification_keywords):
                return True
            
            try:
                title = await self.page.title()
                if any(keyword in title.lower() for keyword in verification_keywords):
                    return True
            except:
                pass
            
            verification_selectors = [
                'iframe[src*="captcha"]',
                'iframe[src*="verify"]',
                '.captcha',
                '.verify',
                '#captcha',
                '#verify',
                '[class*="captcha"]',
                '[class*="verify"]',
                '[class*="slider"]',
            ]
            
            for selector in verification_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            print(f"⚠️ 检测验证时出错: {e}")
            return False
    
    async def wait_for_verification(self):
        """
        等待用户完成验证
        """
        print("\n" + "="*60)
        print("🔒 检测到需要验证")
        print("="*60)
        print("请在浏览器中完成验证操作：")
        print("  1. 完成滑块验证、图片验证等")
        print("  2. 确保验证通过后")
        print("-"*60)
        print(">>> 完成后请按 Enter 键继续... <<<")
        print("="*60)
        
        await asyncio.get_event_loop().run_in_executor(None, input)
        
        print("\n正在检查验证状态...")
        await asyncio.sleep(1)
        
        still_need_verification = await self.check_verification()
        if not still_need_verification:
            print("✓ 验证已完成！")
            return True
        else:
            print("⚠️ 仍检测到验证页面，请再次尝试...")
            return False
    
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
        if hasattr(self, 'playwright') and self.playwright:
            try:
                await self.playwright.stop()
            except:
                pass
    
    async def scroll_to_load(self, scroll_times=5):
        """
        滚动页面以加载动态内容
        
        参数:
            scroll_times: 滚动次数
        """
        for i in range(scroll_times):
            await self.page.evaluate('window.scrollBy(0, window.innerHeight)')
            await asyncio.sleep(0.5)
        # 滚回顶部
        await self.page.evaluate('window.scrollTo(0, 0)')
        await asyncio.sleep(0.3)
    
    async def get_total_pages(self):
        """
        检测当前搜索结果的总页数
        
        返回:
            int: 总页数，如果无法检测则返回 1
        """
        try:
            # 滚动到底部以确保分页组件加载
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(1)
            
            # 方式1: 查找分页组件中的总页数
            # 常见的分页选择器
            pagination_selectors = [
                '.pagination',
                '.pager',
                '[class*="pagination"]',
                '[class*="pager"]',
                '[class*="page-list"]',
            ]
            
            for selector in pagination_selectors:
                try:
                    pagination = await self.page.query_selector(selector)
                    if pagination:
                        # 获取分页区域的所有页码
                        page_items = await pagination.query_selector_all('a, button, li, span')
                        max_page = 1
                        for item in page_items:
                            text = await item.inner_text()
                            text = text.strip()
                            # 尝试提取数字
                            if text.isdigit():
                                page_num = int(text)
                                if page_num > max_page:
                                    max_page = page_num
                        if max_page > 1:
                            return max_page
                except:
                    continue
            
            # 方式2: 查找"下一页"按钮是否禁用或不存在
            next_page_selectors = [
                '.pagination-next',
                '.page-next',
                '[class*="next"]',
                'a:has-text("下一页")',
                'button:has-text("下一页")',
            ]
            
            has_next = False
            for selector in next_page_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        is_visible = await elem.is_visible()
                        is_disabled = await elem.get_attribute('disabled')
                        class_attr = await elem.get_attribute('class') or ''
                        
                        # 检查是否被禁用
                        if is_visible and not is_disabled and 'disabled' not in class_attr:
                            has_next = True
                            break
                except:
                    continue
            
            # 如果没有下一页按钮或被禁用，说明只有1页
            if not has_next:
                return 1
            
            # 方式3: 查找页面中是否有"共 X 页"或类似文本
            try:
                page_text = await self.page.inner_text('body')
                # 匹配 "共 X 页" 或 "共X页" 或 "总共 X 页"
                match = re.search(r'共\s*(\d+)\s*页|总共\s*(\d+)\s*页', page_text)
                if match:
                    total = match.group(1) or match.group(2)
                    return int(total)
            except:
                pass
            
            # 默认返回一个较大的值，让程序继续尝试翻页
            return 999
            
        except Exception as e:
            print(f"⚠️ 检测总页数时出错: {e}")
            return 999
    
    async def check_has_next_page(self):
        """
        检测是否还有下一页
        
        返回:
            bool: True 表示有下一页，False 表示没有
        """
        try:
            # 检查下一页按钮是否存在且可用
            next_page_selectors = [
                '.pagination-next:not(.disabled)',
                '.page-next:not(.disabled)',
                '[class*="next"]:not([class*="disabled"])',
                'a:has-text("下一页"):not(.disabled)',
                'button:has-text("下一页"):not(:disabled)',
            ]
            
            for selector in next_page_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        is_visible = await elem.is_visible()
                        if is_visible:
                            # 检查是否被禁用
                            is_disabled = await elem.get_attribute('disabled')
                            class_attr = await elem.get_attribute('class') or ''
                            aria_disabled = await elem.get_attribute('aria-disabled')
                            
                            if not is_disabled and 'disabled' not in class_attr.lower() and aria_disabled != 'true':
                                return True
                except:
                    continue
            
            # 没有找到可用的下一页按钮
            return False
            
        except Exception as e:
            print(f"⚠️ 检测下一页时出错: {e}")
            return False
    
    def extract_products(self, html_content, page_num):
        """
        从HTML中提取商品信息（针对小米有品页面结构）
        
        小米有品商品列表结构可能为：
        - 商品容器带有 data-gid 或 data-pid 属性
        - 或者包含 goods-item / product-item 类名
        
        参数:
            html_content: HTML内容
            page_num: 页码
            
        返回:
            products: 商品列表
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        products = []
        
        # 查找所有商品容器 - 多种可能的选择器
        product_containers = []
        
        # 方式1: 带有 data-gid 属性的元素
        containers = soup.find_all(attrs={'data-gid': True})
        if containers:
            product_containers = containers
        
        # 方式2: 带有 data-pid 属性的元素
        if not product_containers:
            containers = soup.find_all(attrs={'data-pid': True})
            if containers:
                product_containers = containers
        
        # 方式3: 包含 goods-item 类的元素
        if not product_containers:
            containers = soup.find_all(class_=re.compile(r'goods[-_]?item|product[-_]?item|search[-_]?item', re.I))
            if containers:
                product_containers = containers
        
        # 方式4: 包含商品链接的 a 标签容器
        if not product_containers:
            links = soup.find_all('a', href=re.compile(r'/detail|/product|/goods|gid=', re.I))
            for link in links:
                parent = link.find_parent(['div', 'li', 'article'])
                if parent and parent not in product_containers:
                    product_containers.append(parent)
        
        # 方式5: 查找包含价格的商品块
        if not product_containers:
            price_elements = soup.find_all(class_=re.compile(r'price', re.I))
            for price_elem in price_elements:
                parent = price_elem.find_parent(['div', 'li', 'article'], class_=True)
                if parent and parent not in product_containers:
                    # 确保是商品容器而不是其他元素
                    if parent.find('img') and parent.find('a'):
                        product_containers.append(parent)
        
        print(f"找到 {len(product_containers)} 个商品容器")
        
        for idx, container in enumerate(product_containers, 1):
            try:
                product = {
                    'page': page_num,
                    'index': idx
                }
                
                # 1. 提取商品ID
                product_id = (container.get('data-gid', '') or 
                             container.get('data-pid', '') or 
                             container.get('data-id', ''))
                product['product_id'] = product_id
                
                # 2. 提取商品链接
                link_elem = container.find('a', href=True)
                href = ''
                if link_elem:
                    href = link_elem.get('href', '')
                    if href:
                        if href.startswith('//'):
                            href = 'https:' + href
                        elif href.startswith('/'):
                            href = 'https://www.xiaomiyoupin.com' + href
                        href = href.replace('&amp;', '&')
                    
                    # 从链接中提取商品ID
                    if not product_id:
                        id_match = re.search(r'gid=(\d+)|/detail/(\d+)|/product/(\d+)', href)
                        if id_match:
                            product_id = id_match.group(1) or id_match.group(2) or id_match.group(3)
                            product['product_id'] = product_id
                
                product['link'] = href
                
                # 3. 提取商品图片和名称
                img_elem = container.find('img')
                product_image = ''
                title_from_img = ''
                if img_elem:
                    img_src = (img_elem.get('src', '') or 
                              img_elem.get('data-src', '') or 
                              img_elem.get('data-lazy-src', '') or
                              img_elem.get('data-original', ''))
                    if img_src:
                        if img_src.startswith('//'):
                            img_src = 'https:' + img_src
                        elif img_src.startswith('/'):
                            img_src = 'https://www.xiaomiyoupin.com' + img_src
                        # 过滤占位图
                        if 'placeholder' not in img_src.lower() and 'loading' not in img_src.lower():
                            product_image = img_src
                    title_from_img = img_elem.get('alt', '')
                
                product['image'] = product_image
                
                # 4. 提取商品名称
                title = ''
                # 尝试多种选择器
                title_selectors = [
                    ('[class*="name"]', None),
                    ('[class*="title"]', None),
                    ('h3', None),
                    ('h4', None),
                    ('.goods-name', None),
                    ('.product-name', None),
                    ('.item-name', None),
                ]
                
                for selector, _ in title_selectors:
                    title_elem = container.select_one(selector)
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        if title and len(title) > 2:
                            break
                
                if not title:
                    title = title_from_img
                
                title = ' '.join(title.split()) if title else ''
                product['title'] = title
                
                # 5. 提取售价
                price = ''
                price_selectors = [
                    '[class*="price"]',
                    '[class*="sale"]',
                    '.goods-price',
                    '.product-price',
                    '.item-price',
                ]
                
                for selector in price_selectors:
                    price_elems = container.select(selector)
                    for price_elem in price_elems:
                        price_text = price_elem.get_text(strip=True)
                        # 提取数字价格
                        price_match = re.search(r'[\d.]+', price_text)
                        if price_match:
                            price = price_match.group()
                            break
                    if price:
                        break
                
                product['price'] = price
                
                # 6. 提取原价（如果有）
                original_price = ''
                orig_price_selectors = [
                    '[class*="origin"]',
                    '[class*="market"]',
                    '[class*="old"]',
                    'del',
                    's',
                ]
                
                for selector in orig_price_selectors:
                    orig_elem = container.select_one(selector)
                    if orig_elem:
                        orig_text = orig_elem.get_text(strip=True)
                        orig_match = re.search(r'[\d.]+', orig_text)
                        if orig_match:
                            original_price = orig_match.group()
                            break
                
                product['original_price'] = original_price
                
                # 7. 提取折扣信息
                discount = ''
                discount_selectors = [
                    '[class*="discount"]',
                    '[class*="off"]',
                    '[class*="tag"]',
                ]
                
                for selector in discount_selectors:
                    discount_elem = container.select_one(selector)
                    if discount_elem:
                        discount_text = discount_elem.get_text(strip=True)
                        if '折' in discount_text or '%' in discount_text or 'off' in discount_text.lower():
                            discount = discount_text
                            break
                
                product['discount'] = discount
                
                # 8. 提取评价数/销量
                sales = ''
                sales_selectors = [
                    '[class*="comment"]',
                    '[class*="review"]',
                    '[class*="sale"]',
                    '[class*="sold"]',
                ]
                
                for selector in sales_selectors:
                    sales_elem = container.select_one(selector)
                    if sales_elem:
                        sales_text = sales_elem.get_text(strip=True)
                        if re.search(r'\d+', sales_text):
                            sales = sales_text
                            break
                
                product['sales'] = sales
                
                # 验证是否为有效商品（必须有标题和链接）
                is_valid = bool(product.get('title') and product.get('link'))
                
                if is_valid:
                    products.append(product)
                    title_preview = product['title'][:40] + '...' if len(product['title']) > 40 else product['title']
                    price_display = f"¥{product['price']}" if product.get('price') else 'N/A'
                    print(f"商品 {len(products)}: {title_preview} - {price_display}")
                
            except Exception as e:
                print(f"提取商品 {idx} 时出错: {e}")
                continue
        
        print(f"\n总共提取到 {len(products)} 个有效商品")
        return products


async def crawl_products_automated(products, num_pages_per_product, headless=False, save_html=False, output_dir='xiaomiyoupin_data'):
    """
    按照自动化流程爬取多个商品的多页数据
    
    参数:
        products: 商品名称列表，例如 ['手机', '耳机', '电脑']
        num_pages_per_product: 每个商品要爬取的页数
        headless: 是否无头模式（默认False）
        save_html: 是否保存HTML文件
        output_dir: 输出目录
    
    返回:
        all_products: 所有商品列表
    """
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    crawler = XiaomiYoupinCrawler(headless=headless, save_html=save_html)
    all_products = []
    
    try:
        await crawler.init_browser()
        
        # 打开首页
        url = "https://www.xiaomiyoupin.com"
        print(f"\n{'='*60}")
        print(f"打开网页: {url}")
        print(f"{'='*60}")
        await crawler.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        
        # 等待页面加载
        await asyncio.sleep(3)
        
        # 检测是否需要验证
        while await crawler.check_verification():
            success = await crawler.wait_for_verification()
            if success:
                break
        
        # 遍历每个商品
        for product_idx, product_name in enumerate(products, 1):
            print(f"\n{'='*60}")
            print(f"商品 {product_idx}/{len(products)}: {product_name}")
            print(f"{'='*60}")
            
            product_products = []
            
            # 使用URL直接搜索
            # 小米有品搜索URL格式
            search_url = f"https://www.xiaomiyoupin.com/search?keyword={product_name}"
            print(f"\n打开搜索页面: {search_url}")
            
            try:
                await crawler.page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(3)
                
                # 检测是否需要验证
                while await crawler.check_verification():
                    success = await crawler.wait_for_verification()
                    if success:
                        break
                
            except Exception as e:
                print(f"⚠️ 打开搜索页面失败: {e}")
                continue
            
            # 检测总页数
            total_pages = await crawler.get_total_pages()
            actual_pages = min(num_pages_per_product, total_pages)
            
            if total_pages < num_pages_per_product:
                print(f"\n📄 检测到该商品只有 {total_pages} 页搜索结果（设定爬取 {num_pages_per_product} 页）")
                print(f"   将爬取所有 {total_pages} 页后继续下一个商品")
            else:
                print(f"\n📄 检测到该商品有 {total_pages}+ 页，将爬取前 {num_pages_per_product} 页")
            
            # 遍历每个页面
            for page_num in range(1, actual_pages + 1):
                print(f"\n  {'-'*50}")
                print(f"  第 {page_num}/{num_pages_per_product} 页")
                print(f"  {'-'*50}")
                
                try:
                    # 检测验证
                    while await crawler.check_verification():
                        success = await crawler.wait_for_verification()
                        if success:
                            break
                    
                    # 等待页面稳定
                    await asyncio.sleep(2)
                    try:
                        await crawler.page.wait_for_load_state('domcontentloaded', timeout=15000)
                    except:
                        pass
                    
                    # 滚动加载动态内容
                    print("  滚动页面加载商品...")
                    await crawler.scroll_to_load(scroll_times=5)
                    
                    # 获取HTML内容
                    html_content = await crawler.page.content()
                    
                    if html_content:
                        # 保存HTML
                        if save_html:
                            html_file = os.path.join(output_dir, f"{product_name}_page_{page_num}.html")
                            with open(html_file, 'w', encoding='utf-8') as f:
                                f.write(html_content)
                            print(f"  ✓ HTML已保存: {html_file}")
                        
                        # 提取商品信息
                        products_data = crawler.extract_products(html_content, page_num)
                        product_products.extend(products_data)
                        print(f"  ✓ 第 {page_num} 页完成，提取到 {len(products_data)} 个商品")
                    else:
                        print(f"  ⚠️ 第 {page_num} 页无法获取HTML内容")
                
                except Exception as e:
                    print(f"  ⚠️ 第 {page_num} 页爬取出错: {e}")
                
                # 如果不是最后一页，尝试翻页
                if page_num < actual_pages:
                    # 先检测是否有下一页
                    has_next = await crawler.check_has_next_page()
                    if not has_next:
                        print(f"  ℹ️ 没有更多页面了，当前商品爬取完成（共 {page_num} 页）")
                        break
                    
                    print(f"  点击下一页...")
                    try:
                        # 尝试使用选择器点击下一页
                        next_page_selectors = [
                            '.pagination-next',
                            '.page-next',
                            '[class*="next"]',
                            'a:has-text("下一页")',
                            'button:has-text("下一页")',
                        ]
                        
                        clicked = False
                        for selector in next_page_selectors:
                            try:
                                elem = await crawler.page.query_selector(selector)
                                if elem:
                                    is_visible = await elem.is_visible()
                                    if is_visible:
                                        # 检查是否禁用
                                        is_disabled = await elem.get_attribute('disabled')
                                        class_attr = await elem.get_attribute('class') or ''
                                        if not is_disabled and 'disabled' not in class_attr.lower():
                                            await elem.click()
                                            clicked = True
                                            print("  ✓ 已点击下一页")
                                            break
                            except:
                                continue
                        
                        if not clicked:
                            # 尝试通过URL翻页
                            current_url = crawler.page.url
                            if 'page=' in current_url:
                                new_url = re.sub(r'page=\d+', f'page={page_num + 1}', current_url)
                            else:
                                separator = '&' if '?' in current_url else '?'
                                new_url = f"{current_url}{separator}page={page_num + 1}"
                            
                            await crawler.page.goto(new_url, wait_until='domcontentloaded', timeout=60000)
                            print(f"  ✓ 通过URL跳转到第 {page_num + 1} 页")
                        
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        print(f"  ⚠️ 翻页失败: {e}")
                        break
            
            # 保存当前商品的数据
            if product_products:
                all_products.extend(product_products)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                # 保存JSON
                json_file = os.path.join(output_dir, f"{product_name}_products_{timestamp}.json")
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(product_products, f, ensure_ascii=False, indent=2)
                print(f"\n✓ {product_name} 的JSON数据已保存: {json_file}")
                
                print(f"✓ {product_name} 完成，共提取 {len(product_products)} 个商品")
            else:
                print(f"\n⚠️ {product_name} 未提取到任何商品")
        
        # 保存所有商品的总数据
        if all_products:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            all_json_file = os.path.join(output_dir, f"all_products_{timestamp}.json")
            with open(all_json_file, 'w', encoding='utf-8') as f:
                json.dump(all_products, f, ensure_ascii=False, indent=2)
            print(f"\n{'='*60}")
            print(f"✓ 所有商品数据已保存: {all_json_file}")
            print(f"总共爬取到 {len(all_products)} 个商品")
            print(f"{'='*60}")
        
    except Exception as e:
        print(f"❌ 爬取过程出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await crawler.close()
    
    return all_products


def get_crawled_products(data_dir='xiaomiyoupin_data', check_html=True):
    """
    从数据目录中提取已爬取的商品名称
    
    参数:
        data_dir: 数据目录路径
        check_html: 是否也检查 HTML 文件
    
    返回:
        set: 已爬取的商品名称集合
    """
    crawled_products = set()
    data_path = Path(data_dir)
    
    if not data_path.exists():
        return crawled_products
    
    # 查找所有 *_products_*.json 文件
    for json_file in data_path.glob('*_products_*.json'):
        if json_file.name.startswith('all_products'):
            continue
        match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
        if match:
            product_name = match.group(1)
            crawled_products.add(product_name)
    
    if check_html:
        for html_file in data_path.glob('*_page_*.html'):
            match = re.match(r'^(.+?)_page_\d+\.html$', html_file.name)
            if match:
                product_name = match.group(1)
                crawled_products.add(product_name)
    
    return crawled_products


def filter_products(products_list, crawled_products):
    """
    从商品列表中移除已爬取的商品
    
    参数:
        products_list: 原始商品列表
        crawled_products: 已爬取的商品集合
    
    返回:
        tuple: (未爬取的商品列表, 已爬取的商品列表)
    """
    uncrawled = []
    crawled = []
    
    for product in products_list:
        if product in crawled_products:
            crawled.append(product)
        else:
            uncrawled.append(product)
    
    return uncrawled, crawled


if __name__ == "__main__":
    # 示例用法
    print("小米有品 xiaomiyoupin.com 商品爬虫")
    print("="*60)
    print("注意：小米有品无需登录即可爬取数据")
    print("="*60)
    
    # 商品列表 - 小米有品特色商品
    products_list = [
    'A字裙', 'POLO衫', 'T恤', 'choker项圈', '丝巾', '乐福鞋', '亚克力首饰', '人字拖', 
    '休闲裤', '保暖袜', '光学眼镜', '内裤', '凉鞋', '切尔西靴', '化妆刷', '化妆包', 
    '半身裙', '单肩包', '卡其裤', '卫衣', '双肩包', '发夹', '发带', '发箍', '发饰', 
    '口罩', '口袋巾', '古龙水', '合金首饰', '吊带', '吊带裙', '喇叭裤', '围巾', 
    '大衣', '太阳帽', '太阳镜', '夹克', '宝石', '家居服', '宽檐帽', '小黑裙', 
    '工装裤', '帆布袋', '帆布鞋', '帽子', '平底鞋', '德比鞋', '怀表', '戒指', 
    '手套', '手拿包', '手提包', '手机壳', '手表', '手链', '托特包', '护照夹', 
    '披肩', '拖鞋', '文创包袋', '文胸', '斜挎包', '旅行收纳包', '晚宴包', '晚礼服', 
    '智能戒指', '智能手环', '智能手表', '机械表', '条纹衫', '板鞋', '棒球帽', 
    '毛呢外套', '毛线帽', '毛衣', '水桶包', '沙滩巾', '波士顿包', '泳衣', '淡香水', 
    '淡香精', '渔夫帽', '燕尾服', '牛仔外套', '牛仔夹克', '牛仔裤', '牛津鞋', 
    '玛丽珍鞋', '环保包袋', '珍珠项链', '珍珠首饰', '瑜伽裤', '男士西装', '白衬衫', 
    '百褶裙', '皮带', '皮衣', '眼镜框', '睡袍', '短裤', '石英表', '科技设备', 
    '穆勒鞋', '紧身裤', '编织饰品', '罩衫', '美妆蛋', '羽绒服', '耳机保护套', 
    '耳环', '耳线', '耳罩', '耳钉', '背心', '胸衣', '胸针', '脚链', '腰包', 
    '腰带', '芭蕾鞋', '茶歇裙', '草帽', '衬衫', '衬衫裙', '袖扣', '西装外套', 
    '西装套装', '西裤', '贝雷帽', '跑步鞋', '踝靴', '运动内衣', '运动头带', 
    '运动手套', '运动水壶', '运动衫', '运动鞋', '连体裤', '连衣裙', '金银首饰', 
    '针织衫', '钻石', '铅笔裙', '链条包', '阔腿裤', '雨鞋', '雪地靴', '项链', 
    '领带', '领结', '颈枕', '风衣', '飞行员夹克', '香体喷雾', '香水', '马丁靴', 
    '马甲', '高跟鞋', '黑色紧身裤'
]
    num_pages = 20  # 每个商品爬取的页数
    
    # 自动检查并过滤已爬取的商品
    crawled_products = get_crawled_products('xiaomiyoupin_data', check_html=True)
    print(f"\n已爬取的商品 ({len(crawled_products)} 个):")
    for product in sorted(crawled_products):
        print(f"  - {product}")
    
    products_list, _ = filter_products(products_list, crawled_products)
    
    print(f"\n过滤后待爬取的商品 ({len(products_list)} 个):")
    for product in sorted(products_list):
        print(f"  - {product}")
    
    if not products_list:
        print("\n所有商品已爬取完成，无需再次运行。")
    else:
        print("\n开始爬取商品...")
        all_products = asyncio.run(crawl_products_automated(
            products=products_list,
            num_pages_per_product=num_pages,
            headless=False,
            save_html=True,
            output_dir='xiaomiyoupin_data'
        ))
        
        print(f"\n爬取完成！共获取 {len(all_products)} 个商品")
