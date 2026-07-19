#!/usr/bin/env python3
"""
开髓洞形制备AI评分引擎
评估维度：位置、轮廓、壁光滑度、髓室顶揭除、根管口暴露、髓室底保护、穿孔检测、便利形、外展度、牙体保存
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import math


@dataclass
class CavityMeasurement:
    name: str; score: float; max_score: float; raw_value: float
    ideal_value: float; unit: str; detail: str; status: str
    process_analysis: str = ''; targeted_suggestion: str = ''
    sub_scores: List[dict] = field(default_factory=list)


@dataclass
class ScoringReport:
    total_score: float = 0; max_total: float = 100
    dimensions: List[CavityMeasurement] = field(default_factory=list)
    problem_areas: List[dict] = field(default_factory=list)
    overall_assessment: str = ''
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)


SCORING_CONFIG = {
    'access_location':   {'max': 15, 'desc': '开髓位置准确性'},
    'outline_form':      {'max': 15, 'desc': '洞形轮廓'},
    'wall_smoothness':   {'max': 10, 'desc': '洞壁光滑度'},
    'roof_removal':      {'max': 10, 'desc': '髓室顶揭除完整度'},
    'orifice_exposure':  {'max': 10, 'desc': '根管口暴露清晰度'},
    'floor_integrity':   {'max': 10, 'desc': '髓室底完整性'},
    'no_perforation':    {'max': 15, 'desc': '无穿孔检测'},
    'convenience_form':  {'max': 5,  'desc': '便利形'},
    'wall_divergence':   {'max': 5,  'desc': '洞壁外展度'},
    'tooth_preservation':{'max': 5,  'desc': '牙体组织保存'},
}


class 开髓洞形评分引擎:
    def __init__(self):
        self.calibration_scale = None

    def _make(self, name, score, max_s, raw, ideal, unit, detail, status, process='', suggestion='', subs=None):
        return CavityMeasurement(name=name, score=round(min(max_s, max(0, score)), 1),
                                 max_score=max_s, raw_value=round(raw, 3),
                                 ideal_value=ideal, unit=unit, detail=detail, status=status,
                                 process_analysis=process, targeted_suggestion=suggestion,
                                 sub_scores=subs or [])

    def detect_scale(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=50,
                                   param1=50, param2=30, minRadius=10, maxRadius=80)
        if circles is not None and len(circles[0]) >= 2:
            cs = np.round(circles[0]).astype(int)
            if len(cs) > 2: cs = cs[cs[:, 0].argsort()]; c1, c2 = cs[0], cs[-1]
            else: c1, c2 = cs[0], cs[1]
            d = np.sqrt((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2)
            if 30 < d < 500: return 5.0 / d
        return None

    def extract_region(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return binary, contours

    # ═══════════════════════════════════════
    # 1. 开髓位置准确性 (15分)
    # ═══════════════════════════════════════
    def score_access_location(self, image, contours):
        max_s = 15
        if not contours:
            return self._make('开髓位置', 0, max_s, 0, 1, '准确度', '未检测到开髓洞形', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        M = cv2.moments(cavity)
        if M['m00'] == 0:
            return self._make('开髓位置', 5, max_s, 0, 1, '准确度', '无法定位', 'warning')

        cx = int(M['m10'] / M['m00'])
        cy = int(M['m01'] / M['m00'])

        # 获取牙冠边界
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, tooth_bin = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        tooth_contours, _ = cv2.findContours(tooth_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if tooth_contours:
            tooth = max(tooth_contours, key=cv2.contourArea)
            tx, ty, tw, th = cv2.boundingRect(tooth)
            tooth_cx, tooth_cy = tx + tw//2, ty + th//2

            # 偏离度：开髓中心与牙冠中心的距离
            deviation = np.sqrt((cx - tooth_cx)**2 + (cy - tooth_cy)**2)
            max_dev = np.sqrt(tw**2 + th**2) / 2
            dev_ratio = deviation / max_dev if max_dev > 0 else 0

            if dev_ratio < 0.15:
                loc_score, loc_note = 1.0, '开髓位置居中，解剖定位准确 ✓'
            elif dev_ratio < 0.3:
                loc_score, loc_note = 0.75, f'开髓位置略有偏移({dev_ratio:.0%})'
            else:
                loc_score, loc_note = 0.4, f'开髓位置明显偏离中心({dev_ratio:.0%})'

            # 颌面比例检查
            cavity_area = cv2.contourArea(cavity)
            tooth_area = cv2.contourArea(tooth)
            area_ratio = cavity_area / tooth_area if tooth_area > 0 else 0.1

            if 0.15 < area_ratio < 0.40:
                area_score, area_note = 1.0, f'洞形占牙面{area_ratio:.0%}，比例合理 ✓'
            elif 0.08 < area_ratio < 0.55:
                area_score, area_note = 0.7, f'洞形占比{area_ratio:.0%}，稍有偏差'
            else:
                area_score, area_note = 0.4, f'洞形占比{area_ratio:.0%}，过大或过小'

            raw = loc_score * 0.55 + area_score * 0.45
        else:
            raw, loc_note, area_note = 0.7, '牙冠边界检测受限', '比例估算受限'

        score = max_s * raw
        process = (
            f'【开髓位置打分过程】\n'
            f'├─ 开髓中心: ({cx},{cy}), 牙冠中心: ({tooth_cx},{tooth_cy})\n'
            f'├─ 中心偏离度: {dev_ratio:.0%} (理想<15%)\n'
            f'│   → {loc_note} → {loc_score:.0%}×55%\n'
            f'├─ 洞形/牙面比例: {area_ratio:.0%} (理想15%-40%)\n'
            f'│   → {area_note} → {area_score:.0%}×45%\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        if dev_ratio > 0.3:
            suggestion = '开髓位置偏离中心。建议：术前在X线片上测量髓室位置，根据牙位解剖标志确定开髓点（前牙：舌侧窝；前磨牙：颌面中央窝；磨牙：中央窝偏近中）。'
        elif area_ratio > 0.5:
            suggestion = '开髓洞形过大。建议：开髓范围以能暴露全部根管口为度，避免过多磨除健康牙体组织。'
        else:
            suggestion = '开髓位置和大小基本合理。'

        status = 'good' if raw >= 0.8 else ('warning' if raw >= 0.55 else 'bad')
        return self._make('开髓位置', score, max_s, raw, 1.0, '准确度', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 2. 洞形轮廓 (15分)
    # ═══════════════════════════════════════
    def score_outline_form(self, image, contours):
        max_s = 15
        if not contours:
            return self._make('洞形轮廓', 0, max_s, 0, 1, '相似度', '未检测到洞形', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cavity)
        perimeter = cv2.arcLength(cavity, True)

        # 圆形度
        circularity = 4 * np.pi * area / (perimeter**2) if perimeter > 0 else 0

        # 凸度
        hull = cv2.convexHull(cavity)
        hull_area = cv2.contourArea(hull)
        convexity = area / hull_area if hull_area > 0 else 0

        # 开髓洞形应为近三角形或卵圆形（磨牙）或椭圆形（前磨牙/前牙）
        # 圆形度: 0.6-0.9 为合理的非圆形
        if 0.55 < circularity < 0.92:
            cir_score, cir_note = 1.0, '形状为不规则多边形/卵圆形，符合开髓洞形 ✓'
        elif 0.4 < circularity < 0.98:
            cir_score, cir_note = 0.7, '形状基本合理'
        else:
            cir_score, cir_note = 0.4, '形状异常，过于圆形或过于不规则'

        # 凸度: 开髓洞形应基本凸出
        if convexity > 0.75:
            cvx_score, cvx_note = 1.0, '轮廓平滑，无异常凹陷 ✓'
        else:
            cvx_score, cvx_note = 0.6, '轮廓存在凹陷，可能损伤髓室底'

        raw = cir_score * 0.5 + cvx_score * 0.5
        score = max_s * raw

        process = (
            f'【洞形轮廓打分过程】\n'
            f'├─ 圆形度={circularity:.2f}(理想0.55-0.92) → {cir_note} → {cir_score:.0%}×50%\n'
            f'├─ 凸度={convexity:.2f}(理想>0.75) → {cvx_note} → {cvx_score:.0%}×50%\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = '洞形轮廓良好。' if raw >= 0.75 else '洞形轮廓需优化。建议：参照标准开髓洞形图谱，磨牙为圆三角形，前磨牙为卵圆形，前牙为椭圆形。'
        status = 'good' if raw >= 0.8 else ('warning' if raw >= 0.55 else 'bad')
        return self._make('洞形轮廓', score, max_s, raw, 1.0, '得分率', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 3. 洞壁光滑度 (10分)
    # ═══════════════════════════════════════
    def score_wall_smoothness(self, image, contours):
        max_s = 10
        if not contours: return self._make('洞壁光滑度', 0, max_s, 0, 0, '粗糙度', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cavity)
        perimeter = cv2.arcLength(cavity, True)
        if area == 0: return self._make('洞壁光滑度', 5, max_s, 0, 0, '粗糙度', '无效', 'warning')

        ideal_p = 2 * np.sqrt(np.pi * area)
        roughness = perimeter / ideal_p - 1

        if roughness < 0.15: r_score, r_note = 1.0, '洞壁光滑 ✓'
        elif roughness < 0.3: r_score, r_note = 0.8, '轻微粗糙'
        elif roughness < 0.5: r_score, r_note = 0.55, '中等粗糙'
        else: r_score, r_note = 0.3, '明显粗糙'

        # 边缘梯度一致性
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        border = cv2.dilate(mask, k) - cv2.erode(mask, k)
        grad = cv2.Sobel(gray, cv2.CV_64F, 1, 1, ksize=3)
        border_grad = np.abs(grad[border > 0])
        grad_std = float(np.std(border_grad)) if len(border_grad) > 0 else 30

        raw = r_score * 0.55 + max(0, 1 - grad_std/50) * 0.45
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【洞壁光滑度打分过程】\n'
            f'├─ 粗糙度指数={roughness:.2f}(<0.15优,>0.5差) → {r_score:.0%}×55%\n'
            f'├─ 梯度一致性(std={grad_std:.1f}) → {max(0,1-grad_std/50):.0%}×45%\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = ('洞壁光滑。' if roughness < 0.2 else
                      '洞壁粗糙。建议：使用金刚砂车针修整洞壁，去除悬突，使洞壁平滑连续、无台阶。')
        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('洞壁光滑度', score, max_s, roughness, 0, '粗糙度', f'R={roughness:.2f}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 4. 髓室顶揭除完整度 (10分) — 基于洞底颜色/纹理均匀性
    # ═══════════════════════════════════════
    def score_roof_removal(self, image, contours):
        max_s = 10
        if not contours: return self._make('髓室顶揭除', 0, max_s, 0, 1, '完整度', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cavity_gray = gray[mask > 0]
        if len(cavity_gray) < 20:
            return self._make('髓室顶揭除', 5, max_s, 0, 1, '完整度', '像素不足', 'warning')

        # 髓室内部应该均匀暗（髓室顶揭除后露出的髓室空间）
        mean_val = float(np.mean(cavity_gray))
        std_val = float(np.std(cavity_gray))

        # 内部颜色均匀性 → 揭除完整度
        uniform_score = max(0, 1 - std_val / 35)
        # 深度足够 → 髓室内部应明显暗于牙面
        surround = gray.copy()
        surround[mask > 0] = 0
        surround_vals = surround[surround > 0]
        surround_mean = float(np.mean(surround_vals)) if len(surround_vals) > 0 else mean_val + 40
        depth_contrast = surround_mean - mean_val

        if depth_contrast > 30:
            depth_score, depth_note = 1.0, '洞内明显深于牙面,髓室顶已揭除 ✓'
        elif depth_contrast > 15:
            depth_score, depth_note = 0.6, '深度一般,髓室顶可能部分残留'
        else:
            depth_score, depth_note = 0.3, '深度不足,髓室顶可能未完全揭除'

        raw = uniform_score * 0.4 + depth_score * 0.6
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【髓室顶揭除打分过程】\n'
            f'├─ 洞内灰度均值={mean_val:.0f}, 标准差={std_val:.1f}\n'
            f'├─ 均匀性: {uniform_score:.0%}×40%\n'
            f'├─ 深度对比: {depth_contrast:.0f}(>30优) → {depth_note} → {depth_score:.0%}×60%\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = ('髓室顶揭除完整。' if raw >= 0.75 else
                      '髓室顶可能未完全揭除。建议：用探针沿洞壁探查有无悬突(髓室顶残余)，确认根管口完全暴露、髓室底清晰可见。')
        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('髓室顶揭除', score, max_s, raw, 1.0, '完整度', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 5. 根管口暴露清晰度 (10分)
    # ═══════════════════════════════════════
    def score_orifice_exposure(self, image, contours):
        max_s = 10
        if not contours: return self._make('根管口暴露', 5, max_s, 0, 1, '清晰度', '未检测', 'warning')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cavity_gray = gray[mask > 0]

        if len(cavity_gray) < 50:
            return self._make('根管口暴露', 5, max_s, 0, 1, '清晰度', '像素不足', 'warning')

        # 寻找洞底最暗的多个斑点(可能的根管口)
        dark_threshold = np.percentile(cavity_gray, 15)  # 最暗15%
        dark_mask = np.zeros_like(gray)
        dark_mask[mask > 0] = (gray[mask > 0] < dark_threshold).astype(np.uint8) * 255

        # 检测暗区连通域数量(可能的根管口数量)
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dark_mask, connectivity=8)
        # 排除太小的噪点
        valid_orifices = sum(1 for i in range(1, n_labels) if stats[i, cv2.CC_STAT_AREA] > 10)

        # 合理根管口数: 前牙1个,前磨牙1-2个,磨牙3-4个
        # 无法确定牙位，范围1-4都算合理
        if 1 <= valid_orifices <= 4:
            count_score, count_note = 1.0, f'检测到{valid_orifices}个可能的根管口，数量合理 ✓'
        elif valid_orifices == 0:
            count_score, count_note = 0.3, '未检测到明确根管口，可能髓室顶未完全揭除'
        else:
            count_score, count_note = 0.6, f'根管口数量异常({valid_orifices}个),可能有误判'

        raw = count_score
        score = max_s * raw

        process = (
            f'【根管口暴露打分过程】\n'
            f'├─ 洞底暗区分析：检测到{valid_orifices}个可能的根管口\n'
            f'├─ 连通域分析：共{n_labels-1}个暗区,有效{valid_orifices}个(>10px)\n'
            f'├─ {count_note} → {count_score:.0%}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = ('根管口暴露清晰。' if valid_orifices >= 1 else
                      '未检测到根管口。建议：进一步揭除髓室顶，用DG16探针探查根管口位置。磨牙需确认MB、DB、P或MB1、MB2、DB、P等全部根管口。')
        status = 'good' if valid_orifices >= 1 else 'bad'
        return self._make('根管口暴露', score, max_s, valid_orifices, 3, '个', f'{valid_orifices}个', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 6. 髓室底完整性 (10分)
    # ═══════════════════════════════════════
    def score_floor_integrity(self, image, contours):
        max_s = 10
        if not contours: return self._make('髓室底完整性', 5, max_s, 0, 1, '完整度', '未检测', 'warning')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # 髓室底应该是一个均匀的暗色平面
        # 异常亮点可能表示髓室底穿孔
        cavity_region = gray.copy()
        cavity_region[mask == 0] = 0
        vals = cavity_region[mask > 0]

        if len(vals) < 50:
            return self._make('髓室底完整性', 5, max_s, 0, 1, '完整度', '像素不足', 'warning')

        mean_v = float(np.mean(vals))
        std_v = float(np.std(vals))

        # 检测异常亮点(可能穿孔到牙周膜或根分叉)
        bright_threshold = mean_v + 2.5 * std_v
        bright_pixels = np.sum(vals > bright_threshold)
        bright_ratio = bright_pixels / len(vals)

        if bright_ratio < 0.03:
            bright_score, bright_note = 1.0, '无异常亮点,髓室底完整 ✓'
        elif bright_ratio < 0.08:
            bright_score, bright_note = 0.6, f'存在少量亮点({bright_ratio:.1%}),可能存在轻微损伤'
        else:
            bright_score, bright_note = 0.25, f'异常亮点较多({bright_ratio:.1%}),⚠️ 警惕髓室底穿孔!'

        raw = bright_score
        score = max_s * raw

        process = (
            f'【髓室底完整性打分过程】\n'
            f'├─ 洞底灰度: 均值={mean_v:.0f}, 标准差={std_v:.1f}\n'
            f'├─ 异常亮点检测(>均值+2.5σ): {bright_pixels}像素({bright_ratio:.1%})\n'
            f'├─ 穿孔风险评估: {bright_note} → {bright_score:.0%}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        if bright_ratio > 0.05:
            suggestion = ('⚠️ 髓室底可能存在损伤或穿孔！建议：①用探针仔细检查髓室底有无穿通点；'
                         '②如有穿孔，需行穿孔修补(MTA/iRoot BP)；③拍摄术中X线片确认。')
        else:
            suggestion = '髓室底完整性良好。'
        status = 'good' if bright_ratio < 0.03 else ('warning' if bright_ratio < 0.08 else 'bad')
        return self._make('髓室底完整性', score, max_s, bright_ratio, 0, '亮点比', f'{bright_ratio:.1%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 7. 无穿孔检测 (15分) — 综合评估
    # ═══════════════════════════════════════
    def score_no_perforation(self, image, contours):
        max_s = 15
        if not contours: return self._make('无穿孔检测', 5, max_s, 0, 1, '安全性', '未检测', 'warning')

        cavity = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 检测洞缘外异常暗区(侧穿信号)
        expanded = cv2.dilate(mask, np.ones((20, 20), np.uint8))
        surrounding = expanded - mask
        surround_vals = gray[surrounding > 0]

        if len(surround_vals) < 20:
            return self._make('无穿孔检测', 12, max_s, 0, 1, '安全性', '评估受限', 'good')

        surround_mean = float(np.mean(surround_vals))
        # 异常暗区(低于周围均值-40): 可能是侧穿导致的牙龈/骨组织暴露
        dark_anomalies = np.sum(gray[surrounding > 0] < (surround_mean - 40))
        anomaly_ratio = dark_anomalies / np.sum(surrounding > 0)

        # 长宽比极端异常(侧穿可能导致轮廓异常延伸)
        aspect = w / h if h > 0 else 1
        if 0.5 < aspect < 2.5: asp_score = 1.0
        elif 0.3 < aspect < 3.5: asp_score = 0.7
        else: asp_score = 0.4

        if anomaly_ratio < 0.02:
            anom_score, anom_note = 1.0, '未检测到穿孔迹象 ✓'
        elif anomaly_ratio < 0.08:
            anom_score, anom_note = 0.65, '存在可疑区域'
        else:
            anom_score, anom_note = 0.3, '⚠️ 高度怀疑穿孔!'

        raw = anom_score * 0.65 + asp_score * 0.35
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【无穿孔检测打分过程】\n'
            f'├─ 洞缘周围异常暗区: {anomaly_ratio:.1%}(>8%警示) → {anom_note} → {anom_score:.0%}×65%\n'
            f'├─ 轮廓长宽比={aspect:.2f}(0.5-2.5正常) → {asp_score:.0%}×35%\n'
            f'└─ 得分: {score:.1f}/{max_s} ⚠️ 此为AI辅助检测,建议结合X线片确认'
        )

        if anomaly_ratio > 0.05:
            suggestion = '⚠️ 疑似穿孔！建议立即拍摄CBCT或术中X线片确认穿孔位置和范围。侧穿需行MTA修补，底穿预后较差需评估拔除。'
        else:
            suggestion = '未检测到穿孔迹象。保持当前操作规范。'
        status = 'good' if anomaly_ratio < 0.03 else ('warning' if anomaly_ratio < 0.08 else 'bad')
        return self._make('无穿孔检测', score, max_s, anomaly_ratio, 0, '异常率', f'{anomaly_ratio:.1%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 8. 便利形 (5分)
    # ═══════════════════════════════════════
    def score_convenience_form(self, image, contours):
        max_s = 5
        if not contours: return self._make('便利形', 3, max_s, 0, 1, '便利度', '未检测', 'good')

        cavity = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity)
        aspect = w / h if h > 0 else 1

        # 便利形评估: 洞形应有适当扩展,便于器械直线进入
        area = cv2.contourArea(cavity)
        perimeter = cv2.arcLength(cavity, True)
        # 轮廓复杂度: 越复杂说明外形越不规则(可能不够便利)
        complexity = perimeter**2 / (4 * np.pi * area) if area > 0 else 1

        if complexity < 2.5: cx_score, cx_note = 1.0, '外形简洁,器械可直线进入 ✓'
        elif complexity < 4.0: cx_score, cx_note = 0.7, '外形稍复杂'
        else: cx_score, cx_note = 0.4, '外形过于复杂,可能影响器械进入'

        # 长宽比合理(便于操作)
        if 0.5 < aspect < 2.0: asp_s = 1.0
        else: asp_s = 0.6

        raw = cx_score * 0.5 + asp_s * 0.5
        score = max_s * raw

        process = (
            f'【便利形打分过程】\n'
            f'├─ 轮廓复杂度={complexity:.1f}(<2.5优) → {cx_score:.0%}×50%\n'
            f'├─ 长宽比={aspect:.2f} → {asp_s:.0%}×50%\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = '便利形良好。' if raw >= 0.7 else '便利形可优化。建议：适当扩展洞形，去除牙本质悬突，确保根管器械可直线进入根管口。'
        status = 'good' if raw >= 0.7 else 'warning'
        return self._make('便利形', score, max_s, raw, 1.0, '便利度', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 9. 洞壁外展度 (5分)
    # ═══════════════════════════════════════
    def score_wall_divergence(self, image, contours):
        max_s = 5
        if not contours:
            return self._make('洞壁外展度', 3, max_s, 0, 5, '度', '未检测', 'good')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # 外展度评估: 从洞底到洞口的灰度渐变(洞底暗→洞口亮)
        # 纵向扫描灰度变化
        y_indices, x_indices = np.where(mask > 0)
        if len(y_indices) < 20:
            return self._make('洞壁外展度', 3, max_s, 0, 5, '度', '数据不足', 'good')

        y_min, y_max = y_indices.min(), y_indices.max()
        # 上半区(洞口)vs下半区(洞底)的平均宽度
        mid_y = (y_min + y_max) // 2
        top_rows = mask[y_min:mid_y, :]
        bot_rows = mask[mid_y:y_max+1, :]

        top_cols = np.where(top_rows.sum(axis=0) > 0)[0]
        bot_cols = np.where(bot_rows.sum(axis=0) > 0)[0]

        top_w = top_cols[-1] - top_cols[0] if len(top_cols) >= 2 else 100
        bot_w = bot_cols[-1] - bot_cols[0] if len(bot_cols) >= 2 else 80

        # 洞口>洞底 = 外展 ✓
        ratio = top_w / bot_w if bot_w > 0 else 1.1
        if 1.05 < ratio < 1.5:
            div_score, div_note = 1.0, f'洞壁向外展开{ratio:.1f}倍,外展度合适 ✓'
        elif 0.9 < ratio < 1.8:
            div_score, div_note = 0.7, f'外展度{ratio:.1f}倍,基本合理'
        else:
            div_score, div_note = 0.4, f'外展度异常({ratio:.1f}倍)'

        raw = div_score
        score = max_s * raw

        process = (
            f'【洞壁外展度打分过程】\n'
            f'├─ 洞口宽度={top_w}px, 洞底宽度={bot_w}px\n'
            f'├─ 外展比={ratio:.2f}(理想1.05-1.5)\n'
            f'├─ {div_note} → {div_score:.0%}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = '外展度合适。' if 0.9 < ratio < 1.7 else '外展度需调整。建议：洞壁向咬合面方向外展2-5度，形成漏斗状，便于器械进入和视野暴露。'
        status = 'good' if 0.9 < ratio < 1.7 else 'warning'
        return self._make('洞壁外展度', score, max_s, ratio, 1.2, '倍', f'{ratio:.1f}x', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 10. 牙体组织保存 (5分)
    # ═══════════════════════════════════════
    def score_tooth_preservation(self, image, contours):
        max_s = 5
        if not contours: return self._make('牙体保存', 3, max_s, 0, 1, '保存度', '未检测', 'good')

        cavity = max(contours, key=cv2.contourArea)
        cavity_area = cv2.contourArea(cavity)

        # 检测牙体总轮廓
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, tooth_bin = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        tooth_contours, _ = cv2.findContours(tooth_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if tooth_contours:
            tooth = max(tooth_contours, key=cv2.contourArea)
            tooth_area = cv2.contourArea(tooth)
            ratio = cavity_area / tooth_area if tooth_area > 0 else 0.15

            if ratio < 0.25: preserve_score, note = 1.0, f'去除{ratio:.0%}牙体,保存良好 ✓'
            elif ratio < 0.45: preserve_score, note = 0.7, f'去除{ratio:.0%},保存尚可'
            else: preserve_score, note = 0.4, f'去除{ratio:.0%}牙体,磨除过多'
        else:
            preserve_score, note, ratio = 0.8, '牙冠边界检测受限', 0.15

        raw = preserve_score
        score = max_s * raw

        process = (
            f'【牙体保存打分过程】\n'
            f'├─ 开髓面积/牙冠面积 = {ratio:.0%}(理想<25%)\n'
            f'├─ {note} → {preserve_score:.0%}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = '牙体保存良好。' if ratio < 0.3 else '去除牙体组织偏多。建议：开髓以暴露全部根管口为度，避免过度扩展，保留更多健康牙体组织以增强牙体抗力。'
        status = 'good' if ratio < 0.3 else 'warning'
        return self._make('牙体保存', score, max_s, ratio, 0.2, '占比', f'{ratio:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 主分析入口
    # ═══════════════════════════════════════
    def analyze(self, image_path):
        image = cv2.imread(image_path)
        report = ScoringReport()
        if image is None:
            report.problem_areas = [{'msg': '无法读取图像'}]
            return report

        h, w = image.shape[:2]
        if max(h, w) > 600:
            scale = 600 / max(h, w)
            image = cv2.resize(image, (int(w*scale), int(h*scale)))

        self.calibration_scale = self.detect_scale(image)
        binary, contours = self.extract_region(image)

        dims = [
            self.score_access_location(image, contours),
            self.score_outline_form(image, contours),
            self.score_wall_smoothness(image, contours),
            self.score_roof_removal(image, contours),
            self.score_orifice_exposure(image, contours),
            self.score_floor_integrity(image, contours),
            self.score_no_perforation(image, contours),
            self.score_convenience_form(image, contours),
            self.score_wall_divergence(image, contours),
            self.score_tooth_preservation(image, contours),
        ]

        report.dimensions = dims
        report.total_score = round(sum(d.score for d in dims if d), 1)

        good = [d for d in dims if d.status == 'good']
        bad = [d for d in dims if d.status == 'bad']
        report.strengths = [f'{d.name}:{d.score:.0f}/{d.max_score}' for d in good]
        report.weaknesses = [f'{d.name}:{d.targeted_suggestion[:60]}' for d in (bad + [d for d in dims if d.status == 'warning'])]

        if report.total_score >= 90: report.overall_assessment = '优秀。开髓洞形制备规范。'
        elif report.total_score >= 80: report.overall_assessment = '良好。主要维度达标。'
        elif report.total_score >= 70: report.overall_assessment = '中等。部分维度可优化。'
        elif report.total_score >= 60: report.overall_assessment = '及格。达到基本要求。'
        else: report.overall_assessment = '不及格。需重点改进。'

        for d in bad + [d for d in dims if d.status == 'warning']:
            report.problem_areas.append({'dimension': d.name, 'detail': d.detail, 'severity': d.status,
                                         'process_analysis': d.process_analysis, 'suggestion': d.targeted_suggestion})

        return report


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        e = 开髓洞形评分引擎()
        r = e.analyze(sys.argv[1])
        print(f'总分: {r.total_score:.1f}/100 | {r.overall_assessment}')
        for d in r.dimensions:
            print(f'  {d.name}: {d.score:.1f}/{d.max_score} [{d.status}]')
