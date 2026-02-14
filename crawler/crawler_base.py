import asyncio
import os
import subprocess
import time
import math
import random
import pyautogui
from playwright.async_api import async_playwright

# 全局配置 (可根据需要修改)
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
USER_DATA_DIR_BASE = r"C:\Users\lenovo\AppData\Local\Microsoft\Edge\User Data"





class BaseCrawler:
    def __init__(self, port, headless=False):
        self.port = port
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def init_browser(self):
        """标准化的浏览器启动逻辑"""
        print(f"[Port {self.port}] 🔄 初始化浏览器...")

        # 1. 构造独立的用户目录
        unique_user_data_dir = f"{USER_DATA_DIR_BASE}_{self.port}"
        if not os.path.exists(unique_user_data_dir):
            try:
                os.makedirs(unique_user_data_dir)
            except:
                pass

        # 2. 启动 Edge 进程
        print(f"[Port {self.port}] 🚀 启动 Edge (Debug Port: {self.port})...")
        cmd = [
            EDGE_PATH,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={unique_user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        # 使用 subprocess 不阻塞主进程
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 等待浏览器完全启动
        await asyncio.sleep(4)

        # 3. 连接浏览器
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(f"http://localhost:{self.port}")
            self.context = self.browser.contexts[0]
            if len(self.context.pages) > 0:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            # 注入防检测 JS
            await self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            print(f"[Port {self.port}] ✅ 连接成功")

        except Exception as e:
            print(f"[Port {self.port}] ❌ 连接失败: {e}")
            raise e

    async def close(self):
        try:
            # 不要 close browser，否则会杀掉进程。断开 playwright 连接即可。
            if self.playwright: await self.playwright.stop()
            print(f"[Port {self.port}] 断开连接")
        except:
            pass

    # 子类需要覆盖的方法
    async def crawl(self, keywords, max_count, output_dir):
        raise NotImplementedError


class MultiCrawlerManager:
    """多进程任务管理器 (通用版)"""

    def __init__(self, crawler_class, base_port=9222, workers=4):
        self.crawler_class = crawler_class  # 传入具体的爬虫类 (如 DepopCrawler)
        self.base_port = base_port
        self.workers = workers

    def kill_all_edge_processes(self):
        print("☠️  清理残留 Edge 进程...")
        try:
            subprocess.run("taskkill /F /IM msedge.exe /T", shell=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            time.sleep(2)
        except:
            pass

    async def run(self, all_tasks, max_count, output_dir):
        self.kill_all_edge_processes()

        # 任务分配 (Round Robin)
        chunks = [[] for _ in range(self.workers)]
        for i, task in enumerate(all_tasks):
            chunks[i % self.workers].append(task)

        coroutines = []
        print(f"\n🔥 启动 {self.workers} 个并发爬虫...")

        for i in range(self.workers):
            port = self.base_port + i
            worker_tasks = chunks[i]
            if not worker_tasks: continue

            # 实例化具体的爬虫类
            crawler_instance = self.crawler_class(port=port)

            # 启动爬取任务
            coro = crawler_instance.crawl(worker_tasks, max_count, output_dir)
            coroutines.append(coro)

        if coroutines:
            await asyncio.gather(*coroutines, return_exceptions=True)
            print("\n✅ 所有任务完成")