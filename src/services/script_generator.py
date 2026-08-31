"""
剧本生成服务（ScriptGenerator）

负责调用 LLM 服务生成剧本，解析 LLM 输出，
管理角色和分镜信息，支持分镜重新生成
"""

import re
import time
import json
from typing import Optional, Dict, List, Tuple
from sqlalchemy.orm import Session

from src.services.llm_service import LLMService, get_llm_service
from src.database.models import Project, Character, Scene, ProjectStatus
from src.services.project_manager import ProjectManager
from src.utils.logger import logger
from src.services.generation_review import GenerationReviewService, TextReviewer, require_passed
from src.utils.storage import storage_manager
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
        num_chapters: int = 3,
        temperature: float = 0.7,
        max_tokens: int = 8192
    ) -> Dict:
        """
        生成剧本（增强版，支持章节结构）
        
        Args:
            project_id: 项目ID
            theme: 主题关键词（可选）
            outline: 故事大纲（可选）
            num_scenes: 分镜数量（默认 10）
            num_characters: 角色数量（默认 2）
            style: 风格偏好（默认"现代都市"）
            num_chapters: 章节数量（默认 3，新增）
            temperature: LLM 温度参数（默认 0.7）
            max_tokens: 最大生成 token 数（默认 8192，增加以支持更详细的内容）
            
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
        if isinstance(self.llm_service, LLMService) and not self.llm_service.is_loaded:
            self.llm_service = get_llm_service()
        
        # 获取项目
        project = self.project_manager.get_project(project_id)
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        logger.info(f"开始为项目 {project_id} 生成剧本（增强版）")
        logger.info(
            f"参数: theme={theme}, outline={outline}, "
            f"num_scenes={num_scenes}, num_characters={num_characters}, "
            f"style={style}, num_chapters={num_chapters}"
        )
        
        # 通过 WebSocket 推送开始消息
        _send_websocket_message(project_id, {
            "type": "script_generation_start",
            "project_id": project_id,
            "message": "开始生成剧本..."
        })
        
        try:
            # 导入增强版 Prompt 生成函数
            from src.services.enhanced_script_prompt import generate_enhanced_script_prompt
            
            # 构建增强版 Prompt
            prompt = generate_enhanced_script_prompt(
                theme=theme,
                outline=outline,
                num_scenes=num_scenes,
                num_characters=num_characters,
                style=style,
                num_chapters=num_chapters
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
            if len(parsed_script["scenes"]) != num_scenes:
                raise ScriptParseError(f"期望 {num_scenes} 个分镜，实际 {len(parsed_script['scenes'])} 个")
            review_path = storage_manager.get_project_path(project_id) / "reviews" / "story.json"
            reviewer = GenerationReviewService(TextReviewer(self.llm_service))
            for attempt in range(2):
                review = reviewer.review_story(parsed_script, review_path.with_name(f"story_attempt_{attempt}.json"))
                from src.services.generation_review import write_report
                write_report(review_path, review)
                if review["status"] != "needs_review" or attempt == 1:
                    break
                correction = (
                    prompt + "\n请根据审核只修复存在问题的情节和镜头，保留主题、角色及总分镜数。"
                    "输出完整的修订剧本，保持原格式。\n原剧本：\n" + script_text
                    + "\n审核意见：\n" + json.dumps(review["review"], ensure_ascii=False)
                )
                script_text = self.llm_service.generate(prompt=correction, max_tokens=max_tokens, temperature=0.3)
                parsed_script = self.parse_script(script_text)
                if len(parsed_script["scenes"]) != num_scenes:
                    raise ScriptParseError("修订剧本分镜数量不符，需重新规划")
            require_passed(review)
            parsed_script["story_review"] = {"status": review["status"], "path": str(review_path), "input_hash": review["input_hash"]}
            
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
        finally:
            from src.services.llm_service import cleanup_llm_service
            cleanup_llm_service()
    
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
                r'【(?:剧本|故事大纲)】\s*(.*?)\s*【角色】',
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
        # Parse fields only. Prompt compilation happens once before rendering.
        labels = {
            "场景描述": "description", "环境描述": "environment",
            "人物描述": "character_description", "镜头描述": "camera",
            "光线描述": "lighting", "氛围描述": "atmosphere",
            "故事节点": "story_beat", "对话": "dialogue",
            "说话人": "speaker", "情感": "emotion", "图像提示词": "image_prompt",
        }
        scene_data = {}
        for label, key in labels.items():
            match = re.search(r"-\s*" + label + r"[：:]\s*([^\n\r]+)", scene_content)
            if match:
                scene_data[key] = match.group(1).strip()
        match = re.search(r"-\s*出现角色[：:]\s*\[([^\]]*)\]", scene_content)
        if match:
            scene_data["characters"] = [
                name.strip() for name in re.split(r"[,，、]", match.group(1))
                if name.strip() and name.strip() != "无"
            ]
        for key in ("dialogue", "speaker"):
            if scene_data.get(key) in {"无", "无对白", "None", "none"}:
                scene_data[key] = None
        if not scene_data.get("description"):
            scene_data["description"] = "，".join(
                scene_data[key] for key in (
                    "environment", "character_description", "camera", "lighting", "atmosphere"
                ) if scene_data.get(key)
            )
        return scene_data
    
    def _save_script_to_db(self, project: Project, parsed_script: Dict):
        """
        保存剧本到数据库
        
        Args:
            project: 项目对象
            parsed_script: 解析后的剧本
        """
        try:
            # 保存角色并自动生成外貌特征
            characters_data = parsed_script.get("characters", [])
            for char_data in characters_data:
                character = self.db.query(Character).filter(
                    Character.project_id == project.id, Character.name == char_data.get("name")
                ).first()
                if character is None:
                    character = Character(project_id=project.id, name=char_data.get("name"))
                    self.db.add(character)
                if not character.appearance:
                    character.appearance = self._generate_character_appearance(
                        char_data.get("name"), char_data.get("description")
                    )
                character.description = char_data.get("description")
            # A newly approved script replaces the old scene list in this transaction.
            self.db.query(Scene).filter(Scene.project_id == project.id).delete(synchronize_session="fetch")
            
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
    
    def _generate_character_appearance(self, character_name: str, character_description: str) -> str:
        """
        使用 LLM 为角色生成独特的外貌特征
        
        Args:
            character_name: 角色名称
            character_description: 角色描述
            
        Returns:
            外貌特征描述
        """
        try:
            prompt = f"""Translate the character's known visual identity into English.
Return only a concise phrase of at most 25 words: age, gender, hair, identifying clothing.
Preserve supplied features. Do not invent elaborate accessories or generic beauty tags.
Name: {character_name}
Description: {character_description}
English identity anchor:"""
            
            appearance = self.llm_service.generate(
                prompt=prompt,
                max_tokens=150,
                temperature=0.2
            )
            
            # 清理结果
            appearance = appearance.strip()
            if appearance.startswith('"') and appearance.endswith('"'):
                appearance = appearance[1:-1]
            from src.services.shot_prompt_service import ShotPromptService
            appearance = ShotPromptService.validate_prompt(appearance)
            if len(appearance.split()) > 25:
                raise ValueError("Identity anchor exceeds 25 words")
            
            logger.info(f"角色 '{character_name}' 外貌特征生成成功: {appearance}")
            return appearance
            
        except Exception as e:
            raise ValueError(f"角色 {character_name} 的外貌锚点生成失败: {e}") from e
    
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
            scene.visual_description = new_description or new_scene_data.get("description") or scene.visual_description
            scene.image_prompt = scene.image_path = scene.video_path = None
            scene.audio_path = scene.subtitle_path = None
            project.final_video_path = None
            project.status = ProjectStatus.SCRIPT_GENERATED
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
        finally:
            from src.services.llm_service import cleanup_llm_service
            cleanup_llm_service()
    
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
