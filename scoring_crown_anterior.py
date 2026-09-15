#!/usr/bin/env python3
"""
模块二·前牙全瓷冠牙体预备 AI 评分引擎（11 / 21）
10 维 100 分，对标金砖赛 Fair Grader 2000 三维评分项；另折算设备分(×0.35,/35)。
照片槽位见 scoring_crown_common.SLOTS。
"""

import cv2
import numpy as np
from scoring_crown_common import (
    CrownReport, load_gray, largest_contour, calibrate_mm,
    measure_reduction_dirs, taper_angles, margin_roughness,
    gauss_dev, status_of, make, finalize,
)

# 前牙经验参考宽度(mm)，用于无标尺时的像素标定（报告标注近似）
TOOTH_WIDTH_MM = 8.5


class 前牙全瓷冠评分引擎:
    def analyze(self, photos: dict, tooth='11'):
        r = CrownReport(tooth=tooth)
        d = {}

        # ── 预读各槽位图像与轮廓 ──
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

        # 导板剖面：毫米标定 + 分方向磨除量
        red = None
        scale = None
        if has('guide'):
            _, ggray, gcont = imgs['guide']
            scale = calibrate_mm(ggray, gcont, TOOTH_WIDTH_MM)
            red = measure_reduction_dirs(photos['guide'], scale)

        # ── 1. 切端磨除 12（导板竖直向 + 切端位45°斜面）──
        if red and red.get('vert'):
            v = np.array(red['vert']); mean = float(v.mean()); cv = float(v.std()/mean)
            rate = gauss_dev(mean, 1.5, 2.0, k=6.0, hard=(1.0, 2.5))
            uniform = max(0.0, 1 - cv) * 0.0
            sub = [{'name': '切端间隙均值', 'score': round(mean, 2), 'note': 'mm，理想1.5-2.0'},
                   {'name': '均匀度CV', 'score': round(cv, 2), 'note': '越小越均匀'}]
            proc = (f'【切端磨除】导板近远中剖面竖直缝隙 {len(v)} 点\n'
                    f'├─ 均值={mean:.2f}mm（理想1.5-2.0）→ 得分率{rate:.0%}\n'
                    f'└─ 离散CV={cv:.2f}；切缘应与牙长轴成45°向腭侧小斜面（看③切端位）')
            sug = ('切端间隙合格。' if 1.5 <= mean <= 2.0 else
                   f'切端磨除{"不足(<1.5)" if mean < 1.5 else "过量(>2.0)"}，'
                   '按1.5-2.0mm定深沟控制，并在切缘做45°腭侧小斜面。')
            d['incisal'] = make(self, '切端磨除（1.5-2.0mm·45°腭侧斜面）', 12, rate, mean,
                                '1.5-2.0mm', 'mm', f'均{mean:.2f}mm', proc, sug, sub)
        else:
            d['incisal'] = make(self, '切端磨除（1.5-2.0mm·45°腭侧斜面）', 12, None, 0,
                                '1.5-2.0mm', 'mm', '缺导板剖面/切端位', skip=True,
                                process='⚠️ 未上传⑥导板剖面或③切端位，本维按70%保底，建议补拍。')

        # ── 2. 唇面磨除 13（导板水平向）──
        if red and red.get('horz'):
            h = np.array(red['horz']); mean = float(h.mean()); cv = float(h.std()/mean)
            rate = gauss_dev(mean, 0.8, 1.2, k=8.0, hard=(0.5, 1.6))
            rate = rate * (1 - min(cv, 0.5) * 0.4)   # 不均匀再扣
            proc = (f'【唇面磨除】导板唇舌剖面水平缝隙 {len(h)} 点\n'
                    f'├─ 均值={mean:.2f}mm（理想≈1.0），离散CV={cv:.2f}\n'
                    f'└─ 应分颈/中/切两个方向预备、保留唇面弧面；颈缘终止龈下0.5mm')
            sug = ('唇面磨除均匀达标。' if 0.8 <= mean <= 1.2 and cv < 0.3 else
                   '唇面应均匀磨除约1.0mm，用定深沟分两方向预备，避免磨成平面；颈缘止于龈下0.5mm。')
            d['labial'] = make(self, '唇面磨除（均匀1.0mm·龈下0.5）', 13, rate, mean,
                               '≈1.0mm', 'mm', f'均{mean:.2f}mm CV{cv:.2f}', proc, sug)
        else:
            d['labial'] = make(self, '唇面磨除（均匀1.0mm·龈下0.5）', 13, None, 0,
                               '≈1.0mm', 'mm', '缺导板唇舌切面', skip=True,
                               process='⚠️ 缺⑥导板唇舌向剖面，本维保底70%。')

        # ── 3. 舌面磨除 10（切端位轮廓 + 导板，弱信号→用③边缘梯度代理）──
        if has('occlusal'):
            _, gray, cont = imgs['occlusal']
            rgh = margin_roughness(gray, cont)
            rate = 0.75 if rgh else 0.6
            proc = ('【舌面磨除】③切端位评估舌窝/舌隆突降磨与形态保留\n'
                    '├─ 舌窝按原外形磨1.0mm、舌侧皱襞(隆突)降1.0mm\n'
                    f'└─ 2D近似：边缘粗糙度={rgh[0]:.2f}（仅作形态参考），精确量需导板切面')
            sug = '舌面按舌窝解剖均匀磨1.0mm，舌隆突要降够但别磨平舌窝凹陷。'
            d['lingual'] = make(self, '舌面磨除（舌窝/舌隆突1.0mm）', 10, rate, 0,
                                '≈1.0mm', 'mm', '切端位近似', proc, sug)
        else:
            d['lingual'] = make(self, '舌面磨除（舌窝/舌隆突1.0mm）', 10, None, 0,
                                '≈1.0mm', 'mm', '缺切端位', skip=True,
                                process='⚠️ 缺③切端位照片，本维保底70%。')

        # ── 4. 邻面磨除 8（术后正位/侧位：边缘连续、无异常凸角）──
        if has('post'):
            _, gray, cont = imgs['post']
            hull = cv2.convexHull(cont); hull_area = cv2.contourArea(hull)
            conv = cv2.contourArea(cont) / hull_area if hull_area else 0
            rate = gauss_dev(conv, 0.75, 1.0, k=6.0)
            proc = (f'【邻面磨除】术后正位轮廓凸度={conv:.2f}（去净倒凹、边缘连续应较规则）\n'
                    '├─ 邻面至少磨开、去除倒凹，颈部边缘与唇/舌侧连续\n└─ 不伤邻牙')
            sug = '邻面片切要去净倒凹并让颈缘与唇舌侧连续，建议成形片保护邻牙。' if conv < 0.75 else '邻面去倒凹与边缘连续性良好。'
            d['proximal'] = make(self, '邻面磨除（去倒凹·边缘连续·不伤邻牙）', 8, rate, conv,
                                 '规则连续', '凸度', f'{conv:.2f}', proc, sug)
        else:
            d['proximal'] = make(self, '邻面磨除（去倒凹·边缘连续·不伤邻牙）', 8, None, 0,
                                 '规则连续', '凸度', '缺术后正位', skip=True,
                                 process='⚠️ 缺②术后正位，本维保底70%。')

        # ── 5. 颈缘肩台 16（特写：连续/粗糙度/无卷边；宽度需特写标尺，近似）──
        if has('margin'):
            _, mgray, mcont = imgs['margin']
            rgh = margin_roughness(mgray, mcont)
            roughness, grad = rgh
            smooth_rate = 1.0 if roughness < 0.25 else 0.8 if roughness < 0.4 else 0.5
            sharp_rate = min(1.0, max(0.0, grad / 70.0))
            rate = smooth_rate * 0.6 + sharp_rate * 0.4
            proc = (f'【颈缘肩台】⑤颈缘特写\n├─ 轮廓粗糙度={roughness:.2f}（<0.25连续光滑）→{smooth_rate:.0%}\n'
                    f'├─ 边缘梯度={grad:.0f}（清晰无卷边）→{sharp_rate:.0%}\n'
                    f'└─ 标准：宽0.8-1.0mm连续、无菲边/卷边；唇侧龈下0.5、舌侧齐龈')
            sug = ('肩台连续清晰。' if rate >= 0.8 else
                   '肩台存在不连续/卷边或宽窄不均：用肩台车针沿颈缘匀速走一遍，做出0.8-1.0mm连续直角/浅凹肩台。')
            d['margin'] = make(self, '颈缘肩台（0.8-1.0mm·连续无卷边）', 16, rate, roughness,
                               '0.8-1.0mm', '粗糙度', f'R{roughness:.2f}', proc, sug)
        else:
            d['margin'] = make(self, '颈缘肩台（0.8-1.0mm·连续无卷边）', 16, None, 0,
                               '0.8-1.0mm', '粗糙度', '缺颈缘特写', skip=True,
                               process='⚠️ 缺⑤颈缘特写，本维保底70%。')

        # ── 6. 聚合度·就位道 16（邻面侧位）──
        if has('lateral'):
            _, _, lcont = imgs['lateral']
            ta = taper_angles(lcont)
            if ta:
                taper, la, ra = ta
                rate = gauss_dev(taper, 2.0, 5.0, k=0.12, hard=(0, 15))
                if taper > 15:
                    rate = min(rate, 0.3)
                proc = (f'【聚合度·就位道】④邻面侧位多边形逼近\n'
                        f'├─ 左壁倾角={la:.1f}° 右壁={ra:.1f}° → 切向总聚合≈{taper:.1f}°\n'
                        f'└─ 理想2-5°；5-8轻扣，8-15警告，>15重扣；轴面无倒凹、唇舌壁平行')
                sug = ('聚合度2-5°、就位道良好。' if 2 <= taper <= 5 else
                       f'聚合度过{"大("+format(taper,".1f")+"°>5°)，就位道差、固位力下降" if taper>5 else "小，注意有无倒凹/就位受阻"}，'
                       '备牙时车针整体顺牙长轴、控制唇舌壁平行。')
                d['taper'] = make(self, '聚合度·共同就位道（2-5°）', 16, rate, taper,
                                  '2-5°', '度', f'{taper:.1f}°', proc, sug)
            else:
                d['taper'] = make(self, '聚合度·共同就位道（2-5°）', 16, None, 0, '2-5°', '度',
                                  '侧位无法提取轴壁', skip=True,
                                  process='⚠️ 侧位照片未能提取两条轴壁，请竖直拍摄牙长轴。')
        else:
            d['taper'] = make(self, '聚合度·共同就位道（2-5°）', 16, None, 0, '2-5°', '度',
                              '缺邻面侧位', skip=True, process='⚠️ 缺④邻面侧位，本维保底70%。')

        # ── 7. 轴面精修·线角 8（正位+特写梯度）──
        grad_vals = []
        for slot in ('post', 'margin'):
            if has(slot):
                rgh = margin_roughness(imgs[slot][1], imgs[slot][2])
                if rgh:
                    grad_vals.append(rgh[1])
        if grad_vals:
            grad = float(np.mean(grad_vals))
            rate = min(1.0, max(0.0, grad / 70.0))
            proc = f'【轴面精修】术后正位+颈缘特写平均边缘梯度={grad:.0f}（越清晰线角越利落）'
            sug = '轴面光滑、线角圆钝连续。' if rate >= 0.8 else '精修不足：用红环细砂车针(F)抛修轴面，消除棱角台阶、圆钝线角。'
            d['finish'] = make(self, '轴面精修·线角（光滑圆钝）', 8, rate, grad, '清晰连续',
                               '梯度', f'{grad:.0f}', proc, sug)
        else:
            d['finish'] = make(self, '轴面精修·线角（光滑圆钝）', 8, None, 0, '清晰连续', '梯度',
                               '缺正位/特写', skip=True, process='⚠️ 缺②或⑤，本维保底70%。')

        # ── 8. 整体形态/体积比 9（术前vs术后正位轮廓差）──
        if has('pre') and has('post'):
            _, _, cpre = imgs['pre']; _, _, cpost = imgs['post']
            xp, yp, wp, hp = cv2.boundingRect(cpre)
            xq, yq, wq, hq = cv2.boundingRect(cpost)
            area_pre, area_post = cv2.contourArea(cpre), cv2.contourArea(cpost)
            dev = abs(area_pre - area_post) / area_pre if area_pre else 1
            # 冠预备合理面积缩减带（2D投影 8%-30%），过小=欠磨，过大=过磨
            rate = gauss_dev(dev, 0.08, 0.30, k=40.0)
            proc = (f'【整体形态/体积比】术前vs术后正位轮廓\n'
                    f'├─ 术前面积={area_pre:.0f} 术后={area_post:.0f} 投影变化={dev:.1%}\n'
                    f'└─ 合理缩减带8-30%（对标3D体积比，2D为近似）；外形应与原牙一致')
            sug = '整体磨除量与原牙外形协调。' if 0.08 <= dev <= 0.30 else ('投影变化过小，可能整体欠磨。' if dev < 0.08 else '投影变化过大，警惕整体过磨/形态失真。')
            d['volume'] = make(self, '整体形态/体积比（对标3D偏差）', 9, rate, dev*100,
                               '偏差≤10%', '%', f'变{dev:.0%}', proc, sug)
        else:
            d['volume'] = make(self, '整体形态/体积比（对标3D偏差）', 9, None, 0, '偏差≤10%', '%',
                               '缺术前/术后正位', skip=True,
                               process='⚠️ 需①术前与②术后同角度正位才能做形态比对，本维保底70%。')

        # ── 9. 邻牙·牙龈保护 5（正位轮廓异常横展代理）──
        if has('post'):
            _, _, cont = imgs['post']
            x, y, w, h = cv2.boundingRect(cont)
            ar = w / h if h else 1
            rate = 1.0 if ar < 1.6 else 0.7 if ar < 2.2 else 0.4
            proc = f'【邻牙/牙龈保护】术后正位外接宽高比={ar:.2f}（异常横展提示邻面误伤，近似判断）'
            sug = '未见明显邻牙/牙龈损伤。' if rate >= 1 else '邻面可能过展，务必用成形片保护邻牙并检查牙龈有无划伤。'
            d['protect'] = make(self, '邻牙·牙龈保护（无损伤）', 5, rate, ar, '无损伤', '宽高比',
                                f'{ar:.2f}', proc, sug)
        else:
            d['protect'] = make(self, '邻牙·牙龈保护（无损伤）', 5, None, 0, '无损伤', '宽高比',
                                '缺术后正位', skip=True, process='⚠️ 缺②术后正位，本维保底70%。')

        # ── 10. 整洁 3（半自动默认良好，裁判可覆盖）──
        d['clean'] = make(self, '头模/工作台整洁', 3, 0.85, 0, '整洁', '', '默认良好',
                          '【整洁】AI默认给85%，现场裁判可根据头模/台面清洁情况覆盖。',
                          '赛后关机、整理器械、清洁台面。')

        order = ['incisal', 'labial', 'lingual', 'proximal', 'margin', 'taper',
                 'finish', 'volume', 'protect', 'clean']
        r.dimensions = [d[k] for k in order]
        r.slots_present = list(imgs.keys())
        return finalize(self, r)
