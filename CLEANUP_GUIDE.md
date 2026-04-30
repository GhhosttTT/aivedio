# 项目清理指南

本指南说明如何清理项目，准备上传到 GitHub。

## 🎯 清理目标

- 删除所有临时文件和开发工具文件
- 删除生成的数据库和测试文件
- 删除大型 AI 模型文件（通过 .gitignore 排除）
- 保持项目结构清晰简洁

## 🚀 快速清理

### 方法 1：使用清理脚本（推荐）

```bash
# 运行清理脚本
python cleanup_project.py
```

脚本会自动：
- ✅ 删除所有 .bat 和 .sh 临时脚本
- ✅ 删除状态和进度文件
- ✅ 删除开发工具目录（.kiro, .agents, .trae）
- ✅ 删除测试缓存和数据库文件
- ✅ 清空 storage 目录但保留结构
- ✅ 删除所有 Python 缓存

### 方法 2：手动清理

如果你想手动控制清理过程：

```bash
# 1. 删除临时脚本
rm -f *.bat *.sh

# 2. 删除状态文件
rm -f *_COMPLETE.md *_STATUS*.md *_SUMMARY.md
rm -f COMMIT_MESSAGE.txt progress.txt skills-lock.json

# 3. 删除开发工具目录
rm -rf .kiro .agents .trae .hypothesis .pytest_cache .vscode

# 4. 删除数据库文件
rm -f *.db

# 5. 清空 storage 目录
find storage -type f ! -name '.gitkeep' -delete

# 6. 删除 Python 缓存
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

## 📋 清理清单

### 需要删除的文件

- [ ] `*.bat` - Windows 批处理脚本
- [ ] `*.sh` - Shell 脚本（除了 scripts/ 目录）
- [ ] `*_COMPLETE.md` - 完成状态文件
- [ ] `*_STATUS*.md` - 状态报告文件
- [ ] `*_SUMMARY.md` - 总结文件
- [ ] `COMMIT_MESSAGE.txt` - 临时提交消息
- [ ] `progress.txt` - 进度文件
- [ ] `skills-lock.json` - 技能锁文件
- [ ] `*.db` - SQLite 数据库文件

### 需要删除的目录

- [ ] `.kiro/` - Kiro AI 工具配置
- [ ] `.agents/` - AI 代理配置
- [ ] `.trae/` - Trae 工具配置
- [ ] `.hypothesis/` - Hypothesis 测试缓存
- [ ] `.pytest_cache/` - Pytest 缓存
- [ ] `.vscode/` - VS Code 配置
- [ ] `models/` - AI 模型文件（太大）

### 需要清空的目录

- [ ] `storage/projects/` - 项目文件
- [ ] `storage/images/` - 生成的图像
- [ ] `storage/videos/` - 生成的视频
- [ ] `storage/audios/` - 生成的音频
- [ ] `storage/subtitles/` - 生成的字幕
- [ ] `storage/temp/` - 临时文件

## 📝 .gitignore 检查

确保 `.gitignore` 包含以下内容：

```gitignore
# 开发工具
.kiro/
.agents/
.trae/
.vscode/

# 临时文件
*.bat
*.sh
*_COMPLETE.md
*_STATUS*.md
*_SUMMARY.md

# 数据库
*.db
*.sqlite

# AI 模型
models/

# 生成文件
storage/projects/
storage/images/
storage/videos/
storage/audios/
storage/subtitles/

# Python
__pycache__/
*.pyc
.pytest_cache/
.hypothesis/
```

## 🔍 验证清理结果

清理完成后，检查：

```bash
# 1. 查看 git 状态
git status

# 2. 查看未跟踪的文件
git ls-files --others --exclude-standard

# 3. 检查项目大小
du -sh .

# 4. 检查是否有大文件
find . -type f -size +10M
```

## 📤 上传到 GitHub

清理完成后：

```bash
# 1. 添加所有更改
git add .

# 2. 提交更改
git commit -m "chore: 项目清理，准备发布"

# 3. 推送到 GitHub
git push origin main
```

## ⚠️ 注意事项

### 保留的文件

以下文件应该保留：
- ✅ `README.md` - 项目说明
- ✅ `LICENSE` - 许可证
- ✅ `requirements.txt` - Python 依赖
- ✅ `pyproject.toml` - 项目配置
- ✅ `.env.example` - 环境变量示例
- ✅ `.gitignore` - Git 忽略规则
- ✅ `docker-compose.yml` - Docker 配置
- ✅ `Dockerfile` - Docker 镜像
- ✅ `alembic.ini` - 数据库迁移配置

### 模型文件说明

由于 AI 模型文件太大（10GB+），不适合上传到 GitHub。

在 README.md 中添加模型下载说明：

```markdown
## 📥 下载 AI 模型

本项目需要以下 AI 模型：

1. **Qwen2.5-14B-Instruct-GGUF**
   - 下载地址：https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
   - 放置位置：`models/qwen2.5-14b-instruct-q4_k_m.gguf`

2. **Stable Diffusion XL**
   - 下载地址：https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
   - 放置位置：`models/stable-diffusion-xl-base-1.0/`

3. **Stable Video Diffusion**
   - 下载地址：https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt
   - 放置位置：`models/stable-video-diffusion-img2vid-xt/`

或使用自动下载脚本：
\`\`\`bash
bash scripts/download_models.sh
\`\`\`
```

## 🎉 完成

清理完成后，你的项目应该：
- ✅ 结构清晰
- ✅ 文件精简
- ✅ 大小合理（< 100MB）
- ✅ 准备好上传到 GitHub

---

**有问题？** 查看 [README.md](README.md) 或提交 Issue。
