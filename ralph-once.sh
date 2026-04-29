#!/bin/bash
# ralph-once.sh - 单次 Ralph 循环执行脚本

set -e

SPEC_DIR=".kiro/specs/ai-short-drama-production"

# 构建提示模板
build_prompt() {
  cat <<'PROMPT'
【需求】
__REQ__

【设计】
__DES__

【任务列表】
__TASKS__

【进度】
__PROGRESS__

## 执行指令

1. 理解需求和设计文档
2. 查看任务列表和进度，找出下一个未完成的任务（标记为 [ ]）
3. 执行该任务：
   - 阅读相关代码文件
   - 实现功能
   - 运行测试验证
   - 提交变更
4. 完成后，将 tasks.md 中的复选框从 [ ] 更新为 [x]（必需）
5. 将完成的内容附加到 progress.txt 中（必需）

## 重要约束

- 每次执行仅实现一个任务
- 禁止使用 npm run test。必须使用 npm run test:unit 或 npm run test -- --run
- 禁止常驻进程，必须只执行一次即可结束的命令
- 禁止使用 npm run dev、yarn start 等开发服务器命令
- 测试命令必须使用 --run 标志以避免 watch 模式
- 所有代码使用中文注释
- 遵循 4 空格缩进规范
- 使用驼峰命名法（变量/函数）和大驼峰命名法（类）

## 完成标志

- 仅在所有任务完成时输出 <promise>COMPLETE</promise>
- 如果 tasks.md 中仍有未完成任务 [ ]，则绝对不要输出 <promise>COMPLETE</promise>
PROMPT
}

# 读取规范文件
req="$(cat "${SPEC_DIR}/requirements.md")"
des="$(cat "${SPEC_DIR}/design.md")"
tasks="$(cat "${SPEC_DIR}/tasks.md")"
progress="$(cat progress.txt 2>/dev/null || echo '尚无进度')"

# 构建完整提示
prompt="$(build_prompt)"
prompt="${prompt/__REQ__/$req}"
prompt="${prompt/__DES__/$des}"
prompt="${prompt/__TASKS__/$tasks}"
prompt="${prompt/__PROGRESS__/$progress}"

# 输出提示（用于调试）
echo "$prompt"
