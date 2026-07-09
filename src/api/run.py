"""Entry point to run the API server."""
from src.api.app import create_app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)