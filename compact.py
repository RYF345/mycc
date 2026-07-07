"""
compact.py - Context Compaction System

四层压缩策略：
- L1 (snip_compact): 裁掉无关的旧对话
- L2 (micro_compact): 旧工具结果占位
- L3 (tool_result_budget): 大结果落盘
- L4 (compact_history): LLM 全量摘要
- 应急 (reactive_compact): API 报错时应急裁剪
"""

import json
import time
from pathlib import Path
from config import client, MODEL, WORKDIR

# ── 压缩相关常量 ──────────────────────────────────────────
MAX_MESSAGES = 50  # snip_compact 保留的最大消息数
KEEP_RECENT_TOOL_RESULTS = 3  # micro_compact 保留最近几条完整结果
TOOL_RESULT_BUDGET_BYTES = 200_000  # tool_result_budget 的字节限制
TOKEN_THRESHOLD = 150_000  # 触发 compact_history 的 token 阈值
MAX_REACTIVE_RETRIES = 1  # reactive_compact 最大重试次数
MAX_COMPACT_FAILURES = 3  # compact_history 连续失败熔断器

# ── 目录设置 ──────────────────────────────────────────────
TASK_OUTPUTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
TRANSCRIPTS_DIR = WORKDIR / ".transcripts"

# 创建必要的目录
TASK_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# ── 全局状态 ──────────────────────────────────────────────
compact_failure_count = 0  # 跟踪连续失败次数


# ── 辅助函数 ──────────────────────────────────────────────
def estimate_token_count(messages: list) -> int:
    """
    粗略估算消息列表的 token 数量

    业务逻辑：
    - 将所有消息内容序列化为 JSON 字符串
    - 使用简单的字符数除以 3 来估算 token 数（英文约 4 字符/token，中文约 2 字符/token）
    - 这是快速估算，不需要精确的 tokenizer

    Args:
        messages: 消息列表

    Returns:
        估算的 token 数量
    """
    total_chars = len(json.dumps(messages, ensure_ascii=False))
    return total_chars // 3


def _message_has_tool_use(message: dict) -> bool:
    """
    检查消息是否包含 tool_use

    业务逻辑：
    - assistant 消息的 content 可能是列表，包含多个 block
    - 遍历 content，查找是否有 type 为 "tool_use" 的 block

    Args:
        message: 单条消息

    Returns:
        True 如果消息包含 tool_use
    """
    if message.get("role") != "assistant":
        return False
    content = message.get("content", [])
    if not isinstance(content, list):
        return False
    return any(block.get("type") == "tool_use" for block in content if isinstance(block, dict))


def _is_tool_result_message(message: dict) -> bool:
    """
    检查消息是否是 tool_result 消息

    业务逻辑：
    - user 消息的 content 可能是列表，包含 tool_result blocks
    - 检查是否所有 block 都是 tool_result 类型

    Args:
        message: 单条消息

    Returns:
        True 如果消息是 tool_result 消息
    """
    if message.get("role") != "user":
        return False
    content = message.get("content", [])
    if not isinstance(content, list):
        return False
    return len(content) > 0 and all(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


# ── L1: snip_compact ──────────────────────────────────────
def snip_compact(messages: list, max_messages: int = MAX_MESSAGES) -> list:
    """
    L1: 裁掉无关的旧对话

    业务逻辑：
    - 如果消息数 <= max_messages，不做处理
    - 保留头部 3 条消息（初始上下文）
    - 保留尾部 (max_messages - 3) 条消息（当前工作）
    - 中间部分用占位符替换
    - 边界保护：不能把 tool_use 和后续的 tool_result 拆开

    边界处理：
    - 如果 head_end - 1 位置有 tool_use，需要向后扩展包含所有对应的 tool_result
    - 如果 tail_start 位置是 tool_result，需要向前扩展包含对应的 tool_use

    Args:
        messages: 原始消息列表
        max_messages: 最大保留消息数

    Returns:
        压缩后的消息列表
    """
    if len(messages) <= max_messages:
        return messages

    # 保留头部 3 条，尾部 (max_messages - 3) 条
    head_end = 3
    tail_start = len(messages) - (max_messages - 3)

    # 边界保护：head_end 位置的前一条消息如果有 tool_use，需要包含后续的 tool_result
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1

    # 边界保护：tail_start 位置如果是 tool_result，需要包含前面的 tool_use
    if tail_start > 0 and _is_tool_result_message(messages[tail_start]) and _message_has_tool_use(messages[tail_start - 1]):
        tail_start -= 1

    # 计算裁掉的消息数
    snipped = tail_start - head_end
    if snipped <= 0:
        return messages

    # 创建占位符消息
    placeholder = {
        "role": "user",
        "content": f"[snipped {snipped} messages from conversation middle]"
    }

    print(f"\033[90m[COMPACT] snip_compact: 裁掉中间 {snipped} 条消息\033[0m")

    return messages[:head_end] + [placeholder] + messages[tail_start:]


# ── L2: micro_compact ──────────────────────────────────────
def micro_compact(messages: list) -> list:
    """
    L2: 旧工具结果占位

    业务逻辑：
    - 收集所有 tool_result blocks（按顺序）
    - 只保留最近 KEEP_RECENT_TOOL_RESULTS 条的完整内容
    - 更旧的 tool_result 如果内容超过 120 字符，替换为占位符
    - 模型看到占位符后知道这是旧结果，如果需要可以重新调用工具

    实现细节：
    - 遍历所有消息，找到 tool_result blocks
    - 记录每个 block 的位置（message_idx, block_idx）
    - 对倒数第 KEEP_RECENT_TOOL_RESULTS 之前的 blocks 进行占位符替换

    TODO: 增强版 - 在占位符中包含工具名称和参数
    - 通过 tool_use_id 回溯找到对应的 tool_use
    - 提取工具名称和参数信息
    - 占位符格式: "[Earlier tool result compacted. Original call: read_file(path='test.py'). Re-run if needed.]"
    - 这样 AI 可以知道如何重新调用工具

    Args:
        messages: 消息列表

    Returns:
        压缩后的消息列表
    """
    # 收集所有 tool_result blocks 的位置
    tool_results = []
    for msg_idx, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block_idx, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_results.append((msg_idx, block_idx, block))

    # 如果 tool_result 数量 <= 保留数量，不做处理
    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages

    # 对旧的 tool_result 进行占位符替换
    compacted_count = 0
    for msg_idx, block_idx, block in tool_results[:-KEEP_RECENT_TOOL_RESULTS]:
        content = str(block.get("content", ""))
        if len(content) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
            compacted_count += 1

    if compacted_count > 0:
        print(f"\033[90m[COMPACT] micro_compact: 压缩了 {compacted_count} 条旧工具结果\033[0m")

    return messages


# ── L3: tool_result_budget 辅助函数 ───────────────────────
def persist_large_output(tool_use_id: str, content: str) -> str:
    """
    将大的工具结果持久化到磁盘

    业务逻辑：
    - 为每个大工具结果创建一个文件
    - 文件名使用 tool_use_id 确保唯一性
    - 返回包含文件路径和内容预览的占位符
    - AI 看到 <persisted-output> 标记后知道完整内容在磁盘上

    Args:
        tool_use_id: 工具调用的唯一 ID
        content: 工具结果的完整内容

    Returns:
        占位符字符串，包含文件路径和前 2000 字符的预览
    """
    # 创建文件名（基于 tool_use_id）
    filename = f"{tool_use_id}.txt"
    filepath = TASK_OUTPUTS_DIR / filename

    # 写入完整内容到磁盘
    filepath.write_text(content, encoding="utf-8")

    # 返回占位符：文件路径 + 前 2000 字符预览
    preview = content[:2000]
    if len(content) > 2000:
        preview += f"\n... ({len(content) - 2000} more chars)"

    placeholder = (
        f"<persisted-output path='{filepath.relative_to(WORKDIR)}'>\n"
        f"{preview}\n"
        f"</persisted-output>"
    )

    return placeholder
