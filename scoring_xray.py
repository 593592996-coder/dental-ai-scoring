#!/usr/bin/env python3
"""
根管充填X光片AI评估引擎
评估维度：充填长度、致密度、锥度、三维封闭、超填/欠填、根尖封闭、影像均匀性
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


@dataclass
class ScoringReport:
    total_score: float = 0; max_total: float = 100
    dimensions: List[CavityMeasurement] = field(default_factory=list)
    problem_areas: List[dict] = field(default_factory=list)
    overall_assessment: str = ''
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)


SCORING_CONFIG = {
    'filling_length':    {'max': 25, 'desc': '根充长度(恰填)'},
    'filling_density':   {'max': 20, 'desc': '根充致密度'},
    'filling_taper':     {'max': 15, 'desc': '根充锥度连续性'},
    'void_detection':    {'max': 15, 'desc': '无空隙/三维封闭'},
    'apical_seal':       {'max': 15, 'desc': '根尖封闭质量'},
    'over_under_fill':   {'max': 5,  'desc': '超填/欠填判定'},
    'radiographic_uniform': {'max': 5, 'desc': '影像均匀性'},
}


class 根管X光片评估引擎:
    def __init__(self):
        self.known_apex_distance_mm = 2.0  # 理想充填止点距根尖距离

    def _make(self, name, score, max_s, raw, ideal, unit, detail, status, process='', suggestion=''):
        return CavityMeasurement(name=name, score=round(min(max_s, max(0, score)), 1),
                                 max_score=max_s, raw_value=round(raw, 3),
                                 ideal_value=ideal, unit=unit, detail=detail, status=status,
                                 process_analysis=process, targeted_suggestion=suggestion)

    # ═══════════════════════════════════════
    # 1. 根充长度/恰填评估 (25分) ★最重要
    # ═══════════════════════════════════════
    def score_filling_length(self, image):
        """评估根管充填材料末端距影像学根尖的距离"""
        max_s = 25
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        # 预处理
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 检测根管充填材料(高密度=亮) vs 背景
        _, bright_mask = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 在亮区中检测最下端(根尖方向)
        y_coords, x_coords = np.where(bright_mask > 0)
        if len(y_coords) < 100:
            return self._make('根充长度', 10, max_s, 0, 2.0, 'mm', 'X光片质量不足或充填材料不清晰', 'warning',
                              process='❌ 图像中未检测到清晰的根管充填材料。请确保X光片曝光合适、对比度足够。',
                              suggestion='重新拍摄X光片，调整曝光参数。根管充填材料应为明显高密度影。')

        # 获取充填材料的最下端和牙根轮廓
        y_max = y_coords.max()  # 充填材料最下端(根尖方向)

        # 检测牙根轮廓
        edges = cv2.Canny(enhanced, 50, 150)
        # 牙根尖通常在最下端
        root_contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        apex_y = y_max  # 默认
        apex_detected = False
        if root_contours:
            # 找最下方的轮廓点(根尖)
            all_points = np.vstack([c.reshape(-1, 2) for c in root_contours if cv2.contourArea(c) > 50])
            if len(all_points) > 0:
                apex_idx = np.argmax(all_points[:, 1])  # y最大=最下方
                apex_y = all_points[apex_idx, 1]
                apex_detected = True

        # 计算充填止点与根尖的像素距离
        fill_to_apex_px = apex_y - y_max  # 正值=欠填(未到根尖), 负值=超填(超出根尖)

        # 像素→mm估算 (成人磨牙长约20mm, 在X光片上约400-600px)
        # 粗糙估计: 1mm ≈ 25px
        px_per_mm = 25
        fill_to_apex_mm = fill_to_apex_px / px_per_mm

        # 评分: 理想=0.5-2mm短于根尖(恰填)
        if 0.5 <= fill_to_apex_mm <= 2.0:
            length_score, length_note = 1.0, f'根充止点距根尖{fill_to_apex_mm:.1f}mm，恰填 ✓'
            status = 'good'
        elif 0 <= fill_to_apex_mm < 0.5:
            length_score, length_note = 0.85, f'根充接近根尖({fill_to_apex_mm:.1f}mm)，接近恰填'
            status = 'good'
        elif 2.0 < fill_to_apex_mm <= 3.5:
            length_score, length_note = 0.7, f'轻微欠填({fill_to_apex_mm:.1f}mm)'
            status = 'warning'
        elif fill_to_apex_mm > 3.5:
            length_score, length_note = 0.35, f'明显欠填({fill_to_apex_mm:.1f}mm)'
            status = 'bad'
        elif -0.5 <= fill_to_apex_mm < 0:
            length_score, length_note = 0.7, f'轻微超填({abs(fill_to_apex_mm):.1f}mm)'
            status = 'warning'
        else:
            length_score, length_note = 0.3, f'明显超填({abs(fill_to_apex_mm):.1f}mm)'
            status = 'bad'

        score = max_s * length_score

        process = (
            f'【根充长度打分过程】\n'
            f'├─ 充填材料最下端: y={y_max}, 根尖位置: y={apex_y} ({"自动检测" if apex_detected else "估计"})\n'
            f'├─ 充填止点距根尖: {fill_to_apex_mm:.1f}mm (换算: {fill_to_apex_px}px / {px_per_mm}px/mm)\n'
            f'├─ 理想距离: 0.5-2mm短于根尖(恰填)\n'
            f'├─ {length_note} → {length_score:.0%}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        if fill_to_apex_mm > 3:
            suggestion = f'欠填{fill_to_apex_mm:.1f}mm。建议：重新测量工作长度，确认根管通畅后再行充填。X线片确认主尖距根尖0.5-2mm。'
        elif fill_to_apex_mm < -1:
            suggestion = f'超填{abs(fill_to_apex_mm):.1f}mm。建议：控制主尖就位深度，避免超出根尖孔。超填可能引起术后疼痛和根尖周炎症。'
        else:
            suggestion = '根充长度控制良好。保持工作长度测量规范。'

        return self._make('根充长度', score, max_s, fill_to_apex_mm, 1.5, 'mm',
                          f'{fill_to_apex_mm:+.1f}mm', status, process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 2. 根充致密度 (20分)
    # ═══════════════════════════════════════
    def score_filling_density(self, image):
        """评估充填材料在根管内的致密程度"""
        max_s = 20
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 提取亮区(充填材料)
        bright_threshold = np.percentile(enhanced, 70)
        filling_mask = (enhanced > bright_threshold).astype(np.uint8) * 255

        if np.sum(filling_mask) < 500:
            return self._make('根充致密度', 8, max_s, 0, 1, '密度', '充填材料区域不足', 'warning',
                              process='❌ 根管充填材料密度过低或曝光不足，无法评估。')

        # 充填区域内像素值分布
        filling_vals = enhanced[filling_mask > 0]

        # ① 平均密度(亮度越高=越致密)
        mean_density = float(np.mean(filling_vals))
        # ② 密度均匀性(标准差越小=填充越均匀)
        std_density = float(np.std(filling_vals))
        # ③ 低密度区域(可能存在空隙): 低于中位数-1.5σ
        median_val = np.median(filling_vals)
        low_density = float(np.sum(filling_vals < (median_val - 1.5 * std_density)) / len(filling_vals))

        # 密度评分
        if mean_density > 160: dens_score, dens_note = 1.0, '充填材料高密度,致密 ✓'
        elif mean_density > 130: dens_score, dens_note = 0.8, '密度良好'
        elif mean_density > 100: dens_score, dens_note = 0.5, '密度偏低'
        else: dens_score, dens_note = 0.25, '密度严重不足'

        # 均匀性评分
        if std_density < 25: unif_score, unif_note = 1.0, '密度分布均匀 ✓'
        elif std_density < 40: unif_score, unif_note = 0.7, '略有密度不均'
        else: unif_score, unif_note = 0.4, '密度不均匀'

        # 低密度区评分(空隙风险)
        if low_density < 0.05: void_score, void_note = 1.0, '无明显低密度区 ✓'
        elif low_density < 0.15: void_score, void_note = 0.7, f'低密度区{low_density:.1%}'
        else: void_score, void_note = 0.35, f'明显低密度区{low_density:.1%},可能存在空隙'

        raw = dens_score * 0.30 + unif_score * 0.35 + void_score * 0.35
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【根充致密度打分过程】\n'
            f'├─ 充填区域像素数: {np.sum(filling_mask)}px\n'
            f'├─ ① 平均密度={mean_density:.0f}(>160优) → {dens_note} → {dens_score:.0%}×30%\n'
            f'├─ ② 密度标准差={std_density:.1f}(<25优) → {unif_note} → {unif_score:.0%}×35%\n'
            f'├─ ③ 低密度区占比={low_density:.1%}(<5%优) → {void_note} → {void_score:.0%}×35%\n'
            f'└─ 综合={raw:.0%},得分={score:.1f}/{max_s}'
        )

        if low_density > 0.12:
            suggestion = f'存在{low_density:.0%}低密度区域，疑似空隙。建议：①侧压或热牙胶垂直加压需更充分；②拍摄多角度X线片确认；③如有明显空隙需重新充填。'
        elif std_density > 35:
            suggestion = '充填密度不均匀。建议：加强侧方加压或热牙胶垂直加压的力度和次数。'
        else:
            suggestion = '充填致密，密度均匀。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.5 else 'bad')
        return self._make('根充致密度', score, max_s, raw, 1.0, '得分率', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 3. 根充锥度连续性 (15分)
    # ═══════════════════════════════════════
    def score_filling_taper(self, image):
        """评估充填材料从冠方到根尖的锥度是否连续递减"""
        max_s = 15
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        _, bright = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 沿Y轴(根尖方向)扫描充填材料宽度
        y_coords, x_coords = np.where(bright > 0)
        if len(y_coords) < 100:
            return self._make('充填锥度', 6, max_s, 0, 1, '连续性', '材料区域不足', 'warning')

        y_min, y_max = y_coords.min(), y_coords.max()
        y_range = y_max - y_min

        widths = []
        segments = 10
        for i in range(segments):
            y_start = y_min + int(i * y_range / segments)
            y_end = y_min + int((i + 1) * y_range / segments)
            row_x = x_coords[(y_coords >= y_start) & (y_coords < y_end)]
            if len(row_x) >= 2:
                widths.append(row_x.max() - row_x.min())

        if len(widths) < 5:
            return self._make('充填锥度', 8, max_s, 0, 1, '连续性', '宽度数据不足', 'warning')

        # 锥度评估: 冠方宽度应大于根方(递减)
        top_widths = np.mean(widths[:3])  # 冠方
        bot_widths = np.mean(widths[-3:])  # 根方

        if top_widths > bot_widths:
            taper_ratio = bot_widths / top_widths
            if 0.3 < taper_ratio < 0.8:
                taper_score, taper_note = 1.0, f'锥度连续递减(根/冠={taper_ratio:.2f}) ✓'
            elif 0.15 < taper_ratio < 0.95:
                taper_score, taper_note = 0.7, f'锥度基本连续'
            else:
                taper_score, taper_note = 0.4, f'锥度异常'
        else:
            taper_ratio = top_widths / bot_widths if bot_widths > 0 else 1
            taper_score, taper_note = 0.3, '充填材料宽度未递减,锥度消失'

        # 宽度变化连续性
        if len(widths) >= 2:
            diffs = np.diff(widths)
            abrupt = float(np.sum(np.abs(diffs) > np.mean(np.abs(diffs)) * 3) / len(diffs))
            cont_score = max(0, 1 - abrupt * 3)
        else:
            cont_score = 0.7

        raw = taper_score * 0.6 + cont_score * 0.4
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【充填锥度打分过程】\n'
            f'├─ 沿Y轴分{segments}段扫描,获取{len(widths)}段宽度\n'
            f'├─ 冠方均宽={top_widths:.0f}px, 根方均宽={bot_widths:.0f}px\n'
            f'├─ 锥度比={taper_ratio:.2f}(理想0.3-0.8) → {taper_note} → {taper_score:.0%}×60%\n'
            f'├─ 宽度变化连续性={1-abrupt:.0%} → {cont_score:.0%}×40%\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        suggestion = '充填锥度良好。' if raw >= 0.7 else '锥度不理想。建议：使用大锥度牙胶尖，确保根管预备和充填均有连续锥度。'
        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.5 else 'bad')
        return self._make('充填锥度', score, max_s, raw, 1.0, '得分率', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 4. 空隙检测/三维封闭 (15分)
    # ═══════════════════════════════════════
    def score_void_detection(self, image):
        """检测充填材料内部的空隙(暗区)"""
        max_s = 15
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 充填区域
        bright_threshold = np.percentile(enhanced, 65)
        filling = (enhanced > bright_threshold)

        if np.sum(filling) < 300:
            return self._make('空隙检测', 8, max_s, 0, 1, '空隙率', '区域不足', 'warning')

        # 在充填区域内检测暗区(空隙)
        filling_only = enhanced.copy()
        filling_only[~filling] = 0

        # 低于充填区域均值-1.8σ = 疑似空隙
        f_vals = filling_only[filling_only > 0]
        f_mean, f_std = float(np.mean(f_vals)), float(np.std(f_vals))
        void_threshold = f_mean - 1.8 * f_std
        void_mask = np.zeros_like(enhanced)
        void_mask[filling] = (enhanced[filling] < void_threshold)

        # 统计空隙
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            void_mask.astype(np.uint8) * 255, connectivity=8
        )
        # 有效空隙(面积>5px)
        voids = [(i, stats[i, cv2.CC_STAT_AREA]) for i in range(1, n_labels)
                 if stats[i, cv2.CC_STAT_AREA] > 5]

        void_count = len(voids)
        total_void_area = sum(a for _, a in voids)
        void_ratio = total_void_area / np.sum(filling) if np.sum(filling) > 0 else 0

        if void_ratio < 0.02:
            void_score, void_note = 1.0, f'无明显空隙,三维封闭良好 ✓'
        elif void_ratio < 0.08:
            void_score, void_note = 0.65, f'检测到{void_count}个可疑空隙({void_ratio:.1%})'
        else:
            void_score, void_note = 0.3, f'大量空隙({void_count}个,{void_ratio:.1%}),封闭不足!'

        raw = void_score
        score = max_s * raw

        process = (
            f'【空隙检测打分过程】\n'
            f'├─ 充填区域均值={f_mean:.0f},标准差={f_std:.1f}\n'
            f'├─ 空隙阈值=均值-1.8σ={void_threshold:.0f}\n'
            f'├─ 检测到{void_count}个空隙,总面积{total_void_area}px({void_ratio:.1%})\n'
            f'├─ {void_note} → {void_score:.0%}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        if void_ratio > 0.06:
            suggestion = f'检测到{void_count}个空隙({void_ratio:.1%})。建议：①侧方加压或热牙胶垂直加压需更充分；②大空隙需重新充填；③多角度X线片确认。'
        else:
            suggestion = '三维封闭良好，未见明显空隙。'
        status = 'good' if void_ratio < 0.03 else ('warning' if void_ratio < 0.08 else 'bad')
        return self._make('空隙检测', score, max_s, void_ratio, 0, '空隙率', f'{void_ratio:.1%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 5. 根尖封闭质量 (15分)
    # ═══════════════════════════════════════
    def score_apical_seal(self, image):
        """评估根尖1/3区域的充填质量"""
        max_s = 15
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        _, bright = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        y_coords = np.where(bright > 0)[0]
        if len(y_coords) < 100:
            return self._make('根尖封闭', 6, max_s, 0, 1, '质量', '数据不足', 'warning')

        y_max = y_coords.max()

        # 根尖1/3区域(Y轴最下端1/3)
        y_min_bright = y_coords.min()
        apical_third_start = y_max - int((y_max - y_min_bright) / 3)
        apical_region = enhanced[apical_third_start:y_max, :]
        apical_bright = bright[apical_third_start:y_max, :]

        apical_vals = apical_region[apical_bright > 0]
        if len(apical_vals) < 30:
            return self._make('根尖封闭', 8, max_s, 0, 1, '质量', '根尖区数据不足', 'warning')

        # 根尖区密度
        apical_mean = float(np.mean(apical_vals))
        apical_std = float(np.std(apical_vals))
        # 整体密度
        all_vals = enhanced[bright > 0]
        overall_mean = float(np.mean(all_vals))

        # 根尖区不应明显低于整体(说明根尖封闭良好)
        density_ratio = apical_mean / overall_mean if overall_mean > 0 else 1

        if density_ratio > 0.9:
            dens_s, dens_n = 1.0, '根尖区密度与整体一致,封闭良好 ✓'
        elif density_ratio > 0.75:
            dens_s, dens_n = 0.7, '根尖区密度略低'
        else:
            dens_s, dens_n = 0.35, '根尖区密度明显不足,封闭不良!'

        # 根尖区空隙检测
        apical_void_ratio = float(np.sum(apical_vals < (apical_mean - 1.5 * apical_std)) / len(apical_vals))
        if apical_void_ratio < 0.03: void_s, void_n = 1.0, '根尖区无空隙 ✓'
        elif apical_void_ratio < 0.1: void_s, void_n = 0.6, f'根尖区少量空隙({apical_void_ratio:.1%})'
        else: void_s, void_n = 0.25, f'根尖区明显空隙({apical_void_ratio:.1%})'

        raw = dens_s * 0.5 + void_s * 0.5
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【根尖封闭打分过程】\n'
            f'├─ 根尖区密度/整体密度={density_ratio:.2f}(>0.9优) → {dens_s:.0%}×50%\n'
            f'│   {dens_n}\n'
            f'├─ 根尖区空隙率={apical_void_ratio:.1%}(<3%优) → {void_s:.0%}×50%\n'
            f'│   {void_n}\n'
            f'└─ 得分: {score:.1f}/{max_s}'
        )

        if raw < 0.5:
            suggestion = '根尖封闭不良！建议：①确认工作长度准确；②使用大锥度牙胶尖+AH Plus等封闭剂；③热牙胶垂直加压确保根尖区致密封闭。'
        else:
            suggestion = '根尖封闭良好。'
        status = 'good' if raw >= 0.7 else ('warning' if raw >= 0.45 else 'bad')
        return self._make('根尖封闭', score, max_s, raw, 1.0, '得分率', f'{raw:.0%}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 6. 超填/欠填判定 (5分)
    # ═══════════════════════════════════════
    def score_over_under(self, image):
        """综合判定是否为明显的超填或欠填"""
        max_s = 5
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        _, bright = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        y_coords = np.where(bright > 0)[0]
        if len(y_coords) < 50:
            return self._make('超/欠填', 3, max_s, 0, 0, '判定', '数据不足', 'warning')

        # 检测充填材料最下端超出根尖轮廓的情况
        edges = cv2.Canny(enhanced, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 简单判定: 检测充填材料是否过度延伸
        y_min, y_max = y_coords.min(), y_coords.max()
        filling_span = y_max - y_min

        # 充填材料长度相对牙根比例异常检测
        all_points = np.vstack([c.reshape(-1, 2) for c in contours if cv2.contourArea(c) > 30]) if contours else np.array([[0, 0]])
        if len(all_points) > 0:
            root_ymax = all_points[:, 1].max()
            over_extension = y_max - root_ymax  # 正值=超出根尖(超填)
        else:
            over_extension = 0

        if abs(over_extension) < 15:  # < 0.6mm估计
            status = 'good'; score = max_s
            detail = '充填长度在正常范围 ✓'
        elif over_extension > 30:
            status = 'bad'; score = 1; detail = f'疑似明显超填'
        elif over_extension < -40:
            status = 'bad'; score = 1; detail = f'疑似明显欠填'
        else:
            status = 'warning'; score = 3; detail = '充填长度略有偏差'

        process = (
            f'【超/欠填判定】\n'
            f'├─ 充填材料纵向跨度: {filling_span}px\n'
            f'├─ 超出根尖量: {over_extension}px\n'
            f'└─ {detail} → {score}/{max_s}'
        )

        suggestion = '充填长度可接受。' if score >= 3 else '建议重拍X线片并测量确认，必要时重新充填。'
        return self._make('超/欠填', score, max_s, over_extension, 0, 'px', detail, status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 7. 影像均匀性 (5分)
    # ═══════════════════════════════════════
    def score_uniformity(self, image):
        """评估X光片本身的影像均匀性(排除技术因素)"""
        max_s = 5
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        h, w = gray.shape
        # 分区域检测亮度均匀性
        regions = [
            gray[0:h//3, :],
            gray[h//3:2*h//3, :],
            gray[2*h//3:, :],
        ]

        means = [float(np.mean(r)) for r in regions]
        mean_diff = max(means) - min(means)

        if mean_diff < 30:
            score = max_s; detail = '影像均匀 ✓'; status = 'good'
        elif mean_diff < 60:
            score = 3.5; detail = '影像略有阴影差异'; status = 'warning'
        else:
            score = 2; detail = '影像不均匀,可能影响评估精度'; status = 'warning'

        process = (
            f'【影像均匀性】\n'
            f'├─ 三段亮度: 上={means[0]:.0f},中={means[1]:.0f},下={means[2]:.0f}\n'
            f'├─ 段间差异={mean_diff:.0f}(<30优)\n'
            f'└─ {detail} → {score}/{max_s}'
        )

        suggestion = '影像均匀。' if mean_diff < 40 else 'X光片曝光或冲洗不均匀。建议重新拍摄，确保胶片/传感器位置正确。'
        return self._make('影像均匀', score, max_s, mean_diff, 20, '差异', f'{mean_diff:.0f}', status,
                          process=process, suggestion=suggestion)

    # ═══════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════
    def analyze(self, image_path):
        image = cv2.imread(image_path)
        report = ScoringReport()
        if image is None:
            report.problem_areas = [{'msg': '无法读取X光片图像'}]
            return report

        # X光片通常不需要太大分辨率
        h, w = image.shape[:2]
        if max(h, w) > 800:
            scale = 800 / max(h, w)
            image = cv2.resize(image, (int(w*scale), int(h*scale)))

        dims = [
            self.score_filling_length(image),
            self.score_filling_density(image),
            self.score_filling_taper(image),
            self.score_void_detection(image),
            self.score_apical_seal(image),
            self.score_over_under(image),
            self.score_uniformity(image),
        ]

        report.dimensions = [d for d in dims if d is not None]
        report.total_score = round(sum(d.score for d in report.dimensions), 1)

        good = [d for d in report.dimensions if d.status == 'good']
        bad = [d for d in report.dimensions if d.status == 'bad']

        if report.total_score >= 90: report.overall_assessment = '优秀。根管充填质量优良,符合临床标准。'
        elif report.total_score >= 80: report.overall_assessment = '良好。根管充填质量良好。'
        elif report.total_score >= 70: report.overall_assessment = '中等。部分指标可优化。'
        elif report.total_score >= 60: report.overall_assessment = '及格。基本达到临床可接受标准。'
        else: report.overall_assessment = '不及格。需重新充填或进一步处理。'

        for d in report.dimensions:
            if d.status in ('bad', 'warning'):
                report.problem_areas.append({'dimension': d.name, 'detail': d.detail,
                                             'severity': d.status, 'suggestion': d.targeted_suggestion})

        return report


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        e = 根管X光片评估引擎()
        r = e.analyze(sys.argv[1])
        print(f'总分: {r.total_score:.1f}/100 | {r.overall_assessment}')
        for d in r.dimensions:
            print(f'  {d.name}: {d.score:.1f}/{d.max_score} [{d.status}]')
