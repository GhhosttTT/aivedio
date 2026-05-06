"""
AI 短剧系统服务启动脚本（带实时日志）

自动激活虚拟环境并启动所有必要服务，并在当前终端显示日志：
1. Redis (消息队列)
2. ComfyUI (图像生成)
3. FastAPI (后端 API)
4. Celery Worker (异步任务)
5. Frontend (前端开发服务器)
"""

import os
import sys
import subprocess
import time
from pathlib import Path
import signal
import threading


# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    END = '\033[0m'


def print_info(msg):
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")


def print_success(msg):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.END} {msg}")


def print_warning(msg):
    print(f"{Colors.YELLOW}[WARNING]{Colors.END} {msg}")


def print_error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.END} {msg}")


def print_service_log(service_name, msg):
    """打印服务日志"""
    color_map = {
        'Redis': Colors.CYAN,
        'ComfyUI': Colors.MAGENTA,
        'FastAPI': Colors.GREEN,
        'Celery': Colors.YELLOW,
        'Frontend': Colors.BLUE
    }
    color = color_map.get(service_name, Colors.END)
    print(f"{color}[{service_name}]{Colors.END} {msg}")


def check_python():
    """检查 Python 环境"""
    try:
        result = subprocess.run(
            [sys.executable, '--version'],
            capture_output=True,
            text=True
        )
        print_info(f"Python 版本: {result.stdout.strip()}")
        return True
    except Exception as e:
        print_error(f"Python 检查失败: {e}")
        return False


def check_virtualenv():
    """检查虚拟环境"""
    # 尝试多个可能的虚拟环境路径
    possible_paths = [
        Path(__file__).parent / '.venv',
        Path('F:\\study\\localmodel\\.venv'),
        Path.home() / 'miniconda3',
    ]
    
    for venv_path in possible_paths:
        if venv_path.exists():
            print_info(f"虚拟环境路径: {venv_path}")
            return True
    
    print_error("虚拟环境不存在")
    return False


def start_redis():
    """启动 Redis 服务"""
    print_info("启动 Redis...")
    
    try:
        # 检查是否已有 Redis 运行
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', 6379))
        sock.close()
        
        if result == 0:
            print_success("Redis 已在运行")
            return True
        
        # 在 Windows 上启动 Redis
        if sys.platform == 'win32':
            redis_cmd = ['redis-server']
        else:
            redis_cmd = ['redis-server']
        
        process = subprocess.Popen(
            redis_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # 启动线程读取日志
        def read_logs():
            for line in process.stdout:
                print_service_log('Redis', line.strip())
        
        thread = threading.Thread(target=read_logs, daemon=True)
        thread.start()
        
        print_success("Redis 已启动")
        time.sleep(2)  # 等待 Redis 初始化
        
        return True
    except FileNotFoundError:
        print_warning("未找到 redis-server 命令，跳过 Redis 启动")
        return False
    except Exception as e:
        print_error(f"启动 Redis 失败: {e}")
        return False


def start_service_in_new_window(name, cmd, cwd=None):
    """
    在新窗口中启动服务并显示日志
    
    Args:
        name: 服务名称
        cmd: 启动命令
        cwd: 工作目录
        
    Returns:
        True 如果启动成功
    """
    print_info(f"启动 {name} (新窗口)...")
    
    try:
        if sys.platform == 'win32':
            # Windows 下使用 START 命令在新窗口启动
            full_cmd = f'start "{name}" cmd /k "cd /d {cwd} && {" ".join(cmd)}"'
            subprocess.Popen(full_cmd, shell=True)
        else:
            # Linux/Mac 使用 subprocess
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
        
        print_success(f"{name} 已在新窗口启动")
        return True
    
    except Exception as e:
        print_error(f"启动 {name} 失败: {e}")
        return False


def start_service_with_logs(name, cmd, cwd=None):
    """
    启动服务并实时显示日志
    
    Args:
        name: 服务名称
        cmd: 启动命令
        cwd: 工作目录
        
    Returns:
        进程对象
    """
    print_info(f"启动 {name}...")
    
    try:
        # 设置环境变量
        env = os.environ.copy()
        
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8',
            errors='ignore'
        )
        
        # 启动线程读取日志
        def read_logs():
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        print_service_log(name, line.rstrip())
                    else:
                        break
            except Exception as e:
                print_error(f"读取 {name} 日志失败: {e}")
        
        thread = threading.Thread(target=read_logs, daemon=True)
        thread.start()
        
        print_success(f"{name} 已启动 (PID: {process.pid})")
        
        return process
    
    except Exception as e:
        print_error(f"启动 {name} 失败: {e}")
        return None


def check_port(port, timeout=10):
    """
    检查端口是否已监听
    
    Args:
        port: 端口号
        timeout: 超时时间（秒）
    """
    import socket
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            
            if result == 0:
                return True
        except Exception:
            pass
        
        time.sleep(1)
    
    return False


def check_database():
    """检查并更新数据库结构"""
    from sqlalchemy import text, inspect
    from src.database.session import engine
    
    print_info("检查数据库结构...")
    
    try:
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('characters')]
        
        needs_update = False
        if 'personality' not in columns:
            print_info("添加 personality 字段...")
            needs_update = True
        
        if 'appearance' not in columns:
            print_info("添加 appearance 字段...")
            needs_update = True
        
        if needs_update:
            with engine.connect() as conn:
                try:
                    conn.execute(text('ALTER TABLE characters ADD COLUMN personality VARCHAR(200)'))
                except Exception:
                    pass
                
                try:
                    conn.execute(text('ALTER TABLE characters ADD COLUMN appearance VARCHAR(500)'))
                except Exception:
                    pass
                
                conn.commit()
            
            print_success("数据库结构已更新")
        else:
            print_success("数据库结构正常")
        
        return True
    
    except Exception as e:
        print_error(f"数据库检查失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("AI 短剧系统 - 服务启动器（带实时日志）")
    print("=" * 60)
    print()
    
    # 获取项目根目录
    project_root = Path(__file__).parent.absolute()
    print_info(f"项目根目录: {project_root}")
    
    # 检查环境
    if not check_python():
        return False
    
    if not check_virtualenv():
        return False
    
    # 检查并更新数据库
    if not check_database():
        print_warning("数据库检查失败，但将继续启动服务")
    
    print()
    print("=" * 60)
    print("开始启动服务")
    print("=" * 60)
    print()
    
    processes = []
    
    # 1. 启动 Redis
    redis_started = start_redis()
    if redis_started:
        print_success("✓ Redis 已就绪")
    else:
        print_warning("✗ Redis 未启动，某些功能可能不可用")
    
    print()
    
    # 2. 启动 ComfyUI (新窗口)
    if start_service_in_new_window(
        name='ComfyUI',
        cmd=[sys.executable, 'main.py', '--listen', '127.0.0.1', '--port', '8188'],
        cwd=str(project_root / 'ComfyUI')
    ):
        print_info("等待 ComfyUI 初始化...")
        time.sleep(10)
    
    print()
    
    # 3. 启动 FastAPI Backend (新窗口)
    if start_service_in_new_window(
        name='FastAPI',
        cmd=[sys.executable, 'main.py'],
        cwd=str(project_root)
    ):
        print_info("等待 FastAPI 初始化...")
        time.sleep(5)
    
    print()
    
    # 4. 启动 Celery Worker (新窗口)
    if start_service_in_new_window(
        name='Celery',
        cmd=['celery', '-A', 'src.tasks.celery_app', 'worker', '--pool=solo', '--loglevel=info'],
        cwd=str(project_root)
    ):
        print_info("等待 Celery 初始化...")
        time.sleep(3)
    
    print()
    
    # 5. 启动 Frontend (新窗口)
    if start_service_in_new_window(
        name='Frontend',
        cmd=['npm', 'run', 'dev'],
        cwd=str(project_root / 'frontend')
    ):
        print_info("等待 Frontend 初始化...")
        time.sleep(5)
    
    print()
    print("=" * 60)
    print("服务启动完成")
    print("=" * 60)
    print()
    
    # 检查服务状态
    print_info("检查服务状态...")
    print()
    
    services_to_check = [
        ('Redis', 6379),
        ('ComfyUI', 8188),
        ('FastAPI', 8000),
        ('Frontend', 5173)
    ]
    
    for name, port in services_to_check:
        if check_port(port, timeout=5):
            print_success(f"✓ {name} (端口 {port}) - 运行中")
        else:
            print_warning(f"✗ {name} (端口 {port}) - 可能未就绪")
    
    print_success("✓ Celery Worker - 已在新窗口启动")
    
    print()
    print("=" * 60)
    print("访问地址")
    print("=" * 60)
    print()
    print(f"  前端界面:     http://localhost:5173")
    print(f"  后端 API:     http://localhost:8000")
    print(f"  API 文档:     http://localhost:8000/docs")
    print(f"  ComfyUI:      http://localhost:8188")
    print()
    print("=" * 60)
    print("提示")
    print("=" * 60)
    print()
    print("  - 每个服务都在独立的窗口中运行")
    print("  - 您可以在各个窗口中查看实时日志")
    print("  - 关闭服务请关闭对应的窗口")
    print()
    
    return True


if __name__ == '__main__':
    try:
        success = main()
        if success:
            print_success("\n服务运行结束\n")
            sys.exit(0)
        else:
            print_error("\n服务启动失败\n")
            sys.exit(1)
    except Exception as e:
        print_error(f"\n启动过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
