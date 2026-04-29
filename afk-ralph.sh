#!/bin/bash
# afk-ralph.sh - Ralph 循环控制脚本

set -e

SPEC_DIR=".kiro/specs/ai-short-drama-production"
MAX_ITERATIONS=${1:-50}

echo "START afk-ralph.sh"
echo "最大迭代次数: ${MAX_ITERATIONS}"

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
   - 运行测试验证（如果任务要求）
   - 提交变更到 git
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
- 函数必须添加文档字符串说明功能、参数和返回值

## 完成标志

- 仅在所有任务完成时输出 <promise>COMPLETE</promise>
- 如果 tasks.md 中仍有未完成任务 [ ]，则绝对不要输出 <promise>COMPLETE</promise>
PROMPT
}

# 主循环
for ((i=1; i<=${MAX_ITERATIONS}; i++)); do
  echo ""
  echo "=========================================="
  echo "循环迭代 $i / ${MAX_ITERATIONS}"
  echo "=========================================="
  
  # 读取三种规范和 progress.txt
  req="$(cat "${SPEC_DIR}/requirements.md")"
  des="$(cat "${SPEC_DIR}/design.md")"
  tasks="$(cat "${SPEC_DIR}/tasks.md")"
  progress="$(cat progress.txt 2>/dev/null || echo '尚无进度')"
  
  # 将占位符替换为实际内容
  prompt="$(build_prompt)"
  prompt="${prompt/__REQ__/$req}"
  prompt="${prompt/__DES__/$des}"
  prompt="${prompt/__TASKS__/$tasks}"
  prompt="${prompt/__PROGRESS__/$progress}"
  
  # 执行 Kiro CLI（这里使用交互模式，因为我们在 Kiro 内部）
  # 在实际的 devcontainer 环境中，应该使用：
  # logfile="/tmp/kiro-iteration-${i}.log"
  # kiro-cli chat --no-interactive --trust-all-tools "$prompt" 2>&1 | tee "$logfile"
  
  echo "提示已准备好，等待执行..."
  echo "$prompt" > "/tmp/ralph-prompt-${i}.txt"
  
  # 检查未完成任务数量
  uncompleted=$(grep -cE '^\- \[ \]' "${SPEC_DIR}/tasks.md" 2>/dev/null || echo "0")
  
  echo "未完成任务数: $uncompleted"
  
  if [ "$uncompleted" -eq 0 ]; then
    echo "所有任务已完成！总迭代次数: $i"
    exit 0
  fi
  
  # 在实际环境中，这里会检查 COMPLETE 标志
  # has_promise=$(grep -q "<promise>COMPLETE</promise>" "$logfile" && echo "yes" || echo "no")
  # if [ "$uncompleted" -eq 0 ] && [ "$has_promise" = "yes" ]; then
  #   echo "All tasks verified complete after $i iterations."
  #   exit 0
  # fi
  
  # 暂停以便手动执行（在实际自动化环境中删除此行）
  echo "请手动执行任务，完成后按 Enter 继续..."
  read -r
done

echo "达到最大迭代次数 ${MAX_ITERATIONS}，停止执行"
echo "剩余未完成任务: $uncompleted"
