"""
Tests for Tools/sub_agent_tool.py module.
"""
import pytest


class TestExtractText:
    """Tests for extract_text function."""
    
    def test_extract_text_from_string(self):
        """Test extracting text from plain string."""
        from Tools.sub_agent_tool import extract_text
        result = extract_text("hello world")
        assert result == "hello world"
    
    def test_extract_text_from_list(self):
        """Test extracting text from content blocks list."""
        from Tools.sub_agent_tool import extract_text
        
        # Create mock content blocks
        class MockBlock:
            def __init__(self, text, block_type):
                self.text = text
                self.type = block_type
        
        content = [
            MockBlock("Hello", "text"),
            MockBlock("World", "text"),
        ]
        result = extract_text(content)
        assert "Hello" in result
        assert "World" in result
    
    def test_extract_text_empty(self):
        """Test extracting text from empty content."""
        from Tools.sub_agent_tool import extract_text
        result = extract_text([])
        assert result == ""


class TestSubAgentTools:
    """Tests for subagent tool definitions."""
    
    def test_sub_tools_defined(self):
        """Test that SUB_TOOLS has expected tools."""
        from Tools.sub_agent_tool import SUB_TOOLS
        
        tool_names = [t["name"] for t in SUB_TOOLS]
        assert "bash" in tool_names
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names
        assert "glob" in tool_names
        # task should NOT be in SUB_TOOLS (no recursive spawning)
        assert "task" not in tool_names
    
    def test_sub_handlers_defined(self):
        """Test that SUB_HANDLERS has expected handlers."""
        from Tools.sub_agent_tool import SUB_HANDLERS
        
        assert "bash" in SUB_HANDLERS
        assert "read_file" in SUB_HANDLERS
        assert "write_file" in SUB_HANDLERS
        assert "edit_file" in SUB_HANDLERS
        assert "glob" in SUB_HANDLERS


class TestTaskToolRegistration:
    """Tests for task tool registration."""
    
    def test_task_tool_added_to_tools(self):
        """Test that task tool is added to parent TOOLS."""
        from Tools.tools import TOOLS
        
        tool_names = [t["name"] for t in TOOLS]
        assert "task" in tool_names
    
    def test_task_handler_registered(self):
        """Test that task handler is registered."""
        from Tools.tools import TOOL_HANDLERS
        
        assert "task" in TOOL_HANDLERS