#!/usr/bin/env python3
"""
II类洞AI评分引擎 v2 — 增强版
新增：逐维度打分过程分析 + 针对性改进建议
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import math


@dataclass
class CavityMeasurement:
    """单个维度的测量结果（增强版）"""
    name: str
    score: float
    max_score: float
    raw_value: float
    ideal_value: float
    unit: str
    detail: str
    status: str  # 'good','warning','bad'
    # 新增字段
    process_analysis: str = ''       # 打分过程拆解
    targeted_suggestion: str = ''    # 针对性改进建议
    sub_scores: List[dict] = field(default_factory=list)  # 子维度得分明细


@dataclass
class ScoringReport:
    total_score: float = 0
    max_total: float = 100
    dimensions: List[CavityMeasurement] = field(default_factory=list)
    problem_areas: List[dict] = field(default_factory=list)
    annotated_image_path: Optional[str] = None
    # 新增
    overall_assessment: str = ''     # 整体评估
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)


SCORING_CONFIG = {
    'outline_form': {'max': 20, 'ideal': 1.0, 'unit': '相似度', 'desc': '洞形设计·外形轮廓'},
    'isthmus_ratio': {'max': 15, 'ideal': 0.33, 'unit': '比值', 'desc': '鸠尾峡·宽度比例'},
    'cavity_depth': {'max': 10, 'ideal': 0.5, 'unit': 'mm', 'desc': '洞深·深度达标率'},
    'floor_flatness': {'max': 8, 'ideal': 0.0, 'unit': '残差', 'desc': '底平·髓壁平面度'},
    'wall_verticality': {'max': 7, 'ideal': 90.0, 'unit': '度', 'desc': '壁直·侧壁垂直度'},
    'line_angle_sharpness': {'max': 10, 'ideal': 1.0, 'unit': '锐度', 'desc': '点线角·锐度清晰'},
    'proximal_box': {'max': 10, 'ideal': 1.0, 'unit': '完整度', 'desc': '邻面洞形·盒形完整'},
    'margin_smoothness': {'max': 5, 'ideal': 0.0, 'unit': '粗糙度', 'desc': '洞缘光滑·无悬釉'},
    'adjacent_protection': {'max': 10, 'ideal': 0.0, 'unit': '损伤', 'desc': '邻牙保护·无损伤'},
    'operation_process': {'max': 5, 'ideal': 900, 'unit': '秒', 'desc': '操作过程·时长效率'},
}


class II类洞评分引擎V2:
    """II类洞制备AI评分引擎 v2.0"""

    def __init__(self):
        self.calibration_scale = None
        self.reference_marker_mm = 5.0

    # ═══════════════════════════════════════════════
    # 基础工具
    # ═══════════════════════════════════════════════
    def detect_scale_marker(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=50,
                                   param1=50, param2=30, minRadius=10, maxRadius=80)
        if circles is not None and len(circles[0]) >= 2:
            circles = np.round(circles[0]).astype(int)
            if len(circles) > 2:
                circles = circles[circles[:, 0].argsort()]
                c1, c2 = circles[0], circles[-1]
            else:
                c1, c2 = circles[0], circles[1]
            pixel_dist = np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)
            if 30 < pixel_dist < 500:
                return self.reference_marker_mm / pixel_dist
        return None

    def estimate_scale_from_tooth(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            if 100 < w < 2000:
                return 11.0 / w
        return 0.05

    def extract_cavity_region(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return binary, contours

    def _make_result(self, name, score, max_s, raw, ideal, unit, detail, status,
                     process='', suggestion='', subs=None):
        return CavityMeasurement(
            name=name, score=round(min(max_s, max(0, score)), 1),
            max_score=max_s, raw_value=round(raw, 3),
            ideal_value=ideal, unit=unit, detail=detail, status=status,
            process_analysis=process, targeted_suggestion=suggestion,
            sub_scores=subs or []
        )

    # ═══════════════════════════════════════════════
    # 1. 外形轮廓评分 (20分)
    # ═══════════════════════════════════════════════
    def score_outline_form(self, image, binary, contours):
        max_s = 20
        if not contours:
            return self._make_result('外形轮廓', 0, max_s, 0, 1.0, '相似度',
                                     '未检测到制备区域', 'bad',
                                     process='❌ 图像中未检测到有效的制备区域轮廓。请确保拍摄光线充足、制备区域与周围牙体颜色有明显对比。')

        cavity_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cavity_contour)
        perimeter = cv2.arcLength(cavity_contour, True)

        # 子维度1: 圆形度 (II类洞为不规则多边形，非圆形)
        circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0
        if 0.25 < circularity < 0.65:
            cir_score, cir_note = 1.0, '形状为不规则多边形，符合II类洞特征 ✓'
            cir_status = 'good'
        elif 0.15 < circularity < 0.75:
            cir_score, cir_note = 0.7, '形状基本符合，但规则度偏高或偏低'
            cir_status = 'warning'
        else:
            cir_score, cir_note = 0.4, '形状过于规则或不规则，不符合典型II类洞轮廓'
            cir_status = 'bad'

        # 子维度2: 凸度 (鸠尾+邻面结构使轮廓凹陷多)
        hull = cv2.convexHull(cavity_contour)
        hull_area = cv2.contourArea(hull)
        convexity = area / hull_area if hull_area > 0 else 0
        if 0.6 < convexity < 0.9:
            cvx_score, cvx_note = 1.0, '轮廓凹度合理，鸠尾+邻面双区域结构清晰 ✓'
            cvx_status = 'good'
        elif 0.5 < convexity < 0.95:
            cvx_score, cvx_note = 0.7, '轮廓凹凸性基本合理'
            cvx_status = 'warning'
        else:
            cvx_score, cvx_note = 0.4, '轮廓凹凸性异常，可能缺少鸠尾或邻面结构'
            cvx_status = 'bad'

        # 子维度3: 面积合理性
        x, y, w, h = cv2.boundingRect(cavity_contour)
        aspect = w / h if h > 0 else 1
        if 0.5 < aspect < 2.0:
            asp_score, asp_note = 1.0, '长宽比合理 ✓'
            asp_status = 'good'
        else:
            asp_score, asp_note = 0.6, '长宽比失衡，注意鸠尾与邻面盒形的比例分配'
            asp_status = 'warning'

        # 综合
        raw = cir_score * 0.35 + cvx_score * 0.40 + asp_score * 0.25
        score = max_s * raw

        process = (
            f'【外形轮廓打分过程】\n'
            f'├─ 子维度① 圆形度 (权重35%): 实测值={circularity:.2f} (理想0.25-0.65)\n'
            f'│    → {cir_note} → 得分率{cir_score:.0%}\n'
            f'├─ 子维度② 凸度分析 (权重40%): 实测值={convexity:.2f} (理想0.6-0.9)\n'
            f'│    → {cvx_note} → 得分率{cvx_score:.0%}\n'
            f'├─ 子维度③ 长宽比 (权重25%): 实测值={aspect:.2f} (理想0.5-2.0)\n'
            f'│    → {asp_note} → 得分率{asp_score:.0%}\n'
            f'└─ 综合得分率 = {raw:.0%}, 得分 = {score:.1f}/{max_s}'
        )

        if cir_status == 'bad':
            suggestion = '轮廓形状异常。建议：在牙面用铅笔预先描画II类洞外形线（鸠尾+邻面盒形），确认形态后再开始制备。'
        elif cvx_status == 'bad':
            suggestion = '缺少鸠尾或邻面盒形结构。建议：II类洞必须包含颌面鸠尾固位形和邻面盒形两部分，制备前确认两者均被设计在内。'
        elif cir_status == 'warning' or cvx_status == 'warning':
            suggestion = '外形轮廓基本合格但可优化。建议：对照标准II类洞图谱检查鸠尾展开角度和邻面龈壁位置。'
        else:
            suggestion = '外形轮廓良好，继续保持。'

        status = 'good' if raw >= 0.8 else ('warning' if raw >= 0.6 else 'bad')
        return self._make_result('外形轮廓', score, max_s, raw, 1.0, '得分率', f'综合{raw:.0%}', status,
                                 process=process, suggestion=suggestion,
                                 subs=[{'name': '圆形度', 'score': cir_score, 'note': cir_note},
                                       {'name': '凸度分析', 'score': cvx_score, 'note': cvx_note},
                                       {'name': '长宽比', 'score': asp_score, 'note': asp_note}])

    # ═══════════════════════════════════════════════
    # 2. 鸠尾峡评分 (15分)
    # ═══════════════════════════════════════════════
    def score_isthmus_ratio(self, image, contours):
        max_s, ideal = 15, 0.33
        if not contours:
            return self._make_result('鸠尾峡比例', max_s//2, max_s, 0, ideal, '比值',
                                     '无法检测', 'warning',
                                     process='❌ 未检测到制备轮廓。')

        cavity_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity_contour)

        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        widths = []
        for row in range(y, min(y + h, mask.shape[0])):
            row_pixels = np.where(mask[row, :] > 0)[0]
            if len(row_pixels) >= 2:
                widths.append(row_pixels[-1] - row_pixels[0])

        if not widths or len(widths) < 5:
            return self._make_result('鸠尾峡比例', round(max_s*0.7, 1), max_s, 0, ideal, '比值',
                                     '轮廓数据不足', 'warning',
                                     process='⚠️ 轮廓扫描数据不足。请调整拍摄角度，确保颌面正位照片清晰覆盖鸠尾峡区域。')

        min_w = min(widths)
        max_w = max(widths)
        ratio = min_w / max_w if max_w > 0 else 0
        avg_w = np.mean(widths)

        # 评分
        ratio_score = math.exp(-50 * (ratio - ideal) ** 2)

        # 位置检查：峡部应该出现在中段（y方向30%-70%范围）
        min_idx = widths.index(min_w)
        position_ratio = min_idx / len(widths)
        if 0.25 < position_ratio < 0.75:
            pos_score, pos_note = 1.0, '峡部位于轮廓中段，位置合理 ✓'
        else:
            pos_score, pos_note = 0.7, '峡部位置偏上/偏下，建议调整到颌面中段'

        raw = ratio_score * 0.8 + pos_score * 0.2
        score = max_s * raw

        if self.calibration_scale:
            real_min = min_w * self.calibration_scale
            real_max = max_w * self.calibration_scale
            size_note = f'(换算: 峡宽≈{real_min:.1f}mm, 颊舌尖距≈{real_max:.1f}mm)'
        else:
            size_note = '(像素测量，未检测到标尺)'

        direction = '偏宽' if ratio > ideal else '偏窄' if ratio < ideal else '适中'

        process = (
            f'【鸠尾峡打分过程】\n'
            f'├─ 步骤1: 沿Y轴扫描轮廓，获取每行宽度（共{len(widths)}行）\n'
            f'├─ 步骤2: 定位最窄处(峡部)={min_w}px, 最宽处={max_w}px {size_note}\n'
            f'├─ 步骤3: 计算峡宽比 = {min_w}/{max_w} = {ratio:.3f}\n'
            f'│    → 理想比值={ideal}, 偏差={abs(ratio-ideal):.3f}\n'
            f'├─ 步骤4: 高斯评分 = exp(-50×{abs(ratio-ideal):.3f}²) = {ratio_score:.3f}\n'
            f'├─ 步骤5: 峡部位置检测({pos_note}) → 位置得分率={pos_score:.0%}\n'
            f'└─ 综合得分率 = {raw:.0%}, 得分 = {score:.1f}/{max_s}'
        )

        if abs(ratio - ideal) < 0.06:
            suggestion = '鸠尾峡比例优秀，接近理想值1/3。保持当前操作手感。'
        elif ratio > ideal:
            suggestion = (f'鸠尾峡偏宽(峡/宽={ratio:.2f}>理想{ideal})。'
                         f'建议：制备前在牙面标记峡部边界线(颊舌尖距的1/3处)，'
                         f'制备时钻针不要超出标记线。峡部过宽会削弱固位力。')
        else:
            suggestion = (f'鸠尾峡偏窄(峡/宽={ratio:.2f}<理想{ideal})。'
                         f'建议：适当扩展峡部宽度至颊舌尖距的1/3，'
                         f'峡部过窄可能导致充填体折断。')

        status = 'good' if raw >= 0.8 else ('warning' if raw >= 0.55 else 'bad')
        return self._make_result('鸠尾峡比例', score, max_s, ratio, ideal, '比值',
                                 f'{direction} {ratio:.2f}', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 3. 洞深评分 (10分) — LAB色差分析
    # ═══════════════════════════════════════════════
    def score_cavity_depth(self, image, contours, tooth_type='real'):
        max_s = 10
        if not contours:
            return self._make_result('洞深', 0, max_s, 0, 0.5, 'mm',
                                     '无法检测', 'bad',
                                     process='❌ 未检测到制备区域。')

        cavity_contour = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        # ── 树脂牙模式：基于灰度梯度的几何估算 ──
        if tooth_type == 'resin':
            return self._score_depth_resin(image, mask, contours, max_s)

        # ── 离体牙模式：LAB色差分析（原有逻辑）──
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        cavity_pixels = lab[mask > 0]

        if len(cavity_pixels) == 0:
            return self._make_result('洞深', round(max_s*0.5, 1), max_s, 0, 0.5, 'mm',
                                     '分割无效', 'warning')

        l_vals = cavity_pixels[:, 0]
        b_vals = cavity_pixels[:, 2]

        # 像素分类
        total = len(cavity_pixels)
        enamel = np.sum((l_vals > 80) & (b_vals > 5))
        dej = np.sum((l_vals >= 70) & (l_vals <= 85) & (b_vals >= 0) & (b_vals <= 8))
        dentin_shallow = np.sum((l_vals >= 55) & (l_vals <= 75) & (b_vals >= -5) & (b_vals <= 5))
        dentin_deep = np.sum((l_vals < 55) & (b_vals < -5))

        enamel_pct = enamel / total * 100
        dej_pct = dej / total * 100
        target_pct = dentin_shallow / total * 100  # 达标
        deep_pct = dentin_deep / total * 100       # 过深风险

        # 评分
        level_score = target_pct / 100 + dej_pct / 200  # 达标+半权重过渡区
        depth_penalty = min(0.3, deep_pct / 100 * 0.5)  # 过深扣分
        shallow_penalty = min(0.3, enamel_pct / 100 * 0.4)  # 过浅扣分
        raw = max(0, min(1, level_score - depth_penalty - shallow_penalty))
        score = max_s * raw

        l_mean, b_mean = np.mean(l_vals), np.mean(b_vals)

        process = (
            f'【洞深打分过程 — LAB色彩空间分析】\n'
            f'├─ 制备区域像素总数: {total}\n'
            f'├─ L通道均值={l_mean:.1f} (亮度), B通道均值={b_mean:.1f} (黄蓝轴)\n'
            f'├─ 像素分类结果:\n'
            f'│   ├─ 牙釉质(太浅): {enamel}({enamel_pct:.1f}%)  L>80, B>5\n'
            f'│   ├─ 釉牙本质界(过渡): {dej}({dej_pct:.1f}%)  L=70-85, B=0-8\n'
            f'│   ├─ 牙本质浅层(✓达标): {dentin_shallow}({target_pct:.1f}%)  L=55-75, B=-5~5\n'
            f'│   └─ 牙本质深层(⚠过深): {dentin_deep}({deep_pct:.1f}%)  L<55, B<-5\n'
            f'├─ 深度达标分 = {target_pct:.1f}% + 过渡区半计{dej_pct/2:.1f}% = {level_score:.1%}\n'
            f'├─ 过浅扣分 = {shallow_penalty:.1%}, 过深扣分 = {depth_penalty:.1%}\n'
            f'└─ 最终得分率 = {raw:.0%}, 得分 = {score:.1f}/{max_s}'
        )

        if deep_pct > 15:
            suggestion = (f'⚠️ {deep_pct:.0f}%区域洞深过大，存在穿髓风险！'
                         f'建议：①控制每次进针深度在半钻针直径内；②采用分层预备法；'
                         f'③使用带深度标记的钻针；④预备过程中多次用探针检查洞深。')
        elif enamel_pct > 40:
            suggestion = (f'{enamel_pct:.0f}%区域深度不足，仍在牙釉质层。'
                         f'建议：继续均匀加深至釉牙本质界下0.5mm，'
                         f'看到淡黄色牙本质即为到达目标深度。')
        elif target_pct >= 70:
            suggestion = '洞深控制良好，大部分区域到达目标深度。保持当前手感。'
        else:
            suggestion = '洞深不够均匀。建议采用分层预备，每层深度保持一致，预备后用探针检查洞底平整度。'

        status = 'good' if raw >= 0.8 else ('warning' if raw >= 0.5 else 'bad')
        return self._make_result('洞深', score, max_s, target_pct/100, 0.7, '达标率',
                                 f'达标{target_pct:.0f}%', status,
                                 process=process, suggestion=suggestion,
                                 subs=[{'name': '牙釉质(太浅)', 'score': enamel_pct, 'note': f'{enamel}像素'},
                                       {'name': '釉牙本质界', 'score': dej_pct, 'note': f'{dej}像素'},
                                       {'name': '牙本质浅层(✓)', 'score': target_pct, 'note': f'{dentin_shallow}像素'},
                                       {'name': '牙本质深层(⚠)', 'score': deep_pct, 'note': f'{dentin_deep}像素'}])

    # ═══════════════════════════════════════════════
    # 辅助: 树脂牙洞深估算法
    # ═══════════════════════════════════════════════
    def _score_depth_resin(self, image, mask, contours, max_s):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cavity_gray = gray[mask > 0]
        surrounding_mask = cv2.dilate(mask, np.ones((15, 15), np.uint8)) - mask
        surrounding_gray = gray[surrounding_mask > 0]
        if len(cavity_gray) == 0:
            return self._make_result('洞深', round(max_s*0.5, 1), max_s, 0, 0.5, 'mm', '分割无效', 'warning')
        cavity_mean = float(np.mean(cavity_gray))
        surface_mean = float(np.mean(surrounding_gray)) if len(surrounding_gray) > 0 else cavity_mean + 50
        contrast = surface_mean - cavity_mean
        cavity_std = float(np.std(cavity_gray))
        grad = cv2.Sobel(gray, cv2.CV_64F, 1, 1, ksize=5)
        grad_mag = float(np.mean(np.abs(grad[mask > 0])))
        if 20 < contrast < 100: contrast_score, contrast_note = 1.0, '灰度对比度适中，深度合理'
        elif 10 < contrast < 130: contrast_score, contrast_note = 0.7, f'对比度={contrast:.0f}'
        else: contrast_score, contrast_note = 0.4, f'对比度={contrast:.0f}异常'
        uniform_score = max(0.0, 1.0 - cavity_std / 40)
        if grad_mag > 15: grad_score, grad_note = 1.0, '梯度清晰'
        elif grad_mag > 8: grad_score, grad_note = 0.7, '梯度一般'
        else: grad_score, grad_note = 0.4, '梯度不足'
        raw = max(0.0, min(1.0, contrast_score * 0.35 + uniform_score * 0.35 + grad_score * 0.3))
        score = max_s * raw
        process = (
            f'【洞深打分过程 — 树脂牙·几何估算法】\n'
            f'├─ 树脂牙为单色材料，改用灰度几何估算替代LAB色差法\n'
            f'├─ ①灰度对比度(35%): 洞内={cavity_mean:.0f},表面={surface_mean:.0f},差={contrast:.0f} → {contrast_note} → {contrast_score:.0%}\n'
            f'├─ ②内部均匀性(35%): std={cavity_std:.1f} → {uniform_score:.0%}\n'
            f'├─ ③边缘梯度(30%): grad={grad_mag:.1f} → {grad_note} → {grad_score:.0%}\n'
            f'└─ 综合={raw:.0%},得分={score:.1f}/{max_s} (树脂牙估深精度有限，建议人工复核)'
        )
        suggestion = '树脂牙深度评估基于灰度估算。建议制备后使用牙周探针实际测量洞深(釉牙本质界下0.5mm)进行人工验证。'
        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.5 else 'bad')
        return self._make_result('洞深', score, max_s, contrast, 50, '灰度差', '树脂牙·估深', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 4. 髓壁平面度评分 (8分)
    # ═══════════════════════════════════════════════
    def score_floor_flatness(self, image, contours):
        max_s = 8
        if not contours:
            return self._make_result('髓壁平面度', 0, max_s, 0, 0, 'std',
                                     '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity_contour)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        # 分析3个区域: 近中、中央、远中
        center_y = y + h // 2
        third_h = h // 3

        regions = {
            '近中1/3': (max(0, center_y - h//6 - third_h), center_y - h//6),
            '中央1/3': (center_y - h//6, center_y + h//6),
            '远中1/3': (center_y + h//6, min(mask.shape[0], center_y + h//6 + third_h)),
        }

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region_stats = []
        overall_stds = []

        for name, (r_start, r_end) in regions.items():
            roi_mask = mask[r_start:r_end, :]
            roi_gray = gray[r_start:r_end, :]
            valid = roi_gray[roi_mask > 0]
            if len(valid) > 10:
                r_std = float(np.std(valid))
                r_mean = float(np.mean(valid))
                region_stats.append({'name': name, 'mean': r_mean, 'std': r_std})
                overall_stds.append(r_std)

        if not overall_stds:
            return self._make_result('髓壁平面度', round(max_s*0.6, 1), max_s, 0, 0, 'std',
                                     '有效像素不足', 'warning')

        # 指标1: 平均灰度标准差 (越小越平坦)
        avg_std = np.mean(overall_stds)
        std_score = max(0, 1 - (avg_std - 12) / 28)

        # 指标2: 区域间均值差异 (越小越均匀)
        if len(region_stats) >= 2:
            means = [r['mean'] for r in region_stats]
            mean_diff = max(means) - min(means)
            uniform_score = max(0, 1 - mean_diff / 40)
        else:
            uniform_score = 0.7

        raw = std_score * 0.55 + uniform_score * 0.45
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        region_detail = '\n'.join(
            f'│   {r["name"]}: 均值={r["mean"]:.1f}, 标准差={r["std"]:.1f}'
            for r in region_stats
        )

        process = (
            f'【髓壁平面度打分过程】\n'
            f'├─ 将制备区域划分为近中/中央/远中三段分别分析\n'
            f'{region_detail}\n'
            f'├─ 指标① 平均灰度标准差 = {avg_std:.1f} (越小越平, <12优, >40差)\n'
            f'│   → 标准差得分率 = {std_score:.0%}\n'
            f'├─ 指标② 区域间均匀性 = {mean_diff if len(region_stats)>=2 else "N/A":.1f} (区域间均值差异)\n'
            f'│   → 均匀性得分率 = {uniform_score:.0%}\n'
            f'└─ 综合得分率 = 标准差{std_score:.0%}×55% + 均匀性{uniform_score:.0%}×45% = {raw:.0%}'
        )

        if avg_std > 35:
            suggestion = ('髓壁明显不平整。建议：①使用平头裂钻进行髓壁修整；'
                         '②手机保持稳定转速(低速)，匀速移动；③预备后使用挖器平整洞底；'
                         '④用探针沿洞底滑行检查有无台阶感。')
        elif avg_std > 20:
            suggestion = ('髓壁略有起伏。建议：预备时注意保持手机与髓壁平行，'
                         '避免钻针在洞底"弹跳"，可采用分层平整法逐层加深。')
        else:
            suggestion = '髓壁平面度良好，保持操作习惯。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make_result('髓壁平面度', score, max_s, avg_std, 12, 'std',
                                 f'std={avg_std:.1f}', status,
                                 process=process, suggestion=suggestion,
                                 subs=region_stats)

    # ═══════════════════════════════════════════════
    # 5. 侧壁垂直度评分 (7分)
    # ═══════════════════════════════════════════════
    def score_wall_verticality(self, image, contours):
        max_s = 7
        if not contours:
            return self._make_result('侧壁垂直度', 0, max_s, 0, 90, '度', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        epsilon = 0.02 * cv2.arcLength(cavity_contour, True)
        approx = cv2.approxPolyDP(cavity_contour, epsilon, True)

        edges_info = []
        for i in range(len(approx)):
            p1 = approx[i][0]
            p2 = approx[(i + 1) % len(approx)][0]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = np.sqrt(dx**2 + dy**2)
            if length > 15:
                angle = abs(math.degrees(math.atan2(dy, abs(dx) + 0.01)))
                dev = min(abs(angle - 90), abs(angle - 270))
                edges_info.append({'angle': angle, 'deviation': dev, 'length': length})

        if not edges_info:
            return self._make_result('侧壁垂直度', round(max_s*0.6, 1), max_s, 0, 90, '度',
                                     '无法提取边特征', 'warning')

        # 统计
        vertical_edges = [e for e in edges_info if e['deviation'] < 25]
        near_vertical = [e for e in edges_info if e['deviation'] < 15]
        slanted = [e for e in edges_info if e['deviation'] >= 25]

        v_ratio = len(vertical_edges) / len(edges_info)
        avg_dev = np.mean([e['deviation'] for e in edges_info])

        # ① 垂直边占比
        ratio_score = v_ratio
        # ② 角度偏差
        dev_score = max(0, 1 - avg_dev / 40)
        raw = ratio_score * 0.55 + dev_score * 0.45
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        edge_detail = '\n'.join(
            f'│   边{i+1}: 角度={e["angle"]:.0f}°, 偏差={e["deviation"]:.0f}° {"✓" if e["deviation"]<15 else "⚠" if e["deviation"]<25 else "✗"}'
            for i, e in enumerate(edges_info[:8])
        )

        process = (
            f'【侧壁垂直度打分过程】\n'
            f'├─ 轮廓多边形逼近 → 提取{len(edges_info)}条有效边\n'
            f'{edge_detail}\n'
            f'├─ 垂直边(偏差<25°): {len(vertical_edges)}条, 占比={v_ratio:.0%}\n'
            f'├─ 近垂直边(偏差<15°): {len(near_vertical)}条\n'
            f'├─ 倾斜边(偏差≥25°): {len(slanted)}条\n'
            f'├─ 平均角度偏差 = {avg_dev:.1f}° (理想<10°)\n'
            f'├─ 垂直占比得分率 = {ratio_score:.0%} ×55%\n'
            f'├─ 偏差得分率 = {dev_score:.0%} ×45%\n'
            f'└─ 综合得分率 = {raw:.0%}, 得分 = {score:.1f}/{max_s}'
        )

        if len(slanted) >= 2:
            wall_names = [f'边{i+1}' for i, e in enumerate(edges_info) if e['deviation'] >= 25]
            suggestion = (f'侧壁倾斜明显({",".join(wall_names[:3])})。'
                         f'建议：①手机与牙体长轴保持平行；②制备时以髓壁为参考平面；'
                         f'③使用口镜从多个角度观察侧壁垂直度；④侧壁应向外展开2-5°而非向内倾斜。')
        elif avg_dev > 15:
            suggestion = '侧壁垂直度一般。建议：注意保持手机主轴与牙体长轴平行，避免手腕倾斜。'
        else:
            suggestion = '侧壁垂直度良好。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make_result('侧壁垂直度', score, max_s, avg_dev, 10, '度',
                                 f'平均偏差{avg_dev:.1f}°', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 6. 点线角锐度 (10分)
    # ═══════════════════════════════════════════════
    def score_line_angle_sharpness(self, image, contours):
        max_s = 10
        if not contours:
            return self._make_result('点线角锐度', 0, max_s, 0, 80, '梯度', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        gradient_mag = np.sqrt(sobel_x ** 2 + sobel_y ** 2)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        contour_border = cv2.dilate(mask, kernel) - cv2.erode(mask, kernel)
        border_gradients = gradient_mag[contour_border > 0]

        if len(border_gradients) < 10:
            return self._make_result('点线角锐度', round(max_s*0.6, 1), max_s, 0, 80, '梯度',
                                     '边缘像素不足', 'warning')

        avg_gradient = float(np.mean(border_gradients))
        grad_std = float(np.std(border_gradients))
        strong_edges = float(np.sum(border_gradients > 60) / len(border_gradients))

        # ① 平均梯度强度
        grad_score = min(1.0, max(0, avg_gradient / 80))
        # ② 强边缘占比 (梯度>60的比例)
        strong_score = min(1.0, strong_edges * 2)
        # ③ 梯度一致性（标准差适中为佳，太大了说明不均匀）
        consistency = max(0, 1 - grad_std / 50)

        raw = grad_score * 0.5 + strong_score * 0.3 + consistency * 0.2
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【点线角锐度打分过程 — Sobel边缘梯度分析】\n'
            f'├─ 沿轮廓边缘提取梯度值（共{len(border_gradients)}个采样点）\n'
            f'├─ ① 平均梯度强度 = {avg_gradient:.1f} (理想>80)\n'
            f'│   → 得分率 = {grad_score:.0%}×50%\n'
            f'├─ ② 强边缘占比(梯度>60) = {strong_edges:.1%}\n'
            f'│   → 得分率 = {strong_score:.0%}×30%\n'
            f'├─ ③ 梯度一致性(std={grad_std:.1f}) → 得分率 = {consistency:.0%}×20%\n'
            f'└─ 综合得分率 = {raw:.0%}, 得分 = {score:.1f}/{max_s}'
        )

        if avg_gradient < 40:
            suggestion = ('点线角圆钝，边缘不够锐利。建议：①使用新的锐利钻针；'
                         '②支点稳定、手腕不晃动；③点线角处使用倒锥钻或小号裂钻专门修整；'
                         '④避免在洞缘反复摩擦导致边缘圆钝。')
        elif avg_gradient < 65:
            suggestion = '点线角锐度基本合格但可提升。建议：换用新钻针，注意控制手机转速和支点稳定性。'
        else:
            suggestion = '点线角锐利清晰，保持。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.45 else 'bad')
        return self._make_result('点线角锐度', score, max_s, avg_gradient, 80, '梯度值',
                                 f'梯度{avg_gradient:.0f}', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 7. 邻面盒形 (10分) — 基于邻面侧位照片
    # ═══════════════════════════════════════════════
    def score_proximal_box(self, image, contours):
        max_s = 10
        if not contours:
            return self._make_result('邻面盒形', 0, max_s, 0, 1.0, '完整度',
                                     '请上传邻面侧位照片进行分析', 'warning',
                                     process='⚠️ 未检测到邻面结构。请从近中或远中方向拍摄邻面盒形照片。')

        cavity_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity_contour)

        # 分析邻面区域的轮廓特征
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        # 如果从侧位拍摄，轮廓应呈梯形(龈壁宽→颌方窄)或矩形
        aspect = w / h if h > 0 else 1

        # 子维度: 龈壁宽度合理性
        if 0.3 < aspect < 3.0:
            gw_score, gw_note = 1.0, '邻面形态比例合理 ✓'
        elif 0.2 < aspect < 4.0:
            gw_score, gw_note = 0.7, '邻面形态比例稍有偏差'
        else:
            gw_score, gw_note = 0.4, '邻面形态比例异常，请检查'

        # 轮廓完整性
        area = cv2.contourArea(cavity_contour)
        hull = cv2.convexHull(cavity_contour)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0

        if solidity > 0.8:
            sol_score, sol_note = 1.0, '邻面盒形轮廓完整 ✓'
        elif solidity > 0.6:
            sol_score, sol_note = 0.7, '邻面盒形轮廓略有缺损'
        else:
            sol_score, sol_note = 0.4, '邻面盒形轮廓不完整，可能龈壁或颊舌壁不足'

        raw = gw_score * 0.4 + sol_score * 0.6
        raw = max(0.0, min(1.0, raw))
        score = max_s * raw

        process = (
            f'【邻面盒形打分过程 — 侧位轮廓分析】\n'
            f'├─ 邻面区域轮廓: {w}×{h}px, 长宽比={aspect:.2f}\n'
            f'├─ ① 龈壁宽度合理性 → 得分率 = {gw_score:.0%}×40%\n'
            f'│   {gw_note}\n'
            f'├─ ② 轮廓完整性(solidity={solidity:.2f}) → 得分率 = {sol_score:.0%}×60%\n'
            f'│   {sol_note}\n'
            f'└─ 综合得分率 = {raw:.0%}, 得分 = {score:.1f}/{max_s}'
        )

        if raw < 0.6:
            suggestion = ('邻面盒形需要改进。建议：①龈壁宽度应达1.0-1.5mm；'
                         '②颊舌壁应扩展至自洁区；③盒形底部与龈缘平行；'
                         '④从邻面拍照检查盒形深度是否足够(应达釉牙本质界下0.5mm)。')
        else:
            suggestion = '邻面盒形结构良好。建议上传标准邻面侧位照片以获得更准确的分析。'

        status = 'good' if raw >= 0.75 else ('warning' if raw >= 0.5 else 'bad')
        return self._make_result('邻面盒形', score, max_s, raw, 1.0, '完整度',
                                 f'{raw:.0%}', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 8. 洞缘光滑度 (5分) — 粗糙度指数
    # ═══════════════════════════════════════════════
    def score_margin_smoothness(self, image, contours):
        max_s = 5
        if not contours:
            return self._make_result('洞缘光滑度', 0, max_s, 0, 0, '粗糙度', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cavity_contour)
        perimeter = cv2.arcLength(cavity_contour, True)

        if perimeter == 0 or area == 0:
            return self._make_result('洞缘光滑度', round(max_s*0.6, 1), max_s, 0, 0, '粗糙度',
                                     '无效轮廓', 'warning')

        ideal_perimeter = 2 * np.sqrt(np.pi * area)
        roughness = perimeter / ideal_perimeter - 1

        # 分段评分
        if roughness < 0.15:
            smooth_score, note = 1.0, '洞缘非常光滑，无悬釉 ✓'
        elif roughness < 0.30:
            smooth_score, note = 0.8, '洞缘基本光滑，轻微粗糙'
        elif roughness < 0.50:
            smooth_score, note = 0.55, '洞缘中等粗糙，存在少量悬釉'
        else:
            smooth_score, note = 0.25, '洞缘粗糙明显，悬釉较多'

        raw = smooth_score
        score = max_s * raw

        process = (
            f'【洞缘光滑度打分过程 — 粗糙度指数分析】\n'
            f'├─ 制备区域面积 = {area:.0f}px²\n'
            f'├─ 实际周长 = {perimeter:.0f}px\n'
            f'├─ 等面积圆周长 = {ideal_perimeter:.0f}px\n'
            f'├─ 粗糙度指数 = 实际周长/理想周长 - 1 = {roughness:.3f}\n'
            f'│   (0=完美光滑, <0.15=优, 0.15-0.30=良, >0.50=差)\n'
            f'├─ 判定: {note}\n'
            f'└─ 得分 = {score:.1f}/{max_s}'
        )

        if roughness > 0.4:
            suggestion = ('洞缘粗糙/悬釉较多。建议：①使用金刚砂车针精细修整洞缘；'
                         '②洞缘釉质应修整为光滑曲线，去除悬釉；'
                         '③修整后使用探针沿洞缘滑行检查；④避免钻针在洞缘反复摩擦。')
        elif roughness > 0.2:
            suggestion = '洞缘有轻微粗糙。建议：用细粒度金刚砂车针沿洞缘修整一遍。'
        else:
            suggestion = '洞缘光滑度良好。'

        status = 'good' if roughness < 0.2 else ('warning' if roughness < 0.4 else 'bad')
        return self._make_result('洞缘光滑度', score, max_s, roughness, 0, '粗糙度',
                                 f'R={roughness:.2f}', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 9. 邻牙保护 (10分)
    # ═══════════════════════════════════════════════
    def score_adjacent_protection(self, image, contours):
        max_s = 10
        if not contours:
            return self._make_result('邻牙保护', max_s, max_s, 0, 0, '损伤', '未检测到异常', 'good')

        cavity_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity_contour)
        aspect_ratio = w / h if h > 0 else 1
        area = cv2.contourArea(cavity_contour)
        hull = cv2.convexHull(cavity_contour)
        hull_area = cv2.contourArea(hull)

        # 检测指标
        # ① 横向扩展度：II类洞不应过度横向扩展
        if aspect_ratio > 3.5:
            expand_score, expand_note = 0.5, '轮廓横向扩展明显，邻牙风险较高'
        elif aspect_ratio > 2.5:
            expand_score, expand_note = 0.75, '轮廓横向略有扩展'
        else:
            expand_score, expand_note = 1.0, '横向扩展在正常范围 ✓'

        # ② 轮廓规则度：突然的凸起可能表示邻牙损伤
        convexity = area / hull_area if hull_area > 0 else 0
        if convexity > 0.7:
            convex_score, convex_note = 1.0, '轮廓规则，无异常凸起 ✓'
        elif convexity > 0.5:
            convex_score, convex_note = 0.8, '轮廓基本规则'
        else:
            convex_score, convex_note = 0.5, '轮廓不规则，邻面区域可能有异常'

        raw = expand_score * 0.5 + convex_score * 0.5
        score = max_s * raw

        process = (
            f'【邻牙保护打分过程】\n'
            f'├─ 轮廓长宽比 = {aspect_ratio:.2f} (过宽>3.5提示邻牙风险)\n'
            f'│   → {expand_note} → {expand_score:.0%}×50%\n'
            f'├─ 轮廓规则度 = {convexity:.2f}\n'
            f'│   → {convex_note} → {convex_score:.0%}×50%\n'
            f'└─ 综合得分 = {score:.1f}/{max_s}'
        )

        if raw < 0.7:
            suggestion = ('存在邻牙损伤风险！建议：①制备邻面盒形时使用邻面保护器(金属成形片)；'
                         '②在邻牙邻面放置保护蜡片；③手机操作时保持支点稳定，防止滑脱；'
                         '④制备完成后检查邻牙邻面是否有划痕或磨损。')
        else:
            suggestion = '未检测到明显邻牙损伤迹象。继续保持邻牙保护操作规范。'

        status = 'good' if raw >= 0.8 else ('warning' if raw >= 0.6 else 'bad')
        return self._make_result('邻牙保护', score, max_s, aspect_ratio, 2.0, '长宽比',
                                 f'AR={aspect_ratio:.1f}', status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 10. 操作过程 (5分)
    # ═══════════════════════════════════════════════
    def score_operation_process(self, elapsed_seconds=None):
        max_s, ideal = 5, 900
        if elapsed_seconds is None:
            return self._make_result('操作过程', round(max_s*0.8, 1), max_s, 0, ideal, '秒',
                                     '未记录时间，默认良好', 'good',
                                     process='ℹ️ 未记录操作时长。建议在系统中输入操作时间以获得更准确的效率评估。')

        elapsed_min = elapsed_seconds / 60
        score_ratio = math.exp(-((elapsed_seconds - ideal) / 600) ** 2)
        score = max_s * score_ratio

        if elapsed_seconds < 600:
            detail, status, note = f'{elapsed_min:.0f}分钟(偏快)', 'warning', '偏快，可能存在粗制滥造'
        elif elapsed_seconds < 1200:
            detail, status, note = f'{elapsed_min:.0f}分钟(合理)', 'good', '时间合理，操作节奏良好 ✓'
        elif elapsed_seconds < 1800:
            detail, status, note = f'{elapsed_min:.0f}分钟(偏慢)', 'warning', '偏慢，效率有待提高'
        else:
            detail, status, note = f'{elapsed_min:.0f}分钟(过慢)', 'bad', '过慢，需加强熟练度训练'

        process = (
            f'【操作过程打分】\n'
            f'├─ 实际用时: {elapsed_min:.1f}分钟 ({elapsed_seconds:.0f}秒)\n'
            f'├─ 理想用时: 15分钟 (900秒)\n'
            f'├─ 高斯评分: exp(-(({elapsed_seconds:.0f}-900)/600)²) = {score_ratio:.3f}\n'
            f'├─ 判定: {note}\n'
            f'└─ 得分 = {score:.1f}/{max_s}'
        )

        if elapsed_seconds < 600:
            suggestion = '操作偏快。建议适当放慢速度，确保每个制备步骤的质量，避免粗制滥造。'
        elif elapsed_seconds > 1500:
            suggestion = ('操作偏慢。建议：①加强支点稳定性练习，减少反复修整；'
                         '②在模型牙上多练习，提高操作熟练度；③规划好制备顺序(先轮廓后深度)。')
        else:
            suggestion = '操作时长合理，效率良好。'

        return self._make_result('操作过程', score, max_s, elapsed_seconds, ideal, '秒',
                                 detail, status,
                                 process=process, suggestion=suggestion)

    # ═══════════════════════════════════════════════
    # 主分析入口
    # ═══════════════════════════════════════════════
    def analyze(self, image_path, operation_time=None, tooth_type='real'):
        image = cv2.imread(image_path)
        report = ScoringReport()
        if image is None:
            report.problem_areas = [{'msg': '无法读取图像文件'}]
            return report

        h, w = image.shape[:2]
        max_dim = max(h, w)
        if max_dim > 600:
            scale = 600 / max_dim
            image = cv2.resize(image, (int(w * scale), int(h * scale)))

        self.calibration_scale = self.detect_scale_marker(image)
        if self.calibration_scale is None:
            self.calibration_scale = self.estimate_scale_from_tooth(image)

        binary, contours = self.extract_cavity_region(image)

        # 执行9维评分
        dims = [
            self.score_outline_form(image, binary, contours),
            self.score_isthmus_ratio(image, contours),
            self.score_cavity_depth(image, contours, tooth_type=tooth_type),
            self.score_floor_flatness(image, contours),
            self.score_wall_verticality(image, contours),
            self.score_line_angle_sharpness(image, contours),
            self.score_proximal_box(image, contours),
            self.score_margin_smoothness(image, contours),
            self.score_adjacent_protection(image, contours),
            self.score_operation_process(operation_time),
        ]

        report.dimensions = dims
        report.total_score = round(sum(d.score for d in dims), 1)

        # 汇总分析
        good_dims = [d for d in dims if d.status == 'good']
        bad_dims = [d for d in dims if d.status == 'bad']
        warning_dims = [d for d in dims if d.status == 'warning']

        report.strengths = [f'{d.name}: {d.score:.0f}/{d.max_score}分' for d in good_dims]
        report.weaknesses = [f'{d.name}: {d.score:.0f}/{d.max_score}分 — {d.targeted_suggestion[:80]}'
                            for d in (bad_dims + warning_dims)]

        # 整体评估
        if report.total_score >= 90:
            report.overall_assessment = '优秀。制备规范，各项指标均衡发展，接近执业医师考试标准。'
        elif report.total_score >= 80:
            report.overall_assessment = '良好。主要维度达标，部分细节可优化。'
        elif report.total_score >= 70:
            report.overall_assessment = '中等。基础操作正确，但多项指标有提升空间。'
        elif report.total_score >= 60:
            report.overall_assessment = '及格。达到基本要求，多个维度需重点加强。'
        else:
            report.overall_assessment = '不及格。基础操作存在明显问题，建议从外形设计和深度控制重新练习。'

        # 问题汇总
        for d in bad_dims + warning_dims:
            report.problem_areas.append({
                'dimension': d.name,
                'score': d.score,
                'max': d.max_score,
                'detail': d.detail,
                'severity': d.status,
                'process_analysis': d.process_analysis,
                'suggestion': d.targeted_suggestion,
            })

        return report


# ── test ──
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        engine = II类洞评分引擎V2()
        report = engine.analyze(sys.argv[1], operation_time=1200)
        print(f'\n{"="*60}')
        print(f'  总分: {report.total_score:.1f}/100  |  {report.overall_assessment}')
        print(f'{"="*60}')
        for d in report.dimensions:
            bar = '█'*int(d.score/d.max_score*25) + '░'*(25-int(d.score/d.max_score*25))
            icon = {'good':'✅','warning':'⚠️','bad':'❌'}[d.status]
            print(f'\n{icon} {d.name} {bar} {d.score:.1f}/{d.max_score}')
            print(f'   {d.process_analysis}')
            if d.targeted_suggestion:
                print(f'   💡 {d.targeted_suggestion}')
        print(f'\n{"="*60}')
        print(f'✅ 强项({len(report.strengths)}):')
        for s in report.strengths[:3]:
            print(f'   {s}')
        print(f'⚠️ 弱项({len(report.weaknesses)}):')
        for w in report.weaknesses[:3]:
            print(f'   {w}')
    else:
        print('Usage: python scoring_engine_v2.py <image_path>')
