"""Flask API application for my_agent project."""
from flask import Flask, jsonify, request
from src.database import get_connection, init_database


def create_app() -> Flask:
    """Create and configure the Flask application.
    
    Returns:
        Flask: Configured Flask application
    """
    app = Flask(__name__)
    
    # Initialize database on startup
    init_database()
    
    # Health check endpoint
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """Health check endpoint."""
        return jsonify({'status': 'healthy', 'message': 'Service is running'}), 200
    
    # Tasks endpoints
    @app.route('/api/tasks', methods=['GET'])
    def get_tasks():
        """Get all tasks."""
        conn = get_connection()
        try:
            cursor = conn.execute('SELECT * FROM tasks ORDER BY created_at DESC')
            tasks = [dict(row) for row in cursor.fetchall()]
            return jsonify({'tasks': tasks}), 200
        finally:
            conn.close()
    
    @app.route('/api/tasks/<int:task_id>', methods=['GET'])
    def get_task(task_id: int):
        """Get a specific task by ID."""
        conn = get_connection()
        try:
            cursor = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
            task = cursor.fetchone()
            if task:
                return jsonify({'task': dict(task)}), 200
            return jsonify({'error': 'Task not found'}), 404
        finally:
            conn.close()
    
    @app.route('/api/tasks', methods=['POST'])
    def create_task():
        """Create a new task."""
        data = request.get_json()
        if not data or 'subject' not in data:
            return jsonify({'error': 'Subject is required'}), 400
        
        conn = get_connection()
        try:
            cursor = conn.execute(
                'INSERT INTO tasks (subject, description, status, owner) VALUES (?, ?, ?, ?)',
                (data['subject'], data.get('description'), data.get('status', 'pending'), data.get('owner'))
            )
            conn.commit()
            return jsonify({'id': cursor.lastrowid, 'message': 'Task created successfully'}), 201
        finally:
            conn.close()
    
    @app.route('/api/tasks/<int:task_id>', methods=['PUT'])
    def update_task(task_id: int):
        """Update a task."""
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        conn = get_connection()
        try:
            # Build dynamic update query
            fields = []
            values = []
            for field in ['subject', 'description', 'status', 'owner']:
                if field in data:
                    fields.append(f'{field} = ?')
                    values.append(data[field])
            
            if not fields:
                return jsonify({'error': 'No valid fields to update'}), 400
            
            values.append(task_id)
            conn.execute(
                f'UPDATE tasks SET {", ".join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                values
            )
            conn.commit()
            return jsonify({'message': 'Task updated successfully'}), 200
        finally:
            conn.close()
    
    @app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
    def delete_task(task_id: int):
        """Delete a task."""
        conn = get_connection()
        try:
            conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            conn.commit()
            return jsonify({'message': 'Task deleted successfully'}), 200
        finally:
            conn.close()
    
    # Memory endpoints
    @app.route('/api/memories', methods=['GET'])
    def get_memories():
        """Get all memory entries."""
        conn = get_connection()
        try:
            cursor = conn.execute('SELECT * FROM memory_entries ORDER BY created_at DESC')
            memories = [dict(row) for row in cursor.fetchall()]
            return jsonify({'memories': memories}), 200
        finally:
            conn.close()
    
    @app.route('/api/memories', methods=['POST'])
    def create_memory():
        """Create a new memory entry."""
        data = request.get_json()
        if not data or 'name' not in data or 'content' not in data:
            return jsonify({'error': 'Name and content are required'}), 400
        
        conn = get_connection()
        try:
            cursor = conn.execute(
                'INSERT INTO memory_entries (name, content, memory_type) VALUES (?, ?, ?)',
                (data['name'], data['content'], data.get('memory_type', 'general'))
            )
            conn.commit()
            return jsonify({'id': cursor.lastrowid, 'message': 'Memory created successfully'}), 201
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Memory with this name already exists'}), 409
        finally:
            conn.close()
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)