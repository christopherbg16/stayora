from app import app
import os

if __name__ == '__main__':
    app.run(
        debug=os.environ.get('FLASK_DEBUG', '').lower() == 'true',
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '5000')),
    )
