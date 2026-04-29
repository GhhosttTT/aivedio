"""
LLM 服务使用示例

演示如何使用 LLMService 生成剧本
"""

import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.llm_service import LLMService, get_llm_service
from src.utils.logger import setup_logger


def example_basic_usage():
    """示例 1：基本使用"""
    print("=" * 60)
    print("示例 1：基本使用")
    print("=" * 60)
    
    try:
        # 创建 LLM 服务实例
        # 注意：需要先设置环境变量 LLM_MODEL_PATH
        service = LLMService(
            model_path="./models/qwen2.5-14b-instruct-q4_k_m.gguf",
            n_gpu_layers=20,  # GPU 加载 20 层
            n_ctx=4096,       # 上下文窗口 4096
            n_threads=8       # CPU 线程数 8
        )
        
        # 生成简单文本
        prompt = "你好，请介绍一下你自己。"
        response = service.generate(
            prompt=prompt,
            max_tokens=100,
            temperature=0.7
        )
        
        print(f"\n提示词: {prompt}")
        print(f"回复: {response}")
        
        # 卸载模型
        service.unload_model()
        
    except Exception as e:
        print(f"错误: {e}")


def example_script_generation():
    """示例 2：生成剧本"""
    print("\n" + "=" * 60)
    print("示例 2：生成剧本")
    print("=" * 60)
    
    try:
        # 使用全局单例实例
        service = get_llm_service()
        
        # 构建剧本生成 Prompt
        prompt = service.generate_script_prompt(
            theme="都市爱情",
            outline="一个关于职场白领的爱情故事",
            num_scenes=5,
            num_characters=2,
            style="现代都市"
        )
        
        print(f"\n生成的 Prompt 长度: {len(prompt)} 字符")
        print(f"Prompt 预览:\n{prompt[:200]}...\n")
        
        # 生成剧本
        print("正在生成剧本，请稍候...")
        script = service.generate(
            prompt=prompt,
            max_tokens=2048,
            temperature=0.7,
            top_p=0.9
        )
        
        print(f"\n生成的剧本长度: {len(script)} 字符")
        print(f"剧本预览:\n{script[:500]}...\n")
        
    except Exception as e:
        print(f"错误: {e}")


def example_stream_generation():
    """示例 3：流式生成"""
    print("\n" + "=" * 60)
    print("示例 3：流式生成")
    print("=" * 60)
    
    try:
        service = get_llm_service()
        
        # 定义回调函数
        def on_token(token: str):
            print(token, end='', flush=True)
        
        prompt = "请写一个关于友情的短故事（100字以内）："
        
        print(f"\n提示词: {prompt}")
        print("回复: ", end='')
        
        # 流式生成
        response = service.generate(
            prompt=prompt,
            max_tokens=200,
            temperature=0.8,
            stream=True,
            callback=on_token
        )
        
        print("\n")
        
    except Exception as e:
        print(f"\n错误: {e}")


def example_with_stop_words():
    """示例 4：使用停止词"""
    print("\n" + "=" * 60)
    print("示例 4：使用停止词")
    print("=" * 60)
    
    try:
        service = get_llm_service()
        
        prompt = "请列举三种水果："
        
        # 使用停止词
        response = service.generate(
            prompt=prompt,
            max_tokens=100,
            temperature=0.7,
            stop=["4.", "\n\n"]  # 遇到 "4." 或两个换行符时停止
        )
        
        print(f"\n提示词: {prompt}")
        print(f"回复: {response}")
        
    except Exception as e:
        print(f"错误: {e}")


def example_model_info():
    """示例 5：获取模型信息"""
    print("\n" + "=" * 60)
    print("示例 5：获取模型信息")
    print("=" * 60)
    
    try:
        service = get_llm_service()
        
        info = service.get_model_info()
        
        print("\n模型配置信息:")
        for key, value in info.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"错误: {e}")


def main():
    """主函数"""
    # 设置日志
    setup_logger()
    
    print("\n" + "=" * 60)
    print("LLM 服务使用示例")
    print("=" * 60)
    
    # 检查环境变量
    if not os.getenv("LLM_MODEL_PATH"):
        print("\n警告: 未设置环境变量 LLM_MODEL_PATH")
        print("请先设置环境变量或创建 .env 文件")
        print("\n示例:")
        print("  export LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf")
        print("  或在 .env 文件中添加:")
        print("  LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf")
        return
    
    # 运行示例
    try:
        # 注意：这些示例需要实际的模型文件才能运行
        # 如果模型文件不存在，会抛出 FileNotFoundError
        
        # example_basic_usage()
        # example_script_generation()
        # example_stream_generation()
        # example_with_stop_words()
        example_model_info()
        
    except FileNotFoundError as e:
        print(f"\n错误: {e}")
        print("\n请确保模型文件存在于指定路径")
        print("可以从以下地址下载 Qwen2.5-14B GGUF 模型:")
        print("  https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF")
        
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 清理资源
        from src.services.llm_service import cleanup_llm_service
        cleanup_llm_service()
        print("\n资源已清理")


if __name__ == "__main__":
    main()
