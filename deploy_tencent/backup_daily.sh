#!/bin/bash
# 口腔AI评分系统 每日数据备份（reports + uploads + 花名册），保留最近7份
mkdir -p /opt/backups/aipingfen
cd /opt/aipingfen
tar czf /opt/backups/aipingfen/data_$(date +%Y%m%d_%H%M).tgz reports uploads 花名册 banned.json 2>/dev/null
ls -t /opt/backups/aipingfen/data_*.tgz 2>/dev/null | tail -n +8 | xargs -r rm -f
echo "backup done: $(ls -t /opt/backups/aipingfen/*.tgz | head -1)"
