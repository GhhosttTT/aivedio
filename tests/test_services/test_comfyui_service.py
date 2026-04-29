"""
ComfyUI 服务单元测试

测试 ComfyUIService 的核心功能
"""

import pytest
import json
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Mock httpx 模块（如果未安装）
if 'httpx' not in sys.modules:
    sys.modules['httpx'] = MagicMock()
    sys.modules['httpx'].Client = MagicMock
    sys.modules['httpx'].TimeoutException = Exception
    sys.modules['httpx'].ConnectError = Exception

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
            assert service.workflow_config is not None
            assert service.workflow_config["workflow"]["name"] == "Test Workflow"
    
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
            assert workflow["clip_text_encode_positive"]["inputs"]["text"] == "test prompt"
            assert workflow["clip_text_encode_negative"]["inputs"]["text"] == "bad"
            assert workflow["empty_latent_image"]["inputs"]["width"] == 512
            assert workflow["empty_latent_image"]["inputs"]["height"] == 512
            assert workflow["ksampler"]["inputs"]["steps"] == 15
            assert workflow["ksampler"]["inputs"]["cfg"] == 6.0
            assert workflow["ksampler"]["inputs"]["seed"] == 12345


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
