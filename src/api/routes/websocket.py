"""
WebSocket 路由

提供 WebSocket 端点用于实时通信
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from src.api.websocket import manager


router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: int):
    """
    WebSocket 端点
    
    Args:
        websocket: WebSocket 连接对象
        project_id: 项目 ID
    """
    # 建立连接
    await manager.connect(websocket, project_id)
    
    try:
        # 保持连接，接收客户端消息
        while True:
            # 接收消息（主要用于心跳响应）
            data = await websocket.receive_text()
            logger.debug(f"收到客户端消息: project_id={project_id}, data={data}")
            
            # 可以在这里处理客户端发送的消息
            # 例如：心跳响应、订阅特定事件等
    
    except WebSocketDisconnect:
        logger.info(f"客户端主动断开连接: project_id={project_id}")
        manager.disconnect(websocket, project_id)
    
    except Exception as e:
        logger.error(f"WebSocket 连接异常: project_id={project_id}, error={e}")
        manager.disconnect(websocket, project_id)
