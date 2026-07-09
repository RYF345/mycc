"""
API Endpoints Module
Provides RESTful API endpoints for users and posts.
"""

from flask import Flask, request, jsonify
from functools import wraps

app = Flask(__name__)

# In-memory database simulation
users_db = {}
posts_db = {}
user_id_counter = 1
post_id_counter = 1


# ============ Users API ============

@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users."""
    return jsonify({
        'success': True,
        'data': list(users_db.values())
    })


@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    """Get a specific user by ID."""
    if user_id not in users_db:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    return jsonify({'success': True, 'data': users_db[user_id]})


@app.route('/api/users', methods=['POST'])
def create_user():
    """Create a new user."""
    global user_id_counter
    data = request.get_json()
    
    if not data or 'username' not in data or 'email' not in data:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    user = {
        'id': user_id_counter,
        'username': data['username'],
        'email': data['email']
    }
    users_db[user_id_counter] = user
    user_id_counter += 1
    
    return jsonify({'success': True, 'data': user}), 201


@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """Update a user."""
    if user_id not in users_db:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    data = request.get_json()
    user = users_db[user_id]
    
    if 'username' in data:
        user['username'] = data['username']
    if 'email' in data:
        user['email'] = data['email']
    
    return jsonify({'success': True, 'data': user})


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user."""
    if user_id not in users_db:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    del users_db[user_id]
    return jsonify({'success': True, 'message': 'User deleted'})


# ============ Posts API ============

@app.route('/api/posts', methods=['GET'])
def get_posts():
    """Get all posts."""
    return jsonify({
        'success': True,
        'data': list(posts_db.values())
    })


@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    """Get a specific post by ID."""
    if post_id not in posts_db:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    return jsonify({'success': True, 'data': posts_db[post_id]})


@app.route('/api/posts', methods=['POST'])
def create_post():
    """Create a new post."""
    global post_id_counter
    data = request.get_json()
    
    if not data or 'user_id' not in data or 'title' not in data:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    if data['user_id'] not in users_db:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    post = {
        'id': post_id_counter,
        'user_id': data['user_id'],
        'title': data['title'],
        'content': data.get('content', '')
    }
    posts_db[post_id_counter] = post
    post_id_counter += 1
    
    return jsonify({'success': True, 'data': post}), 201


@app.route('/api/posts/<int:post_id>', methods=['PUT'])
def update_post(post_id):
    """Update a post."""
    if post_id not in posts_db:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    
    data = request.get_json()
    post = posts_db[post_id]
    
    if 'title' in data:
        post['title'] = data['title']
    if 'content' in data:
        post['content'] = data['content']
    
    return jsonify({'success': True, 'data': post})


@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    """Delete a post."""
    if post_id not in posts_db:
        return jsonify({'success': False, 'error': 'Post not found'}), 404
    
    del posts_db[post_id]
    return jsonify({'success': True, 'message': 'Post deleted'})


# ============ Health Check ============

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)