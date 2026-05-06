# 角色一致性问题修复 - 更新日志

## 版本信息
- **修复日期**: 2026-05-06
- **问题**: 不同角色生成的图像相似度过高，主角和反派"长一个样子"
- **影响范围**: 图像生成、角色管理、提示词增强

## 修复内容

### 1. 核心功能改进

#### 1.1 自动生成角色外貌特征
**文件**: `src/services/script_generator.py`

**新增方法**:
```python
def _generate_character_appearance(self, character_name: str, character_description: str) -> str
```

**功能**:
- 在剧本生成时自动为每个角色生成详细的外貌特征
- 包含年龄、发型、服装、气质、独特标识等8个维度
- 使用 LLM 确保外貌特征具体、独特、可区分

**修改方法**:
```python
def _save_script_to_db(self, project: Project, parsed_script: Dict)
```

**改进**:
- 在保存角色时自动调用外貌特征生成
- 将生成的外貌特征保存到 `Character.appearance` 字段

#### 1.2 增强提示词生成
**文件**: `src/services/prompt_enhancer.py`

**修改方法**:
```python
def enhance_prompt(
    self,
    visual_description: str,
    character_name: str = None,
    character_appearance: str = None,  # 新增参数
    scene_context: str = None
) -> str
```

**改进**:
- 新增 `character_appearance` 参数
- 更新 System Prompt，强调角色特征明确性
- 禁止使用泛化词汇（handsome, beautiful）
- 要求使用具体的视觉特征描述

**修改方法**:
```python
def batch_enhance_prompts(self, scenes: list) -> dict
```

**改进**:
- 支持传递角色外貌特征到批量增强

#### 1.3 图像生成时注入角色特征
**文件**: `src/tasks/image_tasks.py`

**修改方法**:
```python
def generate_image_task(
    self,
    scene_id: int,
    prompt: str,
    project_id: int,
    task_id: int,
    character_name: str = None,
    **kwargs
)
```

**改进**:
- 从数据库查询角色的外貌特征
- 将外貌特征传递给提示词增强器
- 如果角色没有外貌特征，记录警告日志
- 降级处理：如果增强失败，至少将外貌特征加入提示词

### 2. 新增工具

#### 2.1 角色外貌设置工具
**文件**: `scripts/setup_character_appearances.py`

**功能**:
- 交互式设置角色外貌特征
- 提供10+个外貌模板（年轻女性、成熟男性、霸总型等）
- 支持自定义输入
- 智能推荐（根据角色名称）
- 批量处理

**使用方法**:
```bash
python scripts/setup_character_appearances.py
```

#### 2.2 功能测试脚本
**文件**: `scripts/test_character_appearance_generation.py`

**功能**:
- 测试角色外貌特征生成
- 测试提示词增强功能
- 验证不同角色是否有明显区分

**使用方法**:
```bash
python scripts/test_character_appearance_generation.py
```

### 3. 文档更新

#### 3.1 修复方案文档
**文件**: `docs/character-consistency-fix.md`

**内容**:
- 问题描述和原因分析
- 详细的解决方案
- 技术实现细节
- 效果对比
- 未来改进方向

#### 3.2 使用指南
**文件**: `docs/character-appearance-guide.md`

**内容**:
- 快速开始指南
- 外貌特征规范
- 工具使用教程
- 常见问题解答
- 最佳实践

## 技术细节

### 角色外貌特征规范

**必须包含的8个维度**:
1. 年龄段（如"25岁"、"30岁"）
2. 性别（男性/女性）
3. 发型和发色（如"短发"、"长发披肩"）
4. 脸型特征（如"瓜子脸"、"方脸"）
5. 身材特征（如"身材苗条"、"身材挺拔"）
6. 服装风格（如"商务西装"、"优雅连衣裙"）
7. 气质特征（如"温柔气质"、"霸道总裁气场"）
8. 独特标识（如"戴金丝眼镜"、"略带胡茬"）

**示例**:
```
30岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质，身材挺拔
```

### 提示词增强改进

**禁止使用的泛化词汇**:
- ❌ handsome, beautiful（太泛化，无法区分角色）
- ❌ perfect, flawless（不真实）
- ❌ ultra-detailed, hyper-realistic（过度渲染）

**推荐使用的具体描述**:
- ✅ age 30 with short hair（具体年龄和发型）
- ✅ wearing gold-rimmed glasses（独特标识）
- ✅ mature and composed demeanor（气质特征）
- ✅ realistic facial features, natural skin texture（真实感）

### 数据流程

```
剧本生成
  ↓
创建角色 → 自动生成外貌特征 → 保存到数据库
  ↓
图像生成任务
  ↓
查询角色外貌特征
  ↓
传递给提示词增强器
  ↓
生成包含角色特征的提示词
  ↓
调用 ComfyUI 生成图像
  ↓
不同角色有明显区分 ✅
```

## 兼容性

### 向后兼容
- ✅ 现有项目不受影响
- ✅ 可以使用工具为现有角色设置外貌特征
- ✅ 如果角色没有外貌特征，系统会记录警告但不会报错

### 降级处理
- 如果 LLM 服务不可用，使用角色描述作为外貌特征
- 如果提示词增强失败，至少将外貌特征加入原始提示词
- 如果角色没有外貌特征，使用原有的提示词生成逻辑

## 测试建议

### 1. 功能测试
```bash
# 测试角色外貌特征生成
python scripts/test_character_appearance_generation.py
```

### 2. 集成测试
1. 创建新项目
2. 生成剧本
3. 检查角色是否有外貌特征
4. 开始生产
5. 检查生成的图像是否有明显区分

### 3. 现有项目测试
1. 选择一个现有项目
2. 使用工具设置角色外貌特征
3. 重新生成图像
4. 对比修复前后的效果

## 已知限制

1. **LLM 依赖**: 自动生成外貌特征需要 LLM 服务，如果不可用会降级
2. **手动调整**: 自动生成的外貌特征可能不完美，需要手动调整
3. **语言限制**: 当前主要支持中文角色名称和描述

## 未来改进

### 短期（1-2周）
- [ ] 增加更多外貌模板（古装、科幻等）
- [ ] 外貌特征相似度检测
- [ ] 可视化预览功能

### 中期（1-2月）
- [ ] 角色关系图可视化
- [ ] 外貌特征库（预设角色）
- [ ] 多语言支持

### 长期（3-6月）
- [ ] 基于图像的外貌特征提取
- [ ] 角色外貌演化（年龄变化）
- [ ] 风格迁移（现代→古装）

## 贡献者

- **问题发现**: 用户反馈
- **方案设计**: AI 开发团队
- **代码实现**: Kiro AI Assistant
- **文档编写**: Kiro AI Assistant
- **测试验证**: 待进行

## 相关链接

- [修复方案详细文档](docs/character-consistency-fix.md)
- [使用指南](docs/character-appearance-guide.md)
- [角色一致性最佳实践](docs/character-consistency.md)

## 反馈

如果在使用过程中遇到问题或有改进建议，请：
1. 查看文档中的常见问题
2. 运行测试脚本验证功能
3. 提交问题报告

---

**修复状态**: ✅ 已完成  
**测试状态**: ⏳ 待测试  
**文档状态**: ✅ 已完成  
**部署状态**: ⏳ 待部署
