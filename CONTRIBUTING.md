# 贡献指南

感谢你对 AI 短剧自动化生产平台的关注！我们欢迎所有形式的贡献。

## 🤝 如何贡献

### 报告 Bug

如果你发现了 Bug，请：

1. 检查 [Issues](https://github.com/your-org/ai-short-drama-production/issues) 确认问题是否已被报告
2. 如果没有，创建新的 Issue，包含：
   - 清晰的标题和描述
   - 复现步骤
   - 预期行为和实际行为
   - 系统环境信息
   - 相关日志和截图

### 提出新功能

如果你有新功能建议：

1. 创建 Feature Request Issue
2. 描述功能的用途和价值
3. 提供使用场景示例
4. 等待社区讨论和反馈

### 提交代码

1. **Fork 项目**
   ```bash
   git clone https://github.com/your-username/ai-short-drama-production.git
   cd ai-short-drama-production
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **编写代码**
   - 遵循项目代码规范
   - 添加必要的测试
   - 更新相关文档

4. **运行测试**
   ```bash
   python -m pytest tests/ -v
   ```

5. **提交更改**
   ```bash
   git add .
   git commit -m "feat: 添加新功能描述"
   ```

6. **推送到 GitHub**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **创建 Pull Request**
   - 提供清晰的 PR 描述
   - 关联相关 Issue
   - 等待代码审查

## 📝 代码规范

### Python 代码风格

- 使用 **4 个空格**缩进
- 遵循 [PEP 8](https://pep8.org/) 规范
- 使用类型注解（Type Hints）
- 函数和类添加文档字符串

**示例：**

```python
def generate_script(
    theme: Optional[str] = None,
    outline: Optional[str] = None,
    num_scenes: int = 10
) -> Dict[str, Any]:
    """
    生成剧本
    
    Args:
        theme: 主题关键词
        outline: 故事大纲
        num_scenes: 分镜数量
        
    Returns:
        包含剧本和分镜的字典
        
    Raises:
        ValueError: 当参数无效时
    """
    pass
```

### 命名规范

- **变量和函数**：小驼峰（camelCase）或下划线（snake_case）
- **类**：大驼峰（PascalCase）
- **常量**：全大写下划线（UPPER_SNAKE_CASE）
- **私有成员**：前缀下划线（_private）

### Commit 消息规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型（type）：**
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具相关

**示例：**
```
feat(api): 添加项目列表分页功能

- 添加 page 和 page_size 参数
- 返回总数和分页信息
- 更新 API 文档

Closes #123
```

## 🧪 测试要求

### 单元测试

- 所有新功能必须包含单元测试
- 测试覆盖率不低于 80%
- 使用 pytest 框架

```python
def test_create_project():
    """测试创建项目"""
    project = create_project(name="测试项目")
    assert project.name == "测试项目"
    assert project.status == "draft"
```

### 属性测试

对于复杂逻辑，建议添加属性测试：

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=100))
def test_project_name_valid(name):
    """测试项目名称验证"""
    project = create_project(name=name)
    assert len(project.name) > 0
```

## 📚 文档要求

### 代码文档

- 所有公共 API 必须有文档字符串
- 复杂逻辑添加行内注释
- 使用中文注释

### 用户文档

如果你的更改影响用户使用：

- 更新 README.md
- 更新相关文档（docs/）
- 添加使用示例

## 🔍 代码审查

所有 PR 都需要经过代码审查：

1. **自动检查**
   - CI/CD 测试通过
   - 代码风格检查通过
   - 测试覆盖率达标

2. **人工审查**
   - 代码质量
   - 设计合理性
   - 文档完整性

3. **反馈处理**
   - 及时回复审查意见
   - 根据反馈修改代码
   - 保持沟通

## 🎯 优先级

我们特别欢迎以下方面的贡献：

- 🐛 Bug 修复
- 📝 文档改进
- 🧪 测试覆盖
- 🚀 性能优化
- 🌐 国际化支持
- ♿ 可访问性改进

## 💬 社区

- **GitHub Discussions**: 讨论功能和想法
- **Issues**: 报告问题和建议
- **Pull Requests**: 提交代码

## 📜 行为准则

请遵守我们的 [行为准则](CODE_OF_CONDUCT.md)：

- 尊重他人
- 包容多样性
- 建设性沟通
- 专注于项目目标

## 🙏 感谢

感谢所有贡献者的付出！你的贡献让这个项目变得更好。

---

**有问题？** 随时在 Issues 中提问或发送邮件到 your-email@example.com
