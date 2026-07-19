#!/bin/bash
# ============================================================
# II类洞AI评分系统 — 一键公网启动
# 手机流量也能访问，无需同一WiFi
# ============================================================
cd /Users/ouyangjunhan/Desktop/AI评分系统

echo "=========================================="
echo "  II类洞AI评分系统"
echo "=========================================="

# 1. Kill old processes
pkill -f 'python3 app.py' 2>/dev/null
pkill -f 'tunnel.py' 2>/dev/null
sleep 1

# 2. Start web server
echo "▶  启动本地服务..."
nohup python3 app.py > server.log 2>&1 &
sleep 2

# 3. Start public tunnel
echo "▶  创建公网隧道（无需注册，无需同一WiFi）..."
python3 tunnel.py

# When tunnel stops (Ctrl+C), also kill the server
pkill -f 'python3 app.py' 2>/dev/null
echo "系统已停止"
