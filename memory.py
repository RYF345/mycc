#!/usr/bin/env python3
"""
memory.py - Memory Management System

跨会话、跨压缩的知识存储系统。
"""

import json
import re
from pathlib import Path

from config import WORKDIR, client, MODEL

# ── 配置 ──────────────────────────────────────────────
MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
CONSOLIDATE_THRESHOLD = 15

# 确保目录存在
MEMORY_DIR.mkdir(exist_ok=True)


# ── 存储层：写入记忆文件 ──────────────────────────────
def write_memory_file(name: str, mem_type: str, description: str, body: str) -> str:
    """
    写入一个记忆文件

    Args:
        name: 记忆名称（kebab-case slug）
        mem_type: 记忆类型（user/feedback/project/reference）
        description: 一行描述
        body: 记忆内容

    Returns:
        写入的文件路径

    业务逻辑：
    1. 将 name 转换为 kebab-case 文件名
    2. 构建 YAML frontmatter（name/description/type）
    3. 写入 .memory/<slug>.md
    4. 自动重建索引（调用 _rebuild_index()）
    """
    # 转换为 kebab-case
    slug = name.lower().replace(" ", "-").replace("_", "-")
    # 移除非法字符
    slug = re.sub(r'[^a-z0-9-]', '', slug)

    filepath = MEMORY_DIR / f"{slug}.md"

    # 构建文件内容（YAML frontmatter + body）
    content = f"""---
name: {name}
description: {description}
type: {mem_type}
---

{body.strip()}
"""

    filepath.write_text(content, encoding="utf-8")

    # 重建索引
    _rebuild_index()

    return str(filepath)


def list_memory_files() -> list:
    """
    列出所有记忆文件的元数据

    Returns:
        记忆文件列表，每个元素包含 filename/name/description/type

    业务逻辑：
    1. 遍历 .memory/*.md 文件（跳过 MEMORY.md）
    2. 读取并解析 YAML frontmatter
    3. 提取 name/description/type 字段
    4. 返回元数据列表
    """
    files = []

    if not MEMORY_DIR.exists():
        return files

    for filepath in MEMORY_DIR.glob("*.md"):
        # 跳过索引文件
        if filepath.name == "MEMORY.md":
            continue

        try:
            content = filepath.read_text(encoding="utf-8")

            # 解析 YAML frontmatter
            match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if not match:
                continue

            frontmatter = match.group(1)

            # 提取字段
            name = re.search(r'^name:\s*(.+)$', frontmatter, re.MULTILINE)
            description = re.search(r'^description:\s*(.+)$', frontmatter, re.MULTILINE)
            mem_type = re.search(r'^type:\s*(.+)$', frontmatter, re.MULTILINE)

            if name and description and mem_type:
                files.append({
                    "filename": filepath.name,
                    "name": name.group(1).strip(),
                    "description": description.group(1).strip(),
                    "type": mem_type.group(1).strip(),
                })

        except Exception as e:
            print(f"Warning: Failed to parse {filepath.name}: {e}")
            continue

    return files


def _rebuild_index():
    """
    重建 MEMORY.md 索引文件

    业务逻辑：
    1. 调用 list_memory_files() 获取所有记忆
    2. 如果没有记忆，创建空索引
    3. 如果有记忆，生成索引：每行 "- [name](filename.md) — description"
    4. 写入 MEMORY.md
    """
    files = list_memory_files()

    if not files:
        # 没有记忆文件，创建空索引
        MEMORY_INDEX.write_text("# Memory Index\n\nNo memories yet.\n", encoding="utf-8")
        return

    # 构建索引内容
    lines = ["# Memory Index\n"]
    for f in files:
        lines.append(f"- [{f['name']}]({f['filename']}) — {f['description']}")

    MEMORY_INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_memory_file(filename: str) -> str | None:
    """
    读取记忆文件的完整内容

    Args:
        filename: 文件名（不含路径），例如 "user-preference-tabs.md"

    Returns:
        文件内容字符串，如果文件不存在返回 None

    业务逻辑：
    1. 拼接完整路径 MEMORY_DIR / filename
    2. 检查文件是否存在
    3. 读取并返回文件内容
    """
    filepath = MEMORY_DIR / filename
    if not filepath.exists():
        return None

    try:
        return filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Warning: Failed to read {filename}: {e}")
        return None


# ── 辅助函数 ──────────────────────────────────────────
def _format_messages_for_query(messages: list) -> str:
    """
    格式化消息用于 query

    Args:
        messages: 消息列表

    Returns:
        格式化的文本，格式为 "role: content"

    业务逻辑：
    1. 遍历消息列表
    2. 提取 role 和 content
    3. 如果 content 是字符串，直接截取前 200 字符
    4. 如果 content 是列表（含 text blocks），提取所有 text 并拼接
    5. 返回 "role: content" 格式的多行文本
    """
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, str):
            lines.append(f"{role}: {content[:200]}")
        elif isinstance(content, list):
            # 提取 text blocks
            texts = [b.text for b in content if hasattr(b, "text")]
            if texts:
                lines.append(f"{role}: {' '.join(texts)[:200]}")

    return "\n".join(lines)


def _extract_text(content) -> str:
    """
    从 Claude response content 中提取文本

    Args:
        content: response.content（可能是 str, list, 或其他类型）

    Returns:
        提取的文本字符串

    业务逻辑：
    1. 如果是字符串，直接返回
    2. 如果是列表，提取所有 text block 并拼接
    3. 其他情况，转换为字符串返回
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for block in content:
            if hasattr(block, "text"):
                texts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                texts.append(block["text"])
        return " ".join(texts)

    return str(content)


# ── 加载层：选择相关记忆 ──────────────────────────────
def select_relevant_memories(messages: list, max_items: int = 5) -> list:
    """
    使用 LLM side-query 选择相关记忆文件

    Args:
        messages: 当前对话历史
        max_items: 最多返回的记忆数（默认 5）

    Returns:
        相关记忆的文件名列表，例如 ["user-preference-tabs.md", "feedback-no-mock.md"]

    业务逻辑：
    1. 获取所有记忆文件的元数据
    2. 提取最近 5 条对话作为上下文
    3. 构建记忆目录："0: name — description"
    4. 发送 side-query 给 LLM，要求返回相关记忆的索引 JSON 数组
    5. 解析 JSON，验证索引，返回文件名列表
    6. 如果失败（API错误或解析失败），降级到关键词匹配
    """
    files = list_memory_files()
    if not files:
        return []

    # 构建最近对话摘要（最近 5 条消息）
    recent_messages = messages[-5:] if len(messages) > 5 else messages
    recent_text = _format_messages_for_query(recent_messages)

    # 构建记忆目录："0: name — description"
    catalog = "\n".join(
        f"{i}: {f['name']} — {f['description']}"
        for i, f in enumerate(files)
    )

    # Side-query prompt
    prompt = f"""Based on the recent conversation, select relevant memory indices (0-{len(files)-1}).
Return a JSON array of indices, e.g., [0, 2, 5]. Maximum {max_items} items.
If nothing is relevant, return [].

Recent conversation:
{recent_text}

Memory catalog:
{catalog}
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        # 提取文本内容
        text = _extract_text(response.content).strip()

        # 解析 JSON 数组
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if not match:
            raise ValueError("No JSON array found in response")

        indices = json.loads(match.group())

        # 验证索引并返回文件名
        selected = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(files):
                selected.append(files[idx]["filename"])
            if len(selected) >= max_items:
                break

        return selected

    except Exception as e:
        print(f"[Memory] LLM selection failed ({e}), falling back to keyword matching")
        return select_relevant_memories_fallback(messages, max_items)


def select_relevant_memories_fallback(messages: list, max_items: int = 5) -> list:
    """
    关键词匹配降级方案

    Args:
        messages: 当前对话历史
        max_items: 最多返回的记忆数

    Returns:
        相关记忆的文件名列表

    业务逻辑：
    1. 提取最近对话中的关键词（至少 3 个字符）
    2. 去除常见停用词（the, a, and, or, ...）
    3. 对每个记忆文件，计算 name + description 中匹配的关键词数量
    4. 按匹配数降序排序，返回前 max_items 个（得分 > 0）
    """
    files = list_memory_files()
    if not files:
        return []

    # 提取最近对话文本
    recent_messages = messages[-5:] if len(messages) > 5 else messages
    recent_text = _format_messages_for_query(recent_messages).lower()

    # 简单关键词提取（去除常见停用词）
    stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
    keywords = set(re.findall(r'\b\w{3,}\b', recent_text))  # 至少 3 个字符
    keywords = keywords - stopwords

    # 计算每个记忆的相关性得分
    scores = []
    for f in files:
        text = f"{f['name']} {f['description']}".lower()
        score = sum(1 for kw in keywords if kw in text)
        scores.append((score, f["filename"]))

    # 按得分排序，返回前 max_items 个（得分 > 0）
    scores.sort(reverse=True, key=lambda x: x[0])
    return [filename for score, filename in scores[:max_items] if score > 0]


def load_memories(messages: list, max_items: int = 5) -> str:
    """
    加载相关记忆内容

    Args:
        messages: 当前对话历史
        max_items: 最多加载的记忆数

    Returns:
        格式化的记忆内容字符串，可直接注入到 user message
        格式：<memories count="N">...</memories>

    业务逻辑：
    1. 调用 select_relevant_memories() 选择相关文件
    2. 读取每个文件的完整内容（包括 frontmatter）
    3. 格式化为 "## filename\n\ncontent" 格式
    4. 用 <memories> 标签包裹，返回完整字符串
    5. 如果没有相关记忆，返回空字符串
    """
    selected_files = select_relevant_memories(messages, max_items)

    if not selected_files:
        return ""

    # 读取文件内容
    memories = []
    for filename in selected_files:
        content = read_memory_file(filename)
        if content:
            memories.append(f"## {filename}\n\n{content}")

    if not memories:
        return ""

    # 格式化为注入内容
    header = f"<memories count=\"{len(memories)}\">\n"
    footer = "\n</memories>"
    body = "\n\n---\n\n".join(memories)

    return header + body + footer


# ── 提取层：从对话中提取新记忆 ────────────────────────
def extract_memories(messages: list):
    """
    从对话中提取新记忆

    Args:
        messages: 当前对话历史（压缩前的完整对话）

    业务逻辑：
    1. 格式化最近 10 条消息
    2. 列出已有记忆，避免重复
    3. 发送提取 prompt 给 LLM
    4. 要求返回 JSON 数组：[{name, type, description, body}]
    5. 解析 JSON，为每个新记忆调用 write_memory_file()
    6. 如果没有新记忆或解析失败，静默返回
    """
    # 格式化最近对话（最近 10 条消息）
    recent_messages = messages[-10:] if len(messages) > 10 else messages
    dialogue = _format_messages_for_query(recent_messages)

    # 限制对话长度，避免超出 token 限制
    if len(dialogue) > 4000:
        dialogue = dialogue[:4000]

    # 列出已有记忆
    existing = list_memory_files()
    existing_text = "\n".join(f"- {m['name']}: {m['description']}" for m in existing)

    # 提取 prompt
    prompt = f"""Extract user preferences, constraints, feedback, or project facts from the dialogue.
Return a JSON array: [{{"name": "...", "type": "user|feedback|project|reference", "description": "...", "body": "..."}}]

Guidelines:
- type: user (preferences/role), feedback (how to do things), project (current goals), reference (where to find things)
- body: include **Why:** and **How to apply:** when relevant
- Only extract if NEW information not already covered
- If nothing new, return []

Existing memories:
{existing_text if existing_text else "(none)"}

Dialogue:
{dialogue}
"""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        text = _extract_text(response.content).strip()

        # 解析 JSON 数组
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if not match:
            return  # 没有找到 JSON，静默返回

        memories = json.loads(match.group())

        if not memories:
            return  # 空数组，没有新记忆

        # 写入新记忆
        for mem in memories:
            if all(k in mem for k in ["name", "type", "description", "body"]):
                write_memory_file(
                    name=mem["name"],
                    mem_type=mem["type"],
                    description=mem["description"],
                    body=mem["body"]
                )
                print(f"[Memory] Extracted: {mem['name']}")

    except Exception as e:
        # 提取失败，静默返回（不影响主流程）
        print(f"[Memory] Extraction failed: {e}")
        return


# ── 整理层：合并去重记忆 ──────────────────────────────
def consolidate_memories():
    """
    整理记忆：去重、合并、淘汰过时

    业务逻辑：
    1. 检查文件数是否达到阈值（CONSOLIDATE_THRESHOLD = 10）
    2. 如果未达到，直接返回
    3. 如果达到，读取所有记忆文件的完整内容
    4. 构建目录：每个记忆包含 filename/name/description/body
    5. 发送给 LLM，要求整理：去重、合并、保留重要信息
    6. LLM 返回整理后的 JSON 数组
    7. 删除所有旧文件（保留 MEMORY.md）
    8. 写入新文件
    9. 打印整理结果
    """
    files = list_memory_files()

    if len(files) < CONSOLIDATE_THRESHOLD:
        return  # 文件数不足，不需要整理

    # 读取所有记忆内容，构建目录
    catalog_parts = []
    for f in files:
        content = read_memory_file(f["filename"])
        if content:
            # 提取 body（去掉 frontmatter）
            match = re.match(r'^---\s*\n.*?\n---\s*\n(.*)$', content, re.DOTALL)
            body = match.group(1).strip() if match else content

            catalog_parts.append(
                f"## {f['filename']}\n"
                f"name: {f['name']}\n"
                f"description: {f['description']}\n"
                f"{body}"
            )

    catalog = "\n\n".join(catalog_parts)

    # 整理 prompt
    prompt = (
        "Consolidate the following memory files. Rules:\n"
        "1. Merge duplicates into one\n"
        "2. Remove outdated/contradicted memories\n"
        "3. Keep the total under 30 memories\n"
        "4. Preserve important user preferences above all\n"
        "Return a JSON array. Each item: {name, type, description, body}.\n\n"
        f"{catalog[:16000]}"
    )

    try:
        response = client.messages.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000
        )

        text = _extract_text(response.content).strip()
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return

        items = json.loads(match.group())

        # 删除所有旧记忆文件（保留 MEMORY.md）
        for f in MEMORY_DIR.glob("*.md"):
            if f.name != "MEMORY.md":
                f.unlink()

        # 写入新记忆
        for mem in items:
            name = mem.get("name", f"memory_{int(__import__('time').time())}")
            mem_type = mem.get("type", "user")
            desc = mem.get("description", "")
            body = mem.get("body", "")
            if desc and body:
                write_memory_file(name, mem_type, desc, body)

        print(f"\n\033[33m[Memory: consolidated {len(files)} → {len(items)} memories]\033[0m")

    except Exception as e:
        print(f"[Memory] Consolidation failed: {e}")
        pass
