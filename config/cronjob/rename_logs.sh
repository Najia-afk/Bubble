#!/bin/bash
current_date_time="$(date +%Y-%m-%d_%H-%M-%S)"

log_file1="/tmp/Postgres_db_connection_log"
log_file2="/tmp/cron-log"
log_file3="/tmp/app.log"

if [ -f "$log_file1" ]; then
  mv "$log_file1" "$log_file1.$current_date_time"
fi

if [ -f "$log_file2" ]; then
  mv "$log_file2" "$log_file2.$current_date_time"
fi

if [ -f "$log_file3" ]; then
  mv "$log_file3" "$log_file3.$current_date_time"
fi
