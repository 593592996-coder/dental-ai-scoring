#!/bin/bash
# ============================================================
# 口腔AI评分系统 腾讯云部署脚本（Ubuntu 22.04，root 执行）
# 前置：代码已 rsync 到 /opt/aipingfen（含 reports/uploads 数据）
# 用法：bash /opt/aipingfen/deploy_tencent/server_setup.sh
# 访问：http://162.14.98.126/score/
# ============================================================
set -e
APP_DIR=/opt/aipingfen

echo "▶ 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-pip python3-venv

echo "▶ 创建虚拟环境并安装依赖（含 opencv/numpy，约2-4分钟）..."
cd $APP_DIR
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

echo "▶ 配置 systemd 常驻..."
cat > /etc/systemd/system/aipingfen.service <<EOF
[Unit]
Description=KouQiang AI Scoring System (aipingfen)
After=network.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/gunicorn -w 2 -b 127.0.0.1:5050 --timeout 300 app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable aipingfen
systemctl restart aipingfen

echo "▶ 配置 nginx 子路径 /score/ ..."
NGINX_CONF=/etc/nginx/sites-available/default
if [ ! -f "$NGINX_CONF" ]; then NGINX_CONF=$(grep -rl 'server_name' /etc/nginx/sites-enabled/ | head -1); fi
cp $NGINX_CONF ${NGINX_CONF}.bak_$(date +%m%d)
cat $NGINX_CONF deploy_tencent/nginx_score.location > /tmp/nginx_new.conf
cp /tmp/nginx_new.conf $NGINX_CONF
nginx -t && systemctl reload nginx

echo "▶ 配置每日自动备份（凌晨3:30，保留7天）..."
chmod +x $APP_DIR/deploy_tencent/backup_daily.sh
( crontab -l 2>/dev/null | grep -v backup_daily ; echo '30 3 * * * /opt/aipingfen/deploy_tencent/backup_daily.sh' ) | crontab -

sleep 2
systemctl status aipingfen --no-pager | head -6
echo ""
echo "✅ 部署完成：http://162.14.98.126/score/  (教师后台 /score/admin 密码 aimei2026)"
