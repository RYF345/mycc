"""
Tests for Tools/tools.py module.
"""
import pytest
from pathlib import Path


class TestSafePath:
    """Tests for safe_path function."""
    
    def test_safe_path_within_workspace(self, monkeypatch):
        """Test that paths within workspace are accepted."""
        from Tools import tools
        monkeypatch.setattr(tools, "WORKDIR", Path("E:/Coding_Project/Java/my_agent"))
        tools.CURRENT_TODOS = []
        
        # Reload to get patched WORKDIR
        from Tools.tools import safe_path
        result = safe_path("some_file.txt")
        assert isinstance(result, Path)
    
    def test_safe_path_escape_workspace(self, monkeypatch):
        """Test that paths escaping workspace are rejected."""
        from Tools import tools
        monkeypatch.setattr(tools, "WORKDIR", Path("E:/Coding_Project/Java/my_agent"))
        tools.CURRENT_TODOS = []
        
        from Tools.tools import safe_path
        with pytest.raises(ValueError, match="escapes workspace"):
            safe_path("../outside_file.txt")


class TestNormalizeTodos:
    """Tests for _normalize_todos function."""
    
    def test_normalize_valid_list(self):
        """Test normalizing a valid todo list."""
        from Tools.tools import _normalize_todos
        todos = [
            {"content": "Task 1", "status": "pending"},
            {"content": "Task 2", "status": "completed"},
        ]
        result, error = _normalize_todos(todos)
        assert error is None
        assert result == todos
    
    def test_normalize_invalid_status(self):
        """Test that invalid status is rejected."""
        from Tools.tools import _normalize_todos
        todos = [{"content": "Task", "status": "invalid"}]
        result, error = _normalize_todos(todos)
        assert "invalid status" in error
    
    def test_normalize_missing_content(self):
        """Test that missing content is rejected."""
        from Tools.tools import _normalize_todos
        todos = [{"status": "pending"}]
        result, error = _normalize_todos(todos)
        assert "missing" in error
    
    def test_normalize_json_string(self):
        """Test normalizing JSON string input."""
        from Tools.tools import _normalize_todos
        todos_str = '[{"content": "Task", "status": "pending"}]'
        result, error = _normalize_todos(todos_str)
        assert error is None
        assert len(result) == 1


class TestTodoWrite:
    """Tests for run_todo_write function."""
    
    def test_todo_write_valid(self):
        """Test writing valid todos."""
        from Tools.tools import run_todo_write
        todos = [{"content": "Test task", "status": "pending"}]
        result = run_todo_write(todos)
        assert "Updated" in result
    
    def test_todo_write_invalid_type(self):
        """Test that invalid type is rejected."""
        from Tools.tools import run_todo_write
        result = run_todo_write("not a list")
        assert "Error" in result


class TestGlob:
    """Tests for run_glob function."""
    
    def test_glob_find_files(self, monkeypatch):
        """Test finding files with glob pattern."""
        from Tools import tools
        monkeypatch.setattr(tools, "WORKDIR", Path("E:/Coding_Project/Java/my_agent"))
        tools.CURRENT_TODOS = []
        
        from Tools.tools import run_glob
        result = run_glob("*.txt")
        # Should find requirements.txt or return no matches
        assert isinstance(result, str)
    
    def test_glob_no_matches(self, monkeypatch):
        """Test glob with no matches."""
        from Tools import tools
        monkeypatch.setattr(tools, "WORKDIR", Path("E:/Coding_Project/Java/my_agent"))
        tools.CURRENT_TODOS = []
        
        from Tools.tools import run_glob
        result = run_glob("*.nonexistent_extension_xyz")
        assert "no matches" in result or result == ""