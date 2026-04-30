"""
WebSocket 属性测试

使用 Hypothesis 进行基于属性的测试，验证 WebSocket 通信的正确性
"""
import pytest
import asyncio
from hypothesis import given, strategies as st, settings
from unittest.mock import AsyncMock

from src.api.websocket import ConnectionManager, send_status_update, send_progress_update


class TestWebSocketProperties:
    """WebSocket 属性测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """设置测试环境"""
        self.manager = ConnectionManager()
        
        yield
        
        # 清理
        self.manager._connections.clear()
    
    @given(
        num_connections=st.integers(min_value=1, max_value=10),
        project_id=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=15, deadline=2000)
    @pytest.mark.asyncio
    async def test_property_16_websocket_message_push_timeliness(self, num_connections, project_id):
        """
        属性 16：WebSocket 消息推送及时性
        
        验证：
        1. 消息能够及时推送到所有连接的客户端
        2. 所有客户端都能收到相同的消息
        3. 消息推送不会丢失
        """
        # 创建模拟的 WebSocket 连接
        mock_websockets = []
        for i in range(num_connections):
            mock_ws = AsyncMock()
            mock_ws.send_json = AsyncMock()
            mock_websockets.append(mock_ws)
            
            # 添加到连接管理器
            await self.manager.connect(mock_ws, str(project_id))
        
        # 准备测试消息
        test_message = {
            "type": "test",
            "data": "test_data",
            "timestamp": "2026-04-29T10:00:00Z"
        }
        
        # 广播消息
        await self.manager.broadcast(str(project_id), test_message)
        
        # 验证所有连接都收到消息
        for i, mock_ws in enumerate(mock_websockets):
            assert mock_ws.send_json.called, \
                f"连接 {i+1} 应该收到消息"
            
            # 获取发送的消息
            call_args = mock_ws.send_json.call_args
            if call_args:
                sent_message = call_args[0][0]
                assert sent_message == test_message, \
                    f"连接 {i+1} 收到的消息与发送的消息不一致"
    
    @given(
        num_projects=st.integers(min_value=1, max_value=5),
        connections_per_project=st.integers(min_value=1, max_value=5)
    )
    @settings(max_examples=10, deadline=2000)
    @pytest.mark.asyncio
    async def test_property_17_websocket_connection_management_correctness(self, num_projects, connections_per_project):
        """
        属性 17：WebSocket 连接管理正确性
        
        验证：
        1. 连接按项目 ID 正确分组
        2. 断开连接后，连接从管理器中移除
        3. 不同项目的连接互不影响
        """
        # 创建多个项目的连接
        project_connections = {}
        
        for project_id in range(num_projects):
            project_key = str(project_id)
            project_connections[project_key] = []
            
            for i in range(connections_per_project):
                mock_ws = AsyncMock()
                mock_ws.send_json = AsyncMock()
                project_connections[project_key].append(mock_ws)
                
                # 添加到连接管理器
                await self.manager.connect(mock_ws, project_key)
        
        # 验证连接数量
        for project_key, connections in project_connections.items():
            assert len(self.manager._connections.get(project_key, [])) == connections_per_project, \
                f"项目 {project_key} 的连接数不正确"
        
        # 断开第一个项目的所有连接
        first_project_key = str(0)
        for mock_ws in project_connections[first_project_key]:
            self.manager.disconnect(mock_ws, first_project_key)
        
        # 验证第一个项目的连接已移除
        assert len(self.manager._connections.get(first_project_key, [])) == 0, \
            f"项目 {first_project_key} 的连接应该被移除"
        
        # 验证其他项目的连接不受影响
        for project_id in range(1, num_projects):
            project_key = str(project_id)
            assert len(self.manager._connections.get(project_key, [])) == connections_per_project, \
                f"项目 {project_key} 的连接数应该保持不变"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
