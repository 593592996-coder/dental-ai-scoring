#!/usr/bin/env python3
"""
公网隧道 — 使用localhost.run (SSH)，无需注册账号
将本地5050端口暴露到公网，手机流量也能访问
"""
import subprocess, re, sys, signal, os

PORT = 5050

def start_tunnel():
    print("正在创建公网隧道...")
    cmd = [
        'ssh', '-o', 'StrictHostKeyChecking=no',
        '-o', 'ServerAliveInterval=30',
        '-R', f'80:localhost:{PORT}',
        'nokey@localhost.run'
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    url_found = None
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                print(line)
            # localhost.run URL pattern
            match = re.search(r'https?://[a-zA-Z0-9-]+\.lhr\.(life|domains)', line)
            if match and not url_found:
                url_found = match.group(0)
                print("\n" + "=" * 60)
                print(f"  🎉 公网访问地址（手机流量也能打开）:")
                print(f"  {url_found}")
                print("=" * 60)
                print("\n按 Ctrl+C 停止隧道\n")
    except KeyboardInterrupt:
        print("\n隧道已停止")
    finally:
        proc.terminate()
        proc.wait()

if __name__ == '__main__':
    start_tunnel()
