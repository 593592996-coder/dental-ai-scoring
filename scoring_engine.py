#!/usr/bin/env python3
"""
II类洞AI评分引擎 — Phase 1 (规则引擎 + OpenCV传统算法)
无需训练数据，基于图像处理的标准测量算法
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import math
import json


# ============================================================
# Data Structures
# ============================================================
@dataclass
class CavityMeasurement:
    """单个维度的测量结果"""
    name: str
    score: float          # 0-满分
    max_score: float
    raw_value: float      # 原始测量值
    ideal_value: float    # 理想值
    unit: str
    detail: str           # 人类可读的评价
    status: str           # 'good', 'warning', 'bad'


@dataclass
class ScoringReport:
    """完整评分报告"""
    total_score: float = 0
    max_total: float = 100
    dimensions: List[CavityMeasurement] = field(default_factory=list)
    problem_areas: List[dict] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    annotated_image_path: Optional[str] = None


# ============================================================
# Configuration: II类洞评分标准 (参照执业医师考试)
# ============================================================
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


# ============================================================
# Core Analysis Functions
# ============================================================
class II类洞评分引擎:
    """II类洞制备AI评分引擎"""

    def __init__(self):
        self.calibration_scale = None  # mm/pixel
        self.reference_marker_mm = 5.0  # 参考标尺=5mm
        self.config = SCORING_CONFIG
        # Color thresholds for depth analysis (LAB color space)
        self.enamel_l_range = (80, 100)   # 牙釉质: 亮白
        self.enamel_b_range = (3, 15)     # 牙釉质: 偏蓝
        self.dej_l_range = (70, 85)       # 釉牙本质界: 过渡
        self.dej_b_range = (0, 8)         # 釉牙本质界: 中性偏蓝
        self.dentin_l_range = (55, 75)    # 牙本质浅层: 偏暗 (目标深度)
        self.dentin_b_range = (-5, 5)     # 牙本质浅层: 偏黄

    # ── 1. 标尺识别与尺寸校准 ──
    def detect_scale_marker(self, image: np.ndarray) -> Optional[float]:
        """
        检测图像中的参考标尺，返回 mm/pixel 比例
        支持两种模式：
          A) 标准标尺贴纸（两个黑色圆点，间距5mm）
          B) 牙科探针刻度（已知探针头直径1mm）
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # 模式A: 检测圆形标记点
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=50,
            param1=50, param2=30, minRadius=10, maxRadius=80
        )
        if circles is not None and len(circles[0]) >= 2:
            circles = np.round(circles[0]).astype(int)
            # 取最接近的两个圆（距离约代表5mm间距范围）
            if len(circles) > 2:
                # 按x坐标排序，取首尾两个
                circles = circles[circles[:, 0].argsort()]
                c1, c2 = circles[0], circles[-1]
            else:
                c1, c2 = circles[0], circles[1]
            pixel_dist = np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)
            if 30 < pixel_dist < 500:  # 合理范围
                return self.reference_marker_mm / pixel_dist
        # 模式B: 回退 — 使用图像宽度估算
        # 假设标准拍摄距离15cm，树脂牙颌面约10mm宽
        return None

    def estimate_scale_from_tooth(self, image: np.ndarray) -> float:
        """基于牙冠标准宽度估算比例尺（回退方案）"""
        # 下颌第一磨牙近远中径≈11mm，颊舌径≈10.5mm
        # 从轮廓检测中估计牙冠宽度
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 100)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            if 100 < w < 2000:  # 合理像素范围
                # 假设检测到的是牙冠轮廓，宽度≈11mm
                return 11.0 / w
        return 0.05  # 默认值

    # ── 2. 牙体分割与制备区域提取 ──
    def extract_cavity_region(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        从图像中分割出制备区域
        返回: (二值掩膜, 轮廓列表)
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)

        # Otsu自动阈值分割（制备区域颜色更深）
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # 形态学操作：去除噪声，连接相邻区域
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return binary, contours

    # ── 3. 外形轮廓评分 (20分) ──
    def score_outline_form(self, image: np.ndarray, binary: np.ndarray,
                           contours: list) -> CavityMeasurement:
        """基于轮廓形状特征评分"""
        max_s = self.config['outline_form']['max']
        if not contours:
            return CavityMeasurement('外形轮廓', 0, max_s, 0, 1.0, '相似度', '未检测到制备区域', 'bad')

        # 选择最大轮廓（制备区域）
        cavity_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cavity_contour)
        perimeter = cv2.arcLength(cavity_contour, True)

        # 指标1: 圆形度（II类洞应为不规则多边形，非圆形）
        if perimeter > 0:
            circularity = 4 * np.pi * area / (perimeter ** 2)
            # II类洞理想圆形度≈0.3-0.6
            if 0.25 < circularity < 0.65:
                shape_score = 1.0
            elif 0.15 < circularity < 0.75:
                shape_score = 0.8
            else:
                shape_score = 0.5
        else:
            shape_score = 0

        # 指标2: 轮廓凹凸性（检查是否具有鸠尾+邻面双区域特征）
        hull = cv2.convexHull(cavity_contour)
        hull_area = cv2.contourArea(hull)
        if hull_area > 0:
            convexity = area / hull_area
            # 鸠尾+邻面结构使convexity降低（凹入多）
            if 0.6 < convexity < 0.9:
                convexity_score = 1.0
            elif 0.5 < convexity < 0.95:
                convexity_score = 0.8
            else:
                convexity_score = 0.5
        else:
            convexity_score = 0

        # 综合评分
        raw = shape_score * 0.5 + convexity_score * 0.5
        score = max_s * raw

        detail = f'圆形度={circularity:.2f}, 凸度={convexity:.2f}'
        status = 'good' if raw > 0.8 else ('warning' if raw > 0.6 else 'bad')
        return CavityMeasurement('外形轮廓', round(score, 1), max_s, round(raw, 2),
                                 1.0, '相似度', detail, status)

    # ── 4. 鸠尾峡评分 (15分) ──
    def score_isthmus_ratio(self, image: np.ndarray,
                            contours: list) -> CavityMeasurement:
        """测量鸠尾峡宽度与颊舌尖距的比例"""
        max_s = self.config['isthmus_ratio']['max']
        ideal = self.config['isthmus_ratio']['ideal']

        if not contours:
            return CavityMeasurement('鸠尾峡比例', max_s // 2, max_s, 0, ideal,
                                     '比值', '无法检测', 'warning')

        cavity_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity_contour)

        # 估算: 峡部最窄处宽度 / 牙冠颊舌总宽度
        # 方法: 将轮廓纵向扫描，找到最小宽度（峡部）和最大宽度（颊舌尖距）
        if h > 10 and w > 10:
            # 沿Y轴扫描，计算每行的轮廓宽度
            mask = np.zeros(image.shape[:2], dtype=np.uint8)
            cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

            widths = []
            for row in range(y, min(y + h, mask.shape[0])):
                row_pixels = np.where(mask[row, :] > 0)[0]
                if len(row_pixels) >= 2:
                    widths.append(row_pixels[-1] - row_pixels[0])

            if widths:
                min_width = min(widths)  # 峡部宽度
                max_width = max(widths)  # 最大宽度(近似颊舌尖距)

                if max_width > 0:
                    ratio = min_width / max_width
                    # 高斯评分：越接近0.33得分越高
                    score_ratio = math.exp(-50 * (ratio - ideal) ** 2)
                    score = max_s * score_ratio

                    if abs(ratio - ideal) < 0.1:
                        detail = f'峡/宽={ratio:.2f} ✓ 接近理想值{ideal}'
                        status = 'good'
                    elif abs(ratio - ideal) < 0.2:
                        direction = '偏宽' if ratio > ideal else '偏窄'
                        detail = f'峡/宽={ratio:.2f} {direction}，理想值{ideal}'
                        status = 'warning'
                    else:
                        direction = '偏宽' if ratio > ideal else '偏窄'
                        detail = f'峡/宽={ratio:.2f} 严重{direction}，理想值{ideal}'
                        status = 'bad'

                    return CavityMeasurement('鸠尾峡比例', round(score, 1), max_s,
                                             round(ratio, 3), ideal, '比值', detail, status)

        return CavityMeasurement('鸠尾峡比例', round(max_s * 0.7, 1), max_s, 0, ideal,
                                 '比值', '测量受限，使用近似估计', 'warning')

    # ── 5. 洞深评分 (10分) — 色差分析 ──
    def score_cavity_depth(self, image: np.ndarray, contours: list) -> CavityMeasurement:
        """基于LAB色彩空间分析洞深"""
        max_s = self.config['cavity_depth']['max']
        ideal = self.config['cavity_depth']['ideal']

        if not contours:
            return CavityMeasurement('洞深', 0, max_s, 0, ideal, 'mm', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        # 转换到LAB色彩空间
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        cavity_pixels = lab[mask > 0]

        if len(cavity_pixels) == 0:
            return CavityMeasurement('洞深', round(max_s * 0.6, 1), max_s, 0,
                                     ideal, 'mm', '分割区域无效', 'warning')

        # 分析L和B通道
        l_vals = cavity_pixels[:, 0]
        b_vals = cavity_pixels[:, 2]

        l_mean = np.mean(l_vals)
        b_mean = np.mean(b_vals)

        # 分类每个像素的深度层级
        # 牙本质浅层(目标): L=55-75, B=-5~5
        dentin_pixels = np.sum((l_vals >= 55) & (l_vals <= 75) &
                               (b_vals >= -5) & (b_vals <= 5))
        # 牙釉质(太浅): L>80, B>5
        enamel_pixels = np.sum((l_vals > 80) & (b_vals > 5))
        # 牙本质深层(太深): L<55, B<-5
        deep_pixels = np.sum((l_vals < 55) & (b_vals < -5))
        # 釉牙本质界(过渡): L=70-85, B=0-8
        dej_pixels = np.sum((l_vals >= 70) & (l_vals <= 85) &
                            (b_vals >= 0) & (b_vals <= 8))

        total = len(cavity_pixels)
        target_ratio = (dentin_pixels + dej_pixels * 0.5) / total  # 达标+过渡
        too_shallow_ratio = enamel_pixels / total
        too_deep_ratio = deep_pixels / total

        # 评分
        score = max_s * target_ratio
        if too_deep_ratio > 0.15:  # 超过15%像素太深 → 疑似穿髓风险
            score -= 3
        score = max(0, min(max_s, score))

        detail = f'L均值={l_mean:.0f}, B均值={b_mean:.0f}, '
        detail += f'达标率={target_ratio:.0%}, 过浅={too_shallow_ratio:.0%}, 过深={too_deep_ratio:.0%}'

        if target_ratio > 0.75 and too_deep_ratio < 0.1:
            status = 'good'
        elif target_ratio > 0.5:
            status = 'warning'
        else:
            status = 'bad'

        return CavityMeasurement('洞深', round(score, 1), max_s,
                                 round(target_ratio, 2), 1.0, '达标率', detail, status)

    # ── 6. 底平评分 (8分) — 平面度分析 ──
    def score_floor_flatness(self, image: np.ndarray, contours: list) -> CavityMeasurement:
        """评估髓壁区域的颜色/纹理均匀性来推断平面度"""
        max_s = self.config['floor_flatness']['max']

        if not contours:
            return CavityMeasurement('髓壁平面度', 0, max_s, 0, 0, '残差', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        # 提取洞底中心区域
        x, y, w, h = cv2.boundingRect(cavity_contour)
        center_y = y + h // 2
        center_x = x + w // 2
        center_region = mask[max(0, center_y - h // 6): min(mask.shape[0], center_y + h // 6),
                             max(0, center_x - w // 4): min(mask.shape[1], center_x + w // 4)]

        if center_region.size == 0 or np.sum(center_region) == 0:
            return CavityMeasurement('髓壁平面度', round(max_s * 0.6, 1), max_s, 0,
                                     0, '残差', '中心区域检测失败', 'warning')

        # 分析中心区域灰度标准差（越小越均匀 → 越平坦）
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        center_gray = gray[max(0, center_y - h // 6): min(mask.shape[0], center_y + h // 6),
                           max(0, center_x - w // 4): min(mask.shape[1], center_x + w // 4)]
        center_gray_valid = center_gray[center_region > 0]

        if len(center_gray_valid) < 20:
            return CavityMeasurement('髓壁平面度', round(max_s * 0.6, 1), max_s, 0,
                                     0, '残差', '有效像素不足', 'warning')

        std_val = np.std(center_gray_valid)
        # 标准差映射到得分: std<15 → 满分, std>40 → 不及格
        flatness = max(0.0, min(1.0, 1.0 - (std_val - 15) / 30))
        score = max(0.0, min(max_s, max_s * flatness))

        detail = f'灰度标准差={std_val:.1f} (越小越平坦, <15为优)'
        status = 'good' if std_val < 20 else ('warning' if std_val < 35 else 'bad')
        return CavityMeasurement('髓壁平面度', round(score, 1), max_s,
                                 round(std_val, 1), 0, 'std', detail, status)

    # ── 7. 壁直评分 (7分) — 边缘直线度 ──
    def score_wall_verticality(self, image: np.ndarray, contours: list) -> CavityMeasurement:
        """基于轮廓边缘的直线度评估侧壁垂直度"""
        max_s = self.config['wall_verticality']['max']

        if not contours:
            return CavityMeasurement('侧壁垂直度', 0, max_s, 0, 90, '度', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        # 对轮廓进行多边形逼近
        epsilon = 0.02 * cv2.arcLength(cavity_contour, True)
        approx = cv2.approxPolyDP(cavity_contour, epsilon, True)

        # 计算每条边的角度分布
        angles = []
        for i in range(len(approx)):
            p1 = approx[i][0]
            p2 = approx[(i + 1) % len(approx)][0]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            if abs(dx) + abs(dy) > 10:  # 忽略太短的边
                angle = abs(math.degrees(math.atan2(dy, abs(dx))))
                angles.append(angle)

        if not angles:
            return CavityMeasurement('侧壁垂直度', round(max_s * 0.6, 1), max_s, 0,
                                     90, '度', '无法提取边角度', 'warning')

        # 计算接近垂直（70°-110°）的边占比
        vertical_edges = sum(1 for a in angles if 65 < a < 115)
        ratio = vertical_edges / len(angles)

        # 角度偏差均值
        deviations = [min(abs(a - 90), abs(a - 270)) for a in angles if a < 180]
        avg_dev = np.mean(deviations) if deviations else 30

        score = max(0.0, min(max_s, max_s * ratio * (1 - avg_dev / 45)))

        detail = f'垂直边占比={ratio:.0%}, 平均偏差={avg_dev:.1f}°'
        status = 'good' if ratio > 0.7 else ('warning' if ratio > 0.4 else 'bad')
        return CavityMeasurement('侧壁垂直度', round(score, 1), max_s,
                                 round(ratio, 2), 1.0, '垂直占比', detail, status)

    # ── 8. 点线角评分 (10分) — 边缘锐度 ──
    def score_line_angle_sharpness(self, image: np.ndarray,
                                   contours: list) -> CavityMeasurement:
        """基于边缘梯度的锐度分析"""
        max_s = self.config['line_angle_sharpness']['max']

        if not contours:
            return CavityMeasurement('点线角锐度', 0, max_s, 0, 1.0, '锐度', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [cavity_contour], -1, 255, -1)

        # 沿轮廓采样，计算每点的局部梯度
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        gradient_mag = np.sqrt(sobel_x ** 2 + sobel_y ** 2)

        # 提取轮廓附近的梯度
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        contour_border = cv2.dilate(mask, kernel) - cv2.erode(mask, kernel)
        border_gradients = gradient_mag[contour_border > 0]

        if len(border_gradients) < 10:
            return CavityMeasurement('点线角锐度', round(max_s * 0.6, 1), max_s, 0,
                                     1.0, '锐度', '边缘像素不足', 'warning')

        avg_gradient = np.mean(border_gradients)
        # 梯度越大 → 边缘越锐利
        # 映射: avg_gradient>80 → 满分, <30 → 不及格
        sharpness = min(1.0, max(0, avg_gradient / 80))
        score = max_s * sharpness

        detail = f'平均边缘梯度={avg_gradient:.1f} (>80为锐利)'
        status = 'good' if sharpness > 0.75 else ('warning' if sharpness > 0.4 else 'bad')
        return CavityMeasurement('点线角锐度', round(score, 1), max_s,
                                 round(avg_gradient, 1), 80, '梯度值', detail, status)

    # ── 9. 洞缘光滑度评分 (5分) — 纹理分析 ──
    def score_margin_smoothness(self, image: np.ndarray, contours: list) -> CavityMeasurement:
        """评估洞缘的粗糙度"""
        max_s = self.config['margin_smoothness']['max']

        if not contours:
            return CavityMeasurement('洞缘光滑度', 0, max_s, 0, 0, '粗糙度', '无法检测', 'bad')

        cavity_contour = max(contours, key=cv2.contourArea)
        # 计算轮廓的平滑度：周长²/面积比例
        area = cv2.contourArea(cavity_contour)
        perimeter = cv2.arcLength(cavity_contour, True)

        if perimeter == 0 or area == 0:
            return CavityMeasurement('洞缘光滑度', round(max_s * 0.6, 1), max_s, 0,
                                     0, '粗糙度', '无效轮廓', 'warning')

        # 粗糙度指数: 实际周长/等面积圆的周长
        ideal_perimeter = 2 * np.sqrt(np.pi * area)
        roughness = perimeter / ideal_perimeter - 1  # 0 = 完美光滑

        # 映射: roughness<0.2 → 满分, >0.6 → 不及格
        smoothness_score = max(0, 1 - roughness / 0.6)
        score = max_s * smoothness_score

        detail = f'粗糙度指数={roughness:.2f} (<0.2为光滑)'
        status = 'good' if roughness < 0.25 else ('warning' if roughness < 0.5 else 'bad')
        return CavityMeasurement('洞缘光滑度', round(score, 1), max_s,
                                 round(roughness, 2), 0, '粗糙度', detail, status)

    # ── 10. 邻牙保护评分 (10分) — 邻面检测 ──
    def score_adjacent_protection(self, image: np.ndarray,
                                  contours: list) -> CavityMeasurement:
        """检测邻牙区域是否有异常（模拟）"""
        max_s = self.config['adjacent_protection']['max']
        # Phase 1简化: 检查制备区域是否过度扩展到邻面
        if not contours:
            return CavityMeasurement('邻牙保护', max_s, max_s, 0, 0, '损伤', '未检测到异常', 'good')

        cavity_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(cavity_contour)

        # 检查轮廓的长宽比（如果过于横向扩展，可能损伤邻牙）
        aspect_ratio = w / h if h > 0 else 1
        if aspect_ratio > 3.5:
            detail = f'轮廓横向扩展明显(长宽比={aspect_ratio:.1f})，注意检查邻牙'
            return CavityMeasurement('邻牙保护', round(max_s * 0.7, 1), max_s,
                                     aspect_ratio, 2.0, '长宽比', detail, 'warning')
        elif aspect_ratio > 2.5:
            detail = f'长宽比={aspect_ratio:.1f}，边缘状态'
            return CavityMeasurement('邻牙保护', round(max_s * 0.85, 1), max_s,
                                     aspect_ratio, 2.0, '长宽比', detail, 'warning')
        else:
            return CavityMeasurement('邻牙保护', max_s, max_s, aspect_ratio, 2.0,
                                     '长宽比', '未检测到明显邻牙损伤', 'good')

    # ── 11. 操作过程评分 (5分) — 简易时间评估 ──
    def score_operation_process(self, elapsed_seconds: Optional[float] = None) -> CavityMeasurement:
        """基于操作时间的简易评估"""
        max_s = self.config['operation_process']['max']
        ideal = self.config['operation_process']['ideal']

        if elapsed_seconds is None:
            return CavityMeasurement('操作过程', round(max_s * 0.8, 1), max_s, 0,
                                     ideal, '秒', '未记录操作时间，默认良好', 'good')

        # 高斯评分: 最佳15分钟(900秒)，太短(粗制滥造)和太长(不熟练)都扣分
        score_ratio = math.exp(-((elapsed_seconds - ideal) / 600) ** 2)
        score = max_s * score_ratio

        if elapsed_seconds < 600:
            detail = f'操作{elapsed_seconds:.0f}秒，偏快，检查质量'
            status = 'warning'
        elif elapsed_seconds < 1200:
            detail = f'操作{elapsed_seconds:.0f}秒，时间合理'
            status = 'good'
        elif elapsed_seconds < 1800:
            detail = f'操作{elapsed_seconds:.0f}秒，偏慢，需提高效率'
            status = 'warning'
        else:
            detail = f'操作{elapsed_seconds:.0f}秒，过慢，需加强训练'
            status = 'bad'
        return CavityMeasurement('操作过程', round(score, 1), max_s,
                                 elapsed_seconds, ideal, '秒', detail, status)

    # ── 12. 综合评分 ──
    def analyze(self, image_path: str, operation_time: Optional[float] = None) -> ScoringReport:
        """
        主分析入口
        输入：制备洞形照片路径
        输出：完整评分报告
        """
        image = cv2.imread(image_path)
        if image is None:
            report = ScoringReport()
            report.total_score = 0
            report.problem_areas = [{'msg': '无法读取图像文件'}]
            return report

        # 调整图像大小（保持宽高比，限制最大边=1200px）
        h, w = image.shape[:2]
        max_dim = max(h, w)
        if max_dim > 1200:
            scale = 1200 / max_dim
            image = cv2.resize(image, (int(w * scale), int(h * scale)))

        # 标尺校准
        self.calibration_scale = self.detect_scale_marker(image)
        if self.calibration_scale is None:
            self.calibration_scale = self.estimate_scale_from_tooth(image)

        # 提取制备区域
        binary, contours = self.extract_cavity_region(image)

        # 执行各项评分
        report = ScoringReport()
        dims = []

        d = self.score_outline_form(image, binary, contours)
        dims.append(d)
        d = self.score_isthmus_ratio(image, contours)
        dims.append(d)
        d = self.score_cavity_depth(image, contours)
        dims.append(d)
        d = self.score_floor_flatness(image, contours)
        dims.append(d)
        d = self.score_wall_verticality(image, contours)
        dims.append(d)
        d = self.score_line_angle_sharpness(image, contours)
        dims.append(d)
        d = self.score_margin_smoothness(image, contours)
        dims.append(d)
        d = self.score_adjacent_protection(image, contours)
        dims.append(d)
        d = self.score_operation_process(operation_time)
        dims.append(d)

        report.dimensions = dims
        report.total_score = sum(d.score for d in dims)

        # 生成问题区域和改进建议
        for d in dims:
            if d.status == 'warning':
                report.problem_areas.append({
                    'dimension': d.name,
                    'score': d.score,
                    'max': d.max_score,
                    'detail': d.detail,
                    'severity': 'warning'
                })
            elif d.status == 'bad':
                report.problem_areas.append({
                    'dimension': d.name,
                    'score': d.score,
                    'max': d.max_score,
                    'detail': d.detail,
                    'severity': 'bad'
                })
                if '过深' in d.detail:
                    report.improvement_suggestions.append('洞深偏深，注意控制进针深度，每层预备不超过钻针直径一半')
                if '偏宽' in d.detail:
                    report.improvement_suggestions.append(f'鸠尾峡偏宽，建议下次在牙面标记峡部边界（颊舌尖距1/3处）')
                if '偏窄' in d.detail:
                    report.improvement_suggestions.append(f'鸠尾峡偏窄，注意保持峡宽为颊舌尖距的1/3，避免固位不足')
                if '标准差' in d.detail and d.status != 'good':
                    report.improvement_suggestions.append('髓壁欠平整，建议分层预备，保持手机转速稳定')
                if '垂直' in d.name and d.status != 'good':
                    report.improvement_suggestions.append('侧壁垂直度不足，注意手机与牙体长轴保持平行')
                if '锐度' in d.name and d.status != 'good':
                    report.improvement_suggestions.append('点线角不够锐利，建议使用新钻针，操作时保持支点稳定')

        # 去重
        report.improvement_suggestions = list(dict.fromkeys(report.improvement_suggestions))

        # 生成标注图
        annotated = self.generate_annotated_image(image, contours, binary)
        if annotated is not None:
            ann_path = image_path.replace('.', '_annotated.')
            cv2.imwrite(ann_path, annotated)
            report.annotated_image_path = ann_path

        return report

    def generate_annotated_image(self, image, contours, binary):
        """生成带有AI标注的分析图"""
        annotated = image.copy()
        if contours:
            cavity_contour = max(contours, key=cv2.contourArea)
            # 绿色轮廓 = 检测到的制备区域
            cv2.drawContours(annotated, [cavity_contour], -1, (0, 255, 0), 3)

            # 标注鸠尾峡大概位置（轮廓最窄处）
            x, y, w, h = cv2.boundingRect(cavity_contour)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (255, 165, 0), 2)

            # 标注中心区域（用于平面度分析）
            center_y = y + h // 2
            center_x = x + w // 2
            cv2.circle(annotated, (center_x, center_y), 15, (255, 0, 0), 2)

            # 添加文字说明
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(annotated, 'Cavity Outline', (x, max(0, y - 10)),
                        font, 0.6, (0, 255, 0), 2)
            cv2.putText(annotated, 'Isthmus Region', (x + w // 3, y + h // 2),
                        font, 0.5, (255, 165, 0), 1)
            cv2.putText(annotated, 'Floor Center', (center_x - 40, center_y - 20),
                        font, 0.5, (255, 0, 0), 1)

            # 添加测量数据
            y_offset = 30
            cv2.putText(annotated, f'BBox: {w}x{h}px', (10, y_offset),
                        font, 0.5, (255, 255, 255), 1)
            if self.calibration_scale:
                real_w = w * self.calibration_scale
                real_h = h * self.calibration_scale
                cv2.putText(annotated, f'Size: {real_w:.1f}x{real_h:.1f}mm',
                            (10, y_offset + 20), font, 0.5, (255, 255, 255), 1)

        return annotated


# ============================================================
# Test Entry
# ============================================================
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        engine = II类洞评分引擎()
        report = engine.analyze(sys.argv[1], operation_time=1200)
        print(f'\n{"="*50}')
        print(f'  II类洞制备 AI评分报告')
        print(f'{"="*50}')
        print(f'  总分: {report.total_score:.1f} / {report.max_total}')
        print(f'{"─"*50}')
        for d in report.dimensions:
            bar = '█' * int(d.score / d.max_score * 20) + '░' * (20 - int(d.score / d.max_score * 20))
            icon = {'good': '✅', 'warning': '⚠️', 'bad': '❌'}.get(d.status, '')
            print(f'  {icon} {d.name:<12s} {bar} {d.score:.1f}/{d.max_score}')
            print(f'     {d.detail}')
        print(f'{"─"*50}')
        if report.improvement_suggestions:
            print(f'  🔧 改进建议:')
            for s in report.improvement_suggestions:
                print(f'     · {s}')
        print()
    else:
        print('Usage: python scoring_engine.py <image_path>')
