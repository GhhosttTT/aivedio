#!/usr/bin/env python3
"""
LLM 服务启动脚本

功能：
- 启动 LLM 服务
- 测试模型加载
- 验证基本功能
- 显示服务状态
"""

import os
import sys
import time
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.llm_service import LLMService
from src.utils.logger import setup_logger, logger
from src.utils.gpu_utils import get_gpu_info, print_gpu_info


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="LLM 服务启动脚本")
    
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="模型文件路径（默认从环境变量 LLM_MODEL_PATH 读取）"
    )
    
    parser.add_argument(
        "--n-gpu-layers",
        type=int,
        default=20,
        help="GPU 加载的层数（默认 20）"
    )
    
    parser.add_argument(
        "--n-ctx",
        type=int,
        default=4096,
        help="上下文窗口大小（默认 4096）"
    )
    
    parser.add_argument(
        "--n-threads",
        type=int,
        default=8,
        help="CPU 线程数（默认 8）"
    )
    
    parser.add_argument(
        "--test",
        action="store_true",
        help="启动后运行测试"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出详细日志"
    )
    
    return parser.parse_args()


def check_environment():
    """检查环境配置"""
    logger.info("检查环境配置...")
    
    # 检查模型路径
    model_path = os.getenv("LLM_MODEL_PATH")
    if not model_path:
        logger.warning("未设置环境变量 LLM_MODEL_PATH")
        return False
    
    if not os.path.exists(model_path):
        logger.error(f"模型文件不存在: {model_path}")
        return False
    
    logger.info(f"模型路径: {model_path}")
    
    # 检查 GPU
    try:
        gpu_info = get_gpu_info()
        if gpu_info:
            logger.info(f"检测到 GPU: {gpu_info['name']}")
            logger.info(f"显存: {gpu_info['memory_total_mb']:.0f} MB")
        else:
            logger.warning("未检测到 GPU，将使用 CPU 模式")
    except Exception as e:
        logger.warning(f"无法获取 GPU 信息: {e}")
    
    return True


def start_llm_service(args):
    """
    启动 LLM 服务
    
    Args:
        args: 命令行参数
        
    Returns:
        LLMService 实例，如果失败则返回 None
    """
    logger.info("=" * 60)
    logger.info("启动 LLM 服务")
    logger.info("=" * 60)
    
    try:
        # 显示配置信息
        logger.info("配置参数:")
        logger.info(f"  模型路径: {args.model_path or os.getenv('LLM_MODEL_PATH')}")
        logger.info(f"  GPU 层数: {args.n_gpu_layers}")
        logger.info(f"  上下文窗口: {args.n_ctx}")
        logger.info(f"  CPU 线程数: {args.n_threads}")
        
        # 记录开始时间
        start_time = time.time()
        
        # 显示 GPU 信息（加载前）
        logger.info("\n加载前 GPU 状态:")
        print_gpu_info()
        
        # 创建服务实例
        logger.info("\n开始加载模型...")
        service = LLMService(
            model_path=args.model_path,
            n_gpu_layers=args.n_gpu_layers,
            n_ctx=args.n_ctx,
            n_threads=args.n_threads,
            verbose=args.verbose
        )
        
        # 计算加载时间
        load_time = time.time() - start_time
        logger.info(f"\n模型加载完成，耗时: {load_time:.2f} 秒")
        
        # 显示 GPU 信息（加载后）
        logger.info("\n加载后 GPU 状态:")
        print_gpu_info()
        
        # 显示模型信息
        model_info = service.get_model_info()
        logger.info("\n模型信息:")
        for key, value in model_info.items():
            logger.info(f"  {key}: {value}")
        
        return service
        
    except Exception as e:
        logger.error(f"启动 LLM 服务失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_basic_generation(service: LLMService):
    """
    测试基本文本生成
    
    Args:
        service: LLM 服务实例
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试 1: 基本文本生成")
    logger.info("=" * 60)
    
    try:
        prompt = "你好，请用一句话介绍你自己。"
        
        logger.info(f"\n提示词: {prompt}")
        logger.info("生成中...")
        
        start_time = time.time()
        
        response = service.generate(
            prompt=prompt,
            max_tokens=100,
            temperature=0.7
        )
        
        generation_time = time.time() - start_time
        
        logger.info(f"\n回复: {response}")
        logger.info(f"生成时间: {generation_time:.2f} 秒")
        logger.info(f"生成速度: {len(response) / generation_time:.2f} 字符/秒")
        
        return True
        
    except Exception as e:
        logger.error(f"基本文本生成测试失败: {e}")
        return False


def test_script_generation(service: LLMService):
    """
    测试剧本生成
    
    Args:
        service: LLM 服务实例
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试 2: 剧本生成")
    logger.info("=" * 60)
    
    try:
        # 构建剧本生成 Prompt
        prompt = service.generate_script_prompt(
            theme="友情",
            num_scenes=3,
            num_characters=2,
            style="现代都市"
        )
        
        logger.info(f"\nPrompt 长度: {len(prompt)} 字符")
        logger.info("生成剧本中（这可能需要 30-60 秒）...")
        
        start_time = time.time()
        
        script = service.generate(
            prompt=prompt,
            max_tokens=1024,
            temperature=0.7,
            top_p=0.9
        )
        
        generation_time = time.time() - start_time
        
        logger.info(f"\n剧本长度: {len(script)} 字符")
        logger.info(f"生成时间: {generation_time:.2f} 秒")
        logger.info(f"生成速度: {len(script) / generation_time:.2f} 字符/秒")
        logger.info(f"\n剧本预览:\n{script[:300]}...")
        
        return True
        
    except Exception as e:
        logger.error(f"剧本生成测试失败: {e}")
        return False


def test_stream_generation(service: LLMService):
    """
    测试流式生成
    
    Args:
        service: LLM 服务实例
    """
    logger.info("\n" + "=" * 60)
    logger.info("测试 3: 流式生成")
    logger.info("=" * 60)
    
    try:
        prompt = "请写一个关于人工智能的短故事（50字以内）："
        
        logger.info(f"\n提示词: {prompt}")
        logger.info("回复: ", end='', flush=True)
        
        # 定义回调函数
        tokens = []
        def on_token(token: str):
            tokens.append(token)
            print(token, end='', flush=True)
        
        start_time = time.time()
        
        response = service.generate(
            prompt=prompt,
            max_tokens=100,
            temperature=0.8,
            stream=True,
            callback=on_token
        )
        
        generation_time = time.time() - start_time
        
        print()  # 换行
        logger.info(f"\n生成时间: {generation_time:.2f} 秒")
        logger.info(f"Token 数量: {len(tokens)}")
        logger.info(f"生成速度: {len(tokens) / generation_time:.2f} tokens/秒")
        
        return True
        
    except Exception as e:
        logger.error(f"流式生成测试失败: {e}")
        return False


def run_tests(service: LLMService):
    """
    运行所有测试
    
    Args:
        service: LLM 服务实例
    """
    logger.info("\n" + "=" * 60)
    logger.info("运行功能测试")
    logger.info("=" * 60)
    
    results = {
        "基本文本生成": test_basic_generation(service),
        "剧本生成": test_script_generation(service),
        "流式生成": test_stream_generation(service)
    }
    
    # 显示测试结果
    logger.info("\n" + "=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)
    
    for test_name, result in results.items():
        status = "✓ 通过" if result else "✗ 失败"
        logger.info(f"{test_name}: {status}")
    
    # 统计
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    logger.info(f"\n总计: {passed}/{total} 测试通过")
    
    return all(results.values())


def main():
    """主函数"""
    # 解析命令行参数
    args = parse_args()
    
    # 设置日志
    setup_logger()
    
    logger.info("LLM 服务启动脚本")
    logger.info("=" * 60)
    
    # 检查环境
    if not check_environment():
        logger.error("环境检查失败，请检查配置")
        return 1
    
    # 启动服务
    service = start_llm_service(args)
    if service is None:
        logger.error("启动服务失败")
        return 1
    
    logger.info("\n✓ LLM 服务启动成功")
    
    # 运行测试
    if args.test:
        success = run_tests(service)
        
        # 清理资源
        logger.info("\n清理资源...")
        service.unload_model()
        logger.info("资源已清理")
        
        return 0 if success else 1
    else:
        logger.info("\n服务已就绪，可以开始使用")
        logger.info("提示: 使用 --test 参数运行功能测试")
        
        # 保持服务运行
        try:
            logger.info("\n按 Ctrl+C 停止服务")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n\n收到停止信号，正在关闭服务...")
            service.unload_model()
            logger.info("服务已停止")
            return 0


if __name__ == "__main__":
    sys.exit(main())
