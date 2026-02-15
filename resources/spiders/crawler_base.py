import asyncio
import os
import subprocess
import platform
import shutil
import time

from playwright.async_api import async_playwright


class BaseCrawler:
    def __init__(self, port, headless=True):  # 默认 headless=True
        self.port = port
        self.headless = headless  # 服务器上必须为 True
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def init_browser(self):
        """标准化的浏览器启动逻辑 (自动适配 Windows/Linux)"""
        print(f"[Port {self.port}] 🔄 初始化浏览器...")

        system_name = platform.system()

        # 1. 配置路径和命令
        if system_name == "Windows":
            # Windows 配置 (保持你原有的)
            browser_executable = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
            user_data_dir = fr"C:\Users\lenovo\AppData\Local\Microsoft\Edge\User Data_{self.port}"
            # Windows 上如果你想看界面，可以去掉 --headless
            headless_arg = []
        else:
            # Linux 配置 (服务器环境)
            # 假设服务器已安装 Chrome 或 Edge，通常命令是 google-chrome 或 microsoft-edge
            # 这里的路径通常是 /usr/bin/google-chrome
            browser_executable = "google-chrome"  # 或者 "microsoft-edge"
            user_data_dir = f"/root/browser_data_{self.port}"
            # Linux 服务器必须加无头参数
            headless_arg = ["--headless", "--disable-gpu", "--no-sandbox"]

        # 确保数据目录存在
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir, exist_ok=True)

        # 2. 启动浏览器进程 (调试模式挂载)
        print(f"[Port {self.port}] 🚀 启动浏览器 ({system_name})...")

        cmd = [
                  browser_executable,
                  f"--remote-debugging-port={self.port}",
                  f"--user-data-dir={user_data_dir}",
                  "--no-first-run",
                  "--no-default-browser-check"
              ] + headless_arg

        try:
            # 使用 subprocess 启动浏览器进程
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            print(f"❌ 找不到浏览器可执行文件: {browser_executable}")
            print("请在服务器上运行: dnf install google-chrome-stable -y (或其他浏览器安装命令)")
            raise

        # 等待浏览器启动
        await asyncio.sleep(5)

        # 3. Playwright 连接
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(f"http://localhost:{self.port}")
            self.context = self.browser.contexts[0]
            if len(self.context.pages) > 0:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            await self.page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            print(f"[Port {self.port}] ✅ 连接成功")

        except Exception as e:
            print(f"[Port {self.port}] ❌ 连接失败: {e}")
            raise e

    async def close(self):
        try:
            if self.playwright: await self.playwright.stop()
            print(f"[Port {self.port}] 断开连接")
        except:
            pass

    async def crawl(self, keywords, max_count, output_dir):
        raise NotImplementedError


class MultiCrawlerManager:
    """多进程任务管理器"""

    def __init__(self, crawler_class, base_port=9222, workers=4):
        self.crawler_class = crawler_class
        self.base_port = base_port
        self.workers = workers

    def kill_all_processes(self):
        """清理残留进程"""
        print("☠️  清理残留浏览器进程...")
        if platform.system() == "Windows":
            subprocess.run("taskkill /F /IM msedge.exe /T", shell=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        else:
            # Linux 清理命令
            os.system("pkill -f google-chrome")
            os.system("pkill -f microsoft-edge")
        time.sleep(2)

    async def run(self, all_tasks, max_count, output_dir):
        self.kill_all_processes()
        chunks = [[] for _ in range(self.workers)]
        for i, task in enumerate(all_tasks):
            chunks[i % self.workers].append(task)

        coroutines = []
        print(f"\n🔥 启动 {self.workers} 个并发爬虫...")

        for i in range(self.workers):
            port = self.base_port + i
            worker_tasks = chunks[i]
            if not worker_tasks: continue

            # 实例化
            crawler_instance = self.crawler_class(port=port)
            coro = crawler_instance.crawl(worker_tasks, max_count, output_dir)
            coroutines.append(coro)

        if coroutines:
            await asyncio.gather(*coroutines, return_exceptions=True)
            print("\n✅ 所有任务完成")