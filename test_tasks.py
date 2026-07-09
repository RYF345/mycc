#!/usr/bin/env python3
"""
test_tasks.py - 测试任务系统

测试场景：
1. 创建任务并验证文件存储
2. 测试任务列表和排序
3. 测试依赖关系和 can_start
4. 测试认领和完成流程
5. 测试下游任务解锁
"""

import sys
from pathlib import Path

# 确保可以导入模块
sys.path.insert(0, str(Path(__file__).parent))

from tasks import (
    create_task,
    list_tasks,
    get_task,
    can_start,
    claim_task,
    complete_task,
    TASKS_DIR,
    HIGHWATERMARK_FILE,
)


def cleanup():
    """清理测试文件"""
    import shutil
    if TASKS_DIR.exists():
        shutil.rmtree(TASKS_DIR)
    TASKS_DIR.mkdir(exist_ok=True)
    print("[OK] 清理完成")


def test_basic_creation():
    """测试 1: 基本任务创建"""
    print("\n" + "="*50)
    print("测试 1: 基本任务创建和存储")
    print("="*50)

    # 创建任务
    print("\n-> 创建第一个任务...")
    task1 = create_task("Setup database schema", "Create users and posts tables")
    print(f"  [OK] 创建任务: {task1.id}")
    assert task1.status == "pending"
    assert task1.owner is None
    assert task1.blockedBy == []

    # 检查文件是否创建
    task_file = TASKS_DIR / f"{task1.id}.json"
    assert task_file.exists(), f"任务文件应该存在: {task_file}"
    print(f"  [OK] 任务文件已创建: {task_file.name}")

    # 检查 highwatermark
    assert HIGHWATERMARK_FILE.exists(), "highwatermark 文件应该存在"
    watermark = int(HIGHWATERMARK_FILE.read_text(encoding="utf-8").strip())
    print(f"  [OK] Highwatermark: {watermark}")

    # 创建第二个任务
    print("\n-> 创建第二个任务...")
    task2 = create_task("Create API endpoints")
    print(f"  [OK] 创建任务: {task2.id}")

    # 验证 ID 递增
    seq1 = int(task1.id.split('_')[-1])
    seq2 = int(task2.id.split('_')[-1])
    assert seq2 == seq1 + 1, f"序列号应该递增: {seq1} -> {seq2}"
    print(f"  [OK] 序列号递增: {seq1} -> {seq2}")

    print("\n[PASS] 测试 1 通过：基本任务创建正常")


def test_list_and_get():
    """测试 2: 列出和获取任务"""
    print("\n" + "="*50)
    print("测试 2: 列出和获取任务")
    print("="*50)

    print("\n-> 列出所有任务...")
    tasks = list_tasks()
    print(f"  -> 任务数量: {len(tasks)}")
    for t in tasks:
        print(f"    - {t.id}: {t.subject} [{t.status}]")

    assert len(tasks) >= 2, "应该至少有 2 个任务"
    print(f"  [OK] 列出了 {len(tasks)} 个任务")

    # 验证排序
    sequences = [int(t.id.split('_')[-1]) for t in tasks]
    assert sequences == sorted(sequences), "任务应该按序列号排序"
    print(f"  [OK] 任务按序列号排序")

    # 获取任务详情
    print("\n-> 获取任务详情...")
    task_json = get_task(tasks[0].id)
    print(f"  -> 任务详情:\n{task_json}")
    print(f"  [OK] 获取任务详情成功")

    print("\n[PASS] 测试 2 通过：列出和获取任务正常")


def test_dependencies():
    """测试 3: 任务依赖关系"""
    print("\n" + "="*50)
    print("测试 3: 任务依赖关系")
    print("="*50)

    # 获取现有任务
    tasks = list_tasks()
    schema_task = tasks[0]

    # 创建依赖任务
    print(f"\n-> 创建依赖于 {schema_task.id} 的任务...")
    endpoints_task = create_task(
        "Write API endpoints",
        "Implement REST API",
        blockedBy=[schema_task.id]
    )
    print(f"  [OK] 创建任务: {endpoints_task.id} (blockedBy: {schema_task.id})")

    # 测试 can_start
    print(f"\n-> 测试 can_start()...")
    can_start_schema = can_start(schema_task.id)
    can_start_endpoints = can_start(endpoints_task.id)
    print(f"  -> {schema_task.id} can_start: {can_start_schema}")
    print(f"  -> {endpoints_task.id} can_start: {can_start_endpoints}")

    assert can_start_schema is True, "无依赖的任务应该可以开始"
    assert can_start_endpoints is False, "依赖未完成的任务不应该可以开始"
    print(f"  [OK] can_start 检查正确")

    print("\n[PASS] 测试 3 通过：依赖关系正常")


def test_claim_and_complete():
    """测试 4: 认领和完成任务"""
    print("\n" + "="*50)
    print("测试 4: 认领和完成任务")
    print("="*50)

    tasks = list_tasks()
    schema_task = tasks[0]

    # 认领任务
    print(f"\n-> 认领任务 {schema_task.id}...")
    result = claim_task(schema_task.id, owner="test-agent")
    print(f"  -> {result}")

    # 验证状态
    from tasks import load_task
    task = load_task(schema_task.id)
    assert task.status == "in_progress", "状态应该是 in_progress"
    assert task.owner == "test-agent", "owner 应该是 test-agent"
    print(f"  [OK] 任务状态: {task.status}, owner: {task.owner}")

    # 完成任务
    print(f"\n-> 完成任务 {schema_task.id}...")
    result = complete_task(schema_task.id)
    print(f"  -> {result}")

    # 验证状态
    task = load_task(schema_task.id)
    assert task.status == "completed", "状态应该是 completed"
    print(f"  [OK] 任务状态: {task.status}")

    print("\n[PASS] 测试 4 通过：认领和完成流程正常")


def test_unblock_downstream():
    """测试 5: 下游任务解锁"""
    print("\n" + "="*50)
    print("测试 5: 下游任务解锁")
    print("="*50)

    # 找到被阻塞的任务
    tasks = list_tasks()
    endpoints_task = None
    for t in tasks:
        if t.blockedBy and t.status == "pending":
            endpoints_task = t
            break

    assert endpoints_task is not None, "应该有被阻塞的任务"
    print(f"\n-> 检查任务 {endpoints_task.id} 是否被解锁...")

    # 测试 can_start
    can_start_now = can_start(endpoints_task.id)
    print(f"  -> can_start: {can_start_now}")
    assert can_start_now is True, "依赖完成后应该可以开始"
    print(f"  [OK] 任务已解锁")

    # 认领并完成
    print(f"\n-> 认领并完成任务 {endpoints_task.id}...")
    claim_task(endpoints_task.id)
    result = complete_task(endpoints_task.id)
    print(f"  -> {result}")

    print("\n[PASS] 测试 5 通过：下游任务解锁正常")


def main():
    print("\n" + "=" * 50)
    print("任务系统测试".center(50))
    print("=" * 50)

    try:
        # 清理旧测试数据
        cleanup()

        # 运行测试
        test_basic_creation()
        test_list_and_get()
        test_dependencies()
        test_claim_and_complete()
        test_unblock_downstream()

        print("\n" + "="*50)
        print("所有测试完成！")
        print("="*50)

        # 显示最终状态
        print("\n最终任务列表:")
        tasks = list_tasks()
        for t in tasks:
            icon = {"pending": "O", "in_progress": "->", "completed": "[OK]"}[t.status]
            deps = f" (blockedBy: {', '.join(t.blockedBy)})" if t.blockedBy else ""
            print(f"  {icon} {t.id}: {t.subject} [{t.status}]{deps}")

        print(f"\n总计: {len(tasks)} 个任务")
        print(f"位置: {TASKS_DIR}")

    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n[WARN] 测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] 测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
