"""
LLM 服务单元测试

测试 LLMService 的核心功能
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

# Mock llama_cpp 模块（如果未安装）
if 'llama_cpp' not in sys.modules:
    sys.modules['llama_cpp'] = MagicMock()

from src.services.llm_service import LLMService, get_llm_service, cleanup_llm_service


class TestLLMService:
    """LLM 服务测试类"""
    
    @patch('src.services.llm_service.Llama')
    def test_init_success(self, mock_llama):
        """测试：成功初始化 LLM 服务"""
        # 模拟模型文件存在
        with patch('os.path.exists', return_value=True):
            # 模拟 Llama 实例
            mock_model = MagicMock()
            mock_llama.return_value = mock_model
            
            # 创建服务
            service = LLMService(
                model_path="test_model.gguf",
                n_gpu_layers=20,
                n_ctx=4096,
                n_threads=8
            )
            
            # 验证
            assert service.is_loaded is True
            assert service.model is not None
            assert service.n_gpu_layers == 20
            assert service.n_ctx == 4096
            assert service.n_threads == 8
            
            # 验证 Llama 被正确调用
            mock_llama.assert_called_once()
    
    def test_init_model_not_found(self):
        """测试：模型文件不存在时抛出异常"""
        with patch('os.path.exists', return_value=False):
            with pytest.raises(FileNotFoundError):
                LLMService(model_path="nonexistent_model.gguf")
    
    def test_init_no_model_path(self):
        """测试：未配置模型路径时抛出异常"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="未配置 LLM 模型路径"):
                LLMService()
    
    @patch('src.services.llm_service.Llama')
    def test_generate_success(self, mock_llama):
        """测试：成功生成文本"""
        # 模拟模型文件存在
        with patch('os.path.exists', return_value=True):
            # 模拟 Llama 实例和生成结果
            mock_model = MagicMock()
            mock_model.return_value = {
                "choices": [{"text": "生成的文本内容"}]
            }
            mock_llama.return_value = mock_model
            
            # 创建服务
            service = LLMService(model_path="test_model.gguf")
            
            # 生成文本
            result = service.generate(
                prompt="测试提示词",
                max_tokens=100,
                temperature=0.7
            )
            
            # 验证
            assert result == "生成的文本内容"
            mock_model.assert_called()
    
    @patch('src.services.llm_service.Llama')
    def test_generate_empty_prompt(self, mock_llama):
        """测试：空提示词时抛出异常"""
        with patch('os.path.exists', return_value=True):
            mock_model = MagicMock()
            mock_llama.return_value = mock_model
            
            service = LLMService(model_path="test_model.gguf")
            
            with pytest.raises(ValueError, match="输入提示词不能为空"):
                service.generate(prompt="")
    
    @patch('src.services.llm_service.Llama')
    def test_generate_model_not_loaded(self, mock_llama):
        """测试：模型未加载时抛出异常"""
        with patch('os.path.exists', return_value=True):
            mock_model = MagicMock()
            mock_llama.return_value = mock_model
            
            service = LLMService(model_path="test_model.gguf")
            service.is_loaded = False
            service.model = None
            
            with pytest.raises(RuntimeError, match="LLM 模型未加载"):
                service.generate(prompt="测试")
    
    def test_generate_script_prompt_with_theme(self):
        """测试：使用主题生成剧本 Prompt"""
        with patch('os.path.exists', return_value=True):
            with patch('src.services.llm_service.Llama'):
                service = LLMService(model_path="test_model.gguf")
                
                prompt = service.generate_script_prompt(
                    theme="爱情故事",
                    num_scenes=10,
                    num_characters=2,
                    style="现代都市"
                )
                
                # 验证 Prompt 包含关键信息
                assert "爱情故事" in prompt
                assert "10" in prompt
                assert "2" in prompt
                assert "现代都市" in prompt
                assert "【剧本】" in prompt
                assert "【角色】" in prompt
                assert "【分镜】" in prompt
    
    def test_generate_script_prompt_with_outline(self):
        """测试：使用大纲生成剧本 Prompt"""
        with patch('os.path.exists', return_value=True):
            with patch('src.services.llm_service.Llama'):
                service = LLMService(model_path="test_model.gguf")
                
                prompt = service.generate_script_prompt(
                    outline="一个关于友情的故事",
                    num_scenes=5,
                    num_characters=3,
                    style="青春校园"
                )
                
                # 验证 Prompt 包含关键信息
                assert "一个关于友情的故事" in prompt
                assert "5" in prompt
                assert "3" in prompt
                assert "青春校园" in prompt
    
    def test_generate_script_prompt_no_theme_or_outline(self):
        """测试：主题和大纲都为空时抛出异常"""
        with patch('os.path.exists', return_value=True):
            with patch('src.services.llm_service.Llama'):
                service = LLMService(model_path="test_model.gguf")
                
                with pytest.raises(ValueError, match="主题和大纲至少需要提供一个"):
                    service.generate_script_prompt()
    
    @patch('src.services.llm_service.Llama')
    def test_unload_model(self, mock_llama):
        """测试：卸载模型"""
        with patch('os.path.exists', return_value=True):
            mock_model = MagicMock()
            mock_llama.return_value = mock_model
            
            service = LLMService(model_path="test_model.gguf")
            
            # 卸载模型
            service.unload_model()
            
            # 验证
            assert service.model is None
            assert service.is_loaded is False
    
    @patch('src.services.llm_service.Llama')
    def test_get_model_info(self, mock_llama):
        """测试：获取模型信息"""
        with patch('os.path.exists', return_value=True):
            mock_model = MagicMock()
            mock_llama.return_value = mock_model
            
            service = LLMService(
                model_path="test_model.gguf",
                n_gpu_layers=20,
                n_ctx=4096,
                n_threads=8
            )
            
            info = service.get_model_info()
            
            # 验证
            assert info["model_path"] == "test_model.gguf"
            assert info["n_gpu_layers"] == 20
            assert info["n_ctx"] == 4096
            assert info["n_threads"] == 8
            assert info["is_loaded"] is True
    
    @patch('src.services.llm_service.Llama')
    def test_generate_with_stop_words(self, mock_llama):
        """测试：使用停止词生成文本"""
        with patch('os.path.exists', return_value=True):
            mock_model = MagicMock()
            mock_model.return_value = {
                "choices": [{"text": "生成的文本"}]
            }
            mock_llama.return_value = mock_model
            
            service = LLMService(model_path="test_model.gguf")
            
            result = service.generate(
                prompt="测试",
                stop=["停止词1", "停止词2"]
            )
            
            # 验证停止词被传递
            call_args = mock_model.call_args
            assert "stop" in call_args[1]
            assert call_args[1]["stop"] == ["停止词1", "停止词2"]
    
    @patch('src.services.llm_service.Llama')
    def test_generate_stream(self, mock_llama):
        """测试：流式生成文本"""
        with patch('os.path.exists', return_value=True):
            # 模拟流式输出
            mock_stream = [
                {"choices": [{"text": "第一"}]},
                {"choices": [{"text": "部分"}]},
                {"choices": [{"text": "文本"}]}
            ]
            mock_model = MagicMock()
            mock_model.return_value = iter(mock_stream)
            mock_llama.return_value = mock_model
            
            service = LLMService(model_path="test_model.gguf")
            
            # 回调函数
            tokens = []
            def callback(token):
                tokens.append(token)
            
            result = service.generate(
                prompt="测试",
                stream=True,
                callback=callback
            )
            
            # 验证
            assert result == "第一部分文本"
            assert tokens == ["第一", "部分", "文本"]


class TestGlobalLLMService:
    """全局 LLM 服务测试类"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        cleanup_llm_service()
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        cleanup_llm_service()
    
    @patch('src.services.llm_service.Llama')
    def test_get_llm_service_singleton(self, mock_llama):
        """测试：全局服务实例是单例"""
        with patch('os.path.exists', return_value=True):
            with patch.dict(os.environ, {
                'LLM_MODEL_PATH': 'test_model.gguf',
                'LLM_N_GPU_LAYERS': '20',
                'LLM_N_CTX': '4096',
                'LLM_N_THREADS': '8'
            }):
                mock_model = MagicMock()
                mock_llama.return_value = mock_model
                
                # 获取两次实例
                service1 = get_llm_service()
                service2 = get_llm_service()
                
                # 验证是同一个实例
                assert service1 is service2
                
                # 验证 Llama 只被调用一次
                assert mock_llama.call_count == 1
    
    @patch('src.services.llm_service.Llama')
    def test_cleanup_llm_service(self, mock_llama):
        """测试：清理全局服务实例"""
        with patch('os.path.exists', return_value=True):
            with patch.dict(os.environ, {
                'LLM_MODEL_PATH': 'test_model.gguf'
            }):
                mock_model = MagicMock()
                mock_llama.return_value = mock_model
                
                # 获取实例
                service = get_llm_service()
                assert service is not None
                
                # 清理实例
                cleanup_llm_service()
                
                # 再次获取应该创建新实例
                service2 = get_llm_service()
                assert service2 is not service


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
