# RTX 3060 12GB 短剧生成：实现与验收

本轮基于 GitHub `d4dbc26` 梳理。目标设备由用户提供：RTX 3060，12GB 显存。
开发电脑只检测到 Intel UHD 630，没有连接目标 GPU 主机。代码测试、媒体处理测试和模型质量测试应分别记录，不能相互替代。

## 1. 已确认的生成问题

| 原路径的问题 | 本轮处理 |
| --- | --- |
| 剧本模板要求章节和大段描写，解析器依赖不同标题 | 模板统一为解析器支持的格式；保留中文原始画面描述 |
| 翻译提示词强制人像、完美皮肤、85mm，再经过增强器和优化器扩写 | 单次关键帧编译；保留空镜、景别和动画风格；限制描述长度，拒绝多时刻动作 |
| 配置 Juggernaut 后自动切回 SDXL 基础模型加 LCM LoRA；参数混用 | 保持选定工作流，关闭隐式提示词/参数优化 |
| IP-Adapter 模板实际使用 SD 1.5 | 增加 SDXL 参考图模板，要求参考图与文生图使用相同 checkpoint |
| 按 JSON 节点顺序猜测正负提示词节点 | 沿采样器的 conditioning 连接定位 |
| 将本机绝对路径直接交给 ComfyUI | 通过 `/upload/image` 上传并使用服务器返回的名称 |
| 把说话人当作画面人物；自动将第一张图保存为角色参考 | 优先使用剧本的出现角色；参考图需明确选择 |
| 模型失败时默认输出占位图、静帧和静音 | 默认关闭草稿兜底；草稿不允许通过生产审核 |
| instruct 模型用原始 completion 接口，缺少对话模板 | 使用 llama.cpp chat completion；检测输出截断和上下文不足 |

这些问题足以导致效果下降。修复后仍需评估模型自身的构图、人体、多人物交互能力。

## 2. 当前流程

```text
故事与短分镜生成
  -> 独立审核请求：因果、动机、连续性、可拍摄性
  -> 不合格时最多定向修订一次，再次审核
  -> 审核通过后保存剧本和稳定英文角色特征
  -> 生产前复核当前分镜（手动修改会使旧审核失效）
  -> 批量编译短提示词，保存缓存，再卸载本地语言模型
  -> 每个分镜串行生成多张关键帧候选，技术评分 + 本地 VLM 评分，择优晋级
  -> 卸载 ComfyUI 模型，串行生成多个图生视频候选
  -> 卸载 SVD，使用本地视觉语言模型抽帧评分：画面质量、身份漂移、动作连续性、闪烁变形
  -> 选择抽帧评分最高的视频候选晋级
  -> 所有镜头通过后才允许合成
```

一张关键帧优先包含一个人物、一个主要动作、一个地点和一种主光源。
对话可用正反打，递物可拆为道具特写与接收者反应，复杂动作应在剧本层分镜。
编译器发现必须跨多个时刻的动作时会要求重新拆镜头，不会直接截掉句子后声称已保留情节。
75 个英文单词是工程上的描述长度上限，并非 CLIP token 上限，也不保证模型理解了全部语义。
多人同框时，系统会把剧本中该镜头的所有可见角色身份锚点一起写入提示词，并要求保持角色彼此区分。
单人镜头仍优先使用该角色参考图；多人镜头暂时不把单个 FaceID 参考图强行套到整张图，避免一张脸污染所有人。
构图约束由代码强制拼接进最终提示词：单人镜头限制“唯一可见人物、脸无遮挡”，双人镜头固定“角色 A 在画面左侧、角色 B 在画面右侧”，多人镜头按左、中、右等位置分配。
复杂多人互动后续仍需要 OpenPose、Depth、区域提示或专用视频模型来稳定姿态和空间关系。

## 3. 3060 起步配置

先使用一套验证过的 SDXL checkpoint 跑通 6 个镜头，避免同时更换模型、LoRA、采样器和镜头设计。
当前默认 Juggernaut 面向写实画面。动画需要选择匹配风格的 SDXL checkpoint；流程支持保留动画提示词，默认模型不承诺适合所有画风。

```dotenv
GENERATION_PROVIDER=local_comfyui
COMFYUI_DEFAULT_WORKFLOW_TYPE=juggernaut
COMFYUI_REFERENCE_WORKFLOW_PATH=./configs/comfyui_workflow_ipadapter_sdxl.json
GENERATION_WIDTH=1344
GENERATION_HEIGHT=768
GENERATION_STEPS=28
GENERATION_CFG=6.0
GENERATION_IMAGE_CANDIDATES=3
GENERATION_IMAGE_REFINEMENT_PASSES=1
GENERATION_IMAGE_MIN_SCORE=4.0
GENERATION_REQUIRE_IMAGE_REVIEW=false
GENERATION_VIDEO_CANDIDATES=2
GENERATION_VIDEO_MIN_SCORE=4.0
GENERATION_REQUIRE_VIDEO_REVIEW=false
ENABLE_DRAFT_MEDIA_FALLBACK=false
CELERY_WORKER_CONCURRENCY=1
LLM_N_CTX=8192
LOCAL_REVIEW_BACKEND=llama_cpp
LOCAL_REVIEW_BASE_URL=http://127.0.0.1:8080/v1
LOCAL_REVIEW_MODEL=local-vlm
LOCAL_REVIEW_TIMEOUT=300
```

这是待实测的起步参数，不是 12GB 显存占用保证。当前 SVD 后端仍以横屏输入为主；竖屏视频和复杂运动需要单独验收。
文本模型可沿用已可运行的 GGUF。显存紧张时先降低文本模型 GPU 层数或使用较小量化模型，避免与图像模型同时驻留。
`llama-cpp-python` 已从过旧的固定版本调整为 `>=0.3.16,<0.4`，目标机器需安装与驱动匹配的 CUDA 构建，不能只确认 Python 包安装成功。

只启动一个消费 GPU 任务的 worker。Windows 使用：

```powershell
python -m celery -A src.tasks.celery_app worker --pool=solo --concurrency=1 --loglevel=info --queues=default,image,video,audio,localization
```

多 worker 或 API 中同时启动其他模型任务仍可能抢占显存；本轮没有实现跨主机的全局 GPU 调度器。专用 3060 环境应一次运行一个生产任务，并与源片译制错峰执行。

参考图需有可识别主体。FaceID 对插画和高度风格化人物可能失败，不能把失败当作保持身份成功。
可使用匹配模型的 `IPAdapterAdvanced` 工作流；当前图适配器支持简单 `KSampler + CLIPTextEncode` 图，不承诺任意 ComfyUI 导出图均可直接接入。
更改 checkpoint 时，文生图和参考图模板必须一起修改。

## 4. 用时间换图像质量

当前关键帧生成已经改为候选择优：

```text
角色定妆
  -> 多张正面参考图候选
  -> 技术评分 + llama.cpp VLM 评分
  -> 最佳图保存为角色参考图，候选和 reference_quality.json 保留

同一分镜提示词
  -> candidate_01 / candidate_02 / candidate_03 ...
  -> 每张记录 seed、steps、cfg、尺寸
  -> 基础技术评分：曝光、边缘清晰度、色彩丰富度、尺寸合法性
  -> 若本地 VLM 可用，再评分：剧情匹配、构图、美观、画面完整性、身份一致性
  -> 低分候选的问题证据写入下一轮提示词与负面提示词
  -> 分数最高且达到门槛的候选复制为正式 scene image
  -> 保存 .quality.json 和 .generation.json
```

`GENERATION_IMAGE_CANDIDATES` 是每轮候选数量。3060 12GB 建议从 3 开始；如果你愿意等，可调到 5 或 6。超过 8 目前会被代码限制，避免单镜头排队过久。
`GENERATION_IMAGE_REFINEMENT_PASSES` 是额外精修轮数。设为 1 表示最多生成两轮候选；第一轮已经有 VLM 高分图时会提前停止。
`GENERATION_IMAGE_MIN_SCORE` 是晋级门槛。建议先用 4.0，人工校准后再提高。
`GENERATION_REQUIRE_IMAGE_REVIEW=true` 时，本地 VLM 不可用会直接拦截图片，不会只靠技术指标放行。正式跑片建议打开；开发调试可以先保持 false。
`GENERATION_QUALITY_PROMPT_APPEND` 会追加到每张候选图的正向提示词，用来稳定构图、人体和主动作可读性。
`GENERATION_QUALITY_NEGATIVE_APPEND` 会追加到负向提示词，用来压制截断、脏光、畸形手脸、随机文字和水印。

当第一轮低于门槛时，系统会提取低分项证据和 major/critical 问题，例如“脸被裁掉”“手指断裂”“灯光脏”，并写入下一轮候选图的修正提示词。这一层能把等待时间转化成可解释的迭代，而不是只盲目换 seed。

这个机制提升的是命中率和可追溯性，仍依赖底层模型、checkpoint、LoRA、Control/IPAdapter 节点质量。低质模型生成 20 张也可能只能选出较差的一张；候选择优不能替代更强模型或人工定妆。

视频阶段同样支持候选择优。`GENERATION_VIDEO_CANDIDATES` 会让同一关键帧串行生成多个视频候选，并轻微扰动 SVD 的运动强度和噪声增强参数；每个候选都会保存独立的 `.review.json` 抽帧审核报告，最终视频旁边保存 `.quality.json` 候选排序。正式跑片建议打开 `GENERATION_REQUIRE_VIDEO_REVIEW=true`，避免 llama.cpp 视觉模型离线时把未审核视频当成高质量结果。

## 5. 审核与抽帧评分

情节审核：检查全部分镜编号，必须每个编号恰好出现一次。独立 critic 请求可使用同一本地文本模型，属于第二次审稿，不等同于独立模型的交叉验证。

关键帧审核：每个候选图保存独立评分。基础技术评分可以离线运行，本地 VLM 评分需要 `llama-server` 的 OpenAI 兼容接口可用。
评分报告位于正式图片同目录，后缀为 `.quality.json`。候选图保留为 `.candidate_01.png` 等，便于人工回看和调参。

画面评分：每镜头至少 3 帧，长镜头约每秒一帧；采样覆盖时长的 5% 至 95%。超过 59 秒的片段要求拆分，避免静默截断审核范围。
每批最多 3 个采样帧，可另附 1 张参考图。按剧情匹配、构图、可见瑕疵、身份一致性、时间连续性分别给 0 至 5 分，并写明证据。
时间连续性会检查同一人物的脸、发型、服装、体型和相对站位是否稳定，动作推进是否合理，是否出现闪烁、变形、突然多出或消失的人，以及无关镜头跳变。
目前门槛为平均分至少 4、各项至少 3、无 major/critical 问题。任一批失败，整个镜头不能通过。
文件损坏、模型离线、JSON 无效、漏审或重复帧号会记录 `error`，不会生成默认高分。

报告保存于 `storage/projects/<项目ID>/reviews/`：

- `story_attempt_0.json`、`story_attempt_1.json`：情节审核与修订轨迹。
- `story.json`：最新生成阶段审核。
- `production_story.json`：当前数据库分镜的生产前审核。
- `scene_<ID>.json`：采样时间、图片路径、文件哈希、分项评分和问题。
- `generation.json`：整个项目的画面审核结果。

`GET /api/projects/<ID>/generation-review` 可读取本人项目的报告。当前前端还没有独立的评分工作台。
合成前会重新核对剧情与媒体哈希，改动后的素材需要重新审核。
现有数据库状态没有新增 `needs_review` 枚举：审核未通过的任务状态为失败，原因及报告中明确记录需要复核。

这些分数属于视觉语言模型判断，尚未与人工标注校准。时间连续性审核会拦截采样帧中可见的身份漂移、闪烁和帧间运动异常；抽帧仍可能漏掉两帧之间的瞬时问题，不能据此宣称电影级质量或全面时序审核完成。
当前评分对象是分镜视频，合成后的字幕、音画同步和总片节奏还需成片验收。

## 6. 可直接运行的验证

先安装并启动 ComfyUI、本地文本模型、llama.cpp 视觉模型，确保 FFmpeg 与 ffprobe 可执行。
视觉审核服务使用 llama.cpp 的 OpenAI 兼容 `/v1/chat/completions` 接口。示例：

```powershell
llama-server -m .\models\vlm\model.gguf --mmproj .\models\vlm\mmproj.gguf --host 127.0.0.1 --port 8080 -c 8192 -ngl 99
```

也可以使用支持 `-hf` 自动加载多模态投影的 GGUF 仓库。关键是模型必须支持图像输入；普通文本 GGUF 不能做画面审核。
安装模型和节点后执行以下命令；预检失败会返回非零退出码并保存具体原因。

```powershell
python -m scripts.validate_local_generation preflight
python -m scripts.validate_local_generation render-images
python -m scripts.validate_local_generation review-video --video "path/to/scene.mp4" --description "女孩在办公室门口拿着红色信封"
```

可通过 `--base-url http://GPU主机地址:8188` 连接同一局域网的 ComfyUI。
固定用例为 `examples/local_generation_cases.json`；可用 `--cases` 指向自己的镜头集。
输出默认保存于 `storage/validation`。`render-images` 没有占位回退，成功也只标记为待人工检查，不能等同于质量达标。
命令行单独执行视觉审核前，应先结束其他 GPU 作业并卸载其模型。

## 7. 下一步验收顺序

1. 在真实 3060 上运行预检，记录驱动、模型完整名称、节点版本、显存峰值和每镜头耗时。
2. 固定 checkpoint、分辨率、种子，对比旧提示词与新提示词。至少覆盖空镜、单人中景、反应特写、道具特写、正反打和目标动画风格。
3. 人工选择角色定妆图，连续测试同一角色至少 6 镜头，检查脸、发型、服装、道具和位置连续性。
4. 收集至少 30 个好坏样本，人工评分后校准关键帧 VLM 门槛，统计误放行和误拦截。先做到可解释、可复核，再提高候选数和精修轮数。
5. 跑一条真实配音的 20 至 30 秒短剧，检查每个镜头时长与对白匹配、字幕不抢画面、画风统一、抽帧证据完整。
6. 再扩展复杂互动、局部重绘、姿态/构图控制、竖屏图生视频和更长剧情。明确区分步骤问题、模型上限和显存约束。

满足上述实图和成片验收前，项目仍处于待 GPU 联调阶段。

## 8. 实现依据

- [ComfyUI 本地接口](https://docs.comfy.org/development/comfyui-server/comms_routes)：参考图上传、节点信息、队列及模型卸载。
- [llama-cpp-python 对话调用](https://llama-cpp-python.readthedocs.io/en/latest/#chat-completion)：使用 GGUF 的对话模板。
- [llama.cpp 多模态文档](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/docs/multimodal.md)：`llama-server` 支持图片输入和 OpenAI-compatible `/chat/completions`。
- [llama-cpp-python OpenAI 兼容服务](https://llama-cpp-python.readthedocs.io/en/latest/)：可作为本地 OpenAI API 替代，并提供 Vision API 支持。
