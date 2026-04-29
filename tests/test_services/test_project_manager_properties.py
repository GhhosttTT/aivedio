"""
项目管理服务属性测试

使用 Hypothesis 进行基于属性的测试，验证 ProjectManager 的正确性属性
"""

import pytest
import os
import tempfile
import shutil
from datetime import datetime
from hypothesis import given, strategies as st, settings, assume
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, ProjectStatus
from src.services.project_manager import ProjectManager


# 自定义策略：生成有效的项目名称
@st.composite
def valid_project_name(draw):
    """
    生成有效的项目名称
    
    规则：
    - 长度：1-100字符
    - 字符：中文、英文、数字、下划线、连字符、空格
    - 必须匹配正则表达式：^[\\u4e00-\\u9fa5a-zA-Z0-9_\\-\\s]+$
    """
    # 生成长度
    length = draw(st.integers(min_value=1, max_value=20))  # 减少长度以提高测试效率
    
    # 定义字符集合
    # 英文字母
    letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    # 数字
    digits = '0123456789'
    # 特殊字符
    special = '_- '
    # 常用中文字符（简化，只使用一小部分）
    chinese = '一二三四五六七八九十项目测试'
    
    # 合并所有字符
    all_chars = letters + digits + special + chinese
    
    # 生成字符列表
    chars = draw(st.lists(
        st.sampled_from(all_chars),
        min_size=length,
        max_size=length
    ))
    
    name = ''.join(chars).strip()
    
    # 确保不为空（去除空格后）
    assume(len(name) > 0)
    # 确保长度不超过100
    assume(len(name) <= 100)
    
    return name


# 自定义策略：生成可选的文本字段
@st.composite
def optional_text(draw, max_length=500):
    """生成可选的文本字段"""
    return draw(st.one_of(
        st.none(),
        st.text(min_size=1, max_size=max_length)
    ))


@pytest.fixture(scope="module")
def temp_storage_module():
    """创建临时存储目录（模块级别）"""
    temp_dir = tempfile.mkdtemp()
    
    # 设置环境变量
    os.environ["STORAGE_PATH"] = temp_dir
    
    yield temp_dir
    
    # 清理
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


def create_test_db_and_manager():
    """创建测试数据库和 ProjectManager 实例的辅助函数"""
    # 使用内存数据库
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    manager = ProjectManager(session)
    
    return session, manager


class TestProjectManagerProperties:
    """ProjectManager 属性测试类"""
    
    # 属性 1：项目创建幂等性
    # 验证需求：1.1, 1.2
    @given(
        name=valid_project_name(),
        theme=optional_text(max_length=200),
        outline=optional_text(max_length=1000)
    )
    @settings(max_examples=50, deadline=None)
    def test_property_1_project_creation_idempotency(
        self,
        temp_storage_module,
        name,
        theme,
        outline
    ):
        """
        **验证需求：1.1, 1.2**
        
        属性 1：项目创建幂等性
        
        对于任何有效的项目名称、主题和大纲，创建项目应该：
        1. 返回唯一的项目 ID
        2. 该项目可以通过 ID 检索到完整信息
        3. 检索到的信息与创建时提供的信息一致
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建项目
            project = project_manager.create_project(
                name=name,
                theme=theme,
                outline=outline
            )
            
            # 验证返回了有效的项目 ID
            assert project.id is not None
            assert isinstance(project.id, int)
            assert project.id > 0
            
            # 通过 ID 检索项目
            retrieved_project = project_manager.get_project(project.id)
            
            # 验证项目可以被检索到
            assert retrieved_project is not None
            
            # 验证检索到的信息与创建时一致
            assert retrieved_project.id == project.id
            assert retrieved_project.name == name
            # theme 和 outline 会被 strip，所以需要比较 strip 后的值
            expected_theme = theme.strip() if theme else None
            expected_outline = outline.strip() if outline else None
            # 如果 strip 后为空字符串，ProjectManager 会将其设为 None
            if expected_theme == '':
                expected_theme = None
            if expected_outline == '':
                expected_outline = None
            assert retrieved_project.theme == expected_theme
            assert retrieved_project.outline == expected_outline
            assert retrieved_project.status == ProjectStatus.DRAFT
            
            # 验证必需字段存在
            assert retrieved_project.created_at is not None
            assert retrieved_project.updated_at is not None
            assert isinstance(retrieved_project.created_at, datetime)
            assert isinstance(retrieved_project.updated_at, datetime)
            
        finally:
            session.close()
    
    # 属性 2：项目更新保持一致性
    # 验证需求：1.3
    @given(
        original_name=valid_project_name(),
        new_name=valid_project_name(),
        new_theme=optional_text(max_length=200),
        new_outline=optional_text(max_length=1000)
    )
    @settings(max_examples=50, deadline=None)
    def test_property_2_project_update_consistency(
        self,
        temp_storage_module,
        original_name,
        new_name,
        new_theme,
        new_outline
    ):
        """
        **验证需求：1.3**
        
        属性 2：项目更新保持一致性
        
        对于任何已存在的项目，更新剧本或分镜后：
        1. 检索项目应该返回更新后的值
        2. updated_at 时间戳应该大于更新前的值
        3. 其他未更新的字段保持不变
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建项目
            project = project_manager.create_project(name=original_name)
            
            original_id = project.id
            original_created_at = project.created_at
            original_updated_at = project.updated_at
            
            # 等待一小段时间确保时间戳不同
            import time
            time.sleep(0.01)
            
            # 更新项目
            updated_project = project_manager.update_project(
                project.id,
                name=new_name,
                theme=new_theme,
                outline=new_outline
            )
            
            # 验证更新后的值
            assert updated_project.name == new_name
            assert updated_project.theme == new_theme
            assert updated_project.outline == new_outline
            
            # 验证 updated_at 时间戳增加
            assert updated_project.updated_at > original_updated_at
            
            # 验证未更新的字段保持不变
            assert updated_project.id == original_id
            assert updated_project.created_at == original_created_at
            assert updated_project.status == ProjectStatus.DRAFT
            
            # 通过 ID 重新检索，验证更新已持久化
            retrieved_project = project_manager.get_project(project.id)
            assert retrieved_project.name == new_name
            assert retrieved_project.theme == new_theme
            assert retrieved_project.outline == new_outline
            assert retrieved_project.updated_at == updated_project.updated_at
            
        finally:
            session.close()
    
    # 属性 3：项目删除完整性
    # 验证需求：1.4
    @given(
        name=valid_project_name(),
        theme=optional_text(max_length=200)
    )
    @settings(max_examples=50, deadline=None)
    def test_property_3_project_deletion_integrity(
        self,
        temp_storage_module,
        name,
        theme
    ):
        """
        **验证需求：1.4**
        
        属性 3：项目删除完整性
        
        对于任何已存在的项目，删除项目后：
        1. 该项目不应该能被检索到
        2. 所有关联的文件应该被删除
        3. 删除操作返回成功
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建项目
            project = project_manager.create_project(name=name, theme=theme)
            project_id = project.id
            storage_path = project.storage_path
            
            # 验证存储目录存在
            assert storage_path is not None
            assert os.path.exists(storage_path)
            
            # 创建一些测试文件
            test_file = os.path.join(storage_path, "test.txt")
            with open(test_file, "w") as f:
                f.write("test content")
            
            assert os.path.exists(test_file)
            
            # 删除项目
            result = project_manager.delete_project(project_id)
            
            # 验证删除操作返回成功
            assert result is True
            
            # 验证项目不能被检索到
            deleted_project = project_manager.get_project(project_id)
            assert deleted_project is None
            
            # 验证存储目录和文件被删除
            assert not os.path.exists(storage_path)
            assert not os.path.exists(test_file)
            
        finally:
            session.close()
    
    # 属性 4：项目列表排序正确性
    # 验证需求：1.5
    @given(
        project_names=st.lists(
            valid_project_name(),
            min_size=2,
            max_size=10,
            unique=True
        )
    )
    @settings(max_examples=30, deadline=None)
    def test_property_4_project_list_sorting_correctness(
        self,
        temp_storage_module,
        project_names
    ):
        """
        **验证需求：1.5**
        
        属性 4：项目列表排序正确性
        
        对于任何项目集合，列表查询应该：
        1. 返回按 created_at 时间戳倒序排列的项目列表
        2. 最新创建的项目排在最前面
        3. 列表中的项目数量与创建的项目数量一致
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建多个项目
            created_projects = []
            for name in project_names:
                project = project_manager.create_project(name=name)
                created_projects.append(project)
                
                # 添加小延迟确保时间戳不同
                import time
                time.sleep(0.01)
            
            # 获取项目列表（默认按创建时间倒序）
            projects = project_manager.list_projects(limit=len(project_names))
            
            # 验证返回的项目数量正确
            assert len(projects) == len(project_names)
            
            # 验证排序正确性：按 created_at 倒序
            for i in range(len(projects) - 1):
                assert projects[i].created_at >= projects[i + 1].created_at
            
            # 验证最新创建的项目排在最前面
            assert projects[0].id == created_projects[-1].id
            assert projects[0].name == project_names[-1]
            
            # 验证最早创建的项目排在最后面
            assert projects[-1].id == created_projects[0].id
            assert projects[-1].name == project_names[0]
            
            # 验证所有创建的项目都在列表中
            project_ids = {p.id for p in projects}
            created_ids = {p.id for p in created_projects}
            assert project_ids == created_ids
            
        finally:
            session.close()
    
    # 额外属性：项目 ID 唯一性
    @given(
        project_names=st.lists(
            valid_project_name(),
            min_size=2,
            max_size=20,
            unique=True
        )
    )
    @settings(max_examples=30, deadline=None)
    def test_property_extra_project_id_uniqueness(
        self,
        temp_storage_module,
        project_names
    ):
        """
        额外属性：项目 ID 唯一性
        
        对于任何数量的项目创建操作：
        1. 每个项目应该获得唯一的 ID
        2. 不同项目的 ID 不应该重复
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建多个项目
            project_ids = []
            for name in project_names:
                project = project_manager.create_project(name=name)
                project_ids.append(project.id)
            
            # 验证所有 ID 都是唯一的
            assert len(project_ids) == len(set(project_ids))
            
            # 验证所有 ID 都是正整数
            for project_id in project_ids:
                assert isinstance(project_id, int)
                assert project_id > 0
                
        finally:
            session.close()
    
    # 额外属性：项目状态过滤正确性
    @given(
        draft_count=st.integers(min_value=1, max_value=5),
        completed_count=st.integers(min_value=1, max_value=5)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_extra_project_status_filtering(
        self,
        temp_storage_module,
        draft_count,
        completed_count
    ):
        """
        额外属性：项目状态过滤正确性
        
        对于任何状态的项目集合：
        1. 按状态过滤应该只返回该状态的项目
        2. 不同状态的项目数量应该正确
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建草稿项目
            draft_projects = []
            for i in range(draft_count):
                project = project_manager.create_project(name=f"草稿项目{i}")
                draft_projects.append(project)
            
            # 创建完成项目
            completed_projects = []
            for i in range(completed_count):
                project = project_manager.create_project(name=f"完成项目{i}")
                project_manager.update_project(
                    project.id,
                    status=ProjectStatus.COMPLETED
                )
                completed_projects.append(project)
            
            # 验证草稿项目过滤
            draft_list = project_manager.list_projects(
                status=ProjectStatus.DRAFT,
                limit=100
            )
            assert len(draft_list) == draft_count
            for project in draft_list:
                assert project.status == ProjectStatus.DRAFT
            
            # 验证完成项目过滤
            completed_list = project_manager.list_projects(
                status=ProjectStatus.COMPLETED,
                limit=100
            )
            assert len(completed_list) == completed_count
            for project in completed_list:
                assert project.status == ProjectStatus.COMPLETED
            
            # 验证总数
            all_projects = project_manager.list_projects(limit=100)
            assert len(all_projects) == draft_count + completed_count
            
        finally:
            session.close()
    
    # 额外属性：项目分页正确性
    @given(
        total_count=st.integers(min_value=5, max_value=20),
        page_size=st.integers(min_value=2, max_value=5)
    )
    @settings(max_examples=20, deadline=None)
    def test_property_extra_project_pagination_correctness(
        self,
        temp_storage_module,
        total_count,
        page_size
    ):
        """
        额外属性：项目分页正确性
        
        对于任何项目集合和分页参数：
        1. 分页应该返回正确数量的项目
        2. 不同页的项目不应该重复
        3. 所有页的项目合并后应该等于总项目数
        """
        # 为每个示例创建新的数据库和管理器
        session, project_manager = create_test_db_and_manager()
        
        try:
            # 创建项目
            created_projects = []
            for i in range(total_count):
                project = project_manager.create_project(name=f"项目{i}")
                created_projects.append(project)
                import time
                time.sleep(0.01)
            
            # 计算总页数
            total_pages = (total_count + page_size - 1) // page_size
            
            # 获取所有页
            all_paged_projects = []
            for page in range(total_pages):
                offset = page * page_size
                projects = project_manager.list_projects(
                    limit=page_size,
                    offset=offset
                )
                
                # 验证每页的项目数量
                if page < total_pages - 1:
                    # 非最后一页应该返回完整的 page_size
                    assert len(projects) == page_size
                else:
                    # 最后一页可能少于 page_size
                    expected_count = total_count - (page * page_size)
                    assert len(projects) == expected_count
                
                all_paged_projects.extend(projects)
            
            # 验证总数
            assert len(all_paged_projects) == total_count
            
            # 验证没有重复
            project_ids = [p.id for p in all_paged_projects]
            assert len(project_ids) == len(set(project_ids))
            
            # 验证所有项目都被包含
            created_ids = {p.id for p in created_projects}
            paged_ids = {p.id for p in all_paged_projects}
            assert created_ids == paged_ids
            
        finally:
            session.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
