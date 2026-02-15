"""
Flask Backend API - 完美适配 main.py
"""
import sys
import os
import logging
from queue import Queue
import threading
import time
import json
import paramiko
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS

# ==================== 1. 路径与静态资源配置 (核心修复) ====================
# 获取 resources 目录的绝对路径 (兼容本地运行和打包环境)
CURRENT_FILE_PATH = os.path.abspath(__file__)

# 往上找两级：resources/backend/backend_final.py -> resources
BASE_DIR = os.path.dirname(os.path.dirname(CURRENT_FILE_PATH))

# 定义前端路径
WEB_DIR = os.path.join(BASE_DIR, 'web')
ASSETS_DIR = os.path.join(WEB_DIR, 'assets')

print(f"[Path Debug] Current Code: {CURRENT_FILE_PATH}")
print(f"[Path Debug] Resource Root: {BASE_DIR}")
print(f"[Path Debug] Web Dir: {WEB_DIR}")

# 初始化 Flask
# static_folder: 指定硬盘上静态文件的真实位置
# static_url_path: 指定浏览器访问这些文件的 URL 前缀
app = Flask(__name__,
            static_folder=ASSETS_DIR,
            static_url_path='/assets')

CORS(app)


# ==================== 2. 路由配置 ====================

@app.route('/')
def serve_index():
    """访问根路径，返回 index.html"""
    return send_from_directory(WEB_DIR, 'index.html')


@app.route('/<path:path>')
def serve_fallback(path):
    """
    兜底路由：
    1. 如果是请求 favicon.ico 或 manifest.json 等根目录文件 -> 返回文件
    2. 如果是 React 内部路由 -> 返回 index.html
    3. [关键] 如果是 assets 请求但没找到 -> 返回 404 (不要返回 index.html，否则会报语法错误)
    """
    # 安全检查：防止目录遍历
    if '..' in path or path.startswith('/'):
        return "Invalid path", 400

    # 尝试直接返回文件
    full_path = os.path.join(WEB_DIR, path)
    if os.path.exists(full_path) and os.path.isfile(full_path):
        return send_from_directory(WEB_DIR, path)

    # 如果请求的是资源文件但没找到，返回404，不要返回index.html（防止白屏报错）
    if path.startswith('assets/'):
        return "Asset not found", 404

    # 其他情况（如 React 路由），返回 index.html
    return send_from_directory(WEB_DIR, 'index.html')


# ==================== 3. 核心逻辑 (保持不变) ====================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量
log_queue = Queue()
active_tasks = {}

# 爬虫配置
SPIDERS = {
    "depop": {"file": "depop_crawler.py", "dir_name": "depop_data"},
    "ebay": {"file": "ebay_crawler.py", "dir_name": "ebay_data"},
    "goofish": {"file": "goofish_crawler.py", "dir_name": "goofish_data"},
    "vips": {"file": "vips_crawler.py", "dir_name": "vips_data"},
    "xiaomi": {"file": "xiaomiyoupin_crawler.py", "dir_name": "xiaomiyoupin_data"},
    "grailed": {"file": "grailed_crawler.py", "dir_name": "grailed_data"},
}


def create_ssh_client(server_ip, server_user, key_file_path):
    try:
        key = paramiko.RSAKey.from_private_key_file(key_file_path)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=server_ip, username=server_user, pkey=key, timeout=10)
        logger.info(f" link to {server_ip}")
        return client
    except Exception as e:
        logger.error(f" SSH filed: {e}")
        raise


def upload_file(sftp, local_path, remote_path):
    try:
        remote_path = remote_path.replace("\\", "/")
        remote_dir = os.path.dirname(remote_path)

        dirs = remote_dir.split("/")
        path = ""
        for d in dirs:
            if not d: continue
            path += "/" + d
            try:
                sftp.stat(path)
            except FileNotFoundError:
                sftp.mkdir(path)

        sftp.put(local_path, remote_path)
        logger.info(f" 上传: {os.path.basename(local_path)}")
        return True
    except Exception as e:
        logger.error(f" 上传失败: {e}")
        return False


def sync_project_files(client, local_task_file, remote_task_file, remote_code_dir):
    logger.info(f" 开始同步文件到 {remote_code_dir}...")
    sftp = client.open_sftp()

    try:
        # 1. 上传 crawler_base.py (从 spiders 目录找)
        base_crawler_path = os.path.join(BASE_DIR, "spiders", "crawler_base.py")
        if os.path.exists(base_crawler_path):
            upload_file(sftp, base_crawler_path, f"{remote_code_dir}/crawler_base.py")
        else:
            logger.warning(" 未找到 crawler_base.py")

        # 2. 上传 spiders 目录下的所有脚本
        spiders_dir = os.path.join(BASE_DIR, "spiders")
        if os.path.exists(spiders_dir):
            for f in os.listdir(spiders_dir):
                if f.endswith(".py"):
                    local_p = os.path.join(spiders_dir, f)
                    remote_p = f"{remote_code_dir}/{f}"
                    upload_file(sftp, local_p, remote_p)

        # 3. 上传任务文件
        upload_file(sftp, local_task_file, remote_task_file)

        sftp.close()
        logger.info(" 文件同步完成")
        return True
    except Exception as e:
        logger.error(f" 同步失败: {e}")
        sftp.close()
        return False


def execute_remote_crawler(task_id, config):
    try:
        log_queue.put({"task_id": task_id, "message": " 正在连接远程服务器...", "type": "info"})
        client = create_ssh_client(config["server_ip"], config["server_user"], config["key_file_path"])
        log_queue.put({"task_id": task_id, "message": " 连接成功", "type": "success"})

        # 生成临时任务文件
        local_task_file = f"temp_task_{task_id}.json"
        with open(local_task_file, 'w', encoding='utf-8') as f:
            json.dump(config["product_names"], f, ensure_ascii=False, indent=2)

        log_queue.put({"task_id": task_id, "message": " 正在上传任务文件...", "type": "info"})

        spider_config = SPIDERS[config["site_name"]]
        remote_task_path = f"{config['remote_code_dir']}/current_tasks.json"
        final_data_dir = f"{config['remote_data_root']}/{spider_config['dir_name']}"

        sync_success = sync_project_files(client, local_task_file, remote_task_path, config['remote_code_dir'])
        if not sync_success: raise Exception("文件同步失败")

        log_queue.put({"task_id": task_id, "message": " 文件上传完成", "type": "success"})

        # 处理 Cookie (如果存在)
        remote_script_name = spider_config['file']
        cookie_arg = ""
        # TODO: 这里可以扩展 Cookie 上传逻辑

        cmd = (
            f"cd {config['remote_code_dir']} && "
            f"export PYTHONPATH=$PYTHONPATH:. && "
            f"python3 {remote_script_name} "
            f"--workers {config['workers']} "
            f"--base_port {config['base_port']} "
            f"--max_count {config['max_count']} "
            f"--output_dir '{final_data_dir}' "
            f"--task_file '{remote_task_path}'"
            f"{cookie_arg}"
        )

        log_queue.put({"task_id": task_id, "message": f" 启动爬虫: {config['site_name']}", "type": "info"})
        log_queue.put({"task_id": task_id, "message": f" 执行命令: {cmd}", "type": "info"})

        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        for line in iter(stdout.readline, ""):
            if line.strip():
                log_queue.put({"task_id": task_id, "message": line.rstrip(), "type": "info"})

        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            log_queue.put({"task_id": task_id, "message": f" 任务执行出错 (Exit: {exit_status})", "type": "error"})
            active_tasks[task_id] = "failed"
        else:
            log_queue.put({"task_id": task_id, "message": " 任务执行完毕！", "type": "success"})
            active_tasks[task_id] = "completed"

        client.close()
        if os.path.exists(local_task_file): os.remove(local_task_file)

    except Exception as e:
        error_msg = f" 执行错误: {str(e)}"
        logger.error(error_msg)
        log_queue.put({"task_id": task_id, "message": error_msg, "type": "error"})
        active_tasks[task_id] = "failed"


# ==================== API 端点 ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "爬虫API正在运行"})


@app.route('/api/spiders', methods=['GET'])
def get_spiders():
    return jsonify({"spiders": list(SPIDERS.keys()), "details": SPIDERS})


@app.route('/api/validate-config', methods=['POST'])
def validate_config():
    data = request.json
    try:
        if not os.path.exists(data['key_file_path']):
            return jsonify({"valid": False, "error": "密钥文件不存在"}), 400
        client = create_ssh_client(data['server_ip'], data['server_user'], data['key_file_path'])
        client.close()
        return jsonify({"valid": True, "message": "配置有效"})
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)}), 400


@app.route('/api/execute', methods=['POST'])
def execute_crawler():
    data = request.json
    if data['site_name'] not in SPIDERS:
        return jsonify({"error": f"未知爬虫: {data['site_name']}"}), 400

    task_id = f"task_{int(time.time())}"
    active_tasks[task_id] = "running"

    config = {
        "site_name": data['site_name'],
        "product_names": data['product_names'],
        "max_count": data['max_count'],
        "workers": data['workers'],
        "base_port": data['base_port'],
        "server_ip": data['server_ip'],
        "server_user": data['server_user'],
        "key_file_path": data['key_file_path'],
        "remote_code_dir": data['remote_code_dir'],
        "remote_data_root": data['remote_data_root']
    }

    thread = threading.Thread(target=execute_remote_crawler, args=(task_id, config))
    thread.daemon = True
    thread.start()

    return jsonify({"task_id": task_id, "status": "started", "message": "任务已启动"})


@app.route('/api/logs/stream')
def stream_logs():
    def generate():
        while True:
            if not log_queue.empty():
                log = log_queue.get()
                yield f"data: {json.dumps(log, ensure_ascii=False)}\n\n"
            else:
                time.sleep(0.1)

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    # 这里的代码只有单独运行 backend_final.py 时才会执行
    # 如果通过 launcher.py 运行，这部分会被跳过，这是正确的
    print(" 独立运行模式")
    app.run(host='0.0.0.0', port=5000, debug=True)
