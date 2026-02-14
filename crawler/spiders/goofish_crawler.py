"""
Goofish.com 商品爬虫
封装成函数，输入商品名称和页数，爬取对应商品对应页数的信息
"""
import asyncio
import json
import os
import time
import random
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import re
import pyautogui
import pyperclip


class GoofishCrawler:
    """Goofish.com 爬虫类"""
    
    def __init__(self, headless=True, save_html=False):
        """
        初始化爬虫
        
        参数:
            headless: 是否无头模式（默认True）
            save_html: 是否保存HTML文件（默认False）
        """
        self.headless = headless
        self.save_html = save_html
        self.playwright = None  # 保存 Playwright 实例
        self.browser = None
        self.context = None  # 保存浏览器上下文
        self.page = None
        self.is_first_open = True  # 标记是否是首次打开（用于确定弹窗坐标）
        
    async def init_browser(self):
        """初始化浏览器（使用 Edge）"""
        # 如果 Playwright 实例不存在，创建新的
        if not self.playwright:
            self.playwright = await async_playwright().start()
        # 使用 Edge 浏览器
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            channel='msedge',  # 使用 Edge 浏览器
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        
        # 创建上下文，设置用户代理（Edge 浏览器）
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
            # 获取当前URL
            current_url = self.page.url
            
            # 检查URL中是否包含验证相关关键词
            verification_keywords = ['verify', 'captcha', 'challenge', 'security', 'validate', 
                                    '验证', '安全验证', '人机验证', '滑块验证']
            if any(keyword in current_url.lower() for keyword in verification_keywords):
                return True
            
            # 获取页面标题
            try:
                title = await self.page.title()
                if any(keyword in title.lower() for keyword in verification_keywords):
                    return True
            except:
                pass
            
            # 检查页面内容中是否包含验证相关元素
            verification_selectors = [
                'iframe[src*="captcha"]',
                'iframe[src*="verify"]',
                'iframe[src*="challenge"]',
                '.captcha',
                '.verify',
                '.challenge',
                '#captcha',
                '#verify',
                '[class*="captcha"]',
                '[class*="verify"]',
                '[class*="slider"]',
                '[id*="captcha"]',
                '[id*="verify"]',
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
            
            # 检查页面文本内容
            try:
                page_text = await self.page.inner_text('body')
                verification_texts = ['安全验证', '人机验证', '请完成验证', '拖动滑块', 
                                    '验证码', 'captcha', 'verification', 'challenge']
                if any(text in page_text for text in verification_texts):
                    return True
            except:
                pass
            
            return False
            
        except Exception as e:
            print(f"⚠️ 检测验证时出错: {e}")
            return False
    
    async def handle_verification_with_retry(self, wait_time = 127, restore_state_callback=None, skip_current=True):
        """
        处理验证：关闭网站，等待后重新打开
        
        参数:
            wait_time: 等待时间（秒），默认60秒
            restore_state_callback: 恢复状态的回调函数（可选）
            skip_current: 是否跳过当前商品，默认True
        
        返回:
            tuple: (success: bool, should_skip: bool)
                success: True表示成功重新打开且无需验证，False表示仍然需要验证
                should_skip: True表示应该跳过当前商品，False表示继续当前商品
        """
        print("\n" + "="*60)
        print(f"⚠️  检测到需要验证！")
        print("="*60)
        if skip_current:
            print("⚠️  将跳过当前商品，重新打开后爬取下一个商品")
        print(f"关闭网站，等待 {wait_time} 秒后重新打开...")
        print("="*60)
        
        # 关闭当前页面
        try:
            await self.page.close()
            print("✓ 已关闭当前页面")
        except:
            pass
        
        # 等待指定时间
        print(f"等待 {wait_time} 秒...")
        for remaining in range(wait_time, 0, -1):
            print(f"  剩余 {remaining} 秒...", end='\r')
            await asyncio.sleep(1)
        print(f"  等待完成！{' '*20}")
        
        # 重新打开网站（完全重启浏览器以躲避验证）
        # 原理：新开 PowerShell 窗口能躲过验证，是因为创建了全新的浏览器实例和上下文
        # 我们通过完全关闭并重新初始化浏览器来模拟这个效果
        print("\n重新打开网站（完全重启浏览器以躲避验证）...")
        print("原理：创建全新的浏览器实例和上下文，模拟新开 PowerShell 窗口的效果")
        try:
            # 完全关闭浏览器和上下文
            if self.page:
                try:
                    await self.page.close()
                except:
                    pass
                self.page = None
            
            if self.context:
                try:
                    await self.context.close()
                except:
                    pass
                self.context = None
            
            if self.browser:
                try:
                    await self.browser.close()
                except:
                    pass
                self.browser = None
            
            # 如果 Playwright 实例存在，也关闭它（可选，为了更彻底的清理）
            # 注意：关闭 Playwright 后需要重新创建
            if self.playwright:
                try:
                    await self.playwright.stop()
                except:
                    pass
                self.playwright = None
            
            # 重新初始化浏览器（创建全新的浏览器实例和上下文）
            print("正在创建全新的浏览器实例和上下文...")
            await self.init_browser()
            
            # 重新打开首页
            url = "https://www.goofish.com"
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
            
            # 等待页面完全加载
            await asyncio.sleep(1)
            
            print("✓ 网站已重新打开（使用全新的浏览器实例和上下文）")
            
            # 完全重启浏览器后，和首次打开一样，应该使用 (1350, 792) 坐标
            # 所以设置为 True，使用首次打开的坐标
            self.is_first_open = True
            
            # 检查是否仍然需要验证
            if await self.check_verification():
                print("⚠️  重新打开后仍然需要验证")
                return (False, skip_current)
            else:
                print("✓ 重新打开后无需验证，正在恢复页面状态...")
                
                # 如果有恢复状态的回调函数，调用它来恢复页面状态
                if restore_state_callback:
                    await restore_state_callback()
                
                return (True, skip_current)
                
        except Exception as e:
            print(f"⚠️  重新打开网站时出错: {e}")
            return (False, skip_current)
    
    async def close(self):
        """关闭浏览器"""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    def extract_products(self, html_content, page_num):
        """
        从HTML中提取商品信息（根据实际HTML结构优化）
        
        参数:
            html_content: HTML内容
            page_num: 页码
            
        返回:
            products: 商品列表
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        products = []
        
        # 根据实际HTML结构，商品容器是 class="feeds-item-wrap--rGdH_KoF" 的 a 标签
        product_containers = soup.find_all('a', class_=re.compile(r'feeds-item-wrap', re.I))
        
        if not product_containers:
            # 备用方法：查找包含商品链接的容器
            product_links = soup.find_all('a', href=re.compile(r'goofish\.com/item\?id=', re.I))
            for link in product_links:
                container = link.find_parent('a', class_=re.compile(r'feeds-item-wrap', re.I))
                if container and container not in product_containers:
                    product_containers.append(container)
        
        print(f"找到 {len(product_containers)} 个商品容器")
        
        for idx, container in enumerate(product_containers, 1):
            try:
                product = {
                    'page': page_num,
                    'index': idx
                }
                
                # 1. 提取商品链接（从 a 标签的 href 属性）
                href = container.get('href', '')
                if href:
                    # 处理相对链接和协议相对链接
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = 'https://www.goofish.com' + href
                    # 处理HTML实体编码
                    href = href.replace('&amp;', '&')
                product['link'] = href
                
                # 2. 提取商品标题（从 row1-wrap-title 的 title 属性）
                title_div = container.find('div', class_=re.compile(r'row1-wrap-title', re.I))
                if title_div:
                    title = title_div.get('title', '')
                    if not title:
                        # 如果没有title属性，从main-title的文本获取
                        main_title = title_div.find('span', class_=re.compile(r'main-title', re.I))
                        if main_title:
                            title = main_title.get_text(strip=True)
                else:
                    title = ''
                
                # 清理标题（移除多余空白）
                title = ' '.join(title.split()) if title else ''
                product['title'] = title
                
                # 3. 提取商品价格（从 row3-wrap-price 中提取）
                price_div = container.find('div', class_=re.compile(r'row3-wrap-price', re.I))
                price = ''
                if price_div:
                    # 查找价格数字部分
                    number_span = price_div.find('span', class_=re.compile(r'number--', re.I))
                    decimal_span = price_div.find('span', class_=re.compile(r'decimal--', re.I))
                    
                    if number_span:
                        price = number_span.get_text(strip=True)
                        if decimal_span:
                            decimal = decimal_span.get_text(strip=True)
                            if decimal:
                                price = f"{price}.{decimal}"
                product['price'] = price
                
                # 4. 提取商品图片（优先webp格式，过滤占位图片）
                # 在容器中查找所有图片
                all_images = container.find_all('img')
                webp_images = []
                other_valid_images = []
                
                for img in all_images:
                    img_src = (img.get('src', '') or 
                              img.get('data-src', '') or 
                              img.get('data-lazy-src', ''))
                    
                    if not img_src:
                        continue
                    
                    # 处理相对链接
                    if img_src.startswith('//'):
                        img_src = 'https:' + img_src
                    elif img_src.startswith('/'):
                        img_src = 'https://www.goofish.com' + img_src
                    
                    # 过滤占位图片（包含 tps-2-2, tps-1-1 等小尺寸占位图）
                    if re.search(r'tps-[12]-[12]', img_src, re.I):
                        continue
                    
                    # 检查是否是商品图片（包含xy_item、fleamarket等关键词，或来自bao/uploaded）
                    is_product_image = bool(
                        re.search(r'xy_item|fleamarket|item\.jpg|item\.webp|bao/uploaded', img_src, re.I) or
                        (img.get('class') and any('feeds-image' in str(c) for c in img.get('class', [])))
                    )
                    
                    if is_product_image:
                        # 优先webp格式
                        if img_src.endswith('.webp') or '.webp' in img_src:
                            webp_images.append(img_src)
                        # 其他格式也收集，但优先级较低
                        elif not img_src.endswith('.png') or not re.search(r'tps-\d+-\d+', img_src, re.I):
                            # 不是占位png，可以使用
                            other_valid_images.append(img_src)
                
                # 优先使用webp格式的图片
                if webp_images:
                    product_image = webp_images[0]
                elif other_valid_images:
                    product_image = other_valid_images[0]
                else:
                    product_image = ''
                
                product['image'] = product_image
                
                # 5. 提取商家地址（从 row4-wrap-seller 中提取）
                seller_div = container.find('div', class_=re.compile(r'row4-wrap-seller', re.I))
                seller_location = ''
                if seller_div:
                    # 从 seller-text-wrap 的 title 属性获取
                    seller_text_wrap = seller_div.find('div', class_=re.compile(r'seller-text-wrap', re.I))
                    if seller_text_wrap:
                        seller_location = seller_text_wrap.get('title', '')
                        if not seller_location:
                            # 如果没有title，从seller-text的文本获取
                            seller_text = seller_text_wrap.find('p', class_=re.compile(r'seller-text', re.I))
                            if seller_text:
                                seller_location = seller_text.get_text(strip=True)
                product['seller_location'] = seller_location
                
                # 6. 提取商家头像（从 avatar 中提取）
                avatar_elem = container.find('img', class_=re.compile(r'avatar', re.I))
                seller_avatar = ''
                if avatar_elem:
                    avatar_src = avatar_elem.get('src', '') or avatar_elem.get('data-src', '')
                    if avatar_src:
                        if avatar_src.startswith('//'):
                            avatar_src = 'https:' + avatar_src
                        elif avatar_src.startswith('/'):
                            avatar_src = 'https://www.goofish.com' + avatar_src
                        seller_avatar = avatar_src
                product['seller_avatar'] = seller_avatar
                
                # 验证是否为有效商品（必须有标题和链接）
                is_valid = bool(product.get('title') and product.get('link'))
                if is_valid:
                    # 进一步验证链接必须是商品链接
                    if not re.search(r'goofish\.com/item\?id=', product.get('link', ''), re.I):
                        is_valid = False
                
                if is_valid:
                    products.append(product)
                    title_preview = product['title'][:50] + '...' if len(product['title']) > 50 else product['title']
                    price_display = product.get('price', 'N/A')
                    if price_display:
                        price_display = f"¥{price_display}"
                    location = product.get('seller_location', '')
                    print(f"商品 {len(products)}: {title_preview} - {price_display} ({location})")
                
            except Exception as e:
                print(f"提取商品 {idx} 时出错: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\n总共提取到 {len(products)} 个有效商品")
        return products



async def crawl_products_automated(products, num_pages_per_product, headless=False, save_html=False, output_dir='goofish_data'):
    """
    按照自动化流程爬取多个商品的多页数据
    
    参数:
        products: 商品名称列表，例如 ['手机', '衣服', '电脑']
        num_pages_per_product: 每个商品要爬取的页数
        headless: 是否无头模式（默认False，需要显示浏览器进行鼠标操作）
        save_html: 是否保存HTML文件
        output_dir: 输出目录
    
    返回:
        all_products: 所有商品列表
    """
    # 坐标配置
    CLOSE_POPUP_X, CLOSE_POPUP_Y = 1350, 792  # 关闭初始弹窗
    SEARCH_BAR_X, SEARCH_BAR_Y = 1310, 125  # 搜索栏
    SEARCH_BUTTON_X, SEARCH_BUTTON_Y = 1363, 125  # 搜索按钮
    CLOSE_SEARCH_POPUP_X, CLOSE_SEARCH_POPUP_Y = 1350, 725  # 搜索后的弹窗
    NEXT_PAGE_X, NEXT_PAGE_Y = 1395, 858  # 下一页按钮
    
    crawler = GoofishCrawler(headless=headless, save_html=save_html)
    all_products = []
    
    try:
        await crawler.init_browser()
        
        # 打开首页
        url = "https://www.goofish.com"
        print(f"\n{'='*60}")
        print(f"打开网页: {url}")
        print(f"{'='*60}")
        await crawler.page.goto(url, wait_until='networkidle', timeout=30000)
        
        # 验证重试机制变量
        current_wait_time = 127  # 当前等待时间（秒）
        consecutive_failures = 0  # 连续失败次数
        skip_first_product = False  # 初始化跳过第一个商品的标志
        #await asyncio.sleep(5000)
        # 定义恢复页面状态的函数
        async def restore_page_state():
            """恢复页面状态：缩小页面、关闭弹窗"""
            # 1. 连按7次"ctrl -"让页面缩小
            print("\n恢复页面状态：缩小页面...")
            for i in range(7):
                pyautogui.hotkey('ctrl', '-')
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.1)
            print("✓ 页面已缩小")
            
            # 2. 关闭初始弹窗
            # 如果完全重启浏览器（is_first_open=True），使用首次打开的坐标 (1350, 792)
            # 如果只是关闭页面重新打开（is_first_open=False），使用搜索弹窗坐标 (1350, 725)
            if crawler.is_first_open:
                popup_x, popup_y = CLOSE_POPUP_X, CLOSE_POPUP_Y
                print(f"恢复页面状态：关闭初始弹窗 ({popup_x}, {popup_y})...（完全重启，使用首次打开坐标）")
            else:
                popup_x, popup_y = CLOSE_SEARCH_POPUP_X, CLOSE_SEARCH_POPUP_Y
                print(f"恢复页面状态：关闭初始弹窗 ({popup_x}, {popup_y})...（仅关闭页面，使用搜索弹窗坐标）")
            
            pyautogui.moveTo(popup_x, popup_y, duration=0.3)
            await asyncio.sleep(0.1)
            pyautogui.click(popup_x, popup_y)
            await asyncio.sleep(0.1)
            print("✓ 弹窗已关闭")
        
        # 检测是否需要验证（打开页面后可能立即需要验证）
        while await crawler.check_verification():
            # 处理验证：关闭网站，等待后重新打开
            success = await crawler.handle_verification_with_retry(current_wait_time, restore_state_callback=restore_page_state)
            
            if success:
                # 成功重新打开且无需验证，重置等待时间和失败计数
                current_wait_time = 127
                consecutive_failures = 0
                break
            else:
                # 仍然需要验证，增加等待时间
                consecutive_failures += 1
                current_wait_time = 127 + (consecutive_failures * 10)  # 60, 70, 80, 90...
                print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
        
        # 如果是首次打开（不是从验证恢复），执行初始化步骤
        # 1. 连按7次"ctrl -"让页面缩小
        print("\n缩小页面（按7次 Ctrl+-）...")
        for i in range(7):
            pyautogui.hotkey('ctrl', '-')
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.1)
        print("✓ 页面已缩小")
        
        # 2. 鼠标移动到(1350, 792)点击关闭初始弹窗（首次打开使用此坐标）
        print(f"\n关闭初始弹窗 ({CLOSE_POPUP_X}, {CLOSE_POPUP_Y})...")
        pyautogui.moveTo(CLOSE_POPUP_X, CLOSE_POPUP_Y, duration=0.3)
        await asyncio.sleep(0.1)
        pyautogui.click(CLOSE_POPUP_X, CLOSE_POPUP_Y)
        await asyncio.sleep(0.1)
        print("✓ 弹窗已关闭")
        
        # 标记首次打开已完成
        crawler.is_first_open = False
        
        # 遍历每个商品
        for product_idx, product_name in enumerate(products, 1):
            # 如果之前检测到验证需要跳过第一个商品，则跳过
            if skip_first_product and product_idx == 1:
                print(f"\n{'='*60}")
                print(f"⚠️  跳过商品 {product_idx}/{len(products)}: {product_name}（因验证中断）")
                print(f"{'='*60}")
                continue
            
            print(f"\n{'='*60}")
            print(f"商品 {product_idx}/{len(products)}: {product_name}")
            print(f"{'='*60}")
            
            product_products = []  # 当前商品的所有页面数据
            should_skip = False  # 初始化跳过标志
            
            # 3. 鼠标移动到搜索栏，点击并清空
            print(f"\n选中搜索栏 ({SEARCH_BAR_X}, {SEARCH_BAR_Y})...")
            pyautogui.moveTo(SEARCH_BAR_X, SEARCH_BAR_Y, duration=0.3)
            await asyncio.sleep(0.1)
            pyautogui.click(SEARCH_BAR_X, SEARCH_BAR_Y)
            await asyncio.sleep(0.1)
            
            # 全选并删除
            pyautogui.hotkey('ctrl', 'a')
            await asyncio.sleep(0.1)
            pyautogui.press('backspace')
            await asyncio.sleep(0.1)
            print("✓ 搜索栏已清空")
            
            # 4. 复制商品名称到剪贴板并粘贴
            print(f"输入商品名称: {product_name}")
            pyperclip.copy(product_name)
            await asyncio.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            await asyncio.sleep(0.1)
            print("✓ 商品名称已输入")
            
            # 5. 鼠标移动到搜索按钮，点击搜索
            print(f"点击搜索按钮 ({SEARCH_BUTTON_X}, {SEARCH_BUTTON_Y})...")
            pyautogui.moveTo(SEARCH_BUTTON_X, SEARCH_BUTTON_Y, duration=0.3)
            await asyncio.sleep(0.1)
            pyautogui.click(SEARCH_BUTTON_X, SEARCH_BUTTON_Y)
            await asyncio.sleep(0.1)  # 等待搜索结果加载
            
            # 检测是否需要验证（搜索后可能触发验证）
            while await crawler.check_verification():
                success, should_skip = await crawler.handle_verification_with_retry(
                    current_wait_time,
                    restore_state_callback=restore_page_state,
                    skip_current=True
                )
                if success:
                    current_wait_time = 127
                    consecutive_failures = 0
                    if should_skip:
                        print(f"⚠️  跳过当前商品 {product_name}，继续下一个商品")
                        skip_first_product = False  # 重置标志
                        break  # 跳出验证循环
                    break
                else:
                    consecutive_failures += 1
                    current_wait_time = 127 + (consecutive_failures * 10)
                    print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
            
            # 如果检测到验证且需要跳过，跳出商品循环
            if should_skip:
                continue
            
            print("✓ 搜索完成")
            
            # 6. 鼠标移动到(1350, 725)点击关闭搜索后的弹窗
            print(f"关闭搜索弹窗 ({CLOSE_SEARCH_POPUP_X}, {CLOSE_SEARCH_POPUP_Y})...")
            pyautogui.moveTo(CLOSE_SEARCH_POPUP_X, CLOSE_SEARCH_POPUP_Y, duration=0.3)
            await asyncio.sleep(0.1)
            pyautogui.click(CLOSE_SEARCH_POPUP_X, CLOSE_SEARCH_POPUP_Y)
            await asyncio.sleep(0.1)
            print("✓ 搜索弹窗已关闭")
            
            # 等待页面加载
            try:
                await crawler.page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass
            await asyncio.sleep(0.1)
            
            # 再次检测验证（关闭弹窗后可能触发验证）
            while await crawler.check_verification():
                success, should_skip = await crawler.handle_verification_with_retry(
                    current_wait_time,
                    restore_state_callback=restore_page_state,
                    skip_current=True
                )
                if success:
                    current_wait_time = 127
                    consecutive_failures = 0
                    if should_skip:
                        print(f"⚠️  跳过当前商品 {product_name}，继续下一个商品")
                        skip_first_product = False  # 重置标志
                        break  # 跳出验证循环
                    break
                else:
                    consecutive_failures += 1
                    current_wait_time = 127 + (consecutive_failures * 10)
                    print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
            
            # 如果检测到验证且需要跳过，跳出商品循环
            if should_skip:
                continue
            
            # 遍历每个页面
            for page_num in range(1, num_pages_per_product + 1):
                print(f"\n  {'-'*50}")
                print(f"  第 {page_num}/{num_pages_per_product} 页")
                print(f"  {'-'*50}")
                
                # 7. 进行爬取
                try:
                    # 检测是否需要验证（每页开始前检测）
                    while await crawler.check_verification():
                        success, should_skip = await crawler.handle_verification_with_retry(
                            current_wait_time,
                            restore_state_callback=restore_page_state,
                            skip_current=True
                        )
                        if success:
                            current_wait_time = 127
                            consecutive_failures = 0
                            if should_skip:
                                print(f"⚠️  跳过当前商品 {product_name}（第 {page_num} 页检测到验证），继续下一个商品")
                                skip_first_product = False  # 重置标志
                                break  # 跳出验证循环
                            break
                        else:
                            consecutive_failures += 1
                            current_wait_time = 127 + (consecutive_failures * 10)
                            print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
                    
                    # 如果检测到验证且需要跳过，跳出页面循环和商品循环
                    if should_skip:
                        break
                    
                    # 等待页面稳定
                    await asyncio.sleep(0.1)
                    try:
                        await crawler.page.wait_for_load_state('networkidle', timeout=10000)
                    except:
                        pass
                    
                    # 再次检测验证（页面加载后可能触发验证）
                    while await crawler.check_verification():
                        success, should_skip = await crawler.handle_verification_with_retry(
                            current_wait_time,
                            restore_state_callback=restore_page_state,
                            skip_current=True
                        )
                        if success:
                            current_wait_time = 127
                            consecutive_failures = 0
                            if should_skip:
                                print(f"⚠️  跳过当前商品 {product_name}（第 {page_num} 页检测到验证），继续下一个商品")
                                skip_first_product = False  # 重置标志
                                break  # 跳出验证循环
                            break
                        else:
                            consecutive_failures += 1
                            current_wait_time = 127 + (consecutive_failures * 10)
                            print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
                    
                    # 如果检测到验证且需要跳过，跳出页面循环和商品循环
                    if should_skip:
                        break
                    
                    # 如果成功爬取，重置失败计数（但保持当前等待时间，直到下次失败）
                    # 这里不重置，因为如果成功爬取，说明等待时间合适，保持即可
                    
                    # 获取HTML内容
                    max_retries = 3
                    html_content = None
                    for attempt in range(max_retries):
                        try:
                            html_content = await crawler.page.content()
                            break
                        except Exception as e:
                            if attempt < max_retries - 1:
                                await asyncio.sleep(0.1)
                                try:
                                    await crawler.page.wait_for_load_state('networkidle', timeout=5000)
                                except:
                                    pass
                            else:
                                raise
                    
                    if html_content:
                        # 保存HTML（如果需要）
                        if save_html:
                            html_file = os.path.join(output_dir, f"{product_name}_page_{page_num}.html")
                            with open(html_file, 'w', encoding='utf-8') as f:
                                f.write(html_content)
                        
                        # 提取商品信息
                        products_data = crawler.extract_products(html_content, page_num)
                        product_products.extend(products_data)
                        print(f"  ✓ 第 {page_num} 页完成，提取到 {len(products_data)} 个商品")
                        
                        # 成功爬取后，重置失败计数和等待时间
                        consecutive_failures = 0
                        current_wait_time = 127
                    else:
                        print(f"  ⚠️ 第 {page_num} 页无法获取HTML内容")
                
                except Exception as e:
                    print(f"  ⚠️ 第 {page_num} 页爬取出错: {e}")
                
                # 8. 如果不是最后一页，点击下一页
                if page_num < num_pages_per_product:
                    print(f"  点击下一页 ({NEXT_PAGE_X}, {NEXT_PAGE_Y})...")
                    pyautogui.moveTo(NEXT_PAGE_X, NEXT_PAGE_Y, duration=0.3)
                    await asyncio.sleep(0.1)
                    pyautogui.click(NEXT_PAGE_X, NEXT_PAGE_Y)
                    await asyncio.sleep(0.1)  # 等待页面跳转
                    
                    # 检测是否需要验证（翻页可能触发验证）
                    while await crawler.check_verification():
                        success, should_skip = await crawler.handle_verification_with_retry(
                            current_wait_time,
                            restore_state_callback=restore_page_state,
                            skip_current=True
                        )
                        if success:
                            current_wait_time = 127
                            consecutive_failures = 0
                            if should_skip:
                                print(f"⚠️  跳过当前商品 {product_name}（第 {page_num} 页翻页时检测到验证），继续下一个商品")
                                skip_first_product = False  # 重置标志
                                break  # 跳出验证循环
                            break
                        else:
                            consecutive_failures += 1
                            current_wait_time = 127 + (consecutive_failures * 10)
                            print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
                    
                    # 如果检测到验证且需要跳过，跳出页面循环和商品循环
                    if should_skip:
                        break
                    
                    print("  ✓ 已跳转到下一页")
            
            # 保存当前商品的数据
            if product_products:
                all_products.extend(product_products)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                # 保存JSON
                json_file = os.path.join(output_dir, f"{product_name}_products_{timestamp}.json")
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(product_products, f, ensure_ascii=False, indent=2)
                print(f"\n✓ {product_name} 的JSON数据已保存: {json_file}")
                
                # 保存CSV
                csv_file = os.path.join(output_dir, f"{product_name}_products_{timestamp}.csv")
                import csv
                with open(csv_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=product_products[0].keys())
                    writer.writeheader()
                    writer.writerows(product_products)
                print(f"✓ {product_name} 的CSV数据已保存: {csv_file}")
                
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



def get_crawled_products(data_dir='goofish_data', check_html=True):
    """
    从数据目录中提取已爬取的商品名称
    
    参数:
        data_dir: 数据目录路径
        check_html: 是否也检查 HTML 文件（如果有 HTML 文件但没有 products 文件，也算已爬取）
    
    返回:
        set: 已爬取的商品名称集合
    """
    import re
    from pathlib import Path
    
    crawled_products = set()
    data_path = Path(data_dir)
    
    if not data_path.exists():
        return crawled_products
    
    # 方法1: 查找所有 *_products_*.json 文件（排除 all_products）
    for json_file in data_path.glob('*_products_*.json'):
        # 跳过 all_products 文件
        if json_file.name.startswith('all_products'):
            continue
        # 从文件名中提取商品名称
        # 格式：商品名_products_时间戳.json
        match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
        if match:
            product_name = match.group(1)
            crawled_products.add(product_name)
    
    # 方法2: 如果 check_html=True，也检查 HTML 文件
    # 如果有商品名_page_*.html 文件，说明该商品已经爬取过（即使没有生成 products 文件）
    if check_html:
        html_products = set()
        for html_file in data_path.glob('*_page_*.html'):
            # 格式：商品名_page_页码.html
            match = re.match(r'^(.+?)_page_\d+\.html$', html_file.name)
            if match:
                product_name = match.group(1)
                html_products.add(product_name)
        
        # 合并结果
        crawled_products.update(html_products)
    
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
    print("Goofish.com 商品爬虫")
    print("="*60)

    
    # 方式2: 多个商品自动化爬取（新方式，按照流程.txt）
    products_list = ['工装裤', '紧身裤', '衬衫裙', '家居服', '帆布鞋', '芭蕾鞋', '平底鞋', '雪地靴', '托特包', '链条包', '耳环', '耳线', '金银首饰']
    num_pages = 50  # 每个商品爬取的页数
    
    # 自动检查并过滤已爬取的商品
    crawled_products = get_crawled_products('goofish_data', check_html=True)
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
        print("\n开始爬取剩余商品...")
        all_products = asyncio.run(crawl_products_automated(
            products=products_list,
            num_pages_per_product=num_pages,
            headless=False,  # 必须为False，需要显示浏览器进行鼠标操作
            save_html=True,
            output_dir='goofish_data'
        ))
        
        print(f"\n爬取完成！共获取 {len(all_products)} 个商品")

