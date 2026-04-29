"""
安全属性测试

使用 Hypothesis 进行基于属性的测试，验证安全相关的正确性属性
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, strategies as st
from hypothesis import settings as hypothesis_settings
from jose import jwt

from src.api.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)
from src.config import settings


# ==================== 属性 21：JWT Token 有效期限制 ====================

@given(
    user_id=st.integers(min_value=1, max_value=1000000),
    username=st.text(min_size=3, max_size=20, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
)
@hypothesis_settings(max_examples=20, deadline=1000)
def test_property_21_token_contains_expiration(user_id, username):
    """
    属性 21：JWT Token 包含过期时间

    验证需求：13.3

    属性：所有创建的 Token 必须包含 exp 字段，且过期时间在未来
    """
    token = create_access_token(
        data={"sub": user_id, "username": username}
    )
    
    # 解码 Token（不验证过期时间）
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False}
    )
    
    # 验证包含 exp 字段
    assert "exp" in payload
    
    # 验证过期时间在未来（允许一定的时间误差）
    exp_timestamp = payload["exp"]
    now_timestamp = datetime.now(timezone.utc).timestamp()
    assert exp_timestamp > now_timestamp - 1
    
    # 验证过期时间在合理范围内
    max_exp_timestamp = (datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS, minutes=5)).timestamp()
    assert exp_timestamp <= max_exp_timestamp



# ==================== 属性 22：密码哈希不可逆性 ====================

@given(
    password=st.text(min_size=6, max_size=20, alphabet=st.characters(min_codepoint=33, max_codepoint=126)),
)
@hypothesis_settings(max_examples=10, deadline=2000)
def test_property_22_password_hash_irreversible(password):
    """
    属性 22：密码哈希不可逆性

    验证需求：20.2

    属性：密码哈希后，无法从哈希值反推出原始密码
    """
    hashed = hash_password(password)
    
    # 验证哈希值不等于原始密码
    assert hashed != password
    
    # 验证哈希值不包含原始密码
    assert password not in hashed
    
    # 验证哈希值是 bcrypt 格式
    assert hashed.startswith("$2b$")
    
    # 验证可以正确验证密码
    assert verify_password(password, hashed) is True
    
    # 验证错误密码无法通过验证
    wrong_password = password + "x"
    assert verify_password(wrong_password, hashed) is False


@given(
    password=st.text(min_size=6, max_size=20, alphabet=st.characters(min_codepoint=33, max_codepoint=126)),
)
@hypothesis_settings(max_examples=10, deadline=3000)
def test_property_22_same_password_different_hashes(password):
    """
    属性 22：相同密码产生不同哈希值（盐值随机性）

    验证需求：20.2

    属性：相同的密码多次哈希应该产生不同的哈希值（因为盐值不同）
    """
    hash1 = hash_password(password)
    hash2 = hash_password(password)
    
    # 验证两次哈希值不同
    assert hash1 != hash2
    
    # 验证两个哈希值都可以验证原始密码
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True


# ==================== 额外的安全属性测试 ====================

@given(
    user_id=st.integers(min_value=1, max_value=1000000),
    username=st.text(min_size=3, max_size=20, alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
)
@hypothesis_settings(max_examples=20, deadline=1000)
def test_property_token_tampering_detection(user_id, username):
    """
    额外属性：Token 篡改检测

    验证需求：13.3, 20.2

    属性：篡改 Token 内容后，解码应该失败
    """
    token = create_access_token(
        data={"sub": user_id, "username": username}
    )
    
    # 篡改 Token（完全替换签名部分）
    parts = token.split('.')
    if len(parts) == 3:
        tampered_token = f"{parts[0]}.{parts[1]}.INVALID_SIGNATURE_HERE"
        
        # 解码篡改的 Token 应该失败
        payload = decode_access_token(tampered_token)
        assert payload is None


@given(
    user_id=st.integers(min_value=1, max_value=1000000),
)
@hypothesis_settings(max_examples=20, deadline=1000)
def test_property_token_user_id_type_consistency(user_id):
    """
    额外属性：Token 用户 ID 类型一致性

    验证需求：13.3

    属性：Token 中的 sub 字段应该始终是字符串类型（JWT 标准）
    """
    token = create_access_token(data={"sub": user_id})
    
    # 解码 Token
    payload = decode_access_token(token)
    assert payload is not None
    
    # 验证 sub 字段是字符串
    assert isinstance(payload["sub"], str)
    
    # 验证可以转换回整数
    assert int(payload["sub"]) == user_id
