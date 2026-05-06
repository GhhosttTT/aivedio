# 角色一致性问题修复方案

## 问题描述

在短剧制作中，不同角色（主角、反派、配角等）生成的图像可能会出现"长一个样子"的问题，这是因为：

1. **缺少独特的外貌特征描述**：所有男性角色可能都使用"1man, handsome"这种通用描述
2. **提示词中没有区分角色**：图像生成时没有将角色的独特特征注入到提示词中
3. **角色外貌字段未使用**：虽然数据库有 `appearance` 字段，但在图像生成流程中没有被使用

## 解决方案

### 1. 自动生成角色外貌特征

**修改文件**: `src/services/script_generator.py`

在剧本生成时，系统会自动为每个角色生成详细的外貌特征：

```python
def _generate_character_appearance(self, character_name: str, character_description: str) -> str:
    """
    使用 LLM 为角色生成独特的外貌特征
    
    包含：年龄、发型、服装、气质、独特标识等
    """
```

**生成的外貌特征示例**：
- 主角："30岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质，身材挺拔"
- 反派："35岁男性，中分发型，略带胡茬，休闲西装，不羁气质，冷峻面容"
- 女主："25岁女性，长发披肩，温柔气质，清秀面容，身材苗条，穿着优雅连衣裙"

### 2. 增强提示词生成

**修改文件**: `src/services/prompt_enhancer.py`

提示词增强器现在支持角色外貌特征参数：

```python
def enhance_prompt(
    self,
    visual_description: str,
    character_name: str = None,
    character_appearance: str = None,  # 新增参数
    scene_context: str = None
) -> str:
```

**改进的 System Prompt**：
- 强调角色特征明确性
- 禁止使用泛化词汇（如"handsome"、"beautiful"）
- 要求使用具体的视觉特征描述
- 提供详细的角色外貌描述规范

### 3. 图像生成时注入角色特征

**修改文件**: `src/tasks/image_tasks.py`

在图像生成任务中，系统会：

1. 从数据库查询角色的外貌特征
2. 将外貌特征传递给提示词增强器
3. 生成包含角色独特特征的图像提示词

```python
# 查询角色外貌特征
character = db.query(Character).filter(
    Character.project_id == project_id,
    Character.name == scene.character_name
).first()

if character and character.appearance:
    character_appearance = character.appearance
    logger.info(f"角色 '{scene.character_name}' 外貌特征: {character_appearance}")

# 传递给提示词增强器
enhanced_prompt = enhancer.enhance_prompt(
    visual_description=prompt,
    character_name=scene.character_name,
    character_appearance=character_appearance,  # 注入外貌特征
    scene_context=None
)
```

### 4. 手动设置工具

**新增文件**: `scripts/setup_character_appearances.py`

提供交互式工具，用于为现有项目的角色设置外貌特征：

**功能**：
- 列出项目中的所有角色
- 查看外貌模板（年轻女性、成熟男性、霸总型等）
- 为角色设置自定义外貌特征
- 智能推荐外貌特征（根据角色名称）

**使用方法**：
```bash
python scripts/setup_character_appearances.py
```

**外貌模板示例**：
- 年轻女性_温柔型："25岁女性，长发披肩，温柔气质，清秀面容，身材苗条，穿着优雅连衣裙"
- 成熟男性_霸总型："32岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质，身材挺拔"
- 年轻男性_痞帅型："28岁男性，微卷短发，不羁气质，休闲装扮，略带胡茬"

## 使用流程

### 新项目（自动）

1. 用户创建项目并生成剧本
2. 系统自动为每个角色生成独特的外貌特征
3. 图像生成时自动使用角色外貌特征
4. 不同角色生成的图像具有明显区分

### 现有项目（手动）

1. 运行外貌设置工具：
   ```bash
   python scripts/setup_character_appearances.py
   ```

2. 选择项目

3. 为每个角色设置外貌特征：
   - 使用模板（快速）
   - 自定义输入（精确）

4. 重新生成图像，角色外貌将保持一致且有区分

## 效果对比

### 修复前

**主角提示词**：
```
1man, handsome, standing in office, natural lighting
```

**反派提示词**：
```
1man, handsome, sitting in car, natural lighting
```

**问题**：两个角色的提示词几乎相同，生成的图像会很相似

### 修复后

**主角提示词**：
```
raw photo, candid shot, 1man age 30 with short hair, wearing gold-rimmed glasses, 
business suit, mature and composed demeanor, standing in office, natural expression, 
realistic facial features, natural skin texture, natural window light, film grain, 
documentary photography style, authentic moment, unposed, 35mm film aesthetic
```

**反派提示词**：
```
raw photo, candid shot, 1man age 35 with middle-parted hair, slight stubble, 
casual suit, rebellious temperament, cold expression, sitting in luxury car, 
natural expression, realistic facial features, natural skin texture, ambient light, 
film grain, documentary photography style, authentic moment, unposed, 35mm film aesthetic
```

**效果**：
- 主角：30岁，短发，戴眼镜，商务西装，成熟稳重
- 反派：35岁，中分发型，有胡茬，休闲西装，不羁冷峻

两个角色有明显的视觉区分！

## 技术细节

### 角色外貌特征生成规范

必须包含的元素：
1. **年龄段**：如"25岁"、"30岁"
2. **性别**：男性/女性
3. **发型和发色**：如"短发"、"长发披肩"、"微卷黑发"
4. **脸型特征**：如"瓜子脸"、"方脸"
5. **身材特征**：如"身材苗条"、"身材挺拔"
6. **服装风格**：如"商务西装"、"优雅连衣裙"
7. **气质特征**：如"温柔气质"、"霸道总裁气场"
8. **独特标识**：如"戴金丝眼镜"、"略带胡茬"

### 提示词增强规范

**禁止使用的泛化词汇**：
- ❌ handsome, beautiful（太泛化）
- ❌ perfect, flawless（不真实）
- ❌ ultra-detailed, hyper-realistic（过度渲染）

**推荐使用的具体描述**：
- ✅ age 30 with short hair（具体年龄和发型）
- ✅ wearing gold-rimmed glasses（独特标识）
- ✅ mature and composed demeanor（气质特征）
- ✅ realistic facial features, natural skin texture（真实感）

## 注意事项

1. **角色外貌一致性**：
   - 同一角色在不同分镜中应使用相同的外貌特征
   - 系统会自动从数据库读取角色外貌特征

2. **IP-Adapter 参考图**：
   - 角色首次生成的图像会自动保存为参考图
   - 后续分镜会使用参考图保持面部一致性
   - 外貌特征 + IP-Adapter = 最佳一致性

3. **LLM 服务依赖**：
   - 自动生成外貌特征需要 LLM 服务
   - 如果 LLM 不可用，会使用角色描述作为降级方案

4. **手动调整**：
   - 如果自动生成的外貌特征不满意，可以使用工具手动调整
   - 建议在生成图像前检查角色外貌特征

## 未来改进

1. **角色外貌库**：
   - 预设更多角色外貌模板
   - 支持按风格（现代、古装、科幻等）筛选

2. **外貌特征验证**：
   - 检查外貌特征是否足够独特
   - 警告相似度过高的角色

3. **可视化预览**：
   - 在设置外貌特征时生成预览图
   - 帮助用户更直观地调整

4. **角色关系图**：
   - 可视化角色之间的关系
   - 确保主要角色外貌差异明显

## 总结

通过这次修复，系统现在能够：

✅ 自动为每个角色生成独特的外貌特征  
✅ 在图像生成时注入角色外貌特征  
✅ 确保不同角色有明显的视觉区分  
✅ 提供手动调整工具  
✅ 保持角色在不同分镜中的一致性  

**结果**：主角和反派不再"长一个样子"，每个角色都有独特的视觉特征！
