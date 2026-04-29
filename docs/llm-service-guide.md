# LLM 服务使用指南

## 概述

LLMService 是 AI 短剧自动化生产平台的核心组件之一，负责封装 llama.cpp 调用逻辑，管理 Qwen2.5-14B 模型的加载和卸载，并提供剧本生成功能。

## 主要特性

- ✅ **模型加载与管理**：支持 GGUF 格式模型的加载和卸载
- ✅ **CPU Offload 优化**：通过配置 GPU 层数，将部分层 offload 到 CPU，优化显存使用
- ✅ **文本生成**：支持多种生成参数（temperature、top_p、max_tokens 等）
- ✅ **流式生成**：支持流式输出，实时获取生成结果
- ✅ **剧本生成**：提供专门的剧本生成 Prompt 模板
- ✅ **错误处理**：完善的错误处理和日志记录
- ✅ **模型预热**：首次加载时自动预热，优化后续调用性能
- ✅ **单例模式**：支持全局单例实例，避免重复加载模型

## 环境配置

### 1. 安装依赖

```bash
pip install llama-cpp-python==0.2.20
```

### 2. 下载模型

从 Hugging Face 下载 Qwen2.5-14B GGUF 模型：

```bash
# 使用 huggingface-cli 下载
huggingface-cli download Qwen/Qwen2.5-14B-Instruct-GGUF \
    qwen2.5-14b-instruct-q4_k_m.gguf \
    --local-dir ./models
```

或手动下载：
- 模型地址：https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
- 推荐使用 Q4_K_M 量化版本（约 8GB）

### 3. 配置环境变量

在 `.env` 文件中添加以下配置：

```env
# LLM 模型路径
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf

# GPU 加载的层数（默认 20 层，约占用 4-6GB 显存）
LLM_N_GPU_LAYERS=20

# 上下文窗口大小
LLM_N_CTX=4096

# CPU 线程数
LLM_N_THREADS=8
```

## 使用方法

### 方式 1：直接创建实例

```python
from src.services.llm_service import LLMService

# 创建服务实例
service = LLMService(
    model_path="./models/qwen2.5-14b-instruct-q4_k_m.gguf",
    n_gpu_layers=20,  # GPU 加载 20 层
    n_ctx=4096,       # 上下文窗口 4096
    n_threads=8       # CPU 线程数 8
)

# 生成文本
response = service.generate(
    prompt="你好，请介绍一下你自己。",
    max_tokens=100,
    temperature=0.7
)

print(response)

# 卸载模型
service.unload_model()
```

### 方式 2：使用全局单例

```python
from src.services.llm_service import get_llm_service, cleanup_llm_service

# 获取全局单例实例（自动从环境变量读取配置）
service = get_llm_service()

# 生成文本
response = service.generate(
    prompt="你好，请介绍一下你自己。",
    max_tokens=100,
    temperature=0.7
)

print(response)

# 应用关闭时清理资源
cleanup_llm_service()
```

## API 参考

### LLMService 类

#### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_path` | `str` | 环境变量 | GGUF 模型文件路径 |
| `n_gpu_layers` | `int` | 20 | GPU 加载的层数（剩余层 offload 到 CPU） |
| `n_ctx` | `int` | 4096 | 上下文窗口大小 |
| `n_threads` | `int` | 8 | CPU 线程数 |
| `n_batch` | `int` | 512 | 批处理大小 |
| `verbose` | `bool` | False | 是否输出详细日志 |

#### generate() 方法

生成文本的主要方法。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | `str` | 必需 | 输入提示词 |
| `max_tokens` | `int` | 2048 | 最大生成 token 数 |
| `temperature` | `float` | 0.7 | 温度参数（0.0-2.0），控制随机性 |
| `top_p` | `float` | 0.9 | Top-p 采样参数（0.0-1.0） |
| `top_k` | `int` | 40 | Top-k 采样参数 |
| `repeat_penalty` | `float` | 1.1 | 重复惩罚 |
| `stop` | `list` | None | 停止词列表 |
| `stream` | `bool` | False | 是否流式输出 |
| `callback` | `Callable` | None | 流式输出回调函数 |

**返回值：** `str` - 生成的文本

**示例：**

```python
# 基本使用
response = service.generate(
    prompt="请写一个关于友情的故事",
    max_tokens=500,
    temperature=0.8
)

# 使用停止词
response = service.generate(
    prompt="请列举三种水果：",
    max_tokens=100,
    stop=["4.", "\n\n"]
)

# 流式生成
def on_token(token: str):
    print(token, end='', flush=True)

response = service.generate(
    prompt="请介绍一下人工智能",
    max_tokens=200,
    stream=True,
    callback=on_token
)
```

#### generate_script_prompt() 方法

构建剧本生成的 Prompt。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `theme` | `str` | None | 主题关键词（可选） |
| `outline` | `str` | None | 故事大纲（可选） |
| `num_scenes` | `int` | 10 | 分镜数量 |
| `num_characters` | `int` | 2 | 角色数量 |
| `style` | `str` | "现代都市" | 风格偏好 |

**返回值：** `str` - 完整的 Prompt 文本

**注意：** `theme` 和 `outline` 至少需要提供一个。

**示例：**

```python
# 使用主题
prompt = service.generate_script_prompt(
    theme="都市爱情",
    num_scenes=10,
    num_characters=2,
    style="现代都市"
)

# 使用大纲
prompt = service.generate_script_prompt(
    outline="一个关于职场白领的爱情故事",
    num_scenes=5,
    num_characters=3,
    style="现代都市"
)

# 生成剧本
script = service.generate(prompt, max_tokens=2048)
```

#### unload_model() 方法

卸载模型释放资源。

**示例：**

```python
service.unload_model()
```

#### get_model_info() 方法

获取模型配置信息。

**返回值：** `dict` - 包含模型配置信息的字典

**示例：**

```python
info = service.get_model_info()
print(info)
# {
#     "model_path": "./models/qwen2.5-14b-instruct-q4_k_m.gguf",
#     "n_gpu_layers": 20,
#     "n_ctx": 4096,
#     "n_threads": 8,
#     "n_batch": 512,
#     "is_loaded": True
# }
```

## 显存优化

### GPU 层数配置

LLMService 通过 `n_gpu_layers` 参数控制 GPU 加载的层数，剩余层会 offload 到 CPU 执行。

**Qwen2.5-14B 模型层数：** 40 层

**显存占用估算：**

| GPU 层数 | 显存占用 | 推理速度 | 适用场景 |
|---------|---------|---------|---------|
| 0 | ~1GB | 慢 | 纯 CPU 推理 |
| 10 | ~2-3GB | 较慢 | 显存紧张 |
| 20 | ~4-6GB | 中等 | **推荐配置** |
| 30 | ~6-8GB | 较快 | 显存充足 |
| 40 | ~8-10GB | 快 | 纯 GPU 推理 |

**推荐配置：**

- **RTX 4090/3090 (24GB)**：`n_gpu_layers=20`（为 SD 和 SVD 预留显存）
- **RTX 4080 (16GB)**：`n_gpu_layers=15`
- **RTX 4070 (12GB)**：`n_gpu_layers=10`

### 显存不足处理

如果遇到显存不足错误，可以：

1. **减少 GPU 层数**：降低 `LLM_N_GPU_LAYERS` 环境变量的值
2. **清理 GPU 缓存**：在任务切换时调用 `torch.cuda.empty_cache()`
3. **使用更小的模型**：考虑使用 Qwen2.5-7B 或更小的模型

## 错误处理

### 常见错误

#### 1. 模型文件不存在

```
FileNotFoundError: LLM 模型文件不存在: ./models/qwen2.5-14b-instruct-q4_k_m.gguf
```

**解决方法：**
- 检查模型文件路径是否正确
- 确保模型文件已下载

#### 2. 显存不足

```
RuntimeError: 显存不足，无法加载模型。当前 GPU 层数: 20，请减少 LLM_N_GPU_LAYERS 环境变量的值
```

**解决方法：**
- 减少 `LLM_N_GPU_LAYERS` 的值（如从 20 降到 15 或 10）
- 关闭其他占用显存的程序

#### 3. llama-cpp-python 未安装

```
RuntimeError: llama-cpp-python 未安装，请运行: pip install llama-cpp-python
```

**解决方法：**
```bash
pip install llama-cpp-python==0.2.20
```

## 性能优化建议

### 1. 模型预热

LLMService 在初始化时会自动进行模型预热，避免首次调用的延迟。

### 2. 批处理

如果需要生成多个文本，建议复用同一个 LLMService 实例，避免重复加载模型。

### 3. 上下文窗口

根据实际需求调整 `n_ctx` 参数：
- 短文本生成：2048
- 中等长度：4096（推荐）
- 长文本生成：8192

### 4. CPU 线程数

根据 CPU 核心数调整 `n_threads` 参数：
- 4 核 CPU：4
- 8 核 CPU：8（推荐）
- 16 核 CPU：12-16

## 测试

运行单元测试：

```bash
python -m pytest tests/test_services/test_llm_service.py -v
```

测试覆盖：
- ✅ 模型初始化
- ✅ 文本生成
- ✅ 流式生成
- ✅ 剧本 Prompt 构建
- ✅ 停止词处理
- ✅ 模型卸载
- ✅ 错误处理
- ✅ 全局单例

## 示例代码

完整的示例代码请参考：`examples/llm_service_example.py`

运行示例：

```bash
python examples/llm_service_example.py
```

## 常见问题

### Q: 如何选择合适的 temperature 值？

A: 
- `0.0-0.3`：确定性输出，适合事实性内容
- `0.4-0.7`：平衡创造性和一致性，**推荐用于剧本生成**
- `0.8-1.0`：高创造性，适合创意写作
- `>1.0`：非常随机，可能产生不连贯的内容

### Q: 如何提高生成速度？

A:
1. 增加 `n_gpu_layers`（如果显存充足）
2. 减少 `max_tokens`
3. 使用更小的模型（如 Qwen2.5-7B）
4. 增加 `n_batch`（如 1024）

### Q: 如何避免重复内容？

A:
1. 增加 `repeat_penalty`（如 1.2-1.3）
2. 使用 `top_p` 采样（如 0.9）
3. 适当提高 `temperature`

### Q: 如何在多个请求间共享模型？

A: 使用全局单例模式：

```python
from src.services.llm_service import get_llm_service

# 在不同的请求处理函数中
service = get_llm_service()  # 总是返回同一个实例
response = service.generate(prompt)
```

## 相关文档

- [模型设置指南](./model-setup-guide.md)
- [API 文档](../README.md)
- [性能优化指南](./performance-optimization.md)

## 许可证

本项目采用 MIT 许可证。
