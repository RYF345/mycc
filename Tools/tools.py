import json, ast, subprocess
from pathlib import Path

from config import WORKDIR

# ── Global state ──────────────────────────────────────────
CURRENT_TODOS: list[dict] = []

# ── Tool definitions ─────────────────────────────────────
TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "todo_write", "description": "Create and manage a task list for your current coding session.",
     "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["content", "status"]}}}, "required": ["todos"]}},
    {"name": "load_skill", "description": "Load the full content of a skill by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "compact", "description": "Manually trigger context compaction to free up space. Use when context is getting large.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "debug_messages", "description": "Show current message count and recent message info for debugging compact feature.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "create_task", "description": "Create a new task with optional blockedBy dependencies.",
     "input_schema": {"type": "object", "properties": {"subject": {"type": "string", "description": "Task title"}, "description": {"type": "string", "description": "Detailed description (optional)"}, "blockedBy": {"type": "array", "items": {"type": "string"}, "description": "List of task IDs that must be completed first (optional)"}}, "required": ["subject"]}},
    {"name": "list_tasks", "description": "List all tasks with their status, owner, and dependencies.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_task", "description": "Get full details of a specific task by ID.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string", "description": "Task ID"}}, "required": ["task_id"]}},
    {"name": "claim_task", "description": "Claim a pending task. Sets owner and changes status to in_progress.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string", "description": "Task ID to claim"}}, "required": ["task_id"]}},
    {"name": "complete_task", "description": "Complete an in-progress task. Reports unblocked downstream tasks.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string", "description": "Task ID to complete"}}, "required": ["task_id"]}},
]


# ── Tool implementations ─────────────────────────────────
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, timeout=120)
        out = ((r.stdout or b"") + (r.stderr or b""))
        try:
            out = out.decode("utf-8")
        except UnicodeDecodeError:
            out = out.decode("gbk", errors="replace")
        out = out.strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    import glob as g
    try:
        results = []
        for match in g.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"
    

def _normalize_todos(todos):
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"
    for i, t in enumerate(todos):
        if not isinstance(t, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "content" not in t or "status" not in t:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if t["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{t['status']}'"
    return todos, None

def run_todo_write(todos: list | None) -> str:
    global CURRENT_TODOS
    todos, error = _normalize_todos(todos)
    if error:
        return error
    assert todos is not None  # 告诉类型检查器这里 todos 不是 None
    CURRENT_TODOS = todos
    lines = ["\n\033[33m## Current Tasks\033[0m"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m", "completed": "\033[32m✓\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"


def run_compact() -> str:
    """
    Compact 工具的处理函数

    业务逻辑：
    - 这个函数只是返回占位符信息
    - 真正的压缩逻辑在 agent_loop.py 中处理
    - 当检测到 compact 工具调用时，agent_loop 会：
      1. 调用 compact_history(messages)
      2. 返回此函数的结果
      3. break 结束当前 turn，用压缩后的上下文开始新一轮

    Returns:
        占位符信息（真正的压缩在 agent_loop 中执行）
    """
    return "[Compact requested. History will be summarized.]"


def run_load_skill(name: str) -> str:
    """
    Load skill 工具的处理函数

    Args:
        name: 技能名称

    Returns:
        技能的完整内容

    业务逻辑：
    - 从 skill_using 模块导入 load_skill 函数
    - 返回技能的完整内容，供 LLM 使用
    """
    from skill_using import load_skill
    return load_skill(name)


TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob, "todo_write": run_todo_write,
    "compact": run_compact, "load_skill": run_load_skill,
}


# ── Task tool implementations ────────────────────────────
def run_create_task(subject: str, description: str = "", blockedBy: list[str] | None = None) -> str:
    """创建任务的工具处理函数"""
    from tasks import create_task
    task = create_task(subject, description, blockedBy)
    deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
    print(f"  \033[34m[create] {task.subject}{deps}\033[0m")
    return f"Created {task.id}: {task.subject}{deps}"


def run_list_tasks() -> str:
    """列出所有任务的工具处理函数"""
    from tasks import list_tasks
    tasks = list_tasks()
    if not tasks:
        return "No tasks. Use create_task to add some."
    lines = []
    for t in tasks:
        icon = {"pending": "○", "in_progress": "●", "completed": "✓"}.get(t.status, "?")
        deps = f" (blockedBy: {', '.join(t.blockedBy)})" if t.blockedBy else ""
        owner = f" [{t.owner}]" if t.owner else ""
        lines.append(f"  {icon} {t.id}: {t.subject} [{t.status}]{owner}{deps}")
    return "\n".join(lines)


def run_get_task(task_id: str) -> str:
    """获取任务详情的工具处理函数"""
    from tasks import get_task
    try:
        return get_task(task_id)
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


def run_claim_task(task_id: str) -> str:
    """认领任务的工具处理函数"""
    from tasks import claim_task
    try:
        return claim_task(task_id, owner="agent")
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


def run_complete_task(task_id: str) -> str:
    """完成任务的工具处理函数"""
    from tasks import complete_task
    try:
        return complete_task(task_id)
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


# 更新 TOOL_HANDLERS 添加任务工具
TOOL_HANDLERS.update({
    "create_task": run_create_task,
    "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task,
    "complete_task": run_complete_task,
})
