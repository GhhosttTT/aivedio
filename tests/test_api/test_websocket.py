"""
WebSocket 测试

测试 WebSocket 实时通信功能
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from src.api.websocket import (
    ConnectionManager,
    manager,
    send_status_update,
    send_progress_update,
    send_completion_notification,
    send_error_notification
)


@pytest.fixture
def connection_manager():
    """创建连接管理器实例"""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """创建 Mock WebSocket 对象"""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_connection_manager_connect(connection_manager, mock_websocket):
    """测试连接建立"""
    project_id = 1
    
    await connection_manager.connect(mock_websocket, project_id)
    
    # 验证连接已接受
    mock_websocket.accept.assert_called_once()
    
    # 验证连接已添加到连接池
    assert project_id in connection_manager.active_connections
    assert mock_websocket in connection_manager.active_connections[project_id]
    
    # 验证发送了连接成功消息
    mock_websocket.send_json.assert_called()
    call_args = mock_websocket.send_json.call_args[0][0]
    assert call_args["type"] == "connected"
    assert call_args["project_id"] == project_id
    
    # 清理心跳任务
    if mock_websocket in connection_manager.heartbeat_tasks:
        connection_manager.heartbeat_tasks[mock_websocket].cancel()


@pytest.mark.asyncio
async def test_connection_manager_disconnect(connection_manager, mock_websocket):
    """测试连接断开"""
    project_id = 1
    
    # 先建立连接
    await connection_manager.connect(mock_websocket, project_id)
    
    # 断开连接
    connection_manager.disconnect(mock_websocket, project_id)
    
    # 验证连接已从连接池移除
    assert project_id not in connection_manager.active_connections or \
           mock_websocket not in connection_manager.active_connections.get(project_id, set())
    
    # 验证心跳任务已取消
    assert mock_websocket not in connection_manager.heartbeat_tasks


@pytest.mark.asyncio
async def test_connection_manager_send_personal_message(connection_manager, mock_websocket):
    """测试发送个人消息"""
    message = {"type": "test", "data": "hello"}
    
    await connection_manager.send_personal_message(mock_websocket, message)
    
    # 验证消息已发送
    mock_websocket.send_json.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_connection_manager_broadcast(connection_manager):
    """测试广播消息"""
    project_id = 1
    
    # 创建多个 Mock WebSocket
    ws1 = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2 = AsyncMock()
    ws2.send_json = AsyncMock()
    
    # 手动添加到连接池（跳过 connect 以避免心跳任务）
    connection_manager.active_connections[project_id] = {ws1, ws2}
    
    # 广播消息
    message = {"type": "broadcast", "data": "hello all"}
    await connection_manager.broadcast(project_id, message)
    
    # 验证所有连接都收到消息
    ws1.send_json.assert_called_once_with(message)
    ws2.send_json.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_connection_manager_broadcast_no_connections(connection_manager):
    """测试广播消息到没有连接的项目"""
    project_id = 999
    message = {"type": "broadcast", "data": "hello"}
    
    # 不应该抛出异常
    await connection_manager.broadcast(project_id, message)


@pytest.mark.asyncio
async def test_connection_manager_broadcast_with_failed_connection(connection_manager):
    """测试广播消息时处理失败的连接"""
    project_id = 1
    
    # 创建一个正常的和一个失败的 WebSocket
    ws_good = AsyncMock()
    ws_good.send_json = AsyncMock()
    
    ws_bad = AsyncMock()
    ws_bad.send_json = AsyncMock(side_effect=Exception("Connection failed"))
    
    # 手动添加到连接池
    connection_manager.active_connections[project_id] = {ws_good, ws_bad}
    
    # 广播消息
    message = {"type": "broadcast", "data": "hello"}
    await connection_manager.broadcast(project_id, message)
    
    # 验证正常连接收到消息
    ws_good.send_json.assert_called_once_with(message)
    
    # 验证失败的连接已被移除
    assert ws_bad not in connection_manager.active_connections.get(project_id, set())


def test_connection_manager_get_connection_count(connection_manager):
    """测试获取连接数量"""
    # 手动添加连接
    connection_manager.active_connections[1] = {Mock(), Mock()}
    connection_manager.active_connections[2] = {Mock()}
    
    # 测试获取特定项目的连接数
    assert connection_manager.get_connection_count(1) == 2
    assert connection_manager.get_connection_count(2) == 1
    assert connection_manager.get_connection_count(999) == 0
    
    # 测试获取总连接数
    assert connection_manager.get_connection_count() == 3


@pytest.mark.asyncio
async def test_send_status_update():
    """测试发送状态更新"""
    with patch.object(manager, 'broadcast', new_callable=AsyncMock) as mock_broadcast:
        project_id = 1
        status = "running"
        progress = 0.5
        current_step = "生成图像"
        
        await send_status_update(project_id, status, progress, current_step)
        
        # 验证调用了 broadcast
        mock_broadcast.assert_called_once()
        call_args = mock_broadcast.call_args[0]
        assert call_args[0] == project_id
        
        message = call_args[1]
        assert message["type"] == "status_update"
        assert message["project_id"] == project_id
        assert message["status"] == status
        assert message["progress"] == progress
        assert message["current_step"] == current_step


@pytest.mark.asyncio
async def test_send_progress_update():
    """测试发送进度更新"""
    with patch.object(manager, 'broadcast', new_callable=AsyncMock) as mock_broadcast:
        project_id = 1
        progress = 0.75
        current_step = "生成视频"
        
        await send_progress_update(project_id, progress, current_step)
        
        # 验证调用了 broadcast
        mock_broadcast.assert_called_once()
        call_args = mock_broadcast.call_args[0]
        
        message = call_args[1]
        assert message["type"] == "progress_update"
        assert message["progress"] == progress
        assert message["current_step"] == current_step


@pytest.mark.asyncio
async def test_send_completion_notification():
    """测试发送完成通知"""
    with patch.object(manager, 'broadcast', new_callable=AsyncMock) as mock_broadcast:
        project_id = 1
        result = {"video_path": "/path/to/video.mp4"}
        
        await send_completion_notification(project_id, result)
        
        # 验证调用了 broadcast
        mock_broadcast.assert_called_once()
        call_args = mock_broadcast.call_args[0]
        
        message = call_args[1]
        assert message["type"] == "completion"
        assert message["result"] == result


@pytest.mark.asyncio
async def test_send_error_notification():
    """测试发送错误通知"""
    with patch.object(manager, 'broadcast', new_callable=AsyncMock) as mock_broadcast:
        project_id = 1
        error = "生成失败：显存不足"
        
        await send_error_notification(project_id, error)
        
        # 验证调用了 broadcast
        mock_broadcast.assert_called_once()
        call_args = mock_broadcast.call_args[0]
        
        message = call_args[1]
        assert message["type"] == "error"
        assert message["error"] == error


@pytest.mark.asyncio
async def test_heartbeat_mechanism(connection_manager, mock_websocket):
    """测试心跳机制"""
    project_id = 1
    
    # 设置较短的心跳间隔用于测试
    connection_manager.heartbeat_interval = 0.1
    
    await connection_manager.connect(mock_websocket, project_id)
    
    # 等待心跳消息
    await asyncio.sleep(0.2)
    
    # 验证发送了心跳消息（至少一次，包括连接消息）
    assert mock_websocket.send_json.call_count >= 2
    
    # 检查是否有心跳消息
    calls = mock_websocket.send_json.call_args_list
    heartbeat_found = False
    for call in calls:
        message = call[0][0]
        if message.get("type") == "heartbeat":
            heartbeat_found = True
            break
    
    assert heartbeat_found, "未找到心跳消息"
    
    # 清理
    connection_manager.disconnect(mock_websocket, project_id)


@pytest.mark.asyncio
async def test_multiple_connections_same_project(connection_manager):
    """测试同一项目的多个连接"""
    project_id = 1
    
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()
    
    # 建立两个连接
    await connection_manager.connect(ws1, project_id)
    await connection_manager.connect(ws2, project_id)
    
    # 验证两个连接都在连接池中
    assert len(connection_manager.active_connections[project_id]) == 2
    assert ws1 in connection_manager.active_connections[project_id]
    assert ws2 in connection_manager.active_connections[project_id]
    
    # 清理
    connection_manager.disconnect(ws1, project_id)
    connection_manager.disconnect(ws2, project_id)
