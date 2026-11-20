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

    def test_preflight_validates_video_model_assets_beyond_checkpoints(
        self, mock_workflow_config, mock_http_client,
    ):
        response = MagicMock()
        response.json.return_value = {
            "UNETLoader": {"input": {"required": {
                "unet_name": [["wan22_fp8.safetensors"]],
            }}},
            "VAELoader": {"input": {"required": {
                "vae_name": [["wan_vae.safetensors"]],
            }}},
        }
        mock_http_client.get.return_value = response
        workflow = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan22_fp8.safetensors"}},
            "2": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_vae.safetensors"}},
        }

        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            report = service.preflight(workflow)

        assert report["node_count"] == 2
        assert {item["input"] for item in report["model_assets"]} == {"unet_name", "vae_name"}
        assert all(item["verified"] for item in report["model_assets"])

    def test_preflight_rejects_missing_unet_asset(
        self, mock_workflow_config, mock_http_client,
    ):
        response = MagicMock()
        response.json.return_value = {
            "UNETLoader": {"input": {"required": {
                "unet_name": [["installed.safetensors"]],
            }}},
        }
        mock_http_client.get.return_value = response

        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            with pytest.raises(ComfyUIError, match="missing model: unet_name=missing_fp8.safetensors"):
                service.preflight({
                    "1": {"class_type": "UNETLoader", "inputs": {
                        "unet_name": "missing_fp8.safetensors",
                    }},
                })
    
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
                        "driving_video": "{driving_video}",
                        "performance_audio": "{performance_audio}",
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
                "driving_video": "driving.mp4",
                "performance_audio": "dialogue.wav",
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
            assert replaced["1"]["inputs"]["driving_video"] == "driving.mp4"
            assert replaced["1"]["inputs"]["performance_audio"] == "dialogue.wav"

    def test_avatar_route_rejects_workflow_without_native_audio_binding(
        self, mock_workflow_config, mock_http_client, tmp_path,
    ):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "avatar.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "ReferenceAudioMetadata", "inputs": {
                    "audios": "{reference_audios_json}",
                }},
            }), encoding="utf-8")
            opening = tmp_path / "opening.png"
            audio = tmp_path / "dialogue.wav"
            opening.write_bytes(b"image")
            audio.write_bytes(b"audio")

            with pytest.raises(ComfyUIError, match="performance_audio"):
                service.generate_video(
                    prompt="dialogue reaction",
                    reference_image=str(opening),
                    reference_audios=[str(audio)],
                    output_path=str(tmp_path / "scene.mp4"),
                    workflow_path=str(workflow_path),
                    local_engine_route={
                        "model_profile": "hunyuanvideo_avatar",
                        "requested_capabilities": ["identity_reference", "performance_control"],
                    },
                )

    def test_wan_animate_binds_uploaded_driving_video_to_real_node(
        self, mock_workflow_config, mock_http_client, tmp_path, monkeypatch,
    ):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "animate.json"
            workflow_path.write_text(json.dumps({
                "image": {"class_type": "LoadImage", "inputs": {"image": "{reference_image}"}},
                "video": {"class_type": "VHS_LoadVideo", "inputs": {"video": "{driving_video}"}},
                "output": {"class_type": "SaveVideo", "inputs": {}},
            }), encoding="utf-8")
            opening = tmp_path / "opening.png"
            driving = tmp_path / "driving.mp4"
            opening.write_bytes(b"image")
            driving.write_bytes(b"video")
            captured = {}
            monkeypatch.setattr(service, "_upload_reference_image", lambda _path: "input/opening.png")
            monkeypatch.setattr(service, "_upload_input_media", lambda _path: "input/driving.mp4")
            monkeypatch.setattr(service, "preflight", lambda _workflow: None)
            monkeypatch.setattr(
                service, "_run_submitted_job",
                lambda workflow, *_args, **_kwargs: captured.setdefault("workflow", workflow) or str(tmp_path / "scene.mp4"),
            )

            service.generate_video(
                prompt="controlled walk",
                reference_image=str(opening),
                reference_videos=[str(driving)],
                output_path=str(tmp_path / "scene.mp4"),
                workflow_path=str(workflow_path),
                local_engine_route={
                    "model_profile": "wan_2_2_animate",
                    "requested_capabilities": ["identity_reference", "motion_control"],
                },
            )

            assert captured["workflow"]["video"]["inputs"]["video"] == "input/driving.mp4"

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

    def test_video_workflow_binds_frame_indexed_keyframes(
        self, mock_workflow_config, mock_http_client, tmp_path, monkeypatch,
    ):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "LoadImage", "inputs": {"image": "{reference_image}"}},
                "2": {"class_type": "TemporalConditioning", "inputs": {
                    "images": "{keyframe_images}",
                    "indices": "{keyframe_indices}",
                    "strengths": "{keyframe_strengths}",
                    "roles": "{keyframe_roles}",
                }},
                "3": {"class_type": "SaveVideo", "inputs": {}},
            }), encoding="utf-8")
            opening = tmp_path / "opening.png"
            middle = tmp_path / "middle.png"
            early = tmp_path / "early.png"
            opening.write_bytes(b"opening")
            middle.write_bytes(b"middle")
            early.write_bytes(b"early")
            captured = []
            monkeypatch.setattr(
                service,
                "_upload_reference_image",
                lambda path: f"uploaded/{Path(path).name}",
            )
            monkeypatch.setattr(service, "preflight", lambda graph: captured.append(graph))
            monkeypatch.setattr(
                service, "_run_submitted_job", lambda *args, **kwargs: str(tmp_path / "scene.mp4"),
            )

            service.generate_video(
                prompt="controlled performance",
                reference_image=str(opening),
                keyframe_images=[
                    {
                        "path": str(middle),
                        "frame_index": 64,
                        "strength": 0.88,
                        "role": "action_peak",
                    },
                    {
                        "path": str(early),
                        "frame_index": 30,
                        "strength": 0.82,
                        "role": "action_commitment",
                    },
                ],
                output_path=str(tmp_path / "scene.mp4"),
                workflow_path=str(workflow_path),
                duration_seconds=5,
                fps=24,
            )

            temporal = captured[0]["2"]["inputs"]
            assert temporal["images"] == ["uploaded/early.png", "uploaded/middle.png"]
            assert temporal["indices"] == [30, 64]
            assert temporal["strengths"] == [0.82, 0.88]
            assert temporal["roles"] == ["action_commitment", "action_peak"]

    def test_video_workflow_rejects_unbound_middle_keyframe(
        self, mock_workflow_config, mock_http_client, tmp_path,
    ):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "SaveVideo", "inputs": {}},
            }), encoding="utf-8")
            middle = tmp_path / "middle.png"
            middle.write_bytes(b"middle")

            with pytest.raises(ComfyUIError, match="keyframe_images"):
                service.generate_video(
                    prompt="controlled performance",
                    reference_image=str(tmp_path / "opening.png"),
                    keyframe_images=[{"path": str(middle), "frame_index": 24}],
                    output_path=str(tmp_path / "scene.mp4"),
                    workflow_path=str(workflow_path),
                    duration_seconds=4,
                    fps=24,
                )

    def test_temporal_workflow_merges_end_image_as_final_keyframe(
        self, mock_workflow_config, mock_http_client, tmp_path, monkeypatch,
    ):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "ltx_video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "LoadImage", "inputs": {"image": "{reference_image}"}},
                "2": {"class_type": "VideoConditionByKeyframeIndex", "inputs": {
                    "images": "{keyframe_images}",
                    "indices": "{keyframe_indices}",
                    "roles": "{keyframe_roles}",
                }},
                "3": {"class_type": "SaveVideo", "inputs": {}},
            }), encoding="utf-8")
            opening = tmp_path / "opening.png"
            middle = tmp_path / "middle.png"
            ending = tmp_path / "ending.png"
            for path in (opening, middle, ending):
                path.write_bytes(path.stem.encode("utf-8"))
            captured = []
            uploaded = []
            monkeypatch.setattr(
                service,
                "_upload_reference_image",
                lambda path: uploaded.append(str(path)) or f"uploaded/{Path(path).name}",
            )
            monkeypatch.setattr(service, "preflight", lambda graph: captured.append(graph))
            monkeypatch.setattr(
                service, "_run_submitted_job", lambda *args, **kwargs: str(tmp_path / "scene.mp4"),
            )

            service.generate_video(
                prompt="keyframed action",
                reference_image=str(opening),
                end_image=str(ending),
                keyframe_images=[{
                    "path": str(middle), "frame_index": 48,
                    "strength": 0.85, "role": "action_peak",
                }],
                output_path=str(tmp_path / "scene.mp4"),
                workflow_path=str(workflow_path),
                duration_seconds=5,
                fps=24,
            )

            temporal = captured[0]["2"]["inputs"]
            assert temporal["indices"] == [48, 119]
            assert temporal["roles"] == ["action_peak", "closing_frame"]
            assert temporal["images"] == ["uploaded/middle.png", "uploaded/ending.png"]
            assert uploaded.count(str(ending)) == 1

    def test_video_workflow_rejects_missing_bound_media(self, mock_workflow_config, mock_http_client, tmp_path):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "ReferenceStack", "inputs": {
                    "videos": "{reference_videos_json}",
                    "audios": "{reference_audios_json}",
                }},
            }), encoding="utf-8")

            with pytest.raises(ComfyUIError, match="参考视频不存在"):
                service.generate_video(
                    prompt="validated references",
                    reference_image=str(tmp_path / "opening.png"),
                    reference_videos=[str(tmp_path / "missing.mp4")],
                    output_path=str(tmp_path / "scene.mp4"),
                    workflow_path=str(workflow_path),
                )

    def test_video_workflow_uploads_video_and_audio_references(self, mock_workflow_config, mock_http_client, tmp_path, monkeypatch):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({
                "1": {"class_type": "ReferenceStack", "inputs": {
                    "videos": "{reference_videos_json}",
                    "audios": "{reference_audios_json}",
                }},
            }), encoding="utf-8")
            opening = tmp_path / "opening.png"
            previous = tmp_path / "previous.mp4"
            dialogue = tmp_path / "dialogue.wav"
            for path in (opening, previous, dialogue):
                path.write_bytes(b"media")
            uploaded = []
            monkeypatch.setattr(service, "_upload_input_media", lambda path: uploaded.append(path) or f"input/{Path(path).name}")
            monkeypatch.setattr(service, "preflight", lambda _workflow: None)
            monkeypatch.setattr(service, "_run_submitted_job", lambda *args, **kwargs: str(tmp_path / "scene.mp4"))

            service.generate_video(
                prompt="multimodal shot",
                reference_image=str(opening),
                reference_videos=[str(previous)],
                reference_audios=[str(dialogue)],
                output_path=str(tmp_path / "scene.mp4"),
                workflow_path=str(workflow_path),
            )

            assert uploaded == [str(opening), str(previous), str(dialogue)]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"end_image": "end.png"}, "last_frame"),
            ({"continuity_reference_image": "previous.png"}, "连续帧"),
            ({"shot_plan": {"spatial_plan": {"camera_angle": "low"}}}, "spatial_plan_json"),
        ],
    )
    def test_video_workflow_rejects_unbound_control_contracts(self, mock_workflow_config, mock_http_client, tmp_path, kwargs, message):
        with patch('src.services.comfyui_service.httpx.Client', return_value=mock_http_client):
            service = ComfyUIService(workflow_path=mock_workflow_config)
            workflow_path = tmp_path / "video.json"
            workflow_path.write_text(json.dumps({"1": {"class_type": "VideoSampler", "inputs": {}}}), encoding="utf-8")

            with pytest.raises(ComfyUIError, match=message):
                service.generate_video(
                    prompt="controlled shot",
                    reference_image=str(tmp_path / "opening.png"),
                    output_path=str(tmp_path / "scene.mp4"),
                    workflow_path=str(workflow_path),
                    **kwargs,
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


def test_video_frame_aliases_follow_requested_duration(tmp_path, monkeypatch):
    service = object.__new__(ComfyUIService)
    path = tmp_path / "video.json"
    path.write_text(json.dumps({
        "sampler": {"class_type": "VideoSampler", "inputs": {
            "length": "{num_frames}", "frames": "{frame_count}",
            "video_frames": "{video_frames}", "fps": "{fps}",
        }},
        "save": {"class_type": "SaveVideo", "inputs": {}},
    }), encoding="utf-8")
    captured = []
    monkeypatch.setattr(service, "_upload_reference_image", lambda _: "input/first.png")
    monkeypatch.setattr(service, "preflight", lambda graph: captured.append(graph))
    monkeypatch.setattr(service, "_run_submitted_job", lambda *args, **kwargs: "clip.mp4")
    from src.config import settings
    monkeypatch.setattr(settings, "COMFYUI_VIDEO_OUTPUT_NODE", "")

    service.generate_video(
        prompt="shot", reference_image="first.png", output_path=str(tmp_path / "clip.mp4"),
        workflow_path=str(path), duration_seconds=5.05, fps=16,
    )

    assert captured[0]["sampler"]["inputs"] == {
        "length": 81, "frames": 81, "video_frames": 81, "fps": 16,
    }


def test_standard_wan_api_workflow_uses_sidecar_node_bindings(tmp_path, monkeypatch):
    service = object.__new__(ComfyUIService)
    path = tmp_path / "wan_api.json"
    path.write_text(json.dumps({
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "image": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "latent": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
            "width": 704, "height": 1280, "length": 81,
        }},
        "sampler": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
        "save": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "old", "fps": 16}},
    }), encoding="utf-8")
    (tmp_path / "wan_api.bindings.json").write_text(json.dumps({
        "bindings": {
            "positive_prompt": {"node_id": "positive", "input": "text"},
            "negative_prompt": {"node_id": "negative", "input": "text"},
            "reference_image": {"node_id": "image", "input": "image"},
            "width": {"node_id": "latent", "input": "width"},
            "height": {"node_id": "latent", "input": "height"},
            "num_frames": {"node_id": "latent", "input": "length"},
            "seed": {"node_id": "sampler", "input": "noise_seed"},
            "fps": {"node_id": "save", "input": "fps"},
            "output_prefix": {"node_id": "save", "input": "filename_prefix"}
        }
    }), encoding="utf-8")
    captured = []
    monkeypatch.setattr(service, "_upload_reference_image", lambda _: "input/first.png")
    monkeypatch.setattr(service, "preflight", lambda graph: captured.append(graph))
    monkeypatch.setattr(service, "_run_submitted_job", lambda *args, **kwargs: "clip.mp4")
    from src.config import settings
    monkeypatch.setattr(settings, "COMFYUI_VIDEO_BINDINGS_PATH", "")
    monkeypatch.setattr(settings, "COMFYUI_VIDEO_OUTPUT_NODE", "")

    service.generate_video(
        prompt="premium close-up reaction",
        negative_prompt="flicker, face drift",
        reference_image="first.png",
        output_path=str(tmp_path / "clip.mp4"),
        workflow_path=str(path),
        width=704,
        height=1280,
        duration_seconds=4,
        fps=24,
        seed=991,
    )

    graph = captured[0]
    assert graph["positive"]["inputs"]["text"] == "premium close-up reaction"
    assert graph["negative"]["inputs"]["text"] == "flicker, face drift"
    assert graph["image"]["inputs"]["image"] == "input/first.png"
    assert graph["latent"]["inputs"] == {"width": 704, "height": 1280, "length": 96}
    assert graph["sampler"]["inputs"]["noise_seed"] == 991
    assert graph["save"]["inputs"]["fps"] == 24
    assert graph["save"]["inputs"]["filename_prefix"] == "clip"


def test_workflow_binding_preserves_detail_stage_and_literal_prompt():
    service = object.__new__(ComfyUIService)
    workflow = {
        "base": {"inputs": {"width": "{width}", "seed": "{seed}", "text": "{prompt}"}},
        "detail": {"inputs": {"width": 1536, "seed": 998, "text": "preserve skin texture"}},
        "video": {"inputs": {"length": "{num_frames}", "label": "shot-{seed}"}},
    }
    resolved = service._replace_workflow_placeholders(workflow, {
        "width": 768, "seed": 42, "prompt": "A sign reads {seed}", "num_frames": 81,
    })
    assert resolved["detail"] == workflow["detail"]
    assert resolved["base"]["inputs"] == {
        "width": 768, "seed": 42, "text": "A sign reads {seed}",
    }
    assert resolved["video"]["inputs"] == {"length": 81, "label": "shot-42"}
    assert workflow["base"]["inputs"]["width"] == "{width}"


@pytest.mark.parametrize("duration,fps", [(float("nan"), 8), (5, 0), (True, 8), (-1, 8)])
def test_video_invalid_timing_is_rejected_before_upload(duration, fps):
    service = object.__new__(ComfyUIService)
    with pytest.raises(ComfyUIError, match="finite positive"):
        service.generate_video(
            prompt="shot", reference_image="first.png", output_path="clip.mp4",
            workflow_path="unused.json", duration_seconds=duration, fps=fps,
        )


def test_repair_image_uses_source_frame_and_targeted_low_denoise_graph(tmp_path, monkeypatch):
    from src.config import settings

    source = tmp_path / "accepted.png"
    source.write_bytes(b"source")
    output = tmp_path / "repaired.png"
    workflow_path = Path(__file__).parents[2] / "configs" / "comfyui_workflow_image_repair.json"
    service = object.__new__(ComfyUIService)
    captured = {}
    monkeypatch.setattr(settings, "COMFYUI_IMAGE_REPAIR_WORKFLOW_PATH", str(workflow_path))
    monkeypatch.setattr(settings, "COMFYUI_IMAGE_REPAIR_OUTPUT_NODE", "")
    monkeypatch.setattr(service, "_upload_reference_image", lambda path: "input/accepted.png")
    monkeypatch.setattr(service, "preflight", lambda graph: captured.setdefault("graph", graph))

    def run(graph, output_path, kind, output_node, _download):
        captured.update({"kind": kind, "output_node": output_node, "output_path": output_path})
        return output_path

    monkeypatch.setattr(service, "_run_submitted_job", run)

    result = service.repair_image(
        str(source),
        output_path=str(output),
        prompt="preserve the same actor",
        negative_prompt="identity drift",
        repair_target="hands, fingers",
        denoise=0.3,
        steps=28,
        cfg_scale=5.2,
        seed=42,
    )

    graph = captured["graph"]
    assert result == str(output)
    assert captured["kind"] == "image_repair"
    assert all(node["class_type"] != "EmptyLatentImage" for node in graph.values())
    load = next(node for node in graph.values() if node["class_type"] == "LoadImage")
    detailer = next(node for node in graph.values() if node["class_type"] == "FaceDetailer")
    detector = next(node for node in graph.values() if node["class_type"] == "CLIPSegDetectorProvider")
    load_id = next(node_id for node_id, node in graph.items() if node is load)
    assert load["inputs"]["image"] == "input/accepted.png"
    assert detailer["inputs"]["image"] == [load_id, 0]
    assert detailer["inputs"]["denoise"] == 0.3
    assert detailer["inputs"]["steps"] == 28
    assert detailer["inputs"]["seed"] == 42
    assert detector["inputs"]["text"] == "hands, fingers"
    assert output.with_suffix(".workflow.json").is_file()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
