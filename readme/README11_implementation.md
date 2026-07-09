# Error Recovery 错误恢复实现总结

## 修改概览

参照 `readme/README11.md` 和 `readme/code.py`，为 `agent_loop.py` 实现了完整的错误恢复机制，使 agent 能够从 API 错误中自动恢复。

## 核心变更

### 1. 新增错误恢复常量（第 46-64 行）

```python
DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 64000
MAX_RETRIES = 10
BASE_DELAY_MS = 500
MAX_CONSECUTIVE_529 = 3
MAX_RECOVERY_RETRIES = 3
CONTINUATION_PROMPT = "Output token limit hit. Resume directly — no apology, no recap. Pick up mid-thought."
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID", "")
PRIMARY_MODEL = MODEL
```

**业务逻辑**：
- **DEFAULT_MAX_TOKENS → ESCALATED_MAX_TOKENS**：8K → 64K（8 倍空间）
- **MAX_RETRIES**：瞬态错误最多重试 10 次
- **MAX_CONSECUTIVE_529**：连续 3 次 529 触发模型切换
- **MAX_RECOVERY_RETRIES**：输出截断最多续写 3 次
- **FALLBACK_MODEL**：备用模型（从环境变量读取）

### 2. 新增 RecoveryState 类（第 219-247 行）

```python
class RecoveryState:
    def __init__(self):
        self.has_escalated = False           # 是否已升级 max_tokens
        self.recovery_count = 0              # 续写次数
        self.consecutive_529 = 0             # 连续 529 错误次数
        self.has_attempted_reactive_compact = False  # 是否已尝试应急压缩
        self.current_model = PRIMARY_MODEL   # 当前使用的模型
```

**业务逻辑**：
- 封装所有恢复状态，避免全局变量
- `has_escalated` 和 `has_attempted_reactive_compact` 确保某些恢复只执行一次
- `recovery_count` 和 `consecutive_529` 用于计数限制
- `current_model` 支持动态切换模型

### 3. 新增 retry_delay 函数（第 250-290 行）

```python
def retry_delay(attempt: int, retry_after: int | None = None) -> float:
    if retry_after:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter
```

**业务逻辑**：
- 指数退避公式：`min(500 × 2^attempt, 32000) ms`
- 添加 25% 随机抖动，避免并发请求同时重试
- 优先使用服务器返回的 `Retry-After` 值

**指数退避表**：
| 尝试 | 基础延迟 | 加抖动后 |
|------|---------|---------|
| 0 | 500ms | 500-625ms |
| 1 | 1000ms | 1000-1250ms |
| 2 | 2000ms | 2000-2500ms |
| 3 | 4000ms | 4000-5000ms |
| 6+ | 32000ms | 32000-40000ms |

### 4. 新增 is_prompt_too_long_error 函数（第 293-327 行）

```python
def is_prompt_too_long_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (("prompt" in msg and "long" in msg)
            or "prompt_is_too_long" in msg
            or "context_length_exceeded" in msg
            or "max_context_window" in msg)
```

**业务逻辑**：
- 多模式匹配，覆盖不同 API 版本和云服务商的错误消息
- 用于判断是否触发 reactive_compact

### 5. 新增 with_retry 函数（第 330-406 行）

```python
def with_retry(fn, state: RecoveryState):
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            # 429 限流 -> 指数退避
            if "ratelimit" in name.lower() or "429" in msg:
                delay = retry_delay(attempt)
                time.sleep(delay)
                continue
            
            # 529 过载 -> 指数退避 + 可能切换模型
            if "overloaded" in name.lower() or "529" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    if FALLBACK_MODEL:
                        state.current_model = FALLBACK_MODEL
                continue
            
            # 非瞬态错误 -> 抛给外层
            raise
    
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")
```

**业务逻辑**：
- 自动重试 429（限流）和 529（过载）错误
- 使用指数退避 + 随机抖动
- 连续 3 次 529 → 切换到 FALLBACK_MODEL
- 非瞬态错误（如 prompt_too_long）抛给外层处理
- 超过最大重试次数抛出 RuntimeError

### 6. 修改 agent_loop 函数 - 三处关键修改

#### 修改 6.1：初始化（第 413-424 行）

**之前**：
```python
def agent_loop(messages: list):
    global rounds_since_todo
    reactive_retries = 0
    system = build_system()
```

**之后**：
```python
def agent_loop(messages: list):
    global rounds_since_todo
    
    # ── s11: 创建恢复状态和初始 max_tokens ─────────────
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS
    
    # ── s10: 初始化 context 并组装 system prompt ────────
    context = update_context({}, messages)
    system = get_system_prompt(context)
```

#### 修改 6.2：LLM 调用和错误处理（第 448-495 行）

**之前**：
```python
try:
    response = client.messages.create(
        model=MODEL, system=system, messages=request_messages,
        tools=TOOLS, max_tokens=8000,
    )
except Exception as e:
    # 简单的 prompt_too_long 检查
    if "prompt" in error_message and "too long" in error_message:
        messages[:] = reactive_compact(messages)
        continue
```

**之后**：
```python
try:
    # with_retry 处理瞬态错误（429/529）
    response = with_retry(
        lambda: client.messages.create(
            model=state.current_model,  # 可能切换模型
            system=system,
            messages=request_messages,
            tools=TOOLS,
            max_tokens=max_tokens,  # 可能升级
        ),
        state
    )

except Exception as e:
    # ── 路径 2: prompt_too_long -> reactive compact (一次) ──
    if is_prompt_too_long_error(e):
        if not state.has_attempted_reactive_compact:
            messages[:] = reactive_compact(messages)
            state.has_attempted_reactive_compact = True
            continue
        # 压缩后还是超限，无法恢复
        print("  \033[31m[unrecoverable] still too long after compact\033[0m")
        return
    
    # ── 其他不可恢复错误 ──
    print(f"  \033[31m[unrecoverable] {name}: {str(e)[:100]}\033[0m")
    return
```

#### 修改 6.3：max_tokens 截断恢复（第 498-520 行）

**新增逻辑**：
```python
# ── 路径 1: max_tokens -> 升级或续写 ──────────────────
if response.stop_reason == "max_tokens":
    # 第一次截断：升级到 64K，不追加截断内容，重试相同请求
    if not state.has_escalated:
        max_tokens = ESCALATED_MAX_TOKENS
        state.has_escalated = True
        print(f"  \033[33m[max_tokens] escalating {DEFAULT_MAX_TOKENS} -> {ESCALATED_MAX_TOKENS}\033[0m")
        continue  # messages 不变，用更大 max_tokens 重试

    # 64K 还是截断：保存截断内容 + 续写提示
    messages.append({"role": "assistant", "content": response.content})
    if state.recovery_count < MAX_RECOVERY_RETRIES:
        messages.append({"role": "user", "content": CONTINUATION_PROMPT})
        state.recovery_count += 1
        print(f"  \033[33m[max_tokens] continuation {state.recovery_count}/{MAX_RECOVERY_RETRIES}\033[0m")
        continue
    # 续写 3 次后还是截断，放弃
    print("  \033[31m[max_tokens] recovery limit reached\033[0m")
    return

# ── 正常完成：追加响应 ────────────────────────────────
messages.append({"role": "assistant", "content": response.content})
```

## 三种错误恢复路径

### 路径 1：输出截断（max_tokens）

**触发条件**：`response.stop_reason == "max_tokens"`

**恢复流程**：
1. **第一次截断**（未升级过）：
   - 升级 `max_tokens` 从 8K 到 64K
   - **不追加截断内容**（保持请求不变）
   - `continue` 重试相同请求
   
2. **第二次及以后截断**（已升级过）：
   - 追加截断内容到 messages
   - 添加续写提示（CONTINUATION_PROMPT）
   - 最多续写 3 次
   
3. **仍然截断**：放弃，返回

**为什么第一次不追加截断内容**：
- 保持原请求不变，只是给模型更多 token 空间
- 这样可以得到完整输出，而不是"截断 + 续写"的拼接

### 路径 2：上下文超限（prompt_too_long）

**触发条件**：`is_prompt_too_long_error(e) == True`

**恢复流程**：
1. **第一次超限**（未压缩过）：
   - 调用 `reactive_compact(messages)`（保留最后 5 条 + LLM 摘要）
   - 设置 `has_attempted_reactive_compact = True`
   - `continue` 重试
   
2. **第二次超限**（已压缩过）：
   - 无法恢复，退出
   - 添加错误消息到 messages

**与现有压缩系统的关系**：
- 项目已有四层压缩（snip_compact、micro_compact、tool_result_budget、compact_history）
- reactive_compact 是最后一道防线，比常规压缩更激进
- 只在 API 明确返回 prompt_too_long 时触发

### 路径 3：瞬态错误（429/529）

**触发条件**：`with_retry` 捕获到 429 或 529 错误

**恢复流程**：

**429 限流错误**：
1. 计算延迟：`retry_delay(attempt)`
2. sleep 延迟
3. 重试（最多 10 次）

**529 过载错误**：
1. `consecutive_529 += 1`
2. 如果连续 3 次 529：
   - 切换到 `FALLBACK_MODEL`（如果配置了）
   - 重置 `consecutive_529`
3. 计算延迟：`retry_delay(attempt)`
4. sleep 延迟
5. 重试（最多 10 次）

**成功后**：
- 重置 `consecutive_529 = 0`

## 与参考代码的对比

| 组件 | 参考代码 (s11) | 本项目实现 |
|------|---------------|-----------|
| RecoveryState | ✅ | ✅ 相同 |
| retry_delay | ✅ | ✅ 相同 |
| with_retry | ✅ | ✅ 相同 |
| is_prompt_too_long_error | ✅ | ✅ 相同 |
| reactive_compact | 简化版（保留最后 N 条） | **增强版**（LLM 摘要 + 保留最后 5 条） |
| max_tokens 恢复 | ✅ | ✅ 相同 |
| 模型切换 | ✅ | ✅ 相同 |

**本项目的 reactive_compact 更强大**：
- 参考代码：简单保留最后 5 条消息
- 本项目：调用 LLM 生成摘要 + 保留最后 5 条 + 保存完整 transcript

## 错误处理流程图

```
agent_loop 开始
    ↓
创建 RecoveryState
max_tokens = 8000
    ↓
进入 while True 循环
    ↓
压缩管线（4 层）
    ↓
try:
    with_retry(lambda: client.messages.create(...))
    ↓
    ├─ 成功 → 继续处理响应
    ├─ 429 → 指数退避 → 重试（最多 10 次）
    ├─ 529 → 指数退避 + 可能切换模型 → 重试（最多 10 次）
    └─ 其他错误 → 抛给外层
except:
    ├─ prompt_too_long?
    │   ├─ 未压缩过？→ reactive_compact → continue
    │   └─ 已压缩过？→ 无法恢复 → return
    └─ 其他错误 → 记录 → return
    ↓
response.stop_reason == "max_tokens"?
    ├─ 未升级过？→ 升级到 64K → continue
    ├─ 已升级过 + 续写 < 3？→ 追加 + 续写提示 → continue
    └─ 续写 >= 3？→ 放弃 → return
    ↓
response.stop_reason != "tool_use"?
    ├─ 是 → 提取记忆 → return
    └─ 否 → 执行工具 → 更新 context → continue
```

## 业务逻辑改进

### 之前（无错误恢复）
1. API 错误直接崩溃
2. max_tokens 截断无法恢复
3. 上下文超限依赖手动 compact 工具
4. 429/529 错误需要手动重启

### 之后（完整错误恢复）
1. **路径 1（输出截断）**：8K → 64K → 续写 3 次
2. **路径 2（上下文超限）**：reactive_compact → 重试
3. **路径 3（瞬态错误）**：指数退避 + 模型切换
4. **调试友好**：打印恢复状态和进度

## 测试建议

### 1. 测试输出截断恢复
```python
# 让 agent 生成一段很长的代码
query = "Generate a complete Python web framework with detailed comments"
```
**预期行为**：
- 看到 `[max_tokens] escalating 8000 -> 64000`
- 如果仍然截断，看到 `[max_tokens] continuation 1/3`

### 2. 测试上下文超限恢复
```python
# 连续读取大量文件
for i in range(100):
    query = f"Read all Python files in the project"
```
**预期行为**：
- 看到 `[COMPACT] reactive_compact: API 返回 prompt_too_long`
- 压缩后继续运行

### 3. 测试模拟 429/529（需要修改代码）
在 `with_retry` 中添加模拟错误：
```python
if attempt == 0:
    raise Exception("429 rate limit")
```
**预期行为**：
- 看到 `[429 rate limit] retry 1/10, wait 0.5s`
- 自动重试

### 4. 测试模型切换（需要配置环境变量）
```bash
export FALLBACK_MODEL_ID="claude-sonnet-4-20250514"
```
模拟连续 3 次 529：
**预期行为**：
- 看到 `[529 x3] switching to claude-sonnet-4-20250514`

## 配置选项

### 环境变量
- `FALLBACK_MODEL_ID`：备用模型 ID（可选）

### 可调整常量
- `DEFAULT_MAX_TOKENS = 8000`：初始 token 限制
- `ESCALATED_MAX_TOKENS = 64000`：升级后的 token 限制
- `MAX_RETRIES = 10`：瞬态错误最大重试次数
- `BASE_DELAY_MS = 500`：指数退避基础延迟
- `MAX_CONSECUTIVE_529 = 3`：触发模型切换的连续 529 次数
- `MAX_RECOVERY_RETRIES = 3`：输出截断最多续写次数

## 总结

✅ 实现了完整的三路错误恢复机制
✅ 支持输出截断恢复（8K → 64K → 续写 3 次）
✅ 支持上下文超限恢复（reactive_compact）
✅ 支持瞬态错误重试（429/529 + 指数退避）
✅ 支持模型自动切换（连续 3 次 529）
✅ 调试友好（打印恢复状态）
✅ 与现有系统完美集成（压缩、记忆、技能）

相对于无错误恢复的版本，新实现：
- **更可靠**：自动从常见错误中恢复
- **更智能**：根据错误类型选择恢复策略
- **更高效**：指数退避避免浪费资源
- **更灵活**：支持模型切换和动态升级
