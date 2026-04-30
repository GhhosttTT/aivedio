"""
API 速率限制属性测试

使用 Hypothesis 进行基于属性的测试，验证速率限制的正确性
"""
import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import Mock, patch

from src.api.rate_limiter import RateLimiter, RateLimitExceeded


class TestRateLimiterProperties:
    """速率限制属性测试"""
    
    @given(
        rate=st.integers(min_value=1, max_value=100),
        period=st.integers(min_value=1, max_value=60),
        num_requests=st.integers(min_value=1, max_value=200)
    )
    @settings(max_examples=20, deadline=2000)
    def test_property_23_rate_limit_effectiveness(self, rate, period, num_requests):
        """
        属性 23：API 速率限制有效性
        
        验证：
        1. 在限制周期内，允许的请求数不超过配置的速率
        2. 超过速率限制后，后续请求被拒绝
        3. retry_after 时间合理（大于 0）
        """
        limiter = RateLimiter(rate=rate, period=period)
        identifier = "test_user"
        
        allowed_count = 0
        denied_count = 0
        
        # 发送多个请求
        for i in range(num_requests):
            allowed, retry_after = limiter._check_rate_limit_local(identifier)
            
            if allowed:
                allowed_count += 1
            else:
                denied_count += 1
                # 验证 retry_after 大于 0
                assert retry_after > 0, f"retry_after 应该大于 0，实际为 {retry_after}"
        
        # 验证允许的请求数不超过速率限制
        assert allowed_count <= rate, \
            f"允许的请求数 ({allowed_count}) 不应超过速率限制 ({rate})"
        
        # 如果请求数超过速率限制，应该有被拒绝的请求
        if num_requests > rate:
            assert denied_count > 0, \
                f"当请求数 ({num_requests}) 超过速率限制 ({rate}) 时，应该有被拒绝的请求"
        
        # 验证总请求数等于允许数 + 拒绝数
        assert allowed_count + denied_count == num_requests, \
            f"总请求数不匹配：{allowed_count} + {denied_count} != {num_requests}"
    
    @given(
        rate=st.integers(min_value=1, max_value=50),
        period=st.integers(min_value=1, max_value=30)
    )
    @settings(max_examples=15, deadline=2000)
    def test_property_rate_limit_per_user_isolation(self, rate, period):
        """
        属性：速率限制用户隔离性
        
        验证：
        1. 不同用户的速率限制互不影响
        2. 每个用户都有独立的速率限制计数
        """
        limiter = RateLimiter(rate=rate, period=period)
        
        user1 = "user1"
        user2 = "user2"
        
        # 用户 1 发送请求直到达到限制
        user1_allowed = 0
        for i in range(rate + 5):
            allowed, _ = limiter._check_rate_limit_local(user1)
            if allowed:
                user1_allowed += 1
        
        # 用户 2 应该仍然可以发送请求
        user2_allowed = 0
        for i in range(rate):
            allowed, _ = limiter._check_rate_limit_local(user2)
            if allowed:
                user2_allowed += 1
        
        # 验证用户 1 达到限制
        assert user1_allowed == rate, \
            f"用户 1 应该被允许 {rate} 个请求，实际为 {user1_allowed}"
        
        # 验证用户 2 不受影响
        assert user2_allowed == rate, \
            f"用户 2 应该被允许 {rate} 个请求，实际为 {user2_allowed}"
    
    @given(
        rate=st.integers(min_value=5, max_value=20),
        period=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=10, deadline=2000)
    def test_property_rate_limit_token_bucket_behavior(self, rate, period):
        """
        属性：速率限制令牌桶行为
        
        验证：
        1. 初始时有 rate 个令牌可用
        2. 每次请求消耗一个令牌
        3. 令牌用完后请求被拒绝
        """
        limiter = RateLimiter(rate=rate, period=period)
        identifier = "test_user"
        
        # 第一批请求：应该有 rate 个被允许
        first_batch_allowed = 0
        for i in range(rate):
            allowed, _ = limiter._check_rate_limit_local(identifier)
            if allowed:
                first_batch_allowed += 1
        
        assert first_batch_allowed == rate, \
            f"第一批应该允许 {rate} 个请求，实际为 {first_batch_allowed}"
        
        # 第二批请求：应该全部被拒绝
        second_batch_denied = 0
        for i in range(5):
            allowed, retry_after = limiter._check_rate_limit_local(identifier)
            if not allowed:
                second_batch_denied += 1
                assert retry_after > 0
        
        assert second_batch_denied == 5, \
            f"第二批应该拒绝 5 个请求，实际为 {second_batch_denied}"
    
    @given(
        rate=st.integers(min_value=1, max_value=20)
    )
    @settings(max_examples=10, deadline=2000)
    def test_property_rate_limit_retry_after_consistency(self, rate):
        """
        属性：retry_after 一致性
        
        验证：
        1. 当请求被拒绝时，retry_after 应该大于 0
        2. retry_after 应该小于等于 period
        """
        period = 60
        limiter = RateLimiter(rate=rate, period=period)
        identifier = "test_user"
        
        # 消耗所有令牌
        for i in range(rate):
            limiter._check_rate_limit_local(identifier)
        
        # 下一个请求应该被拒绝
        allowed, retry_after = limiter._check_rate_limit_local(identifier)
        
        assert not allowed, "请求应该被拒绝"
        assert retry_after > 0, f"retry_after 应该大于 0，实际为 {retry_after}"
        assert retry_after <= period, \
            f"retry_after ({retry_after}) 不应超过 period ({period})"
    
    @given(
        rate=st.integers(min_value=1, max_value=50),
        num_users=st.integers(min_value=2, max_value=10)
    )
    @settings(max_examples=10, deadline=3000)
    def test_property_rate_limit_concurrent_users(self, rate, num_users):
        """
        属性：并发用户速率限制
        
        验证：
        1. 多个用户同时发送请求时，每个用户的限制独立
        2. 总允许请求数等于 rate * num_users
        """
        period = 60
        limiter = RateLimiter(rate=rate, period=period)
        
        total_allowed = 0
        
        # 每个用户发送 rate + 5 个请求
        for user_id in range(num_users):
            identifier = f"user_{user_id}"
            user_allowed = 0
            
            for i in range(rate + 5):
                allowed, _ = limiter._check_rate_limit_local(identifier)
                if allowed:
                    user_allowed += 1
            
            # 每个用户应该被允许 rate 个请求
            assert user_allowed == rate, \
                f"用户 {user_id} 应该被允许 {rate} 个请求，实际为 {user_allowed}"
            
            total_allowed += user_allowed
        
        # 总允许请求数应该等于 rate * num_users
        expected_total = rate * num_users
        assert total_allowed == expected_total, \
            f"总允许请求数应该为 {expected_total}，实际为 {total_allowed}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
