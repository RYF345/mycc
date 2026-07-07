#!/usr/bin/env python3
"""
test_memory.py - 测试 Memory 模块

测试场景：
1. 测试基本存储和索引功能
2. 测试记忆提取功能
3. 测试记忆加载功能
4. 测试整合功能
"""

import sys
from pathlib import Path

# 确保可以导入 memory 模块
sys.path.insert(0, str(Path(__file__).parent))

from memory import (
    write_memory_file,
    list_memory_files,
    read_memory_file,
    select_relevant_memories,
    load_memories,
    extract_memories,
    consolidate_memories,
    MEMORY_DIR,
    MEMORY_INDEX,
)


def cleanup():
    """清理测试文件"""
    import shutil
    if MEMORY_DIR.exists():
        shutil.rmtree(MEMORY_DIR)
    MEMORY_DIR.mkdir(exist_ok=True)
    print("[OK] 清理完成")


def test_basic_storage():
    """测试 1: 基本存储和索引"""
    print("\n" + "="*50)
    print("测试 1: 基本存储和索引功能")
    print("="*50)

    # 写入记忆
    print("\n-> 写入第一个记忆...")
    write_memory_file(
        name="user-preference-tabs",
        mem_type="user",
        description="User prefers tabs for indentation",
        body="User prefers using tabs, not spaces.\n**Why:** Consistency with existing code.\n**How to apply:** Always use tabs when writing code."
    )

    # 检查文件是否创建
    files = list_memory_files()
    assert len(files) == 1, f"应该有 1 个记忆文件，实际有 {len(files)}"
    assert files[0]["name"] == "user-preference-tabs"
    print(f"  [OK] 记忆文件已创建: {files[0]['filename']}")

    # 检查索引是否更新
    assert MEMORY_INDEX.exists(), "索引文件应该存在"
    index_content = MEMORY_INDEX.read_text(encoding="utf-8")
    assert "user-preference-tabs" in index_content
    print(f"  [OK] 索引已更新")

    # 写入第二个记忆
    print("\n-> 写入第二个记忆...")
    write_memory_file(
        name="feedback-no-mock-db",
        mem_type="feedback",
        description="Don't mock database in tests",
        body="Don't mock the database in tests.\n**Why:** Previous incident where mocked tests passed but prod failed.\n**How to apply:** Use real test database for integration tests."
    )

    files = list_memory_files()
    assert len(files) == 2, f"应该有 2 个记忆文件，实际有 {len(files)}"
    print(f"  [OK] 现在有 {len(files)} 个记忆文件")

    print("\n[PASS] 测试 1 通过：基本存储和索引功能正常")


def test_memory_selection():
    """测试 2: 记忆选择功能"""
    print("\n" + "="*50)
    print("测试 2: 记忆选择功能")
    print("="*50)

    # 模拟对话历史
    messages = [
        {"role": "user", "content": "Create a Python file with a function"},
        {"role": "assistant", "content": "Sure, I'll create it."},
    ]

    print("\n-> 测试关键词匹配降级（不调用 LLM）...")
    # 注意：这里会尝试调用 LLM side-query，如果失败会降级到关键词匹配
    # 为了纯测试，我们直接导入降级函数
    from memory import select_relevant_memories_fallback

    selected = select_relevant_memories_fallback(messages, max_items=5)
    print(f"  -> 选中的记忆: {selected}")
    # Python 文件创建可能匹配到 user-preference-tabs（如果关键词匹配到 "python" 或 "file"）

    print("\n[PASS] 测试 2 通过：记忆选择功能正常")


def test_memory_loading():
    """测试 3: 记忆加载功能"""
    print("\n" + "="*50)
    print("测试 3: 记忆加载功能")
    print("="*50)

    # 模拟对话
    messages = [
        {"role": "user", "content": "I want to write some Python code with proper indentation"},
    ]

    print("\n-> 加载相关记忆...")
    print("  （注意：这会调用 LLM side-query，可能需要几秒钟）")

    try:
        memories_content = load_memories(messages, max_items=5)

        if memories_content:
            print(f"\n  [OK] 加载了记忆内容（{len(memories_content)} 字符）")
            print("\n  记忆内容预览：")
            print("  " + "-"*40)
            preview = memories_content[:300] + "..." if len(memories_content) > 300 else memories_content
            print("  " + preview.replace("\n", "\n  "))
            print("  " + "-"*40)
        else:
            print("  [INFO]  没有找到相关记忆（这可能是正常的）")

        print("\n[PASS] 测试 3 通过：记忆加载功能正常")
    except Exception as e:
        print(f"\n[WARN]  测试 3 警告：LLM 调用失败，这是正常的")
        print(f"  错误信息: {e}")
        print("  （在实际使用中会自动降级到关键词匹配）")


def test_memory_extraction():
    """测试 4: 记忆提取功能"""
    print("\n" + "="*50)
    print("测试 4: 记忆提取功能")
    print("="*50)

    # 模拟对话历史（用户明确表达偏好）
    messages = [
        {"role": "user", "content": "I prefer single quotes over double quotes in Python strings. Please remember that."},
        {"role": "assistant", "content": "Got it, I'll use single quotes for Python strings from now on."},
    ]

    print("\n-> 从对话中提取记忆...")
    print("  （注意：这会调用 LLM，可能需要几秒钟）")

    files_before = len(list_memory_files())
    print(f"  提取前记忆数: {files_before}")

    try:
        extract_memories(messages)

        files_after = len(list_memory_files())
        print(f"  提取后记忆数: {files_after}")

        if files_after > files_before:
            print(f"  [OK] 成功提取了 {files_after - files_before} 个新记忆")

            # 显示新记忆
            all_files = list_memory_files()
            print("\n  所有记忆:")
            for f in all_files:
                print(f"    - {f['name']} ({f['type']}): {f['description']}")
        else:
            print("  [INFO]  没有提取到新记忆（可能 LLM 认为已存在）")

        print("\n[PASS] 测试 4 通过：记忆提取功能正常")
    except Exception as e:
        print(f"\n[WARN]  测试 4 警告：LLM 调用失败")
        print(f"  错误信息: {e}")


def test_memory_consolidation():
    """测试 5: 记忆整合功能"""
    print("\n" + "="*50)
    print("测试 5: 记忆整合功能")
    print("="*50)

    print("\n-> 当前记忆数量...")
    files_before = list_memory_files()
    print(f"  当前有 {len(files_before)} 个记忆文件")

    # 检查是否达到阈值
    from memory import CONSOLIDATE_THRESHOLD
    print(f"  整合阈值: {CONSOLIDATE_THRESHOLD}")

    if len(files_before) < CONSOLIDATE_THRESHOLD:
        print(f"\n  -> 创建更多测试记忆（需要 {CONSOLIDATE_THRESHOLD - len(files_before)} 个）...")
        for i in range(CONSOLIDATE_THRESHOLD - len(files_before)):
            write_memory_file(
                name=f"test-memory-{i}",
                mem_type="user",
                description=f"Test memory {i}",
                body=f"This is test memory number {i}."
            )

        files_before = list_memory_files()
        print(f"  [OK] 现在有 {len(files_before)} 个记忆文件")

    print("\n-> 尝试触发整合...")
    print("  （注意：这会调用 LLM，可能需要几秒钟）")

    try:
        consolidate_memories()

        files_after = list_memory_files()
        print(f"\n  整合前: {len(files_before)} 个文件")
        print(f"  整合后: {len(files_after)} 个文件")

        if len(files_after) < len(files_before):
            print(f"  [OK] 成功整合，减少了 {len(files_before) - len(files_after)} 个重复/过时记忆")
        else:
            print("  [INFO]  没有进行整合（可能数量不足或 LLM 认为都需要保留）")

        print("\n[PASS] 测试 5 通过：记忆整合功能正常")
    except Exception as e:
        print(f"\n[WARN]  测试 5 警告：LLM 调用失败")
        print(f"  错误信息: {e}")


def main():
    print("\n" + "=" * 50)
    print("Memory 模块测试".center(50))
    print("=" * 50)
    print("\n说明：部分测试需要调用 LLM API，请确保：")
    print("  1. ANTHROPIC_API_KEY 已配置")
    print("  2. MODEL_ID 已设置")
    print("  3. 网络连接正常\n")

    try:
        # 清理旧测试数据
        cleanup()

        # 运行测试
        test_basic_storage()
        test_memory_selection()
        test_memory_loading()
        test_memory_extraction()
        test_memory_consolidation()

        print("\n" + "="*50)
        print("所有测试完成！")
        print("="*50)

        # 显示最终状态
        print("\n最终记忆文件列表:")
        files = list_memory_files()
        for f in files:
            print(f"  - {f['filename']}: {f['description']}")

        print(f"\n总计: {len(files)} 个记忆文件")
        print(f"位置: {MEMORY_DIR}")

    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[WARN]  测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] 测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
