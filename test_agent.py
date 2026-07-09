#!/usr/bin/env python3
"""
测试 agent_loop 的错误恢复功能
"""

from agent_loop import agent_loop

# 测试消息
messages = []

query = "Create tasks: setup database schema, create API endpoints (depends on schema), write tests (depends on endpoints), write docs (depends on schema)"

messages.append({"role": "user", "content": query})

try:
    print("开始执行 agent_loop...")
    agent_loop(messages)

    print("\n\n=== 最终响应 ===")
    if messages:
        last_message = messages[-1]
        content = last_message.get("content", "")
        if isinstance(content, list):
            for block in content:
                if hasattr(block, "text"):
                    print(block.text)
                elif isinstance(block, dict) and "text" in block:
                    print(block["text"])
        else:
            print(content)
except Exception as e:
    print(f"\n\n!!! 发生错误 !!!")
    print(f"错误类型: {type(e).__name__}")
    print(f"错误信息: {e}")
    import traceback
    traceback.print_exc()
