#!/usr/bin/env python3
"""
LLM 服务性能测试脚本

功能：
- 测试不同 n_gpu_layers 配置的性能
- 测试 CPU offload 功能
- 测试模型加载时间和显存占用
- 验证生成质量和速度
- 记录性能基准数据
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.llm_service import LLMService
from src.utils.logger import setup_logger, logger
from src.utils.gpu_utils import get_gpu_info, get_gpu_memory_usage


class PerformanceTest:
    """性能测试类"""
    
    def __init__(self, model_path: str, output_dir: str = "performance_results"):
        """
        初始化性能测试
        
        Args:
            model_path: 模型文件路径
            output_dir: 结果输出目录
        """
        self.model_path = model_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 测试结果
        self.results: List[Dict] = []
        
        # 测试提示词
        self.test_prompts = {
            "short": "你好，请介绍一下你自己。",
            "medium": "请写一个关于人工智能的短故事（200字左右）。",
            "long": "请详细介绍一下深度学习的发展历史和主要应用领域。"
        }
    
    def test_configuration(
        self,
        n_gpu_layers: int,
        n_ctx: int = 4096,
        n_threads: int = 8,
        test_name: Optional[str] = None
    ) -> Dict:
        """
        测试特定配置
        
        Args:
            n_gpu_layers: GPU 层数
            n_ctx: 上下文窗口大小
            n_threads: CPU 线程数
            test_name: 测试名称
            
        Returns:
            测试结果字典
        """
        test_name = test_name or f"n_gpu_layers_{n_gpu_layers}"
        
        logger.info("=" * 60)
        logger.info(f"测试配置: {test_name}")
        logger.info("=" * 60)
        logger.info(f"GPU 层数: {n_gpu_layers}")
        logger.info(f"上下文窗口: {n_ctx}")
        logger.info(f"CPU 线程数: {n_threads}")
        
        result = {
            "test_name": test_name,
            "config": {
                "n_gpu_layers": n_gpu_layers,
                "n_ctx": n_ctx,
                "n_threads": n_threads
            },
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # 获取加载前的 GPU 信息
            gpu_before = get_gpu_memory_usage()
            if gpu_before:
                result["gpu_memory_before_mb"] = gpu_before["used_mb"]
            
            # 测试模型加载
            logger.info("\n1. 测试模型加载...")
            load_start = time.time()
            
            service = LLMService(
                model_path=self.model_path,
                n_gpu_layers=n_gpu_layers,
                n_ctx=n_ctx,
                n_threads=n_threads,
                verbose=False
            )
            
            load_time = time.time() - load_start
            result["load_time_seconds"] = round(load_time, 2)
            logger.info(f"   加载时间: {load_time:.2f} 秒")
            
            # 获取加载后的 GPU 信息
            gpu_after = get_gpu_memory_usage()
            if gpu_after:
                result["gpu_memory_after_mb"] = gpu_after["used_mb"]
                if gpu_before:
                    memory_increase = gpu_after["used_mb"] - gpu_before["used_mb"]
                    result["gpu_memory_increase_mb"] = round(memory_increase, 2)
                    logger.info(f"   显存占用增加: {memory_increase:.2f} MB")
            
            # 测试不同长度的文本生成
            logger.info("\n2. 测试文本生成性能...")
            generation_results = {}
            
            for prompt_type, prompt in self.test_prompts.items():
                logger.info(f"\n   测试 {prompt_type} 提示词...")
                
                # 根据提示词类型设置 max_tokens
                max_tokens_map = {
                    "short": 100,
                    "medium": 300,
                    "long": 500
                }
                max_tokens = max_tokens_map[prompt_type]
                
                # 生成文本
                gen_start = time.time()
                
                response = service.generate(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=0.7
                )
                
                gen_time = time.time() - gen_start
                
                # 计算性能指标
                chars_per_sec = len(response) / gen_time if gen_time > 0 else 0
                
                generation_results[prompt_type] = {
                    "generation_time_seconds": round(gen_time, 2),
                    "output_length_chars": len(response),
                    "chars_per_second": round(chars_per_sec, 2),
                    "output_preview": response[:100] + "..." if len(response) > 100 else response
                }
                
                logger.info(f"      生成时间: {gen_time:.2f} 秒")
                logger.info(f"      输出长度: {len(response)} 字符")
                logger.info(f"      生成速度: {chars_per_sec:.2f} 字符/秒")
            
            result["generation_tests"] = generation_results
            
            # 测试流式生成
            logger.info("\n3. 测试流式生成...")
            stream_start = time.time()
            
            tokens = []
            def on_token(token: str):
                tokens.append(token)
            
            stream_response = service.generate(
                prompt=self.test_prompts["short"],
                max_tokens=100,
                temperature=0.7,
                stream=True,
                callback=on_token
            )
            
            stream_time = time.time() - stream_start
            tokens_per_sec = len(tokens) / stream_time if stream_time > 0 else 0
            
            result["stream_test"] = {
                "generation_time_seconds": round(stream_time, 2),
                "token_count": len(tokens),
                "tokens_per_second": round(tokens_per_sec, 2)
            }
            
            logger.info(f"   生成时间: {stream_time:.2f} 秒")
            logger.info(f"   Token 数量: {len(tokens)}")
            logger.info(f"   生成速度: {tokens_per_sec:.2f} tokens/秒")
            
            # 卸载模型
            logger.info("\n4. 卸载模型...")
            service.unload_model()
            
            # 获取卸载后的 GPU 信息
            gpu_after_unload = get_gpu_memory_usage()
            if gpu_after_unload:
                result["gpu_memory_after_unload_mb"] = gpu_after_unload["used_mb"]
            
            result["status"] = "success"
            logger.info("\n✓ 测试完成")
            
        except Exception as e:
            logger.error(f"\n✗ 测试失败: {e}")
            result["status"] = "failed"
            result["error"] = str(e)
            import traceback
            result["traceback"] = traceback.format_exc()
        
        self.results.append(result)
        return result
    
    def test_gpu_layers_range(
        self,
        layers_list: List[int],
        n_ctx: int = 4096,
        n_threads: int = 8
    ):
        """
        测试一系列 GPU 层数配置
        
        Args:
            layers_list: GPU 层数列表
            n_ctx: 上下文窗口大小
            n_threads: CPU 线程数
        """
        logger.info("\n" + "=" * 60)
        logger.info("测试不同 GPU 层数配置")
        logger.info("=" * 60)
        logger.info(f"测试配置: {layers_list}")
        
        for n_gpu_layers in layers_list:
            self.test_configuration(
                n_gpu_layers=n_gpu_layers,
                n_ctx=n_ctx,
                n_threads=n_threads,
                test_name=f"GPU_{n_gpu_layers}_layers"
            )
            
            # 等待一段时间让 GPU 冷却
            logger.info("\n等待 5 秒...")
            time.sleep(5)
    
    def test_cpu_offload(self):
        """测试 CPU offload 功能"""
        logger.info("\n" + "=" * 60)
        logger.info("测试 CPU Offload 功能")
        logger.info("=" * 60)
        
        # 测试纯 GPU（40 层）
        logger.info("\n测试 1: 纯 GPU 模式（40 层）")
        self.test_configuration(
            n_gpu_layers=40,
            test_name="pure_gpu_40_layers"
        )
        
        time.sleep(5)
        
        # 测试混合模式（20 层 GPU + 20 层 CPU）
        logger.info("\n测试 2: 混合模式（20 层 GPU + 20 层 CPU）")
        self.test_configuration(
            n_gpu_layers=20,
            test_name="hybrid_20_gpu_20_cpu"
        )
        
        time.sleep(5)
        
        # 测试纯 CPU（0 层）
        logger.info("\n测试 3: 纯 CPU 模式（0 层）")
        self.test_configuration(
            n_gpu_layers=0,
            test_name="pure_cpu_0_layers"
        )
    
    def save_results(self, filename: Optional[str] = None):
        """
        保存测试结果
        
        Args:
            filename: 输出文件名（可选）
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"llm_performance_test_{timestamp}.json"
        
        output_path = self.output_dir / filename
        
        # 添加系统信息
        output_data = {
            "system_info": self._get_system_info(),
            "test_results": self.results
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"\n测试结果已保存到: {output_path}")
        
        # 生成 Markdown 报告
        self._generate_markdown_report(output_path.with_suffix(".md"))
    
    def _get_system_info(self) -> Dict:
        """获取系统信息"""
        info = {
            "timestamp": datetime.now().isoformat(),
            "model_path": self.model_path
        }
        
        # GPU 信息
        try:
            gpu_info = get_gpu_info()
            if gpu_info:
                info["gpu"] = {
                    "name": gpu_info["name"],
                    "memory_total_mb": gpu_info["memory_total_mb"],
                    "driver_version": gpu_info.get("driver_version", "unknown")
                }
        except Exception as e:
            logger.warning(f"无法获取 GPU 信息: {e}")
        
        # CPU 信息
        try:
            import psutil
            info["cpu"] = {
                "count": psutil.cpu_count(),
                "count_physical": psutil.cpu_count(logical=False)
            }
            
            # 内存信息
            mem = psutil.virtual_memory()
            info["memory"] = {
                "total_mb": round(mem.total / 1024 / 1024, 2),
                "available_mb": round(mem.available / 1024 / 1024, 2)
            }
        except ImportError:
            pass
        
        return info
    
    def _generate_markdown_report(self, output_path: Path):
        """
        生成 Markdown 格式的测试报告
        
        Args:
            output_path: 输出文件路径
        """
        lines = []
        
        # 标题
        lines.append("# LLM 服务性能测试报告")
        lines.append("")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # 系统信息
        lines.append("## 系统信息")
        lines.append("")
        
        if self.results:
            system_info = self._get_system_info()
            
            if "gpu" in system_info:
                gpu = system_info["gpu"]
                lines.append(f"- **GPU**: {gpu['name']}")
                lines.append(f"- **显存**: {gpu['memory_total_mb']:.0f} MB")
            
            if "cpu" in system_info:
                cpu = system_info["cpu"]
                lines.append(f"- **CPU 核心数**: {cpu['count']} ({cpu['count_physical']} 物理核心)")
            
            if "memory" in system_info:
                mem = system_info["memory"]
                lines.append(f"- **内存**: {mem['total_mb']:.0f} MB")
            
            lines.append(f"- **模型路径**: {self.model_path}")
            lines.append("")
        
        # 测试结果汇总
        lines.append("## 测试结果汇总")
        lines.append("")
        lines.append("| 测试名称 | GPU 层数 | 加载时间(秒) | 显存占用(MB) | 生成速度(字符/秒) | 状态 |")
        lines.append("|---------|---------|------------|-------------|-----------------|------|")
        
        for result in self.results:
            test_name = result["test_name"]
            config = result["config"]
            n_gpu_layers = config["n_gpu_layers"]
            load_time = result.get("load_time_seconds", "N/A")
            memory_increase = result.get("gpu_memory_increase_mb", "N/A")
            
            # 计算平均生成速度
            gen_tests = result.get("generation_tests", {})
            if gen_tests:
                speeds = [t["chars_per_second"] for t in gen_tests.values()]
                avg_speed = sum(speeds) / len(speeds) if speeds else 0
                avg_speed_str = f"{avg_speed:.2f}"
            else:
                avg_speed_str = "N/A"
            
            status = "✓" if result["status"] == "success" else "✗"
            
            lines.append(f"| {test_name} | {n_gpu_layers} | {load_time} | {memory_increase} | {avg_speed_str} | {status} |")
        
        lines.append("")
        
        # 详细测试结果
        lines.append("## 详细测试结果")
        lines.append("")
        
        for result in self.results:
            lines.append(f"### {result['test_name']}")
            lines.append("")
            
            # 配置信息
            lines.append("**配置参数**:")
            lines.append("")
            config = result["config"]
            lines.append(f"- GPU 层数: {config['n_gpu_layers']}")
            lines.append(f"- 上下文窗口: {config['n_ctx']}")
            lines.append(f"- CPU 线程数: {config['n_threads']}")
            lines.append("")
            
            # 性能指标
            lines.append("**性能指标**:")
            lines.append("")
            lines.append(f"- 模型加载时间: {result.get('load_time_seconds', 'N/A')} 秒")
            lines.append(f"- 显存占用增加: {result.get('gpu_memory_increase_mb', 'N/A')} MB")
            lines.append("")
            
            # 文本生成测试
            gen_tests = result.get("generation_tests", {})
            if gen_tests:
                lines.append("**文本生成测试**:")
                lines.append("")
                lines.append("| 提示词类型 | 生成时间(秒) | 输出长度(字符) | 生成速度(字符/秒) |")
                lines.append("|-----------|------------|---------------|-----------------|")
                
                for prompt_type, test_result in gen_tests.items():
                    gen_time = test_result["generation_time_seconds"]
                    output_len = test_result["output_length_chars"]
                    speed = test_result["chars_per_second"]
                    lines.append(f"| {prompt_type} | {gen_time} | {output_len} | {speed} |")
                
                lines.append("")
            
            # 流式生成测试
            stream_test = result.get("stream_test", {})
            if stream_test:
                lines.append("**流式生成测试**:")
                lines.append("")
                lines.append(f"- 生成时间: {stream_test['generation_time_seconds']} 秒")
                lines.append(f"- Token 数量: {stream_test['token_count']}")
                lines.append(f"- 生成速度: {stream_test['tokens_per_second']} tokens/秒")
                lines.append("")
            
            # 错误信息
            if result["status"] == "failed":
                lines.append("**错误信息**:")
                lines.append("")
                lines.append(f"```\n{result.get('error', 'Unknown error')}\n```")
                lines.append("")
        
        # 性能建议
        lines.append("## 性能建议")
        lines.append("")
        lines.append(self._generate_recommendations())
        
        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        logger.info(f"Markdown 报告已保存到: {output_path}")
    
    def _generate_recommendations(self) -> str:
        """生成性能建议"""
        recommendations = []
        
        # 分析测试结果
        if not self.results:
            return "无测试结果，无法生成建议。"
        
        # 找出最佳配置
        successful_results = [r for r in self.results if r["status"] == "success"]
        
        if not successful_results:
            return "所有测试均失败，请检查配置和环境。"
        
        # 按生成速度排序
        results_with_speed = []
        for result in successful_results:
            gen_tests = result.get("generation_tests", {})
            if gen_tests:
                speeds = [t["chars_per_second"] for t in gen_tests.values()]
                avg_speed = sum(speeds) / len(speeds) if speeds else 0
                results_with_speed.append((result, avg_speed))
        
        if results_with_speed:
            results_with_speed.sort(key=lambda x: x[1], reverse=True)
            best_result, best_speed = results_with_speed[0]
            
            recommendations.append(f"### 推荐配置")
            recommendations.append("")
            recommendations.append(f"根据测试结果，推荐使用以下配置：")
            recommendations.append("")
            recommendations.append(f"- **GPU 层数**: {best_result['config']['n_gpu_layers']}")
            recommendations.append(f"- **平均生成速度**: {best_speed:.2f} 字符/秒")
            recommendations.append(f"- **显存占用**: {best_result.get('gpu_memory_increase_mb', 'N/A')} MB")
            recommendations.append("")
        
        # 通用建议
        recommendations.append("### 通用建议")
        recommendations.append("")
        recommendations.append("1. **显存充足时**：使用更多 GPU 层数（30-40 层）以获得最佳性能")
        recommendations.append("2. **显存紧张时**：使用 15-20 层 GPU，为其他模型（SD、SVD）预留显存")
        recommendations.append("3. **纯 CPU 模式**：仅在无 GPU 或显存极度不足时使用，性能较低")
        recommendations.append("4. **生产环境**：建议使用 20 层 GPU 配置，平衡性能和显存占用")
        recommendations.append("")
        
        return "\n".join(recommendations)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="LLM 服务性能测试脚本")
    
    parser.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="模型文件路径（默认从环境变量 LLM_MODEL_PATH 读取）"
    )
    
    parser.add_argument(
        "--test-type",
        type=str,
        choices=["quick", "full", "gpu-layers", "cpu-offload"],
        default="quick",
        help="测试类型（quick: 快速测试, full: 完整测试, gpu-layers: GPU 层数测试, cpu-offload: CPU offload 测试）"
    )
    
    parser.add_argument(
        "--gpu-layers",
        type=str,
        default="0,10,20,30,40",
        help="要测试的 GPU 层数列表，逗号分隔（默认: 0,10,20,30,40）"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="performance_results",
        help="结果输出目录（默认: performance_results）"
    )
    
    return parser.parse_args()


def main():
    """主函数"""
    # 解析命令行参数
    args = parse_args()
    
    # 设置日志
    setup_logger(level="INFO")
    
    logger.info("=" * 60)
    logger.info("LLM 服务性能测试")
    logger.info("=" * 60)
    
    # 获取模型路径
    model_path = args.model_path or os.getenv("LLM_MODEL_PATH")
    if not model_path:
        logger.error("未设置模型路径，请使用 --model-path 参数或设置环境变量 LLM_MODEL_PATH")
        return 1
    
    if not os.path.exists(model_path):
        logger.error(f"模型文件不存在: {model_path}")
        return 1
    
    logger.info(f"模型路径: {model_path}")
    logger.info(f"测试类型: {args.test_type}")
    logger.info(f"输出目录: {args.output_dir}")
    
    # 创建性能测试实例
    perf_test = PerformanceTest(
        model_path=model_path,
        output_dir=args.output_dir
    )
    
    try:
        # 根据测试类型执行测试
        if args.test_type == "quick":
            # 快速测试：只测试推荐配置（20 层）
            logger.info("\n执行快速测试（推荐配置：20 层 GPU）")
            perf_test.test_configuration(n_gpu_layers=20)
            
        elif args.test_type == "full":
            # 完整测试：测试所有配置
            logger.info("\n执行完整测试")
            layers_list = [int(x) for x in args.gpu_layers.split(",")]
            perf_test.test_gpu_layers_range(layers_list)
            
        elif args.test_type == "gpu-layers":
            # GPU 层数测试
            logger.info("\n执行 GPU 层数测试")
            layers_list = [int(x) for x in args.gpu_layers.split(",")]
            perf_test.test_gpu_layers_range(layers_list)
            
        elif args.test_type == "cpu-offload":
            # CPU offload 测试
            logger.info("\n执行 CPU Offload 测试")
            perf_test.test_cpu_offload()
        
        # 保存结果
        perf_test.save_results()
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ 所有测试完成")
        logger.info("=" * 60)
        
        return 0
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
