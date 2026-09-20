#!/usr/bin/env python3
"""合成藻酸盐印模测试图（好/中/差），验证规则CV引擎各维度响应方向。"""
import cv2
import numpy as np
from scoring_impression import 藻酸盐取模评分引擎


def make_impression(path, quality='good', seed=0):
    rng = np.random.default_rng(seed)
    H, W = 700, 900
    img = np.full((H, W, 3), 40, np.uint8)  # 深色衬底

    # ── 马蹄形(U环)主体：外弧+反向内弧组成填充多边形 ──
    cx, cy = W // 2, H // 2
    R = 270
    thick = 130 if quality != 'bad' else 95
    a0, a1 = 205, 335
    outer = [(int(cx + R * np.cos(np.deg2rad(d))),
              int(cy + R * np.sin(np.deg2rad(d)))) for d in range(a0, a1)]
    inner = [(int(cx + (R - thick) * np.cos(np.deg2rad(d))),
              int(cy + (R - thick) * np.sin(np.deg2rad(d)))) for d in range(a1 - 1, a0 - 1, -1)]
    poly = np.array(outer + inner, np.int32)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    # 轻微不规则边缘，更像真实印模
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    base = np.array([150, 95, 220])  # BGR 饱和粉色（H≈167,S≈57，对齐真实藻酸盐）
    obj = np.clip(
        np.full_like(img, base).astype(np.int16) + np.random.normal(0, 7, img.shape),
        0, 255).astype(np.uint8)
    img = np.where(mask[:, :, None] > 0, obj, img)

    # ── 牙列纹理：牙尖小三角沿环带中线排列 ──
    if quality != 'bad':
        for deg in range(215, 328, 10):
            r = R - thick // 2 + rng.integers(-5, 6)
            x = int(cx + r * np.cos(np.deg2rad(deg)))
            y = int(cy + r * np.sin(np.deg2rad(deg)))
            cv2.circle(img, (x, y), 6, (78, 68, 118), -1)  # 孤立小暗坑，模拟牙窝
    if quality == 'bad':
        img = cv2.GaussianBlur(img, (9, 9), 0)

    # ── 气泡（暗圆坑），限制尝试次数防死循环 ──
    n_bub = {'good': 1, 'mid': 5, 'bad': 9}[quality]
    placed = 0
    for _ in range(5000):
        if placed >= n_bub:
            break
        deg = rng.integers(208, 332)
        r = R - rng.integers(12, thick - 8)
        x = int(cx + r * np.cos(np.deg2rad(deg)))
        y = int(cy + r * np.sin(np.deg2rad(deg)))
        if 0 <= y < H and 0 <= x < W and mask[y, x] > 0:
            rad = int(rng.integers(6, 15))
            cv2.circle(img, (x, y), rad, (85, 80, 120), -1)
            placed += 1

    if quality == 'bad':
        # 撕裂：细长黑线
        cv2.line(img, (cx - 185, cy + 55), (cx - 95, cy + 125), (45, 45, 70), 3)
        cv2.line(img, (cx + 150, cy - 185), (cx + 215, cy - 120), (45, 45, 70), 3)
        # 托盘外露：大块异色光滑区
        cv2.ellipse(img, (cx + 205, cy - 150), (38, 22), 30, 0, 360, (60, 190, 210), -1)
        # 血迹
        cv2.circle(img, (cx - 200, cy - 120), 12, (60, 60, 180), -1)

    cv2.imwrite(path, img)
    return path


if __name__ == '__main__':
    e = 藻酸盐取模评分引擎()
    for q in ('good', 'mid', 'bad'):
        p = make_impression(f'/tmp/imp_{q}.jpg', q, seed=hash(q) & 0xffff)
        r = e.analyze_jaw(p, 'upper')
        print(f'\n===== {q} =====')
        if not r.ok:
            print('识别失败:', r.error); continue
        print(f'总分 {r.total_score}/100  严重变形={r.severe_deformity} 关键区缺失={r.key_area_missing} 积水={r.water_warning}')
        for d in r.dimensions:
            print(f'  {d.name:<12} {d.score:>5}/{d.max_score} [{d.status}] {d.detail}')
        print('metrics:', r.metrics)
