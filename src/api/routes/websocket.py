"""
WebSocket 路由

提供 WebSocket 端点用于实时通信
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from src.api.auth import decode_access_token
from src.database.models import Project, User
from src.database.session import get_db_session
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
    token = websocket.query_params.get("token") or websocket.query_params.get("access_token")
    payload = decode_access_token(token) if token else None
    user_id: int | None = None
    if payload and payload.get("token_type") == "access":
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            user_id = None

    if user_id is None:
        await websocket.close(code=1008, reason="Authentication required")
        return

    db_generator = get_db_session()
    db = next(db_generator)
    try:
        project = (
            db.query(Project)
            .join(User, Project.user_id == User.id)
            .filter(Project.id == project_id, Project.user_id == user_id, User.is_active == 1)
            .first()
        )
    finally:
        db.close()

    if project is None:
        await websocket.close(code=1008, reason="Project access denied")
        return

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
