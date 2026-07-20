# 生成 Provider 重构说明

## 目标

当前系统不再把“生成图片/视频”硬编码为本地 ComfyUI。新的设计把生成能力抽象为 provider，方便后续接入即梦、可灵、海螺等更强的视频生成 API。

## Provider 列表

| Provider | 用途 | 当前状态 |
|---|---|---|
| `local_comfyui` | 本地 ComfyUI 图片生成 | 已接入 |
| `jimeng_api` | 即梦 API 图片/视频生成 | 占位，等待真实协议 |
| `kling_api` | 可灵 API 图片/视频生成 | 占位，等待真实协议 |
| `hailuo_api` | 海螺 API 图片/视频生成 | 占位，等待真实协议 |
| `hybrid` | API 优先，本地回退 | 已有框架 |

API provider 现在不会伪造成功结果；如果没有配置 endpoint/key，或者还没有接具体协议，会明确抛错。

## 配置

```env
GENERATION_PROVIDER=local_comfyui
GENERATION_PRIMARY_PROVIDER=jimeng_api

JIMENG_ENDPOINT=
JIMENG_API_KEY=
KLING_ENDPOINT=
KLING_API_KEY=
HAILUO_ENDPOINT=
HAILUO_API_KEY=
```

## 调用路径

```text
generate_image_task
 -> get_generation_provider()
 -> provider.generate_image(ImageGenerationRequest)
 -> local ComfyUI 或外部 API
```

## 后续接即梦 API 时要做的事

1. 明确即梦 API 的鉴权方式、图片生成接口、视频生成接口、轮询接口。
2. 在 `JimengApiProvider.generate_image()` 和 `generate_video()` 中实现协议。
3. 把返回素材下载到系统的 `output_path`，而不是只保存远程 URL。
4. 增加失败重试、候选结果、人工选片。
5. 给每个分镜增加 provider、seed、reference image、attempt 元数据。

## 质量策略

短剧成片质量建议走混合模式：

- 草稿、低价值镜头：`local_comfyui`
- 主角特写、高潮镜头、关键动作：`jimeng_api` / `kling_api` / `hailuo_api`
- 失败或超预算时：回退本地生成
