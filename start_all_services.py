"""
AI 短剧系统服务启动脚本（独立窗口模式）

为每个服务创建独立的窗口显示日志：
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


# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'


def print_info(msg):
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")


def print_success(msg):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.END} {msg}")


def print_warning(msg):
    print(f"{Colors.YELLOW}[WARNING]{Colors.END} {msg}")


def print_error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.END} {msg}")


def start_service_in_window(name, cmd, cwd=None, delay=3, load_env=False):
    """
    在新窗口中启动服务
    
    Args:
        name: 服务名称
        cmd: 启动命令列表
        cwd: 工作目录
        delay: 等待时间（秒）
        load_env: 是否加载 .env 文件
    """
    print_info(f"启动 {name}...")
    
    try:
        if sys.platform == 'win32':
            # Windows: 使用 START 命令在新窗口启动
            cmd_str = ' '.join(cmd)
            
            # 如果需要加载 .env 文件，使用 Python 脚本加载
            if load_env and cwd:
                env_file = os.path.join(cwd, '.env')
                if os.path.exists(env_file):
                    # 创建一个临时脚本来加载环境变量并执行命令
                    temp_script = os.path.join(cwd, '_temp_start.cmd')
                    with open(temp_script, 'w', encoding='utf-8') as f:
                        f.write('@echo off\n')
                        f.write(f'cd /d {cwd}\n')
                        f.write('for /F "tokens=* delims=" %%a in (.env) do set %%a\n')
                        f.write(f'{cmd_str}\n')
                    
                    full_cmd = f'start "{name}" cmd /k "{temp_script}"'
                else:
                    full_cmd = f'start "{name}" cmd /k "cd /d {cwd} && {cmd_str}"'
            else:
                full_cmd = f'start "{name}" cmd /k "cd /d {cwd} && {cmd_str}"'
            
            subprocess.Popen(full_cmd, shell=True)
        else:
            # Linux/Mac
            subprocess.Popen(cmd, cwd=cwd)
        
        print_success(f"✓ {name} 已在新窗口启动")
        
        if delay > 0:
            time.sleep(delay)
        
        return True
    except Exception as e:
        print_error(f"✗ 启动 {name} 失败: {e}")
        return False


def check_port(port, timeout=5):
    """检查端口是否监听"""
    import socket
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                return True
        except:
            pass
        time.sleep(1)
    return False


def main():
    """主函数"""
    print("=" * 70)
    print("AI 短剧系统 - 服务启动器（独立窗口模式）")
    print("=" * 70)
    print()
    
    project_root = Path(__file__).parent.absolute()
    print_info(f"项目根目录: {project_root}")
    print()
    
    print("=" * 70)
    print("启动服务（每个服务将在独立窗口中显示日志）")
    print("=" * 70)
    print()
    
    # 1. Redis
    print_info("1. 检查 Redis...")
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    redis_running = sock.connect_ex(('127.0.0.1', 6379)) == 0
    sock.close()
    
    if redis_running:
        print_success("✓ Redis 已在运行")
    else:
        print_warning("✗ Redis 未运行，请手动启动")
    print()
    
    # 2. ComfyUI
    print_info("2. 启动 ComfyUI...")
    start_service_in_window(
        name='ComfyUI',
        cmd=[sys.executable, 'main.py', '--listen', '0.0.0.0', '--port', '8188'],
        cwd=str(project_root / 'ComfyUI'),
        delay=15  # 增加等待时间，确保完全启动
    )
    print()
    
    # 3. FastAPI
    print_info("3. 启动 FastAPI Backend...")
    start_service_in_window(
        name='FastAPI',
        cmd=[sys.executable, 'main.py'],
        cwd=str(project_root),
        delay=5,
        load_env=True  # 加载 .env 文件
    )
    print()
    
    # 4. Celery Worker
    print_info("4. 启动 Celery Worker...")
    start_service_in_window(
        name='Celery Worker',
        cmd=['celery', '-A', 'src.tasks.celery_app', 'worker', '--pool=solo', '--loglevel=info'],
        cwd=str(project_root),
        delay=3,
        load_env=True  # 加载 .env 文件
    )
    print()
    
    # 5. Frontend
    print_info("5. 启动 Frontend...")
    start_service_in_window(
        name='Frontend',
        cmd=['npm', 'run', 'dev'],
        cwd=str(project_root / 'frontend'),
        delay=5
    )
    print()
    
    # 检查服务状态
    print("=" * 70)
    print("服务状态检查")
    print("=" * 70)
    print()
    
    services = [
        ('Redis', 6379),
        ('ComfyUI', 8188),
        ('FastAPI', 8000),
        ('Frontend', 5173)
    ]
    
    for name, port in services:
        if check_port(port):
            print_success(f"✓ {name:15} (端口 {port}) - 运行中")
        else:
            print_warning(f"✗ {name:15} (端口 {port}) - 可能未就绪")
    
    print_success(f"✓ Celery Worker   - 已启动")
    print()
    
    print("=" * 70)
    print("访问地址")
    print("=" * 70)
    print()
    print(f"  📱 前端界面:     http://localhost:5173")
    print(f"  🔌 后端 API:     http://localhost:8000")
    print(f"  📖 API 文档:     http://localhost:8000/docs")
    print(f"  🎨 ComfyUI:      http://localhost:8188")
    print()
    
    print("=" * 70)
    print("说明")
    print("=" * 70)
    print()
    print("  ✓ 每个服务都在独立的命令行窗口中运行")
    print("  ✓ 您可以在各个窗口中查看实时日志")
    print("  ✓ 关闭服务只需关闭对应的窗口")
    print("  ✓ 建议按以下顺序查看日志：")
    print("    1. ComfyUI 窗口 - 图像生成日志")
    print("    2. FastAPI 窗口 - API 请求日志")
    print("    3. Celery 窗口 - 任务执行日志")
    print("    4. Frontend 窗口 - 前端开发日志")
    print()
    print("=" * 70)
    
    return True


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print_warning("\n用户中断")
    except Exception as e:
        print_error(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
