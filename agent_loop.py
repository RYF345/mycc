#!/usr/bin/env python3
"""
agent_loop.py - The Agent Loop

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

Usage:
    pip install anthropic python-dotenv
    ANTHROPIC_API_KEY=... python agent_loop.py
"""

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from config import client, MODEL
from Tools.tools import TOOLS, TOOL_HANDLERS
from skill_using import list_skills
from hooks import trigger_hooks
from config import WORKDIR
import Tools.sub_agent_tool  # Register task tool

# 导入 Memory 功能
from memory import load_memories, extract_memories, consolidate_memories, MEMORY_INDEX

# 导入压缩功能
from compact import (
    estimate_token_count,
    snip_compact,
    micro_compact,
    tool_result_budget,
    compact_history,
    reactive_compact,
    TOKEN_THRESHOLD,
    MAX_REACTIVE_RETRIES
)

import json
import time
import random
import os

# ── Error Recovery Constants (s11) ──────────────────────

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 64000
MAX_RETRIES = 10
BASE_DELAY_MS = 500
MAX_CONSECUTIVE_529 = 3
MAX_RECOVERY_RETRIES = 3
CONTINUATION_PROMPT = (
    "Output token limit hit. Resume directly — no apology, no recap. "
    "Pick up mid-thought."
)

# 备用模型（可选，从环境变量读取）
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID", "")
PRIMARY_MODEL = MODEL  # 保存原始模型

# ── Prompt Sections ──────────────────────────────────────

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "workspace": f"Working directory: {WORKDIR}",
    "tools": "Use available tools to complete tasks.",
    "skills_template": "Skills available:\n{catalog}\nUse load_skill to get full details when needed.",
    "memory_template": "Memory Index:\n{content}",
}


def assemble_system_prompt(context: dict) -> str:
    """
    根据 context 动态选择并拼接 prompt sections

    Args:
        context: 包含当前状态的字典
            - skills_catalog: 技能目录字符串（可选）
            - memory_index: 记忆索引内容（可选）

    Returns:
        拼接后的 system prompt 字符串

    业务逻辑：
    1. 始终加载：identity、workspace、tools
    2. 按需加载：
       - 如果 context 中有 skills_catalog，加载 skills section
       - 如果 context 中有 memory_index，加载 memory section
    3. 用 "\n\n" 连接所有 sections
    """
    sections = []

    # 始终加载
    sections.append(PROMPT_SECTIONS["identity"])
    sections.append(PROMPT_SECTIONS["workspace"])
    sections.append(PROMPT_SECTIONS["tools"])

    # 按需加载 - skills
    skills_catalog = context.get("skills_catalog", "")
    if skills_catalog:
        sections.append(PROMPT_SECTIONS["skills_template"].format(catalog=skills_catalog))

    # 按需加载 - memory
    memory_index = context.get("memory_index", "")
    if memory_index:
        sections.append(PROMPT_SECTIONS["memory_template"].format(content=memory_index))

    return "\n\n".join(sections)


def update_context(context: dict, messages: list) -> dict:
    """
    从真实状态更新 context

    Args:
        context: 当前 context（可能为空）
        messages: 对话历史（未使用，保留以备后续扩展）

    Returns:
        更新后的 context 字典

    业务逻辑：
    1. 读取技能目录（通过 list_skills()）
    2. 检查记忆索引文件是否存在且有内容
    3. 返回包含实际状态的 context 字典

    为什么基于真实状态而不是关键词：
    - 文件可能在对话中被创建或删除
    - 不依赖消息内容，避免误判
    - 保证 system prompt 反映当前真实环境
    """
    # 读取技能目录
    skills_catalog = list_skills()

    # 检查记忆索引文件
    memory_index = ""
    if MEMORY_INDEX.exists():
        content = MEMORY_INDEX.read_text(encoding="utf-8").strip()
        if content:
            memory_index = content

    return {
        "skills_catalog": skills_catalog,
        "memory_index": memory_index,
    }


# ── Caching ──────────────────────────────────────────────

_last_context_key = None
_last_prompt = None


def get_system_prompt(context: dict) -> str:
    """
    缓存包装器 - 只在 context 变化时重新组装

    Args:
        context: 当前状态字典

    Returns:
        组装好的 system prompt

    业务逻辑：
    1. 使用 json.dumps 将 context 序列化为确定性字符串作为 cache key
    2. 如果 key 与上次相同，返回缓存的 prompt（避免重复拼接）
    3. 如果 key 不同，调用 assemble_system_prompt() 重新组装
    4. 更新缓存并返回新 prompt

    为什么用 json.dumps 而不是 hash()：
    - Python 的 hash() 有进程随机化（PYTHONHASHSEED）
    - hash() 对 dict/list 会报错 "unhashable type"
    - json.dumps(sort_keys=True) 保证相同内容产生相同字符串

    注意：
    - 这个缓存只避免字符串拼接的重复计算（进程内优化）
    - 与 Claude API 的 prompt cache 无关（那是服务端缓存）
    """
    global _last_context_key, _last_prompt

    # 生成确定性 cache key
    key = json.dumps(context, sort_keys=True, ensure_ascii=False)

    # 检查缓存
    if key == _last_context_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt unchanged\033[0m")
        return _last_prompt

    # 缓存未命中，重新组装
    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)

    # 打印加载的 sections（调试信息）
    loaded = ["identity", "workspace", "tools"]
    if context.get("skills_catalog"):
        loaded.append("skills")
    if context.get("memory_index"):
        loaded.append("memory")
    print(f"  \033[32m[assembled] sections: {', '.join(loaded)}\033[0m")

    return _last_prompt


# ── Error Recovery (s11) ─────────────────────────────────

class RecoveryState:
    """
    跟踪恢复尝试状态

    属性说明：
    - has_escalated: 是否已将 max_tokens 从 8K 升级到 64K（只升级一次）
    - recovery_count: 输出截断续写的次数（最多 3 次）
    - consecutive_529: 连续 529 错误的次数（达到 3 次切换备用模型）
    - has_attempted_reactive_compact: 是否已尝试过应急压缩（只尝试一次）
    - current_model: 当前使用的模型 ID（可能从 PRIMARY_MODEL 切换到 FALLBACK_MODEL）

    业务逻辑：
    - 每个 agent_loop 调用创建一个 RecoveryState 实例
    - 在整个对话循环中保持状态，避免重复恢复动作
    - has_escalated 和 has_attempted_reactive_compact 确保每种恢复只尝试一次
    - recovery_count 和 consecutive_529 用于计数限制
    - current_model 支持动态切换模型
    """
    def __init__(self):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = PRIMARY_MODEL


def retry_delay(attempt: int, retry_after: int | None = None) -> float:
    """
    计算指数退避延迟（带随机抖动）

    Args:
        attempt: 重试次数（从 0 开始）
        retry_after: 服务器返回的 Retry-After 值（秒），优先使用

    Returns:
        延迟秒数（浮点数）

    业务逻辑：
    1. 如果服务器返回 Retry-After header，直接使用该值
    2. 否则使用指数退避公式：base = min(500 × 2^attempt, 32000) ms
    3. 添加随机抖动：0 到 base 的 25%
    4. 返回秒数（base + jitter）/ 1000

    指数退避表：
    - 尝试 0: 500ms + 0-125ms = 500-625ms
    - 尝试 1: 1000ms + 0-250ms = 1000-1250ms
    - 尝试 2: 2000ms + 0-500ms = 2000-2500ms
    - 尝试 3: 4000ms + 0-1000ms = 4000-5000ms
    - 尝试 4: 8000ms + 0-2000ms = 8000-10000ms
    - 尝试 5: 16000ms + 0-4000ms = 16000-20000ms
    - 尝试 6+: 32000ms + 0-8000ms = 32000-40000ms (上限)

    为什么需要抖动：
    - 避免并发请求在同一时刻重试（thundering herd problem）
    - 分散重试流量，减少服务器压力
    - 25% 的抖动范围是工程经验值
    """
    if retry_after:
        return retry_after

    # 指数退避：500 × 2^attempt，上限 32000 毫秒
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000  # 转换为秒

    # 随机抖动：0 到 base 的 25%
    jitter = random.uniform(0, base * 0.25)

    return base + jitter


def is_prompt_too_long_error(e: Exception) -> bool:
    """
    检查异常是否为上下文超限错误

    Args:
        e: API 调用抛出的异常

    Returns:
        True 如果是上下文超限错误，False 否则

    业务逻辑：
    1. 将异常消息转换为小写字符串
    2. 检查是否包含以下关键词组合：
       - "prompt" + "long": prompt 太长
       - "prompt_is_too_long": Claude API 的具体错误类型
       - "context_length_exceeded": 超出上下文长度限制
       - "max_context_window": 超出最大上下文窗口
    3. 满足任一条件即判定为上下文超限错误

    为什么需要多种模式匹配：
    - 不同 API 版本可能返回不同的错误消息
    - 不同云服务商（AWS Bedrock、GCP Vertex AI）可能用不同表述
    - 错误消息可能变化，多种模式提高鲁棒性

    与 compact.py 中 reactive_compact 的关系：
    - 当前项目已有 reactive_compact 实现（在 compact.py 中）
    - 本函数用于判断何时触发 reactive_compact
    - 如果检测到上下文超限，agent_loop 会调用 reactive_compact
    """
    try:
        msg = str(e).lower()
    except:
        msg = repr(e).lower()
    return (("prompt" in msg and "long" in msg)
            or "prompt_is_too_long" in msg
            or "context_length_exceeded" in msg
            or "max_context_window" in msg)


def with_retry(fn, state: RecoveryState):
    """
    指数退避重试包装器，处理瞬态错误（429 限流、529 过载）

    Args:
        fn: 要执行的函数（通常是 lambda: client.messages.create(...)）
        state: RecoveryState 实例，跟踪连续 529 错误和当前模型

    Returns:
        fn() 的返回值（成功时）

    Raises:
        RuntimeError: 超过最大重试次数
        Exception: 非瞬态错误直接抛出给外层处理

    业务逻辑：
    1. 尝试执行 fn()，最多 MAX_RETRIES 次（10 次）
    2. 成功时：重置 consecutive_529 计数器，返回结果
    3. 遇到 429 错误：
       - 打印重试信息
       - 使用 retry_delay() 计算延迟
       - sleep 后继续重试
    4. 遇到 529 错误：
       - consecutive_529 计数器 +1
       - 如果连续 3 次 529 且配置了 FALLBACK_MODEL：
         * 切换到 FALLBACK_MODEL
         * 重置 consecutive_529 计数器
         * 打印模型切换信息
       - 使用 retry_delay() 计算延迟
       - sleep 后继续重试
    5. 遇到其他错误：直接 raise 给外层 try/except 处理
    6. 超过最大重试次数：raise RuntimeError

    为什么 429 和 529 是瞬态错误：
    - 429 Rate Limit：请求频率太高，等待后可恢复
    - 529 Overloaded：服务器过载，等待后可恢复
    - 其他错误（如 prompt_too_long）不是瞬态的，需要改变请求本身

    为什么需要 consecutive_529 计数：
    - 偶尔一次 529 是正常的（流量波动）
    - 连续 3 次 529 说明主模型持续过载，需要切换到备用模型
    - 切换后重置计数，因为新模型可能有独立的容量
    """
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            # 成功：重置 529 计数器
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__
            try:
                msg = str(e).lower()
            except:
                msg = repr(e).lower()

            # 429 限流错误 -> 指数退避
            if "ratelimit" in name.lower() or "429" in msg:
                delay = retry_delay(attempt)
                print(f"  \033[33m[429 rate limit] retry {attempt+1}/{MAX_RETRIES},"
                      f" wait {delay:.1f}s\033[0m")
                time.sleep(delay)
                continue

            # 529 过载错误 -> 指数退避 + 可能切换模型
            if "overloaded" in name.lower() or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1

                # 连续 3 次 529 -> 切换备用模型
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    if FALLBACK_MODEL:
                        state.current_model = FALLBACK_MODEL
                        state.consecutive_529 = 0
                        print(f"  \033[31m[529 x{MAX_CONSECUTIVE_529}]"
                              f" switching to {FALLBACK_MODEL}\033[0m")
                    else:
                        # 没有配置备用模型，重置计数继续重试
                        state.consecutive_529 = 0
                        print(f"  \033[31m[529 x{MAX_CONSECUTIVE_529}]"
                              f" no FALLBACK_MODEL_ID configured, continuing retry\033[0m")

                delay = retry_delay(attempt)
                print(f"  \033[33m[529 overloaded] retry {attempt+1}/{MAX_RETRIES},"
                      f" wait {delay:.1f}s\033[0m")
                time.sleep(delay)
                continue

            # 非瞬态错误 -> 直接抛出给外层处理
            raise

    # 超过最大重试次数
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")


# ── The core pattern: a while loop that calls tools until the model stops ──
rounds_since_todo = 0


def agent_loop(messages: list):
    global rounds_since_todo

    # ── s11: 创建恢复状态和初始 max_tokens ─────────────
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    # ── s10: 初始化 context 并组装 system prompt ────────
    context = update_context({}, messages)
    system = get_system_prompt(context)

    # ── s09: 加载相关记忆 ──────────────────────────────
    memories_content = load_memories(messages)
    memory_turn = len(messages) - 1 if messages and isinstance(messages[-1].get("content"), str) else None

    while True:
        # ── s09: 保存压缩前快照（用于准确提取记忆）────────
        pre_compress = [m.copy() if isinstance(m, dict) else m for m in messages]
        # ── 压缩管线：每轮 LLM 调用前执行 ────────────────────
        # L3: 大结果落盘（必须最先执行，在 micro_compact 之前）
        messages[:] = tool_result_budget(messages)

        # L1: 裁掉中间消息
        messages[:] = snip_compact(messages)

        # L2: 旧工具结果占位
        messages[:] = micro_compact(messages)

        # L4: 如果 token 仍然超阈值，触发 LLM 摘要
        if estimate_token_count(messages) > TOKEN_THRESHOLD:
            messages[:] = compact_history(messages)

        # ── Todo 提醒 ─────────────────────────────────────────
        if rounds_since_todo >= 3 and messages:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0

        # ── s11: LLM 调用（with_retry 处理 429/529） ─────────
        try:
            # s09: 如果有记忆，临时注入到请求中
            request_messages = messages
            if memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                original_content = messages[memory_turn]["content"]

                # 安全处理 content：可能是字符串或列表
                if isinstance(original_content, str):
                    # content 是字符串，直接拼接
                    new_content = memories_content + "\n\n" + original_content
                elif isinstance(original_content, list):
                    # content 是列表（工具结果），将记忆作为第一个文本块
                    new_content = [{"type": "text", "text": memories_content}] + original_content
                else:
                    # 其他情况，保持原样（不注入记忆）
                    new_content = original_content

                request_messages[memory_turn] = {
                    **messages[memory_turn],
                    "content": new_content,
                }

            # with_retry 处理瞬态错误（429/529）
            response = with_retry(
                lambda: client.messages.create(
                    model=state.current_model,  # 使用 state 中的模型（可能切换）
                    system=system,
                    messages=request_messages,
                    tools=TOOLS,
                    max_tokens=max_tokens,  # 使用变量（可能升级）
                ),
                state
            )

        except Exception as e:
            # ── 路径 2: prompt_too_long -> reactive compact (一次) ──
            if is_prompt_too_long_error(e):
                if not state.has_attempted_reactive_compact:
                    messages[:] = reactive_compact(messages)
                    state.has_attempted_reactive_compact = True
                    continue  # 重试
                # 压缩后还是超限，无法恢复
                print("  \033[31m[unrecoverable] still too long after compact\033[0m")
                messages.append({"role": "assistant", "content": [
                    {"type": "text",
                     "text": "[Error] Context too large, cannot continue."}]})
                return

            # ── 其他不可恢复错误 ──────────────────────────────
            name = type(e).__name__
            try:
                error_msg = str(e)
            except:
                error_msg = repr(e)
            print(f"  \033[31m[unrecoverable] {name}: {error_msg[:100]}\033[0m")
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {name}: {error_msg[:200]}"}]})
            return

        # ── 路径 1: max_tokens -> 升级或续写 ──────────────────
        if response.stop_reason == "max_tokens":
            # 第一次截断：升级到 64K，不追加截断内容，重试相同请求
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"  \033[33m[max_tokens] escalating"
                      f" {DEFAULT_MAX_TOKENS} -> {ESCALATED_MAX_TOKENS}\033[0m")
                continue  # messages 不变，用更大 max_tokens 重试

            # 64K 还是截断：保存截断内容 + 续写提示
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                print(f"  \033[33m[max_tokens] continuation"
                      f" {state.recovery_count}/{MAX_RECOVERY_RETRIES}\033[0m")
                continue
            # 续写 3 次后还是截断，放弃
            print("  \033[31m[max_tokens] recovery limit reached\033[0m")
            return

        # ── 正常完成：追加响应 ────────────────────────────────
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # s09: 从压缩前快照提取记忆
            extract_memories(pre_compress)
            consolidate_memories()

            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return

        # ── 执行工具 ──────────────────────────────────────────
        rounds_since_todo += 1
        results = []
        compacted = False  # 标记是否执行了 compact

        for block in response.content:
            if block.type != "tool_use":
                continue

            # ── 特殊处理：compact 工具 ────────────────────────
            if block.name == "compact":
                messages[:] = compact_history(messages)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "[Compacted. History summarized.]"})
                compacted = True
                break  # 结束当前工具执行，不再执行其他工具

            # ── 特殊处理：debug_messages 工具 ─────────────────
            if block.name == "debug_messages":
                # 统计消息信息
                msg_count = len(messages)
                tool_result_count = sum(
                    1 for m in messages
                    for b in (m.get("content", []) if isinstance(m.get("content"), list) else [])
                    if isinstance(b, dict) and b.get("type") == "tool_result"
                )

                # 最近 5 条消息的简要信息
                recent = []
                for msg in messages[-5:]:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        preview = content[:80]
                    elif isinstance(content, list):
                        preview = f"[{len(content)} blocks]"
                    else:
                        preview = str(content)[:80]
                    recent.append(f"{role}: {preview}")

                debug_info = f"""📊 当前消息统计：
- 总消息数: {msg_count}
- 工具结果数: {tool_result_count}
- 估算 token: {estimate_token_count(messages):,}
- 阈值: {TOKEN_THRESHOLD:,}

最近 5 条消息:
{chr(10).join(f"  {r}" for r in recent)}"""

                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": debug_info})
                continue  # 继续执行其他工具

            # ── 正常工具处理 ──────────────────────────────────
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown: {block.name}"

            trigger_hooks("PostToolUse", block, output)

            if block.name == "todo_write":
                rounds_since_todo = 0

            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": results})

        # ── s10: 重新评估 context 和 prompt ──────────────
        # 工具执行后可能改变了状态（创建记忆、添加技能等）
        context = update_context(context, messages)
        system = get_system_prompt(context)

        # 如果执行了 compact，立即开始新一轮（用压缩后的上下文）
        if compacted:
            continue


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("Agent Loop")
    print("输入问题，回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            query = input("\033[36m>> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
