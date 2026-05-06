"""
角色外貌特征设置脚本

用于为项目中的角色设置详细的外貌特征，确保不同角色在图像生成时有明显区分
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from src.database.database import engine
from src.database.models import Project, Character
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 常见角色外貌模板（用于快速设置）
APPEARANCE_TEMPLATES = {
    "年轻女性_温柔型": "25岁女性，长发披肩，温柔气质，清秀面容，身材苗条，穿着优雅连衣裙",
    "年轻女性_职场型": "28岁女性，短发干练，职业装扮，精致妆容，自信气场，穿着商务套装",
    "年轻女性_活泼型": "22岁女性，马尾辫，邻家女孩气质，甜美笑容，休闲装扮",
    
    "成熟男性_霸总型": "32岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质，身材挺拔",
    "成熟男性_儒雅型": "35岁男性，中分发型，温文尔雅，穿着休闲西装，书卷气质",
    "年轻男性_阳光型": "26岁男性，短发清爽，阳光帅气，运动装扮，健康肤色",
    "年轻男性_痞帅型": "28岁男性，微卷短发，不羁气质，休闲装扮，略带胡茬",
    
    "中年女性_优雅型": "45岁女性，盘发，优雅气质，穿着旗袍或高档服饰，保养得当",
    "中年男性_成功型": "50岁男性，短发微白，成熟稳重，高档西装，商界精英气质",
    
    "老年女性": "65岁女性，花白短发，慈祥面容，穿着朴素得体",
    "老年男性": "70岁男性，白发，和蔼可亲，穿着中式唐装或休闲装",
}


def list_projects(db: Session):
    """列出所有项目"""
    projects = db.query(Project).all()
    
    if not projects:
        print("❌ 没有找到任何项目")
        return None
    
    print("\n📋 可用项目列表：")
    print("-" * 60)
    for project in projects:
        print(f"ID: {project.id} | 名称: {project.name} | 状态: {project.status.value}")
    print("-" * 60)
    
    return projects


def list_characters(db: Session, project_id: int):
    """列出项目中的所有角色"""
    characters = db.query(Character).filter(
        Character.project_id == project_id
    ).all()
    
    if not characters:
        print(f"❌ 项目 {project_id} 中没有角色")
        return None
    
    print(f"\n👥 项目中的角色列表：")
    print("-" * 80)
    for char in characters:
        appearance_status = "✅ 已设置" if char.appearance else "❌ 未设置"
        print(f"ID: {char.id} | 名称: {char.name} | 外貌: {appearance_status}")
        if char.appearance:
            print(f"   描述: {char.appearance}")
    print("-" * 80)
    
    return characters


def show_templates():
    """显示外貌模板"""
    print("\n📝 可用外貌模板：")
    print("-" * 80)
    for i, (key, value) in enumerate(APPEARANCE_TEMPLATES.items(), 1):
        print(f"{i}. {key}")
        print(f"   {value}")
    print("-" * 80)


def set_character_appearance(db: Session, character_id: int, appearance: str):
    """设置角色外貌"""
    character = db.query(Character).filter(Character.id == character_id).first()
    
    if not character:
        print(f"❌ 角色 {character_id} 不存在")
        return False
    
    character.appearance = appearance
    db.commit()
    
    print(f"✅ 角色 '{character.name}' 的外貌特征已设置：")
    print(f"   {appearance}")
    
    return True


def interactive_setup(db: Session):
    """交互式设置角色外貌"""
    # 1. 选择项目
    projects = list_projects(db)
    if not projects:
        return
    
    try:
        project_id = int(input("\n请输入项目 ID: "))
    except ValueError:
        print("❌ 无效的项目 ID")
        return
    
    # 验证项目存在
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        print(f"❌ 项目 {project_id} 不存在")
        return
    
    print(f"\n✅ 已选择项目: {project.name}")
    
    # 2. 列出角色
    characters = list_characters(db, project_id)
    if not characters:
        return
    
    # 3. 为每个角色设置外貌
    while True:
        print("\n" + "=" * 80)
        print("选项：")
        print("1. 为角色设置外貌")
        print("2. 查看外貌模板")
        print("3. 重新显示角色列表")
        print("4. 退出")
        print("=" * 80)
        
        choice = input("请选择操作 (1-4): ").strip()
        
        if choice == "1":
            try:
                char_id = int(input("请输入角色 ID: "))
            except ValueError:
                print("❌ 无效的角色 ID")
                continue
            
            character = db.query(Character).filter(Character.id == char_id).first()
            if not character:
                print(f"❌ 角色 {char_id} 不存在")
                continue
            
            print(f"\n为角色 '{character.name}' 设置外貌特征")
            print("提示：外貌特征应包含年龄、发型、服装、气质等，用于区分不同角色")
            print("示例：30岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质")
            
            print("\n选项：")
            print("1. 使用模板")
            print("2. 自定义输入")
            
            method = input("请选择 (1-2): ").strip()
            
            if method == "1":
                show_templates()
                try:
                    template_num = int(input("请选择模板编号: "))
                    template_key = list(APPEARANCE_TEMPLATES.keys())[template_num - 1]
                    appearance = APPEARANCE_TEMPLATES[template_key]
                except (ValueError, IndexError):
                    print("❌ 无效的模板编号")
                    continue
            elif method == "2":
                appearance = input("请输入外貌特征: ").strip()
                if not appearance:
                    print("❌ 外貌特征不能为空")
                    continue
            else:
                print("❌ 无效的选择")
                continue
            
            set_character_appearance(db, char_id, appearance)
            
        elif choice == "2":
            show_templates()
            
        elif choice == "3":
            list_characters(db, project_id)
            
        elif choice == "4":
            print("👋 退出设置")
            break
        
        else:
            print("❌ 无效的选择")


def batch_setup_from_names(db: Session, project_id: int):
    """
    根据角色名称智能推荐外貌特征
    
    这个函数会分析角色名称，尝试推荐合适的外貌模板
    """
    characters = db.query(Character).filter(
        Character.project_id == project_id,
        Character.appearance.is_(None)  # 只处理未设置外貌的角色
    ).all()
    
    if not characters:
        print("✅ 所有角色都已设置外貌特征")
        return
    
    print(f"\n🤖 智能推荐外貌特征（项目 {project_id}）")
    print("-" * 80)
    
    # 简单的名称匹配规则
    name_patterns = {
        "少爷": "成熟男性_霸总型",
        "总裁": "成熟男性_霸总型",
        "老板": "成熟男性_成功型",
        "小姐": "年轻女性_温柔型",
        "夫人": "中年女性_优雅型",
        "太太": "中年女性_优雅型",
        "秘书": "年轻女性_职场型",
        "助理": "年轻女性_职场型",
        "老爷": "老年男性",
        "奶奶": "老年女性",
    }
    
    for character in characters:
        # 尝试匹配名称
        matched_template = None
        for pattern, template_key in name_patterns.items():
            if pattern in character.name:
                matched_template = template_key
                break
        
        if matched_template:
            appearance = APPEARANCE_TEMPLATES[matched_template]
            print(f"角色: {character.name}")
            print(f"推荐: {matched_template}")
            print(f"外貌: {appearance}")
            
            confirm = input("是否应用此推荐？(y/n): ").strip().lower()
            if confirm == 'y':
                set_character_appearance(db, character.id, appearance)
        else:
            print(f"角色: {character.name} - 无法自动推荐，请手动设置")
        
        print("-" * 80)


def main():
    """主函数"""
    print("=" * 80)
    print("🎭 角色外貌特征设置工具")
    print("=" * 80)
    
    # 创建数据库会话
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        print("\n选择模式：")
        print("1. 交互式设置（推荐）")
        print("2. 智能批量推荐")
        
        mode = input("请选择模式 (1-2): ").strip()
        
        if mode == "1":
            interactive_setup(db)
        elif mode == "2":
            projects = list_projects(db)
            if projects:
                try:
                    project_id = int(input("\n请输入项目 ID: "))
                    batch_setup_from_names(db, project_id)
                except ValueError:
                    print("❌ 无效的项目 ID")
        else:
            print("❌ 无效的选择")
    
    finally:
        db.close()
        print("\n✅ 数据库连接已关闭")


if __name__ == "__main__":
    main()
