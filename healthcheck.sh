#!/bin/bash
# 运行目录写入自检：发现写不进去→修属主+重启+记录（防 rsync 属主坑、磁盘满等）
cd /opt/aiscore || exit 1
BAD=""
for d in scores attempts reports uploads 成绩导出 exam_data consult_logs logs; do
  [ -d "$d" ] || continue
  if ! sudo -u ubuntu touch "$d/.wtest" 2>/dev/null; then BAD="$BAD $d"; fi
  rm -f "$d/.wtest" 2>/dev/null
done
if [ -n "$BAD" ]; then
  echo "$(date "+%F %T") 写入失败目录:$BAD → 修复属主并重启"
  chown -R ubuntu:ubuntu /opt/aiscore
  systemctl restart aiscore
  echo "$(date "+%F %T") 修复完成，服务状态: $(systemctl is-active aiscore)"
else
  echo "$(date "+%F %T") 自检通过，所有目录可写"
fi
