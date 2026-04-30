"""
SubtitleGenerator 属性测试

使用 Hypothesis 进行基于属性的测试，验证字幕生成的正确性
"""
import pytest
import os
import tempfile
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import Mock, patch, MagicMock

from src.services.subtitle_generator import SubtitleGenerator


class TestSubtitleGeneratorProperties:
    """SubtitleGenerator 属性测试"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """设置测试环境"""
        self.generator = SubtitleGenerator()
        self.temp_dir = tempfile.mkdtemp()
        
        yield
        
        # 清理临时文件
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    @given(
        num_subtitles=st.integers(min_value=1, max_value=20),
        chars_per_second=st.floats(min_value=10.0, max_value=20.0)
    )
    @settings(max_examples=15, deadline=2000)
    def test_property_11_subtitle_timeline_alignment(self, num_subtitles, chars_per_second):
        """
        属性 11：字幕时间轴对齐
        
        验证：
        1. 字幕的开始时间按顺序递增
        2. 每个字幕的结束时间大于开始时间
        3. 相邻字幕之间没有重叠
        4. 字幕时长与文本长度成正比
        """
        # 生成测试数据
        subtitles = []
        for i in range(num_subtitles):
            text_length = (i + 1) * 10  # 文本长度递增
            text = "测" * text_length
            subtitles.append(text)
        
        # 计算时间轴
        timings = self.generator.calculate_timing(subtitles, chars_per_second=chars_per_second)
        
        # 验证时间轴数量
        assert len(timings) == num_subtitles, \
            f"时间轴数量不匹配：期望 {num_subtitles}，实际 {len(timings)}"
        
        # 验证每个字幕的时间轴
        for i, (start, end) in enumerate(timings):
            # 验证结束时间大于开始时间
            assert end > start, \
                f"字幕 {i+1} 的结束时间 ({end}) 应该大于开始时间 ({start})"
            
            # 验证开始时间非负
            assert start >= 0, \
                f"字幕 {i+1} 的开始时间 ({start}) 不能为负"
            
            # 验证时长与文本长度成正比
            duration = end - start
            expected_duration = len(subtitles[i]) / chars_per_second
            # 允许一定的误差（±10%）
            assert abs(duration - expected_duration) / expected_duration < 0.1, \
                f"字幕 {i+1} 的时长 ({duration}) 与预期 ({expected_duration}) 相差过大"
        
        # 验证开始时间递增
        for i in range(1, len(timings)):
            assert timings[i][0] > timings[i-1][0], \
                f"字幕 {i+1} 的开始时间 ({timings[i][0]}) 应该大于字幕 {i} 的开始时间 ({timings[i-1][0]})"
        
        # 验证相邻字幕没有重叠
        for i in range(1, len(timings)):
            prev_end = timings[i-1][1]
            curr_start = timings[i][0]
            assert curr_start >= prev_end, \
                f"字幕 {i+1} 的开始时间 ({curr_start}) 应该不早于字幕 {i} 的结束时间 ({prev_end})"
    
    @given(
        num_subtitles=st.integers(min_value=1, max_value=15)
    )
    @settings(max_examples=15, deadline=2000)
    def test_property_12_subtitle_file_format_correctness(self, num_subtitles):
        """
        属性 12：字幕文件格式正确性
        
        验证：
        1. SRT 文件格式符合标准
        2. 每个字幕块包含序号、时间轴和文本
        3. 时间轴格式正确（HH:MM:SS,mmm --> HH:MM:SS,mmm）
        4. 字幕块之间有空行分隔
        """
        # 生成测试数据
        subtitles = [f"字幕文本 {i+1}" for i in range(num_subtitles)]
        timings = [(i * 2.0, i * 2.0 + 1.5) for i in range(num_subtitles)]
        
        # 生成 SRT 文件
        srt_path = os.path.join(self.temp_dir, "test.srt")
        self.generator.generate_srt(subtitles, timings, srt_path)
        
        # 读取文件内容
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 分割字幕块
        blocks = content.strip().split('\n\n')
        
        # 验证字幕块数量
        assert len(blocks) == num_subtitles, \
            f"字幕块数量不匹配：期望 {num_subtitles}，实际 {len(blocks)}"
        
        # 验证每个字幕块的格式
        for i, block in enumerate(blocks):
            lines = block.strip().split('\n')
            
            # 验证至少有 3 行（序号、时间轴、文本）
            assert len(lines) >= 3, \
                f"字幕块 {i+1} 的行数不足：期望至少 3 行，实际 {len(lines)} 行"
            
            # 验证序号
            assert lines[0].strip() == str(i + 1), \
                f"字幕块 {i+1} 的序号不正确：期望 {i+1}，实际 {lines[0].strip()}"
            
            # 验证时间轴格式
            timeline = lines[1].strip()
            assert ' --> ' in timeline, \
                f"字幕块 {i+1} 的时间轴格式不正确：缺少 ' --> '"
            
            start_time, end_time = timeline.split(' --> ')
            
            # 验证时间格式（HH:MM:SS,mmm）
            import re
            time_pattern = r'^\d{2}:\d{2}:\d{2},\d{3}$'
            assert re.match(time_pattern, start_time), \
                f"字幕块 {i+1} 的开始时间格式不正确：{start_time}"
            assert re.match(time_pattern, end_time), \
                f"字幕块 {i+1} 的结束时间格式不正确：{end_time}"
            
            # 验证文本内容
            text = '\n'.join(lines[2:])
            assert text.strip(), \
                f"字幕块 {i+1} 的文本内容为空"
    
    @given(
        text_length=st.integers(min_value=1, max_value=200),
        max_chars_per_line=st.integers(min_value=10, max_value=50)
    )
    @settings(max_examples=15, deadline=2000)
    def test_property_text_splitting_consistency(self, text_length, max_chars_per_line):
        """
        属性：文本分割一致性
        
        验证：
        1. 分割后的每行长度不超过最大字符数
        2. 分割后的总字符数等于原始字符数（不包括换行符）
        3. 分割不会破坏单词（对于中文，每个字符都是独立的）
        """
        # 生成测试文本
        text = "测" * text_length
        
        # 分割文本
        lines = self.generator._split_text(text, max_chars_per_line=max_chars_per_line)
        
        # 验证每行长度
        for i, line in enumerate(lines):
            assert len(line) <= max_chars_per_line, \
                f"第 {i+1} 行的长度 ({len(line)}) 超过最大字符数 ({max_chars_per_line})"
        
        # 验证总字符数
        total_chars = sum(len(line) for line in lines)
        assert total_chars == text_length, \
            f"分割后的总字符数 ({total_chars}) 不等于原始字符数 ({text_length})"
        
        # 验证拼接后的文本
        joined_text = ''.join(lines)
        assert joined_text == text, \
            "分割后拼接的文本与原始文本不一致"
    
    @given(
        num_subtitles=st.integers(min_value=2, max_value=10)
    )
    @settings(max_examples=10, deadline=2000)
    def test_property_subtitle_timing_monotonic(self, num_subtitles):
        """
        属性：字幕时间单调递增
        
        验证：
        1. 字幕的开始时间单调递增
        2. 字幕的结束时间单调递增
        3. 任何字幕的开始时间都不早于前一个字幕的开始时间
        """
        # 生成测试数据
        subtitles = [f"字幕 {i+1}" for i in range(num_subtitles)]
        
        # 计算时间轴
        timings = self.generator.calculate_timing(subtitles)
        
        # 提取开始时间和结束时间
        start_times = [start for start, _ in timings]
        end_times = [end for _, end in timings]
        
        # 验证开始时间单调递增
        for i in range(1, len(start_times)):
            assert start_times[i] >= start_times[i-1], \
                f"开始时间不是单调递增：{start_times[i-1]} -> {start_times[i]}"
        
        # 验证结束时间单调递增
        for i in range(1, len(end_times)):
            assert end_times[i] >= end_times[i-1], \
                f"结束时间不是单调递增：{end_times[i-1]} -> {end_times[i]}"
    
    @given(
        audio_duration=st.floats(min_value=1.0, max_value=60.0),
        num_subtitles=st.integers(min_value=1, max_value=20)
    )
    @settings(max_examples=10, deadline=2000)
    def test_property_subtitle_duration_within_audio(self, audio_duration, num_subtitles):
        """
        属性：字幕时长不超过音频时长
        
        验证：
        1. 所有字幕的结束时间不超过音频时长
        2. 字幕均匀分布在音频时长内
        """
        # 生成测试数据
        subtitles = [f"字幕 {i+1}" for i in range(num_subtitles)]
        
        # Mock 音频时长
        with patch.object(self.generator, '_get_audio_duration', return_value=audio_duration):
            # 计算时间轴（基于音频时长）
            audio_path = "dummy_audio.mp3"
            timings = self.generator.calculate_timing(subtitles, audio_path=audio_path)
        
        # 验证所有字幕的结束时间
        for i, (start, end) in enumerate(timings):
            assert end <= audio_duration, \
                f"字幕 {i+1} 的结束时间 ({end}) 超过音频时长 ({audio_duration})"
            
            assert start < audio_duration, \
                f"字幕 {i+1} 的开始时间 ({start}) 超过音频时长 ({audio_duration})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
