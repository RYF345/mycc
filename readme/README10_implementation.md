# System Prompt 自动组装实现总结

## 修改概览

参照 `readme/README10.md` 和 `readme/code.py`，将 `agent_loop.py` 中的硬编码 system prompt 改为运行时自动组装模式。

## 核心变更

### 1. 新增 PROMPT_SECTIONS 字典（第 46-52 行）

```python
PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "workspace": f"Working directory: {WORKDIR}",
    "tools": "Use available tools to complete tasks.",
    "skills_template": "Skills available:\n{catalog}\nUse load_skill to get full details when needed.",
    "memory_template": "Memory Index:\n{content}",
}
```

**设计原理**：
- 将 system prompt 拆分成独立的主题段落
- 使用 `_template` 后缀的 section 支持动态内容注入
- `tools` 采用简化描述，因为 API 的 `tools=TOOLS` 参数已包含完整 schema

### 2. 新增 assemble_system_prompt() 函数（第 55-89 行）

**功能**：根据 context 动态选择并拼接 prompt sections

**业务逻辑**：
1. **始终加载**：identity、workspace、tools
2. **按需加载**：
   - 如果 `context["skills_catalog"]` 非空，加载 skills section
   - 如果 `context["memory_index"]` 非空，加载 memory section
3. 用 `"\n\n"` 连接所有 sections

**关键点**：基于真实状态加载，而不是搜索消息中的关键词

### 3. 新增 update_context() 函数（第 92-121 行）

**功能**：从真实文件系统状态更新 context

**业务逻辑**：
1. 调用 `list_skills()` 获取技能目录
2. 检查 `.memory/MEMORY.md` 是否存在且有内容
3. 返回包含实际状态的 context 字典

**为什么基于真实状态**：
- 文件可能在对话中被创建或删除
- 不依赖消息内容，避免误判
- 保证 system prompt 反映当前真实环境

### 4. 新增 get_system_prompt() 缓存函数（第 124-168 行）

**功能**：缓存包装器，只在 context 变化时重新组装

**业务逻辑**：
1. 使用 `json.dumps(context, sort_keys=True)` 生成确定性 cache key
2. 如果 key 与上次相同，返回缓存的 prompt（避免重复拼接）
3. 如果 key 不同，调用 `assemble_system_prompt()` 重新组装
4. 打印调试信息：`[cache hit]` 或 `[assembled] sections: ...`

**为什么用 json.dumps 而不是 hash()**：
- Python 的 `hash()` 有进程随机化（PYTHONHASHSEED）
- `hash()` 对 dict/list 会报错 "unhashable type"
- `json.dumps(sort_keys=True)` 保证相同内容产生相同字符串

**注意**：这个缓存只避免字符串拼接的重复计算（进程内优化），与 Claude API 的 prompt cache 无关

### 5. 删除 build_system() 函数

原函数（第 50-63 行）已被新的组装机制替代

### 6. 修改 agent_loop() 函数

#### 修改 1：初始化部分（第 175-183 行）

**之前**：
```python
memories_content = load_memories(messages)
memory_turn = len(messages) - 1 if messages and isinstance(messages[-1].get("content"), str) else None
system = build_system()  # 每轮重新构建，因为记忆索引可能更新
```

**之后**：
```python
# ── s10: 初始化 context 并组装 system prompt ────────
context = update_context({}, messages)
system = get_system_prompt(context)

# ── s09: 加载相关记忆 ──────────────────────────────
memories_content = load_memories(messages)
memory_turn = len(messages) - 1 if messages and isinstance(messages[-1].get("content"), str) else None
```

#### 修改 2：工具执行后更新（第 347-351 行）

**之前**：
```python
messages.append({"role": "user", "content": results})

# 如果执行了 compact，立即开始新一轮（用压缩后的上下文）
if compacted:
    continue
```

**之后**：
```python
messages.append({"role": "user", "content": results})

# ── s10: 重新评估 context 和 prompt ──────────────
# 工具执行后可能改变了状态（创建记忆、添加技能等）
context = update_context(context, messages)
system = get_system_prompt(context)

# 如果执行了 compact，立即开始新一轮（用压缩后的上下文）
if compacted:
    continue
```

**为什么每轮更新**：
- 工具执行后可能创建了 `.memory/MEMORY.md`
- 如果状态未变，`get_system_prompt()` 会命中缓存，不会重复组装

## 与参考代码的对比

| 组件 | 参考代码 (s10) | 本项目实现 |
|------|---------------|-----------|
| Sections 数量 | 4 个 (identity, tools, workspace, memory) | 5 个 (增加 skills) |
| Tools section | 明确列举：`bash, read_file, write_file` | 简化描述：`Use available tools` |
| Skills 加载 | 无 | 通过 `list_skills()` 动态加载 |
| Memory 加载 | 检查 `MEMORY.md` 存在性 | 检查 `MEMORY.md` 存在性 + 内容非空 |
| 缓存机制 | `json.dumps` 做 cache key | 相同 |
| Context 更新时机 | 每轮循环开始 | 循环开始 + 工具执行后 |

## 业务逻辑改进

### 之前（硬编码模式）
1. `build_system()` 每次调用都重新读取文件
2. 无论是否有内容，都拼接所有部分
3. 每次都重复字符串拼接操作
4. 无法观察加载了哪些 sections

### 之后（自动组装模式）
1. **分段定义**：PROMPT_SECTIONS 按主题独立维护
2. **按需加载**：只有当 skills_catalog 或 memory_index 非空时才加载
3. **基于真实状态**：检查文件是否存在，不依赖关键词
4. **缓存优化**：相同 context 不重复拼接（使用 json.dumps 做确定性 key）
5. **调试友好**：打印 `[cache hit]` 或 `[assembled] sections: ...`
6. **动态响应**：工具执行后重新评估状态

## 测试建议

1. **启动 agent**：观察初始加载的 sections
   ```bash
   python agent_loop.py
   ```
   预期输出：`[assembled] sections: identity, workspace, tools, skills`

2. **创建记忆文件**：
   ```
   >> Create a file .memory/MEMORY.md with content "# Memory Index\n\n- test memory"
   ```
   下一轮应该看到：`[assembled] sections: identity, workspace, tools, skills, memory`

3. **观察缓存命中**：
   ```
   >> Read the file agent_loop.py
   ```
   如果状态未变，应该看到：`[cache hit] system prompt unchanged`

4. **删除记忆文件**：
   ```
   >> Delete the file .memory/MEMORY.md
   ```
   下一轮 memory section 应该消失

## 总结

✅ 实现了 system prompt 的运行时组装机制
✅ 支持按需加载，避免无关内容占用 token
✅ 基于真实状态，而不是关键词猜测
✅ 缓存优化，避免重复拼接
✅ 调试友好，可观察加载的 sections
✅ 保持了原有的所有功能（记忆、压缩、技能、工具）

相对于硬编码模式，新实现更加：
- **模块化**：每个 section 独立维护
- **灵活**：可以轻松添加新的 section
- **高效**：缓存避免重复计算
- **可维护**：修改一个 section 不影响其他
