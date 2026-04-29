"""
WebSocket 实时通信

提供实时任务进度和状态更新推送
"""

import asyncio
import json
from typing import Dict, Set
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class ConnectionManager:
    """
    WebSocket 连接管理器
    
    管理所有活跃的 WebSocket 连接，支持按项目 ID 分组
    """
    
    def __init__(self):
        """初始化连接管理器"""
        # 存储所有活跃连接：{project_id: {websocket1, websocket2, ...}}
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # 心跳任务：{websocket: task}
        self.heartbeat_tasks: Dict[WebSocket, asyncio.Task] = {}
        # 心跳间隔（秒）
        self.heartbeat_interval = 30
        # 心跳超时（秒）
        self.heartbeat_timeout = 60
    
    async def connect(self, websocket: WebSocket, project_id: int):
        """
        接受新的 WebSocket 连接
        
        Args:
            websocket: WebSocket 连接对象
            project_id: 项目 ID
        """
        await websocket.accept()
        
        # 添加到连接池
        if project_id not in self.active_connections:
            self.active_connections[project_id] = set()
        self.active_connections[project_id].add(websocket)
        
        # 启动心跳任务
        heartbeat_task = asyncio.create_task(self._heartbeat(websocket, project_id))
        self.heartbeat_tasks[websocket] = heartbeat_task
        
        logger.info(f"WebSocket 连接建立: project_id={project_id}, total_connections={len(self.active_connections[project_id])}")
        
        # 发送连接成功消息
        await self.send_personal_message(
            websocket,
            {
                "type": "connected",
                "project_id": project_id,
                "message": "连接成功",
                "timestamp": datetime.now().isoformat()
            }
        )
    
    def disconnect(self, websocket: WebSocket, project_id: int):
        """
        断开 WebSocket 连接
        
        Args:
            websocket: WebSocket 连接对象
            project_id: 项目 ID
        """
        # 取消心跳任务
        if websocket in self.heartbeat_tasks:
            self.heartbeat_tasks[websocket].cancel()
            del self.heartbeat_tasks[websocket]
        
        # 从连接池移除
        if project_id in self.active_connections:
            self.active_connections[project_id].discard(websocket)
            
            # 如果该项目没有连接了，删除项目键
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]
        
        logger.info(f"WebSocket 连接断开: project_id={project_id}")
    
    async def send_personal_message(self, websocket: WebSocket, message: dict):
        """
        发送消息给指定连接
        
        Args:
            websocket: WebSocket 连接对象
            message: 消息内容（字典）
        """
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"发送个人消息失败: {e}")
    
    async def broadcast(self, project_id: int, message: dict):
        """
        广播消息给指定项目的所有连接
        
        Args:
            project_id: 项目 ID
            message: 消息内容（字典）
        """
        if project_id not in self.active_connections:
            logger.debug(f"项目 {project_id} 没有活跃连接，跳过广播")
            return
        
        # 记录断开的连接
        disconnected = []
        
        # 广播给所有连接
        for websocket in self.active_connections[project_id]:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"广播消息失败: {e}")
                disconnected.append(websocket)
        
        # 清理断开的连接
        for websocket in disconnected:
            self.disconnect(websocket, project_id)
        
        logger.debug(f"广播消息到项目 {project_id}: {len(self.active_connections.get(project_id, []))} 个连接")
    
    async def _heartbeat(self, websocket: WebSocket, project_id: int):
        """
        心跳机制
        
        定期发送心跳消息，保持连接活跃
        
        Args:
            websocket: WebSocket 连接对象
            project_id: 项目 ID
        """
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                
                # 发送心跳消息
                await self.send_personal_message(
                    websocket,
                    {
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat()
                    }
                )
                
                logger.debug(f"发送心跳: project_id={project_id}")
        
        except asyncio.CancelledError:
            logger.debug(f"心跳任务取消: project_id={project_id}")
        except Exception as e:
            logger.error(f"心跳任务异常: {e}")
            self.disconnect(websocket, project_id)
    
    def get_connection_count(self, project_id: int = None) -> int:
        """
        获取连接数量
        
        Args:
            project_id: 项目 ID（可选，如果不提供则返回总连接数）
        
        Returns:
            连接数量
        """
        if project_id is not None:
            return len(self.active_connections.get(project_id, set()))
        else:
            return sum(len(connections) for connections in self.active_connections.values())


# 全局连接管理器实例
manager = ConnectionManager()


async def send_status_update(project_id: int, status: str, progress: float = None, current_step: str = None):
    """
    发送状态更新消息
    
    Args:
        project_id: 项目 ID
        status: 任务状态
        progress: 进度（0.0-1.0）
        current_step: 当前步骤描述
    """
    message = {
        "type": "status_update",
        "project_id": project_id,
        "status": status,
        "timestamp": datetime.now().isoformat()
    }
    
    if progress is not None:
        message["progress"] = progress
    
    if current_step is not None:
        message["current_step"] = current_step
    
    await manager.broadcast(project_id, message)


async def send_progress_update(project_id: int, progress: float, current_step: str):
    """
    发送进度更新消息
    
    Args:
        project_id: 项目 ID
        progress: 进度（0.0-1.0）
        current_step: 当前步骤描述
    """
    message = {
        "type": "progress_update",
        "project_id": project_id,
        "progress": progress,
        "current_step": current_step,
        "timestamp": datetime.now().isoformat()
    }
    
    await manager.broadcast(project_id, message)


async def send_completion_notification(project_id: int, result: dict = None):
    """
    发送完成通知
    
    Args:
        project_id: 项目 ID
        result: 结果数据（可选）
    """
    message = {
        "type": "completion",
        "project_id": project_id,
        "message": "任务完成",
        "timestamp": datetime.now().isoformat()
    }
    
    if result is not None:
        message["result"] = result
    
    await manager.broadcast(project_id, message)


async def send_error_notification(project_id: int, error: str):
    """
    发送错误通知
    
    Args:
        project_id: 项目 ID
        error: 错误信息
    """
    message = {
        "type": "error",
        "project_id": project_id,
        "error": error,
        "timestamp": datetime.now().isoformat()
    }
    
    await manager.broadcast(project_id, message)
