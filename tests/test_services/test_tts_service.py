"""
TTS 服务单元测试

测试 TTSService 的核心功能
"""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# 创建 Mock httpx 模块
mock_httpx = MagicMock()
mock_httpx.Client = MagicMock
mock_httpx.HTTPStatusError = Exception

# 在导入前设置 Mock
sys.modules['httpx'] = mock_httpx

# 导入服务模块
from src.services.tts_service import (
    TTSService,
    TTSError,
    TTSQuotaError,
    get_tts_service,
    cleanup_tts_service
)

# Patch HTTPX_AVAILABLE 为 True
import src.services.tts_service as tts_module
tts_module.HTTPX_AVAILABLE = True
tts_module.httpx = mock_httpx


class TestTTSService:
    """TTS 服务测试类"""
    
    @pytest.fixture
    def mock_client(self):
        """创建 Mock HTTP 客户端"""
        client = MagicMock()
        client.post = MagicMock()
        client.get = MagicMock()
        client.close = MagicMock()
        return client
    
    @pytest.fixture
    def service(self, mock_client):
        """创建 TTS 服务实例"""
        with patch.object(mock_httpx, 'Client', return_value=mock_client):
            service = TTSService(api_key="test_api_key")
            return service
    
    def test_init_success(self, mock_client):
        """测试：成功初始化服务"""
        with patch.object(mock_httpx, 'Client', return_value=mock_client):
            service = TTSService(
                api_key="test_key",
                base_url="https://test.com/api",
                timeout=60,
                max_retries=5
            )
            
            assert service.api_key == "test_key"
            assert service.base_url == "https://test.com/api"
            assert service.timeout == 60
            assert service.max_retries == 5
    
    def test_init_no_api_key(self):
        """测试：未提供 API 密钥时抛出异常"""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="TTS API 密钥未配置"):
                TTSService()
    
    def test_generate_speech_success(self, service, mock_client):
        """测试：成功生成语音"""
        # Mock API 响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "audio_url": "https://test.com/audio.mp3"
        }
        mock_client.post.return_value = mock_response
        
        # Mock 音频下载
        mock_audio_response = MagicMock()
        mock_audio_response.content = b"fake audio data"
        mock_client.get.return_value = mock_audio_response
        
        # 生成语音
        audio_path = service.generate_speech(
            text="测试文本",
            speaker="speaker1",
            emotion="happy",
            speed=1.2
        )
        
        # 验证
        assert audio_path is not None
        assert audio_path.endswith(".mp3")
        mock_client.post.assert_called_once()
    
    def test_generate_speech_empty_text(self, service):
        """测试：空文本时抛出异常"""
        with pytest.raises(ValueError, match="输入文本不能为空"):
            service.generate_speech(text="")
    
    def test_generate_speech_invalid_speed(self, service):
        """测试：无效语速时抛出异常"""
        with pytest.raises(ValueError, match="语速必须在 0.5-2.0 之间"):
            service.generate_speech(text="测试", speed=3.0)
    
    def test_generate_speech_quota_error(self, service, mock_client):
        """测试：配额不足时抛出 TTSQuotaError"""
        # Mock API 响应（429 状态码）
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_client.post.return_value = mock_response
        
        with pytest.raises(TTSQuotaError, match="配额不足"):
            service.generate_speech(text="测试文本")
    
    def test_generate_speech_api_error(self, service, mock_client):
        """测试：API 返回错误时抛出 TTSError"""
        # Mock API 响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "error",
            "message": "API 错误"
        }
        mock_client.post.return_value = mock_response
        
        with pytest.raises(TTSError, match="API 返回错误"):
            service.generate_speech(text="测试文本")
    
    def test_generate_speech_retry(self, service, mock_client):
        """测试：失败后重试"""
        # 第一次失败，第二次成功
        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 500
        mock_response_fail.raise_for_status.side_effect = Exception("Server error")
        
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "status": "success",
            "audio_url": "https://test.com/audio.mp3"
        }
        
        mock_client.post.side_effect = [mock_response_fail, mock_response_success]
        
        # Mock 音频下载
        mock_audio_response = MagicMock()
        mock_audio_response.content = b"fake audio data"
        mock_client.get.return_value = mock_audio_response
        
        # 生成语音（应该重试成功）
        with patch('time.sleep'):  # 跳过等待时间
            audio_path = service.generate_speech(text="测试文本")
        
        assert audio_path is not None
        assert mock_client.post.call_count == 2
    
    def test_list_speakers_success(self, service, mock_client):
        """测试：成功获取说话人列表"""
        # Mock API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "speakers": [
                {"id": "speaker1", "name": "说话人1", "description": "描述1"},
                {"id": "speaker2", "name": "说话人2", "description": "描述2"}
            ]
        }
        mock_client.get.return_value = mock_response
        
        # 获取说话人列表
        speakers = service.list_speakers()
        
        assert len(speakers) == 2
        assert speakers[0]["id"] == "speaker1"
        assert speakers[1]["id"] == "speaker2"
    
    def test_list_speakers_error(self, service, mock_client):
        """测试：获取说话人列表失败"""
        # Mock API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "error",
            "message": "获取失败"
        }
        mock_client.get.return_value = mock_response
        
        with pytest.raises(TTSError, match="获取说话人列表失败"):
            service.list_speakers()
    
    def test_check_quota_success(self, service, mock_client):
        """测试：成功检查配额"""
        # Mock API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "quota": {
                "total": 1000,
                "used": 300,
                "remaining": 700
            }
        }
        mock_client.get.return_value = mock_response
        
        # 检查配额
        quota = service.check_quota()
        
        assert quota["total"] == 1000
        assert quota["used"] == 300
        assert quota["remaining"] == 700
    
    def test_check_quota_error(self, service, mock_client):
        """测试：检查配额失败"""
        # Mock API 响应
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "error",
            "message": "检查失败"
        }
        mock_client.get.return_value = mock_response
        
        with pytest.raises(TTSError, match="检查配额失败"):
            service.check_quota()
    
    def test_close(self, service, mock_client):
        """测试：关闭服务"""
        service.close()
        
        mock_client.close.assert_called_once()


class TestGlobalTTSService:
    """全局 TTS 服务测试类"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        cleanup_tts_service()
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        cleanup_tts_service()
    
    def test_get_tts_service_singleton(self, monkeypatch):
        """测试：全局服务实例是单例"""
        # Mock 环境变量
        monkeypatch.setenv("TTS_API_KEY", "test_key")
        
        # Mock HTTP 客户端
        mock_client = MagicMock()
        with patch.object(mock_httpx, 'Client', return_value=mock_client):
            # 获取两次实例
            service1 = get_tts_service()
            service2 = get_tts_service()
            
            # 验证是同一个实例
            assert service1 is service2
    
    def test_cleanup_tts_service(self, monkeypatch):
        """测试：清理全局服务实例"""
        # Mock 环境变量
        monkeypatch.setenv("TTS_API_KEY", "test_key")
        
        # Mock HTTP 客户端
        mock_client = MagicMock()
        with patch.object(mock_httpx, 'Client', return_value=mock_client):
            # 获取实例
            service = get_tts_service()
            assert service is not None
            
            # 清理实例
            cleanup_tts_service()
            
            # 再次获取应该创建新实例
            service2 = get_tts_service()
            assert service2 is not service


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
