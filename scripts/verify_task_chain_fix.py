"""
验证任务链修复脚本

快速检查任务链修复是否成功
"""

import sys
import inspect
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_task_signature(task_func, task_name):
    """
    检查任务函数签名是否正确
    
    Args:
        task_func: 任务函数
        task_name: 任务名称
    
    Returns:
        bool: 签名是否正确
    """
    sig = inspect.signature(task_func)
    params = list(sig.parameters.keys())
    
    print(f"\n检查 {task_name}:")
    print(f"  参数列表: {params}")
    
    # 检查是否包含 previous_result
    if 'previous_result' in params:
        print(f"  ❌ 错误: 包含 previous_result 参数")
        return False
    else:
        print(f"  ✅ 正确: 不包含 previous_result 参数")
        return True


def check_orchestrator_uses_si():
    """
    检查任务编排器是否使用 .si() 方法
    
    Returns:
        bool: 是否使用 .si()
    """
    print("\n检查任务编排器:")
    
    orchestrator_file = project_root / "src" / "services" / "task_orchestrator.py"
    
    if not orchestrator_file.exists():
        print(f"  ❌ 错误: 文件不存在 {orchestrator_file}")
        return False
    
    with open(orchestrator_file, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 检查是否使用 .si()
    si_count = content.count(".si(")
    
    # 检查是否有错误的 .s( 使用 (排除 .si( 和其他合法用法)
    import re
    # 查找 task.s( 模式 (但不是 task.si()
    wrong_s_pattern = r'_task\.s\('
    wrong_s_matches = re.findall(wrong_s_pattern, content)
    s_count = len(wrong_s_matches)
    
    print(f"  .si() 使用次数: {si_count}")
    print(f"  错误的 .s() 使用次数: {s_count}")
    
    if si_count >= 5 and s_count == 0:
        print(f"  ✅ 正确: 使用 .si() 方法")
        return True
    elif s_count > 0:
        print(f"  ❌ 错误: 仍在使用 .s() 方法")
        return False
    else:
        print(f"  ⚠️  警告: .si() 使用次数不足 (期望至少5次)")
        return si_count > 0


def main():
    """主函数"""
    print("=" * 60)
    print("任务链修复验证脚本")
    print("=" * 60)
    
    all_passed = True
    
    # 1. 检查视频生成任务
    try:
        from src.tasks.video_tasks import generate_video_task
        if not check_task_signature(generate_video_task, "视频生成任务"):
            all_passed = False
    except Exception as e:
        print(f"\n❌ 导入视频生成任务失败: {e}")
        all_passed = False
    
    # 2. 检查音频生成任务
    try:
        from src.tasks.audio_tasks import generate_audio_task
        if not check_task_signature(generate_audio_task, "音频生成任务"):
            all_passed = False
    except Exception as e:
        print(f"\n❌ 导入音频生成任务失败: {e}")
        all_passed = False
    
    # 3. 检查字幕生成任务
    try:
        from src.tasks.subtitle_tasks import generate_subtitle_task
        if not check_task_signature(generate_subtitle_task, "字幕生成任务"):
            all_passed = False
    except Exception as e:
        print(f"\n❌ 导入字幕生成任务失败: {e}")
        all_passed = False
    
    # 4. 检查合成任务
    try:
        from src.tasks.composition_tasks import compose_final_video_task
        if not check_task_signature(compose_final_video_task, "视频合成任务"):
            all_passed = False
    except Exception as e:
        print(f"\n❌ 导入视频合成任务失败: {e}")
        all_passed = False
    
    # 5. 检查任务编排器
    if not check_orchestrator_uses_si():
        all_passed = False
    
    # 总结
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 所有检查通过! 任务链修复成功!")
        print("\n下一步:")
        print("1. 重启 Celery Worker:")
        print("   celery -A src.tasks.celery_app worker --loglevel=info --pool=solo")
        print("\n2. 启动后端服务:")
        print("   python main.py")
        print("\n3. 启动前端:")
        print("   cd frontend && npm run dev")
        print("\n4. 测试完整流程:")
        print("   创建项目 → 生成剧本 → 开始制作")
    else:
        print("❌ 部分检查失败! 请检查上述错误信息")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
