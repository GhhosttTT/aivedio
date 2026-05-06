"""
AI 短剧系统服务启动脚本

自动激活虚拟环境并启动所有必要服务：
1. ComfyUI (图像生成)
2. FastAPI (后端 API)
3. Celery Worker (异步任务)
4. Frontend (前端开发服务器)
"""

import os
import sys
import subprocess
import time
from pathlib import Path
import signal


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


def start_service(name, cmd, cwd=None, delay=3):
    """
    启动服务
    
    Args:
        name: 服务名称
        cmd: 启动命令
        cwd: 工作目录
        delay: 启动后等待时间（秒）
    """
    print_info(f"启动 {name}...")
    
    try:
        # Windows 下使用 START 命令在新窗口启动
        if sys.platform == 'win32':
            # 构建完整的命令
            full_cmd = f'start "{name}" cmd /k "cd /d {cwd} && {" ".join(cmd)}"'
            subprocess.Popen(full_cmd, shell=True)
        else:
            # Linux/Mac 使用 subprocess
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        
        print_success(f"{name} 已启动")
        
        # 等待服务初始化
        if delay > 0:
            print_info(f"等待 {delay} 秒让服务初始化...")
            time.sleep(delay)
        
        return True
    
    except Exception as e:
        print_error(f"启动 {name} 失败: {e}")
        return False


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
    print("AI 短剧系统 - 服务启动器")
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
    
    # 服务配置
    services = [
        {
            'name': 'ComfyUI',
            'cmd': ['python', 'main.py', '--listen', '127.0.0.1', '--port', '8188'],
            'cwd': str(project_root / 'ComfyUI'),
            'port': 8188,
            'delay': 10
        },
        {
            'name': 'FastAPI Backend',
            'cmd': ['python', 'main.py'],
            'cwd': str(project_root),
            'port': 8000,
            'delay': 5
        },
        {
            'name': 'Celery Worker',
            'cmd': ['celery', '-A', 'src.tasks.celery_app', 'worker', '--pool=solo', '--loglevel=info'],
            'cwd': str(project_root),
            'port': None,  # Celery 不监听端口
            'delay': 3
        },
        {
            'name': 'Frontend (Vite)',
            'cmd': ['npm', 'run', 'dev'],
            'cwd': str(project_root / 'frontend'),
            'port': 5173,
            'delay': 5
        }
    ]
    
    # 启动所有服务
    started_services = []
    for service in services:
        success = start_service(
            name=service['name'],
            cmd=service['cmd'],
            cwd=service['cwd'],
            delay=service['delay']
        )
        
        if success:
            started_services.append(service)
        else:
            print_warning(f"跳过 {service['name']}")
    
    print()
    print("=" * 60)
    print("服务启动完成")
    print("=" * 60)
    print()
    
    # 检查服务状态
    print_info("检查服务状态...")
    print()
    
    for service in started_services:
        if service['port']:
            if check_port(service['port'], timeout=5):
                print_success(f"✓ {service['name']} (端口 {service['port']}) - 运行中")
            else:
                print_warning(f"✗ {service['name']} (端口 {service['port']}) - 可能未就绪")
        else:
            print_success(f"✓ {service['name']} - 已启动")
    
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
    print("  - 所有服务已在新窗口中启动")
    print("  - 关闭服务请关闭对应的窗口")
    print("  - 查看日志请在对应窗口中查看")
    print()
    
    return True


if __name__ == '__main__':
    try:
        success = main()
        if success:
            print_success("\n所有服务启动完成！\n")
            sys.exit(0)
        else:
            print_error("\n服务启动失败\n")
            sys.exit(1)
    except KeyboardInterrupt:
        print_warning("\n用户中断启动")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n启动过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
