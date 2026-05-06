"""
工作流模板服务单元测试
"""

import pytest
import tempfile
from pathlib import Path
from src.services.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateManager,
    TemplateCategory,
    get_workflow_template_manager
)
from src.models.workflow_config import (
    WorkflowType, 
    WorkflowConfig,
    WorkflowMetadata,
    ParameterConfig,
    NegativePromptConfig
)


class TestWorkflowTemplate:
    """测试 WorkflowTemplate 类"""
    
    def test_create_template(self):
        """测试创建模板"""
        template = WorkflowTemplate(
            id="test-template",
            name="测试模板",
            description="这是一个测试模板",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={
                "name": "测试",
                "version": "1.0",
                "nodes": {},
                "parameters": {"sampling_steps": 20},
                "negative_prompt": "low quality"
            }
        )
        
        assert template.id == "test-template"
        assert template.name == "测试模板"
        assert template.category == TemplateCategory.BASIC
        assert template.workflow_type == WorkflowType.BASIC
    
    def test_validate_parameters_valid(self):
        """测试参数验证（有效参数）"""
        template = WorkflowTemplate(
            id="test",
            name="测试",
            description="测试",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={},
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 1,
                    "max": 100,
                    "default": 20
                },
                "cfg_scale": {
                    "type": "float",
                    "min": 1.0,
                    "max": 20.0,
                    "default": 7.0
                }
            }
        )
        
        # 有效参数
        assert template.validate_parameters({"sampling_steps": 25, "cfg_scale": 7.5}) is True
    
    def test_validate_parameters_invalid_type(self):
        """测试参数验证（无效类型）"""
        template = WorkflowTemplate(
            id="test",
            name="测试",
            description="测试",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={},
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 1,
                    "max": 100,
                    "default": 20
                }
            }
        )
        
        # 无效类型
        assert template.validate_parameters({"sampling_steps": "20"}) is False
    
    def test_validate_parameters_out_of_range(self):
        """测试参数验证（超出范围）"""
        template = WorkflowTemplate(
            id="test",
            name="测试",
            description="测试",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={},
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 1,
                    "max": 100,
                    "default": 20
                }
            }
        )
        
        # 超出范围
        assert template.validate_parameters({"sampling_steps": 150}) is False
        assert template.validate_parameters({"sampling_steps": 0}) is False
    
    def test_create_config_without_params(self):
        """测试从模板创建配置（无参数）"""
        template = WorkflowTemplate(
            id="test",
            name="测试模板",
            description="测试",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={
                "name": "测试配置",
                "version": "1.0",
                "nodes": {},
                "parameters": {"sampling_steps": 20, "cfg_scale": 7.0},
                "negative_prompt": "low quality"
            }
        )
        
        config = template.create_config()
        
        assert isinstance(config, WorkflowConfig)
        assert config.workflow.name == "测试配置"
        assert config.parameters.default["sampling_steps"] == 20
        assert config.parameters.default["cfg_scale"] == 7.0
    
    def test_create_config_with_params(self):
        """测试从模板创建配置（带参数）"""
        template = WorkflowTemplate(
            id="test",
            name="测试模板",
            description="测试",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={
                "name": "测试配置",
                "version": "1.0",
                "nodes": {},
                "parameters": {"sampling_steps": 20, "cfg_scale": 7.0},
                "negative_prompt": "low quality"
            },
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 1,
                    "max": 100,
                    "default": 20
                },
                "cfg_scale": {
                    "type": "float",
                    "min": 1.0,
                    "max": 20.0,
                    "default": 7.0
                }
            }
        )
        
        config = template.create_config({"sampling_steps": 30, "cfg_scale": 8.0})
        
        assert config.parameters.default["sampling_steps"] == 30
        assert config.parameters.default["cfg_scale"] == 8.0
    
    def test_to_dict(self):
        """测试转换为字典"""
        template = WorkflowTemplate(
            id="test",
            name="测试模板",
            description="测试",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={},
            tags=["测试"]
        )
        
        data = template.to_dict()
        
        assert data["id"] == "test"
        assert data["name"] == "测试模板"
        assert data["category"] == "basic"
        assert data["workflow_type"] == "basic"
        assert data["tags"] == ["测试"]
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "id": "test",
            "name": "测试模板",
            "description": "测试",
            "category": "basic",
            "workflow_type": "basic",
            "base_config": {},
            "parameters": {},
            "tags": ["测试"]
        }
        
        template = WorkflowTemplate.from_dict(data)
        
        assert template.id == "test"
        assert template.name == "测试模板"
        assert template.category == TemplateCategory.BASIC
        assert template.workflow_type == WorkflowType.BASIC


class TestWorkflowTemplateManager:
    """测试 WorkflowTemplateManager 类"""
    
    def test_singleton(self):
        """测试单例模式"""
        manager1 = WorkflowTemplateManager()
        manager2 = WorkflowTemplateManager()
        assert manager1 is manager2
    
    def test_get_workflow_template_manager(self):
        """测试获取全局实例"""
        manager1 = get_workflow_template_manager()
        manager2 = get_workflow_template_manager()
        assert manager1 is manager2
        assert isinstance(manager1, WorkflowTemplateManager)
    
    def test_predefined_templates_loaded(self):
        """测试预定义模板已加载"""
        manager = get_workflow_template_manager()
        
        # 应该有 5 个预定义模板
        templates = manager.get_all_templates()
        assert len(templates) >= 5
        
        # 验证特定模板存在
        basic_txt2img = manager.get_template("basic-txt2img")
        assert basic_txt2img is not None
        assert basic_txt2img.name == "基础文生图"
        
        ipadapter = manager.get_template("ipadapter-template")
        assert ipadapter is not None
        assert ipadapter.name == "IP-Adapter 模板"
        
        realism = manager.get_template("realism-enhanced")
        assert realism is not None
        assert realism.name == "真实感增强"
        
        hires_fix = manager.get_template("hires-fix")
        assert hires_fix is not None
        assert hires_fix.name == "高清修复"
        assert hires_fix.workflow_type == WorkflowType.HIGH_QUALITY  # 修改断言
        
        fast_gen = manager.get_template("fast-generation")
        assert fast_gen is not None
        assert fast_gen.name == "快速生成"
    
    def test_add_template(self):
        """测试添加模板"""
        manager = get_workflow_template_manager()
        
        template = WorkflowTemplate(
            id="custom-test",
            name="自定义测试",
            description="测试添加模板",
            category=TemplateCategory.CUSTOM,
            workflow_type=WorkflowType.BASIC,
            base_config={}
        )
        
        manager.add_template(template)
        
        # 验证已添加
        retrieved = manager.get_template("custom-test")
        assert retrieved is not None
        assert retrieved.name == "自定义测试"
    
    def test_get_templates_by_category(self):
        """测试根据分类获取模板"""
        manager = get_workflow_template_manager()
        
        # 获取基础模板
        basic_templates = manager.get_templates_by_category(TemplateCategory.BASIC)
        assert len(basic_templates) >= 2  # 至少有基础文生图和快速生成
        
        # 获取高级模板
        advanced_templates = manager.get_templates_by_category(TemplateCategory.ADVANCED)
        assert len(advanced_templates) >= 2  # 至少有 IP-Adapter 和高清修复
        
        # 获取专用模板
        specialized_templates = manager.get_templates_by_category(TemplateCategory.SPECIALIZED)
        assert len(specialized_templates) >= 1  # 至少有真实感增强
    
    def test_search_templates_by_keyword(self):
        """测试根据关键词搜索模板"""
        manager = get_workflow_template_manager()
        
        # 搜索包含"快速"的模板
        results = manager.search_templates(keyword="快速")
        assert len(results) >= 1
        assert any("快速" in t.name or "快速" in t.description for t in results)
        
        # 搜索包含"IP-Adapter"的模板
        results = manager.search_templates(keyword="IP-Adapter")
        assert len(results) >= 1
        assert any("IP-Adapter" in t.name for t in results)
    
    def test_search_templates_by_category(self):
        """测试根据分类搜索模板"""
        manager = get_workflow_template_manager()
        
        # 搜索基础模板
        results = manager.search_templates(category=TemplateCategory.BASIC)
        assert len(results) >= 2
        assert all(t.category == TemplateCategory.BASIC for t in results)
    
    def test_search_templates_by_tags(self):
        """测试根据标签搜索模板"""
        manager = get_workflow_template_manager()
        
        # 搜索包含"基础"标签的模板
        results = manager.search_templates(tags=["基础"])
        assert len(results) >= 1
        assert all("基础" in t.tags for t in results)
    
    def test_export_template(self):
        """测试导出模板"""
        manager = get_workflow_template_manager()
        
        # 创建一个配置
        workflow_meta = WorkflowMetadata(
            name="测试配置",
            version="1.0"
        )
        param_config = ParameterConfig(
            default={"sampling_steps": 25}
        )
        negative_prompt_config = NegativePromptConfig(
            default="low quality"
        )
        config = WorkflowConfig(
            workflow=workflow_meta,
            nodes={},
            parameters=param_config,
            negative_prompt=negative_prompt_config
        )
        
        # 导出为模板
        template = manager.export_template(
            config=config,
            template_id="exported-test",
            name="导出的测试模板",
            description="从配置导出的模板",
            workflow_type=WorkflowType.BASIC,  # 添加 workflow_type
            category=TemplateCategory.CUSTOM,
            author="测试作者"
        )
        
        assert template.id == "exported-test"
        assert template.name == "导出的测试模板"
        assert template.category == TemplateCategory.CUSTOM
        assert template.author == "测试作者"
        
        # 验证已添加到管理器
        retrieved = manager.get_template("exported-test")
        assert retrieved is not None
    
    def test_save_and_load_template(self):
        """测试保存和加载模板"""
        manager = get_workflow_template_manager()
        
        template = WorkflowTemplate(
            id="save-test",
            name="保存测试",
            description="测试保存和加载",
            category=TemplateCategory.CUSTOM,
            workflow_type=WorkflowType.BASIC,
            base_config={}
        )
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # 保存模板
            manager.save_template(template, tmpdir_path)
            
            # 验证文件已创建
            file_path = tmpdir_path / f"{template.id}.json"
            assert file_path.exists()
            
            # 加载模板
            loaded_template = manager.load_template(file_path)
            assert loaded_template is not None
            assert loaded_template.id == template.id
            assert loaded_template.name == template.name
    
    def test_create_config_from_template(self):
        """测试从模板创建配置"""
        manager = get_workflow_template_manager()
        
        # 获取基础文生图模板
        template = manager.get_template("basic-txt2img")
        assert template is not None
        
        # 创建配置（使用默认参数）
        config1 = template.create_config()
        assert isinstance(config1, WorkflowConfig)
        assert config1.parameters.default["sampling_steps"] == 20
        
        # 创建配置（自定义参数）
        config2 = template.create_config({"sampling_steps": 30, "cfg_scale": 8.0})
        assert config2.parameters.default["sampling_steps"] == 30
        assert config2.parameters.default["cfg_scale"] == 8.0
    
    def test_template_usage_guide(self):
        """测试模板使用指南"""
        manager = get_workflow_template_manager()
        
        # 所有预定义模板都应该有使用指南
        templates = manager.get_all_templates()
        for template in templates:
            if template.category != TemplateCategory.CUSTOM:
                assert template.usage_guide is not None
                assert len(template.usage_guide) > 0
    
    def test_template_example_params(self):
        """测试模板示例参数"""
        manager = get_workflow_template_manager()
        
        # 所有预定义模板都应该有示例参数
        templates = manager.get_all_templates()
        for template in templates:
            if template.category != TemplateCategory.CUSTOM:
                assert template.example_params is not None
                assert len(template.example_params) > 0


class TestTemplateCategory:
    """测试 TemplateCategory 枚举"""
    
    def test_template_category_values(self):
        """测试模板分类枚举值"""
        assert TemplateCategory.BASIC.value == "basic"
        assert TemplateCategory.ADVANCED.value == "advanced"
        assert TemplateCategory.SPECIALIZED.value == "specialized"
        assert TemplateCategory.CUSTOM.value == "custom"
