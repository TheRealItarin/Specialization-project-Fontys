#!/bin/bash


export XKB_DEFAULT_LAYOUT=hu


cd /opt/auth_service
uvicorn main:app --host 0.0.0.0 --port 5000 &
AUTH_PID=$!
cd /


nginx


trap '[[ -n "$AUTH_PID" ]] && kill "$AUTH_PID" 2>/dev/null' EXIT
tail -f /dev/null