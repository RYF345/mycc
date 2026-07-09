#!/usr/bin/env python3
"""
tasks.py - Task Management System

基于 DAG 的任务依赖管理系统，支持 blockedBy 关系。
"""

import json
import time
import random
from pathlib import Path
from dataclasses import dataclass, asdict

from config import WORKDIR

# ── 配置 ──────────────────────────────────────────────
TASKS_DIR = WORKDIR / ".tasks"
TASKS_DIR.mkdir(exist_ok=True)


# ── Task 数据类 ────────────────────────────────────────
@dataclass
class Task:
    """任务数据结构

    Fields:
        id: 唯一标识符，格式 "task_<timestamp>_<random>"
        subject: 任务标题（简短描述）
        description: 详细描述
        status: 状态 - "pending" | "in_progress" | "completed"
        owner: 任务所有者（多 agent 场景中使用，可为 None）
        blockedBy: 依赖的任务 ID 列表（必须全部完成才能开始）
    """
    id: str
    subject: str
    description: str
    status: str          # pending | in_progress | completed
    owner: str | None    # Agent name (multi-agent scenarios)
    blockedBy: list[str] # Dependency task IDs


# ── 基础存储函数 ────────────────────────────────────────
def _task_path(task_id: str) -> Path:
    """返回任务文件的路径

    Args:
        task_id: 任务 ID

    Returns:
        Path 对象，格式 .tasks/<task_id>.json

    业务逻辑：
    - 拼接 TASKS_DIR 和 task_id，后缀为 .json
    """
    return TASKS_DIR / f"{task_id}.json"


def save_task(task: Task):
    """将任务保存到磁盘

    Args:
        task: Task 对象

    业务逻辑：
    1. 使用 dataclasses.asdict() 转换为字典
    2. JSON 序列化，带缩进（indent=2）
    3. 写入 .tasks/<task_id>.json
    """
    _task_path(task.id).write_text(json.dumps(asdict(task), indent=2), encoding="utf-8")


def load_task(task_id: str) -> Task:
    """从磁盘加载任务

    Args:
        task_id: 任务 ID

    Returns:
        Task 对象

    Raises:
        FileNotFoundError: 如果任务文件不存在

    业务逻辑：
    1. 读取 .tasks/<task_id>.json 文件内容
    2. JSON 反序列化为字典
    3. 使用 **dict 解包创建 Task 对象
    """
    return Task(**json.loads(_task_path(task_id).read_text(encoding="utf-8")))


# ── ID 生成（时间戳 + 自增序列）────────────────────────
HIGHWATERMARK_FILE = TASKS_DIR / ".highwatermark"


def _next_task_id() -> str:
    """生成下一个任务 ID（时间戳 + 自增序列）

    Returns:
        任务 ID，格式 "task_<timestamp>_<sequence>"
        示例：task_1720512345_0001

    业务逻辑：
    1. 读取 .tasks/.highwatermark 文件，获取当前序列号
    2. 如果文件不存在，从 0 开始
    3. 递增序列号
    4. 写回 .highwatermark 文件
    5. 拼接时间戳和序列号，返回完整 ID

    特点：
    - 时间戳：便于调试，能看出创建时间
    - 序列号：保证唯一性，即使删除任务也不重用
    - 格式：task_<timestamp>_<sequence>（4位补零）
    """
    try:
        sequence = int(HIGHWATERMARK_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        sequence = 0

    next_sequence = sequence + 1
    HIGHWATERMARK_FILE.write_text(str(next_sequence), encoding="utf-8")

    timestamp = int(time.time())
    return f"task_{timestamp}_{next_sequence:04d}"


# ── 任务创建和查询 ─────────────────────────────────────
def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None) -> Task:
    """创建新任务

    Args:
        subject: 任务标题
        description: 详细描述（可选）
        blockedBy: 依赖的任务 ID 列表（可选）

    Returns:
        创建的 Task 对象

    业务逻辑：
    1. 调用 _next_task_id() 生成 ID（时间戳 + 序列号）
    2. 初始化 Task 对象：
       - status = "pending"
       - owner = None
       - blockedBy = blockedBy or []
    3. 调用 save_task() 持久化到磁盘
    4. 返回 Task 对象
    """
    task = Task(
        id=_next_task_id(),
        subject=subject,
        description=description,
        status="pending",
        owner=None,
        blockedBy=blockedBy or [],
    )
    save_task(task)
    return task


def list_tasks() -> list[Task]:
    """列出所有任务

    Returns:
        Task 对象列表，按序列号排序

    业务逻辑：
    1. 使用 glob 查找 .tasks/task_*.json 文件
    2. 读取每个文件，反序列化为 Task 对象
    3. 提取序列号（ID 的最后一部分），按序列号排序
    4. 返回 Task 列表
    """
    tasks = []
    for p in TASKS_DIR.glob("task_*.json"):
        try:
            task = Task(**json.loads(p.read_text(encoding="utf-8")))
            tasks.append(task)
        except Exception as e:
            print(f"Warning: Failed to load task {p.name}: {e}")

    # 按 ID 中的序列号排序（task_<timestamp>_<sequence> 中提取 sequence）
    tasks.sort(key=lambda t: int(t.id.split('_')[-1]) if '_' in t.id else 0)
    return tasks


def get_task(task_id: str) -> str:
    """获取任务详情（JSON 格式）

    Args:
        task_id: 任务 ID

    Returns:
        任务详情的 JSON 字符串

    业务逻辑：
    1. 调用 load_task() 加载任务
    2. 使用 asdict() 转换为字典
    3. JSON 序列化，带缩进（indent=2）
    4. 返回字符串（便于工具调用返回给 LLM）
    """
    task = load_task(task_id)
    return json.dumps(asdict(task), indent=2)


# ── 依赖检查和任务认领 ──────────────────────────────────
def can_start(task_id: str) -> bool:
    """检查任务是否可以开始（所有依赖是否都完成）

    Args:
        task_id: 任务 ID

    Returns:
        True 表示可以开始，False 表示被阻塞

    业务逻辑：
    1. 加载任务对象
    2. 遍历 blockedBy 列表中的每个依赖 ID
    3. 检查依赖文件是否存在：
       - 不存在 → 返回 False（防止引用错误 ID）
    4. 检查依赖状态是否为 "completed"：
       - 不是 completed → 返回 False
    5. 所有依赖都通过检查 → 返回 True

    边缘情况：
    - 缺失的依赖（文件不存在）视为 blocked
    - 避免因为引用错误 ID 而崩溃
    """
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False  # 依赖不存在，视为 blocked
        dep = load_task(dep_id)
        if dep.status != "completed":
            return False  # 依赖未完成
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    """认领任务（设置 owner，状态变为 in_progress）

    Args:
        task_id: 任务 ID
        owner: 认领者名称（默认 "agent"）

    Returns:
        操作结果消息字符串

    业务逻辑：
    1. 加载任务对象
    2. 检查状态是否为 "pending"：
       - 不是 pending → 返回错误消息（已被认领或已完成）
    3. 检查依赖是否都完成（调用 can_start）：
       - 有未完成的依赖 → 返回 blocked 消息，列出阻塞的依赖
    4. 设置 owner = owner
    5. 设置 status = "in_progress"
    6. 保存任务
    7. 返回成功消息

    多 agent 场景：
    - owner 字段记录谁在做这个任务
    - 防止重复认领（status 检查）
    """
    task = load_task(task_id)

    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"

    if not can_start(task_id):
        # 找出哪些依赖还没完成
        deps = [d for d in task.blockedBy
                if not _task_path(d).exists() or load_task(d).status != "completed"]
        return f"Blocked by: {deps}"

    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    print(f"  \033[36m[claim] {task.subject} -> in_progress (owner: {owner})\033[0m")
    return f"Claimed {task_id} ({task.subject})"


# ── 完成任务 ────────────────────────────────────────────
def complete_task(task_id: str) -> str:
    """完成任务并解锁下游任务

    Args:
        task_id: 任务 ID

    Returns:
        操作结果消息字符串（包含解锁的下游任务）

    业务逻辑：
    1. 加载任务对象
    2. 检查状态是否为 "in_progress"：
       - 不是 in_progress → 返回错误消息
    3. 设置 status = "completed"
    4. 保存任务
    5. 扫描所有任务，找出被解锁的下游任务：
       - status = "pending"（还未开始）
       - blockedBy 不为空（有依赖）
       - can_start() 返回 True（依赖都完成了）
    6. 打印完成消息（绿色）
    7. 如果有解锁的任务，打印解锁消息（黄色）
    8. 返回完成消息 + 解锁列表

    下游任务解锁：
    - 当前任务完成后，依赖它的任务可能变为可开始状态
    - 提示用户哪些任务现在可以认领了
    """
    task = load_task(task_id)

    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"

    task.status = "completed"
    save_task(task)

    # 找出被解锁的下游任务
    unblocked = [t.subject for t in list_tasks()
                 if t.status == "pending" and t.blockedBy and can_start(t.id)]

    print(f"  \033[32m[complete] {task.subject} [OK]\033[0m")

    msg = f"Completed {task_id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
        print(f"  \033[33m[unblocked] {', '.join(unblocked)}\033[0m")

    return msg
