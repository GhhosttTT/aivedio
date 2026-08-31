"""Parser-compatible shooting script for local keyframe generation."""

from typing import Optional


def generate_enhanced_script_prompt(
    theme: Optional[str] = None,
    outline: Optional[str] = None,
    num_scenes: int = 10,
    num_characters: int = 2,
    style: str = "现代都市",
    num_chapters: int = 3,
) -> str:
    if not theme and not outline:
        raise ValueError("主题和大纲至少需要提供一个")
    if min(num_scenes, num_characters, num_chapters) < 1:
        raise ValueError("分镜、角色、章节数量必须大于零")
    return f"""你是短剧编剧和分镜导演。为本地图像模型设计可拍摄、连贯的短剧。
主题：{theme or '未指定'}
故事大纲：{outline or '未指定'}
风格：{style}
总分镜：{num_scenes}，角色：{num_characters}，叙事阶段：{num_chapters}。

先安排冲突和转折，再把故事节点拆成可单独出图的镜头。
一个分镜只表现一个时间点、一个主要动作、一个视觉焦点。人物优先单人。
对话采用正反打；递物拆成物品特写和接收者反应；进入房间再坐下拆成两个分镜。
保持总分镜数为 {num_scenes}，通过精简故事节点给动作拆分留出空间。
环境只写地点与必要道具。服装、发型、道具和人物位置保持连续。
空镜允许没有人物。旁白可以在画外，出现角色只填真正可见的人物。
用镜头表达情节，不把心理活动、对白、运镜过程塞入静态画面描述。
尊重指定风格，动画、插画风格可以使用。不要统一改成真人写真。
不要堆叠画质标签，不要求每段凑字数。每个字段写在同一行。

严格输出以下格式，保留【剧本】【角色】【分镜】三个标题：
【剧本】
100字以内的故事摘要，包含冲突和结局。
【角色】
- 实际姓名：年龄、性别、发型、一件标识服装；性格和故事定位。
【分镜】
分镜1：
- 故事节点：本镜头推进什么情节，20字以内
- 环境描述：一个地点，必要道具，30字以内
- 人物描述：可见人物和一个动作或静态表情，30字以内
- 镜头描述：一个景别、一个角度、视觉焦点，20字以内
- 光线描述：一个主要光源，15字以内
- 氛围描述：延续指定风格，15字以内
- 出现角色：[实际姓名]（空镜填 []）
- 对话：一句简短对白，无对白填 无
- 说话人：实际姓名，无对白填 无
- 情感：一个情绪
继续分镜2至分镜{num_scenes}，使用相同字段和连续编号。不要省略分镜。
"""
