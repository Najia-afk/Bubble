# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================

#wsgi.py
from app import create_app

application = create_app()

if __name__ == "__main__":
    application.run()
#gunicorn wsgi:application -b :8000 --workers 13 --threads 3 &
#gunicorn wsgi:application -b :8000 &
#ps aux | grep 'gunicorn' | grep 'wsgi:application' | grep -v grep | awk '{print $2}' | xargs kill -9
#pkill -f 'gunicorn.*wsgi:application'
#pkill -f 'python.*app.py'

