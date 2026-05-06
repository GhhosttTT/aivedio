"""
剧本生成服务（ScriptGenerator）

负责调用 LLM 服务生成剧本，解析 LLM 输出，
管理角色和分镜信息，支持分镜重新生成
"""

import re
import time
from typing import Optional, Dict, List, Tuple
from sqlalchemy.orm import Session

from src.services.llm_service import LLMService, get_llm_service
from src.database.models import Project, Character, Scene, ProjectStatus
from src.services.project_manager import ProjectManager
from src.utils.logger import logger
import asyncio


def _send_websocket_message(project_id: int, message: dict):
    """
    发送 WebSocket 消息（兼容同步和异步环境）
    
    Args:
        project_id: 项目 ID
        message: 消息内容
    """
    try:
        from src.api.websocket import manager
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环正在运行，创建任务
            asyncio.create_task(manager.broadcast(project_id, message))
            logger.debug(f"WebSocket 消息已调度: {message.get('type')}")
        else:
            # 否则直接运行
            loop.run_until_complete(manager.broadcast(project_id, message))
            logger.debug(f"WebSocket 消息已发送: {message.get('type')}")
    except Exception as e:
        logger.warning(f"WebSocket 推送失败: {e}, 消息类型: {message.get('type')}")


class ScriptParseError(Exception):
    """剧本解析错误"""
    pass


class ScriptGenerator:
    """剧本生成服务"""
    
    def __init__(
        self,
        db: Session,
        llm_service: Optional[LLMService] = None
    ):
        """
        初始化剧本生成服务
        
        Args:
            db: 数据库会话
            llm_service: LLM 服务实例（可选，默认使用全局实例）
        """
        self.db = db
        self.llm_service = llm_service or get_llm_service()
        self.project_manager = ProjectManager(db)
    
    def generate_script(
        self,
        project_id: int,
        theme: Optional[str] = None,
        outline: Optional[str] = None,
        num_scenes: int = 10,
        num_characters: int = 2,
        style: str = "现代都市",
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict:
        """
        生成剧本
        
        Args:
            project_id: 项目ID
            theme: 主题关键词（可选）
            outline: 故事大纲（可选）
            num_scenes: 分镜数量（默认 10）
            num_characters: 角色数量（默认 2）
            style: 风格偏好（默认"现代都市"）
            temperature: LLM 温度参数（默认 0.7）
            max_tokens: 最大生成 token 数（默认 4096）
            
        Returns:
            包含剧本信息的字典
            
        Raises:
            ValueError: 如果 theme 和 outline 都为空，或项目不存在
            ScriptParseError: 如果剧本解析失败
            RuntimeError: 如果 LLM 生成失败
        """
        # 验证输入
        if not theme and not outline:
            raise ValueError("主题和大纲至少需要提供一个")
        
        # 获取项目
        project = self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        logger.info(f"开始为项目 {project_id} 生成剧本")
        logger.info(
            f"参数: theme={theme}, outline={outline}, "
            f"num_scenes={num_scenes}, num_characters={num_characters}, style={style}"
        )
        
        # 通过 WebSocket 推送开始消息
        _send_websocket_message(project_id, {
            "type": "script_generation_start",
            "project_id": project_id,
            "message": "开始生成剧本..."
        })
        
        try:
            # 构建 Prompt
            prompt = self.llm_service.generate_script_prompt(
                theme=theme,
                outline=outline,
                num_scenes=num_scenes,
                num_characters=num_characters,
                style=style
            )
            
            # 推送 Prompt 构建完成
            _send_websocket_message(project_id, {
                "type": "progress",
                "project_id": project_id,
                "current_step": "构建提示词",
                "progress": 0.1,
                "message": "正在构建提示词..."
            })
            
            # 调用 LLM 生成剧本（使用流式输出）
            logger.info("调用 LLM 生成剧本...")
            
            # 用于累积生成的文本
            generated_chunks = []
            last_update_time = time.time()
            update_interval = 2.0  # 每2秒更新一次进度
            
            def stream_callback(chunk: str):
                """流式输出回调函数"""
                nonlocal last_update_time
                generated_chunks.append(chunk)
                
                current_time = time.time()
                # 每隔一定时间推送进度
                if current_time - last_update_time >= update_interval:
                    total_length = len(''.join(generated_chunks))
                    logger.info(f"LLM 生成进度: {total_length} 字符")
                    _send_websocket_message(project_id, {
                        "type": "progress",
                        "project_id": project_id,
                        "current_step": "LLM 生成中",
                        "progress": 0.2 + (min(total_length / max_tokens, 0.4)),  # 从 0.2 到 0.6
                        "message": f"AI 正在创作剧本...已生成 {total_length} 字符"
                    })
                    last_update_time = current_time
            
            script_text = self.llm_service.generate(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                callback=stream_callback
            )
            
            logger.info(f"LLM 生成完成，输出长度: {len(script_text)} 字符")
            logger.debug(f"生成的剧本: {script_text[:200]}...")
            
            # 推送 LLM 生成完成
            _send_websocket_message(project_id, {
                "type": "progress",
                "project_id": project_id,
                "current_step": "解析剧本",
                "progress": 0.6,
                "message": f"AI 创作完成（{len(script_text)} 字符），正在解析..."
            })
            
            # 解析剧本
            logger.info("开始解析剧本...")
            parsed_script = self.parse_script(script_text)
            
            # 推送解析完成
            _send_websocket_message(project_id, {
                "type": "progress",
                "project_id": project_id,
                "current_step": "保存数据",
                "progress": 0.8,
                "message": f"解析成功：{len(parsed_script.get('characters', []))} 个角色，{len(parsed_script.get('scenes', []))} 个分镜"
            })
            
            # 保存到数据库
            logger.info("保存剧本到数据库...")
            self._save_script_to_db(project, parsed_script)
            
            # 更新项目状态
            self.project_manager.update_project(
                project_id=project_id,
                status=ProjectStatus.SCRIPT_GENERATED,
                script=parsed_script,
                total_scenes=len(parsed_script.get("scenes", []))
            )
            
            # 推送完成消息
            _send_websocket_message(project_id, {
                "type": "script_generation_complete",
                "project_id": project_id,
                "progress": 1.0,
                "current_step": "完成",
                "message": f"剧本生成成功！共 {len(parsed_script.get('scenes', []))} 个分镜",
                "characters_count": len(parsed_script.get('characters', [])),
                "scenes_count": len(parsed_script.get('scenes', []))
            })
            
            logger.info(f"剧本生成完成，共 {len(parsed_script.get('scenes', []))} 个分镜")
            
            return parsed_script
            
        except ScriptParseError as e:
            logger.error(f"剧本解析失败: {e}")
            # 推送错误消息
            _send_websocket_message(project_id, {
                "type": "script_generation_error",
                "project_id": project_id,
                "error": str(e),
                "message": f"剧本解析失败: {e}"
            })
            raise
        except Exception as e:
            logger.error(f"剧本生成失败: {e}")
            # 推送错误消息
            _send_websocket_message(project_id, {
                "type": "script_generation_error",
                "project_id": project_id,
                "error": str(e),
                "message": f"剧本生成失败: {e}"
            })
            raise RuntimeError(f"剧本生成失败: {e}") from e
    
    def parse_script(self, script_text: str) -> Dict:
        """
        解析 LLM 生成的剧本文本
        
        Args:
            script_text: LLM 生成的剧本文本
            
        Returns:
            解析后的剧本字典，包含以下字段：
            - script: 完整剧本文本
            - characters: 角色列表
            - scenes: 分镜列表
            
        Raises:
            ScriptParseError: 如果解析失败
        """
        if not script_text or len(script_text.strip()) == 0:
            raise ScriptParseError("剧本文本为空")
        
        try:
            # 提取剧本部分
            script_match = re.search(
                r'【剧本】\s*(.*?)\s*【角色】',
                script_text,
                re.DOTALL
            )
            script_content = script_match.group(1).strip() if script_match else ""
            
            # 提取角色部分
            characters = self._parse_characters(script_text)
            
            # 提取分镜部分
            scenes = self._parse_scenes(script_text)
            
            # 验证解析结果
            if not characters:
                logger.warning("未解析到角色信息")
            
            if not scenes:
                raise ScriptParseError("未解析到分镜信息")
            
            logger.info(f"解析成功: {len(characters)} 个角色, {len(scenes)} 个分镜")
            
            return {
                "script": script_content,
                "characters": characters,
                "scenes": scenes
            }
            
        except ScriptParseError:
            raise
        except Exception as e:
            logger.error(f"剧本解析异常: {e}")
            raise ScriptParseError(f"剧本解析失败: {e}") from e
    
    def _parse_characters(self, script_text: str) -> List[Dict]:
        """
        解析角色信息
        
        Args:
            script_text: 剧本文本
            
        Returns:
            角色列表
        """
        characters = []
        
        try:
            # 提取角色部分
            characters_match = re.search(
                r'【角色】\s*(.*?)\s*【分镜】',
                script_text,
                re.DOTALL
            )
            
            if not characters_match:
                return characters
            
            characters_text = characters_match.group(1).strip()
            
            # 解析每个角色
            # 格式: - 角色名：描述
            character_lines = re.findall(
                r'-\s*([^：:]+)[：:]\s*(.+)',
                characters_text
            )
            
            for name, description in character_lines:
                characters.append({
                    "name": name.strip(),
                    "description": description.strip()
                })
            
            logger.debug(f"解析到 {len(characters)} 个角色")
            
        except Exception as e:
            logger.warning(f"角色解析失败: {e}")
        
        return characters
    
    def _parse_scenes(self, script_text: str) -> List[Dict]:
        """
        解析分镜信息
        
        Args:
            script_text: 剧本文本
            
        Returns:
            分镜列表
        """
        scenes = []
        
        try:
            # 提取分镜部分
            scenes_match = re.search(
                r'【分镜】\s*(.*)',
                script_text,
                re.DOTALL
            )
            
            if not scenes_match:
                raise ScriptParseError("未找到分镜部分")
            
            scenes_text = scenes_match.group(1).strip()
            
            # 分割每个分镜
            # 格式: 分镜N: ...
            scene_blocks = re.split(r'分镜\s*(\d+)\s*[：:]', scenes_text)
            
            # scene_blocks[0] 是空字符串或前导文本，跳过
            # scene_blocks[1], scene_blocks[2] 是第一个分镜的编号和内容
            # scene_blocks[3], scene_blocks[4] 是第二个分镜的编号和内容
            # ...
            
            for i in range(1, len(scene_blocks), 2):
                if i + 1 >= len(scene_blocks):
                    break
                
                scene_number = int(scene_blocks[i])
                scene_content = scene_blocks[i + 1].strip()
                
                # 解析分镜字段
                scene_data = self._parse_scene_fields(scene_content)
                scene_data["scene_number"] = scene_number
                
                scenes.append(scene_data)
            
            logger.debug(f"解析到 {len(scenes)} 个分镜")
            
        except ScriptParseError:
            raise
        except Exception as e:
            logger.error(f"分镜解析失败: {e}")
            raise ScriptParseError(f"分镜解析失败: {e}") from e
        
        return scenes
    
    def _parse_scene_fields(self, scene_content: str) -> Dict:
        """
        解析单个分镜的字段
        
        Args:
            scene_content: 分镜内容文本
            
        Returns:
            分镜字段字典
        """
        scene_data = {}
        
        # 解析环境描述
        environment_match = re.search(
            r'-\s*环境描述[：:]\s*(.+)',
            scene_content
        )
        if environment_match:
            scene_data["environment"] = environment_match.group(1).strip()
        
        # 解析人物描述
        character_desc_match = re.search(
            r'-\s*人物描述[：:]\s*(.+)',
            scene_content
        )
        if character_desc_match:
            scene_data["character_description"] = character_desc_match.group(1).strip()
        
        # 解析镜头描述
        camera_match = re.search(
            r'-\s*镜头描述[：:]\s*(.+)',
            scene_content
        )
        if camera_match:
            scene_data["camera"] = camera_match.group(1).strip()
        
        # 解析光线描述
        lighting_match = re.search(
            r'-\s*光线描述[：:]\s*(.+)',
            scene_content
        )
        if lighting_match:
            scene_data["lighting"] = lighting_match.group(1).strip()
        
        # 解析氛围描述
        atmosphere_match = re.search(
            r'-\s*氛围描述[：:]\s*(.+)',
            scene_content
        )
        if atmosphere_match:
            scene_data["atmosphere"] = atmosphere_match.group(1).strip()
        
        # 解析出现角色
        characters_match = re.search(
            r'-\s*出现角色[：:]\s*\[(.+?)\]',
            scene_content
        )
        if characters_match:
            characters_str = characters_match.group(1).strip()
            scene_data["characters"] = [
                c.strip() for c in characters_str.split(',')
            ]
        
        # 解析对话
        dialogue_match = re.search(
            r'-\s*对话[：:]\s*(.+)',
            scene_content
        )
        if dialogue_match:
            scene_data["dialogue"] = dialogue_match.group(1).strip()
        
        # 解析说话人
        speaker_match = re.search(
            r'-\s*说话人[：:]\s*(.+)',
            scene_content
        )
        if speaker_match:
            scene_data["speaker"] = speaker_match.group(1).strip()
        
        # 解析情感
        emotion_match = re.search(
            r'-\s*情感[：:]\s*(.+)',
            scene_content
        )
        if emotion_match:
            scene_data["emotion"] = emotion_match.group(1).strip()
        
        # 生成图像提示词（基于所有详细描述）
        # 首先收集所有中文描述
        chinese_parts = []
        
        if scene_data.get("environment"):
            chinese_parts.append(scene_data["environment"])
        
        if scene_data.get("character_description"):
            chinese_parts.append(scene_data["character_description"])
        
        if scene_data.get("camera"):
            chinese_parts.append(scene_data["camera"])
        
        if scene_data.get("lighting"):
            chinese_parts.append(scene_data["lighting"])
        
        if scene_data.get("atmosphere"):
            chinese_parts.append(scene_data["atmosphere"])
        
        # 使用 LLM 将中文描述翻译为专业的英文摄影提示词
        if chinese_parts and self.llm_service:
            try:
                chinese_text = ", ".join(chinese_parts)
                
                translation_prompt = f"""You are a professional photography and digital art prompt engineer. Translate the following Chinese scene description into a detailed English Stable Diffusion image prompt for HIGH-QUALITY CINEMATIC PORTRAIT.

CRITICAL STYLE REQUIREMENTS:
1. Style: cinematic portrait photography, similar to high-end fashion photos or movie stills
2. Face: beautiful detailed face, delicate facial features, flawless skin, soft natural makeup, expressive eyes with catchlights, perfect symmetry
3. Hair: detailed hair strands, realistic hair texture, natural flow
4. Clothing: highly detailed clothing, intricate patterns, rich textures, elegant draping
5. Lighting: cinematic lighting, soft diffused light, warm golden tones, volumetric lighting, bokeh background, lens flare, rim light
6. Atmosphere: dreamy, ethereal, elegant, graceful, sophisticated, cinematic mood
7. Quality: ultra-detailed, 8k uhd, RAW photo, masterpiece, best quality, professional photography
8. Camera: shot on professional DSLR, 85mm f/1.4 lens, shallow depth of field, sharp focus on face
9. Color: rich colors, professional color grading, warm tones, cinematic color palette

MANDATORY QUALITY TAGS (must include at the beginning):
"masterpiece, best quality, ultra-detailed, 8k uhd, RAW photo, photorealistic, realistic, cinematic"

MANDATORY STYLE TAGS (must include):
"beautiful detailed face, delicate features, soft lighting, bokeh, professional photography, shot on 85mm f/1.4 lens, sharp focus, natural skin texture"

MANDATORY ENDING TAGS (must include at the end):
"highly detailed, professional color grading, cinematic lighting, elegant, graceful"

Output ONLY the prompt, no explanations.
AVOID: cartoon, anime, illustration, painting, drawing, sketch, flat colors, simple shading, low quality

Chinese description:
{chinese_text}

English prompt (cinematic portrait):"""
                
                english_prompt = self.llm_service.generate(
                    prompt=translation_prompt,
                    max_tokens=300,
                    temperature=0.3  # 低温度确保翻译准确
                )
                
                # 清理结果
                english_prompt = english_prompt.strip()
                if english_prompt.startswith('"') and english_prompt.endswith('"'):
                    english_prompt = english_prompt[1:-1]
                
                logger.info(f"提示词翻译成功: {chinese_text[:50]}... -> {english_prompt[:80]}...")
                scene_data["image_prompt"] = english_prompt
                
            except Exception as e:
                logger.warning(f"提示词翻译失败，使用中文: {e}")
                # 降级：直接使用中文 + 质量标签
                visual_parts = chinese_parts + [
                    "masterpiece, best quality, ultra-detailed",
                    "photorealistic, realistic",
                    "professional photography, cinematic lighting, 8k uhd"
                ]
                scene_data["image_prompt"] = ", ".join(visual_parts)
        else:
            # 如果没有 LLM，直接使用中文 + 质量标签
            visual_parts = chinese_parts + [
                "masterpiece, best quality, ultra-detailed",
                "photorealistic, realistic",
                "professional photography, cinematic lighting, 8k uhd"
            ]
            scene_data["image_prompt"] = ", ".join(visual_parts)
        
        # 保存完整的视觉描述（用于数据库）
        scene_data["description"] = scene_data.get("image_prompt", "")
        
        return scene_data
    
    def _save_script_to_db(self, project: Project, parsed_script: Dict):
        """
        保存剧本到数据库
        
        Args:
            project: 项目对象
            parsed_script: 解析后的剧本
        """
        try:
            # 保存角色
            characters_data = parsed_script.get("characters", [])
            for char_data in characters_data:
                character = Character(
                    project_id=project.id,
                    name=char_data.get("name"),
                    description=char_data.get("description")
                )
                self.db.add(character)
            
            # 保存分镜
            scenes_data = parsed_script.get("scenes", [])
            for scene_data in scenes_data:
                scene = Scene(
                    project_id=project.id,
                    scene_number=scene_data.get("scene_number"),
                    visual_description=scene_data.get("description", ""),
                    dialogue=scene_data.get("dialogue"),
                    character_name=scene_data.get("speaker"),
                    image_prompt=scene_data.get("image_prompt")
                )
                self.db.add(scene)
            
            self.db.commit()
            logger.info("剧本保存到数据库成功")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存剧本到数据库失败: {e}")
            raise
    
    def regenerate_scene(
        self,
        project_id: int,
        scene_number: int,
        new_description: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 512
    ) -> Dict:
        """
        重新生成指定分镜
        
        Args:
            project_id: 项目ID
            scene_number: 分镜序号
            new_description: 新的场景描述（可选）
            temperature: LLM 温度参数（默认 0.8，更高的随机性）
            max_tokens: 最大生成 token 数（默认 512）
            
        Returns:
            更新后的分镜信息
            
        Raises:
            ValueError: 如果项目或分镜不存在
            RuntimeError: 如果生成失败
        """
        # 获取项目
        project = self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        # 获取分镜
        scene = self.db.query(Scene).filter(
            Scene.project_id == project_id,
            Scene.scene_number == scene_number
        ).first()
        
        if not scene:
            raise ValueError(f"分镜不存在: scene_number={scene_number}")
        
        logger.info(f"开始重新生成分镜 {scene_number}")
        
        try:
            # 构建 Prompt
            prompt = self._build_regenerate_prompt(
                project=project,
                scene=scene,
                new_description=new_description
            )
            
            # 调用 LLM 生成新分镜
            logger.info("调用 LLM 重新生成分镜...")
            new_scene_text = self.llm_service.generate(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            logger.info(f"LLM 生成完成，输出长度: {len(new_scene_text)} 字符")
            
            # 解析新分镜
            new_scene_data = self._parse_scene_fields(new_scene_text)
            
            # 更新数据库
            if new_description:
                scene.visual_description = new_description
            if new_scene_data.get("dialogue"):
                scene.dialogue = new_scene_data.get("dialogue")
            if new_scene_data.get("speaker"):
                scene.character_name = new_scene_data.get("speaker")
            
            self.db.commit()
            
            logger.info(f"分镜 {scene_number} 重新生成完成")
            
            return {
                "scene_number": scene_number,
                "description": scene.visual_description,
                "dialogue": scene.dialogue,
                "speaker": scene.character_name
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"重新生成分镜失败: {e}")
            raise RuntimeError(f"重新生成分镜失败: {e}") from e
    
    def _build_regenerate_prompt(
        self,
        project: Project,
        scene: Scene,
        new_description: Optional[str]
    ) -> str:
        """
        构建重新生成分镜的 Prompt
        
        Args:
            project: 项目对象
            scene: 分镜对象
            new_description: 新的场景描述
            
        Returns:
            Prompt 文本
        """
        # 获取项目角色
        characters = self.db.query(Character).filter(
            Character.project_id == project.id
        ).all()
        
        character_names = [c.name for c in characters]
        
        # 构建 Prompt
        prompt = f"""请为以下短剧分镜重新生成对话和细节：

项目主题：{project.theme or '未指定'}
角色：{', '.join(character_names)}

分镜 {scene.scene_number}：
场景描述：{new_description or scene.visual_description}

请按照以下格式输出：

- 对话：xxx
- 说话人：角色名
- 情感：情感描述

要求：
1. 对话要自然流畅，符合角色性格
2. 场景描述要具体生动
3. 严格按照上述格式输出
"""
        
        return prompt
    
    def generate_visual_prompt(
        self,
        scene: Scene,
        style: str = "电影级画质",
        additional_tags: Optional[List[str]] = None
    ) -> Tuple[str, str]:
        """
        为分镜生成视觉提示词（用于图像生成）
        
        Args:
            scene: 分镜对象
            style: 风格标签（默认"电影级画质"）
            additional_tags: 额外的标签列表（可选）
            
        Returns:
            (正面提示词, 负面提示词) 元组
        """
        # 构建正面提示词
        positive_parts = [
            scene.visual_description,
            style,
            "高质量",
            "细节丰富",
            "专业摄影"
        ]
        
        if additional_tags:
            positive_parts.extend(additional_tags)
        
        positive_prompt = ", ".join(positive_parts)
        
        # 构建负面提示词
        negative_prompt = (
            "低质量, 模糊, 变形, 多余的手指, 多余的肢体, "
            "文字, 水印, 签名, 丑陋, 扭曲"
        )
        
        logger.debug(f"生成视觉提示词: {positive_prompt[:100]}...")
        
        return positive_prompt, negative_prompt



# ==================== 单例模式 ====================

_script_generator_instance: Optional['ScriptGenerator'] = None


def get_script_generator() -> 'ScriptGenerator':
    """获取 ScriptGenerator 单例实例"""
    global _script_generator_instance
    if _script_generator_instance is None:
        from src.database.session import get_db_session
        from src.services.llm_service import get_llm_service
        db_session = next(get_db_session())
        llm_service = get_llm_service()
        _script_generator_instance = ScriptGenerator(db_session, llm_service)
        logger.info("ScriptGenerator 实例已创建")
    return _script_generator_instance


def cleanup_script_generator():
    """清理 ScriptGenerator 单例实例"""
    global _script_generator_instance
    if _script_generator_instance is not None:
        _script_generator_instance = None
        logger.info("ScriptGenerator 实例已清理")
