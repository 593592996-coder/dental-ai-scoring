#!/usr/bin/env python3
"""
开髓术AI评分引擎 — 对标口内开髓术评分表
评分表结构：操作过程(25分) + 开髓结果(75分) = 100分
穿孔直接0分
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List


@dataclass
class CavityMeasurement:
    name: str; score: float; max_score: float; raw_value: float
    ideal_value: float; unit: str; detail: str; status: str
    process_analysis: str = ''; targeted_suggestion: str = ''


@dataclass
class ScoringReport:
    total_score: float = 0; max_total: float = 100
    dimensions: List[CavityMeasurement] = field(default_factory=list)
    is_perforated: bool = False
    overall_assessment: str = ''
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    manual_check_items: List[str] = field(default_factory=list)


# ============================================================
# 评分配置 — 严格对开口内开髓术评分表
# ============================================================
SCORING_CONFIG = {
    # —— 操作过程 25分 (AI仅能部分评估) ——
    'instrument_selection':  {'max': 2.5, 'desc': '器械选择', 'ai_able': False},
    'grip_method':           {'max': 12.5, 'desc': '握持方式及支点', 'ai_able': False},
    'operation_procedure':   {'max': 10, 'desc': '操作动作及程序', 'ai_able': False},
    # —— 开髓结果 75分 (AI可评估) ——
    'opening_position_shape': {'max': 20, 'desc': '开口位置、洞型及牙体组织量', 'ai_able': True},
    'roof_removal':           {'max': 20, 'desc': '髓室顶去净', 'ai_able': True},
    'chamber_morphology':     {'max': 20, 'desc': '髓腔形态和髓室底完整', 'ai_able': True},
    'orifice_location':       {'max': 15, 'desc': '定位根管口', 'ai_able': True},
}


class 开髓术评分引擎:
    """开髓术AI评分引擎 — 对标官方评分表"""

    def __init__(self):
        self.calibration_scale = None
        self.is_perforated = False  # 穿孔标志 — 直接0分

    def _make(self, name, score, max_s, raw, ideal, unit, detail, status, process='', suggestion=''):
        return CavityMeasurement(name=name, score=round(min(max_s, max(0, score)), 1),
                                 max_score=max_s, raw_value=round(raw, 3),
                                 ideal_value=ideal, unit=unit, detail=detail, status=status,
                                 process_analysis=process, targeted_suggestion=suggestion)

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
    # 穿孔检测 (贯穿整个评估)
    # ═══════════════════════════════════════
    def check_perforation(self, image, contours):
        """检测髓室侧壁或髓室底穿孔 — 如有则直接0分"""
        if not contours: return False

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 检测洞缘外异常暗区(侧穿信号)
        expanded = cv2.dilate(mask, np.ones((25, 25), np.uint8))
        surrounding = expanded - mask
        surround_vals = gray[surrounding > 0]
        if len(surround_vals) < 20: return False

        surround_mean = float(np.mean(surround_vals))
        # 侧穿: 异常暗于周围=暴露了牙周组织
        dark_anomalies = np.sum(gray[surrounding > 0] < (surround_mean - 45))
        anomaly_ratio = dark_anomalies / np.sum(surrounding > 0)

        # 检测洞底异常亮点(底穿=髓室底穿通到根分叉)
        cavity_vals = gray[mask > 0]
        if len(cavity_vals) < 50: return False
        c_mean, c_std = float(np.mean(cavity_vals)), float(np.std(cavity_vals))
        bright_anomalies = np.sum(cavity_vals > c_mean + 2.5 * c_std)
        bright_ratio = bright_anomalies / len(cavity_vals)

        # 轮廓极端不规则(穿孔导致轮廓异常延伸)
        x, y, w, h = cv2.boundingRect(cavity)
        aspect = w / h if h > 0 else 1

        # 综合判定
        side_risk = anomaly_ratio > 0.1
        floor_risk = bright_ratio > 0.08
        shape_risk = (aspect < 0.25 or aspect > 4.0)

        perf_score = (1 if side_risk else 0) + (1 if floor_risk else 0) + (1 if shape_risk else 0)

        self.is_perforated = (perf_score >= 2)  # 两个以上指标异常
        self.perf_details = {
            'anomaly_ratio': anomaly_ratio, 'bright_ratio': bright_ratio,
            'aspect': aspect, 'side_risk': side_risk,
            'floor_risk': floor_risk, 'shape_risk': shape_risk
        }
        return self.is_perforated

    # ═══════════════════════════════════════
    # 1. 开口位置、洞型及牙体组织量 (20分)  【评分表: 位置洞形5+牙体组织15=20】
    # ═══════════════════════════════════════
    def score_opening_position_shape(self, image, contours):
        max_s = 20
        if not contours:
            return self._make('开口位置洞形及牙体组织', 0, max_s, 0, 1, '得分', '未检测到开髓洞形', 'bad',
                              process='❌ 图像中未检测到开髓洞形。')

        cavity = max(contours, key=cv2.contourArea)
        M = cv2.moments(cavity)
        if M['m00'] == 0:
            return self._make('开口位置洞形及牙体组织', 5, max_s, 0, 1, '得分', '无法定位', 'warning')

        cx = int(M['m10'] / M['m00']); cy = int(M['m01'] / M['m00'])
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, tooth_bin = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        tooth_contours, _ = cv2.findContours(tooth_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not tooth_contours:
            return self._make('开口位置洞形及牙体组织', 10, max_s, 0, 1, '得分', '牙体检测受限', 'warning',
                              process='⚠️ 牙冠边界检测受限，位置评估不完整。')

        tooth = max(tooth_contours, key=cv2.contourArea)
        tx, ty, tw, th = cv2.boundingRect(tooth)
        tooth_cx, tooth_cy = tx + tw//2, ty + th//2

        # — 子维度①：开口位置 (5分) —
        deviation = np.sqrt((cx - tooth_cx)**2 + (cy - tooth_cy)**2)
        max_dev = np.sqrt(tw**2 + th**2) / 2
        dev_ratio = deviation / max_dev if max_dev > 0 else 0

        if dev_ratio < 0.12:
            pos_score, pos_note = 5.0, '开口位置正确，位于颌面中央窝 ✓'
            pos_status = 'good'
        elif dev_ratio < 0.25:
            pos_score, pos_note = 3.5, f'开口位置略有偏移({dev_ratio:.0%})，基本正确'
            pos_status = 'warning'
        else:
            pos_score, pos_note = 1.5, f'开口位置偏离中心({dev_ratio:.0%})，位置不正确'
            pos_status = 'bad'

        # — 子维度②：洞形标准度 (5分，含在15分牙体组织量内) —
        area = cv2.contourArea(cavity)
        perimeter = cv2.arcLength(cavity, True)
        circularity = 4 * np.pi * area / (perimeter**2) if perimeter > 0 else 0
        hull = cv2.convexHull(cavity)
        convexity = area / cv2.contourArea(hull) if cv2.contourArea(hull) > 0 else 0

        # 磨牙应为圆三角形/椭圆形(非正圆)
        if 0.5 < circularity < 0.9:
            shape_score, shape_note = 5.0, '洞形为圆三角形/椭圆形，标准 ✓'
            shape_status = 'good'
        elif 0.35 < circularity < 0.95:
            shape_score, shape_note = 3.0, '洞形基本可接受'
            shape_status = 'warning'
        else:
            shape_score, shape_note = 1.0, '洞形差，过于圆形或过于不规则'
            shape_status = 'bad'

        # — 子维度③：牙体组织保存 (10分，总计牙体组织15分-5分洞形) —
        cavity_area = cv2.contourArea(cavity)
        tooth_area = cv2.contourArea(tooth)
        area_ratio = cavity_area / tooth_area if tooth_area > 0 else 0.2

        if area_ratio < 0.2:
            tissue_score, tissue_note = 10.0, f'开髓口大小适中({area_ratio:.0%})，牙体保存良好 ✓'
            tissue_status = 'good'
        elif area_ratio < 0.35:
            tissue_score, tissue_note = 6.0, f'开髓口较大({area_ratio:.0%})，对牙体有所损伤'
            tissue_status = 'warning'
        else:
            tissue_score, tissue_note = 2.0, f'开髓口过大({area_ratio:.0%})，牙体损伤大'
            tissue_status = 'bad'

        total = pos_score + shape_score + tissue_score  # max 5+5+10=20
        raw = total / max_s

        process = (
            f'【开口位置、洞型及牙体组织量 — 评分表20分】\n'
            f'├─ 开口位置(5分): 中心偏离{dev_ratio:.0%}(理想<12%) → {pos_note} → {pos_score}/5\n'
            f'├─ 洞形标准(5分): 圆形度={circularity:.2f},凸度={convexity:.2f} → {shape_note} → {shape_score}/5\n'
            f'├─ 牙体组织(10分): 开髓面积/牙面={area_ratio:.0%}(理想<20%) → {tissue_note} → {tissue_score}/10\n'
            f'└─ 合计: {total:.1f}/{max_s}'
        )

        if area_ratio > 0.35:
            suggestion = '开髓口过大，牙体组织损伤大。建议：开髓以暴露全部根管口为度，避免过度扩展，保留边缘嵴和牙尖。'
        elif dev_ratio > 0.25:
            suggestion = '开口位置不正确。下磨牙应在颌面中央偏颊侧；上磨牙在颌面中央窝。术前通过X线片确定髓室位置。'
        else:
            suggestion = '开口位置、洞形及牙体保留良好。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('开口位置洞形及牙体组织', total, max_s, raw, 1.0, '得分', f'{total:.1f}/20', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 2. 髓室顶去净 (20分)
    # ═══════════════════════════════════════
    def score_roof_removal(self, image, contours):
        """评估髓室顶是否完全揭除 — 评分表20分"""
        max_s = 20
        if not contours:
            return self._make('髓室顶去净', 0, max_s, 0, 1, '得分', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        cavity_vals = gray[mask > 0]
        if len(cavity_vals) < 30:
            return self._make('髓室顶去净', 5, max_s, 0, 1, '得分', '像素不足', 'warning')

        # 指标1: 洞内深度足够(髓室顶揭除后髓室空间深)
        surround = gray.copy(); surround[mask > 0] = 0
        s_vals = surround[surround > 0]
        s_mean = float(np.mean(s_vals)) if len(s_vals) > 0 else 200
        c_mean = float(np.mean(cavity_vals))
        depth = s_mean - c_mean

        if depth > 40:
            dep_score, dep_note = 1.0, '洞内深度充足，髓室顶已揭除 ✓'
        elif depth > 20:
            dep_score, dep_note = 0.6, '深度一般，髓室顶可能部分残留'
        else:
            dep_score, dep_note = 0.25, '深度不足，髓室顶可能未揭除'

        # 指标2: 洞底无悬突(髓室顶残余表现为边缘悬突)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask_eroded = cv2.erode(mask, kernel, iterations=2)
        mask_diff = mask - mask_eroded
        edge_vals = gray[mask_diff > 0]
        edge_std = float(np.std(edge_vals)) if len(edge_vals) > 0 else 30

        # 悬突检测: 边缘灰度不均匀 → 髓室顶残留
        if edge_std < 22:
            overhang_score, overhang_note = 1.0, '边缘均匀，无悬突(=髓室顶去净) ✓'
        elif edge_std < 35:
            overhang_score, overhang_note = 0.55, '边缘有轻微不均匀(=少数部位残留)'
        else:
            overhang_score, overhang_note = 0.2, '边缘明显不均匀(=髓室顶残留)'

        # 指标3: 洞内灰度均匀性
        c_std = float(np.std(cavity_vals))
        uniform_score = max(0, 1 - c_std / 40)

        raw = dep_score * 0.35 + overhang_score * 0.40 + uniform_score * 0.25
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        # 映射到评分表三档
        if raw >= 0.75:
            grade = '探针小弯端不能勾住髓室顶边缘(15分档)'
        elif raw >= 0.45:
            grade = '探针小弯端能勾住少数部位髓室顶边缘(10分档)'
        else:
            grade = '探针小弯端能勾住各个部位髓室顶边缘(0分档)'

        process = (
            f'【髓室顶去净 — 评分表20分】\n'
            f'├─ 深度充足度: {dep_score:.0%}×35% (对比度={depth:.0f}) → {dep_note}\n'
            f'├─ 悬突/残留检测: {overhang_score:.0%}×40% (边缘std={edge_std:.1f}) → {overhang_note}\n'
            f'├─ 均匀性: {uniform_score:.0%}×25%\n'
            f'└─ 综合={raw:.0%} → {grade} → {score:.1f}/{max_s}'
        )

        if raw < 0.5:
            suggestion = '髓室顶未完全揭除。用探针小弯端沿洞壁探查，勾住悬突处即为残留髓室顶，用球钻或安全车针去除。'
        else:
            suggestion = '髓室顶揭除良好。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('髓室顶去净', score, max_s, raw, 1.0, '得分', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 3. 髓腔形态和髓室底完整 (20分)
    # ═══════════════════════════════════════
    def score_chamber_morphology(self, image, contours):
        """评估髓室侧壁是否拉直、有无牙本质领、髓室底完整 — 评分表20分"""
        max_s = 20
        if not contours:
            return self._make('髓腔形态和髓室底完整', 0, max_s, 0, 1, '得分', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 指标1: 侧壁直线度(无牙本质领=侧壁拉直)
        epsilon = 0.02 * cv2.arcLength(cavity, True)
        approx = cv2.approxPolyDP(cavity, epsilon, True)
        edges_info = []
        for i in range(len(approx)):
            p1, p2 = approx[i][0], approx[(i+1)%len(approx)][0]
            dx, dy = p2[0]-p1[0], p2[1]-p1[1]
            length = np.sqrt(dx**2 + dy**2)
            if length > 15:
                edges_info.append({'length': length, 'dx': dx, 'dy': dy})

        if edges_info:
            # 侧壁直线度: 多边形逼近的边数越少且边长越长 → 侧壁越直
            avg_edge_len = np.mean([e['length'] for e in edges_info])
            wall_straightness = min(1.0, avg_edge_len / 60)
        else:
            wall_straightness = 0.5

        # 指标2: 外展度(侧壁向外展开=拉直)
        x, y, w, h = cv2.boundingRect(cavity)
        top_half = mask[y:y+h//2, :]
        bot_half = mask[y+h//2:y+h, :]
        top_cols = np.where(top_half.sum(axis=0) > 0)[0]
        bot_cols = np.where(bot_half.sum(axis=0) > 0)[0]
        top_w = top_cols[-1]-top_cols[0] if len(top_cols) >= 2 else w
        bot_w = bot_cols[-1]-bot_cols[0] if len(bot_cols) >= 2 else w
        flare_ratio = top_w / bot_w if bot_w > 0 else 1.1

        # 外展度1.05-1.4为合理
        if 1.05 < flare_ratio < 1.5:
            flare_score, flare_note = 1.0, '侧壁向外展开，无牙本质领 ✓'
        elif 0.9 < flare_ratio < 1.7:
            flare_score, flare_note = 0.6, '外展度一般，可能有牙本质领'
        else:
            flare_score, flare_note = 0.3, '侧壁未拉直或过度磨除'

        # 指标3: 髓室底完整性(异常亮点=底穿风险)
        c_vals = gray[mask > 0]
        c_mean, c_std = float(np.mean(c_vals)), float(np.std(c_vals))
        bright_ratio = float(np.sum(c_vals > c_mean + 2.5*c_std)) / len(c_vals)

        if bright_ratio < 0.03:
            floor_score, floor_note = 1.0, '髓室底完整，无异常 ✓'
        elif bright_ratio < 0.07:
            floor_score, floor_note = 0.55, '髓室底可能有轻微磨损'
        else:
            floor_score, floor_note = 0.15, '⚠️ 髓室底异常，警惕穿孔!'

        raw = wall_straightness * 0.30 + flare_score * 0.35 + floor_score * 0.35
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        if raw >= 0.7:
            grade = '髓室侧壁拉直、髓室底完整(15分档)'
        else:
            grade = '侧壁不直或有牙本质领/髓室底磨损(10分档)'

        process = (
            f'【髓腔形态和髓室底完整 — 评分表20分】\n'
            f'├─ 侧壁直线度: {wall_straightness:.0%}×30% → 平均边长={avg_edge_len:.0f}px\n'
            f'├─ 外展度(去牙本质领): 洞口/洞底={flare_ratio:.2f} → {flare_note} → {flare_score:.0%}×35%\n'
            f'├─ 髓室底完整: 异常亮点{bright_ratio:.1%}(<3%正常) → {floor_note} → {floor_score:.0%}×35%\n'
            f'└─ 综合={raw:.0%} → {grade} → {score:.1f}/{max_s}'
        )

        if flare_ratio < 1.0:
            suggestion = '侧壁未拉直，存在牙本质领。用安全车针去除牙本质领，使髓室侧壁与根管口直线相连。'
        elif bright_ratio > 0.05:
            suggestion = '⚠️ 髓室底可能磨损或穿孔！用探针检查完整性，如有穿孔需行MTA修补。'
        else:
            suggestion = '髓腔形态和髓室底良好。'

        status = 'good' if raw >= 0.7 else ('warning' if raw >= 0.4 else 'bad')
        return self._make('髓腔形态和髓室底完整', score, max_s, raw, 1.0, '得分', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 4. 定位根管口 (15分)
    # ═══════════════════════════════════════
    def score_orifice_location(self, image, contours):
        """评估根管口暴露和可探入性 — 评分表15分"""
        max_s = 15
        if not contours:
            return self._make('定位根管口', 0, max_s, 0, 4, '个', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cavity_vals = gray[mask > 0]

        if len(cavity_vals) < 50:
            return self._make('定位根管口', 5, max_s, 0, 4, '个', '像素不足', 'warning')

        # 检测根管口: 洞底最暗的多个斑点
        dark_threshold = np.percentile(cavity_vals, 12)
        dark_mask = np.zeros_like(gray)
        dark_mask[mask > 0] = (gray[mask > 0] < dark_threshold).astype(np.uint8) * 255

        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dark_mask, connectivity=8)
        valid_orifices = sum(1 for i in range(1, n_labels) if stats[i, cv2.CC_STAT_AREA] > 8)

        # 映射到评分表四档
        if valid_orifices >= 3:
            note = '所有根管口暴露清楚，根管器械可直线探入(15分档)'
            score = 15.0
            status = 'good'
        elif valid_orifices >= 2:
            note = '根管口暴露尚清楚，但不能自开髓口顺畅探入(10分档)'
            score = 10.0
            status = 'warning'
        elif valid_orifices >= 1:
            note = '遗漏根管口，不能直线探入该根管(5分档)'
            score = 5.0
            status = 'bad'
        else:
            note = '根管口均未暴露(0分档)'
            score = 0
            status = 'bad'

        process = (
            f'【定位根管口 — 评分表15分】\n'
            f'├─ 洞底暗区分析: 检测到{valid_orifices}个可能的根管口\n'
            f'├─ 评分表标准:\n'
            f'│   所有根管口暴露清楚,可直线探入 → 15分\n'
            f'│   暴露尚清楚,但不能顺畅探入 → 10分\n'
            f'│   遗漏根管口 → 5分\n'
            f'│   均未暴露 → 0分\n'
            f'├─ 判定: {note}\n'
            f'└─ 得分: {score}/{max_s}'
        )

        if valid_orifices < 2:
            suggestion = '根管口暴露不全。检查髓室顶是否完全揭除，用DG16探针探查各根管口。磨牙需确认MB、MB2、DB、P等全部根管口。'
        else:
            suggestion = '根管口定位良好。'

        return self._make('定位根管口', score, max_s, valid_orifices, 4, '个', f'{valid_orifices}个', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════
    def analyze(self, image_path):
        image = cv2.imread(image_path)
        report = ScoringReport()
        if image is None:
            report.overall_assessment = '无法读取图像'
            return report

        h, w = image.shape[:2]
        if max(h, w) > 600:
            scale = 600 / max(h, w)
            image = cv2.resize(image, (int(w*scale), int(h*scale)))

        self.calibration_scale = self.detect_scale(image)
        binary, contours = self.extract_region(image)

        # 穿孔检测 — 最高优先级
        perf = self.check_perforation(image, contours)

        if self.is_perforated:
            # 穿孔直接0分
            dims = [
                self._make('⚠️ 穿孔-项目0分', 0, 100, 0, 0, '', '发现髓室侧壁或髓室底穿孔!考试项目为0分', 'bad',
                           process=f'【穿孔检测】\n侧壁风险:{self.perf_details.get("side_risk",False)}\n底穿风险:{self.perf_details.get("floor_risk",False)}\n轮廓异常:{self.perf_details.get("shape_risk",False)}\n→ 三项指标中两项以上异常，判定穿孔。\n→ 按照评分表规定：如有髓室侧壁或髓室底穿孔，则该考试项目"0"分。',
                           suggestion='⚠️ 穿孔！拍摄CBCT确认穿孔位置和范围。侧穿行MTA修补；底穿预后较差。'),
            ]
            report.dimensions = dims
            report.total_score = 0
            report.is_perforated = True
            report.overall_assessment = '穿孔！按照评分表规定，该项目为0分。'
            return report

        # 正常评分: 操作过程(25分需人工) + 开髓结果(75分AI评估)
        # AI只能评估开髓结果部分，操作过程标注为"需人工评分"
        manual_dims = [
            self._make('器械选择 [人工]', 2.5, 2.5, 1.0, 1, '', '请教师现场评分', 'good',
                       process='🖐 此项需人工评分。检查是否选用高速涡轮机、慢速手机、裂钻、球钻、探针、根管锉等。',
                       suggestion=''),
            self._make('握持方式及支点 [人工]', 12.5, 12.5, 1.0, 1, '', '请教师现场评分', 'good',
                       process='🖐 此项需人工评分。\n评分要点: 左手固定(5分)|改良握笔式(2.5分)|无名指支点(2.5分)|点磨平行牙长轴(2.5分)',
                       suggestion=''),
            self._make('操作动作及程序 [人工]', 10, 10, 1.0, 1, '', '请教师现场评分', 'good',
                       process='🖐 此项需人工评分。\n评分要点: 中央窝进入(2.5分)|穿髓揭髓顶(2.5分)|修整侧壁根管口(2.5分)|定位根管口探查(2.5分)',
                       suggestion=''),
        ]

        ai_dims = [
            self.score_opening_position_shape(image, contours),
            self.score_roof_removal(image, contours),
            self.score_chamber_morphology(image, contours),
            self.score_orifice_location(image, contours),
        ]

        report.dimensions = manual_dims + ai_dims
        report.total_score = round(sum(d.score for d in report.dimensions), 1)
        report.manual_check_items = [
            '器械选择 (2.5分): 检查器械是否齐全',
            '握持方式及支点 (12.5分): 左手固定|改良握笔式|无名指支点|点磨平行牙长轴',
            '操作动作及程序 (10分): 中央窝进入|穿髓揭顶|修整侧壁|定位探查',
        ]

        # 整体评估
        ai_total = sum(d.score for d in ai_dims)
        if ai_total >= 65: report.overall_assessment = '优秀。开髓结果优良，操作规范。'
        elif ai_total >= 50: report.overall_assessment = '良好。开髓结果较好，部分细节可优化。'
        elif ai_total >= 35: report.overall_assessment = '中等。开髓结果基本合格。'
        elif ai_total >= 20: report.overall_assessment = '及格。达到基本要求，多项需改进。'
        else: report.overall_assessment = '不及格。开髓结果存在明显问题。'

        good = [d for d in ai_dims if d.status == 'good']
        bad = [d for d in ai_dims if d.status == 'bad']
        report.strengths = [f'{d.name}:{d.score:.0f}/{d.max_score}' for d in good]
        report.weaknesses = [f'{d.name}:{d.targeted_suggestion[:60]}' for d in (bad + [d for d in ai_dims if d.status == 'warning'])]

        return report


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        e = 开髓术评分引擎()
        r = e.analyze(sys.argv[1])
        print(f'总分: {r.total_score:.1f}/100')
        if r.is_perforated:
            print('⚠️ 穿孔 — 0分!')
        else:
            print(f'AI评估: {r.overall_assessment}')
            for d in r.dimensions:
                print(f'  {d.name}: {d.score}/{d.max_score}')
            if r.manual_check_items:
                print(f'\n🖐 需人工评分项目:')
                for m in r.manual_check_items:
                    print(f'  {m}')
