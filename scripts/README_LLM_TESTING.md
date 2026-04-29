# LLM 服务部署测试指南

本目录包含 LLM 服务的启动脚本和性能测试工具，用于验证 LLM 服务的部署和性能。

## 文件说明

### 启动脚本

- **start_llm_service.py**: Python 版本的启动脚本，功能完整
- **start_llm_service.sh**: Shell 版本的启动脚本，简化使用

### 性能测试

- **test_llm_performance.py**: 性能测试脚本，支持多种测试模式

### 文档

- **README_LLM_TESTING.md**: 本文档，使用指南
- **../docs/llm-performance-benchmarks.md**: 性能基准数据文档

## 前置条件

### 1. 环境配置

确保已安装以下依赖：

```bash
# 安装 llama-cpp-python
pip install llama-cpp-python==0.2.20

# 或安装所有项目依赖
pip install -r requirements.txt
```

### 2. 模型下载

下载 Qwen2.5-14B GGUF 模型：

```bash
# 使用 huggingface-cli 下载
huggingface-cli download Qwen/Qwen2.5-14B-Instruct-GGUF \
    qwen2.5-14b-instruct-q4_k_m.gguf \
    --local-dir ./models

# 或手动下载
# 访问: https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
# 下载 qwen2.5-14b-instruct-q4_k_m.gguf 到 ./models 目录
```

### 3. 环境变量配置

在项目根目录创建 `.env` 文件：

```env
# LLM 模型路径
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf

# GPU 加载的层数（默认 20 层）
LLM_N_GPU_LAYERS=20

# 上下文窗口大小
LLM_N_CTX=4096

# CPU 线程数
LLM_N_THREADS=8
```

## 使用方法

### 方式 1: 使用 Python 脚本（推荐）

#### 基本启动

启动 LLM 服务（不运行测试）：

```bash
python scripts/start_llm_service.py
```

服务启动后会显示：
- 模型加载时间
- 显存占用情况
- 模型配置信息

按 `Ctrl+C` 停止服务。

#### 启动并测试

启动服务并运行功能测试：

```bash
python scripts/start_llm_service.py --test
```

测试内容包括：
1. 基本文本生成
2. 剧本生成
3. 流式生成

#### 自定义配置

使用自定义配置启动：

```bash
python scripts/start_llm_service.py \
    --model-path ./models/qwen2.5-14b-instruct-q4_k_m.gguf \
    --n-gpu-layers 20 \
    --n-ctx 4096 \
    --n-threads 8 \
    --test
```

#### 详细日志

输出详细日志信息：

```bash
python scripts/start_llm_service.py --test --verbose
```

### 方式 2: 使用 Shell 脚本

#### Linux/Mac

```bash
# 添加执行权限
chmod +x scripts/start_llm_service.sh

# 启动服务
./scripts/start_llm_service.sh

# 启动并测试
./scripts/start_llm_service.sh --test
```

#### Windows (Git Bash)

```bash
bash scripts/start_llm_service.sh --test
```

## 性能测试

### 快速测试

测试推荐配置（20 层 GPU）：

```bash
python scripts/test_llm_performance.py --test-type quick
```

**输出**:
- 模型加载时间
- 显存占用
- 短/中/长文本生成速度
- 流式生成性能

**耗时**: 约 5-10 分钟

### 完整测试

测试所有配置（0, 10, 20, 30, 40 层 GPU）：

```bash
python scripts/test_llm_performance.py --test-type full
```

**输出**:
- 每个配置的详细性能数据
- 配置对比表
- 性能建议

**耗时**: 约 30-60 分钟

### GPU 层数测试

测试指定的 GPU 层数：

```bash
# 测试 15, 20, 25 层
python scripts/test_llm_performance.py \
    --test-type gpu-layers \
    --gpu-layers "15,20,25"
```

### CPU Offload 测试

测试 CPU offload 功能：

```bash
python scripts/test_llm_performance.py --test-type cpu-offload
```

**测试内容**:
1. 纯 GPU 模式（40 层）
2. 混合模式（20 层 GPU + 20 层 CPU）
3. 纯 CPU 模式（0 层）

### 自定义输出目录

指定结果输出目录：

```bash
python scripts/test_llm_performance.py \
    --test-type quick \
    --output-dir my_test_results
```

## 测试结果

### 结果文件

测试结果保存在 `performance_results/` 目录（或自定义目录）：

```
performance_results/
├── llm_performance_test_20240115_143022.json  # JSON 格式
└── llm_performance_test_20240115_143022.md    # Markdown 格式
```

### JSON 格式

包含完整的测试数据，可用于程序化分析：

```json
{
  "system_info": {
    "timestamp": "2024-01-15T14:30:22",
    "gpu": {
      "name": "NVIDIA GeForce RTX 4090",
      "memory_total_mb": 24576
    },
    "cpu": {
      "count": 16
    }
  },
  "test_results": [
    {
      "test_name": "GPU_20_layers",
      "config": {
        "n_gpu_layers": 20,
        "n_ctx": 4096,
        "n_threads": 8
      },
      "load_time_seconds": 15.23,
      "gpu_memory_increase_mb": 4567.89,
      "generation_tests": {
        "short": {
          "generation_time_seconds": 2.34,
          "output_length_chars": 156,
          "chars_per_second": 66.67
        }
      }
    }
  ]
}
```

### Markdown 格式

人类可读的测试报告，包含：

1. **系统信息**: GPU、CPU、内存配置
2. **测试结果汇总**: 配置对比表
3. **详细测试结果**: 每个配置的详细数据
4. **性能建议**: 基于测试结果的配置建议

示例：

```markdown
# LLM 服务性能测试报告

**生成时间**: 2024-01-15 14:30:22

## 系统信息

- **GPU**: NVIDIA GeForce RTX 4090
- **显存**: 24576 MB
- **CPU 核心数**: 16 (8 物理核心)

## 测试结果汇总

| 测试名称 | GPU 层数 | 加载时间(秒) | 显存占用(MB) | 生成速度(字符/秒) | 状态 |
|---------|---------|------------|-------------|-----------------|------|
| GPU_20_layers | 20 | 15.23 | 4567.89 | 66.67 | ✓ |

...
```

## 验证需求

本测试脚本验证以下需求：

### 需求 4.1: LLM 模型加载

- ✅ 验证模型能够正确加载
- ✅ 测试不同 n_gpu_layers 配置
- ✅ 记录加载时间

### 需求 4.2: LLM 文本生成

- ✅ 验证文本生成功能
- ✅ 测试不同长度的文本生成
- ✅ 测试流式生成
- ✅ 记录生成速度

### 需求 12.1: 显存优化

- ✅ 测试 CPU offload 功能
- ✅ 记录显存占用
- ✅ 验证不同配置的显存使用

## 常见问题

### Q: 模型加载失败，提示 "FileNotFoundError"

**A**: 检查以下几点：

1. 确认模型文件已下载到正确路径
2. 检查 `.env` 文件中的 `LLM_MODEL_PATH` 配置
3. 确认文件路径使用正斜杠 `/` 或反斜杠转义 `\\`

```bash
# 检查模型文件是否存在
ls -lh ./models/qwen2.5-14b-instruct-q4_k_m.gguf
```

### Q: 显存不足，无法加载模型

**A**: 解决方案：

1. **减少 GPU 层数**:
   ```env
   LLM_N_GPU_LAYERS=10  # 从 20 降到 10
   ```

2. **关闭其他占用显存的程序**:
   ```bash
   # 查看 GPU 使用情况
   nvidia-smi
   ```

3. **使用更小的模型**:
   - 下载 Qwen2.5-7B 模型
   - 或使用更低量化版本（Q3_K_M）

### Q: 生成速度很慢

**A**: 优化建议：

1. **增加 GPU 层数**（如果显存充足）:
   ```env
   LLM_N_GPU_LAYERS=30
   ```

2. **增加批处理大小**:
   修改 `src/services/llm_service.py`:
   ```python
   n_batch=1024  # 从 512 增加到 1024
   ```

3. **使用更快的存储**:
   - 将模型文件放在 NVMe SSD 上

### Q: 测试脚本运行时间过长

**A**: 使用快速测试模式：

```bash
# 只测试推荐配置
python scripts/test_llm_performance.py --test-type quick
```

或减少测试的 GPU 层数：

```bash
# 只测试 20 和 30 层
python scripts/test_llm_performance.py \
    --test-type gpu-layers \
    --gpu-layers "20,30"
```

### Q: 如何在 Windows 上运行 Shell 脚本？

**A**: 使用以下方式之一：

1. **Git Bash**:
   ```bash
   bash scripts/start_llm_service.sh --test
   ```

2. **WSL (Windows Subsystem for Linux)**:
   ```bash
   ./scripts/start_llm_service.sh --test
   ```

3. **直接使用 Python 脚本**（推荐）:
   ```bash
   python scripts/start_llm_service.py --test
   ```

## 下一步

完成测试后：

1. **查看测试结果**: 检查 `performance_results/` 目录中的报告
2. **更新基准文档**: 将测试数据填写到 `docs/llm-performance-benchmarks.md`
3. **调整配置**: 根据测试结果优化 `.env` 配置
4. **集成到系统**: 将 LLM 服务集成到完整的短剧生产流程

## 相关文档

- [LLM 服务使用指南](../docs/llm-service-guide.md)
- [LLM 性能基准数据](../docs/llm-performance-benchmarks.md)
- [模型设置指南](../docs/model-setup-guide.md)
- [任务 3.1.5 规格](../.kiro/specs/ai-short-drama-production/tasks.md)

## 技术支持

如遇到问题，请：

1. 查看日志输出，定位错误原因
2. 检查环境配置是否正确
3. 参考常见问题部分
4. 查阅相关文档

---

**最后更新**: 2024-01-15
