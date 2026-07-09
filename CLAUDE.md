# CLAUDE.md - my_agent 项目协作指南

本文档定义了 Claude 与用户在 my_agent 项目中的协作模式和约定。

---

## 项目概述

**项目名称**：my_agent  
**项目路径**：`E:\Coding_Project\Java\my_agent`  
**项目类型**：Python - AI Agent 系统  
**核心功能**：基于 Claude API 的 coding agent，支持工具调用、上下文压缩、记忆系统

**技术栈**：
- Python 3.13
- Anthropic Claude API
- Git

---

## 协作模式

### 1. 渐进式开发原则

在添加新功能或重构代码时，遵循**函数级粒度**的渐进式开发：

- ✅ **每个函数级别的改动都需要征得用户同意**
- ✅ **先说明业务逻辑，再展示代码**
- ✅ **等待用户同意后再执行**

**示例流程**：
```
Claude: 我准备修改 agent_loop() 函数，添加记忆加载功能。
       业务逻辑：在循环开始前调用 load_memories() 选择相关记忆...
       准备添加的代码：
       [显示完整代码]
       
       你是否同意我进行这个修改？

用户: 同意

Claude: [执行修改]
```

### 2. 详细的改动说明

每次改动都需要包含：

1. **改动位置**：文件名、行号、函数名
2. **业务逻辑**：为什么改、改了什么、影响范围
3. **代码示例**：完整的改动代码（不是片段）
4. **关键巧思**：设计考虑、边缘情况处理

**不要**：
- ❌ 笼统地说"添加了一些功能"
- ❌ 只给伪代码或注释
- ❌ 跳过业务逻辑说明

### 3. 实现细节优先于抽象

在解释技术实现时：

- ✅ 展示实际代码，而不是抽象描述
- ✅ 用具体例子说明，而不是理论定义
- ✅ 代码中包含注释，解释关键业务逻辑

**示例**：
```python
# ✅ 好的说明
def extract_memories(messages: list):
    """从对话中提取新记忆
    
    业务逻辑：
    1. 格式化最近 10 条消息
    2. 列出已有记忆，避免重复
    3. 发送给 LLM："从对话中提取新偏好"
    4. 解析 JSON 并写入文件
    """
    dialogue = _format_messages_for_query(messages[-10:])
    existing = list_memory_files()
    # ...

# ❌ 不好的说明
# 添加了记忆提取功能，使用 LLM 处理对话
```

### 4. 参考实现对照

当实现新功能时，如果有参考实现（例如 `readme/code.py`）：

- ✅ 对照参考实现，确保逻辑一致
- ✅ 指出与参考实现的差异（如果有）
- ✅ 说明为什么选择某种实现方式

### 5. 测试与验证

功能实现后：

- ✅ 提供测试脚本或测试方法
- ✅ 运行测试并展示结果
- ✅ 说明测试覆盖了哪些场景

---

## 文档化要求

### 完成后生成汇总文档

每次完成重要功能后，生成一份汇总文档（例如 `09记忆.md`），包含：

1. **功能概述**
   - 核心特性
   - 工作流程
   - 解决的问题

2. **新增文件**
   - 文件列表
   - 每个文件的函数列表
   - 关键代码示例

3. **修改文件**
   - 所有改动点
   - 每处改动的详细说明
   - 改动前后对比

4. **实现细节与巧思**
   - 设计决策
   - 边缘情况处理
   - 性能优化

5. **测试验证**
   - 测试方法
   - 测试结果
   - 实际使用示例

6. **未来改进方向**
   - 基于真实实现（如 Claude Code）的改进建议
   - 每个改进点包含代码示例

### 文档风格

- ✅ 使用 Markdown 格式
- ✅ 代码块标注语言（```python）
- ✅ 清晰的标题层级
- ✅ 使用表格对比
- ✅ 包含实际例子
- ✅ 中文撰写

---

## 代码规范

### Python 代码风格

- **命名**：snake_case（函数、变量），UPPER_CASE（常量）
- **注释**：简洁直接，说明业务逻辑和"为什么"
- **类型提示**：函数签名包含类型提示
- **文档字符串**：简洁的功能说明 + 业务逻辑拆解

**示例**：
```python
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
    # 实现代码
```

### 错误处理

- ✅ 明确的错误消息
- ✅ 关键操作用 try-except 包裹
- ✅ 降级方案（例如：LLM 失败 → 关键词匹配）

---

## 特定功能约定

### Memory 系统

**存储格式**：Markdown + YAML frontmatter

**文件结构**：
```
.memory/
  ├── MEMORY.md           # 索引文件
  ├── user-*.md           # 用户偏好
  ├── feedback-*.md       # 反馈约束
  ├── project-*.md        # 项目背景
  └── reference-*.md      # 外部资源
```

**整合阈值**：15 个文件

### 压缩管线

**执行顺序**（固定）：
1. `tool_result_budget()` - L3: 大结果落盘
2. `snip_compact()` - L1: 裁掉中间消息
3. `micro_compact()` - L2: 旧工具结果占位
4. `compact_history()` - L4: LLM 摘要（按需）

**关键原则**：
- 压缩前保存快照（`pre_compress`），用于准确提取记忆
- 压缩后的 messages 用于 LLM 调用（节省 token）

---

## 沟通约定

### 用户问题类型

1. **"为什么这样设计？"**
   → 解释业务逻辑、设计考虑、边缘情况

2. **"这段代码干什么？"**
   → 逐行解释 + 实际例子

3. **"参考实现是这样吗？"**
   → 对照参考代码，确认一致性

4. **"怎么测试？"**
   → 提供测试方法 + 运行测试

### Claude 的回答风格

- ✅ **直接回答问题**，不绕圈子
- ✅ **用代码示例**，而不是抽象描述
- ✅ **承认不确定**，而不是猜测
- ✅ **对比多个方案**，说明权衡

---

## 项目历史

### 已完成的功能

1. **基础 Agent Loop**（08 及之前）
   - 工具调用循环
   - 上下文压缩管线
   - Hooks 系统
   - Skills 系统

2. **Memory 系统**（09）
   - 跨会话记忆存储
   - LLM side-query 选择
   - 自动提取与整理
   - 完整测试套件

### 当前状态

- ✅ 所有核心功能已实现
- ✅ 测试全部通过
- ✅ 文档已更新

---

## 常用命令

```bash
# 运行 agent
python agent_loop.py

# 测试 memory 模块
python test_memory.py

# 查看记忆文件
ls .memory/
cat .memory/MEMORY.md

# Git 操作
git status
git add <files>
git commit -m "message"
```

---

## 参考资料

- **参考实现**：`readme/code.py` - Memory 系统的官方参考实现
- **功能说明**：`readme/README09.md` - Memory 功能详细说明
- **汇总文档**：`09记忆.md` - Memory 功能实现汇总

---

**最后更新**：2026-07-09  
**适用版本**：my_agent v0.9+（含 Memory 系统）
