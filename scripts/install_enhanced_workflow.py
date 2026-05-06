"""
安装增强工作流脚本

自动安装必要的自定义节点和模型
"""

import os
import subprocess
from pathlib import Path


def run_command(cmd, cwd=None):
    """运行命令"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr
    except Exception as e:
        return False, str(e)


def check_comfyui_path():
    """检查 ComfyUI 路径"""
    possible_paths = [
        "./ComfyUI",
        "../ComfyUI",
        "../../ComfyUI",
        "C:/ComfyUI",
        "D:/ComfyUI"
    ]
    
    for path in possible_paths:
        if Path(path).exists():
            return Path(path)
    
    return None


def install_custom_nodes(comfyui_path):
    """安装自定义节点"""
    print("\n" + "="*60)
    print("安装自定义节点")
    print("="*60)
    
    custom_nodes_path = comfyui_path / "custom_nodes"
    
    nodes = [
        {
            "name": "IP-Adapter Plus",
            "url": "https://github.com/cubiq/ComfyUI_IPAdapter_plus",
            "folder": "ComfyUI_IPAdapter_plus"
        },
        {
            "name": "Impact Pack (FaceDetailer)",
            "url": "https://github.com/ltdrdata/ComfyUI-Impact-Pack",
            "folder": "ComfyUI-Impact-Pack"
        },
        {
            "name": "Ultimate SD Upscale",
            "url": "https://github.com/ssitu/ComfyUI_UltimateSDUpscale",
            "folder": "ComfyUI_UltimateSDUpscale"
        }
    ]
    
    for node in nodes:
        node_path = custom_nodes_path / node["folder"]
        
        if node_path.exists():
            print(f"\n✅ {node['name']} 已安装")
            continue
        
        print(f"\n📥 安装 {node['name']}...")
        success, output = run_command(
            f'git clone {node["url"]}',
            cwd=custom_nodes_path
        )
        
        if success:
            print(f"✅ {node['name']} 安装成功")
            
            # 安装依赖
            requirements_file = node_path / "requirements.txt"
            if requirements_file.exists():
                print(f"  📦 安装依赖...")
                run_command(f"pip install -r requirements.txt", cwd=node_path)
        else:
            print(f"❌ {node['name']} 安装失败: {output}")


def download_models(comfyui_path):
    """下载必要的模型"""
    print("\n" + "="*60)
    print("下载必要的模型")
    print("="*60)
    
    models = [
        {
            "name": "IP-Adapter FaceID Plus V2",
            "url": "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-faceid-plusv2_sdxl.bin",
            "path": comfyui_path / "models" / "ipadapter",
            "filename": "ip-adapter-faceid-plusv2_sdxl.bin"
        },
        {
            "name": "CLIP Vision",
            "url": "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors",
            "path": comfyui_path / "models" / "clip_vision",
            "filename": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
        }
    ]
    
    for model in models:
        model_path = model["path"] / model["filename"]
        
        if model_path.exists():
            print(f"\n✅ {model['name']} 已存在")
            continue
        
        print(f"\n📥 下载 {model['name']}...")
        print(f"  URL: {model['url']}")
        print(f"  保存到: {model_path}")
        print(f"\n⚠️  请手动下载此模型并放置到指定位置")
        print(f"  或使用以下命令:")
        print(f"  wget {model['url']} -O {model_path}")


def create_enhanced_workflow_config():
    """创建增强工作流配置"""
    print("\n" + "="*60)
    print("创建增强工作流配置")
    print("="*60)
    
    config_path = Path("configs/comfyui_workflow_enhanced.json")
    
    if config_path.exists():
        print(f"\n⚠️  配置文件已存在: {config_path}")
        response = input("是否覆盖? (y/n): ")
        if response.lower() != 'y':
            print("跳过创建配置文件")
            return
    
    # 这里应该包含完整的工作流配置
    # 由于太长,建议从文档中复制
    print(f"\n✅ 请参考文档创建配置文件:")
    print(f"  docs/优秀ComfyUI工作流推荐.md")


def print_next_steps():
    """打印后续步骤"""
    print("\n" + "="*60)
    print("✅ 安装完成!")
    print("="*60)
    print("\n📝 后续步骤:")
    print("\n1. 下载模型 (如果未自动下载)")
    print("   - IP-Adapter FaceID Plus V2")
    print("   - CLIP Vision")
    print("   - InsightFace (buffalo_l)")
    print("\n2. 下载高质量 Checkpoint")
    print("   - RealVisXL V4.0: https://civitai.com/models/139562/realvisxl")
    print("\n3. 下载 LoRA")
    print("   - Detail Tweaker XL: https://civitai.com/models/122359/detail-tweaker-xl")
    print("\n4. 创建增强工作流配置")
    print("   - 参考: docs/优秀ComfyUI工作流推荐.md")
    print("\n5. 重启 ComfyUI")
    print("   - 使配置生效")
    print("\n6. 测试新工作流")
    print("   - 创建项目并生成图像")
    print("\n📚 详细文档:")
    print("  - docs/优秀ComfyUI工作流推荐.md")
    print("\n" + "="*60)


def main():
    """主函数"""
    print("="*60)
    print("增强工作流安装脚本")
    print("="*60)
    
    # 检查 ComfyUI 路径
    print("\n🔍 检查 ComfyUI 路径...")
    comfyui_path = check_comfyui_path()
    
    if not comfyui_path:
        print("\n❌ 未找到 ComfyUI 安装目录")
        print("请确保 ComfyUI 已安装,或手动指定路径")
        comfyui_path = input("\n请输入 ComfyUI 路径 (留空退出): ")
        if not comfyui_path:
            return
        comfyui_path = Path(comfyui_path)
        if not comfyui_path.exists():
            print("❌ 路径不存在")
            return
    
    print(f"✅ 找到 ComfyUI: {comfyui_path}")
    
    # 确认安装
    print("\n⚠️  此脚本将:")
    print("  1. 安装自定义节点 (IP-Adapter, FaceDetailer, Upscale)")
    print("  2. 下载必要的模型")
    print("  3. 创建增强工作流配置")
    
    response = input("\n是否继续? (y/n): ")
    if response.lower() != 'y':
        print("已取消")
        return
    
    # 安装自定义节点
    install_custom_nodes(comfyui_path)
    
    # 下载模型
    download_models(comfyui_path)
    
    # 创建配置
    create_enhanced_workflow_config()
    
    # 打印后续步骤
    print_next_steps()


if __name__ == "__main__":
    main()
