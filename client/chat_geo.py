"""悄匿社交 —— IP 属地解析。

属地由**服务端根据 UDP 报文的来源地址**判定（客户端无法伪造、也无法隐藏）：
- 回环地址        → 「本机」
- 私有/链路本地地址 → 「局域网 192.168.x.x」（局域网内网段，无需联网）
- 公网地址        → 依次尝试多个在线接口，尽量解析到**市**（有区/县就更细）
                    全都失败时降级为「公网」

为什么要多个数据源：单一数据源（尤其境外数据源）解析国内 IP 时经常只给到省级、
甚至给错城市。这里按「谁的粒度更细就用谁」来挑结果：
先问对国内 IP 更准的接口，如果只拿到省，就继续问下一个，直到拿到市为止。

说明：局域网里的私有 IP 在公网上没有归属地，所以内网只能显示到网段；
只有当服务端部署在公网、客户端从公网接入时，才会显示真实的省市。
"""
import ipaddress
import json
import threading
import time
import urllib.parse
import urllib.request

TIMEOUT_CN = 1.5        # 国内接口超时
TIMEOUT_INTL = 2.2      # 国外接口超时
LOOKUP_BUDGET = 3.5     # 一次解析最多等多久（几个数据源并行，谁先给出够细的结果就用谁）
TTL_OK = 24 * 3600      # 解析成功缓存 24 小时
TTL_FAIL = 300          # 失败缓存 5 分钟，避免反复卡顿
RETRY_BUDGET = 8.0      # 后台重试用的更长预算（反正是异步的）

# 已经有「省 + 市」就够好了，不用再问后面的源
GOOD_ENOUGH = 4

_cache = {}
_lock = threading.Lock()
_last_probe = {}        # 最近一次解析里，每个数据源的结果（排查用）


# ---------------------------------------------------------------- 地址分类
def local_region(ip):
    """不发网络请求就能给出的属地；公网地址返回 None 表示需要在线解析。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return '未知'
    if addr.is_loopback:
        return '本机'
    if addr.is_link_local:
        return '局域网'
    if addr.is_private:
        parts = (ip or '').split('.')
        if len(parts) == 4:
            return f'局域网 {parts[0]}.{parts[1]}.{parts[2]}.x'
        return '局域网'
    return None


# ---------------------------------------------------------------- 名称归一
_SUFFIXES = ('特别行政区', '维吾尔自治区', '壮族自治区', '回族自治区', '自治区',
             '自治州', '省', '市', '地区', '盟')

# 国外数据源会给拼音/英文（"Fujian Sheng"、"Xiamen"），把常见的翻回中文，
# 免得只在英文源有结果时界面上出现半中半英。键统一小写、去掉空格和 Sheng/Shi 后缀。
_EN2CN = {
    # ---- 中国省级 ----
    'beijing': '北京', 'tianjin': '天津', 'shanghai': '上海', 'chongqing': '重庆',
    'hebei': '河北', 'shanxi': '山西', 'liaoning': '辽宁', 'jilin': '吉林',
    'heilongjiang': '黑龙江', 'jiangsu': '江苏', 'zhejiang': '浙江', 'anhui': '安徽',
    'fujian': '福建', 'jiangxi': '江西', 'shandong': '山东', 'henan': '河南',
    'hubei': '湖北', 'hunan': '湖南', 'guangdong': '广东', 'hainan': '海南',
    'sichuan': '四川', 'guizhou': '贵州', 'yunnan': '云南', 'shaanxi': '陕西',
    'gansu': '甘肃', 'qinghai': '青海', 'taiwan': '台湾',
    'inner mongolia': '内蒙古', 'neimenggu': '内蒙古', 'nei mongol': '内蒙古',
    'guangxi': '广西', 'xizang': '西藏', 'tibet': '西藏', 'ningxia': '宁夏',
    'xinjiang': '新疆', 'hong kong': '香港', 'hongkong': '香港',
    'macau': '澳门', 'macao': '澳门',
    # ---- 中国城市 ----
    'xiamen': '厦门', 'fuzhou': '福州', 'quanzhou': '泉州', 'zhangzhou': '漳州',
    'guangzhou': '广州', 'shenzhen': '深圳', 'dongguan': '东莞', 'foshan': '佛山',
    'zhuhai': '珠海', 'shantou': '汕头', 'hangzhou': '杭州', 'ningbo': '宁波',
    'wenzhou': '温州', 'nanjing': '南京', 'suzhou': '苏州', 'wuxi': '无锡',
    'xuzhou': '徐州', 'chengdu': '成都', 'mianyang': '绵阳', 'wuhan': '武汉',
    'changsha': '长沙', 'zhengzhou': '郑州', 'jinan': '济南', 'qingdao': '青岛',
    'yantai': '烟台', 'hefei': '合肥', 'nanchang': '南昌', 'shenyang': '沈阳',
    'dalian': '大连', 'harbin': '哈尔滨', 'changchun': '长春', 'kunming': '昆明',
    'guiyang': '贵阳', 'nanning': '南宁', 'haikou': '海口', 'sanya': '三亚',
    'lanzhou': '兰州', 'xian': '西安', 'taiyuan': '太原', 'shijiazhuang': '石家庄',
    'urumqi': '乌鲁木齐', 'hohhot': '呼和浩特', 'yinchuan': '银川', 'xining': '西宁',
    'lhasa': '拉萨', 'huizhou': '惠州', 'zhongshan': '中山', 'jiangmen': '江门',
    # 自治区/省份的英文别名（ipinfo 之类会写成 "Xinjiang Uygur"）
    'xinjiang uygur': '新疆', 'xinjiang uyghur': '新疆', 'guangxi zhuang': '广西',
    'ningxia hui': '宁夏', 'xizang tibet': '西藏', 'inner mongolian': '内蒙古',
    'guangxi zhuang autonomous region': '广西', 'tibet autonomous': '西藏',
    'putian': '莆田', 'sanming': '三明', 'nanping': '南平', 'longyan': '龙岩',
    'ningde': '宁德', 'shangrao': '上饶', 'ganzhou': '赣州', 'jiujiang': '九江',
    'tangshan': '唐山', 'baoding': '保定', 'langfang': '廊坊', 'handan': '邯郸',
    'luoyang': '洛阳', 'kaifeng': '开封', 'linyi': '临沂', 'weifang': '潍坊',
    'zibo': '淄博', 'changzhou': '常州', 'nantong': '南通', 'yangzhou': '扬州',
    'zhenjiang': '镇江', 'taizhou': '台州', 'shaoxing': '绍兴', 'jiaxing': '嘉兴',
    'jinhua': '金华', 'huzhou': '湖州', 'lishui': '丽水', 'quzhou': '衢州',
    'zhoushan': '舟山', 'fuyang': '阜阳', 'wuhu': '芜湖', 'bengbu': '蚌埠',
    'anqing': '安庆', 'maanshan': '马鞍山', 'zhuzhou': '株洲', 'xiangtan': '湘潭',
    'hengyang': '衡阳', 'yueyang': '岳阳', 'changde': '常德', 'yichang': '宜昌',
    'xiangyang': '襄阳', 'jingzhou': '荆州', 'shiyan': '十堰', 'zhuhai city': '珠海',
    'zhuhai guangdong': '珠海', 'guilin': '桂林', 'liuzhou': '柳州', 'wuzhou': '梧州',
    'beihai': '北海', 'zhanjiang': '湛江', 'maoming': '茂名', 'zhaoqing': '肇庆',
    'meizhou': '梅州', 'shanwei': '汕尾', 'heyuan': '河源', 'yangjiang': '阳江',
    'qingyuan': '清远', 'chaozhou': '潮州', 'jieyang': '揭阳', 'yunfu': '云浮',
    'shaoguan': '韶关', 'nanyang': '南阳', 'xinyang': '信阳', 'zhoukou': '周口',
    'shangqiu': '商丘', 'pingdingshan': '平顶山', 'anyang': '安阳', 'xinxiang': '新乡',
    'jiaozuo': '焦作', 'xuchang': '许昌', 'zhumadian': '驻马店', 'dezhou': '德州',
    'liaocheng': '聊城', 'heze': '菏泽', 'jining': '济宁', 'taian': '泰安',
    'rizhao': '日照', 'weihai': '威海', 'zaozhuang': '枣庄', 'binzhou': '滨州',
    'datong': '大同', 'yangquan': '阳泉', 'changzhi': '长治', 'jincheng': '晋城',
    'yuncheng': '运城', 'linfen': '临汾', 'anshan': '鞍山', 'fushun': '抚顺',
    'benxi': '本溪', 'dandong': '丹东', 'jinzhou': '锦州', 'yingkou': '营口',
    'panjin': '盘锦', 'dalian city': '大连', 'qiqihar': '齐齐哈尔', 'daqing': '大庆',
    'mudanjiang': '牡丹江', 'jiamusi': '佳木斯', 'baotou': '包头', 'ordos': '鄂尔多斯',
    'yulin': '榆林', 'baoji': '宝鸡', 'xianyang': '咸阳', 'weinan': '渭南',
    'hanzhong': '汉中', 'ankang': '安康', 'tianshui': '天水', 'jiayuguan': '嘉峪关',
    'kelamayi': '克拉玛依', 'kashi': '喀什', 'ili': '伊犁', 'haixi': '海西',
    'liangshan': '凉山', 'zunyi': '遵义', 'qujing': '曲靖', 'dali': '大理',
    'lijiang': '丽江', 'honghe': '红河', 'wenshan': '文山', 'qiandongnan': '黔东南',
    # ---- 常见国家/地区 ----
    'china': '中国', 'united states': '美国', 'usa': '美国', 'america': '美国',
    'japan': '日本', 'south korea': '韩国', 'korea': '韩国', 'north korea': '朝鲜',
    'singapore': '新加坡', 'malaysia': '马来西亚', 'thailand': '泰国',
    'vietnam': '越南', 'philippines': '菲律宾', 'indonesia': '印度尼西亚',
    'india': '印度', 'pakistan': '巴基斯坦', 'bangladesh': '孟加拉国',
    'russia': '俄罗斯', 'ukraine': '乌克兰', 'belarus': '白俄罗斯',
    'kazakhstan': '哈萨克斯坦', 'mongolia': '蒙古', 'nepal': '尼泊尔',
    'myanmar': '缅甸', 'burma': '缅甸', 'cambodia': '柬埔寨', 'laos': '老挝',
    'brunei': '文莱', 'sri lanka': '斯里兰卡', 'maldives': '马尔代夫',
    'united kingdom': '英国', 'uk': '英国', 'england': '英国', 'britain': '英国',
    'ireland': '爱尔兰', 'france': '法国', 'germany': '德国', 'italy': '意大利',
    'spain': '西班牙', 'portugal': '葡萄牙', 'netherlands': '荷兰',
    'holland': '荷兰', 'belgium': '比利时', 'switzerland': '瑞士',
    'austria': '奥地利', 'sweden': '瑞典', 'norway': '挪威', 'denmark': '丹麦',
    'finland': '芬兰', 'iceland': '冰岛', 'poland': '波兰', 'czech': '捷克',
    'czechia': '捷克', 'hungary': '匈牙利', 'romania': '罗马尼亚',
    'bulgaria': '保加利亚', 'greece': '希腊', 'turkey': '土耳其',
    'canada': '加拿大', 'mexico': '墨西哥', 'brazil': '巴西', 'argentina': '阿根廷',
    'chile': '智利', 'peru': '秘鲁', 'colombia': '哥伦比亚', 'venezuela': '委内瑞拉',
    'australia': '澳大利亚', 'new zealand': '新西兰', 'egypt': '埃及',
    'south africa': '南非', 'nigeria': '尼日利亚', 'kenya': '肯尼亚',
    'ethiopia': '埃塞俄比亚', 'morocco': '摩洛哥', 'israel': '以色列',
    'saudi arabia': '沙特阿拉伯', 'united arab emirates': '阿联酋',
    'uae': '阿联酋', 'qatar': '卡塔尔', 'iran': '伊朗', 'iraq': '伊拉克',
    'syria': '叙利亚', 'jordan': '约旦', 'kuwait': '科威特', 'oman': '阿曼',
    'georgia': '格鲁吉亚', 'armenia': '亚美尼亚', 'azerbaijan': '阿塞拜疆',
    'uzbekistan': '乌兹别克斯坦', 'kyrgyzstan': '吉尔吉斯斯坦',
    'tajikistan': '塔吉克斯坦', 'turkmenistan': '土库曼斯坦',
    'afghanistan': '阿富汗', 'cyprus': '塞浦路斯', 'croatia': '克罗地亚',
    'serbia': '塞尔维亚', 'slovenia': '斯洛文尼亚', 'slovakia': '斯洛伐克',
    'lithuania': '立陶宛', 'latvia': '拉脱维亚', 'estonia': '爱沙尼亚',
    'moldova': '摩尔多瓦', 'albania': '阿尔巴尼亚', 'luxembourg': '卢森堡',
    'monaco': '摩纳哥', 'malta': '马耳他', 'cuba': '古巴', 'jamaica': '牙买加',
    'panama': '巴拿马', 'costa rica': '哥斯达黎加', 'uruguay': '乌拉圭',
    'paraguay': '巴拉圭', 'bolivia': '玻利维亚', 'ecuador': '厄瓜多尔',
    'fiji': '斐济', 'papua new guinea': '巴布亚新几内亚', 'tunisia': '突尼斯',
    'algeria': '阿尔及利亚', 'libya': '利比亚', 'sudan': '苏丹',
    'tanzania': '坦桑尼亚', 'uganda': '乌干达', 'ghana': '加纳',
    'senegal': '塞内加尔', 'zimbabwe': '津巴布韦', 'zambia': '赞比亚',
    'mozambique': '莫桑比克', 'angola': '安哥拉', 'cameroon': '喀麦隆',
    # ---- 常见境外城市 ----
    'tokyo': '东京', 'osaka': '大阪', 'kyoto': '京都', 'nagoya': '名古屋',
    'yokohama': '横滨', 'sapporo': '札幌', 'fukuoka': '福冈', 'kobe': '神户',
    'seoul': '首尔', 'busan': '釜山', 'incheon': '仁川', 'daegu': '大邱',
    'taipei': '台北', 'kaohsiung': '高雄', 'taichung': '台中',
    'hong kong island': '香港', 'kuala lumpur': '吉隆坡', 'penang': '槟城',
    'bangkok': '曼谷', 'chiang mai': '清迈', 'phuket': '普吉',
    'hanoi': '河内', 'ho chi minh city': '胡志明市', 'saigon': '胡志明市',
    'da nang': '岘港', 'manila': '马尼拉', 'cebu': '宿务',
    'jakarta': '雅加达', 'surabaya': '泗水', 'bali': '巴厘岛',
    'mumbai': '孟买', 'new delhi': '新德里', 'delhi': '德里', 'bangalore': '班加罗尔',
    'chennai': '金奈', 'kolkata': '加尔各答', 'hyderabad': '海得拉巴',
    'dubai': '迪拜', 'abu dhabi': '阿布扎比', 'doha': '多哈', 'riyadh': '利雅得',
    'tel aviv': '特拉维夫', 'istanbul': '伊斯坦布尔', 'moscow': '莫斯科',
    'saint petersburg': '圣彼得堡', 'st petersburg': '圣彼得堡',
    'london': '伦敦', 'manchester': '曼彻斯特', 'birmingham': '伯明翰',
    'edinburgh': '爱丁堡', 'dublin': '都柏林', 'paris': '巴黎', 'lyon': '里昂',
    'marseille': '马赛', 'nice': '尼斯', 'berlin': '柏林', 'munich': '慕尼黑',
    'frankfurt': '法兰克福', 'hamburg': '汉堡', 'cologne': '科隆',
    'amsterdam': '阿姆斯特丹', 'rotterdam': '鹿特丹', 'brussels': '布鲁塞尔',
    'zurich': '苏黎世', 'geneva': '日内瓦', 'vienna': '维也纳', 'rome': '罗马',
    'milan': '米兰', 'venice': '威尼斯', 'naples': '那不勒斯', 'madrid': '马德里',
    'barcelona': '巴塞罗那', 'lisbon': '里斯本', 'athens': '雅典',
    'stockholm': '斯德哥尔摩', 'oslo': '奥斯陆', 'copenhagen': '哥本哈根',
    'helsinki': '赫尔辛基', 'warsaw': '华沙', 'prague': '布拉格',
    'budapest': '布达佩斯', 'bucharest': '布加勒斯特', 'kyiv': '基辅',
    'kiev': '基辅', 'new york': '纽约', 'los angeles': '洛杉矶',
    'san francisco': '旧金山', 'seattle': '西雅图', 'chicago': '芝加哥',
    'boston': '波士顿', 'washington': '华盛顿', 'miami': '迈阿密',
    'dallas': '达拉斯', 'houston': '休斯顿', 'atlanta': '亚特兰大',
    'denver': '丹佛', 'phoenix': '凤凰城', 'las vegas': '拉斯维加斯',
    'portland': '波特兰', 'san diego': '圣迭戈', 'san jose': '圣何塞',
    'silicon valley': '硅谷', 'toronto': '多伦多', 'vancouver': '温哥华',
    'montreal': '蒙特利尔', 'ottawa': '渥太华', 'calgary': '卡尔加里',
    'mexico city': '墨西哥城', 'sao paulo': '圣保罗', 'rio de janeiro': '里约热内卢',
    'buenos aires': '布宜诺斯艾利斯', 'santiago': '圣地亚哥', 'lima': '利马',
    'bogota': '波哥大', 'sydney': '悉尼', 'melbourne': '墨尔本',
    'brisbane': '布里斯班', 'perth': '珀斯', 'auckland': '奥克兰',
    'wellington': '惠灵顿', 'cairo': '开罗', 'johannesburg': '约翰内斯堡',
    'cape town': '开普敦', 'nairobi': '内罗毕', 'lagos': '拉各斯',
    # 一些容易只出现首都名的国家/地区
    'ulaanbaatar': '乌兰巴托', 'astana': '阿斯塔纳', 'nur-sultan': '阿斯塔纳',
    'tashkent': '塔什干', 'bishkek': '比什凯克', 'dushanbe': '杜尚别',
    'ashgabat': '阿什哈巴德', 'baku': '巴库', 'yerevan': '埃里温',
    'tbilisi': '第比利斯', 'minsk': '明斯克', 'riga': '里加', 'vilnius': '维尔纽斯',
    'tallinn': '塔林', 'zagreb': '萨格勒布', 'belgrade': '贝尔格莱德',
    'sarajevo': '萨拉热窝', 'skopje': '斯科普里', 'tirana': '地拉那',
    'sofia': '索菲亚', 'bratislava': '布拉迪斯拉发', 'ljubljana': '卢布尔雅那',
    'reykjavik': '雷克雅未克', 'beirut': '贝鲁特', 'amman': '安曼',
    'tehran': '德黑兰', 'baghdad': '巴格达', 'karachi': '卡拉奇',
    'lahore': '拉合尔', 'islamabad': '伊斯兰堡', 'dhaka': '达卡',
    'colombo': '科伦坡', 'kathmandu': '加德满都', 'yangon': '仰光',
    'phnom penh': '金边', 'vientiane': '万象', 'bandar seri begawan': '斯里巴加湾',
    'auckland region': '奥克兰', 'canberra': '堪培拉', 'adelaide': '阿德莱德',
    'montreal quebec': '蒙特利尔',
    # ---- 常见州/省（境外） ----
    'california': '加利福尼亚', 'texas': '得克萨斯', 'florida': '佛罗里达',
    'new york state': '纽约州', 'washington state': '华盛顿州',
    'illinois': '伊利诺伊', 'massachusetts': '马萨诸塞', 'virginia': '弗吉尼亚',
    'new jersey': '新泽西', 'pennsylvania': '宾夕法尼亚', 'ohio': '俄亥俄',
    'michigan': '密歇根', 'georgia state': '佐治亚', 'arizona': '亚利桑那',
    'colorado': '科罗拉多', 'oregon': '俄勒冈', 'nevada': '内华达',
    'ontario': '安大略', 'quebec': '魁北克', 'british columbia': '不列颠哥伦比亚',
    'alberta': '阿尔伯塔', 'new south wales': '新南威尔士', 'victoria': '维多利亚',
    'queensland': '昆士兰', 'western australia': '西澳大利亚',
    'tokyo prefecture': '东京都', 'osaka prefecture': '大阪府',
    'bavaria': '巴伐利亚', 'baden-wurttemberg': '巴登-符腾堡',
    'provence-alpes-cote d\'azur': '普罗旺斯', 'catalonia': '加泰罗尼亚',
    'lombardy': '伦巴第', 'england uk': '英格兰', 'scotland': '苏格兰',
    'wales': '威尔士', 'northern ireland': '北爱尔兰',
}


def _norm_en(name):
    """英文地名归一：小写、去掉行政后缀、把 - _ . 逗号统一成空格。"""
    s = str(name or '').strip().lower()
    for suf in (' autonomous region', ' province', ' municipality', ' prefecture',
                ' region', ' state', ' sheng', ' shi', ' city', ' county'):
        if s.endswith(suf):
            s = s[:-len(suf)]
    for ch in ('-', '_', '.', ',', '(', ')', "'"):
        s = s.replace(ch, ' ')
    return ' '.join(s.split())


_EN2CN_NORM = {}
# 短键优先：'tokyo' 不能被 'tokyo prefecture' 归一后的同名键盖掉
for _k in sorted(_EN2CN, key=len):
    _EN2CN_NORM.setdefault(_norm_en(_k), _EN2CN[_k])


def cn_name(name):
    """把英文/拼音的省/州/城市名尽量转回中文（转不了就原样返回）。"""
    s = str(name or '').strip()
    if not s:
        return ''
    got = _EN2CN_NORM.get(_norm_en(s))
    return got or s


def short_name(name):
    """「福建省」→「福建」，「Xiamen」→「厦门」，去掉行政级别后缀/翻回中文。"""
    s = cn_name(name)
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[:-len(suf)]
    return s


def format_region(info):
    """把各接口的字段拼成展示用的属地串，尽量给到最细一级。"""
    if not info:
        return ''
    province = short_name(info.get('region'))
    city = short_name(info.get('city'))
    district = short_name(info.get('district'))
    parts = []
    for p in (province, city, district):
        if p and p not in parts:
            parts.append(p)
    if parts:
        return ' '.join(parts)
    # 连省市都没有，退而求其次给运营商（总比「公网」强）
    isp = str(info.get('isp') or '').strip()
    return isp


def precision(info):
    """粒度打分：有市 3 分、有省 1 分、有区县再 1 分。"""
    if not info:
        return -1
    s = 0
    if str(info.get('city') or '').strip():
        s += 3
    if str(info.get('region') or '').strip():
        s += 1
    if str(info.get('district') or '').strip():
        s += 1
    return s


# ---------------------------------------------------------------- 各数据源
def _get(url, timeout, encoding='utf-8'):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (QiaoNiSocial/1.1)',
        'Accept': 'application/json,text/plain,*/*',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, 'replace')


def fetch_pconline(ip):
    """太平洋电脑网：国内 IP 的城市级准确度最好，顺带给运营商。中文 GBK。"""
    url = ('https://whois.pconline.com.cn/ipJson.jsp?ip='
           + urllib.parse.quote(ip) + '&json=true')
    data = json.loads(_get(url, TIMEOUT_CN, 'gbk'))
    if not isinstance(data, dict) or data.get('err'):
        return None
    addr = str(data.get('addr') or '')
    isp = addr.rsplit(' ', 1)[-1].strip() if ' ' in addr else ''
    return {'country': '中国', 'region': data.get('pro'), 'city': data.get('city'),
            'district': data.get('region'), 'isp': isp}


def fetch_ip_api(ip):
    """ip-api.com：国际通用，国内 IP 有时只到省级，但也有 district 字段。"""
    url = ('http://ip-api.com/json/' + urllib.parse.quote(ip)
           + '?lang=zh-CN&fields=status,message,country,regionName,city,district,isp')
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or data.get('status') != 'success':
        return None
    return {'country': data.get('country'), 'region': data.get('regionName'),
            'city': data.get('city'), 'district': data.get('district'),
            'isp': data.get('isp')}


def fetch_ipwho(ip):
    """ipwho.is：中文名较全，作为最后兜底。"""
    url = 'https://ipwho.is/' + urllib.parse.quote(ip) + '?lang=zh'
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or not data.get('success'):
        return None
    conn = data.get('connection') or {}
    return {'country': data.get('country'), 'region': data.get('region'),
            'city': data.get('city'), 'district': data.get('district'),
            'isp': conn.get('isp') or conn.get('org')}


def fetch_ipwhois_app(ip):
    """ipwhois.app：也是中文友好，作为 ipwho.is 的备用。"""
    url = 'https://ipwhois.app/json/' + urllib.parse.quote(ip) + '?lang=zh'
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or not data.get('success'):
        return None
    return {'country': data.get('country'), 'region': data.get('region'),
            'city': data.get('city'), 'district': data.get('district'),
            'isp': data.get('isp') or data.get('org')}


def fetch_ipsb(ip):
    """api.ip.sb：全球可用，结果是英文（兜底用，总比「属地未知」强）。"""
    url = 'https://api.ip.sb/geoip/' + urllib.parse.quote(ip)
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or data.get('error'):
        return None
    return {'country': data.get('country'), 'region': data.get('region'),
            'city': data.get('city'), 'district': data.get('district'),
            'isp': data.get('isp') or data.get('organization')}


def fetch_ipinfo(ip):
    """ipinfo.io：英文，最后的兜底。"""
    url = 'https://ipinfo.io/' + urllib.parse.quote(ip) + '/json'
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or data.get('error'):
        return None
    return {'country': data.get('country'), 'region': data.get('region'),
            'city': data.get('city'), 'district': data.get('district'),
            'isp': data.get('org')}


# 顺序很重要：先用对国内 IP 最准的，粒度不够再往后问。
# 之所以放这么多源：服务器可能在某些地区/机房，某一家连不上是常事，
# 任何一家都不能是单点。
# 第三项 True = 这个源返回**中文**地名。结果打平时优先用中文源，
# 免得界面上冒出「Inner Mongolia」这种英文（用户明确要求一律显示中文）。
def fetch_vore(ip):
    """vore.top：国内常用，省市级较准（免 key）。"""
    url = 'https://api.vore.top/api/IPdata?ip=' + urllib.parse.quote(ip)
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or str(data.get('code')) not in ('200', '0'):
        return None
    info = data.get('ipdata') or {}
    ad = data.get('adcode') or {}
    prov = info.get('info1') or ad.get('p') or ''
    city = info.get('info2') or ad.get('c') or ''
    if not prov and not city:
        return None
    return {'country': info.get('info3') or '中国', 'region': prov, 'city': city,
            'isp': data.get('ipdata', {}).get('isp') or ''}


def fetch_useragentinfo(ip):
    """ip.useragentinfo.com：中文省市（免 key）。"""
    url = 'https://ip.useragentinfo.com/json?ip=' + urllib.parse.quote(ip)
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or int(data.get('code') or 0) != 200:
        return None
    return {'country': data.get('country') or '中国', 'region': data.get('province'),
            'city': data.get('city'), 'isp': data.get('isp') or ''}


def fetch_ipapi_co(ip):
    """ipapi.co：国际源，作为交叉验证（英文名，会被归一成中文）。"""
    url = 'https://ipapi.co/' + urllib.parse.quote(ip) + '/json/'
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict) or data.get('error'):
        return None
    return {'country': data.get('country_name'), 'region': data.get('region'),
            'city': data.get('city'), 'isp': data.get('org') or ''}


ALL_PROVIDERS = (
    ('pconline', fetch_pconline, True),          # 国内，省市级（默认只用它）
    ('vore', fetch_vore, True),
    ('useragentinfo', fetch_useragentinfo, True),
    ('ip-api', fetch_ip_api, True),
    ('ipwho', fetch_ipwho, True),
    ('ipwhois.app', fetch_ipwhois_app, True),
    ('ipapi.co', fetch_ipapi_co, False),
    ('ip.sb', fetch_ipsb, False),
    ('ipinfo', fetch_ipinfo, False),
)

# 默认**全部源一起投票**（9 个）：单源偶尔会超时或给出偏差，多源更稳。
# 判定规则见 _pick_best：省份多数派（≥2 票）→ 省内城市多数派 → 再取最细/中文源，
# 这样单个国际库把「运营商注册地」当属地（动不动北京、广州）也带不偏结果。
# 想限定源就在配置里写 "geo_sources": "pconline,ip.sb"（留空 = 全部）。
PROVIDERS = ALL_PROVIDERS


def set_sources(names):
    """按名字启用数据源，例如 set_sources('pconline') 或 'pconline,ip.sb'。"""
    global PROVIDERS
    if not names:
        PROVIDERS = ALL_PROVIDERS
        return [p[0] for p in PROVIDERS]
    want = [x.strip().lower() for x in str(names).replace('，', ',').split(',')
            if x.strip()]
    picked = tuple(p for p in ALL_PROVIDERS if p[0].lower() in want)
    PROVIDERS = picked or ALL_PROVIDERS
    return [p[0] for p in PROVIDERS]


def source_names():
    return [p[0] for p in PROVIDERS]


_custom = []      # 配置里指定的自定义接口（自己的反代 / 内网服务）


def set_custom_api(url_template):
    """配置里给一个自定义属地接口，形如 `http://proxy.example.com/geo?ip={ip}`。

    返回 JSON（键名和 ip-api 一致：country / region / city / district / isp）。
    机房出网受限、上面 6 个源都够不着时，可以自己搭个反代指过来。
    """
    global _custom
    tpl = (url_template or '').strip()
    _custom = [tpl] if '{ip}' in tpl else []
    return bool(_custom)


def fetch_custom(ip):
    tpl = _custom[0]
    url = tpl.replace('{ip}', urllib.parse.quote(ip))
    data = json.loads(_get(url, TIMEOUT_INTL))
    if not isinstance(data, dict):
        return None
    if data.get('status') == 'fail' or data.get('error'):
        return None
    return {'country': data.get('country'), 'region': data.get('region') or data.get('regionName'),
            'city': data.get('city'), 'district': data.get('district'),
            'isp': data.get('isp') or data.get('org') or data.get('organization')}


def all_providers():
    """实际使用的数据源列表（自定义接口排在最前面）。"""
    if _custom:
        return (('自定义', fetch_custom, False),) + PROVIDERS
    return PROVIDERS


def as_triples(provs):
    """把 (名字, 函数) 或 (名字, 函数, 是否中文) 统一成三元组。"""
    out = []
    for p in provs:
        if len(p) >= 3:
            out.append((p[0], p[1], bool(p[2])))
        else:
            out.append((p[0], p[1], True))     # 自定义/测试源默认当中文源
    return out


def probe(ip, budget=None):
    """逐个数据源问一遍，返回 [(名字, 耗时, 结果或错误文字), ...]。排查用。"""
    budget = LOOKUP_BUDGET if budget is None else budget
    rows = []
    lock = threading.Lock()
    provs = as_triples(all_providers())

    def work(name, fn, cn):
        t0 = time.time()
        try:
            info = fn(ip)
            err = '' if info else '没有结果'
        except Exception as e:
            info, err = None, f'{type(e).__name__}: {e}'
        with lock:
            rows.append((name, time.time() - t0, info, err))

    threads = [threading.Thread(target=work, args=(n, fn, cn), daemon=True)
               for n, fn, cn in provs]
    for t in threads:
        t.start()
    # 这是人工排查用的，等所有源都出结果（最多再多等 6 秒），
    # 不然「某个源超时了」会被误读成「这个源不存在」
    end = time.time() + budget + 6.0
    while time.time() < end and any(t.is_alive() for t in threads):
        time.sleep(0.05)
    order = {n: i for i, (n, _f, _c) in enumerate(provs)}
    with lock:
        rows.sort(key=lambda r: order.get(r[0], 99))
        done = {r[0] for r in rows}
    for n, _f, _c in provs:
        if n not in done:
            rows.append((n, float(budget + 6.0), None, '超时（还没返回）'))
    return rows


def last_probe():
    """最近一次 lookup 里每个源的情况（给日志用）。"""
    with _lock:
        return dict(_last_probe)


def lookup(ip, providers=None, budget=None):
    """并行问各个数据源，取**粒度最细**的结果。

    多源结果不一致时**按票数决定**（而不是死认第一个源）：
    各家 IP 库对同一个 IP 给出不同城市很常见，谁都可能错；少数服从多数更稳。
    打平时优先**返回中文的源**，再按数据源优先级（越靠前越可信）。
    """
    provs = as_triples(providers if providers is not None else all_providers())
    if not provs:
        return None
    budget = LOOKUP_BUDGET if budget is None else budget
    out = []
    notes = {}
    lock = threading.Lock()
    remain = [len(provs)]

    def work(idx, name, fn, cn):
        t0 = time.time()
        try:
            info = fn(ip)
            err = '' if info else '没有结果'
        except Exception as e:
            info, err = None, f'{type(e).__name__}: {e}'
        cost = time.time() - t0
        if info:
            info = dict(info, _cn=cn, _idx=idx, _src=name)
        with lock:
            notes[name] = {'ok': bool(info), 'cost': round(cost, 2), 'err': err}
            if info:
                out.append((idx, info))
            remain[0] -= 1

    threads = [threading.Thread(target=work, args=(i, n, fn, cn), daemon=True)
               for i, (n, fn, cn) in enumerate(provs)]
    for t in threads:
        t.start()
    start = time.time()
    end = start + budget
    while time.time() < end:
        with lock:
            if remain[0] <= 0:
                break
            # 已经有「多家库一致 + 粒度够细」的结果就不用等了。
            # 但必须等到**国内库**回过话：只凭境外库的一致结论提前收工，
            # 正是「移动出口 IP 被显示成北京」的老病根。
            cn_ok = any(i.get('_cn') for _x, i in out)
            if cn_ok and out and _best_agree(out) >= 2 \
                    and max(precision(i) for _x, i in out) >= GOOD_ENOUGH:
                break
        time.sleep(0.02)
    with lock:
        if providers is None:
            _last_probe.clear()
            _last_probe.update(notes)
        if not out:
            return None
        best = _pick_best(out)
    best.pop('_cn', None)
    best.pop('_idx', None)
    best.pop('_src', None)
    return best


def _key_of(info):
    """用来投票的键：省 + 市（有市看市，没市看省）。"""
    city = short_name(info.get('city'))
    prov = short_name(info.get('region'))
    return (prov, city) if city else (prov, '')


def _best_agree(out):
    """当前结果里，得票最高的那个键有几**家**库支持（同一家只算一票）。"""
    stat = _tally(out, _key_of)
    return max((len(v['fams']) for v in stat.values()), default=0)


# 同属一家的数据源（同一个上游库，结论必然一致）只算一票，
# 否则「一家库的两个域名」能伪造出多数派：实测 ipwho.is / ipwhois.app
# 对同一个移动 IP 都报「北京」，两票就能压过只出了一票的国内库。
_SAME_FAMILY = {
    'ipwhois.app': 'ipwho',
    'ipwho.is': 'ipwho',
    'ipwho': 'ipwho',
    'ipapi.co': 'ipapi',
    'ip-api': 'ipapi',
}
CN_WEIGHT = 2           # 国内库对国内 IP 明显更准，投票时权重至少翻倍
# 各家库对「中国移动/家宽出口 IP」的历史准确度（实测积累），只影响没有共识时的取舍：
#   pconline / ip.sb / ipinfo 对国内 IP 的省市基本靠谱；
#   ipwho.is(ipwhois.app) 常把移动出口登记成北京，ip-api 常登记成广东，权重最低。
_TRUST = {
    'pconline': 3,
    'ip.sb': 3,
    'ipinfo': 3,
    'vore': 2,
    'useragentinfo': 2,
    '自定义': 2,
    'ip-api': 1,
    'ipapi.co': 1,
    'ipwho': 1,
    'ipwhois.app': 1,
}

_last_vote = {}


def _family(info, idx):
    """这一票算哪一家的。没有来源名（单元测试直接喂结果）时按序号各算一家。"""
    name = str(info.get('_src') or '')
    return _SAME_FAMILY.get(name, name or f'#{idx}')


def _weight(info):
    """一票的份量：认识的库按准确度表，不认识的库按「是否返回中文」定。"""
    w = _TRUST.get(str(info.get('_src') or ''), 1)
    if info.get('_cn') and w < CN_WEIGHT:
        w = CN_WEIGHT
    return w


def _tally(pool, key_of):
    """按「家」去重 + 按准确度加权，统计每个键的票。

    返回 {键: {'fams': 几家, 'score': 分数, 'idx': 最靠前的源序号}}。
    """
    stat = {}
    for idx, info in pool:
        k = key_of(info)
        st = stat.setdefault(k, {'fams': set(), 'score': 0, 'idx': idx, 'prec': 0})
        fam = _family(info, idx)
        st['prec'] = max(st['prec'], precision(info))
        if fam in st['fams']:
            continue
        st['fams'].add(fam)
        st['score'] += _weight(info)
        st['idx'] = min(st['idx'], idx)
    return stat


def votes_text():
    """最近一次投票的明细（写日志用）：'福建 3/北京 1/广东 1'。"""
    if not _last_vote:
        return ''
    return '/'.join(f'{k or "?"} {len(v["fams"])}'
                    for k, v in sorted(_last_vote.items(),
                                       key=lambda kv: -len(kv[1]['fams'])))


def _pick_best(out):
    """三步定属地：**省份多数派 → 省内城市多数派 → 取最细/优先中文源**。

    投票规则（2026-09-27 重写，专门治「莫名其妙显示北京」）：
      1. 同一个上游库的多个域名只算一票（ipwho.is 与 ipwhois.app 是同一份数据）；
      2. 国内库权重 2、国外库权重 1；
      3. 先比「几家库一致」，再比加权分，最后才比数据源顺序。

    实测某移动出口 IP 的 9 个源：
      pconline=福建 厦门(中) · ip.sb=Fujian Xiamen · ipinfo=Fujian Fuzhou
      ipwho=Beijing · ipwhois.app=Beijing · ip-api=广东 广州
    北京那两票其实是同一家库，只能算一票；以前它们能凑成 2 票「多数派」，
    只要国内源慢一点或失败一次，用户看到的就是北京。
    """
    global _last_vote
    if not out:
        _last_vote = {}
        return {}

    def _prov(info):
        return short_name(info.get('region')) or ''

    def _city(info):
        return short_name(info.get('city')) or ''

    # 1) 省份多数派
    stat = _tally(out, _prov)
    _last_vote = stat
    best_prov = max(stat, key=lambda p: (len(stat[p]['fams']), stat[p]['score'],
                                         -stat[p]['idx'], 1 if p else 0))
    if len(stat[best_prov]['fams']) >= 2:
        # 两家以上不同的库都指向同一个省：这才是真共识
        pool = [(i, info) for i, info in out if _prov(info) == best_prov]
    else:
        # 没有两家库一致的省 —— 说明这 IP 各家分歧很大（移动/企业出口最常见）。
        # 这时按「哪家的结果更细、更可信」定一个省，而不是让先返回的那个源说了算。
        best_prov = max(stat, key=lambda p: (stat[p]['prec'], stat[p]['score'],
                                             len(stat[p]['fams']),
                                             -stat[p]['idx'], 1 if p else 0))
        pool = [(i, info) for i, info in out if _prov(info) == best_prov]

    # 2) 省内城市多数派（有共识才用，没共识就停在省份级）
    cv = _tally(pool, _city)
    cv.pop('', None)
    if cv:
        best_city = max(cv, key=lambda c: (len(cv[c]['fams']), cv[c]['score'],
                                           -cv[c]['idx']))
        if len(cv[best_city]['fams']) >= 2:
            narrow = [(i, info) for i, info in pool if _city(info) == best_city]
            if narrow:
                pool = narrow

    # 3) 在这个省（市）里挑最细、优先中文源的那条
    best = None
    for idx, info in pool:
        score = (precision(info), 1 if info.get('_cn') else 0, -idx)
        if best is None or score > best[0]:
            best = (score, info)
    return dict(best[1]) if best else {}


def failed_reason():
    """把最近一次解析失败的原因拼成一句话（写日志用）。"""
    p = last_probe()
    if not p:
        return '没有可用数据源'
    bad = [f'{n}({d["err"]})' for n, d in p.items() if not d['ok']]
    ok = [n for n, d in p.items() if d['ok']]
    if not bad:
        return '数据源都正常（没查到具体城市）' if not ok else '数据源正常'
    if ok:
        return '部分数据源失败：' + '、'.join(bad)
    return '所有数据源都没应答：' + '、'.join(bad)


def _fetch(ip, budget=None):
    info = lookup(ip, budget=budget)
    if not info:
        return None
    text = format_region(info)
    if text and text != '中国':
        return text
    return None


UNKNOWN = '属地未知'

_overrides = {}          # ip -> 手工指定的属地（覆盖一切在线解析结果）
_ov_lock = threading.Lock()


def set_overrides(mapping):
    """配置里手工指定的属地映射：{"1.2.3.4": "福建 厦门"}。

    IP 库再准也有错的时候（尤其是家宽/移动出口），给运营者一个直接改的口子。
    """
    global _overrides
    out = {}
    for k, v in (mapping or {}).items():
        k = str(k).strip()
        v = str(v).strip()
        if k and v:
            out[k] = v
    with _ov_lock:
        _overrides = out
    return len(out)


def set_override(ip, region):
    """运行时改一条（控制台 geoset 用）。region 为空表示删掉这条。"""
    ip = str(ip or '').strip()
    region = str(region or '').strip()
    with _ov_lock:
        if region:
            _overrides[ip] = region
        else:
            _overrides.pop(ip, None)
    return _overrides.get(ip, '')


def overrides():
    with _ov_lock:
        return dict(_overrides)


def region_for(ip, online=True, budget=None):
    """返回属地字符串。

    - 手工指定过的一律用指定的（最高优先级）
    - 回环 / 内网 → 「本机」「局域网 x.x.x.x」
    - 公网且解析成功 → 「福建 厦门」这样的具体属地
    - 公网但**解析失败** → 「属地未知」（而不是含混的「公网」，
      用户一看就知道是没查到，而不是觉得自己真在"公网"上）
    - online=False（服务端关掉了联网解析）→ 「公网」
    """
    with _ov_lock:
        fixed = _overrides.get(str(ip or '').strip())
    if fixed:
        return fixed
    local = local_region(ip)
    if local is not None:
        return local
    if not online:
        return '公网'
    now = time.time()
    with _lock:
        hit = _cache.get(ip)
    if hit and hit[1] > now:
        return hit[0]
    try:
        text = _fetch(ip, budget) or UNKNOWN
    except Exception:
        text = UNKNOWN
    # 只到省份级（说明各源没达成城市共识，含金量低）只缓存一小会儿，
    # 免得一个「北京」这种模糊/存疑的结果被钉住 24 小时（用户最直观的感受就是
    # 「属地一直是错的，重启也没用」）。
    if text in (UNKNOWN, '公网'):
        ttl = TTL_FAIL
    elif len(str(text).split()) < 2:
        ttl = TTL_FAIL * 6
    else:
        ttl = TTL_OK
    with _lock:
        _cache[ip] = (text, now + ttl)
    return text


def clear_ip(ip):
    """把某个 IP 的缓存丢掉（后台重试前调用）。"""
    with _lock:
        _cache.pop(ip, None)


def clear_cache():
    with _lock:
        _cache.clear()


# ------------------------------------------------------------ 本机对外 IP
# 服务端要显示「自己在哪」，就得先知道自己对外的公网 IP。这些都是只回显 IP
# 的纯文本接口，谁先答就用谁；国内、国外各放几个，避免某一家被墙就全废。
# 优先要 IPv4：玩家的客户端基本都是 IPv4 接入，显示 IPv6 对不上号。
IP_ECHO_V4 = (
    'https://ipv4.icanhazip.com',
    'https://ipv4.ipify.org',
    'https://ipv4.ident.me',
)
IP_ECHO_ANY = (
    'https://api.ipify.org',
    'https://ifconfig.me/ip',
    'https://ipinfo.io/ip',
)
IP_ECHO_BUDGET = 3.0

_self = {'ip': None, 'region': None}
_self_lock = threading.Lock()


def _public_ip_of(text):
    """把接口返回的文本变成一个公网 IP；不是公网地址就返回 ''。"""
    parts = (text or '').strip().split()
    if not parts:
        return ''
    try:
        addr = ipaddress.ip_address(parts[0])
    except Exception:
        return ''
    return str(addr) if addr.is_global else ''


def _race(urls, budget, want_v4):
    out = []
    lock = threading.Lock()
    remain = [len(urls)]

    def work(url):
        try:
            text = _get(url, TIMEOUT_INTL)
        except Exception:
            text = ''
        ip = _public_ip_of(text)
        with lock:
            if ip and (not want_v4 or ipaddress.ip_address(ip).version == 4):
                out.append(ip)
            remain[0] -= 1

    threads = [threading.Thread(target=work, args=(u,), daemon=True) for u in urls]
    for t in threads:
        t.start()
    end = time.time() + max(0.2, budget or 0)
    while time.time() < end:
        with lock:
            if out or remain[0] <= 0:
                break
        time.sleep(0.02)
    with lock:
        return out[0] if out else ''


def public_ip(budget=IP_ECHO_BUDGET):
    """并行问几个回显接口，拿到本机对外的公网 IP；失败返回 ''。

    先问只回 IPv4 的接口，拿不到再退回到通用接口（可能给 IPv6）。
    结果会缓存（进程内），服务端只需要在启动时问一次。
    """
    with _self_lock:
        if _self['ip']:
            return _self['ip']
    ip = _race(IP_ECHO_V4, (budget or 0) * 0.6, True)
    if not ip:
        ip = _race(IP_ECHO_ANY, (budget or 0) * 0.4, False)
    if ip:
        with _self_lock:
            _self['ip'] = ip
    return ip


def own_region(budget=IP_ECHO_BUDGET, online=True):
    """服务端自己的 (公网 IP, 属地)。解析不出来时返回 ('', '')。"""
    ip = public_ip(budget)
    if not ip:
        return '', ''
    with _self_lock:
        if _self['region']:
            return ip, _self['region']
    # 自己的属地是启动时问一次，不着急：预算给足，能问到具体城市才好看
    text = region_for(ip, online, budget=RETRY_BUDGET) if online else '公网'
    text = '' if text in ('公网', '内网', '本机', UNKNOWN) else text
    with _self_lock:
        _self['region'] = text
    return ip, text
