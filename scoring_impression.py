#!/usr/bin/env python3
"""
藻酸盐取模AI评分引擎 — 纯规则CV（无大模型、离线可用）

学生拍摄规范：印模组织面朝上，放在与印模有反差的干净桌面（深色衬底最佳），
全弓入镜、光线充足、对焦清晰、甩干积水。

处理流程（均在真实学生照片上验证过）：
  1) 色相/饱和度分割印模主体（粉色档，自动识别；Otsu兜底）
  2) 凸包上最大的"开口缺口"定向（下颌=舌侧开口、上颌=后缘切迹 → 后方）
  3) 形心径向射线逐方向找外缘，牙列区=外缘向内解剖偏移带
  4) 沿弓14个牙位模板：落在模板上的暗坑=牙（不计气泡），其余孤立暗坑=气泡
  5) 8维度测量。上下颌各自独立评分，综合成绩=上颌50%+下颌50%。

注意：规则CV对气泡/皱皮为形态学近似判断，阈值需用更多真实学生照片持续校准，
报告统一标注"AI初评仅供参考，以教师复核为准"。
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Dimension:
    name: str
    score: float
    max_score: float
    raw_value: float
    ideal_value: str
    unit: str
    detail: str
    status: str
    process_analysis: str = ''
    targeted_suggestion: str = ''


@dataclass
class JawReport:
    jaw: str                 # 'upper' / 'lower'
    ok: bool = False
    error: str = ''
    total_score: float = 0
    dimensions: List[Dimension] = field(default_factory=list)
    severe_deformity: bool = False
    key_area_missing: bool = False
    water_warning: bool = False
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# 8维度权重（合计100）
SCORING_CONFIG = {
    'completeness': {'max': 20, 'name': '印模完整性'},
    'detail':       {'max': 20, 'name': '清晰度与解剖形态'},
    'extension':    {'max': 15, 'name': '边缘伸展'},
    'bubble':       {'max': 15, 'name': '气泡与空洞'},
    'deformation':  {'max': 10, 'name': '变形与脱模损伤'},
    'thickness':    {'max': 8,  'name': '印模厚度与托盘外露'},
    'cleanliness':  {'max': 7,  'name': '清洁与修整'},
    'usability':    {'max': 5,  'name': '综合临床可用性'},
}

JAW_NAME = {'upper': '上颌', 'lower': '下颌'}

# ───────────────────────── 颜色档 ─────────────────────────
# 粉色：色相落在红区两端；蓝色（明年料）：色相~95–115。自动档按主导饱和色相选择。
COLOR_PROFILES = {
    'pink': {'hue_lo': [(0, 20)], 'hue_hi': [(158, 180)], 'sat_min': 40},
    'blue': {'hue_lo': [(92, 118)], 'hue_hi': [], 'sat_min': 45},
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(x)))


def _lin(x, x0, x1):
    """x<=x0→0, x>=x1→1 的线性映射（x0<x1）。"""
    if x1 == x0:
        return 1.0 if x >= x1 else 0.0
    return _clamp((x - x0) / (x1 - x0))


def _odd(n):
    n = max(3, int(n))
    return n if n % 2 else n + 1


class 藻酸盐取模评分引擎:

    def __init__(self, color_profile: str = 'auto'):
        self.profile_name = color_profile

    # ───────────────────────── 1. 主体分割 ─────────────────────────

    def _hue_mask(self, image):
        """按颜色档生成主体二值图；返回 (mask, 实际颜色档)。"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        H, S = hsv[:, :, 0], hsv[:, :, 1]
        profile = self.profile_name
        if profile == 'auto':
            profile = self._detect_profile(H, S)

        cfg = COLOR_PROFILES[profile]
        hue_sel = np.zeros_like(H, bool)
        for lo, hi in cfg['hue_lo'] + cfg['hue_hi']:
            hue_sel |= (H >= lo) & (H <= hi)
        m = (hue_sel & (S > cfg['sat_min'])).astype(np.uint8) * 255
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if n <= 1:
            return None, profile
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        m = (lab == i).astype(np.uint8) * 255
        if stats[i, cv2.CC_STAT_AREA] < 0.04 * H.size:
            return None, profile
        return m, profile

    @staticmethod
    def _detect_profile(H, S):
        """画面内高饱和像素的色相中位：偏红→pink，偏蓝→blue。"""
        strong = S > 60
        if strong.sum() < 100:
            return 'pink'
        hue = H[strong].astype(int)
        # 红区色相在0/180两端，折叠到"离红的距离"
        dist_red = np.minimum(hue, 180 - hue)
        return 'pink' if np.median(dist_red) < 35 else 'blue'

    def _otsu_fallback(self, image):
        """色相分割失败时的灰度Otsu兜底（亮/暗择优）。"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        h, w = gray.shape
        best = None
        for mask in (th, cv2.bitwise_not(th)):
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            c = max(cnts, key=cv2.contourArea)
            frac = cv2.contourArea(c) / (h * w)
            if 0.10 <= frac <= 0.92 and (best is None or frac > best[0]):
                best = (frac, mask)
        return best[1] if best else None

    @staticmethod
    def _fill_holes(mask):
        ff = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), np.uint8)
        filled = mask.copy()
        cv2.floodFill(filled, ff, (0, 0), 255)
        return mask | cv2.bitwise_not(filled)

    # ───────────────────────── 2. 定向 ─────────────────────────

    @staticmethod
    def _posterior_angle(raw, shape_center=None):
        """凸包内与外界连通的最大缺口中心相对形心的方向角(弧度)。失败返回None。"""
        cnts, _ = cv2.findContours(raw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None
        c = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(c)
        hm = np.zeros_like(raw)
        cv2.fillPoly(hm, [hull], 255)
        deficit = cv2.bitwise_and(hm, cv2.bitwise_not(raw))
        band = cv2.dilate(hm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) - \
               cv2.erode(hm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(deficit, 8)
        M = cv2.moments(raw)
        if M['m00'] == 0:
            return None
        sx, sy = M['m10'] / M['m00'], M['m01'] / M['m00']
        bf = band.flatten() > 0
        best = None
        for i in range(1, n):
            if ((lab == i).flatten()[bf]).sum() == 0:
                continue
            a = stats[i, cv2.CC_STAT_AREA]
            if best is None or a > best[0]:
                best = (a, cent[i][0], cent[i][1])
        if best is None:
            return None
        return float(np.arctan2(best[2] - sy, best[1] - sx))  # 正下方≈90°

    # ───────────────────────── 3. 径向几何 ─────────────────────────

    @staticmethod
    def _radial_extents(filled, cx, cy, diam,
                        betas=np.linspace(-130, 130, 65)):
        """每个β（相对前正中线偏角）方向上从形心到外缘的最大在界距离。"""
        h, w = filled.shape
        out = {}
        for beta in betas:
            a = np.radians(-90 + beta)
            dx, dy = np.cos(a), np.sin(a)
            Rout = None
            for t in np.arange(2.0, 0.80 * diam, 2.0):
                x, y = int(cx + dx * t), int(cy + dy*t)
                if 0 <= x < w and 0 <= y < h and filled[y, x] > 0:
                    Rout = float(t)
            out[float(beta)] = Rout
        return out

    def _build_teeth_geometry(self, filled, raw, gray, diam):
        """牙列几何（暗坑过滤→RANSAC圆→14牙位吸附）。
        返回 牙列带mask、14牙位[(x,y)]、射线外缘数据、圆心、betas。"""
        h, w = filled.shape
        M = cv2.moments(filled)
        cx, cy = M['m10'] / M['m00'], M['m01'] / M['m00']

        # ── 射线外缘（完整性/边缘伸展维度仍使用） ──
        betas = np.linspace(-130, 130, 65)
        extents = self._radial_extents(filled, cx, cy, diam, betas)
        Rvals = np.array([extents[b] if extents[b] is not None else np.nan for b in betas])
        valid = ~np.isnan(Rvals)
        if valid.sum() < 20:
            return None
        Rinterp = np.interp(betas, betas[valid], Rvals[valid])
        Rsmooth = np.convolve(Rinterp, np.ones(5)/5, mode='same')

        # ── 暗坑提取：只认真实材料，剔除贴外缘点 ──
        pits = self._extract_pit_points(gray, raw, filled, diam)
        if pits is None or len(pits) < 6:
            return None
        pts = np.array(pits)

        # ── RANSAC 圆 ──
        ransac = self._ransac_circle(pts, thresh=0.05*diam)
        if ransac is None:
            return None
        acx, acy, R, inl = ransac

        # ── 覆盖弧：以循环均值方向为前牙中线，按内点散布定半宽 ──
        in_pts = pts[inl]
        ang = np.arctan2(in_pts[:, 1]-acy, in_pts[:, 0]-acx)
        mean_ang = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
        unwrap = (ang - mean_ang + np.pi) % (2*np.pi) - np.pi
        half_w = float(np.percentile(np.abs(unwrap), 90))
        half_w = float(_clamp(half_w, 0.75, 1.85))

        # ── 14牙位：沿弧均匀并吸附到最近暗坑 ──
        ts = np.linspace(mean_ang-half_w, mean_ang+half_w, 14)
        templates = []
        for t in ts:
            gx, gy = acx + R*np.cos(t), acy + R*np.sin(t)
            d = np.hypot(pts[:, 0]-gx, pts[:, 1]-gy)
            j = int(np.argmin(d))
            templates.append(tuple(pts[j]) if d[j] < 0.08*diam else (gx, gy))

        # ── 牙列带：环[0.68R..1.12R]×覆盖弧，只取真实材料 ──
        yy, xx = np.mgrid[0:h, 0:w]
        rad = np.hypot(xx-acx, yy-acy)
        th = np.arctan2(yy-acy, xx-acx)
        tu = (th - mean_ang + np.pi) % (2*np.pi) - np.pi
        band = ((rad >= 0.68*R) & (rad <= 1.12*R) &
                (np.abs(tu) <= half_w + 0.15) & (raw > 0))
        bandm = (band.astype(np.uint8) * 255)
        bandm = cv2.dilate(bandm, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (_odd(0.02*diam),)*2))

        ext_smooth = {float(b): float(r) for b, r in zip(betas, Rsmooth)}
        ext_raw = {float(b): extents[float(b)] for b in betas}
        return bandm, templates, (ext_smooth, ext_raw), (acx, acy), betas

    @staticmethod
    def _extract_pit_points(gray, raw, filled, diam):
        """局部暗度图+连通组件，返回 [(x,y)]：
        - 只在真实材料像素(raw)内
        - 形心距边界 <4.5%直径的组件剔除（贴外缘=材料边界/托盘边）。"""
        edge_dist = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
        kb = _odd(0.07 * diam)
        bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kb, kb)))
        dk = bg.astype(int) - gray.astype(int)
        cand = ((dk > 26) & (raw > 0)).astype(np.uint8) * 255
        cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        area = float(np.sum(filled > 0))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(cand, 8)
        pts = []
        for i in range(1, n):
            a = stats[i, cv2.CC_STAT_AREA]
            if a < 0.0005*area or a > 0.03*area:
                continue
            x, y = cent[i]
            if edge_dist[int(y), int(x)] < 0.045*diam:
                continue
            pts.append((float(x), float(y)))
        return pts

    @staticmethod
    def _ransac_circle(pts, iters=500, thresh=None):
        """3点RANSAC圆，内点重拟合(Kasa)。返回 (cx,cy,R,inliers)。"""
        rng = np.random.default_rng(7)
        n = len(pts)
        best = None
        for _ in range(iters):
            i, j, k = rng.choice(n, 3, replace=False)
            (x1, y1), (x2, y2), (x3, y3) = pts[i], pts[j], pts[k]
            A = np.array([[2*(x2-x1), 2*(y2-y1)], [2*(x3-x1), 2*(y3-y1)]])
            b = np.array([x2**2+y2**2-x1**2-y1**2,
                          x3**2+y3**2-x1**2-y1**2])
            if abs(np.linalg.det(A)) < 1e-6:
                continue
            cx, cy = np.linalg.solve(A, b)
            R = np.hypot(cx-x1, cy-y1)
            d = np.abs(np.hypot(pts[:, 0]-cx, pts[:, 1]-cy) - R)
            inl = d < thresh
            if best is None or inl.sum() > best[0]:
                best = (int(inl.sum()), cx, cy, R, inl)
        if best is None:
            return None
        _, _, _, _, inl = best
        p = pts[inl]
        A = np.c_[2*p[:, 0], 2*p[:, 1], np.ones(len(p))]
        bb = p[:, 0]**2 + p[:, 1]**2
        sol, *_ = np.linalg.lstsq(A, bb, rcond=None)
        cx, cy, c = sol
        R = float(np.sqrt(c + cx**2 + cy**2))
        return float(cx), float(cy), R, inl

    # ───────────────────────── 4. 缺陷检测 ─────────────────────────

    @staticmethod
    def _dark_pits(gray, zone, diam, area_ref):
        """区域内的近圆暗坑（黑帽），返回 [(cx,cy,area)]。"""
        ksize = _odd(0.032 * diam)
        bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize)))
        vals = bh[zone > 0]
        if len(vals) == 0:
            return []
        thr = max(20.0, float(np.percentile(vals, 97)))
        cand = ((bh > thr) & (zone > 0)).astype(np.uint8) * 255
        cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(cand, 8)
        pits = []
        for i in range(1, n):
            a = stats[i, cv2.CC_STAT_AREA]
            if a < 0.0004 * area_ref or a > 0.02 * area_ref:
                continue
            ww, hh = stats[i, 2], stats[i, 3]
            if max(ww, hh) / max(1, min(ww, hh)) > 3.0:
                continue
            peri = cv2.arcLength(np.array([[[stats[i,0], stats[i,1]],
                                           [stats[i,0]+ww, stats[i,1]],
                                           [stats[i,0]+ww, stats[i,1]+hh],
                                           [stats[i,0], stats[i,1]+hh]]]), True)
            circ = 4 * np.pi * a / max(1.0, peri*peri)
            if circ < 0.3:
                continue
            pits.append((float(cent[i][0]), float(cent[i][1]), float(a)))
        return pits

    @staticmethod
    def _match_template(x, y, templates, diam):
        for tx, ty in templates:
            if np.hypot(x - tx, y - ty) < 0.075 * diam:
                return True
        return False

    @staticmethod
    def _detect_water(gray, zone, diam, area_ref):
        """局部亮斑（积水高光）计数，只提示。面积门槛放宽到0.02%主体，避免细碎反光混入。"""
        ksize = _odd(0.030 * diam)
        top = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize)))
        vals = top[zone > 0]
        if len(vals) == 0:
            return 0
        thr = max(50.0, float(vals.mean() + 3.2 * vals.std()))
        bw = ((top > thr) & (zone > 0)).astype(np.uint8) * 255
        n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
        return int(sum(1 for i in range(1, n)
                       if 0.0005 * area_ref <= stats[i, 4] <= 0.015 * area_ref))

    @staticmethod
    def _symmetry(filled):
        flipped = cv2.flip(filled, 1)
        inter = np.sum(np.logical_and(filled > 0, flipped > 0))
        union = np.sum(np.logical_or(filled > 0, flipped > 0))
        return float(inter / max(1, union))

    @staticmethod
    def _arch_symmetry(betas, ext_smooth):
        """左右外缘半径配对（β与−β关于前正中线镜像）的相对一致性，0~1。"""
        diffs = []
        for b in betas:
            if abs(b) > 108 or b <= 0:
                continue
            r1, r2 = ext_smooth.get(float(b)), ext_smooth.get(float(-b))
            if r1 and r2:
                diffs.append(abs(r1 - r2) / max(1.0, (r1 + r2) / 2.0))
        if not diffs:
            return 1.0
        return float(np.clip(1.0 - np.mean(diffs), 0.0, 1.0))

    @staticmethod
    def _symmetry_about(mask, axis_x):
        """关于竖轴 x=axis_x 的镜像IoU（用平移实现，避免裁剪改变轴位置）。"""
        m = (mask > 0).astype(np.uint8)
        h, w = m.shape
        M = np.float32([[1, 0, 2*(w/2 - axis_x)], [0, 1, 0]])
        flipped = cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_NEAREST)
        inter = np.sum(np.logical_and(m > 0, flipped > 0))
        union = np.sum(np.logical_or(m > 0, flipped > 0))
        return float(inter / max(1, union))

    @staticmethod
    def _detect_tears(gray, zone, diam, midline_x=None,
                      arch_center=None, edge_dist=None):
        """区域内细长黑线数。排除：
        - 中线±3%直径的竖线（腭中缝/舌系带）
        - 长边沿牙弓切线方向（邻间隙/切缘间隙的暗线）
        - 紧贴外缘（<3.5%直径，多为托盘边缘/材料边界）。"""
        L = _odd(0.16 * diam)
        count = 0
        for ksize in ((L, 3), (3, L)):
            bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, ksize))
            vals = bh[zone > 0]
            if len(vals) == 0:
                continue
            thr = float(vals.mean() + 2.5 * vals.std())
            bw = ((bh > thr) & (zone > 0)).astype(np.uint8) * 255
            n, lab2, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
            for i in range(1, n):
                ww, hh = stats[i, 2], stats[i, 3]
                long_side, short_side = max(ww, hh), max(1, min(ww, hh))
                if not (long_side > 0.12*diam and long_side / short_side > 4):
                    continue
                ccx, ccy = cent[i]
                if midline_x is not None and abs(ccx - midline_x) < 0.03*diam:
                    continue
                if edge_dist is not None and edge_dist[int(ccy), int(ccx)] < 0.035*diam:
                    continue  # 贴外缘
                if arch_center is not None:
                    ax, ay = arch_center
                    phi = np.degrees(np.arctan2(ccy-ay, ccx-ax))
                    tangent = (phi + 90.0) % 180.0
                    theta_long = 0.0 if ww >= hh else 90.0
                    d = abs(theta_long - tangent)
                    if min(d, 180-d) < 25:
                        continue  # 沿弓走行=邻间隙，非撕裂
                count += 1
        return count

    @staticmethod
    def _tray_exposure(image, raw, templates, diam):
        """托盘穿露率 = 14个预期牙位邻域内【材料缺失】的比例。
        只检查应长有牙的位置；托盘柄/舌侧空间无牙位模板，天然不计。
        返回 0~1（缺失面积/应覆盖面积）。"""
        radius = max(5, int(0.055 * diam))
        total, missing = 0, 0
        h, w = raw.shape
        for tx, ty in templates:
            x0, x1 = max(0, int(tx)-radius), min(w, int(tx)+radius)
            y0, y1 = max(0, int(ty)-radius), min(h, int(ty)+radius)
            if x1 <= x0 or y1 <= y0:
                continue
            total += (x1-x0)*(y1-y0)
            missing += int(np.sum(raw[y0:y1, x0:x1] == 0))
        return float(missing / max(1, total))

    def _blood_and_dirt(self, image, filled, teeth_band, zone, diam, profile):
        """血迹=局部又暗又红于周围的致密团块（牙列带内外均可）；
        暗污只统计牙列带以外的区域（牙窝阴影不算脏）。返回 blood, dirt。"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        H, S, V = hsv[:, :, 0].astype(int), hsv[:, :, 1], hsv[:, :, 2].astype(int)
        R, G = image[:, :, 2].astype(int), image[:, :, 1].astype(int)
        area_ref = float(np.sum(filled > 0))

        if profile == 'blue':
            # 蓝料上血迹=色相显著转红且高饱和
            red_excess = (np.abs(((H + 90) % 180) - 90) > 55) & (S > 80)
        else:
            # 粉料：相对周围"更红更暗"的局部增量（黑帽思路），排除均匀粉色底
            red_green = ((R - G) + 128).astype(np.uint8)
            ksize = _odd(0.05 * diam)
            red_bh = cv2.morphologyEx(red_green, cv2.MORPH_BLACKHAT,
                                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize)))
            v_bh = cv2.morphologyEx(V.astype(np.uint8), cv2.MORPH_BLACKHAT,
                                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize)))
            red_excess = (red_bh > 26) & (v_bh > 18) & (S > 60)

        bw = (red_excess & (zone > 0)).astype(np.uint8) * 255
        n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
        blood_area = sum(int(stats[i, 4]) for i in range(1, n)
                         if stats[i, 4] > 0.0006 * area_ref)
        blood = blood_area / area_ref

        dirt_zone = (zone > 0) & (teeth_band == 0)  # 暗污只在牙列带外统计
        med_v = float(np.median(V[filled > 0]))
        dirt = float(np.sum((V < med_v - 55) & dirt_zone) / area_ref)
        return float(blood), float(dirt)

    @staticmethod
    def _flash_spikes(filled, diam):
        """外缘细小尖刺（凸包小而深的窄缺陷）。"""
        cnts, _ = cv2.findContours(filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(c)
        try:
            defects = cv2.convexityDefects(c, hull)
        except cv2.error:
            return 0
        if defects is None:
            return 0
        n = 0
        for d in defects[:, 0]:
            depth = d[3] / 256.0
            gap = np.linalg.norm(c[d[0]][0] - c[d[1]][0])
            if 0.03*diam < depth < 0.10*diam and 0 < gap < 0.02*diam:
                n += 1
        return n

    def _mk(self, name, score, max_s, raw, ideal, unit, detail, process, suggestion):
        pct = score / max_s
        status = 'good' if pct >= 0.75 else ('warning' if pct >= 0.5 else 'bad')
        return Dimension(name=name, score=round(min(max_s, max(0, score)), 1), max_score=max_s,
                         raw_value=round(raw, 3), ideal_value=ideal, unit=unit,
                         detail=detail, status=status,
                         process_analysis=process, targeted_suggestion=suggestion)

    # ───────────────────────── 单颌分析 ─────────────────────────

    def analyze_jaw(self, image_path, jaw='upper'):
        rep = JawReport(jaw=jaw)
        image = cv2.imread(image_path)
        if image is None:
            rep.error = '照片无法读取'
            return rep

        h0, w0 = image.shape[:2]
        if max(h0, w0) > 900:
            s = 900 / max(h0, w0)
            image = cv2.resize(image, (int(w0 * s), int(h0 * s)))

        raw, profile = self._hue_mask(image)
        if raw is None:
            raw = self._otsu_fallback(image)
            profile = profile or 'pink'
        if raw is None:
            rep.error = '未能从照片中识别出印模主体（请使用深色/有反差衬底、全弓入镜）'
            return rep
        filled = self._fill_holes(raw)

        # 定向并旋正（后方向→正下方）
        theta = self._posterior_angle(raw)
        if theta is None:
            rep.error = '印模轮廓不完整，无法判断前后方向'
            return rep
        alpha = 90.0 - np.degrees(theta)
        h, w = image.shape[:2]
        Mrot = cv2.getRotationMatrix2D((w/2, h/2), alpha, 1.0)

        def rot(im, fl=cv2.INTER_LINEAR):
            return cv2.warpAffine(im, Mrot, (im.shape[1], im.shape[0]),
                                  flags=fl, borderValue=0)

        filled_r = rot(filled, cv2.INTER_NEAREST)
        raw_r = rot(raw, cv2.INTER_NEAREST)
        image_r = rot(image)
        # 裁剪到主体包围盒
        ys, xs = np.where(filled_r > 0)
        y0, y1, x0, x1 = ys.min(), ys.max()+1, xs.min(), xs.max()+1
        pad = 8
        sl = (max(0, y0-pad), y1+pad, max(0, x0-pad), x1+pad)
        filled_r = filled_r[sl[0]:sl[1], sl[2]:sl[3]]
        raw_r = raw_r[sl[0]:sl[1], sl[2]:sl[3]]
        image_r = image_r[sl[0]:sl[1], sl[2]:sl[3]]

        gray_r = cv2.cvtColor(image_r, cv2.COLOR_BGR2GRAY)
        area = float(np.sum(filled_r > 0))
        diam = float(np.sqrt(4 * area / np.pi))

        geom = self._build_teeth_geometry(filled_r, raw_r, gray_r, diam)
        if geom is None:
            rep.error = '牙列区域识别失败（请确保全弓入镜、印模完整）'
            return rep
        teeth_band, templates, (ext_smooth, ext_raw), (cx, cy), betas = geom

        # 检测区=牙列带 + 腭/舌侧内部，且只取真实材料像素(raw_r)，
        # 排除fill_holes补上的托盘缝隙（那里本无印模，不应参与血污/暗坑判断）
        inner_eroded = cv2.erode(filled_r, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (_odd(0.03*diam),)*2))
        detect_zone = np.maximum(teeth_band, inner_eroded)
        detect_zone[raw_r == 0] = 0

        metrics = {}
        m = metrics

        # ── 外缘轮廓质量：完整性 + 伸展（共用射线外缘） ──
        raw_R = np.array([ext_raw[b] if ext_raw[b] is not None else np.nan for b in betas])
        sm_R = np.array([ext_smooth[b] for b in betas])
        envelope = float(np.percentile(sm_R, 90))
        present = ~np.isnan(raw_R)
        # 牙弓主体角范围（β±130两端射线斜行，不计入完整性）
        arch_sel = np.abs(betas) <= 118
        # 达标率：平滑外缘达到全局包络85%的方向占比（用平滑值，避免色掩膜毛刺）
        reach = sm_R >= 0.85*envelope
        # 大缺损：牙弓主体角内平滑外缘骤降>15%的方向数，7个方向≈一处
        big_defects = int(np.sum((sm_R < 0.85*envelope) & arch_sel)) // 7
        coverage = float(np.mean(reach[arch_sel]))
        m.update(coverage=round(coverage, 2), big_defects=big_defects)

        widths = sm_R / diam
        w_mean = float(np.mean(widths))
        w_cv = float(np.std(widths) / max(1e-6, w_mean))
        m.update(edge_mean=round(w_mean, 3), edge_cv=round(w_cv, 2))

        # ── 维度2：对焦清晰度 + 牙列带纹理 + 皱皮方向性 ──
        lap_var = float(cv2.Laplacian(gray_r, cv2.CV_32F)[filled_r > 0].var())
        gx = cv2.Sobel(gray_r, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray_r, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        zone_pix = teeth_band > 0
        tex = float(mag[zone_pix].mean()) if zone_pix.any() else 0.0
        streak = 0.0
        if zone_pix.sum() > 30:
            strong = mag[zone_pix] > np.median(mag[zone_pix]) * 1.8
            if strong.sum() > 30:
                ang = np.arctan2(gy[zone_pix][strong], gx[zone_pix][strong])
                hist, _ = np.histogram(ang, bins=12, range=(-np.pi, np.pi))
                streak = float(hist.max() / max(1, hist.mean()))
        m.update(lap_var=round(lap_var, 1), texture=round(tex, 1), streak=round(streak, 2))

        # ── 维度4：暗坑→牙位模板匹配→其余=气泡；积水只提示 ──
        pits = self._dark_pits(gray_r, detect_zone, diam, area)
        bubbles, bub_in_teeth, bubble_area = [], 0, 0.0
        for px, py, pa in pits:
            if self._match_template(px, py, templates, diam):
                continue
            bubbles.append((px, py, pa))
            bubble_area += pa
            if teeth_band[int(py), int(px)] > 0:
                bub_in_teeth += 1
        bubble_density = bubble_area / area
        water_spots = self._detect_water(gray_r, detect_zone, diam, area)
        m.update(bubbles=len(bubbles), bubbles_in_teeth=bub_in_teeth,
                 bubble_density=round(bubble_density, 4), water_spots=water_spots)
        rep.water_warning = water_spots >= 3

        # ── 维度5：对称 + 撕裂 ──
        # 到最近边界的距离（供裂伤排除贴外缘组件）
        edge_dist = cv2.distanceTransform(filled_r, cv2.DIST_L2, 5)
        # 对称性：左右外缘半径关于前正中线配对的一致性（线性、温和），
        # 不把整块mask的IoU拿来判（废料/托盘会拉低），细环IoU又对小错位过敏
        sym_iou = self._arch_symmetry(betas, ext_smooth)
        tears = self._detect_tears(gray_r, detect_zone, diam,
                                   midline_x=cx, arch_center=(cx, cy),
                                   edge_dist=edge_dist)
        m.update(symmetry=round(sym_iou, 2), tears=tears)

        # ── 维度6：托盘穿露 ──
        tray_frac = self._tray_exposure(image_r, raw_r, templates, diam)
        m.update(tray_frac=round(tray_frac, 3))

        # ── 维度7：血迹/暗污/飞边 ──
        blood, dirt = self._blood_and_dirt(image_r, filled_r, teeth_band,
                                           detect_zone, diam, profile)
        flashes = self._flash_spikes(filled_r, diam)
        m.update(blood=round(blood, 4), dirt=round(dirt, 3), flashes=flashes)

        # ───────────────────── 组装维度 ─────────────────────
        jn = JAW_NAME[jaw]
        dims = []

        # 1 完整性 20（sqrt软化，避免一处小缺损主导；极低覆盖率仍给少量底分）
        cov_s = np.sqrt(_lin(coverage, 0.40, 0.95))
        def_s = _clamp(1 - 0.08 * big_defects)
        s1 = 20 * cov_s * def_s
        d1 = f'外缘轮廓达标率{coverage*100:.0f}%（理想≥95%），大块缺损{big_defects}处'
        p1 = (f'【{jn}·完整性】沿牙弓65个方向逐点射线测量外缘，{coverage*100:.0f}%方向的外缘连续达标；\n'
              f'包络分析检出深度>15%牙弓径的大块缺损 {big_defects} 处'
              f'（末端磨牙远中/上颌结节/磨牙后垫区缺料在此体现）。')
        sug1 = '重点检查最后磨牙远中（上颌结节/磨牙后垫区）是否取全；托盘就位后保持稳定不要提前翘动。'
        dims.append(self._mk('印模完整性', s1, 20, coverage, '达标率≥95%', '', d1, p1, sug1))
        rep.key_area_missing = coverage < 0.75

        # 2 清晰度与解剖形态 20
        # 微信压缩图对焦方差天然偏低（>120即很清晰），故以纹理为主(0.65)
        f_s = _lin(lap_var, 22, 120)
        t_s = _lin(tex, 9, 26)
        s2 = 20 * (0.35*f_s + 0.65*t_s)
        if streak > 2.6:
            s2 *= 0.82
        d2 = f'对焦清晰度{lap_var:.0f}，牙列带纹理强度{tex:.0f}，纹理方向集中度{streak:.1f}'
        p2 = (f'【{jn}·清晰度】拉普拉斯对焦方差={lap_var:.0f}（<25糊片）；\n'
              f'牙列带梯度均值={tex:.0f}，反映牙尖窝沟印迹是否锐利；\n'
              f'纹理方向集中度={streak:.1f}（>2.6提示皱皮/方向性拉丝，多为水粉比不当或调拌过慢、脱模迟疑）。')
        sug2 = '严格按水粉比例调拌、60秒内完成调拌与就位；印模膏凝固前勿动；拍照先对焦、手别抖。'
        dims.append(self._mk('清晰度与解剖形态', s2, 20, lap_var, '对焦方差>150', '', d2, p2, sug2))

        # 3 边缘伸展 15
        mean_s = 1.0 if 0.30 <= w_mean <= 0.52 else (
            _lin(w_mean, 0.18, 0.30) if w_mean < 0.30 else 1 - 0.4*_lin(w_mean, 0.52, 0.70))
        even_s = 1 - 0.5*_lin(w_cv, 0.45, 1.0)
        s3 = 15 * (0.6*_clamp(mean_s) + 0.4*_clamp(even_s))
        d3 = f'外缘半径平均{w_mean*100:.0f}%等效直径（理想30–52%），宽窄变异{w_cv*100:.0f}%'
        p3 = (f'【{jn}·边缘伸展】65方向射线外缘半径平均为等效直径的{w_mean*100:.0f}%'
              f'（过短=伸展不足未盖过移行皱襞，过长=材料过厚）；\n'
              f'各方向变异系数{w_cv*100:.0f}%（>80%提示厚薄悬殊、局部脱位）。')
        sug3 = '托盘选号合适、材料量充足，就位时先压后部再向前，保证前庭沟/系带区均匀延展。'
        dims.append(self._mk('边缘伸展', s3, 15, w_mean, '等效直径30–52%', '', d3, p3, sug3))

        # 4 气泡 15（牙列带气泡权重×3）
        weighted = 0.0
        for px, py, pa in bubbles:
            weighted += (3.0 if teeth_band[int(py), int(px)] > 0 else 1.0) * \
                        _clamp(pa / (0.002 * area), 0.5, 3.0)
        s4 = 15 * _clamp(1 - weighted / 9.0)
        d4 = f'检出气泡{len(bubbles)}个（牙列带{bub_in_teeth}个），暗坑面积占比{bubble_density*100:.2f}%'
        p4 = (f'【{jn}·气泡】黑帽形态学检出孤立近圆暗坑 {len(bubbles)} 个，其中牙列带 {bub_in_teeth} 个（权重×3）；\n'
              f'沿弓14个牙位模板上的规则暗坑判定为正常牙窝、不计气泡；暗坑总面积占{density_str(bubble_density)}。'
              f'亮斑（积水反光）{water_spots}处，不计入气泡。')
        sug4 = '调拌沿杯壁单向加压碾转避免裹气；就位从一侧向另一侧旋压让材料流动排气；必要时先在牙面涂布少量材料。'
        dims.append(self._mk('气泡与空洞', s4, 15, len(bubbles), '0个，关键区尤忌', '个', d4, p4, sug4))

        # 5 变形与撕裂 10
        sym_s = _lin(sym_iou, 0.62, 0.92)
        tear_s = _clamp(1 - 0.3*tears)
        s5 = 10*(0.6*sym_s + 0.4*tear_s)
        d5 = f'左右镜像重合度{sym_iou*100:.0f}%，细长裂伤线{tears}条'
        p5 = (f'【{jn}·变形撕裂】主体左右镜像IoU={sym_iou*100:.0f}%（<80%提示牵拉变形）；\n'
              f'检出长度>12%等效直径的细长黑线 {tears} 条（倒凹区撕裂/脱模损伤）。')
        sug5 = '有倒凹先做缓冲；凝固后沿牙长轴方向整体轻取下、忌左右掰动；一旦撕裂变形必须重取。'
        dims.append(self._mk('变形与脱模损伤', s5, 10, sym_iou, '镜像重合≥90%', '', d5, p5, sug5))
        rep.severe_deformity = (tears >= 2) or (sym_iou < 0.62)

        # 6 厚度与托盘外露 8
        tray_s = 1 - _lin(tray_frac, 0.03, 0.20)
        s6 = 8 * _clamp(tray_s)
        d6 = f'疑似托盘穿露/过薄区占{tray_frac*100:.1f}%'
        p6 = (f'【{jn}·厚度托盘】主体内部低饱和光滑异色区域占{tray_frac*100:.1f}%\n'
              f'（>10%提示金属托盘外露或局部材料过薄，理想厚度2–4mm）。')
        sug6 = '材料量要够、托盘就位勿过度施压；穿露出托盘说明该区无有效印模，需重取。'
        dims.append(self._mk('印模厚度与托盘外露', s6, 8, tray_frac, '穿露<3%', '', d6, p6, sug6))

        # 7 清洁与修整 7
        dirty_idx = blood*30 + dirt + flashes*0.02
        s7 = 7 * _clamp(1 - _lin(dirty_idx, 0.02, 0.20))
        d7 = f'血迹{blood*100:.2f}%，暗污区{dirt*100:.1f}%，飞边尖刺{flashes}处'
        p7 = (f'【{jn}·清洁修整】局部红度增量法血迹占比{blood*100:.2f}%（已排除均匀粉色底材）；'
              f'大块暗污{dirt*100:.1f}%；外缘飞边尖刺{flashes}处。')
        sug7 = '取模后清水轻冲、甩干（勿磨伤印迹面）；去除多余飞边再灌模；牙龈出血明显先止血再取。'
        dims.append(self._mk('清洁与修整', s7, 7, dirty_idx, '无血污飞边', '', d7, p7, sug7))

        # 8 综合可用性 5（前七维派生；积水提示扣减）
        pre7 = sum(d.score for d in dims) / 90.0
        s8 = 5 * _clamp(pre7) * (0.8 if rep.water_warning else 1.0)
        d8 = '前七维加权派生' + ('；检出积水反光，灌模前必须吹干' if rep.water_warning else '')
        p8 = f'【{jn}·可用性】由前七维得分率{pre7*100:.0f}%派生，判断该印模能否直接灌模。'
        sug8 = '不达标的印模不要勉强灌模——在椅旁重取成本最低。'
        dims.append(self._mk('综合临床可用性', s8, 5, pre7, '可直接灌模', '', d8, p8, sug8))

        rep.dimensions = dims
        rep.total_score = round(sum(d.score for d in dims), 1)
        rep.metrics = m
        rep.ok = True
        rep.strengths = [f'{d.name} {d.score:.0f}/{d.max_score}' for d in dims if d.status == 'good']
        rep.weaknesses = [f'{d.name} {d.score:.0f}/{d.max_score}' for d in dims if d.status != 'good']
        return rep

    # ───────────────────────── 上下颌成套 ─────────────────────────

    def analyze_set(self, upper_paths: List[str], lower_paths: List[str]):
        """每颌多张取最高分；返回 (综合报告对象或None, 上颌JawReport, 下颌JawReport)。"""
        upper = self._best_jaw(upper_paths, 'upper')
        lower = self._best_jaw(lower_paths, 'lower')
        if upper is None and lower is None:
            return None, upper, lower
        return self._combine(upper, lower), upper, lower

    def _best_jaw(self, paths, jaw):
        best = None
        for p in paths or []:
            try:
                r = self.analyze_jaw(p, jaw)
            except Exception:
                continue
            if r.ok and (best is None or r.total_score > best.total_score):
                best = r
        return best

    def _combine(self, upper: Optional[JawReport], lower: Optional[JawReport]):
        """两颌8维平均成一份100分报告。单颌缺失时该颌维度按60%保底并封顶55。"""
        jaws = [j for j in (upper, lower) if j is not None]
        combined_dims = []
        for idx, key in enumerate(SCORING_CONFIG):
            cfg = SCORING_CONFIG[key]
            present = [j.dimensions[idx] for j in jaws]
            if len(jaws) == 2:
                score = float(np.mean([d.score for d in present]))
                detail = f'上 {present[0].score:.0f}分 · 下 {present[1].score:.0f}分'
                process = present[0].process_analysis + '\n' + present[1].process_analysis
                worst = min(present, key=lambda d: d.score / d.max_score)
                suggestion = worst.targeted_suggestion
                raw = float(np.mean([d.raw_value for d in present]))
            else:
                only = present[0]
                score = only.score * 0.6
                miss = '下颌' if jaws[0].jaw == 'upper' else '上颌'
                detail = f'{only.detail} ｜ ⚠️缺{miss}照片，该维按60%保底'
                process = only.process_analysis + f'\n【缺考】未收到{miss}印模照片，维度分×60%保底。'
                suggestion = only.targeted_suggestion
                raw = only.raw_value
            d = self._mk(cfg['name'], score, cfg['max'], raw, '', '', detail, process, suggestion)
            combined_dims.append(d)

        total = round(sum(d.score for d in combined_dims), 1)
        cap = None
        for j in jaws:
            if j.severe_deformity:
                cap = 55
            if j.key_area_missing and cap is None:
                cap = 60
        if cap is not None:
            total = min(total, cap)

        @dataclass
        class Combined:
            pass
        c = Combined()
        c.dimensions = combined_dims
        c.total_score = total
        c.cap = cap
        c.upper_present = upper is not None
        c.lower_present = lower is not None
        c.upper_score = upper.total_score if upper else None
        c.lower_score = lower.total_score if lower else None
        c.water_warning = any(j.water_warning for j in jaws)
        c.strengths, c.weaknesses = [], []
        for j in jaws:
            tag = JAW_NAME[j.jaw]
            c.strengths += [f'【{tag}】{s}' for s in j.strengths[:3]]
            c.weaknesses += [f'【{tag}】{s}' for s in j.weaknesses[:4]]
        return c


def density_str(x):
    return f'{x*100:.2f}%'


if __name__ == '__main__':
    import sys
    e = 藻酸盐取模评分引擎()
    if len(sys.argv) > 1:
        r = e.analyze_jaw(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'upper')
        print('ok' if r.ok else f'FAIL: {r.error}', f'{r.total_score}/100')
        for d in r.dimensions:
            print(f'  {d.name}: {d.score}/{d.max_score} [{d.status}] {d.detail}')
        print('metrics:', r.metrics)
