#!/bin/bash
# Updated deploy.sh with added functionalities

# Define paths and variables
PROJECT_ROOT="/home/swampy/Bubble"
APP_DIR="$PROJECT_ROOT"
VENV_PATH="/home/swampy/bubble-env"
LOG_DIR="/var/log/my-websites/website_bubble"
SOCK_DIR="/my-websites/website_bubble/app"
SOCK_PATH="$SOCK_DIR/website_bubble.sock"
NGINX_SITE_CONFIG="$PROJECT_ROOT/config/nginx/website_bubble.conf"
SYSTEMD_SERVICE_FILE="$PROJECT_ROOT/config/nginx/website_bubble.service"
SYSTEMD_SERVICE_PATH="/etc/systemd/system/website_bubble.service"
GUNICORN_SERVICE_NAME="website_bubble"

# Ensure log directory exists with secure permissions
if [ ! -d "$LOG_DIR" ]; then
   sudo mkdir -p "$LOG_DIR"
    echo "Created log directory with path: $LOG_DIR"
else
    echo "Log directory already exists: $LOG_DIR"
fi

# Secure the log directory
sudo chmod 750 "$LOG_DIR"

# Ensure socket directory exists with secure permissions
if [ ! -d "$SOCK_DIR" ]; then
   sudo mkdir -p "$SOCK_DIR"
    echo "Created socket directory with path: $SOCK_DIR"
else
    echo "Socket directory already exists: $SOCK_DIR"
fi

# Secure the socket directory
sudo chmod 750 "$SOCK_DIR"



# Activate virtual environment and install dependencies
source "$VENV_PATH/bin/activate"
pip install -r "$APP_DIR/config/requirements.txt"

# Check if Nginx configuration file exists
if [ -f "$NGINX_SITE_CONFIG" ]; then
    sudo cp "$NGINX_SITE_CONFIG" /etc/nginx/sites-available/
    sudo ln -sf "/etc/nginx/sites-available/website_bubble.conf" /etc/nginx/sites-enabled/
    echo "Nginx configuration linked successfully."
else
    echo "Nginx configuration file does not exist: $NGINX_SITE_CONFIG"
    exit 1
fi


# Check if Nginx is installed and running, start if not
if ! pgrep -x "nginx" > /dev/null; then
    echo "Nginx is not running, attempting to start Nginx..."
    sudo systemctl start nginx
    if ! pgrep -x "nginx" > /dev/null; then
        echo "Failed to start Nginx. Please check your Nginx configuration."
        exit 1
    fi
fi


# Copy the systemd service file and reload systemd daemon
sudo cp "$SYSTEMD_SERVICE_FILE" "$SYSTEMD_SERVICE_PATH"
sudo systemctl daemon-reload

# Manage Gunicorn service
if systemctl is-active --quiet "$GUNICORN_SERVICE_NAME"; then
    echo "Gunicorn service for website_bubble is already active. Restarting..."
    sudo systemctl restart "$GUNICORN_SERVICE_NAME"
else
    echo "Gunicorn service for website_bubble not active. Starting..."
    sudo systemctl enable "$GUNICORN_SERVICE_NAME"
    sudo systemctl start "$GUNICORN_SERVICE_NAME"
fi

echo "Deployment of website_bubble completed."
