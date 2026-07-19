#!/usr/bin/env python3
"""
开髓术AI评分引擎 v3 — 纯AI评估(去除操作过程)
对标评分表开髓结果部分(75分) → 归一化到100分
穿孔直接0分 | 定位根管口需插入K锉照片
"""

import cv2, numpy as np
from dataclasses import dataclass, field
from typing import List


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
    kfile_detected: bool = False
    overall_assessment: str = ''
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

SCORING_CONFIG = {
    'opening_position_shape': {'max': 25, 'desc': '开口位置、洞型及牙体组织量', 'orig': 20},
    'roof_removal': {'max': 25, 'desc': '髓室顶去净', 'orig': 20},
    'chamber_morphology': {'max': 25, 'desc': '髓腔形态和髓室底完整', 'orig': 20},
    'orifice_location': {'max': 25, 'desc': '定位根管口(插K锉)', 'orig': 15},
}


class 开髓术评分引擎:
    def __init__(self):
        self.is_perforated = False
        self.kfile_detected = False

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
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k); binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return binary, contours

    # ═══════════════════════════════
    # 穿孔检测
    # ═══════════════════════════════
    def check_perforation(self, image, contours):
        if not contours: return False
        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        expanded = cv2.dilate(mask, np.ones((25, 25), np.uint8)); surrounding = expanded - mask
        s_vals = gray[surrounding > 0]
        if len(s_vals) < 20: return False
        s_mean = float(np.mean(s_vals))
        anomaly_ratio = float(np.sum(gray[surrounding > 0] < (s_mean - 45)) / np.sum(surrounding > 0))

        c_vals = gray[mask > 0]
        if len(c_vals) < 50: return False
        c_mean, c_std = float(np.mean(c_vals)), float(np.std(c_vals))
        bright_ratio = float(np.sum(c_vals > c_mean + 2.5 * c_std) / len(c_vals))

        x, y, w, h = cv2.boundingRect(cavity)
        aspect = w / h if h > 0 else 1

        side_risk = anomaly_ratio > 0.1; floor_risk = bright_ratio > 0.08; shape_risk = (aspect < 0.25 or aspect > 4.0)
        perf_score = (1 if side_risk else 0) + (1 if floor_risk else 0) + (1 if shape_risk else 0)

        self.is_perforated = (perf_score >= 2)
        self.perf_details = {'anomaly_ratio': anomaly_ratio, 'bright_ratio': bright_ratio,
                              'aspect': aspect, 'side_risk': side_risk, 'floor_risk': floor_risk,
                              'shape_risk': shape_risk}
        return self.is_perforated

    # ═══════════════════════════════
    # 检测K锉(定位根管口专用)
    # ═══════════════════════════════
    def detect_kfiles(self, image, mask):
        """检测插入根管口的K锉 — 细长明亮金属线"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # K锉在X光/照片中表现为: 非常亮(金属反射) + 细长条状
        # 检测高亮细线(相对于暗色洞底)
        cavity_only = gray.copy(); cavity_only[mask == 0] = 0
        if np.sum(mask) == 0: return 0, []

        threshold = np.percentile(cavity_only[mask > 0], 90)
        bright_lines = (cavity_only > threshold).astype(np.uint8) * 255

        # 提取细长连通域(K锉形状特征)
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(bright_lines, connectivity=8)

        kfiles = []
        for i in range(1, n_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            # K锉特征: 面积适中, 长宽比大(细长)
            aspect_ratio = max(w, h) / (min(w, h) + 0.01)
            if 15 < area < 800 and aspect_ratio > 3.0:
                kfiles.append({'area': area, 'aspect': aspect_ratio, 'cx': centroids[i][0], 'cy': centroids[i][1]})

        # 排除太密集的重复检测(<15px距离=同一根K锉)
        unique_kfiles = []
        for kf in kfiles:
            too_close = False
            for uk in unique_kfiles:
                if np.sqrt((kf['cx'] - uk['cx'])**2 + (kf['cy'] - uk['cy'])**2) < 15:
                    too_close = True; break
            if not too_close: unique_kfiles.append(kf)

        self.kfile_detected = len(unique_kfiles) >= 1
        return len(unique_kfiles), unique_kfiles

    # ═══════════════════════════════
    # 1. 开口位置、洞型及牙体组织量 (25分)
    # ═══════════════════════════════
    def score_opening_position_shape(self, image, contours):
        max_s = 25
        if not contours:
            return self._make('开口位置洞形及牙体组织', 0, max_s, 0, 1, '得分', '未检测到开髓洞形', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        M = cv2.moments(cavity)
        if M['m00'] == 0: return self._make('开口位置洞形及牙体组织', 8, max_s, 0, 1, '得分', '无法定位', 'warning')

        cx = int(M['m10']/M['m00']); cy = int(M['m01']/M['m00'])
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, tooth_bin = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        tooth_contours, _ = cv2.findContours(tooth_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not tooth_contours:
            return self._make('开口位置洞形及牙体组织', 12, max_s, 0, 1, '得分', '牙体检测受限', 'warning')

        tooth = max(tooth_contours, key=cv2.contourArea)
        tx, ty, tw, th = cv2.boundingRect(tooth)
        tooth_cx, tooth_cy = tx + tw//2, ty + th//2

        deviation = np.sqrt((cx-tooth_cx)**2 + (cy-tooth_cy)**2)
        max_dev = np.sqrt(tw**2 + th**2) / 2
        dev_ratio = deviation / max_dev if max_dev > 0 else 0

        # 位置: 满分8分(按比例25/20*5≈6.25,取7)
        if dev_ratio < 0.12: pos_score, pos_note = 7.0, '开口位置正确，颌面中央窝 ✓'
        elif dev_ratio < 0.25: pos_score, pos_note = 4.5, f'略有偏移({dev_ratio:.0%})'
        else: pos_score, pos_note = 2.0, f'偏离中心({dev_ratio:.0%})'

        # 洞形: 满分7分(25/20*5≈6.25)
        area = cv2.contourArea(cavity); perimeter = cv2.arcLength(cavity, True)
        circularity = 4*np.pi*area/(perimeter**2) if perimeter > 0 else 0
        if 0.5 < circularity < 0.9: shape_score, shape_note = 7.0, '洞形标准(圆三角形/椭圆形) ✓'
        elif 0.35 < circularity < 0.95: shape_score, shape_note = 4.0, '洞形基本可接受'
        else: shape_score, shape_note = 1.5, '洞形差'

        # 牙体保存: 满分11分(25/20*10≈12.5,取11)
        cavity_area = cv2.contourArea(cavity); tooth_area = cv2.contourArea(tooth)
        area_ratio = cavity_area / tooth_area if tooth_area > 0 else 0.2
        if area_ratio < 0.2: tissue_score, tissue_note = 11.0, f'大小适中({area_ratio:.0%}) ✓'
        elif area_ratio < 0.35: tissue_score, tissue_note = 7.0, f'较大({area_ratio:.0%})'
        else: tissue_score, tissue_note = 2.5, f'过大({area_ratio:.0%})'

        total = pos_score + shape_score + tissue_score
        raw = total / max_s

        process = (
            f'【开口位置、洞型及牙体组织量 — 25分】\n'
            f'├─ 开口位置(7分): 偏离{dev_ratio:.0%}(理想<12%) → {pos_note} → {pos_score}/7\n'
            f'├─ 洞形标准(7分): 圆形度={circularity:.2f} → {shape_note} → {shape_score}/7\n'
            f'├─ 牙体保存(11分): 占比={area_ratio:.0%}(理想<20%) → {tissue_note} → {tissue_score}/11\n'
            f'└─ 合计: {total:.1f}/{max_s}'
        )

        suggestion = ('开口位置、洞形及牙体保留良好。' if raw >= 0.75 else
                      '开髓口过大' if area_ratio > 0.35 else '开口位置偏差' if dev_ratio > 0.2 else '洞形需优化')
        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.5 else 'bad')
        return self._make('开口位置洞形及牙体组织', total, max_s, raw, 1.0, '得分', f'{total:.1f}/25', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════
    # 2. 髓室顶去净 (25分)
    # ═══════════════════════════════
    def score_roof_removal(self, image, contours):
        max_s = 25
        if not contours: return self._make('髓室顶去净', 0, max_s, 0, 1, '得分', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        c_vals = gray[mask > 0]
        if len(c_vals) < 30: return self._make('髓室顶去净', 8, max_s, 0, 1, '得分', '像素不足', 'warning')

        surround = gray.copy(); surround[mask > 0] = 0
        s_vals = surround[surround > 0]; s_mean = float(np.mean(s_vals)) if len(s_vals) > 0 else 200
        c_mean = float(np.mean(c_vals)); depth = s_mean - c_mean

        if depth > 40: dep_s, dep_n = 1.0, '深度充足，髓室顶已揭除 ✓'
        elif depth > 20: dep_s, dep_n = 0.6, '深度一般，可能部分残留'
        else: dep_s, dep_n = 0.25, '深度不足，髓室顶未揭除'

        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        diff = mask - cv2.erode(mask, k, iterations=2)
        edge_vals = gray[diff > 0]; edge_std = float(np.std(edge_vals)) if len(edge_vals) > 0 else 30

        if edge_std < 22: over_s, over_n = 1.0, '无悬突(=去净) ✓'
        elif edge_std < 35: over_s, over_n = 0.55, '轻微不均匀(=少数残留)'
        else: over_s, over_n = 0.2, '明显不均匀(=残留)'

        c_std = float(np.std(c_vals)); unif_s = max(0, 1-c_std/40)
        raw = max(0.0, min(1.0, dep_s * 0.35 + over_s * 0.40 + unif_s * 0.25))
        score = max_s * raw

        if raw >= 0.75: grade = '探针小弯端不能勾住髓室顶边缘(满分档)'
        elif raw >= 0.45: grade = '探针小弯端能勾住少数部位髓室顶边缘(中等档)'
        else: grade = '探针小弯端能勾住各个部位髓室顶边缘(不足档)'

        process = (
            f'【髓室顶去净 — 25分】\n'
            f'├─ 深度: {dep_s:.0%}×35% → {dep_n}\n├─ 悬突检测: {over_s:.0%}×40%(std={edge_std:.1f}) → {over_n}\n'
            f'├─ 均匀性: {unif_s:.0%}×25%\n└─ {grade} → {score:.1f}/{max_s}'
        )
        suggestion = ('髓室顶揭除良好。' if raw >= 0.6 else
                      '髓室顶未完全揭除。用探针探查，球钻去除残留髓室顶。')
        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('髓室顶去净', score, max_s, raw, 1.0, '得分', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════
    # 3. 髓腔形态和髓室底完整 (25分)
    # ═══════════════════════════════
    def score_chamber_morphology(self, image, contours):
        max_s = 25
        if not contours: return self._make('髓腔形态和髓室底完整', 0, max_s, 0, 1, '得分', '未检测', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        epsilon = 0.02 * cv2.arcLength(cavity, True)
        approx = cv2.approxPolyDP(cavity, epsilon, True)
        edge_lens = []
        for i in range(len(approx)):
            p1, p2 = approx[i][0], approx[(i+1)%len(approx)][0]
            l = np.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)
            if l > 15: edge_lens.append(l)
        avg_edge = np.mean(edge_lens) if edge_lens else 30
        wall_s = min(1.0, avg_edge/60)

        x, y, w, h = cv2.boundingRect(cavity)
        top = mask[y:y+h//2, :]; bot = mask[y+h//2:y+h, :]
        tc = np.where(top.sum(axis=0)>0)[0]; bc = np.where(bot.sum(axis=0)>0)[0]
        tw = tc[-1]-tc[0] if len(tc)>=2 else w; bw = bc[-1]-bc[0] if len(bc)>=2 else w
        flare = tw/bw if bw>0 else 1.1

        if 1.05 < flare < 1.5: flare_s, flare_n = 1.0, '侧壁外展，无牙本质领 ✓'
        elif 0.9 < flare < 1.7: flare_s, flare_n = 0.6, '可能有牙本质领'
        else: flare_s, flare_n = 0.3, '侧壁未拉直或过度磨除'

        c_vals = gray[mask > 0]; c_mean, c_std = float(np.mean(c_vals)), float(np.std(c_vals))
        bright_r = float(np.sum(c_vals > c_mean + 2.5*c_std) / len(c_vals))
        if bright_r < 0.03: floor_s, floor_n = 1.0, '髓室底完整 ✓'
        elif bright_r < 0.07: floor_s, floor_n = 0.55, '可能有轻微磨损'
        else: floor_s, floor_n = 0.15, '⚠️ 警惕穿孔!'

        raw = max(0.0, min(1.0, wall_s*0.30 + flare_s*0.35 + floor_s*0.35))
        score = max_s * raw
        grade = '侧壁拉直、髓室底完整(满分档)' if raw >= 0.7 else '侧壁不直或有牙本质领/髓室底磨损(扣分档)'

        process = (
            f'【髓腔形态和髓室底完整 — 25分】\n'
            f'├─ 侧壁直线度: {wall_s:.0%}×30% → 平均边长{avg_edge:.0f}px\n'
            f'├─ 外展度(去牙本质领): {flare:.2f} → {flare_n} → {flare_s:.0%}×35%\n'
            f'├─ 髓室底完整: 亮点{bright_r:.1%} → {floor_n} → {floor_s:.0%}×35%\n'
            f'└─ {grade} → {score:.1f}/{max_s}'
        )
        suggestion = ('髓腔形态良好。' if raw >= 0.7 else
                      '侧壁未拉直，存在牙本质领' if flare < 1.0 else '⚠️ 髓室底可能磨损')
        status = 'good' if raw >= 0.7 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('髓腔形态和髓室底完整', score, max_s, raw, 1.0, '得分', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════
    # 4. 定位根管口 — 插K锉检测 (25分)
    # ═══════════════════════════════
    def score_orifice_location(self, image, contours):
        max_s = 25
        if not contours: return self._make('定位根管口(插K锉)', 0, max_s, 0, 4, '个', '未检测到开髓洞形', 'bad')

        cavity = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.drawContours(mask, [cavity], -1, 255, -1)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 方法1: 检测K锉(明亮细线) — 最可靠
        kfile_count, kfiles = self.detect_kfiles(image, mask)

        # 方法2: 检测洞底最暗斑点(根管口) — 辅助
        c_vals = gray[mask > 0]
        if len(c_vals) < 50: return self._make('定位根管口(插K锉)', 5, max_s, 0, 4, '个', '像素不足', 'warning')

        dark_threshold = np.percentile(c_vals, 10)
        dark_mask = np.zeros_like(gray); dark_mask[mask > 0] = (gray[mask > 0] < dark_threshold).astype(np.uint8)*255
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dark_mask, connectivity=8)
        dark_orifices = sum(1 for i in range(1, n_labels) if stats[i, cv2.CC_STAT_AREA] > 5)

        # 综合判定: K锉检测优先
        if kfile_count >= 3:
            orifice_count = kfile_count; orifice_note = f'K锉检测到{kfile_count}个根管口,暴露清楚 ✓'; use_kfile = True
        elif kfile_count >= 2:
            orifice_count = max(kfile_count, dark_orifices); orifice_note = f'K锉{kfile_count}+暗区{dark_orifices}'; use_kfile = True
        elif kfile_count >= 1:
            orifice_count = max(1, dark_orifices); orifice_note = f'仅检测到{kfile_count}根K锉,可能有遗漏'; use_kfile = True
        else:
            # 无K锉 — 提示需要插入K锉照片
            orifice_count = dark_orifices; orifice_note = f'未检测到K锉，仅基于暗区估计({dark_orifices}个)'; use_kfile = False

        # 四档评分
        if orifice_count >= 3:
            score, note = 25.0, '所有根管口暴露清楚，K锉可直线探入(满分)'
            status = 'good'
        elif orifice_count >= 2:
            score, note = 16.0, '根管口暴露尚清楚(中等)'
            status = 'warning'
        elif orifice_count >= 1:
            score, note = 8.0, '遗漏根管口(扣分)'
            status = 'bad'
        else:
            score, note = 0, '根管口均未暴露(0分)'
            status = 'bad'

        process = (
            f'【定位根管口(插K锉) — 25分】\n'
            f'├─ K锉检测: {"✅" if use_kfile else "❌ 未检测到"} 明亮细线={kfile_count}根\n'
            f'├─ 暗区辅助: {dark_orifices}个疑似根管口\n'
            f'├─ 综合根管口数: {orifice_count}个\n'
            f'│   满分: ≥3个,暴露清楚 → 25分\n'
            f'│   中等: 2个 → 16分\n│   扣分: 1个 → 8分\n│   0分: 0个\n'
            f'├─ {orifice_note}\n└─ {note} → {score}/{max_s}'
            + ('\n⚠️ 请上传插入K锉后的照片以获得更准确的根管口评估。' if not use_kfile else '')
        )

        suggestion = ('根管口暴露充分。' if orifice_count >= 3 else
                      '根管口暴露不全或K锉未插入。请确认髓室顶完全揭除，所有根管口均插入K锉后拍照。磨牙需确认MB/MB2/DB/P等全部根管口。')

        return self._make('定位根管口(插K锉)', score, max_s, orifice_count, 4, '个', f'{orifice_count}个', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════
    # 主入口
    # ═══════════════════════════════
    def analyze(self, image_path):
        image = cv2.imread(image_path)
        report = ScoringReport()
        if image is None:
            report.overall_assessment = '无法读取图像'; return report

        h, w = image.shape[:2]
        if max(h, w) > 600: scale = 600 / max(h, w); image = cv2.resize(image, (int(w*scale), int(h*scale)))

        self.calibration_scale = self.detect_scale(image)
        binary, contours = self.extract_region(image)

        # 穿孔检测
        self.check_perforation(image, contours)

        if self.is_perforated:
            report.dimensions = [
                self._make('⚠️ 穿孔-项目0分', 0, 100, 0, 0, '', '髓室侧壁或髓室底穿孔!', 'bad',
                           process='【穿孔检测】侧壁/底穿指标异常。\n评分表规定:如有髓室侧壁或髓室底穿孔，则该考试项目"0"分。',
                           suggestion='⚠️ 穿孔!拍摄CBCT确认。侧穿行MTA修补;底穿预后较差需评估拔除。')
            ]
            report.total_score = 0; report.is_perforated = True
            report.overall_assessment = '穿孔！按照评分表规定，该项目为0分。'
            return report

        # AI评估4个维度
        dims = [
            self.score_opening_position_shape(image, contours),
            self.score_roof_removal(image, contours),
            self.score_chamber_morphology(image, contours),
            self.score_orifice_location(image, contours),
        ]

        report.dimensions = dims
        report.total_score = round(sum(d.score for d in dims), 1)
        report.kfile_detected = self.kfile_detected

        if report.total_score >= 90: report.overall_assessment = '优秀。开髓洞形制备规范，根管口暴露清晰。'
        elif report.total_score >= 75: report.overall_assessment = '良好。主要维度达标，部分细节可优化。'
        elif report.total_score >= 60: report.overall_assessment = '中等。基本合格，多项指标有提升空间。'
        elif report.total_score >= 40: report.overall_assessment = '及格。达到基本要求，需重点改进。'
        else: report.overall_assessment = '不及格。开髓结果存在明显问题，建议重新练习。'

        good = [d for d in dims if d.status == 'good']
        bad = [d for d in dims if d.status == 'bad']
        report.strengths = [f'{d.name}:{d.score:.0f}/{d.max_score}' for d in good]
        report.weaknesses = [f'{d.name}:{d.score:.0f}/{d.max_score}' for d in (bad + [d for d in dims if d.status == 'warning'])]

        return report


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        e = 开髓术评分引擎(); r = e.analyze(sys.argv[1])
        print(f'总分:{r.total_score}/100 穿孔:{r.is_perforated} K锉:{r.kfile_detected}')
        for d in r.dimensions: print(f'  {d.name}: {d.score}/{d.max_score} [{d.status}]')
