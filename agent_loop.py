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


# ── The core pattern: a while loop that calls tools until the model stops ──
rounds_since_todo = 0


def agent_loop(messages: list):
    global rounds_since_todo
    reactive_retries = 0  # 跟踪 reactive_compact 重试次数

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

        # ── LLM 调用（带应急压缩重试） ────────────────────────
        try:
            # s09: 如果有记忆，临时注入到请求中
            request_messages = messages
            if memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                request_messages[memory_turn] = {
                    **messages[memory_turn],
                    "content": memories_content + "\n\n" + messages[memory_turn]["content"],
                }

            response = client.messages.create(
                model=MODEL, system=system, messages=request_messages,
                tools=TOOLS, max_tokens=8000,
            )
            reactive_retries = 0  # 成功后重置

        except Exception as e:
            # 检查是否是 prompt_too_long 错误
            error_message = str(e).lower()
            if "prompt" in error_message and ("too long" in error_message or "too large" in error_message or "413" in error_message):
                if reactive_retries < MAX_REACTIVE_RETRIES:
                    messages[:] = reactive_compact(messages)
                    reactive_retries += 1
                    continue  # 重试
                else:
                    print(f"\033[31m[ERROR] Reactive compact 重试次数超限，停止\033[0m")
                    raise
            else:
                # 其他错误直接抛出
                raise

        # ── 处理响应 ──────────────────────────────────────────
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
