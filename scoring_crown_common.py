#!/usr/bin/env python3
"""
全瓷冠牙体预备 AI 评分 — 公共工具（前牙11/21、后牙16/26/36/46 共用）

对标金砖赛 Fair Grader 2000 三维评分思路（各面切削量 / 肩台 / 聚合度 / 3D偏差），
在仅有 2D 照片 + 硅胶导板剖面的条件下做近似量化：
  · 磨除量(mm)：硅胶导板复位后的剖面照片，测"导板内壁—预备体表面"缝隙，靠毫米标尺标定
  · 聚合度(°) ：邻面侧位照片，多边形逼近测预备体两侧壁夹角
  · 肩台/光滑/损伤：正位、颈缘特写做轮廓与边缘梯度分析

注意：2D+导板为近似值，报告明确标注"最终以赛场3D扫描为准"。
"""

import cv2
import math
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class CrownMeasure:
    name: str
    score: float
    max_score: float
    raw_value: float
    ideal_value: str
    unit: str
    detail: str
    status: str           # good / warning / bad / skip
    process_analysis: str = ''
    targeted_suggestion: str = ''
    sub_scores: List[dict] = field(default_factory=list)


@dataclass
class CrownReport:
    total_score: float = 0
    max_total: float = 100
    tooth: str = ''
    dimensions: List[CrownMeasure] = field(default_factory=list)
    overall_assessment: str = ''
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    equipment_score: float = 0.0   # 对标 Fair Grader 设备分（总分×0.35，满分35）
    slots_present: list = field(default_factory=list)   # 实际有效识别的照片槽位


# 6 张照片的槽位键 → 中文名
SLOTS = {
    'pre':       '①术前正位',
    'post':      '②术后正位',
    'occlusal':  '③切端/合面位',
    'lateral':   '④邻面侧位',
    'margin':    '⑤颈缘特写',
    'guide':     '⑥硅胶导板剖面',
}


def gauss_dev(value, lo, hi, k=8.0, hard=None):
    """满分区间[lo,hi]内返回1；区间外按高斯衰减。
    hard=(low,high)：超出硬边界直接压到≤0.25。k 越大衰减越陡。"""
    if lo <= value <= hi:
        return 1.0
    d = (lo - value) if value < lo else (value - hi)
    rate = math.exp(-k * d * d)
    if hard:
        hlo, hhi = hard
        if value < hlo or value > hhi:
            rate = min(rate, 0.25)
    return max(0.0, min(1.0, rate))


def status_of(rate, good=0.8, warn=0.5):
    return 'good' if rate >= good else ('warning' if rate >= warn else 'bad')


def load_gray(path, max_dim=1000):
    img = cv2.imread(path)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        s = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img, gray


def largest_contour(gray, inv=True):
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    flag = cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY
    _, binary = cv2.threshold(blur, 0, 255, flag + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, binary
    return max(contours, key=cv2.contourArea), binary


# ── 毫米标尺标定：优先识别画面中已知长度的标定物；失败则用牙冠经验宽度回退 ──
def calibrate_mm(gray, contour, fallback_tooth_width_mm):
    """返回 px→mm。先尝试 Hough 直线找标尺刻度（简化：用轮廓外接宽与经验牙宽）。
    教学场景下更稳妥的做法是让标尺与牙同框，这里以预备体/牙的外接宽度做经验标定，
    并在报告中提示数值为近似。"""
    if contour is None:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    ref = max(w, h)
    if ref <= 0:
        return None
    return fallback_tooth_width_mm / ref


def measure_reduction(gray, contour, scale_mm, n_samples=12):
    """硅胶导板剖面缝隙测磨除厚度（mm）。
    思路：剖面中预备体(深色树脂/牙)与外层导板(浅色硅胶)之间形成一圈亮缝隙，
    沿轮廓法线方向由内向外扫描，统计首次跨到高亮硅胶前的暗带宽度。
    返回 (各点厚度mm列表, 均值, 最小值, 离散cv)。纯图像启发式，失败返回None。"""
    if contour is None or scale_mm is None:
        return None
    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    er = cv2.erode(mask, np.ones((5, 5), np.uint8), iterations=1)
    ring = mask - er
    ys, xs = np.where(ring > 0)
    if len(xs) < n_samples:
        return None
    pick = np.linspace(0, len(xs) - 1, n_samples).astype(int)
    M = cv2.moments(contour)
    cx = M['m10'] / max(M['m00'], 1e-6)
    cy = M['m01'] / max(M['m00'], 1e-6)
    thickness_px = []
    H, W = gray.shape
    for i in pick:
        x, y = int(xs[i]), int(ys[i])
        dx, dy = x - cx, y - cy
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm
        # 由边缘向外走，亮缝隙+硅胶会使灰度明显升高；记录升高前的距离
        d_px = 0
        for step in range(2, 60):
            xx, yy = int(x + dx * step), int(y + dy * step)
            if not (0 <= xx < W and 0 <= yy < H):
                break
            if int(gray[yy, xx]) > int(gray[y, x]) + 35:
                d_px = step
                break
        if d_px > 0:
            thickness_px.append(d_px)
    if len(thickness_px) < 4:
        return None
    vals = np.array(thickness_px, dtype=float) * scale_mm
    mean = float(np.mean(vals))
    mn = float(np.min(vals))
    cv = float(np.std(vals) / mean) if mean > 1e-6 else 1.0
    return vals.tolist(), mean, mn, cv


def measure_reduction_dirs(path, scale_mm, n_samples=24):
    """导板剖面按法线方向分组测磨除厚度。
    假定照片竖直放置：竖直方向法线(上下) → 'vert' 切端/合面磨除；
    水平方向法线(左右) → 'horz' 唇/颊/舌轴面磨除。
    返回 {'vert':[mm...], 'horz':[mm...]}，失败返回None。"""
    img, gray = load_gray(path)
    if gray is None:
        return None
    contour, _ = largest_contour(gray)
    if contour is None or scale_mm is None:
        return None
    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    ring = mask - cv2.erode(mask, np.ones((5, 5), np.uint8), iterations=1)
    ys, xs = np.where(ring > 0)
    if len(xs) < n_samples:
        return None
    M = cv2.moments(contour)
    cx, cy = M['m10'] / max(M['m00'], 1e-6), M['m01'] / max(M['m00'], 1e-6)
    pick = np.linspace(0, len(xs) - 1, n_samples).astype(int)
    H, W = gray.shape
    out = {'vert': [], 'horz': []}
    for i in pick:
        x, y = int(xs[i]), int(ys[i])
        dx, dy = x - cx, y - cy
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm
        d_px = 0
        for step in range(2, 60):
            xx, yy = int(x + dx * step), int(y + dy * step)
            if not (0 <= xx < W and 0 <= yy < H):
                break
            if int(gray[yy, xx]) > int(gray[y, x]) + 35:
                d_px = step
                break
        if d_px <= 0:
            continue
        bucket = 'vert' if abs(dy) > abs(dx) else 'horz'
        out[bucket].append(d_px * scale_mm)
    if not out['vert'] and not out['horz']:
        return None
    return out


def taper_angles(contour):
    """邻面侧位测聚合度。取外接多边形左、右两条主边，算各自相对竖直方向的倾角，
    总切向聚合度 ≈ 左倾角 + 右倾角（°）。失败返回None。"""
    if contour is None:
        return None
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
    left_ang = []
    right_ang = []
    x, y, w, h = cv2.boundingRect(contour)
    midx = x + w / 2
    for i in range(len(approx)):
        p1 = approx[i][0]
        p2 = approx[(i + 1) % len(approx)][0]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < h * 0.25:      # 只取够长的轴壁边
            continue
        ang = abs(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)))  # 与竖直方向夹角
        if ang > 35:              # 过滤合面/切缘等近水平横边，只留近竖直轴壁
            continue
        mx = (p1[0] + p2[0]) / 2
        (left_ang if mx < midx else right_ang).append(ang)
    if not left_ang or not right_ang:
        return None
    la, ra = float(np.median(left_ang)), float(np.median(right_ang))
    return la + ra, la, ra


def margin_roughness(gray, contour):
    """颈缘特写：边缘平均梯度(锐度)与轮廓粗糙度，用于肩台连续/光滑/卷边判断。"""
    if contour is None:
        return None
    area = cv2.contourArea(contour)
    peri = cv2.arcLength(contour, True)
    if area <= 0 or peri <= 0:
        return None
    roughness = peri / (2 * math.sqrt(math.pi * area)) - 1
    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    border = cv2.dilate(mask, np.ones((3, 3), np.uint8)) - cv2.erode(mask, np.ones((3, 3), np.uint8))
    pts = mag[border > 0]
    grad = float(np.mean(pts)) if len(pts) else 0.0
    return roughness, grad


def make(engine, name, max_s, rate, raw, ideal, unit, detail,
         process='', suggestion='', subs=None, skip=False):
    rate = 0.0 if rate is None else max(0.0, min(1.0, rate))
    score = max_s * rate
    st = 'skip' if skip else status_of(rate)
    return CrownMeasure(
        name=name, score=round(max_s * 0.6 if skip else score, 1), max_score=max_s,
        raw_value=round(raw, 2) if isinstance(raw, (int, float)) else raw,
        ideal_value=ideal, unit=unit, detail=detail, status=st,
        process_analysis=process, targeted_suggestion=suggestion, sub_scores=subs or [])


def finalize(engine, report):
    # 缺照片的维度按60%保底计入，绝不剔除后归一化（否则缺最难的磨除量反会抬高总分）
    raw_total = round(sum(d.score for d in report.dimensions), 1)
    n_slot = len(set(report.slots_present) & set(SLOTS.keys()))
    coverage = n_slot / len(SLOTS)
    capped = coverage < 0.34   # 有效机位不足三分之一（≤2/6）→封顶55
    report.total_score = round(min(raw_total, 55.0), 1) if capped else raw_total
    report.equipment_score = round(report.total_score * 0.35, 1)
    for d in report.dimensions:
        if d.status in ('good',):
            report.strengths.append(f'{d.name}：{d.score:.0f}/{d.max_score}分')
        elif d.status in ('warning', 'bad'):
            report.weaknesses.append(f'{d.name}：{d.score:.0f}/{d.max_score}分')
    ts = report.total_score
    if ts >= 90:
        report.overall_assessment = '优秀。预备量、肩台与聚合度均衡，接近赛场设备评分高分标准。'
    elif ts >= 80:
        report.overall_assessment = '良好。主要指标达标，重点优化肩台连续性与聚合度。'
    elif ts >= 70:
        report.overall_assessment = '中等。各面磨除量或就位道存在偏差，需按建议针对性练习。'
    elif ts >= 60:
        report.overall_assessment = '及格。多项三维指标不达标，建议在导板下重建预备量概念。'
    else:
        report.overall_assessment = '不及格。磨除量/肩台/聚合度存在明显问题，建议从标准步骤重练。'
    if capped:
        report.overall_assessment = (
            f'⚠️ 照片不足（仅识别到{n_slot}/6个标准机位），总分已封顶在55分。'
            '请按六张规范补全（术前/术后正位、切端或合面位、邻面侧位、颈缘特写、硅胶导板剖面），尤其不能缺⑥导板剖面。')
    return report
