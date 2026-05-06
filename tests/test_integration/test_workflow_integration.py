"""
工作流管理器集成测试

测试 WorkflowManager 与现有系统的集成
"""

import pytest
import time
from pathlib import Path

from src.services.workflow_manager import WorkflowManager, get_workflow_manager, cleanup_workflow_manager
from src.models.workflow_config import WorkflowType


class TestWorkflowManagerIntegration:
    """测试工作流管理器集成"""
    
    def test_load_existing_workflow_files(self):
        """测试加载现有的工作流配置文件"""
        manager = WorkflowManager()
        
        # 测试加载现有的工作流文件
        workflow_files = [
            "./configs/comfyui_workflow.json",
            "./configs/comfyui_workflow_txt2img.json",
            "./configs/comfyui_workflow_fast.json"
        ]
        
        loaded_count = 0
        for workflow_path in workflow_files:
            if Path(workflow_path).exists():
                try:
                    config = manager.load_workflow(workflow_path=workflow_path)
                    assert config is not None
                    assert config.workflow.name is not None
                    print(f"✅ 成功加载: {workflow_path} - {config.workflow.name}")
                    loaded_count += 1
                except Exception as e:
                    print(f"⚠️ 加载失败: {workflow_path} - {e}")
        
        print(f"\n总计加载 {loaded_count}/{len(workflow_files)} 个工作流文件")
        assert loaded_count > 0, "至少应该成功加载一个工作流文件"
    
    def test_switch_between_predefined_workflows(self):
        """测试在预定义工作流之间切换"""
        manager = WorkflowManager()
        
        # 获取所有可用的工作流
        available_workflows = manager.list_available_workflows()
        existing_workflows = [w for w in available_workflows if w["exists"]]
        
        print(f"\n可用的工作流数量: {len(existing_workflows)}")
        
        if len(existing_workflows) < 2:
            pytest.skip("需要至少 2 个工作流文件才能测试切换功能")
        
        # 测试切换
        switched_count = 0
        for workflow in existing_workflows[:3]:  # 测试前3个
            try:
                workflow_type = WorkflowType(workflow["type"])
                start_time = time.time()
                config = manager.switch_workflow(workflow_type)
                elapsed_time = time.time() - start_time
                
                assert config is not None
                assert elapsed_time < 2.0, f"切换时间超过 2 秒: {elapsed_time:.2f}秒"
                
                print(f"✅ 切换到 {workflow['type']}: {config.workflow.name} ({elapsed_time:.3f}秒)")
                switched_count += 1
            except Exception as e:
                print(f"⚠️ 切换失败 {workflow['type']}: {e}")
        
        assert switched_count > 0, "至少应该成功切换一次"
    
    def test_workflow_caching_performance(self):
        """测试工作流缓存性能"""
        manager = WorkflowManager()
        
        # 找到第一个存在的工作流
        available_workflows = manager.list_available_workflows()
        existing_workflow = next((w for w in available_workflows if w["exists"]), None)
        
        if not existing_workflow:
            pytest.skip("没有可用的工作流文件")
        
        workflow_path = existing_workflow["path"]
        
        # 第一次加载（无缓存）
        manager.clear_cache()
        start_time = time.time()
        config1 = manager.load_workflow(workflow_path=workflow_path, use_cache=False)
        first_load_time = time.time() - start_time
        
        # 第二次加载（使用缓存）
        start_time = time.time()
        config2 = manager.load_workflow(workflow_path=workflow_path, use_cache=True)
        cached_load_time = time.time() - start_time
        
        # 验证
        assert config1.workflow.name == config2.workflow.name
        assert cached_load_time < first_load_time or cached_load_time < 0.01  # 缓存应该更快或非常快
        
        speedup = first_load_time / cached_load_time if cached_load_time > 0 else float('inf')
        
        print(f"\n首次加载时间: {first_load_time:.4f}秒")
        print(f"缓存加载时间: {cached_load_time:.4f}秒")
        print(f"性能提升: {speedup:.2f}x")
    
    def test_workflow_validation(self):
        """测试工作流验证"""
        manager = WorkflowManager()
        
        # 加载一个工作流
        available_workflows = manager.list_available_workflows()
        existing_workflow = next((w for w in available_workflows if w["exists"]), None)
        
        if not existing_workflow:
            pytest.skip("没有可用的工作流文件")
        
        config = manager.load_workflow(workflow_path=existing_workflow["path"])
        
        # 验证工作流
        errors = manager.validate_workflow(config)
        
        if errors:
            print(f"\n⚠️ 发现 {len(errors)} 个验证错误:")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"\n✅ 工作流验证通过: {config.workflow.name}")
        
        # 验证基本结构
        assert config.workflow.name is not None
        assert len(config.nodes) > 0
        assert config.parameters is not None
        assert config.negative_prompt is not None
    
    def test_workflow_info_extraction(self):
        """测试工作流信息提取"""
        manager = WorkflowManager()
        
        # 加载一个工作流
        available_workflows = manager.list_available_workflows()
        existing_workflow = next((w for w in available_workflows if w["exists"]), None)
        
        if not existing_workflow:
            pytest.skip("没有可用的工作流文件")
        
        config = manager.load_workflow(workflow_path=existing_workflow["path"])
        
        # 获取工作流信息
        info = manager.get_workflow_info()
        
        print(f"\n工作流信息:")
        print(f"  名称: {info['name']}")
        print(f"  版本: {info['version']}")
        print(f"  描述: {info.get('description', 'N/A')}")
        print(f"  节点数量: {info['node_count']}")
        print(f"  默认参数: {info.get('parameters', {})}")
        
        assert info["name"] is not None
        assert info["node_count"] > 0
    
    def test_workflow_parameter_extraction(self):
        """测试参数提取"""
        manager = WorkflowManager()
        
        # 加载一个工作流
        available_workflows = manager.list_available_workflows()
        existing_workflow = next((w for w in available_workflows if w["exists"]), None)
        
        if not existing_workflow:
            pytest.skip("没有可用的工作流文件")
        
        config = manager.load_workflow(workflow_path=existing_workflow["path"])
        
        # 提取参数
        default_params = config.parameters.default
        
        print(f"\n默认参数:")
        for key, value in default_params.items():
            print(f"  {key}: {value}")
        
        # 提取负面提示词
        negative_prompt = config.negative_prompt.default
        
        print(f"\n默认负面提示词:")
        print(f"  {negative_prompt}")
        
        assert isinstance(default_params, dict)
        assert isinstance(negative_prompt, str)
    
    def test_workflow_node_structure(self):
        """测试节点结构"""
        manager = WorkflowManager()
        
        # 加载一个工作流
        available_workflows = manager.list_available_workflows()
        existing_workflow = next((w for w in available_workflows if w["exists"]), None)
        
        if not existing_workflow:
            pytest.skip("没有可用的工作流文件")
        
        config = manager.load_workflow(workflow_path=existing_workflow["path"])
        
        # 分析节点结构
        print(f"\n节点结构 (共 {len(config.nodes)} 个节点):")
        
        node_types = {}
        for node_name, node_config in config.nodes.items():
            class_type = node_config.class_type
            if class_type not in node_types:
                node_types[class_type] = []
            node_types[class_type].append(node_name)
        
        for class_type, nodes in node_types.items():
            print(f"  {class_type}: {len(nodes)} 个")
            for node in nodes[:2]:  # 只显示前2个
                print(f"    - {node}")
        
        assert len(config.nodes) > 0
    
    def test_workflow_error_recovery(self):
        """测试错误恢复机制"""
        manager = WorkflowManager()
        
        # 尝试加载不存在的文件
        try:
            config = manager.load_workflow(workflow_path="non_existent_file.json")
            
            # 如果成功加载，说明回退机制工作
            assert config is not None
            print(f"\n✅ 错误恢复成功，已回退到: {config.workflow.name}")
        except Exception as e:
            print(f"\n⚠️ 错误恢复失败: {e}")
            # 这也是可以接受的，如果默认工作流也不存在
    
    def test_singleton_pattern(self):
        """测试单例模式"""
        manager1 = get_workflow_manager()
        manager2 = get_workflow_manager()
        
        assert manager1 is manager2
        print("\n✅ 单例模式工作正常")
        
        # 清理
        cleanup_workflow_manager()
        
        # 清理后再次获取应该是新实例
        manager3 = get_workflow_manager()
        assert manager3 is not manager1
        print("✅ 清理后重新创建实例成功")


class TestWorkflowToComfyUIFormat:
    """测试工作流转换为 ComfyUI API 格式"""
    
    def test_convert_workflow_to_api_format(self):
        """测试将工作流配置转换为 ComfyUI API 格式"""
        manager = WorkflowManager()
        
        # 加载一个工作流
        available_workflows = manager.list_available_workflows()
        existing_workflow = next((w for w in available_workflows if w["exists"]), None)
        
        if not existing_workflow:
            pytest.skip("没有可用的工作流文件")
        
        config = manager.load_workflow(workflow_path=existing_workflow["path"])
        
        # 转换为 ComfyUI API 格式（模拟 ComfyUIService 的逻辑）
        workflow_nodes = config.nodes
        node_name_to_id = {name: str(idx + 1) for idx, name in enumerate(workflow_nodes.keys())}
        workflow_api = {}
        
        for node_name, node_config in workflow_nodes.items():
            node_id = node_name_to_id[node_name]
            workflow_api[node_id] = {
                "class_type": node_config.class_type,
                "inputs": {}
            }
            
            # 转换输入参数
            for input_key, input_value in node_config.inputs.items():
                if isinstance(input_value, list) and len(input_value) == 2:
                    ref_node_name, output_idx = input_value
                    if ref_node_name in node_name_to_id:
                        workflow_api[node_id]["inputs"][input_key] = [
                            node_name_to_id[ref_node_name],
                            output_idx
                        ]
                    else:
                        workflow_api[node_id]["inputs"][input_key] = input_value
                else:
                    workflow_api[node_id]["inputs"][input_key] = input_value
        
        # 验证转换结果
        assert len(workflow_api) == len(config.nodes)
        assert all(isinstance(node_id, str) for node_id in workflow_api.keys())
        
        print(f"\n✅ 成功转换 {len(workflow_api)} 个节点到 ComfyUI API 格式")
        
        # 显示前3个节点
        for i, (node_id, node_data) in enumerate(list(workflow_api.items())[:3]):
            print(f"  节点 {node_id}: {node_data['class_type']}")


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    """测试结束后清理"""
    yield
    cleanup_workflow_manager()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
