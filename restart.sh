#!/bin/bash
# II类洞AI评分系统 — 一键重启脚本
cd /Users/ouyangjunhan/Desktop/AI评分系统
pkill -f 'python3 app.py' 2>/dev/null
sleep 1
echo "启动 II类洞AI评分系统..."
nohup python3 app.py > server.log 2>&1 &
sleep 2
echo ""
echo "=========================================="
echo "  II类洞AI评分系统 已启动"
echo "  学生端: http://localhost:5050/"
echo "  教师端: http://localhost:5050/dashboard"
echo "  局域网: http://$(ipconfig getifaddr en0 2>/dev/null || echo 'YOUR_IP'):5050/"
echo "=========================================="
echo ""
echo "查看日志: tail -f /Users/ouyangjunhan/Desktop/AI评分系统/server.log"
echo "停止服务: pkill -f 'python3 app.py'"
