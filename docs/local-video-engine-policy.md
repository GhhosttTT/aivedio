# 本地视频引擎准入

## 目的

短剧成片质量由基础视频模型的时序能力设定上限。角色参考图、分镜约束、候选筛选和 VLM 审核能降低失败率，无法把低时序能力的模型提升为高质量视频模型。

## 当前规则

`preflight_production_video_engine` 会检查 `COMFYUI_VIDEO_WORKFLOW_PATH` 里的模型标识：

| 工作流识别结果 | 最终成片 | 用途 |
| --- | --- | --- |
| `svd_legacy` | 阻断 | 草稿运动、流程联调 |
| `wan_2_2_ti2v_5b` | 可进入真实 GPU 样片验证 | 24GB 级显存的本地短镜头候选路线 |
| `wan_2_2_i2v_14b` | 可进入真实 GPU 样片验证 | 高显存单首帧质量候选路线 |
| `wan_2_2` | 阻断 | 变体不明确，不能证明实际模型容量 |
| `hunyuanvideo_i2v` | 可进入真实 GPU 样片验证 | 单首帧本地短镜头备选路线 |
| `ltx_2_keyframes` | 可进入真实 GPU 多关键帧验证 | 多阶段动作、道具交互和表演锚点主路线 |
| `hunyuanvideo_1_5_keyframes` | 可进入真实 GPU 多关键帧验证 | 多关键帧高质量备选路线 |
| `hunyuan_custom` | 可进入真实 GPU 驱动验证 | 音频或动作参考驱动的表演/动作镜头 |
| `hunyuanvideo_avatar` | 可进入真实 GPU 对白验证 | 音频驱动的单人或多人对白表演 |
| `wan_2_2_animate` | 可进入真实 GPU 动作验证 | 视频驱动的人物动作和表演迁移 |
| `unknown` | 阻断 | 需要明确模型与工作流证据 |

`LOCAL_VIDEO_MODEL_PROFILE=auto` 默认使用工作流识别结果。配置显式 profile 时，系统会核对它和工作流识别结果，避免把 SVD 工作流标称为高质量模型。

启用 `GENERATION_VIDEO_MID_KEYFRAME_ENABLED=true` 后，普通 Wan 2.2 I2V/TI2V 和普通 HunyuanVideo I2V profile 会被阻断。当前时间锚点请求需要 `ltx_2_keyframes` 或 `hunyuanvideo_1_5_keyframes`，并且工作流必须把 `keyframe_images` 与 `keyframe_indices` 绑定到真实时间条件节点。多张普通参考图、元数据节点和仅用于预览的图片列表都不满足该条件。

Wan 2.2 和 HunyuanVideo-I2V profile 要求 `GENERATION_VIDEO_MODEL_FPS >= 24`。最终封装成 24fps 与模型原生以 24fps 采样是两件不同的事；低帧率素材的插帧无法恢复缺失的动作和表演时序。

同时必须满足 `GENERATION_VIDEO_MAX_FRAMES >= ceil(GENERATION_VIDEO_TARGET_SECONDS * GENERATION_VIDEO_MODEL_FPS)`。当前默认的 40 帧仅适合 8fps 草稿；以 24fps 生成时，3.6 秒镜头至少需要 87 帧。

## 多关键帧生产配置起点

以下配置只用于启动真实样片验证，不能直接视为商用验收：

```dotenv
GENERATION_PROVIDER=local_comfyui
COMFYUI_VIDEO_WORKFLOW_PATH=configs/ltx2_keyframes_api.json
COMFYUI_VIDEO_BINDINGS_PATH=configs/ltx2_keyframes_api.bindings.json
LOCAL_VIDEO_MODEL_PROFILE=ltx_2_keyframes
GENERATION_VIDEO_MID_KEYFRAME_ENABLED=true
GENERATION_VIDEO_MAX_MID_KEYFRAMES=2
GENERATION_VIDEO_MID_KEYFRAME_MIN_SECONDS=3.0
GENERATION_VIDEO_KEYFRAME_REFERENCE_MIN_SCORE=2.5
GENERATION_VIDEO_MODEL_FPS=24
GENERATION_VIDEO_OUTPUT_FPS=24
GENERATION_VIDEO_TARGET_SECONDS=4.0
GENERATION_VIDEO_MAX_FRAMES=120
GENERATION_VIDEO_END_FRAME_ENABLED=true
GENERATION_REQUIRE_VIDEO_REVIEW=true
```

导出 ComfyUI API 工作流后，运行：

```powershell
python -m scripts.scaffold_video_workflow_bindings configs/ltx2_keyframes_api.json
python scripts/validate_local_generation.py preflight-video-workflow
python scripts/validate_local_generation.py preflight-production-video
```

预检必须同时出现：模型 `supports_temporal_keyframes=true`、工作流 `has_temporal_keyframe_control=true`，以及可用的视频输出节点。最终样片还必须在标准化后包含全部 `keyframe_references` 评分证据。

## 按镜头能力路由工作流

单个本地工作流会让全部镜头受同一模型能力上限约束。需要组合 Wan 的画面能力和 LTX 的关键帧控制时，复制
`configs/local_video_engine_registry.example.json`，把各条目指向真实的 ComfyUI API 工作流与绑定清单，然后配置：

```dotenv
COMFYUI_VIDEO_ENGINE_REGISTRY_PATH=./configs/local_video_engine_registry.json
```

候选生成前执行以下选择规则：

- 镜头合同明确声明 `temporal_keyframes` 时强制要求该能力。辅助关键帧不会把所有镜头强制路由到关键帧模型；不支持时序条件的专用表演模型不会接收中间帧或末帧输入。
- 动作和道具交互镜头强制要求 `motion_control`。
- `dialogue_reaction`、`emotion_reaction` 和对白镜头强制要求 `performance_control`。
- 多人镜头强制要求 `multi_character`。
- 有人物出镜的镜头强制要求 `identity_reference`；无人出镜的环境镜头不附加身份要求。
- 模型 profile 还要匹配镜头职责。HunyuanVideo-Avatar 仅参与对白和情绪表演镜头；Wan 2.2 Animate 仅参与动作、道具交互、对白和情绪表演镜头；HunyuanCustom 至少需要一个可见主体。环境建立镜头不会因为专用模型优先级更高而错误进入 Avatar/Animate 工作流。
- 一个引擎必须同时满足当前镜头的全部能力组合和原生输入条件。没有完整匹配时直接阻断，并列出各引擎缺失能力或音频/动作视频；无能力要求的环境镜头按 `priority` 排序。

质量候选会在全部可执行引擎之间按 `priority` 轮转，而非固定一个模型反复换 seed。每个候选保存实际 `engine_id`、`model_profile`、workflow、bindings 和请求合同，现有 VLM、技术指标及人工门槛从跨模型候选中选出最佳结果。候选总预算仍由质量策略控制；注册表内只有一个可执行引擎时行为与单工作流模式一致。

实际选择的引擎、工作流文件证据和绑定文件证据会写入 provider request contract。工作流发生变化后，请求哈希也会变化，避免重试任务复用旧引擎的结果。

生产预检会逐项连接 ComfyUI，检查注册表内全部工作流、绑定清单、模型 profile 和时间关键帧能力。它还要求至少有一个可用引擎分别覆盖“身份+表演”“身份+表演+多人”“身份+动作”；启用中间关键帧后，还要求“身份+动作+时间关键帧”组合。能力散落在多个无法单独完成镜头的引擎上不能通过。任一引擎失败或核心能力组合缺失时，整个注册表保持阻断。真实样片验收绑定注册表整体指纹；修改任一工作流、绑定文件、能力声明或原生采样参数后，已有样片状态自动视为过期。

模型profile同时限定可声明能力。普通 Wan 2.2 I2V 和普通 HunyuanVideo I2V 只能声明身份参考；HunyuanCustom可声明身份、表演、多人和动作控制；HunyuanVideo-Avatar可声明身份、表演和多人对白；Wan 2.2 Animate可声明身份、表演和动作驱动；LTX-2/HunyuanVideo 1.5关键帧profile可声明身份、动作和时间关键帧。超出profile的声明会在预检阶段阻断，避免把通用I2V工作流误标成专用短剧引擎。

专用模型必须获得真实条件素材：

- HunyuanVideo-Avatar 的表演镜头使用当前镜头已生成的对白音频；没有对白音频时，可在镜头规格填写 `performance_reference_audio`。两者都不存在时阻断生成。
- Wan 2.2 Animate 和 HunyuanCustom 的动作控制镜头必须在镜头规格填写 `motion_reference_video`。上一镜头视频只用于连续性参考，不会被当作当前镜头的动作驱动。
- HunyuanCustom 的表演控制需要对白/表演音频或显式动作参考视频。输入路径在任务执行机器上必须存在。
- 工作流还必须把 `reference_audios_json` 或 `reference_videos_json` 绑定到真实模型条件节点；仅写入元数据不算接入。

动作镜头可配置 `LOCAL_MOTION_REFERENCE_LIBRARY_PATH` 指向审核过的本地驱动视频清单。清单格式参考 `configs/motion_reference_library.example.json`。系统只在镜头角色、动作强度、出镜人数和中英文动作标签同时满足时自动选取；不做近义词猜测，匹配不到时保持原有阻断。镜头规格显式填写的 `motion_reference_video` 始终优先。选中素材的资产 ID、绝对路径、SHA-256、命中标签和选择原因会写入 `motion_reference_source`，保证同一生成结果可以追溯到具体动作素材。生产预检会在 GPU 任务前验证清单结构及全部文件。

动作驱动候选会额外计算 `driving_motion_reference`：把驱动视频与候选视频的运动能量曲线按时间重采样，并使用稠密光流比较主运动方向和运动区域中心轨迹，综合时间形状、运动强度、时长及空间方向得到0-5分。低于 `GENERATION_VIDEO_DRIVING_MOTION_MIN_SCORE` 的候选不能晋级；存在光流空间证据时，方向相似度还必须达到 `GENERATION_VIDEO_DRIVING_MOTION_MIN_DIRECTION_SIMILARITY`，方向相反的候选即使总运动量接近也不能通过。该指标能发现明显方向错误和运动区域错位，仍无法替代人体关键点与人工表演验收。

包含台词的镜头在通用表演审核之外，还必须提供 `visible_mouth_articulation` 和 `speech_timing` 两项VLM证据。前者检查说话人物是否有自然变化的嘴型，后者检查嘴部活动与反应停顿是否跟随对白节拍。抽帧审核只能发现闭嘴说话、持续乱动、明显延迟和说错人物等问题，不能证明逐音素口型准确；正式验收仍需观看带声音样片。

`summarize` 还会读取每个正式 `.quality.json` 中的 `local_engine_route.engine_id` 和 `selection_reasons`。注册表内每个引擎都必须有通过最终标准化视频审核的代表样片；这些样片合并后还要实际触发该引擎声明的身份、表演、多人、动作和时间关键帧能力。只验证其中一个引擎、用简单静态镜头替代专项能力验证、路由元数据缺失或样片未通过，`local_engine_sample_coverage_passed` 都会保持 `false`，不能进入 `ready_for_seed_dance_candidate`。时间关键帧能力还必须由同一个注册引擎同时证明：声明 `temporal_keyframes=true`、模型支持帧索引条件、工作流存在真实时间条件绑定，并且预检状态为 ready。

## 成片策略

1. 每个镜头控制在 3-6 秒，只保留一个动作和一个情绪节拍。
2. 在视频生成前固定角色三视图、服装/道具/伤口等连续性资产，以及首帧/必要的尾帧约束。
3. 有台词的镜头仍使用独立的配音和口型层；I2V 模型的图像一致性不构成口型准确性证明。
4. 对每个模型分别跑固定的样片集：单人情绪、双人对话、转身、拿放道具、走动、近景口型。通过时序、身份、表演、美术和人工复核后，才允许批量生产。

生产就绪检查会为高复杂度镜头生成可执行的原子镜头方案。双人或多人对白按关系建立镜头、说话者近景和听者反应近景拆分，每个子镜头同时声明所需的身份、表演或多人能力。工作台可先查看方案，再调用 `POST /api/projects/{project_id}/scenes/{scene_number}/decompose` 应用。应用操作会重排后续镜头编号、同步项目脚本，并使受影响镜头的旧图片、音频、字幕和视频失效，之后必须重新冻结连续性资产并生成媒体。

旧项目缺少 `shot_role` 或 `required_engine_capabilities` 时，生产准备会阻断并提供“批量编译镜头合同”动作。`POST /api/projects/{project_id}/compile-shot-contracts` 使用确定性规则补齐缺失字段，不调用 LLM、不覆盖人工指定合同；发生执行合同变化的镜头会清除旧视频，已有图片和音频保持不变。

## 选择依据

Wan2.2 官方仓库提供本地 720P/24fps 图生视频路径，并说明 TI2V-5B 可使用 24GB 显存级别显卡运行；HunyuanVideo-I2V 提供图生视频和稳定模式，但部署与训练资源需求更高。模型选择必须以目标机器的真实样片数据为准，不能以文档描述代替验收。
