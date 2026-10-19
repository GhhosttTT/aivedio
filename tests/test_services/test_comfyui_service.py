"""
ComfyUI 服务单元测试

测试 ComfyUIService 的核心功能
"""

import pytest
import json
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

import httpx

from src.services.comfyui_service import (
    ComfyUIService,
    ComfyUIError,
    get_comfyui_service,
    cleanup_comfyui_service
)


class TestComfyUIService:
    """ComfyUI 服务测试类"""
    
    @pytest.fixture
    def mock_workflow_config(self, tmp_path):
        """创建临时工作流配置文件"""
        workflow_config = {
            "workflow": {
                "name": "Test Workflow",
                "version": "1.0.0"
            },
            "nodes": {
                "checkpoint_loader": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "test.safetensors"}
                },
                "clip_text_encode_positive": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "", "clip": ["checkpoint_loader", 1]}
                },
                "clip_text_encode_negative": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "bad", "clip": ["checkpoint_loader", 1]}
                },
                "empty_latent_image": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": 1024, "height": 1024, "batch_size": 1}
                },
                "ksampler": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": 0,
                        "steps": 20,
                        "cfg": 7.0,
                        "sampler_name": "euler",
                        "scheduler": "normal",
                        "denoise": 1.0,
                        "model": ["checkpoint_loader", 0],
                        "positive": ["clip_text_encode_positive", 0],
                        "negative": ["clip_text_encode_negative", 0],
                        "latent_image": ["empty_latent_image", 0]
                    }
                },
                "vae_decode": {
                    "class_type": "VAEDecode",
                    "inputs": {
                        "samples": ["ksampler", 0],
                        "vae": ["checkpoint_loader", 2]
                    }
                },
                "save_image": {
                    "class_type": "SaveImage",
                    "inputs": {
                        "filename_prefix": "test",
                        "images": ["vae_decode", 0]
                    }
                }
            },
            "negative_prompt": {
                "default": "bad quality, low quality"
            }
        }
        
        config_file = tmp_path / "workflow.json"
        with open(config_file, 'w') as f:
            json.dump(workflow_config, f)
        
        return str(config_file)
    
    @pytest.fixture
    def mock_http_client(self):
        """创建 Mock HTTP 客户端"""
        return MagicMock()
    
    def test_init_success(self, mock_workflow_config, mock_http_client):
        """测试：成功初始化服务"""
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(
                base_url="http://test:8188",
                workflow_path=mock_workflow_config
            )
            
            assert service.base_url == "http://test:8188"
            config = service.workflow_manager.get_current_workflow()
            assert config.workflow.name == "Test Workflow"
    
    def test_init_workflow_not_found(self):
        """测试：工作流配置文件不存在时抛出异常"""
        with pytest.raises(ComfyUIError, match="加载工作流配置失败"):
            ComfyUIService(workflow_path="nonexistent.json")
    
    def test_check_status_success(self, mock_workflow_config, mock_http_client):
        """测试：检查服务状态成功"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_http_client.get.return_value = mock_response
        
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            
            assert service.check_status() is True
    
    def test_generate_image_empty_prompt(self, mock_workflow_config, mock_http_client):
        """测试：空提示词时抛出异常"""
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            
            with pytest.raises(ValueError, match="提示词不能为空"):
                service.generate_image(prompt="")
    
    def test_build_workflow(self, mock_workflow_config, mock_http_client):
        """测试：构建工作流"""
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            
            workflow = service._build_workflow(
                prompt="test prompt",
                negative_prompt="bad",
                width=512,
                height=512,
                steps=15,
                cfg_scale=6.0,
                seed=12345
            )
            
            # 验证工作流结构
            sampler = next(n["inputs"] for n in workflow.values() if n["class_type"] == "KSampler")
            assert workflow[sampler["positive"][0]]["inputs"]["text"] == "test prompt"
            assert workflow[sampler["negative"][0]]["inputs"]["text"] == "bad"
            latent = workflow[sampler["latent_image"][0]]["inputs"]
            assert (latent["width"], latent["height"]) == (512, 512)
            assert (sampler["steps"], sampler["cfg"], sampler["seed"]) == (15, 6.0, 12345)

    def test_video_workflow_replaces_motion_quality_placeholders(self, mock_workflow_config, mock_http_client):
        """测试：视频工作流可接收 motion/noise 调参占位符"""
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)

            workflow = {
                "1": {
                    "class_type": "VideoSampler",
                    "inputs": {
                        "motion_bucket_id": "{motion_bucket_id}",
                        "noise_aug_strength": "{noise_aug_strength}",
                        "seed": "{seed}",
                        "quality_mode": "{quality_mode}",
                        "repair_action": "{repair_action}",
                        "quality_pipeline_json": "{quality_pipeline_json}",
                        "quality_pipeline_stages": "{quality_pipeline_stages}",
                        "spatial_plan_json": "{spatial_plan_json}",
                        "spatial_control_references_json": "{spatial_control_references_json}",
                        "spatial_scene_contract_hash": "{spatial_scene_contract_hash}",
                        "continuity_reference_image": "{continuity_reference_image}",
                        "continuity_reference_fallback": "{continuity_reference_fallback}",
                        "reference_images_json": "{reference_images_json}",
                        "reference_videos_json": "{reference_videos_json}",
                        "reference_audios_json": "{reference_audios_json}",
                    },
                }
            }
            replaced = service._replace_workflow_placeholders(workflow, {
                "motion_bucket_id": 96,
                "noise_aug_strength": 0.012,
                "seed": 42,
                "quality_mode": "seed_dance_reference",
                "repair_action": "refine_video_commercial_aesthetic",
                "quality_pipeline_json": "{\"stages\": [\"platform_reference_gap_repair\"]}",
                "quality_pipeline_stages": "platform_reference_gap_repair",
                "spatial_plan_json": "{\"camera_angle\": \"over_shoulder\"}",
                "spatial_control_references_json": "{\"pose_reference_prompt\": \"locked\"}",
                "spatial_scene_contract_hash": "scene-hash",
                "continuity_reference_image": "previous-last-frame.png",
                "continuity_reference_fallback": "",
                "reference_images_json": "[\"uploaded/scene.png\"]",
                "reference_videos_json": "[\"previous.mp4\"]",
                "reference_audios_json": "[\"dialogue.wav\"]",
            })

            assert replaced["1"]["inputs"]["motion_bucket_id"] == 96
            assert replaced["1"]["inputs"]["noise_aug_strength"] == 0.012
            assert replaced["1"]["inputs"]["seed"] == 42
            assert replaced["1"]["inputs"]["quality_mode"] == "seed_dance_reference"
            assert replaced["1"]["inputs"]["repair_action"] == "refine_video_commercial_aesthetic"
            assert "platform_reference_gap_repair" in replaced["1"]["inputs"]["quality_pipeline_json"]
            assert replaced["1"]["inputs"]["quality_pipeline_stages"] == "platform_reference_gap_repair"
            assert "over_shoulder" in replaced["1"]["inputs"]["spatial_plan_json"]
            assert "pose_reference_prompt" in replaced["1"]["inputs"]["spatial_control_references_json"]
            assert replaced["1"]["inputs"]["spatial_scene_contract_hash"] == "scene-hash"
            assert replaced["1"]["inputs"]["continuity_reference_image"] == "previous-last-frame.png"
            assert replaced["1"]["inputs"]["continuity_reference_fallback"] == ""
            assert replaced["1"]["inputs"]["reference_videos_json"] == "[\"previous.mp4\"]"
            assert replaced["1"]["inputs"]["reference_audios_json"] == "[\"dialogue.wav\"]"

    def test_video_workflow_uploads_distinct_reference_images(self, mock_workflow_config, mock_http_client, tmp_path, monkeypatch):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "ReferenceStack", "inputs": {"images": "{reference_images_json}"}},
            }), encoding="utf-8")
            uploaded = []
            monkeypatch.setattr(service, "_upload_reference_image", lambda path: uploaded.append(path) or f"uploaded/{Path(path).name}")
            monkeypatch.setattr(service, "preflight", lambda _workflow: None)
            monkeypatch.setattr(service, "_run_submitted_job", lambda *args, **kwargs: str(tmp_path / "scene.mp4"))

            service.generate_video(
                prompt="identity-preserving shot",
                reference_image=str(tmp_path / "opening.png"),
                reference_images=[str(tmp_path / "opening.png"), str(tmp_path / "character.png")],
                output_path=str(tmp_path / "scene.mp4"),
                workflow_path=str(workflow_path),
            )

            assert uploaded == [str(tmp_path / "opening.png"), str(tmp_path / "character.png")]

    def test_video_workflow_rejects_unbound_media_references(self, mock_workflow_config, mock_http_client, tmp_path):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({"1": {"class_type": "VideoSampler", "inputs": {}}}), encoding="utf-8")

            with pytest.raises(ComfyUIError, match="reference_videos_json"):
                service.generate_video(
                    prompt="reference video",
                    reference_image=str(tmp_path / "opening.png"),
                    reference_videos=[str(tmp_path / "previous.mp4")],
                    output_path=str(tmp_path / "scene.mp4"),
                    workflow_path=str(workflow_path),
                )

    def test_video_workflow_uses_opening_frame_for_first_shot_continuity(self, mock_workflow_config, mock_http_client, tmp_path, monkeypatch):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "LoadImage", "inputs": {"image": "{continuity_reference_image}"}},
            }), encoding="utf-8")
            uploaded = []
            monkeypatch.setattr(service, "_upload_reference_image", lambda path: uploaded.append(path) or f"uploaded/{Path(path).name}")
            monkeypatch.setattr(service, "preflight", lambda _workflow: None)
            monkeypatch.setattr(service, "_run_submitted_job", lambda *args, **kwargs: str(tmp_path / "scene.mp4"))

            service.generate_video(
                prompt="first shot",
                reference_image=str(tmp_path / "opening.png"),
                output_path=str(tmp_path / "scene.mp4"),
                workflow_path=str(workflow_path),
            )

            assert uploaded == [str(tmp_path / "opening.png")]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
