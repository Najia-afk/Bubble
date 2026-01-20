#!/bin/bash

# Check if redis is running
if systemctl is-active --quiet redis-server; then
    echo "redis is running. Restarting redis..."
    sudo systemctl restart redis-server
else
    echo "redis is not running. Starting redis..."
    sudo systemctl start redis-server
fi

# Wait a bit for redis to fully start
sleep 5

# Kill existing Gunicorn processes
echo "Killing existing Gunicorn processes..."
pkill -f 'gunicorn.*wsgi:application'

# Start Gunicorn
echo "Starting Gunicorn..."
gunicorn wsgi:application -b :8000 --workers 13 --threads 3 &

# Wait a bit for Gunicorn to start
sleep 5

# Kill existing Celery worker processes
echo "Killing existing Celery workers..."
pkill -f 'celery.*worker'

# Start Celery worker
echo "Starting Celery worker..."
celery -A celery_worker.celery_app worker -l info -P solo &
