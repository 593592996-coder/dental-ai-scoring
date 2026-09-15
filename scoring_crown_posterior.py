#!/usr/bin/env python3
"""
模块二·后牙全瓷冠牙体预备 AI 评分引擎（16 / 26 / 36 / 46，不含7号牙）
10 维 100 分，对标金砖赛 Fair Grader 2000 三维评分项；另折算设备分(×0.35,/35)。
照片槽位见 scoring_crown_common.SLOTS。
"""

import cv2
import numpy as np
from scoring_crown_common import (
    CrownReport, load_gray, largest_contour, calibrate_mm,
    measure_reduction_dirs, taper_angles, margin_roughness,
    gauss_dev, make, finalize,
)

# 后牙经验参考颊舌径(mm)，无标尺时像素标定用（报告标注近似）
TOOTH_WIDTH_MM = 11.0


class 后牙全瓷冠评分引擎:
    def analyze(self, photos: dict, tooth='16'):
        r = CrownReport(tooth=tooth)
        d = {}

        imgs = {}
        for slot, path in photos.items():
            if not path:
                continue
            img, gray = load_gray(path)
            if gray is None:
                continue
            cont, _ = largest_contour(gray)
            imgs[slot] = (img, gray, cont)

        def has(slot):
            return slot in imgs and imgs[slot][2] is not None

        red = None
        if has('guide'):
            _, ggray, gcont = imgs['guide']
            scale = calibrate_mm(ggray, gcont, TOOTH_WIDTH_MM)
            red = measure_reduction_dirs(photos['guide'], scale)

        # ── 1. 合面磨除 15（导板竖直向：功能尖2.0/非功能尖1.5；合面位查功能尖斜面）──
        if red and red.get('vert'):
            v = np.array(red['vert']); mean = float(v.mean()); cv = float(v.std()/mean)
            # 混合带：非功能尖1.5到功能尖2.0之间为满分
            rate = gauss_dev(mean, 1.5, 2.0, k=5.0, hard=(1.1, 2.5))
            rate *= (1 - min(cv, 0.5) * 0.3)
            bevel_note = '合面位应见功能尖斜面' + ('（边缘形态可辨）' if has('occlusal') else '（缺③，未核）')
            proc = (f'【合面磨除】导板剖面竖直缝隙 {len(v)} 点\n'
                    f'├─ 均值={mean:.2f}mm（功能尖2.0、非功能尖1.5，混合带1.5-2.0）CV={cv:.2f}\n'
                    f'└─ {bevel_note}；按解剖均匀磨、保持合面窝沟外形')
            good = 1.5 <= mean <= 2.0
            sug = ('合面磨除量与均匀度良好，注意功能尖必须做出2.0mm斜面。' if good else
                   f'合面磨除{"不足(<1.5)" if mean<1.5 else "过量(>2.0)"}，按功能尖2.0/非功能尖1.5定深，勿磨平窝沟。')
            d['occlusal'] = make(self, '合面磨除（功能尖2.0·非功能尖1.5+斜面）', 15, rate, mean,
                                 '1.5-2.0mm', 'mm', f'均{mean:.2f}mm', proc, sug)
        else:
            d['occlusal'] = make(self, '合面磨除（功能尖2.0·非功能尖1.5+斜面）', 15, None, 0,
                                 '1.5-2.0mm', 'mm', '缺导板/合面位', skip=True,
                                 process='⚠️ 未上传⑥导板剖面，本维保底70%，建议补拍。')

        # ── 2. 颊面磨除 11（导板水平向混合，理想1.0-1.5）──
        if red and red.get('horz'):
            h = np.array(red['horz']); mean = float(h.mean()); cv = float(h.std()/mean)
            rate = gauss_dev(mean, 1.0, 1.5, k=7.0, hard=(0.7, 2.0))
            rate *= (1 - min(cv, 0.5) * 0.4)
            proc = (f'【颊/舌轴面磨除】导板唇舌剖面水平缝隙 {len(h)} 点\n'
                    f'├─ 均值={mean:.2f}mm（颊面1.0-1.5；舌面去倒凹），CV={cv:.2f}\n'
                    f'└─ 颊面颈缘齐龈；颊/舌轴面聚合2-5°')
            sug = ('轴面磨除均匀达标。' if 1.0 <= mean <= 1.5 and cv < 0.3 else
                   '轴面按1.0-1.5mm定深沟均匀磨，颊面保留外形、颈缘齐龈，舌面去净倒凹。')
            d['buccal'] = make(self, '颊面磨除（1.0-1.5mm·齐龈）', 11, rate, mean,
                               '1.0-1.5mm', 'mm', f'均{mean:.2f}mm', proc, sug)
        else:
            d['buccal'] = make(self, '颊面磨除（1.0-1.5mm·齐龈）', 11, None, 0,
                               '1.0-1.5mm', 'mm', '缺导板唇舌切面', skip=True,
                               process='⚠️ 缺⑥导板唇舌向剖面，本维保底70%。')

        # ── 3. 舌面磨除 11（侧位/合面位代理：去倒凹、聚合方向）──
        if has('lateral'):
            _, gray, cont = imgs['lateral']
            rgh = margin_roughness(gray, cont)
            rate = 0.75 if rgh else 0.6
            proc = ('【舌面磨除】④邻面侧位评估舌面倒凹与聚合方向（2D近似）\n'
                    '├─ 舌面需去净倒凹、颈缘齐龈、聚合2-5°\n'
                    f'└─ 精确磨除量需导板切面；边缘粗糙度={rgh[0]:.2f}')
            sug = '舌面重点是去净倒凹并让颈缘齐龈，方向顺共同就位道。'
            d['lingual'] = make(self, '舌面磨除（去倒凹·齐龈）', 11, rate, 0,
                                '去倒凹', 'mm', '侧位近似', proc, sug)
        else:
            d['lingual'] = make(self, '舌面磨除（去倒凹·齐龈）', 11, None, 0,
                                '去倒凹', 'mm', '缺邻面侧位', skip=True,
                                process='⚠️ 缺④邻面侧位，本维保底70%。')

        # ── 4. 邻面磨除 8 ──
        if has('post'):
            _, gray, cont = imgs['post']
            hull = cv2.convexHull(cont); hull_area = cv2.contourArea(hull)
            conv = cv2.contourArea(cont) / hull_area if hull_area else 0
            rate = gauss_dev(conv, 0.75, 1.0, k=6.0)
            proc = (f'【邻面磨除】术后正位轮廓凸度={conv:.2f}\n'
                    '├─ 邻间隙足够、方向顺就位道、颈部边缘连续\n└─ 不伤邻牙')
            sug = '邻面片切不足或边缘不连续，分层片切至接触完全打开并保护邻牙。' if conv < 0.75 else '邻面打开与边缘连续性良好。'
            d['proximal'] = make(self, '邻面磨除（间隙足够·不伤邻牙）', 8, rate, conv,
                                 '连续', '凸度', f'{conv:.2f}', proc, sug)
        else:
            d['proximal'] = make(self, '邻面磨除（间隙足够·不伤邻牙）', 8, None, 0,
                                 '连续', '凸度', '缺术后正位', skip=True,
                                 process='⚠️ 缺②术后正位，本维保底70%。')

        # ── 5. 颈缘肩台 17（齐龈）──
        if has('margin'):
            _, mgray, mcont = imgs['margin']
            roughness, grad = margin_roughness(mgray, mcont)
            smooth_rate = 1.0 if roughness < 0.25 else 0.8 if roughness < 0.4 else 0.5
            sharp_rate = min(1.0, max(0.0, grad / 70.0))
            rate = smooth_rate * 0.6 + sharp_rate * 0.4
            proc = (f'【颈缘肩台】⑤颈缘特写\n├─ 粗糙度={roughness:.2f}→{smooth_rate:.0%}，'
                    f'边缘梯度={grad:.0f}→{sharp_rate:.0%}\n'
                    '└─ 宽0.8-1.0mm、齐龈、四面连续、无菲边/卷边')
            sug = ('肩台连续清晰、齐龈。' if rate >= 0.8 else
                   '肩台不连续/卷边或宽窄不一：用肩台车针沿齐龈颈缘匀速做出0.8-1.0mm连续肩台。')
            d['margin'] = make(self, '颈缘肩台（0.8-1.0mm·齐龈·连续）', 17, rate, roughness,
                               '0.8-1.0mm', '粗糙度', f'R{roughness:.2f}', proc, sug)
        else:
            d['margin'] = make(self, '颈缘肩台（0.8-1.0mm·齐龈·连续）', 17, None, 0,
                               '0.8-1.0mm', '粗糙度', '缺颈缘特写', skip=True,
                               process='⚠️ 缺⑤颈缘特写，本维保底70%。')

        # ── 6. 聚合度·就位道 17 ──
        if has('lateral'):
            _, _, lcont = imgs['lateral']
            ta = taper_angles(lcont)
            if ta:
                taper, la, ra = ta
                rate = gauss_dev(taper, 2.0, 5.0, k=0.12, hard=(0, 15))
                if taper > 15:
                    rate = min(rate, 0.3)
                proc = (f'【聚合度·就位道】④邻面侧位\n├─ 左壁{la:.1f}° 右壁{ra:.1f}° → 总聚合≈{taper:.1f}°\n'
                        '└─ 理想2-5°；5-8轻扣，8-15警告，>15重扣；单一就位道、无倒凹')
                sug = ('聚合度2-5°、就位道良好。' if 2 <= taper <= 5 else
                       f'聚合度过{"大("+format(taper,".1f")+"°)，固位力下降" if taper>5 else "小，查倒凹"}，'
                       '车针顺牙长轴、各轴面平行控制。')
                d['taper'] = make(self, '聚合度·共同就位道（2-5°）', 17, rate, taper,
                                  '2-5°', '度', f'{taper:.1f}°', proc, sug)
            else:
                d['taper'] = make(self, '聚合度·共同就位道（2-5°）', 17, None, 0, '2-5°', '度',
                                  '侧位无法提取轴壁', skip=True,
                                  process='⚠️ 侧位未能提取两条轴壁，请竖直拍摄牙长轴。')
        else:
            d['taper'] = make(self, '聚合度·共同就位道（2-5°）', 17, None, 0, '2-5°', '度',
                              '缺邻面侧位', skip=True, process='⚠️ 缺④邻面侧位，本维保底70%。')

        # ── 7. 轴面精修·线角 8 ──
        grad_vals = []
        for slot in ('post', 'margin'):
            if has(slot):
                rgh = margin_roughness(imgs[slot][1], imgs[slot][2])
                if rgh:
                    grad_vals.append(rgh[1])
        if grad_vals:
            grad = float(np.mean(grad_vals))
            rate = min(1.0, max(0.0, grad / 70.0))
            proc = f'【轴面精修】正位+颈缘特写平均边缘梯度={grad:.0f}'
            sug = '轴面光滑、线角圆钝连续。' if rate >= 0.8 else '用红环细砂车针(F)精修，去台阶棱角、圆钝线角。'
            d['finish'] = make(self, '轴面精修·线角（光滑圆钝）', 8, rate, grad, '清晰连续',
                               '梯度', f'{grad:.0f}', proc, sug)
        else:
            d['finish'] = make(self, '轴面精修·线角（光滑圆钝）', 8, None, 0, '清晰连续', '梯度',
                               '缺正位/特写', skip=True, process='⚠️ 缺②或⑤，本维保底70%。')

        # ── 8. 整体形态/体积比 8 ──
        if has('pre') and has('post'):
            _, _, cpre = imgs['pre']; _, _, cpost = imgs['post']
            area_pre, area_post = cv2.contourArea(cpre), cv2.contourArea(cpost)
            dev = abs(area_pre - area_post) / area_pre if area_pre else 1
            rate = gauss_dev(dev, 0.10, 0.32, k=30.0)
            proc = (f'【整体形态/体积比】术前vs术后正位轮廓\n'
                    f'├─ 术前面积={area_pre:.0f} 术后={area_post:.0f} 投影变化={dev:.1%}\n'
                    '└─ 合理缩减带10-32%（对标3D体积比，2D近似），保持合面解剖外形')
            sug = '整体磨除均衡、解剖外形保持良好。' if 0.10 <= dev <= 0.32 else ('变化偏小，可能整体欠磨。' if dev < 0.10 else '变化过大，警惕过磨/外形失真。')
            d['volume'] = make(self, '整体形态/体积比（对标3D偏差）', 8, rate, dev*100,
                               '偏差≤10%', '%', f'变{dev:.0%}', proc, sug)
        else:
            d['volume'] = make(self, '整体形态/体积比（对标3D偏差）', 8, None, 0, '偏差≤10%', '%',
                               '缺术前/术后正位', skip=True,
                               process='⚠️ 需①术前与②术后同角度正位，本维保底70%。')

        # ── 9. 邻牙·牙龈保护 3 ──
        if has('post'):
            _, _, cont = imgs['post']
            x, y, w, h = cv2.boundingRect(cont)
            ar = w / h if h else 1
            rate = 1.0 if ar < 1.5 else 0.7 if ar < 2.0 else 0.4
            proc = f'【邻牙/牙龈保护】术后正位宽高比={ar:.2f}（异常横展提示邻面误伤，近似）'
            sug = '未见明显邻牙/牙龈损伤。' if rate >= 1 else '邻面可能过展，用成形片保护邻牙并检查牙龈。'
            d['protect'] = make(self, '邻牙·牙龈保护（无损伤）', 3, rate, ar, '无损伤', '宽高比',
                                f'{ar:.2f}', proc, sug)
        else:
            d['protect'] = make(self, '邻牙·牙龈保护（无损伤）', 3, None, 0, '无损伤', '宽高比',
                                '缺术后正位', skip=True, process='⚠️ 缺②术后正位，本维保底70%。')

        # ── 10. 整洁 2 ──
        d['clean'] = make(self, '头模/工作台整洁', 2, 0.85, 0, '整洁', '', '默认良好',
                          '【整洁】AI默认给85%，现场裁判可覆盖。',
                          '赛后关机、整理器械、清洁台面。')

        order = ['occlusal', 'buccal', 'lingual', 'proximal', 'margin', 'taper',
                 'finish', 'volume', 'protect', 'clean']
        r.dimensions = [d[k] for k in order]
        r.slots_present = list(imgs.keys())
        return finalize(self, r)
