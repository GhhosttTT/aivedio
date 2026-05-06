"""
创建最佳实践配置文件的脚本
"""

import json
from pathlib import Path

# 配置目录
config_dir = Path("configs/best_practices")
config_dir.mkdir(parents=True, exist_ok=True)

# 剩余的配置
practices = [
    {
        "id": "realistic-vision-indoor-006",
        "name": "Realistic Vision 室内场景",
        "description": "使用 Realistic Vision 生成真实的室内场景，光线自然，氛围感强",
        "source": "civitai",
        "source_url": "https://civitai.com/models/4201/realistic-vision",
        "author": "SG_161222",
        "applicable_scenes": ["indoor", "portrait"],
        "tags": ["室内", "自然光", "氛围", "真实"],
        "workflow_type": "basic",
        "checkpoint": "realisticVisionV60B1_v51.safetensors",
        "lora_models": ["add_detail.safetensors"],
        "sampling_steps": 25,
        "cfg_scale": 7.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "resolution": "768x1024",
        "ipadapter_weight": 0.75,
        "prompt_template": "{subject}, indoor scene, natural window light, soft shadows, cozy atmosphere, realistic, photorealistic",
        "negative_prompt": "outdoor, harsh lighting, artificial, fake, CGI, 3D render",
        "additional_params": {
            "denoise": 0.75,
            "use_facedetailer": True,
            "face_denoise": 0.40
        },
        "quality_score": 87.0,
        "realism_score": 90.0,
        "consistency_score": 85.0,
        "speed_score": 80.0,
        "overall_score": 87.1,
        "usage_count": 0,
        "success_rate": 0.0,
        "average_generation_time": 0.0,
        "version": "1.0"
    },
    {
        "id": "night-photography-007",
        "name": "夜景摄影专用",
        "description": "专门优化的夜景摄影配置，低光环境表现出色，噪点控制好",
        "source": "community",
        "source_url": None,
        "author": "Community",
        "applicable_scenes": ["night", "outdoor"],
        "tags": ["夜景", "低光", "氛围", "专业"],
        "workflow_type": "pro",
        "checkpoint": "RealVisXL_V4.0.safetensors",
        "lora_models": ["LowLightEnhancer.safetensors"],
        "sampling_steps": 32,
        "cfg_scale": 7.5,
        "sampler": "dpmpp_2m_sde",
        "scheduler": "karras",
        "resolution": "1280x720",
        "ipadapter_weight": 0.70,
        "prompt_template": "{subject}, night photography, low light, ambient lighting, city lights, long exposure, professional photography",
        "negative_prompt": "daylight, bright, overexposed, noisy, grainy, low quality",
        "additional_params": {
            "denoise": 0.80,
            "use_facedetailer": False,
            "use_upscale": True,
            "upscale_factor": 1.5
        },
        "quality_score": 85.0,
        "realism_score": 88.0,
        "consistency_score": 82.0,
        "speed_score": 68.0,
        "overall_score": 83.2,
        "usage_count": 0,
        "success_rate": 0.0,
        "average_generation_time": 0.0,
        "version": "1.0"
    },
    {
        "id": "full-body-action-008",
        "name": "全身动作场景",
        "description": "适合生成全身动作场景，动态感强，构图合理",
        "source": "github",
        "source_url": "https://github.com/comfyanonymous/ComfyUI",
        "author": "ComfyUI Community",
        "applicable_scenes": ["full_body", "action"],
        "tags": ["全身", "动作", "动态", "构图"],
        "workflow_type": "basic",
        "checkpoint": "juggernautXL_v9.safetensors",
        "lora_models": ["ActionPose.safetensors"],
        "sampling_steps": 28,
        "cfg_scale": 7.5,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "resolution": "768x1280",
        "ipadapter_weight": 0.75,
        "prompt_template": "{subject}, full body shot, dynamic pose, action scene, professional photography, motion blur",
        "negative_prompt": "static, boring pose, cropped, cut off, close up, portrait only",
        "additional_params": {
            "denoise": 0.78,
            "use_facedetailer": True,
            "face_denoise": 0.45
        },
        "quality_score": 84.0,
        "realism_score": 82.0,
        "consistency_score": 88.0,
        "speed_score": 78.0,
        "overall_score": 83.8,
        "usage_count": 0,
        "success_rate": 0.0,
        "average_generation_time": 0.0,
        "version": "1.0"
    },
    {
        "id": "artistic-style-009",
        "name": "艺术风格创作",
        "description": "艺术风格创作配置，色彩丰富，创意性强，适合艺术创作",
        "source": "civitai",
        "source_url": "https://civitai.com/models/101055/sd-xl",
        "author": "Stability AI",
        "applicable_scenes": ["general"],
        "tags": ["艺术", "创意", "色彩", "风格化"],
        "workflow_type": "sdxl",
        "checkpoint": "sd_xl_base_1.0.safetensors",
        "lora_models": ["ArtisticStyle.safetensors", "ColorEnhancer.safetensors"],
        "sampling_steps": 30,
        "cfg_scale": 9.0,
        "sampler": "dpmpp_2m_sde",
        "scheduler": "karras",
        "resolution": "1024x1024",
        "ipadapter_weight": None,
        "prompt_template": "{subject}, artistic style, vibrant colors, creative composition, masterpiece, award winning",
        "negative_prompt": "realistic, photorealistic, plain, boring, dull colors, amateur",
        "additional_params": {
            "denoise": 0.85,
            "use_facedetailer": False,
            "use_refiner": True,
            "refiner_steps": 10
        },
        "quality_score": 88.0,
        "realism_score": 70.0,
        "consistency_score": 80.0,
        "speed_score": 72.0,
        "overall_score": 79.6,
        "usage_count": 0,
        "success_rate": 0.0,
        "average_generation_time": 0.0,
        "version": "1.0"
    },
    {
        "id": "balanced-general-010",
        "name": "平衡通用配置",
        "description": "平衡的通用配置，质量、速度、一致性都不错，适合大多数场景",
        "source": "official",
        "source_url": "https://github.com/comfyanonymous/ComfyUI",
        "author": "ComfyUI Official",
        "applicable_scenes": ["general"],
        "tags": ["通用", "平衡", "稳定", "推荐"],
        "workflow_type": "basic",
        "checkpoint": "RealVisXL_V4.0.safetensors",
        "lora_models": [],
        "sampling_steps": 25,
        "cfg_scale": 7.0,
        "sampler": "dpmpp_2m",
        "scheduler": "karras",
        "resolution": "1024x1024",
        "ipadapter_weight": 0.75,
        "prompt_template": "{subject}, high quality, detailed, professional",
        "negative_prompt": "low quality, blurry, distorted, bad anatomy",
        "additional_params": {
            "denoise": 0.75,
            "use_facedetailer": True,
            "face_denoise": 0.40
        },
        "quality_score": 85.0,
        "realism_score": 85.0,
        "consistency_score": 90.0,
        "speed_score": 85.0,
        "overall_score": 86.0,
        "usage_count": 0,
        "success_rate": 0.0,
        "average_generation_time": 0.0,
        "version": "1.0"
    }
]

# 保存配置文件
for practice in practices:
    filename = f"{practice['id']}.json"
    filepath = config_dir / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(practice, f, indent=2, ensure_ascii=False)
    
    print(f"已创建: {filepath}")

print(f"\n总共创建了 {len(practices)} 个配置文件")
