"""Tests for API endpoints."""
import pytest
import tempfile
import os
from pathlib import Path
from src.api.app import create_app
from src.database import get_connection, init_database


@pytest.fixture
def app():
    """Create a test application."""
    # Use a temporary database for testing
    test_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    test_db.close()
    
    # Set test database path
    import src.database.connection as db_conn
    original_path = db_conn.DATABASE_PATH
    db_conn.DATABASE_PATH = Path(test_db.name)
    
    app = create_app()
    app.config['TESTING'] = True
    
    yield app
    
    # Cleanup
    db_conn.DATABASE_PATH = original_path
    os.unlink(test_db.name)


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


class TestHealthEndpoint:
    """Tests for health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check returns healthy status."""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'


class TestTasksEndpoints:
    """Tests for task endpoints."""
    
    def test_get_tasks_empty(self, client):
        """Test getting tasks when empty."""
        response = client.get('/api/tasks')
        assert response.status_code == 200
        data = response.get_json()
        assert data['tasks'] == []
    
    def test_create_task(self, client):
        """Test creating a new task."""
        response = client.post('/api/tasks', json={
            'subject': 'Test Task',
            'description': 'Test Description',
            'status': 'pending'
        })
        assert response.status_code == 201
        data = response.get_json()
        assert 'id' in data
        assert data['message'] == 'Task created successfully'
    
    def test_create_task_missing_subject(self, client):
        """Test creating a task without subject fails."""
        response = client.post('/api/tasks', json={
            'description': 'Test Description'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
    
    def test_get_task_by_id(self, client):
        """Test getting a specific task."""
        # Create a task first
        client.post('/api/tasks', json={'subject': 'Test Task'})
        
        response = client.get('/api/tasks/1')
        assert response.status_code == 200
        data = response.get_json()
        assert data['task']['subject'] == 'Test Task'
    
    def test_get_task_not_found(self, client):
        """Test getting non-existent task."""
        response = client.get('/api/tasks/999')
        assert response.status_code == 404
    
    def test_update_task(self, client):
        """Test updating a task."""
        # Create a task first
        client.post('/api/tasks', json={'subject': 'Original Task'})
        
        response = client.put('/api/tasks/1', json={
            'subject': 'Updated Task',
            'status': 'in_progress'
        })
        assert response.status_code == 200
        
        # Verify update
        response = client.get('/api/tasks/1')
        data = response.get_json()
        assert data['task']['subject'] == 'Updated Task'
        assert data['task']['status'] == 'in_progress'
    
    def test_delete_task(self, client):
        """Test deleting a task."""
        # Create a task first
        client.post('/api/tasks', json={'subject': 'Task to Delete'})
        
        response = client.delete('/api/tasks/1')
        assert response.status_code == 200
        
        # Verify deletion
        response = client.get('/api/tasks/1')
        assert response.status_code == 404


class TestMemoryEndpoints:
    """Tests for memory endpoints."""
    
    def test_get_memories_empty(self, client):
        """Test getting memories when empty."""
        response = client.get('/api/memories')
        assert response.status_code == 200
        data = response.get_json()
        assert data['memories'] == []
    
    def test_create_memory(self, client):
        """Test creating a new memory."""
        response = client.post('/api/memories', json={
            'name': 'test_memory',
            'content': 'Test content',
            'memory_type': 'general'
        })
        assert response.status_code == 201
        data = response.get_json()
        assert 'id' in data
    
    def test_create_memory_missing_fields(self, client):
        """Test creating memory without required fields fails."""
        response = client.post('/api/memories', json={'name': 'test'})
        assert response.status_code == 400
    
    def test_create_duplicate_memory(self, client):
        """Test creating duplicate memory fails."""
        client.post('/api/memories', json={
            'name': 'duplicate',
            'content': 'First'
        })
        
        response = client.post('/api/memories', json={
            'name': 'duplicate',
            'content': 'Second'
        })
        assert response.status_code == 409


if __name__ == '__main__':
    pytest.main([__file__, '-v'])