"""
Pytest configuration and fixtures for the agent project.
"""
import pytest
from pathlib import Path


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def temp_file(tmp_path):
    """Create a temporary file for testing."""
    file = tmp_path / "test_file.txt"
    file.write_text("test content")
    return file


@pytest.fixture
def sample_todos():
    """Sample todo list for testing."""
    return [
        {"content": "Task 1", "status": "pending"},
        {"content": "Task 2", "status": "in_progress"},
        {"content": "Task 3", "status": "completed"},
    ]