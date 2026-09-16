# -*- coding: utf-8 -*-
"""病例照片映射：学生做某项检查时才返回对应照片（视诊→口内照，X线片判读→牙片）。

照片实体在 static/images/cases/，文件命名 case00X_序号.jpg。
默认规则：_1 挂「视诊」，_2 挂「X线片判读」；个别病例在 EXTRA_VISUAL 里改挂更贴切的检查。
以后补图：把文件放进 static/images/cases/ 并在这里登记即可。
"""
import os

IMG_SUBDIR = 'cases'

# 口内照/临床照的中文说明（做该检查时随图展示，只描述所见、不写诊断结论）
CAPTION_1 = {
    'case001': '36颌面深大龋洞，洞内大量软化牙本质及食物嵌塞。',
    'case002': '11切端斜行冠折，腭侧断面中央可见针尖样红色露髓点。',
    'case003': '患牙根方颊侧牙龈可见瘘管口，周围龈色暗红。',
    'case004': '患侧面部/眶下区肿胀，皮肤张力高。',
    'case005': '36颌面及窝沟深龋，色黑褐，未见明显露髓点。',
    'case006': '多颗牙唇、颊侧牙颈部硬组织楔形缺损，伴牙龈退缩。',
    'case007': '36颌面深大龋洞，腐质填塞、食物嵌塞。',
    'case008': '牙面碘酊染色后，可见一条沿牙尖斜行走行的着色裂纹。',
    'case009': '上颌前牙腭侧釉质光滑杯状缺损、牙本质暴露，边缘光滑无龋洞。',
    'case011': '多颗后牙咬合面牙尖磨平、牙本质暴露形成磨耗小面。',
    'case012': '邻间隙龈乳头鲜红、肿胀圆钝，可见食物嵌塞。',
}
CAPTION_2 = {
    'case001': '36颌面深龋透射影达髓腔，根尖周未见明显异常。',
    'case002': '11冠折线累及髓腔，根尖孔未完全闭合，未见根折。',
    'case003': '患牙充填体下继发龋达髓腔，根尖区类圆形透射影、边界清楚。',
    'case004': '患牙根尖周牙周膜间隙增宽、根尖区弥散性低密度影。',
    'case005': '龋损透射影近髓但未穿通，根尖周骨质正常。',
    'case007': '龋坏透射影达髓腔，根尖周基本正常。',
    'case013': '冠状位影像示一侧上颌窦黏膜明显增厚、窦腔密度增高，对侧清亮。',
}

# _1 临床照挂到哪个/哪些检查项。默认「视诊」；覆盖项见下。
# case008 隐裂：视诊本就"看不出洞"，染色裂纹只在「染色/透照」时揭示，故不挂视诊。
VISUAL_ITEMS_OVERRIDE = {
    'case008': ['染色/透照'],
}

IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'static', 'images', IMG_SUBDIR)


def _exists(fname):
    return os.path.exists(os.path.join(IMAGES_DIR, fname))


def photos_for(case_id, item):
    """返回该病例在某检查项应显示的照片列表 [{file,url,label,caption}]，无则 []。"""
    out = []
    visual_items = VISUAL_ITEMS_OVERRIDE.get(case_id, ['视诊'])
    if item in visual_items:
        f = f'{case_id}_1.jpg'
        if _exists(f):
            out.append({'file': f'{IMG_SUBDIR}/{f}',
                        'url': f'/images/{IMG_SUBDIR}/{f}',
                        'label': '口内照', 'caption': CAPTION_1.get(case_id, '')})
    if item == 'X线片判读':
        f = f'{case_id}_2.jpg'
        if _exists(f):
            out.append({'file': f'{IMG_SUBDIR}/{f}',
                        'url': f'/images/{IMG_SUBDIR}/{f}',
                        'label': '根尖X线片', 'caption': CAPTION_2.get(case_id, '')})
    return out
