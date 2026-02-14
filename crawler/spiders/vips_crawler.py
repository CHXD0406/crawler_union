"""
唯品会 VIP.com 商品爬虫
封装成函数，输入商品名称和页数，爬取对应商品对应页数的信息
"""
import asyncio
import json
import os
import time
import random
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import re
import pyautogui
import pyperclip


# Cookies 文件路径
COOKIES_FILE = Path(__file__).parent / 'vips_cookies.json'


class VipsCrawler:
    """唯品会 VIP.com 爬虫类"""
    
    def __init__(self, headless=True, save_html=False, cookies_file=None):
        """
        初始化爬虫
        
        参数:
            headless: 是否无头模式（默认True）
            save_html: 是否保存HTML文件（默认False）
            cookies_file: cookies文件路径（默认使用全局配置）
        """
        self.headless = headless
        self.save_html = save_html
        self.cookies_file = Path(cookies_file) if cookies_file else COOKIES_FILE
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.is_first_open = True
        self.is_logged_in = False
        self.is_first_run = True  # 标记是否首次运行
    
    def load_cookies(self):
        """
        从文件加载 cookies
        
        返回:
            list: cookies 列表，如果文件不存在返回空列表
        """
        if self.cookies_file.exists():
            try:
                with open(self.cookies_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                print(f"✓ 已加载保存的 cookies（{len(cookies)} 个）")
                return cookies
            except Exception as e:
                print(f"⚠️ 加载 cookies 失败: {e}")
                return []
        return []
    
    async def save_cookies(self):
        """
        保存当前的 cookies 到文件
        """
        try:
            cookies = await self.context.cookies()
            with open(self.cookies_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"✓ 已保存 cookies 到: {self.cookies_file}")
            print(f"  共 {len(cookies)} 个 cookies")
        except Exception as e:
            print(f"⚠️ 保存 cookies 失败: {e}")
    
    async def check_login_status(self):
        """
        检测当前页面是否已登录
        
        返回:
            bool: True表示已登录，False表示未登录
        """
        try:
            # 检测登录状态的多种方式
            # 1. 检查是否有登录按钮（未登录时显示）
            login_button_selectors = [
                '.c-header-login__btn',
                '.J-login-btn',
                '[class*="login-btn"]',
                'a[href*="login"]',
                '.c-login-btn',
                '.header-login',
                'text=请登录',
                'text=登录',
            ]
            
            for selector in login_button_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        is_visible = await elem.is_visible()
                        text = await elem.inner_text() if is_visible else ''
                        # 如果找到明显的登录按钮，说明未登录
                        if is_visible and ('登录' in text or 'login' in text.lower()):
                            return False
                except:
                    continue
            
            # 2. 检查是否有用户昵称或头像（已登录时显示）
            logged_in_selectors = [
                '.c-header-user__name',
                '.J-user-name',
                '.user-name',
                '[class*="user-name"]',
                '[class*="nickname"]',
                '.c-header-user__avatar',
                '.user-avatar',
            ]
            
            for selector in logged_in_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        is_visible = await elem.is_visible()
                        if is_visible:
                            return True
                except:
                    continue
            
            # 3. 检查 cookies 中是否有登录相关的 cookie
            cookies = await self.context.cookies()
            login_cookie_names = ['user_id', 'userId', 'token', 'session', 'VipUID', 'mars_cid', 'mars_sid']
            for cookie in cookies:
                if any(name.lower() in cookie.get('name', '').lower() for name in login_cookie_names):
                    if cookie.get('value'):
                        return True
            
            # 4. 检查页面URL是否包含登录相关信息
            current_url = self.page.url
            if 'login' in current_url.lower() or 'signin' in current_url.lower():
                return False
            
            # 默认返回 False，让用户确认
            return False
            
        except Exception as e:
            print(f"⚠️ 检测登录状态时出错: {e}")
            return False
    
    async def wait_for_login(self):
        """
        等待用户完成登录或验证
        检测到需要登录时，等待用户操作完成后按 Enter 继续
        """
        print("\n" + "="*60)
        print("🔐 检测到需要登录或验证")
        print("="*60)
        print("请在浏览器中完成以下操作：")
        print("  1. 登录您的唯品会账号")
        print("  2. 完成可能出现的验证")
        print("  3. 确保登录成功后")
        print("-"*60)
        print(">>> 完成后请按 Enter 键继续... <<<")
        print("="*60)
        
        # 等待用户按 Enter
        await asyncio.get_event_loop().run_in_executor(None, input)
        
        print("\n正在检查登录状态...")
        await asyncio.sleep(1)
        
        # 保存登录后的 cookies
        await self.save_cookies()
        
        # 再次检查登录状态
        is_logged_in = await self.check_login_status()
        if is_logged_in:
            print("✓ 登录成功！")
            self.is_logged_in = True
        else:
            print("⚠️ 登录状态未确认，将继续尝试...")
            # 即使检测不到登录状态，也保存 cookies，用户可能已经登录
            self.is_logged_in = True
        
        return self.is_logged_in
    
    async def ensure_logged_in(self):
        """
        确保已登录状态
        首次运行时，无论是否检测到登录，都等待用户调试完成后按 Enter 继续
        """
        # 首次运行时，始终等待用户调试
        if self.is_first_run:
            print("\n" + "="*60)
            print("🔧 首次运行 - 请在浏览器中完成调试")
            print("="*60)
            print("请在浏览器中完成以下操作：")
            print("  1. 检查页面是否正常加载")
            print("  2. 如需登录，请手动登录账号")
            print("  3. 完成任何需要的验证")
            print("  4. 确认一切准备就绪后")
            print("-"*60)
            print(">>> 调试完成后请按 Enter 键继续... <<<")
            print("="*60)
            
            # 等待用户按 Enter
            await asyncio.get_event_loop().run_in_executor(None, input)
            
            print("\n正在保存状态...")
            await asyncio.sleep(1)
            
            # 保存 cookies
            await self.save_cookies()
            
            # 标记首次运行已完成
            self.is_first_run = False
            self.is_logged_in = True
            
            print("✓ 调试完成，开始运行爬虫...")
            return True
        
        # 非首次运行，检查登录状态
        self.is_logged_in = await self.check_login_status()
        
        if self.is_logged_in:
            print("✓ 检测到已登录状态")
            return True
        
        # 未登录，等待用户登录
        return await self.wait_for_login()
        
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
        
        # 加载已保存的 cookies
        saved_cookies = self.load_cookies()
        if saved_cookies:
            try:
                await self.context.add_cookies(saved_cookies)
                print("✓ 已应用保存的 cookies")
            except Exception as e:
                print(f"⚠️ 应用 cookies 失败: {e}")
        
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
    
    async def wait_for_verification(self):
        """
        等待用户完成验证
        检测到验证时，等待用户操作完成后按 Enter 继续
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
        
        # 等待用户按 Enter
        await asyncio.get_event_loop().run_in_executor(None, input)
        
        print("\n正在检查验证状态...")
        await asyncio.sleep(1)
        
        # 保存验证后的 cookies
        await self.save_cookies()
        
        # 再次检查验证状态
        still_need_verification = await self.check_verification()
        if not still_need_verification:
            print("✓ 验证已完成！")
            return True
        else:
            print("⚠️ 仍检测到验证页面，请再次尝试...")
            return False
    
    async def handle_verification_with_retry(self, wait_time=127, restore_state_callback=None, skip_current=True):
        """
        处理验证：等待用户手动完成验证，或者自动等待后重试
        
        参数:
            wait_time: 自动等待时间（秒），默认127秒
            restore_state_callback: 恢复状态的回调函数（可选）
            skip_current: 是否跳过当前商品，默认True
        
        返回:
            tuple: (success: bool, should_skip: bool)
        """
        print("\n" + "="*60)
        print("⚠️  检测到需要验证！")
        print("="*60)
        print("请选择处理方式：")
        print("  1. 在浏览器中手动完成验证，然后按 Enter")
        print("  2. 直接按 Enter 将自动等待后重新打开")
        print("="*60)
        
        # 首先尝试让用户手动验证
        verification_passed = await self.wait_for_verification()
        
        if verification_passed:
            # 用户手动完成了验证
            if restore_state_callback:
                await restore_state_callback()
            return (True, False)  # 成功，不跳过当前商品
        
        # 如果手动验证失败，询问是否自动重试
        print("\n验证未通过，是否自动等待后重新打开？")
        print(f"  输入 'y' 或按 Enter: 等待 {wait_time} 秒后重新打开")
        print("  输入 'n': 跳过当前商品")
        print("  输入 'q': 退出爬虫")
        
        user_input = await asyncio.get_event_loop().run_in_executor(None, input)
        user_input = user_input.strip().lower()
        
        if user_input == 'q':
            print("用户选择退出...")
            raise KeyboardInterrupt("用户选择退出")
        
        if user_input == 'n':
            print("跳过当前商品...")
            return (False, True)  # 失败，跳过当前商品
        
        # 自动等待后重新打开
        if skip_current:
            print("⚠️  将跳过当前商品，重新打开后爬取下一个商品")
        print(f"关闭网站，等待 {wait_time} 秒后重新打开...")
        print("="*60)
        
        try:
            await self.page.close()
            print("✓ 已关闭当前页面")
        except:
            pass
        
        print(f"等待 {wait_time} 秒...")
        for remaining in range(wait_time, 0, -1):
            print(f"  剩余 {remaining} 秒...", end='\r')
            await asyncio.sleep(1)
        print(f"  等待完成！{' '*20}")
        
        print("\n重新打开网站（完全重启浏览器以躲避验证）...")
        try:
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
            
            if self.playwright:
                try:
                    await self.playwright.stop()
                except:
                    pass
                self.playwright = None
            
            print("正在创建全新的浏览器实例和上下文...")
            await self.init_browser()
            
            url = "https://www.vip.com"
            await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
            
            await asyncio.sleep(1)
            
            print("✓ 网站已重新打开")
            
            self.is_first_open = True
            
            # 重新打开后检查登录状态
            await self.ensure_logged_in()
            
            if await self.check_verification():
                print("⚠️  重新打开后仍然需要验证")
                return (False, skip_current)
            else:
                print("✓ 重新打开后无需验证，正在恢复页面状态...")
                
                if restore_state_callback:
                    await restore_state_callback()
                
                return (True, skip_current)
                
        except Exception as e:
            print(f"⚠️  重新打开网站时出错: {e}")
            return (False, skip_current)
    
    async def close(self):
        """关闭浏览器"""
        # 关闭前保存 cookies
        if self.context:
            try:
                await self.save_cookies()
            except:
                pass
        
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
    
    def extract_products(self, html_content, page_num):
        """
        从HTML中提取商品信息（针对唯品会页面结构）
        
        HTML结构示例：
        <div class="c-goods-item J-goods-item c-goods-item--auto-width" data-product-id="6921691287833086801">
            <a href="//detail.vip.com/detail-1710614161-6921691287833086801.html">
                <div class="c-goods-item__img">
                    <img class="J-goods-item__img" src="//h2.appsimg.com/..." alt="商品名称">
                </div>
                <div class="c-goods-item__sale-price J-goods-item__sale-price"><span>¥</span>236</div>
                <div class="c-goods-item__market-price J-goods-item__market-price"><span>¥</span>839</div>
                <div class="c-goods-item__discount J-goods-item__discount">2.8折</div>
                <div class="c-goods-item__name ...">商品名称</div>
            </a>
        </div>
        
        参数:
            html_content: HTML内容
            page_num: 页码
            
        返回:
            products: 商品列表
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        products = []
        
        # 查找所有商品容器 - 带有 data-product-id 属性的 div
        product_containers = soup.find_all('div', attrs={'data-product-id': True})
        
        print(f"找到 {len(product_containers)} 个商品容器")
        
        for idx, container in enumerate(product_containers, 1):
            try:
                product = {
                    'page': page_num,
                    'index': idx
                }
                
                # 1. 提取商品ID（从 data-product-id 属性）
                product_id = container.get('data-product-id', '')
                product['product_id'] = product_id
                
                # 2. 提取商品链接（从 a 标签的 href）
                link_elem = container.find('a', href=True)
                href = ''
                if link_elem:
                    href = link_elem.get('href', '')
                    if href:
                        if href.startswith('//'):
                            href = 'https:' + href
                        elif href.startswith('/'):
                            href = 'https://www.vip.com' + href
                        href = href.replace('&amp;', '&')
                product['link'] = href
                
                # 3. 提取商品图片（从 img 标签，优先查找带 J-goods-item__img 类的）
                img_elem = None
                # 方法1: 查找带有 J-goods-item__img 类的 img
                for img in container.find_all('img'):
                    img_class = img.get('class', [])
                    if img_class:
                        class_str = ' '.join(img_class) if isinstance(img_class, list) else img_class
                        if 'J-goods-item__img' in class_str or 'goods-item__img' in class_str:
                            img_elem = img
                            break
                
                # 方法2: 在 c-goods-item__img 容器中查找
                if not img_elem:
                    for div in container.find_all('div'):
                        div_class = div.get('class', [])
                        if div_class:
                            class_str = ' '.join(div_class) if isinstance(div_class, list) else div_class
                            if 'c-goods-item__img' in class_str:
                                img_elem = div.find('img')
                                if img_elem:
                                    break
                
                product_image = ''
                title_from_img = ''
                if img_elem:
                    img_src = (img_elem.get('src', '') or 
                              img_elem.get('data-src', '') or 
                              img_elem.get('data-original', ''))
                    if img_src:
                        if img_src.startswith('//'):
                            img_src = 'https:' + img_src
                        elif img_src.startswith('/'):
                            img_src = 'https://www.vip.com' + img_src
                        product_image = img_src
                    title_from_img = img_elem.get('alt', '')
                
                product['image'] = product_image
                
                # 4. 提取商品名称（优先从 c-goods-item__name）
                title = ''
                for div in container.find_all('div'):
                    div_class = div.get('class', [])
                    if div_class:
                        class_str = ' '.join(div_class) if isinstance(div_class, list) else div_class
                        if 'c-goods-item__name' in class_str:
                            title = div.get_text(strip=True)
                            break
                if not title:
                    title = title_from_img
                
                title = ' '.join(title.split()) if title else ''
                product['title'] = title
                
                # 5. 提取售价 sale-price
                # <div class="c-goods-item__sale-price J-goods-item__sale-price"><span>¥</span>236</div>
                price = ''
                for div in container.find_all('div'):
                    div_class = div.get('class', [])
                    if div_class:
                        class_str = ' '.join(div_class) if isinstance(div_class, list) else div_class
                        if 'c-goods-item__sale-price' in class_str or 'J-goods-item__sale-price' in class_str:
                            price_text = div.get_text(strip=True)
                            price_match = re.search(r'[\d.]+', price_text)
                            if price_match:
                                price = price_match.group()
                            break
                
                product['price'] = price
                
                # 6. 提取原价 market-price
                # <div class="c-goods-item__market-price J-goods-item__market-price"><span>¥</span>839</div>
                original_price = ''
                for div in container.find_all('div'):
                    div_class = div.get('class', [])
                    if div_class:
                        class_str = ' '.join(div_class) if isinstance(div_class, list) else div_class
                        if 'c-goods-item__market-price' in class_str or 'J-goods-item__market-price' in class_str:
                            market_price_text = div.get_text(strip=True)
                            price_match = re.search(r'[\d.]+', market_price_text)
                            if price_match:
                                original_price = price_match.group()
                            break
                
                product['original_price'] = original_price
                
                # 7. 提取折扣
                # <div class="c-goods-item__discount J-goods-item__discount">2.8折</div>
                discount = ''
                for div in container.find_all('div'):
                    div_class = div.get('class', [])
                    if div_class:
                        class_str = ' '.join(div_class) if isinstance(div_class, list) else div_class
                        if 'c-goods-item__discount' in class_str or 'J-goods-item__discount' in class_str:
                            discount = div.get_text(strip=True)
                            break
                
                product['discount'] = discount
                
                # 8. 提取品牌信息
                brand = ''
                for div in container.find_all('div'):
                    div_class = div.get('class', [])
                    if div_class:
                        class_str = ' '.join(div_class) if isinstance(div_class, list) else div_class
                        if 'c-goods-item__brand' in class_str and 'logo' not in class_str:
                            brand = div.get_text(strip=True)
                            break
                
                product['brand'] = brand
                
                # 验证是否为有效商品（必须有标题和链接）
                is_valid = bool(product.get('title') and product.get('link'))
                
                if is_valid:
                    products.append(product)
                    title_preview = product['title'][:40] + '...' if len(product['title']) > 40 else product['title']
                    price_display = f"¥{product['price']}" if product.get('price') else 'N/A'
                    discount_display = f" ({product['discount']})" if product.get('discount') else ''
                    print(f"商品 {len(products)}: {title_preview} - {price_display}{discount_display}")
                
            except Exception as e:
                print(f"提取商品 {idx} 时出错: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\n总共提取到 {len(products)} 个有效商品")
        return products


async def crawl_products_automated(products, num_pages_per_product, headless=False, save_html=False, output_dir='vips_data'):
    """
    按照自动化流程爬取多个商品的多页数据
    
    参数:
        products: 商品名称列表，例如 ['手机', '衣服', '电脑']
        num_pages_per_product: 每个商品要爬取的页数
        headless: 是否无头模式（默认False）
        save_html: 是否保存HTML文件
        output_dir: 输出目录
    
    返回:
        all_products: 所有商品列表
    """
    # 坐标配置（需要根据实际页面调整）
    # 唯品会首页搜索框位置 - 需要根据实际屏幕分辨率调整
    SEARCH_BAR_X, SEARCH_BAR_Y = 960, 80  # 搜索栏（页面顶部中间）
    SEARCH_BUTTON_X, SEARCH_BUTTON_Y = 1100, 80  # 搜索按钮
    NEXT_PAGE_X, NEXT_PAGE_Y = 960, 900  # 下一页按钮（页面底部）
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    crawler = VipsCrawler(headless=headless, save_html=save_html)
    all_products = []
    
    try:
        await crawler.init_browser()
        
        # 打开首页
        url = "https://www.vip.com"
        print(f"\n{'='*60}")
        print(f"打开网页: {url}")
        print(f"{'='*60}")
        await crawler.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        # 等待页面内容加载
        await asyncio.sleep(3)
        
        # 检测登录状态，如果未登录则等待用户登录
        print("\n检测登录状态...")
        await crawler.ensure_logged_in()
        
        # 验证重试机制变量
        current_wait_time = 127
        consecutive_failures = 0
        skip_first_product = False
        
        # 定义恢复页面状态的函数
        async def restore_page_state():
            """恢复页面状态"""
            print("\n恢复页面状态...")
            await asyncio.sleep(0.5)
            print("✓ 页面已恢复")
        
        # 检测是否需要验证
        while await crawler.check_verification():
            success, _ = await crawler.handle_verification_with_retry(
                current_wait_time, 
                restore_state_callback=restore_page_state
            )
            
            if success:
                current_wait_time = 127
                consecutive_failures = 0
                break
            else:
                consecutive_failures += 1
                current_wait_time = 127 + (consecutive_failures * 10)
                print(f"连续失败 {consecutive_failures} 次，下次等待时间: {current_wait_time} 秒")
        
        # 标记首次打开已完成
        crawler.is_first_open = False
        
        # 遍历每个商品
        for product_idx, product_name in enumerate(products, 1):
            if skip_first_product and product_idx == 1:
                print(f"\n{'='*60}")
                print(f"⚠️  跳过商品 {product_idx}/{len(products)}: {product_name}（因验证中断）")
                print(f"{'='*60}")
                continue
            
            print(f"\n{'='*60}")
            print(f"商品 {product_idx}/{len(products)}: {product_name}")
            print(f"{'='*60}")
            
            product_products = []
            should_skip = False
            
            # 使用URL直接搜索（更可靠的方式）
            search_url = f"https://category.vip.com/suggest.php?keyword={product_name}&ff=search|home|head|input"
            print(f"\n打开搜索页面: {search_url}")
            
            try:
                await crawler.page.goto(search_url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(2)
                
                # 检测是否需要验证
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
                            break
                        break
                    else:
                        consecutive_failures += 1
                        current_wait_time = 127 + (consecutive_failures * 10)
                
                if should_skip:
                    continue
                
            except Exception as e:
                print(f"⚠️ 打开搜索页面失败: {e}")
                continue
            
            # 遍历每个页面
            for page_num in range(1, num_pages_per_product + 1):
                print(f"\n  {'-'*50}")
                print(f"  第 {page_num}/{num_pages_per_product} 页")
                print(f"  {'-'*50}")
                
                try:
                    # 检测验证
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
                                break
                            break
                        else:
                            consecutive_failures += 1
                            current_wait_time = 127 + (consecutive_failures * 10)
                    
                    if should_skip:
                        break
                    
                    # 等待页面稳定
                    await asyncio.sleep(1)
                    try:
                        await crawler.page.wait_for_load_state('domcontentloaded', timeout=15000)
                    except:
                        pass
                    
                    # 滚动加载动态内容
                    print("  滚动页面加载商品...")
                    await crawler.scroll_to_load(scroll_times=5)
                    
                    # 获取HTML内容
                    max_retries = 3
                    html_content = None
                    for attempt in range(max_retries):
                        try:
                            html_content = await crawler.page.content()
                            break
                        except Exception as e:
                            if attempt < max_retries - 1:
                                await asyncio.sleep(0.5)
                            else:
                                raise
                    
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
                        
                        consecutive_failures = 0
                        current_wait_time = 127
                    else:
                        print(f"  ⚠️ 第 {page_num} 页无法获取HTML内容")
                
                except Exception as e:
                    print(f"  ⚠️ 第 {page_num} 页爬取出错: {e}")
                
                # 如果不是最后一页，点击下一页
                if page_num < num_pages_per_product:
                    print(f"  点击下一页...")
                    try:
                        # 尝试使用选择器点击下一页
                        next_page_selectors = [
                            '.J-page-item.page-next-txt',
                            '.c-page__item--next',
                            'a.page-next',
                            '[class*="next"]',
                            '//a[contains(text(),"下一页")]',
                        ]
                        
                        clicked = False
                        for selector in next_page_selectors:
                            try:
                                if selector.startswith('//'):
                                    # XPath
                                    elem = await crawler.page.query_selector(f'xpath={selector}')
                                else:
                                    elem = await crawler.page.query_selector(selector)
                                
                                if elem:
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


def get_crawled_products(data_dir='vips_data', check_html=True):
    """
    从数据目录中提取已爬取的商品名称
    
    参数:
        data_dir: 数据目录路径
        check_html: 是否也检查 HTML 文件
    
    返回:
        set: 已爬取的商品名称集合
    """
    from pathlib import Path
    
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
    print("唯品会 VIP.com 商品爬虫")
    print("="*60)
    
    # 商品列表
    products_list = ['耳罩', '燕尾服', '环保包袋']
    num_pages = 20  # 每个商品爬取的页数
    
    # 自动检查并过滤已爬取的商品
    # crawled_products = get_crawled_products('vips_data', check_html=True)
    # print(f"\n已爬取的商品 ({len(crawled_products)} 个):")
    # for product in sorted(crawled_products):
    #    print(f"  - {product}")
    
    # products_list, _ = filter_products(products_list, crawled_products)
    
    # print(f"\n过滤后待爬取的商品 ({len(products_list)} 个):")
    # for product in sorted(products_list):
    #    print(f"  - {product}")
    
    if not products_list:
        print("\n所有商品已爬取完成，无需再次运行。")
    else:
        print("\n开始爬取剩余商品...")
        all_products = asyncio.run(crawl_products_automated(
            products=products_list,
            num_pages_per_product=num_pages,
            headless=False,
            save_html=True,
            output_dir='vips_data'
        ))
        
        print(f"\n爬取完成！共获取 {len(all_products)} 个商品")
