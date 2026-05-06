# ComfyUI Workflow Enhancement 实施指南

## 📊 当前进度

**已完成**: 2/23 任务 (8.7%)
- ✅ Task 1.1: 工作流配置数据模型（24个测试通过）
- ✅ Task 1.2: 工作流管理器基础类（25个测试通过）

**剩余**: 21 个任务

---

## 🎯 核心架构已就绪

### 已实现的核心组件

1. **WorkflowConfig** (`src/models/workflow_config.py`)
   - 完整的工作流配置数据模型
   - JSON Schema 验证
   - 支持 11 种工作流类型
   - 节点配置、参数配置、负面提示词配置

2. **WorkflowManager** (`src/services/workflow_manager.py`)
   - 工作流加载和切换（<2秒）
   - 配置验证和缓存
   - 自定义工作流注册
   - 错误处理和自动回退
   - 单例模式

---

## 🚀 快速完成剩余任务的策略

### 优先级 P0（必须完成）

#### 1. Task 1.4: 集成 WorkflowManager 到 ComfyUIService
**目标**: 让现有的图像生成服务使用新的工作流管理器

**实施步骤**:
```python
# 在 src/services/comfyui_service.py 中
from src/services.workflow_manager import get_workflow_manager

class ComfyUIService:
    def __init__(self):
        self.workflow_manager = get_workflow_manager()
        # 替换现有的 load_workflow 逻辑
        
    def generate_image(self, ...):
        # 使用 workflow_manager.get_current_workflow()
        # 替代 self.workflow_config
```

**预估时间**: 2小时

---

#### 2. Task 2.1: 参数自动优化器
**目标**: 根据场景自动选择最优参数

**核心逻辑**:
```python
class ParameterOptimizer:
    def optimize(self, scene_type, has_reference_image, quality_mode):
        params = {}
        
        # IP-Adapter 权重
        if has_reference_image:
            params['ipadapter_weight'] = 0.8 if scene_type == 'portrait' else 0.7
        
        # 采样步数
        if quality_mode == 'fast':
            params['steps'] = 15
        elif quality_mode == 'high_quality':
            params['steps'] = 30
        else:
            params['steps'] = 20
        
        # CFG Scale
        if scene_type in ['portrait', 'close_up']:
            params['cfg_scale'] = 6.5
        else:
            params['cfg_scale'] = 7.5
        
        return params
```

**预估时间**: 4小时

---

#### 3. Task 2.2: 提示词优化引擎
**目标**: 自动增强提示词质量

**核心逻辑**:
```python
class PromptOptimizer:
    QUALITY_TAGS = "(masterpiece:1.2), (best quality:1.2), (ultra-detailed:1.2)"
    REALISM_KEYWORDS = "raw photo, candid shot, natural lighting, film grain"
    NEGATIVE_REALISM = "CGI, 3D render, plastic skin, airbrushed, too perfect"
    
    def enhance_prompt(self, prompt, mode='normal'):
        enhanced = f"{self.QUALITY_TAGS}, {prompt}"
        
        if mode == 'realism':
            enhanced += f", {self.REALISM_KEYWORDS}"
        
        return enhanced
    
    def enhance_negative_prompt(self, negative_prompt, mode='normal'):
        enhanced = negative_prompt or "low quality, blurry"
        
        if mode == 'realism':
            enhanced += f", {self.NEGATIVE_REALISM}"
        
        return enhanced
```

**预估时间**: 3小时

---

### 优先级 P1（重要）

#### 4. Task 3.1: 质量分析器
**目标**: 自动评估图像质量

**核心逻辑**:
```python
import cv2
import numpy as np

class QualityAnalyzer:
    def analyze(self, image_path):
        img = cv2.imread(image_path)
        
        # 清晰度（拉普拉斯方差）
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clarity = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # 色彩饱和度
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        saturation = np.mean(hsv[:,:,1])
        
        # 综合评分
        quality_score = min(100, (clarity / 100) * 50 + (saturation / 255) * 50)
        
        return {
            'quality_score': quality_score,
            'clarity': clarity,
            'saturation': saturation,
            'defects': []
        }
```

**预估时间**: 6小时

---

#### 5. Task 4.1: 配置热更新
**目标**: 监听配置文件变化并自动重新加载

**核心逻辑**:
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, workflow_manager):
        self.workflow_manager = workflow_manager
    
    def on_modified(self, event):
        if event.src_path.endswith('.json'):
            logger.info(f"配置文件变化: {event.src_path}")
            time.sleep(5)  # 等待文件写入完成
            self.workflow_manager.reload_current_workflow()

# 在 WorkflowManager 中
def start_file_watcher(self):
    event_handler = ConfigFileHandler(self)
    observer = Observer()
    observer.schedule(event_handler, self.config_dir, recursive=False)
    observer.start()
```

**预估时间**: 4小时

---

### 优先级 P2（可选）

#### 6. Task 2.5: 导入优秀工作流配置
**目标**: 收集并导入 10+ 优秀工作流

**资源**:
- Civitai: https://civitai.com/models?type=Workflow
- GitHub: 搜索 "comfyui workflow"
- OpenArt: https://openart.ai/workflows

**实施步骤**:
1. 研究优秀工作流的参数配置
2. 转换为标准 JSON 格式
3. 保存到 `configs/best_practices/` 目录
4. 记录来源、适用场景、效果评分

**预估时间**: 8小时

---

#### 7. Task 4.6: 更新 API 路由
**目标**: 添加新功能的 API 接口

**新增 API**:
```python
# 工作流管理
GET /api/workflows - 列出所有工作流
POST /api/workflows/switch - 切换工作流
GET /api/workflows/{id} - 获取工作流详情

# 质量分析
GET /api/images/{id}/quality - 获取质量报告
GET /api/quality/stats - 获取质量统计

# 参数优化
POST /api/optimize/parameters - 获取优化参数建议
```

**预估时间**: 4小时

---

## 📝 实施建议

### 第一阶段（1周）- 核心功能
1. ✅ Task 1.1: 工作流配置数据模型
2. ✅ Task 1.2: 工作流管理器
3. Task 1.4: 集成到 ComfyUIService
4. Task 2.1: 参数优化器
5. Task 2.2: 提示词优化器
6. Task 2.3-2.4: 集成优化器

**目标**: 让系统能够自动优化参数和提示词

### 第二阶段（1周）- 质量提升
1. Task 3.1: 质量分析器
2. Task 3.2: 集成质量分析
3. Task 3.5: 真实感增强模式
4. Task 4.1: 配置热更新
5. Task 4.3: 错误恢复机制

**目标**: 提升图像质量和系统稳定性

### 第三阶段（1周）- 完善和优化
1. Task 2.5: 导入优秀工作流
2. Task 4.2: 性能优化
3. Task 4.4: 监控和告警
4. Task 4.6: API 更新
5. Task 4.7: 用户文档

**目标**: 完善功能和文档

---

## 🔧 快速开发模板

### 创建新服务的模板

```python
"""
服务名称（ServiceName）

服务描述
"""

from typing import Dict, List, Optional
from src.utils.logger import logger


class ServiceNameError(Exception):
    """服务错误"""
    pass


class ServiceName:
    """服务类"""
    
    def __init__(self):
        """初始化服务"""
        logger.info("服务初始化完成")
    
    def main_method(self, param: str) -> Dict:
        """
        主要方法
        
        Args:
            param: 参数说明
            
        Returns:
            返回值说明
            
        Raises:
            ServiceNameError: 错误说明
        """
        try:
            # 实现逻辑
            result = {}
            return result
        except Exception as e:
            error_msg = f"操作失败: {e}"
            logger.error(error_msg)
            raise ServiceNameError(error_msg) from e


# 单例模式
_instance: Optional[ServiceName] = None

def get_service() -> ServiceName:
    """获取服务实例"""
    global _instance
    if _instance is None:
        _instance = ServiceName()
    return _instance
```

### 创建测试的模板

```python
"""
服务测试
"""

import pytest
from src.services.service_name import ServiceName, ServiceNameError


class TestServiceName:
    """测试服务"""
    
    def test_init(self):
        """测试初始化"""
        service = ServiceName()
        assert service is not None
    
    def test_main_method_success(self):
        """测试主要方法成功"""
        service = ServiceName()
        result = service.main_method("test")
        assert result is not None
    
    def test_main_method_error(self):
        """测试主要方法错误"""
        service = ServiceName()
        with pytest.raises(ServiceNameError):
            service.main_method("invalid")
```

---

## 📚 参考资源

### ComfyUI 相关
- ComfyUI 官方文档: https://github.com/comfyanonymous/ComfyUI
- ComfyUI API 文档: https://github.com/comfyanonymous/ComfyUI/wiki/API
- ComfyUI 节点参考: https://github.com/comfyanonymous/ComfyUI/wiki/Nodes

### 图像质量评估
- OpenCV 图像质量评估: https://docs.opencv.org/
- BRISQUE 算法: https://learnopencv.com/image-quality-assessment-brisque/
- NIQE 算法: https://live.ece.utexas.edu/research/Quality/niqe_release.zip

### 工作流优化
- Stable Diffusion 参数调优: https://stable-diffusion-art.com/
- ComfyUI 最佳实践: https://civitai.com/articles

---

## ✅ 验收标准

### 功能验收
- [ ] 所有 15 个需求的验收标准全部满足
- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试全部通过

### 性能验收
- [ ] 工作流切换时间 < 2 秒
- [ ] 配置热更新时间 < 5 秒
- [ ] 图像生成成功率 > 90%

### 质量验收
- [ ] 代码符合规范（4空格缩进，中文注释）
- [ ] 所有函数有完整注释
- [ ] API 文档完整

---

## 🎉 总结

通过前两个任务，我们已经建立了坚实的基础架构：

1. **WorkflowConfig**: 完整的配置数据模型和验证
2. **WorkflowManager**: 强大的工作流管理能力

接下来的任务主要是：
- **集成**: 将新组件集成到现有系统
- **优化**: 实现参数和提示词优化
- **分析**: 实现质量分析和监控
- **完善**: 添加文档和测试

建议按照优先级逐步实施，每完成一个阶段就进行测试和验证，确保系统稳定性。

---

*文档版本: 1.0*  
*创建日期: 2026-05-06*  
*最后更新: 2026-05-06*
