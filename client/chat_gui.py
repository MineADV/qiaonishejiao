"""悄匿社交 —— 图形界面客户端（customtkinter，Telegram 风格）。

功能：账号注册/登录、公共大厅、好友私聊、群聊、表情、@提及、
      拖拽发送、Ctrl+V 粘贴截图、图片放大预览、任意大小文件传输。
"""
import json
import gc
import os
import queue
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

import customtkinter as ctk

from chat_common import (
    fmt_time, now_ts, human_size, MAX_TEXT, FILE_INLINE_MAX,
    CONV_ROOM, CONV_AVATAR, conv_kind, conv_user, conv_group, conv_filename,
    normalize_host,
    NICK_MIN, NICK_MAX, PASSWORD_MIN, AVATAR_SIDE, AVATAR_MAX,
    GROUP_ANNOUNCE_MAX, GROUP_JOIN_MSG_MAX, MAX_GROUP_MEMBERS, MUTE_CHOICES,
    BAN_CHOICES, RECALL_WINDOW,
)
from chat_client_core import ChatClient
import chat_chess_ui as chess_ui
import chat_notify
import chat_secret
import chat_sound

PIL_ERR = ''
try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk, ImageGrab
    PIL_OK = True
except Exception as _e:
    PIL_OK = False
    PIL_ERR = repr(_e)
    Image = None

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_OK = True
except Exception:
    DND_OK = False
try:
    import windnd
    WINDND_OK = True
except Exception:
    WINDND_OK = False

ctk.set_default_color_theme('blue')

APP_NAME = '悄匿社交'
# 项目演示用：所有窗口标题统一在名称后面带上这串说明
APP_SUFFIX = '（信息学院 张伊博 项目演示用）'
APP_TITLE = APP_NAME + APP_SUFFIX

# ---------------- 外观主题 ----------------
# 每个主题给出整套界面颜色；apply_theme() 会把它们写进下面那些模块级变量。
# 所有控件创建时都读取这些变量，所以切换主题后重建界面即可整体换肤。
_DARK_CHIPS = ['#e17076', '#7bc862', '#e5ca77', '#65aadd',
               '#a695e7', '#ee7aae', '#6ec9cb', '#faa774']
_LIGHT_CHIPS = ['#b8433c', '#2e8b57', '#9a7410', '#2f7fe0',
                '#7d5fc4', '#bb3f6b', '#1a8f8f', '#b8621c']

THEMES = {
    # ---- 深色系 ----
    'midnight': {
        'label': '午夜蓝', 'mode': 'dark', 'chips': _DARK_CHIPS,
        'bg_app': '#0e1621', 'bg_panel': '#17212b', 'bg_header': '#242f3d',
        'bg_hover': '#202b36', 'bg_active': '#2b5278',
        'card': '#141c2e', 'card_border': '#2a3a52',
        'field_bg': '#0e1621', 'field_border': '#2b3a4a',
        'bubble_in': '#182533', 'bubble_out': '#2b5278', 'bubble_mention': '#3d3520',
        'accent': '#3390ec', 'accent_dim': '#2b6fb0', 'accent_flash': '#7db8f5',
        'on_accent': '#ffffff',
        'text': '#ffffff', 'text_soft': '#8fa3bd', 'text_dim': '#7f91a4',
        'region': '#6fa8dc', 'online': '#4dcd5e', 'warn': '#e5a54b', 'danger': '#e06c75',
        'mention_text': '#ffd479', 'pm_text': '#c792ea', 'me_text': '#a9d5a0',
        'scroll_btn': '#2b3a4a', 'scroll_hover': '#3a4a5a',
        'logo_top': (84, 74, 228), 'logo_bot': (128, 148, 202),
        'grad': ((14, 20, 44), (32, 26, 72), (10, 34, 56)),
        'blobs': ((70, 96, 220), (150, 70, 190), (36, 150, 170),
                  (210, 96, 130), (60, 120, 235)),
    },
    'forest': {
        'label': '森林绿', 'mode': 'dark', 'chips': _DARK_CHIPS,
        'bg_app': '#0d1a14', 'bg_panel': '#141f19', 'bg_header': '#1d2e24',
        'bg_hover': '#1a2a21', 'bg_active': '#2a5a3e',
        'card': '#12211a', 'card_border': '#27402f',
        'field_bg': '#0f1c16', 'field_border': '#27402f',
        'bubble_in': '#17281f', 'bubble_out': '#2a5a3e', 'bubble_mention': '#3a3a1c',
        'accent': '#35a45f', 'accent_dim': '#2a834c', 'accent_flash': '#86e0a9',
        'on_accent': '#ffffff',
        'text': '#eaf5ee', 'text_soft': '#8fae9c', 'text_dim': '#7d9a89',
        'region': '#7fc9a0', 'online': '#4ade80', 'warn': '#e0b341', 'danger': '#e06c75',
        'mention_text': '#ecd07a', 'pm_text': '#c9a0f0', 'me_text': '#9fe0b5',
        'scroll_btn': '#27402f', 'scroll_hover': '#35543e',
        'logo_top': (32, 140, 88), 'logo_bot': (110, 200, 150),
        'grad': ((10, 26, 19), (16, 44, 32), (12, 34, 44)),
        'blobs': ((40, 150, 95), (30, 170, 150), (90, 190, 110),
                  (180, 160, 70), (25, 110, 90)),
    },
    'violet': {
        'label': '霓虹紫', 'mode': 'dark', 'chips': _DARK_CHIPS,
        'bg_app': '#14101f', 'bg_panel': '#1c1729', 'bg_header': '#261f38',
        'bg_hover': '#231c33', 'bg_active': '#4a3a78',
        'card': '#1d1730', 'card_border': '#372c56',
        'field_bg': '#171226', 'field_border': '#372c56',
        'bubble_in': '#221b34', 'bubble_out': '#4a3a78', 'bubble_mention': '#3d3520',
        'accent': '#a06bff', 'accent_dim': '#8250e0', 'accent_flash': '#d0b3ff',
        'on_accent': '#ffffff',
        'text': '#f2eeff', 'text_soft': '#a99fc4', 'text_dim': '#948aad',
        'region': '#b9a3ff', 'online': '#4dcd5e', 'warn': '#e5a54b', 'danger': '#e06c75',
        'mention_text': '#ffd479', 'pm_text': '#7fd6ff', 'me_text': '#a9d5a0',
        'scroll_btn': '#372c56', 'scroll_hover': '#4a3a78',
        'logo_top': (128, 80, 230), 'logo_bot': (190, 140, 255),
        'grad': ((18, 12, 34), (40, 24, 72), (22, 18, 50)),
        'blobs': ((140, 80, 235), (90, 60, 220), (220, 90, 200),
                  (60, 140, 230), (180, 110, 240)),
    },
    'ocean': {
        'label': '深海青', 'mode': 'dark', 'chips': _DARK_CHIPS,
        'bg_app': '#081a20', 'bg_panel': '#0e2530', 'bg_header': '#14323f',
        'bg_hover': '#12303b', 'bg_active': '#1f5f70',
        'card': '#0b2029', 'card_border': '#1d4352',
        'field_bg': '#0a1d25', 'field_border': '#1d4352',
        'bubble_in': '#102a35', 'bubble_out': '#1f5f70', 'bubble_mention': '#3d3520',
        'accent': '#22a7c4', 'accent_dim': '#1a8399', 'accent_flash': '#7fe0f2',
        'on_accent': '#04212a',
        'text': '#e6f6fa', 'text_soft': '#8bb4c0', 'text_dim': '#7ba0ab',
        'region': '#6fd2e6', 'online': '#4dcd5e', 'warn': '#e5a54b', 'danger': '#e06c75',
        'mention_text': '#ffd479', 'pm_text': '#c792ea', 'me_text': '#a9d5a0',
        'scroll_btn': '#1d4352', 'scroll_hover': '#2a6070',
        'logo_top': (26, 150, 180), 'logo_bot': (90, 210, 225),
        'grad': ((6, 24, 30), (10, 44, 58), (8, 34, 46)),
        'blobs': ((30, 150, 175), (20, 110, 160), (60, 180, 190),
                  (110, 90, 200), (25, 170, 145)),
    },
    # ---- 浅色系 ----
    'light': {
        'label': '清透白', 'mode': 'light', 'chips': _LIGHT_CHIPS,
        'bg_app': '#eef1f6', 'bg_panel': '#ffffff', 'bg_header': '#f5f8fc',
        'bg_hover': '#e7ecf5', 'bg_active': '#d3e5ff',
        'card': '#ffffff', 'card_border': '#d8e0ec',
        'field_bg': '#f4f7fb', 'field_border': '#d3dce8',
        'bubble_in': '#ffffff', 'bubble_out': '#cfe3ff', 'bubble_mention': '#fff2c9',
        'accent': '#2f7fe0', 'accent_dim': '#2268bd', 'accent_flash': '#a9cdf7',
        'on_accent': '#ffffff',
        'text': '#16202c', 'text_soft': '#61708a', 'text_dim': '#7b8798',
        'region': '#2f7fe0', 'online': '#1e9e63', 'warn': '#b07314', 'danger': '#d3453f',
        'mention_text': '#8f6100', 'pm_text': '#8a54c8', 'me_text': '#2f7a4f',
        'scroll_btn': '#c9d4e2', 'scroll_hover': '#b3c1d4',
        'logo_top': (47, 127, 224), 'logo_bot': (120, 170, 240),
        'grad': ((238, 242, 248), (222, 232, 248), (234, 240, 246)),
        'blobs': ((150, 180, 240), (200, 170, 235), (140, 210, 215),
                  (240, 175, 195), (160, 190, 245)),
    },
    'sunset': {
        'label': '暖阳橙', 'mode': 'light', 'chips': _LIGHT_CHIPS,
        'bg_app': '#fdf5ee', 'bg_panel': '#ffffff', 'bg_header': '#fff3e8',
        'bg_hover': '#f8e8da', 'bg_active': '#ffd9b8',
        'card': '#ffffff', 'card_border': '#f0dcc8',
        'field_bg': '#fdf7f1', 'field_border': '#ecd6c0',
        'bubble_in': '#ffffff', 'bubble_out': '#ffe0c2', 'bubble_mention': '#fff0c2',
        'accent': '#e8722c', 'accent_dim': '#c65a1c', 'accent_flash': '#ffb877',
        'on_accent': '#ffffff',
        'text': '#35251a', 'text_soft': '#8a7566', 'text_dim': '#9a8878',
        'region': '#d2621f', 'online': '#2f9e63', 'warn': '#b8791a', 'danger': '#d64545',
        'mention_text': '#a06a00', 'pm_text': '#9a5cc4', 'me_text': '#2f7a4f',
        'scroll_btn': '#e8d3bf', 'scroll_hover': '#d8bfa6',
        'logo_top': (232, 114, 44), 'logo_bot': (250, 170, 90),
        'grad': ((253, 245, 238), (255, 232, 214), (252, 242, 232)),
        'blobs': ((250, 190, 140), (255, 205, 150), (245, 160, 140),
                  (255, 220, 170), (240, 175, 120)),
    },
    'paper': {
        'label': '羊皮纸', 'mode': 'light', 'chips': _LIGHT_CHIPS,
        'bg_app': '#f5f1e6', 'bg_panel': '#fffdf7', 'bg_header': '#efe9d9',
        'bg_hover': '#eae3d2', 'bg_active': '#ddceac',
        'card': '#fffdf7', 'card_border': '#e0d6be',
        'field_bg': '#faf6ec', 'field_border': '#ddd2b8',
        'bubble_in': '#fffdf7', 'bubble_out': '#e8ddc0', 'bubble_mention': '#f5e6b4',
        'accent': '#8a6d3b', 'accent_dim': '#6f5730', 'accent_flash': '#c8a86a',
        'on_accent': '#ffffff',
        'text': '#3a3226', 'text_soft': '#7d7160', 'text_dim': '#8c8271',
        'region': '#8a6d3b', 'online': '#4a8a5c', 'warn': '#a8791c', 'danger': '#b5453c',
        'mention_text': '#7d5800', 'pm_text': '#7d5fa8', 'me_text': '#3f7a52',
        'scroll_btn': '#ddd2b8', 'scroll_hover': '#c9bb9c',
        'logo_top': (138, 109, 59), 'logo_bot': (190, 160, 100),
        'grad': ((245, 241, 230), (238, 230, 210), (242, 236, 224)),
        'blobs': ((225, 205, 160), (210, 190, 150), (235, 215, 175),
                  (200, 180, 140), (230, 200, 165)),
    },
}

THEME_ORDER = list(THEMES.keys())
THEME_LABELS = {k: THEMES[k]['label'] for k in THEME_ORDER}
LABEL_TO_THEME = {v: k for k, v in THEME_LABELS.items()}
DEFAULT_THEME = 'midnight'

# 下面这些是「当前主题」的颜色，被所有界面代码直接引用
BG_APP = BG_PANEL = BG_HEADER = BG_HOVER = BG_ACTIVE = '#000000'
CARD = CARD_BORDER = FIELD_BG = FIELD_BORDER = '#000000'
BUBBLE_IN = BUBBLE_OUT = BUBBLE_MENTION = '#000000'
ACCENT = ACCENT_DIM = ACCENT_FLASH = ON_ACCENT = '#000000'
TEXT = TEXT_SOFT = TEXT_DIM = '#ffffff'
REGION = ONLINE = WARN = DANGER = DANGER_DIM = '#000000'
OK_GREEN = OK_GREEN_DIM = NO_RED = NO_RED_DIM = '#000000'
MENTION_TEXT = PM_TEXT = ME_TEXT = '#000000'
SCROLL_BTN = SCROLL_HOVER = '#000000'
LOGO_TOP = LOGO_BOT = (0, 0, 0)
GRAD = ((0, 0, 0), (0, 0, 0), (0, 0, 0))
BLOB_COLORS = ()
NAME_COLORS = list(_DARK_CHIPS)
AVATAR_COLORS = NAME_COLORS
CURRENT_THEME = DEFAULT_THEME


def _shade(hex_color, factor):
    """把颜色调暗一点（factor < 1）或调亮一点（factor > 1）。"""
    try:
        h = str(hex_color).lstrip('#')
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        if factor <= 1:
            r, g, b = (int(v * factor) for v in (r, g, b))
        else:
            r, g, b = (int(v + (255 - v) * (factor - 1)) for v in (r, g, b))
        return '#%02x%02x%02x' % tuple(max(0, min(255, v)) for v in (r, g, b))
    except Exception:
        return hex_color


def apply_theme(key):
    """把主题颜色写进模块级变量（新创建的控件即使用新配色）。"""
    global BG_APP, BG_PANEL, BG_HEADER, BG_HOVER, BG_ACTIVE
    global CARD, CARD_BORDER, FIELD_BG, FIELD_BORDER
    global BUBBLE_IN, BUBBLE_OUT, BUBBLE_MENTION
    global ACCENT, ACCENT_DIM, ACCENT_FLASH, ON_ACCENT
    global TEXT, TEXT_SOFT, TEXT_DIM
    global REGION, ONLINE, WARN, DANGER, DANGER_DIM
    global OK_GREEN, OK_GREEN_DIM, NO_RED, NO_RED_DIM
    global MENTION_TEXT, PM_TEXT, ME_TEXT
    global SCROLL_BTN, SCROLL_HOVER
    global LOGO_TOP, LOGO_BOT, GRAD, BLOB_COLORS
    global NAME_COLORS, AVATAR_COLORS, CURRENT_THEME

    if key not in THEMES:
        key = DEFAULT_THEME
    t = THEMES[key]
    BG_APP = t['bg_app']
    BG_PANEL = t['bg_panel']
    BG_HEADER = t['bg_header']
    BG_HOVER = t['bg_hover']
    BG_ACTIVE = t['bg_active']
    CARD = t['card']
    CARD_BORDER = t['card_border']
    FIELD_BG = t['field_bg']
    FIELD_BORDER = t['field_border']
    BUBBLE_IN = t['bubble_in']
    BUBBLE_OUT = t['bubble_out']
    BUBBLE_MENTION = t['bubble_mention']
    ACCENT = t['accent']
    ACCENT_DIM = t['accent_dim']
    ACCENT_FLASH = t['accent_flash']
    ON_ACCENT = t['on_accent']
    TEXT = t['text']
    TEXT_SOFT = t['text_soft']
    TEXT_DIM = t['text_dim']
    REGION = t['region']
    ONLINE = t['online']
    WARN = t['warn']
    DANGER = t['danger']
    DANGER_DIM = _shade(t['danger'], 0.74)
    # 「同意（绿）/ 拒绝（红）」两颗按钮用的实心色：直接取主题里的在线绿和警示红，
    # 这样 7 套主题下都是协调的，也不会跑出主题配色之外。
    OK_GREEN = t['online']
    OK_GREEN_DIM = _shade(t['online'], 0.82)
    NO_RED = t['danger']
    NO_RED_DIM = _shade(t['danger'], 0.82)
    MENTION_TEXT = t['mention_text']
    PM_TEXT = t['pm_text']
    ME_TEXT = t['me_text']
    SCROLL_BTN = t['scroll_btn']
    SCROLL_HOVER = t['scroll_hover']
    LOGO_TOP = tuple(t['logo_top'])
    LOGO_BOT = tuple(t['logo_bot'])
    GRAD = tuple(tuple(c) for c in t['grad'])
    BLOB_COLORS = tuple(tuple(c) for c in t['blobs'])
    NAME_COLORS = list(t['chips'])
    AVATAR_COLORS = NAME_COLORS
    CURRENT_THEME = key
    try:
        ctk.set_appearance_mode(t['mode'])
    except Exception:
        pass
    return key


def client_config_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'client_config.json')


def log_path():
    """出错日志：跟 client_config.json 放一起（exe 同目录）。"""
    return os.path.join(os.path.dirname(os.path.abspath(client_config_path())),
                        'client_error.log')


def trace_path():
    return os.path.join(os.path.dirname(os.path.abspath(client_config_path())),
                        'client_trace.log')


def diag_path():
    """界面诊断日志（自动记录，最多留 400KB）：排查「重排重画/一片黑」用。"""
    return os.path.join(os.path.dirname(os.path.abspath(client_config_path())),
                        'client_diag.log')


def build_stamp():
    """这个客户端是什么时候的版本（用文件时间当版本号，排查「是不是旧程序」）。"""
    try:
        p = sys.executable if getattr(sys, 'frozen', False) else __file__
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(p)))
    except Exception:
        return '?'


def write_diag(line, cap=400 * 1024):
    """往诊断日志追加一行；超过上限就截掉前半段。任何异常都不影响主流程。"""
    try:
        p = diag_path()
        try:
            if os.path.getsize(p) > cap:
                with open(p, 'r', encoding='utf-8', errors='replace') as f:
                    tail = f.read()[-cap // 2:]
                with open(p, 'w', encoding='utf-8') as f:
                    f.write('……（前面的内容已省略）……\n' + tail)
        except OSError:
            pass
        write_log(p, line)
    except Exception:
        pass


# 设了环境变量 QIAONI_DEBUG=1 就记详细事件流水（排查用）
DEBUG_TRACE = str(os.environ.get('QIAONI_DEBUG', '')).strip().lower() not in (
    '', '0', 'false', 'no')


def write_log(path, line):
    """往日志文件追加一行（任何异常都不能影响主流程）。"""
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {line}\n')
    except Exception:
        pass


def load_client_config():
    try:
        with open(client_config_path(), 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_theme():
    key = load_client_config().get('theme')
    return key if key in THEMES else DEFAULT_THEME


def save_client_config(**updates):
    """把若干键合并写进 client_config.json（其它键原样保留）。

    值为 None 表示**删掉这个键**（比如用户取消「记住密码」）。
    """
    path = client_config_path()
    data = {}
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f) or {}
            if not isinstance(data, dict):
                data = {}
    except Exception:
        data = {}
    for k, v in updates.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def save_theme(key):
    return save_client_config(theme=key)


apply_theme(load_theme())

FONT = 'Microsoft YaHei UI'
EMOJI_FONT = 'Segoe UI Emoji'

MEMBER_ROWS_MAX = 150      # 右侧成员列表最多画多少行（大厅上限 200 人，防卡顿）
EVENTS_PER_TICK = 12       # 每个 tick 最多渲染多少条事件，防止消息爆发时卡住界面
RENDER_TAIL = 20           # 一个会话最多画多少条历史（实测 20 条切会话约 0.6s，
                           # 120 条要 8.7s —— Tk 的布局开销随条数超线性增长）
RENDER_FIRST = 2           # 分帧重绘时第一批至少画多少条（先让屏幕上有东西）
RENDER_CHUNK = 12          # 每帧最多画多少条
CHUNK_SECONDS = 0.012      # 每帧画消息最多占用多少秒：到点就把主线程交还出去
CHUNK_MIN = 1              # 每帧至少画这么多条（不然切得太碎，反而更慢）
IMG_VIEW_MARGIN = 1        # 可见区外再多渲染几屏图片（其余等滚到附近再加载）
BUBBLE_RADIUS = 14         # 气泡最终圆角
POP_FROM = 26              # 新气泡出现时的初始圆角（弹出动画的起点）
POP_FRAMES = ((15, 24, 1.42), (5, 18, 1.16), (0, 14, 1.0))   # (横向偏移, 圆角, 提亮系数)
POP_INTERVAL = 30          # 弹出动画帧间隔（毫秒）
POP_MAX = 3                # 同时最多几个气泡在弹（消息爆发时不做动画，保流畅）
PIN_GAPS = (0, 40, 120, 260)
SYNC_GAPS = (0, 60, 200, 450)   # 内容高度变化后校正滚动区高度的时刻（毫秒）   # 切会话/发消息后「贴底」的校正时刻（毫秒）
VEIL_MIN_SHOW = 0.18       # 加载遮罩最少显示多久（太快会「闪一下」，反而更难看）
VIEW_CACHE_MAX = 20        # 最多同时缓存几个会话的「已画好」界面（内存换速度）
PRELOAD_LIMIT = 20         # 空闲时提前画好多少个会话的界面（≤ VIEW_CACHE_MAX，避免刚画好就被挤掉）
PRELOAD_FIRST_GAP = 200    # 切进一个会话后，隔多久开始预加载（先让当前会话画完）
PRELOAD_GAP = 30           # 两次预加载分片之间的间隔（毫秒）
PRELOAD_FIRST = 2          # 预加载时第一片画多少条
PRELOAD_CHUNK = 4          # 预加载时每片最多画多少条
PRELOAD_SECONDS = 0.020    # 预加载每片最多占用多少秒（后台干活也不能让界面卡）
PRELOAD_IDLE = 0.5         # 你刚动过界面就等一会儿再预热（别和你的操作抢主线程）
RECONNECT_TRIES = 5        # 掉线后自动重连的次数（间隔 2/4/8/15/25 秒）
# 「自己发的消息，等它从服务端回显回来」的有效期（秒）。**必须用本机单调时钟**：
# 乐观回显盖的是本机时间，回显盖的是服务端时间，两端时钟只要有偏差，拿两个
# 时间戳相减就永远对不上 —— 私聊会出现两个一模一样的气泡。
ECHO_MATCH_WINDOW = 120.0

EMOJI_COLS = 16          # 表情面板每行几个（整版画成一张图后按坐标点选）

EMOJIS = [
    '😀', '😁', '😂', '🤣', '😊', '😍', '😘', '😎', '🤔', '🙄', '😴', '😢', '😭',
    '😡', '😅', '😇', '🤝', '👍', '👎', '👏', '🙏', '💪', '👀', '🎉', '🔥', '💯',
    '❤️', '💔', '⭐', '✨', '🌈', '☀️', '🌙', '☕', '🍺', '🍕', '🎁', '🎵', '📷',
    '📎', '✅', '❌', '❓', '❗', '🐱', '🐶', '🐼', '🚀', '⚽', '🏆', '💡',
]

HELP_TEXT = """可用命令：
/me <动作>     发送动作消息（仅公共大厅）
/users         刷新在线列表
/ping          查看网络延迟
/clear         清空当前会话显示
/quit          断开连接

小技巧：
· 直接「拖拽文件到窗口」即可发送
· 截图后按 Ctrl+V 直接发送
· 点击图片可放大预览
· 一条消息里 @昵称 可以提醒对方（公共大厅）"""


if DND_OK:
    class _Base(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class _Base(ctk.CTk):
        pass


class App(_Base):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry('1180x740')
        self.minsize(940, 660)
        self.configure(fg_color=BG_APP)
        self._paint_window_bg()

        self.client = None
        self.connected = False
        self.sound_on = True
        self.sound = chat_sound.SoundPlayer(True)
        self.notify = None            # 右下角通知（窗口建好后挂托盘图标）
        self._chess_seen_moves = {}   # gid -> 已见到的步数（判断新走子放音效）
        self._pending_echo = {}       # conv -> 已乐观显示、等服务端回显的消息
        self._quit_confirm_win = None  # 「还有棋局没下完」的退出确认框
        self._offline_bar = None      # 断线横幅
        self.members_on = True        # 右侧成员面板是否显示（用户可收起）
        # 排查用流水日志：环境变量 QIAONI_DEBUG=1，或在 client_config.json 里写
        # {"debug": true}，都会写到 exe 同目录的 client_trace.log
        self._trace_on = DEBUG_TRACE or bool(load_client_config().get('debug'))
        # 「省电模式」：client_config.json 里写 {"calm": true} 打开 —— 不预热、
        # 一个会话只画最近 8 条、不铺遮罩、不做弹出动画。给很卡的机器兜底用。
        self.calm = bool(load_client_config().get('calm'))
        write_diag(f'--- 客户端启动 build={build_stamp()} '
                   f'frozen={bool(getattr(sys, "frozen", False))} '
                   f'python={sys.version.split()[0]} 省电模式={self.calm} ---')
        self.mode = 'login'
        self.conv = ''                    # 空 = 还没选会话（右侧显示「请选择聊天会话」）
        self.msgs = {}                    # conv -> [消息]
        self._conv_rows = {}
        self._img_refs = []
        self._avatar_cache = {}
        self._file_rows = {}              # fid -> {'bubble','ph'}
        self._msg_rows = {}               # mid -> 消息行控件
        self._img_pending = {}            # fid -> 等着滚到眼前才画的图片
        self._views = {}                  # conv -> 已画好的视图（预加载）
        self._view_lru = []               # 最近用过的会话（末尾最新）
        self._current_view = None
        self._conv_rev = {}               # conv -> 内容改动次数（撤回等）
        self._preload_done = set()        # 这一轮已经提前画好的会话
        self._preload_token = 0
        self._preload_target = None       # 正在预加载哪个会话
        self._preload_msgs = None         # 剩下的消息（切片画）
        self._preloading = False
        self._conv_ids = []               # 侧栏里的会话清单（预加载用）
        self._pending_map_frame = None    # 在屏幕外画好、等着显示出来的消息区
        self._loading_frame = None        # 「正在打开…」占位
        self._veil = None                 # 加载遮罩（盖住没画完的区域）
        self._veil_token = 0
        self._veil_stop = None
        self._veil_until = 0.0            # 遮罩期间先别预热（把主线程让给重绘）
        self._was_unmapped = False        # 刚从「最小化/隐藏」回来
        self._messages_hidden = False     # 最小化时把消息区收起来了
        self._last_input = 0.0            # 最近一次键鼠操作（预加载避开这段时间）
        self._heal_at = {}                # conv -> 上次自愈时间（冷却用）
        self._heal_n = {}                 # conv -> 自愈次数（上限用）
        self._rebuild_at = {}             # conv -> 上次整块重绘时间（限速用）
        self._empty_view = None          # 「请选择聊天会话」占位
        self._map_retry = 0              # 画好但没挂上时的重试计数
        self._my_ip = ''                 # 服务端看到的我的来源 IP
        self._my_public_ip = ''          # 客户端自己探到的出口 IP
        self._my_region_local = ''       # 客户端自己解析出来的属地
        self._ui_queue = queue.Queue()
        self._paste_dir = os.path.join(tempfile.gettempdir(), 'qiaoni_paste')
        self._input_h = 42
        self._grow_pending = False
        self._pending_auth = False
        self._bg_base_w, self._bg_base_h = 320, 200
        self._bg_base = None
        self._bg_blobs = []
        self._bg_running = False
        self._bg_photo = None
        self._add_friend_win = None
        self._add_friend_send = None   # 加好友窗口里的「发送申请」入口（搜索结果也用）
        self._group_win = None         # 群资料窗口
        self._group_win_gid = None
        self._group_file_wait = set()  # 正在下载的群文件 fid
        self._admin_win = None         # 超级管理员控制台
        self._admin_tab = 'users'
        self._reconnecting = False     # 掉线自动重连中
        self._rec_attempt = 0
        self._auth_args = None         # (host, port, nick, pwd, mode)，重连用
        self._auth_cand = 0            # 多地址重试时用到第几个
        self._last_gc = time.time()
        self._search_box = None
        self.theme_key = CURRENT_THEME
        self._theme_vars = []
        self.chess_windows = {}      # gid -> ChessWindow（对局窗口）
        self._chal_win = None        # 约战弹窗
        self._toast_label = None

        self._build_login()
        self._prefill_login()          # 用上次登录过的地址/端口/昵称填好登录框
        self._build_chat()
        self._hook_scroll_events()     # 记录「用户自己滚了」，贴底时避开他
        if self._trace_on:
            self._trace(f'==== 启动 冻结={getattr(sys, "frozen", False)} '
                        f'exe={sys.executable} 主题={self.theme_key} ====')
        self.show_login()

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(60, self._poll)
        self._bind_global()
        self.after(60, self._init_notifier)
        self.after(60, self._fade_in_window)

    def report_callback_exception(self, exc, val, tb):
        """Tk 回调里抛异常时的统一出口。

        默认行为是把 traceback 打到 stderr —— 打包成 --windowed 的 exe 后
        根本没有控制台，于是「点了没反应」这种问题完全无从查起（删除好友按
        了没反应就是这么来的：回调里 NameError，被 Tk 悄悄吞了）。
        现在一律写进客户端目录的 client_error.log，并且界面上给个提示。
        """
        try:
            detail = ''.join(traceback.format_exception(exc, val, tb))
            write_log(log_path(), f'!! 界面回调异常：{val!r}\n{detail}')
        except Exception:
            pass
        try:
            self._toast(f'操作出错：{val}', WARN)
        except Exception:
            pass
        try:
            self._trace(f'回调异常 {val!r}')
        except Exception:
            pass

    # ================= 表情 =================
    @staticmethod
    def _emoji_font(px):
        for name in ('seguiemj.ttf', 'SegoeUIEmoji.ttf'):
            try:
                return ImageFont.truetype(name, px)
            except Exception:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _is_emoji_only(text):
        """整条消息是不是「只有表情」（这种就用大一点的表情字体画，更好看）。"""
        t = (text or '').strip()
        if not t or len(t) > 24:
            return False
        core = t.replace('\ufe0f', '').replace('\u200d', '')
        if not core:
            return False
        # 允许的：emoji、变体选择符、零宽连接符、空格
        for ch in core:
            o = ord(ch)
            if ch == ' ':
                continue
            if 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF \
                    or 0x1F1E6 <= o <= 0x1F1FF or o in (0x2764, 0x203C, 0x2049, 0x2122, 0x2139):
                continue
            return False
        return True

    # ================= 提示音 / 右下角通知 =================
    def _sound(self, kind):
        """放一个提示音（受「提示音」开关控制）。"""
        if not self.sound_on:
            return False
        try:
            self.sound.enabled = True
            return self.sound.play(kind)
        except Exception:
            return False

    def _init_notifier(self):
        """挂任务栏托盘图标；失败会自动退回屏幕右下角浮窗。"""
        try:
            self.notify = chat_notify.Notifier(
                self, tooltip=APP_TITLE, palette=self._chess_palette(),
                onclick=self._focus_app)
            self.notify.attach(self.winfo_id())
        except Exception:
            self.notify = None

    def _focus_app(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _popup(self, title, text, warning=False):
        """右下角弹一条系统通知；托盘不可用时自动用浮窗。"""
        try:
            if self.notify is not None:
                return self.notify.notify(title, text, warning=warning)
        except Exception:
            pass
        return ''

    def _notify_message(self, t, data, conv):
        """新消息的提示音 + 桌面通知。

        好友 / 群聊来消息一定有提示音；如果当前没停在这个会话，再弹一条右下角通知。
        被 @ 到时无论在哪个会话都提醒。
        """
        if t not in ('chat', 'me', 'file_msg') or data.get('history'):
            return
        me = (self.client.me if self.client else '') or ''
        sender = data.get('from') or ''
        if not sender or sender == me:
            return
        kind = conv_kind(conv)
        viewing = (conv == self.conv)
        mentioned = bool(me) and me in (data.get('mentions') or [])

        if mentioned:
            self._sound('mention')
        elif kind in ('friend', 'group'):
            self._sound('message')
        elif kind == 'room' and viewing:
            self._sound('message')
        else:
            return          # 大厅里别人聊天、而你又没在看大厅 → 不打扰

        if viewing:
            return          # 正看着这个会话，就不用再弹通知了
        if mentioned or kind in ('friend', 'group'):
            name = self._conv_display(conv)
            if kind == 'group':
                title = f'{name} · {sender}'
            else:
                title = sender
            if t == 'file_msg':
                label = {'image': '图片', 'video': '视频'}.get(data.get('kind'), '文件')
                text = f'[{label}] {data.get("name", "")}'
            else:
                text = data.get('text') or ''
            text = text.replace('\n', ' ')[:120]
            self._popup(title, text, warning=mentioned)

    def _conv_display(self, conv):
        try:
            return self._conv_title(conv)[0]
        except Exception:
            return '公共大厅'

    # ================= 登录界面 =================
    def _build_login(self):
        self.login = ctk.CTkFrame(self, fg_color=BG_APP, corner_radius=0)
        self._bg_canvas = tk.Canvas(self.login, highlightthickness=0, bd=0, bg=BG_APP)
        self._bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._bg_item = self._bg_canvas.create_image(0, 0, anchor='nw')

        card = ctk.CTkFrame(self.login, fg_color=CARD, corner_radius=22,
                            border_width=1, border_color=CARD_BORDER)
        card.pack(expand=True, ipadx=10, ipady=4)

        logo = self._logo_image(68)
        if logo is not None:
            self._logo_ref = logo
            ctk.CTkLabel(card, image=logo, text='', text_color=TEXT).pack(pady=(18, 4))
        ctk.CTkLabel(card, text=APP_NAME, font=ctk.CTkFont(family=FONT, size=27, weight='bold'),
                     text_color=TEXT).pack()
        ctk.CTkLabel(card, text=APP_SUFFIX, text_color=REGION,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(pady=(2, 0))
        # 把「构建时间」写在登录页上：方便确认你跑的是不是最新那一版
        ctk.CTkLabel(card, text=f'构建 {build_stamp()}（诊断日志：client_diag.log）',
                     text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=10)).pack(pady=(2, 0))
        ctk.CTkLabel(card, text='注册一个昵称，和朋友们安静地聊天',
                     text_color=TEXT_SOFT, font=ctk.CTkFont(family=FONT, size=13)).pack(pady=(6, 12))

        tabs = ctk.CTkFrame(card, fg_color=FIELD_BG, corner_radius=12)
        tabs.pack(fill='x', padx=34, pady=(0, 12))
        self.tab_login = ctk.CTkButton(tabs, text='登 录', height=36, corner_radius=10,
                                       fg_color=ACCENT, hover_color=ACCENT_DIM,
                                       text_color=ON_ACCENT,
                                       font=ctk.CTkFont(family=FONT, size=14, weight='bold'),
                                       command=lambda: self._set_mode('login'))
        self.tab_login.pack(side='left', expand=True, fill='x', padx=3, pady=3)
        self.tab_reg = ctk.CTkButton(tabs, text='注 册', height=36, corner_radius=10,
                                     fg_color='transparent', hover_color=BG_HOVER,
                                     text_color=TEXT_DIM,
                                     font=ctk.CTkFont(family=FONT, size=14),
                                     command=lambda: self._set_mode('register'))
        self.tab_reg.pack(side='left', expand=True, fill='x', padx=3, pady=3)

        # 服务器地址一行两列
        srv = ctk.CTkFrame(card, fg_color='transparent')
        srv.pack(fill='x', padx=34)
        ctk.CTkLabel(srv, text='服务器地址', anchor='w', text_color=TEXT_SOFT,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill='x')
        row = ctk.CTkFrame(srv, fg_color='transparent')
        row.pack(fill='x', pady=(3, 0))
        self.host_entry = ctk.CTkEntry(row, height=40, width=360, corner_radius=10,
                                       fg_color=FIELD_BG,
                                       border_color=FIELD_BORDER, border_width=1,
                                       placeholder_text='例如 192.168.1.5',
                                       text_color=TEXT,
                                       font=ctk.CTkFont(family=FONT, size=14))
        self.host_entry.pack(side='left', fill='x', expand=True)
        self.port_entry = ctk.CTkEntry(row, height=40, width=110, corner_radius=10,
                                       fg_color=FIELD_BG, border_color=FIELD_BORDER,
                                       border_width=1, placeholder_text='端口',
                                       text_color=TEXT,
                                       font=ctk.CTkFont(family=FONT, size=14))
        self.port_entry.pack(side='left', padx=(10, 0))

        self.nick_entry = self._field(card, '昵称', f'{NICK_MIN}-{NICK_MAX} 个字符，全服唯一')
        self.pwd_entry = self._field(card, '密码', f'至少 {PASSWORD_MIN} 位', show='•')

        # 「记住密码」：不勾就只记住地址/端口/昵称，密码每次手输；
        # 勾了才把密码用 DPAPI 加密后存到本机（换账号/换机器都解不开）。
        mem_row = ctk.CTkFrame(card, fg_color='transparent')
        mem_row.pack(fill='x', padx=34, pady=(2, 0))
        self.remember_var = tk.BooleanVar(value=False)
        self.remember_cb = ctk.CTkSwitch(
            mem_row, text='记住密码（下次自动登录）', variable=self.remember_var,
            onvalue=True, offvalue=False, command=self._on_remember_toggle,
            switch_width=40, switch_height=20, corner_radius=10,
            fg_color=BG_ACTIVE, progress_color=ACCENT,
            button_color=ON_ACCENT, button_hover_color=ON_ACCENT,
            text_color=TEXT_SOFT, font=ctk.CTkFont(family=FONT, size=11))
        self.remember_cb.pack(side='left')

        # 四个输入框都支持回车 → 直接登录 / 注册（不用点按钮）
        for entry in (self.host_entry, self.port_entry, self.nick_entry, self.pwd_entry):
            entry.bind('<Return>', self._on_login_return)
            entry.bind('<KP_Enter>', self._on_login_return)   # 小键盘回车

        self.login_status = ctk.CTkLabel(card, text='', text_color=DANGER, height=18,
                                         font=ctk.CTkFont(family=FONT, size=12))
        self.login_status.pack(pady=(8, 0))
        self.auth_btn = ctk.CTkButton(card, text='登 录', height=44, corner_radius=12,
                                      fg_color=ACCENT, hover_color=ACCENT_DIM,
                                      text_color=ON_ACCENT,
                                      font=ctk.CTkFont(family=FONT, size=15, weight='bold'),
                                      command=self._do_auth)
        self.auth_btn.pack(fill='x', padx=34, pady=(10, 8))
        self.auth_hint = ctk.CTkLabel(card, text='', text_color=TEXT_DIM,
                                      font=ctk.CTkFont(family=FONT, size=11))
        self.auth_hint.pack(pady=(0, 8))

        # 登录界面也能直接换外观主题
        theme_row = ctk.CTkFrame(card, fg_color='transparent')
        theme_row.pack(fill='x', padx=34, pady=(0, 10))
        ctk.CTkLabel(theme_row, text='🎨  外观主题', anchor='w', text_color=TEXT_SOFT,
                     font=ctk.CTkFont(family=FONT, size=11)).pack(side='left')
        self._theme_menu(theme_row, fg_color=FIELD_BG).pack(side='right')
        self._set_mode('login')

    def _theme_menu(self, parent, fg_color=None, width=118):
        """主题下拉框：登录界面和聊天界面共用。"""
        var = tk.StringVar(value=THEME_LABELS.get(self.theme_key, ''))
        menu = ctk.CTkOptionMenu(
            parent, values=[THEME_LABELS[k] for k in THEME_ORDER],
            variable=var, command=self._on_theme_pick,
            width=width, height=32, corner_radius=10,
            fg_color=fg_color or BG_PANEL,
            button_color=BG_HOVER, button_hover_color=BG_ACTIVE,
            text_color=TEXT,
            dropdown_fg_color=BG_PANEL, dropdown_hover_color=BG_ACTIVE,
            dropdown_text_color=TEXT,
            font=ctk.CTkFont(family=FONT, size=12),
            dropdown_font=ctk.CTkFont(family=FONT, size=12))
        self._theme_vars.append(var)
        return menu

    def _on_theme_pick(self, label):
        key = LABEL_TO_THEME.get(label)
        if not key or key == self.theme_key:
            return
        self.theme_key = apply_theme(key)
        # 换肤要整体重建界面（一两秒），先把遮罩铺上再动手：
        # 不然这期间窗口上就是一片没画出来的黑块。
        self._veil_show('正在换肤')
        self._paint_window_bg()
        self.after(30, self._rebuild_ui)
        # 落盘放到重建之后做：写文件偶尔要一两百毫秒（杀软扫描），
        # 放在点击回调里会卡住界面。
        self.after(40, lambda k=key: save_theme(k))

    # ---------- 换肤：整体重建界面 ----------
    def _rebuild_ui(self):
        """配色在控件创建时就写死了，所以要重建界面才能整体换肤。"""
        keep = {
            'host': self._entry_text('host_entry', '127.0.0.1'),
            'port': self._entry_text('port_entry', '26000'),
            'nick': self._entry_text('nick_entry', ''),
            'pwd': self._entry_text('pwd_entry', ''),
            'draft': self._draft_text(),
            'sound': self.sound_on,
            'mode': self.mode,
            'connected': self.connected,
            'status': self._label_state('me_sub'),
            'login_status': self._label_state('login_status'),
            'remember': bool(getattr(self, 'remember_var', None)
                             and self.remember_var.get()),
        }
        for attr in ('_add_friend_win', '_search_win'):
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass
                setattr(self, attr, None)
        self._add_friend_send = None

        self._stop_bg()
        for name in ('login', 'chat'):
            frame = getattr(self, name, None)
            if frame is not None:
                try:
                    frame.destroy()
                except Exception:
                    pass

        # 主题换了：头像、缩略图、文件行里都存着旧配色，全部作废
        self._avatar_cache.clear()
        self._img_refs = []
        self._file_rows = {}
        self._conv_rows = {}
        self._theme_vars = []
        self._emoji_grid = None      # 面板控件都重建了，缓存标记要清掉
        self._forget_all_views()     # 换肤后所有消息区都要重画
        self._thumb_cache = {}       # 缩略图按 fid 缓存，但主题换了重新生成更稳
        self._bg_base = None
        self._bg_blobs = []
        self._bg_photo = None
        self._input_h = 42
        self._grow_pending = False
        self._search_box = None
        self._offline_bar = None
        self._member_sig = None
        self._group_win = None
        self._group_win_gid = None
        try:
            self.configure(fg_color=BG_APP)
        except Exception:
            pass
        self._paint_window_bg()
        # 遮罩是旧配色的，换肤后要重建；而且它必须盖在最上面
        try:
            if self._alive(getattr(self, '_veil', None)):
                self._veil.destroy()
        except Exception:
            pass
        self._veil = None

        self._build_login()
        self._build_chat()
        self._hook_scroll_events()     # 界面重建了，滚动监听要重新挂

        # 开着的棋盘窗口跟着换配色（不打断对局）
        palette = self._chess_palette()
        for win in list(self.chess_windows.values()):
            try:
                if win.winfo_exists():
                    win.apply_palette(palette)
            except Exception:
                pass
        for attr, val in (('host_entry', keep['host']), ('port_entry', keep['port']),
                          ('nick_entry', keep['nick']), ('pwd_entry', keep['pwd'])):
            self._set_entry_text(attr, val)
        self.mode = keep['mode']
        self._set_mode(self.mode)
        try:
            self.remember_var.set(bool(keep.get('remember')))
        except Exception:
            pass
        self._auto_login_done = True     # 换肤重建不算「下次启动」，别重复自动登录
        self.sound_on = keep['sound']
        if not self.sound_on:
            self.sound_switch.deselect()
        if keep['draft']:
            try:
                self.input.insert('1.0', keep['draft'])
            except Exception:
                pass
        text, color = keep['login_status']
        if text:
            self._login_status(text, color or DANGER)

        if keep['connected'] and self.client is not None:
            self.show_chat()
            self._rebuild_conv_list()
            self._render_conv()
            self._schedule_preload()      # 换肤后缓存全清了，空闲时重新预热一遍
            self.me_label.configure(text=f'{getattr(self.client, "me", "") or ""}（我）')
            text, color = keep['status']
            if not text:
                text, color = self._status_text(), ONLINE
            self._set_status(text, color or ONLINE)
            try:
                self.me_server.configure(text=self._server_text())
            except Exception:
                pass
        else:
            self.show_login()
            if self._pending_auth:
                try:
                    self.auth_btn.configure(state='disabled')
                except Exception:
                    pass
        # 重建完了，遮罩可以收了（重建期间它一直盖着，不让黑块露出来）
        self.after(60, self._veil_hide)

    # ---------- 重建时保存/恢复界面状态的小工具 ----------
    def _entry_text(self, attr, default=''):
        try:
            return getattr(self, attr).get()
        except Exception:
            return default

    def _set_entry_text(self, attr, value):
        w = getattr(self, attr, None)
        if w is None:
            return
        try:
            w.delete(0, 'end')
            if value:
                w.insert(0, value)
        except Exception:
            pass

    def _label_state(self, attr):
        w = getattr(self, attr, None)
        if w is None:
            return ('', None)
        try:
            return (w.cget('text') or '', w.cget('text_color'))
        except Exception:
            return ('', None)

    def _draft_text(self):
        try:
            return self.input.get('1.0', 'end-1c')
        except Exception:
            return ''

    def _field(self, parent, label, hint='', show=None):
        wrap = ctk.CTkFrame(parent, fg_color='transparent')
        wrap.pack(fill='x', padx=34, pady=(10, 0))
        ctk.CTkLabel(wrap, text=label, anchor='w', text_color=TEXT_SOFT,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill='x')
        e = ctk.CTkEntry(wrap, height=40, width=460, corner_radius=10, fg_color=FIELD_BG,
                         border_color=FIELD_BORDER, border_width=1,
                         placeholder_text=hint, text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=14))
        e.pack(fill='x', pady=(3, 0))
        if show:
            e.configure(show=show)
        e.bind('<FocusIn>', lambda ev, w=e: self._animate(w, 'border_color', FIELD_BORDER, ACCENT, 5, 26))
        e.bind('<FocusOut>', lambda ev, w=e: self._animate(w, 'border_color', ACCENT, FIELD_BORDER, 5, 26))
        return e

    def _prefill_login(self):
        """用上次成功登录的信息填好登录框（密码只在勾了「记住密码」时才有）。"""
        cfg = load_client_config()
        self._saved_cfg = cfg
        try:
            self.host_entry.delete(0, 'end')
            self.host_entry.insert(0, str(cfg.get('host') or '127.0.0.1'))
            self.port_entry.delete(0, 'end')
            self.port_entry.insert(0, str(cfg.get('port') or 26000))
            nick = str(cfg.get('nick') or '')
            if nick:
                self.nick_entry.delete(0, 'end')
                self.nick_entry.insert(0, nick)
        except Exception:
            pass
        # 密码：只有「记住密码」开着、并且能解出来时才回填
        want = bool(cfg.get('save_password'))
        pwd = ''
        if want:
            pwd = chat_secret.unprotect(cfg.get('password') or '')
            if not pwd:
                want = False       # 密文坏了/换机器了：别装作记住了
                save_client_config(save_password=None, password=None)
        if want and pwd:
            try:
                self.pwd_entry.delete(0, 'end')
                self.pwd_entry.insert(0, pwd)
            except Exception:
                pwd = ''
        else:
            # 没有可恢复的密码就把框清空（别留着上次输的，让用户误以为记住了）
            try:
                self.pwd_entry.delete(0, 'end')
            except Exception:
                pass
            pwd = ''
        try:
            self.remember_var.set(want)
        except Exception:
            pass
        if want and pwd and not getattr(self, '_auto_login_done', False):
            # 勾了记住密码 → 直接登录（等界面画完再动手）
            self._auto_login_done = True
            self.after(500, self._auto_login_if_ready)

    def _auto_login_if_ready(self):
        if getattr(self, 'mode', '') != 'login' or self.connected:
            return
        try:
            ready = (self.host_entry.get().strip() and self.port_entry.get().strip()
                     and self.nick_entry.get().strip() and self.pwd_entry.get())
        except Exception:
            return
        if not ready:
            return
        self._login_status('正在用上次保存的账号登录…', ONLINE)
        self._trace('自动登录：使用上次保存的账号')
        self._do_auth()

    def _on_remember_toggle(self):
        """开关一关就立刻把本机存的密码删掉（别让用户以为已经删了）。"""
        try:
            on = bool(self.remember_var.get())
        except Exception:
            on = False
        if not on:
            save_client_config(save_password=None, password=None)
            self._login_status('已取消记住密码，本机保存的密码已删除', TEXT_SOFT)
        else:
            self._login_status('登录成功后会把密码加密保存在本机', TEXT_SOFT)

    def _save_login_info(self):
        """登录成功后：地址/端口/昵称总是记住；密码看「记住密码」开关。"""
        try:
            host = self.host_entry.get().strip()
            port = self.port_entry.get().strip()
            nick = self.nick_entry.get().strip()
        except Exception:
            return
        up = {'host': host, 'port': port, 'nick': nick}
        try:
            remember = bool(self.remember_var.get())
        except Exception:
            remember = False
        if remember:
            try:
                pwd = self.pwd_entry.get()
            except Exception:
                pwd = ''
            token = chat_secret.protect(pwd) if pwd else ''
            if token:
                up['save_password'] = True
                up['password'] = token
            else:
                # 加密不可用（或没密码）：老老实实不存，并提示一次
                up['save_password'] = None
                up['password'] = None
                self._toast('这台机器无法安全保存密码，下次仍需手动输入', WARN)
        else:
            up['save_password'] = None
            up['password'] = None
        save_client_config(**up)
        self._trace(f'已记住登录信息 host={host} port={port} nick={nick} '
                    f'记住密码={remember}')

    def _set_mode(self, mode):
        self.mode = mode
        on = ctk.CTkFont(family=FONT, size=14, weight='bold')
        off = ctk.CTkFont(family=FONT, size=14)
        if mode == 'login':
            self.tab_login.configure(fg_color=ACCENT, text_color=TEXT, font=on)
            self.tab_reg.configure(fg_color='transparent', text_color=TEXT_DIM, font=off)
            self.auth_btn.configure(text='登 录')
            self.auth_hint.configure(text='回车即可登录 · 没有账号点上方「注册」')
        else:
            self.tab_reg.configure(fg_color=ACCENT, text_color=TEXT, font=on)
            self.tab_login.configure(fg_color='transparent', text_color=TEXT_DIM, font=off)
            self.auth_btn.configure(text='注 册 并 登 录')
            self.auth_hint.configure(text='回车即可注册 · 昵称全服唯一，注册后自动登录')

    def _login_status(self, text, color=None):
        # 注意：这里不能用 color=DANGER 当默认值 —— 默认参数在函数定义时求值，
        # 会把「导入时那套主题」的 DANGER 永久固化下来，换主题后颜色就串了。
        self.login_status.configure(text=text, text_color=color or DANGER)

    # ---------- 发起登录 / 注册 ----------
    def _on_login_return(self, event=None):
        """在任意输入框按回车即触发当前的「登录 / 注册」。"""
        if self._pending_auth:
            return 'break'          # 正在连接，避免重复提交
        if self.auth_btn.cget('state') == 'disabled':
            return 'break'
        self._do_auth()
        return 'break'

    def _do_auth(self, use_addr=None, quiet=False):
        raw = self.host_entry.get().strip()
        port_s = self.port_entry.get().strip()
        nick = self.nick_entry.get().strip()
        pwd = self.pwd_entry.get()
        if not raw or not nick or not pwd:
            self._login_status('请填写服务器地址、昵称和密码')
            return
        # 地址里带路径/协议/端口都能认（用户经常直接从浏览器复制）
        host, inline_port = normalize_host(raw)
        if not host:
            self._login_status('服务器地址不合法')
            return
        if inline_port:
            self.port_entry.delete(0, 'end')
            self.port_entry.insert(0, str(inline_port))
            port = inline_port
        else:
            try:
                port = int(port_s)
            except ValueError:
                self._login_status('端口必须是数字')
                return
        if not (0 < port < 65536):
            self._login_status('端口要在 1-65535 之间')
            return
        if len(nick) < NICK_MIN or len(nick) > NICK_MAX:
            self._login_status(f'昵称需 {NICK_MIN}-{NICK_MAX} 个字符')
            return
        if len(pwd) < PASSWORD_MIN:
            self._login_status(f'密码至少 {PASSWORD_MIN} 位')
            return

        # 记下来，掉线时可以自动重连
        self._auth_args = (host, port, nick, pwd, self.mode)
        if not quiet:
            self._login_status('正在连接服务器…', WARN)
        self.auth_btn.configure(state='disabled')
        old = self.client
        self.client = None
        if old is not None:
            try:
                old.disconnect()
            except Exception:
                pass
        try:
            c = ChatClient(host, port, addr=use_addr)
        except socket.gaierror as e:
            self.client = None
            self._login_status(
                f'无法解析服务器地址：{e}。'
                '请检查域名拼写；如果这台机器上不了外网 DNS，直接把服务器 IP 填进来最稳。')
            self.auth_btn.configure(state='normal')
            return
        except Exception as e:
            self.client = None
            self._login_status(f'无法连接服务器地址：{e}')
            self.auth_btn.configure(state='normal')
            return
        c.on_error = self._note_client_error
        self.client = c
        self._pending_auth = True
        if self.mode == 'register':
            c.register(nick, pwd)
        else:
            c.login(nick, pwd)
        self.after(7000, self._check_auth_timeout)

    def _note_client_error(self, text):
        try:
            write_log(log_path(), f'[{time.strftime("%H:%M:%S")}] 网络层：{text}')
        except Exception:
            pass

    def _check_auth_timeout(self):
        if not (self._pending_auth and not self.connected):
            return
        if self._reconnecting:          # 重连没成功 → 安排下一次
            self._reconnect_step()
            return
        # 域名解析出多个地址时，第一个不通就换下一个再试
        c = self.client
        cands = list(getattr(c, 'candidates', None) or [])
        nxt = getattr(self, '_auth_cand', 0) + 1
        if len(cands) > 1 and nxt < len(cands):
            self._auth_cand = nxt
            self._pending_auth = False
            self._login_status(f'第 1 个地址没响应，正在试备用地址 '
                               f'({nxt + 1}/{len(cands)})…', WARN)
            self._do_auth(use_addr=cands[nxt], quiet=True)
            return
        self._login_status('连接超时：请检查地址、端口，以及服务器防火墙 / 安全组是否'
                           '放行了这个 UDP 端口')
        self._reset_login()

    def _reset_login(self):
        self._pending_auth = False
        self._auth_cand = 0
        c = self.client
        self.client = None
        if c is not None:
            try:
                c.disconnect()
            except Exception:
                pass
        self.auth_btn.configure(state='normal')

    # ================= 动画工具 =================
    @staticmethod
    def _mix_hex(a, b, t):
        try:
            a = a.lstrip('#'); b = b.lstrip('#')
            ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
            br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
            return '#%02x%02x%02x' % (int(ar + (br - ar) * t), int(ag + (bg - ag) * t),
                                      int(ab + (bb - ab) * t))
        except Exception:
            return b

    def _animate(self, widget, attr, start, end, steps=6, interval=28):
        def step(i):
            try:
                widget.configure(**{attr: self._mix_hex(start, end, i / steps)})
            except Exception:
                return
            if i < steps:
                self.after(interval, lambda: step(i + 1))
        step(1)

    def _fade_in_window(self, steps=14, interval=24):
        try:
            self.attributes('-alpha', 0.02)
        except Exception:
            return

        def step(i):
            try:
                self.attributes('-alpha', min(1.0, i / steps))
            except Exception:
                return
            if i < steps:
                self.after(interval, lambda: step(i + 1))
            else:
                self._force_opaque()
        self.after(steps * interval + 300, self._force_opaque)
        step(1)

    def _force_opaque(self):
        try:
            self.attributes('-alpha', 1.0)
        except Exception:
            pass

    def _pulse(self, widget, base=None, flash=None, steps=4, interval=50):
        base = base or ACCENT
        flash = flash or ACCENT_FLASH
        base = base or ACCENT
        try:
            widget.configure(fg_color=flash)
        except Exception:
            return

        def step(i):
            try:
                widget.configure(fg_color=self._mix_hex(base, flash, (steps - i) / steps))
            except Exception:
                return
            if i < steps:
                self.after(interval, lambda: step(i + 1))
        step(1)

    def _logo_image(self, size=76):
        if not PIL_OK:
            return None
        try:
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            grad = Image.new('RGB', (1, size))
            top, bot = LOGO_TOP, LOGO_BOT
            for y in range(size):
                t = y / max(1, size - 1)
                grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
            grad = grad.resize((size, size)).convert('RGBA')
            mask = Image.new('L', (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                                   radius=size // 4, fill=255)
            img.paste(grad, (0, 0), mask)
            d = ImageDraw.Draw(img)
            x0, y0, x1, y1 = size * 0.22, size * 0.27, size * 0.78, size * 0.62
            d.rounded_rectangle((x0, y0, x1, y1), radius=size * 0.11, fill=(255, 255, 255, 240))
            d.polygon([(size * 0.34, y1 - 3), (size * 0.29, size * 0.78),
                       (size * 0.48, y1 - 1)], fill=(255, 255, 255, 240))
            return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        except Exception:
            return None

    # ---------- 登录页流动背景 ----------
    def _bg_base_image(self, w, h):
        img = Image.new('RGB', (w, h))
        px = img.load()
        top, mid, bot = GRAD
        for y in range(h):
            t = y / max(1, h - 1)
            if t < 0.5:
                k = t / 0.5
                base = tuple(int(top[i] + (mid[i] - top[i]) * k) for i in range(3))
            else:
                k = (t - 0.5) / 0.5
                base = tuple(int(mid[i] + (bot[i] - mid[i]) * k) for i in range(3))
            for x in range(w):
                f = 1.0 + 0.12 * ((x / max(1, w - 1)) - 0.5)
                px[x, y] = (min(255, int(base[0] * f)), min(255, int(base[1] * f)),
                            min(255, int(base[2] * f)))
        return img.convert('RGBA')

    def _make_blob(self, r, color):
        size = r * 2
        mask = Image.new('L', (size, size), 0)
        mpx = mask.load()
        for y in range(size):
            dy = y - r
            for x in range(size):
                dx = x - r
                d = (dx * dx + dy * dy) ** 0.5
                if d < r:
                    a = 1.0 - d / r
                    mpx[x, y] = int(140 * a * a)
        return Image.new('RGB', (size, size), color), mask

    def _init_blobs(self):
        W, H = self._bg_base_w, self._bg_base_h
        r = int(min(W, H) * 0.34)
        specs = [
            (0.18, 0.25, BLOB_COLORS[0], 0.0016, 0.0011),
            (0.72, 0.20, BLOB_COLORS[1], -0.0013, 0.0014),
            (0.45, 0.75, BLOB_COLORS[2], 0.0011, -0.0012),
            (0.85, 0.70, BLOB_COLORS[3], -0.0015, -0.0010),
            (0.10, 0.80, BLOB_COLORS[4], 0.0014, -0.0013),
        ]
        blobs = []
        for (x, y, color, vx, vy) in specs:
            img, mask = self._make_blob(r, color)
            blobs.append({'x': x, 'y': y, 'vx': vx, 'vy': vy, 'r': r, 'img': img, 'mask': mask})
        return blobs

    def _start_bg(self):
        if self._bg_running or not PIL_OK:
            return
        try:
            if self._bg_base is None:
                self._bg_base = self._bg_base_image(self._bg_base_w, self._bg_base_h)
                self._bg_blobs = self._init_blobs()
            self._bg_running = True
            self._bg_tick()
        except Exception:
            self._bg_running = False

    def _stop_bg(self):
        self._bg_running = False

    def _bg_tick(self):
        if not self._bg_running:
            return
        try:
            w = max(2, self.login.winfo_width())
            h = max(2, self.login.winfo_height())
            W, H = self._bg_base_w, self._bg_base_h
            frame = self._bg_base.copy()
            for b in self._bg_blobs:
                r = b['r']
                frame.paste(b['img'], (int(b['x'] * W - r), int(b['y'] * H - r)), b['mask'])
                b['x'] += b['vx']; b['y'] += b['vy']
                if b['x'] < -0.10 or b['x'] > 1.10:
                    b['vx'] = -b['vx']
                if b['y'] < -0.10 or b['y'] > 1.10:
                    b['vy'] = -b['vy']
            img = frame.convert('RGB').resize((w, h), Image.BILINEAR)
            self._bg_photo = ImageTk.PhotoImage(img)
            self._bg_canvas.itemconfigure(self._bg_item, image=self._bg_photo)
        except Exception:
            pass
        if self._bg_running:
            self.after(85, self._bg_tick)

    # ================= 聊天界面 =================
    def _build_chat(self):
        self.chat = ctk.CTkFrame(self, fg_color=BG_APP, corner_radius=0)

        # ---- 左侧会话列表 ----
        self.sidebar = ctk.CTkFrame(self.chat, fg_color=BG_PANEL, width=300, corner_radius=0)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)

        sb_top = ctk.CTkFrame(self.sidebar, fg_color=BG_HEADER, height=58, corner_radius=0)
        sb_top.pack(fill='x')
        sb_top.pack_propagate(False)
        head_col = ctk.CTkFrame(sb_top, fg_color='transparent')
        head_col.pack(side='left', padx=16)
        ctk.CTkLabel(head_col, text=f'💬  {APP_NAME}', height=21,
                     font=ctk.CTkFont(family=FONT, size=15, weight='bold'),
                     text_color=TEXT).pack(anchor='w')
        ctk.CTkLabel(head_col, text=APP_SUFFIX, height=14, text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=10)).pack(anchor='w')

        self.conv_list = ctk.CTkScrollableFrame(
            self.sidebar, fg_color='transparent', corner_radius=0,
            scrollbar_fg_color='transparent', scrollbar_button_color=SCROLL_BTN,
            scrollbar_button_hover_color=SCROLL_HOVER)
        self.conv_list.pack(fill='both', expand=True, padx=4, pady=(6, 6))

        sb_bottom = ctk.CTkFrame(self.sidebar, fg_color='transparent', height=104)
        sb_bottom.pack(side='bottom', fill='x')
        me_row = ctk.CTkFrame(sb_bottom, fg_color='transparent')
        me_row.pack(fill='x', padx=12, pady=(8, 2))
        self.me_avatar = ctk.CTkLabel(me_row, text='', width=40, fg_color='transparent',
                                      text_color=TEXT, cursor='hand2')
        self.me_avatar.pack(side='left', padx=(2, 8))
        self.me_avatar.bind('<Button-1>', lambda *a: self._pick_avatar())
        me_col = ctk.CTkFrame(me_row, fg_color='transparent')
        me_col.pack(side='left', fill='x', expand=True)
        self.me_label = ctk.CTkLabel(me_col, text='', anchor='w', height=18, text_color=TEXT,
                                     font=ctk.CTkFont(family=FONT, size=13, weight='bold'))
        self.me_label.pack(fill='x')
        sub_row = ctk.CTkFrame(me_col, fg_color='transparent')
        sub_row.pack(fill='x')
        self.me_sub = ctk.CTkLabel(sub_row, text='未登录', anchor='w', text_color=TEXT_DIM,
                                   font=ctk.CTkFont(family=FONT, size=11))
        self.me_sub.pack(side='left')
        self.offline_badge = ctk.CTkLabel(sub_row, text='', anchor='e', text_color=WARN,
                                          font=ctk.CTkFont(family=FONT, size=10))
        self.offline_badge.pack(side='right')
        me_btns = ctk.CTkFrame(sb_bottom, fg_color='transparent')
        me_btns.pack(fill='x', padx=12, pady=(2, 8))
        self.avatar_btn = ctk.CTkButton(me_btns, text='🖼 更换头像', height=26,
                                        width=96, corner_radius=8, fg_color='transparent',
                                        border_width=1, border_color=FIELD_BORDER,
                                        hover_color=BG_HOVER, text_color=TEXT_DIM,
                                        font=ctk.CTkFont(family=FONT, size=10),
                                        command=self._pick_avatar)
        self.avatar_btn.pack(side='left')
        self.admin_btn = ctk.CTkButton(me_btns, text='🛡 控制台', height=26, width=74,
                                       corner_radius=8, fg_color=ACCENT,
                                       hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                                       font=ctk.CTkFont(family=FONT, size=10, weight='bold'),
                                       command=self._open_admin_console)
        # 服务器属地：放在「更换头像」右边，字号小一点（用户明确要求）
        self.me_server = ctk.CTkLabel(me_btns, text='', anchor='e', justify='right',
                                      wraplength=158, text_color=TEXT_DIM,
                                      font=ctk.CTkFont(family=FONT, size=10))
        self.me_server.pack(side='right', padx=(6, 0))

        # ---- 右侧主区 ----
        self.main = ctk.CTkFrame(self.chat, fg_color=BG_APP, corner_radius=0)
        self.main.pack(side='left', fill='both', expand=True)

        header = ctk.CTkFrame(self.main, fg_color=BG_HEADER, height=58, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)
        self.title_label = ctk.CTkLabel(header, text='', height=22, text_color=TEXT,
                                        font=ctk.CTkFont(family=FONT, size=16, weight='bold'))
        self.title_label.pack(side='left', padx=(18, 8))
        self.sub_label = ctk.CTkLabel(header, text='', height=22, text_color=TEXT_DIM,
                                      font=ctk.CTkFont(family=FONT, size=12))
        self.sub_label.pack(side='left')
        self.rtt_label = ctk.CTkLabel(header, text='', height=22, text_color=TEXT_DIM,
                                      font=ctk.CTkFont(family=FONT, size=12))
        self.rtt_label.pack(side='left', padx=10)

        self.disconnect_btn = ctk.CTkButton(header, text='退出登录', width=76, height=30,
                                            corner_radius=10, fg_color='transparent',
                                            border_width=1, border_color=FIELD_BORDER,
                                            hover_color=BG_HOVER, text_color=TEXT_DIM,
                                            font=ctk.CTkFont(family=FONT, size=12),
                                            command=self.disconnect)
        self.disconnect_btn.pack(side='right', padx=(4, 14))
        self.sound_switch = ctk.CTkSwitch(header, text='提示音', command=self._toggle_sound,
                                          font=ctk.CTkFont(family=FONT, size=12),
                                          text_color=TEXT_DIM, progress_color=ACCENT,
                                          fg_color=BG_ACTIVE, button_color=TEXT_DIM,
                                          button_hover_color=TEXT)
        self.sound_switch.select()
        self.sound_switch.pack(side='right', padx=8)
        self.members_btn = ctk.CTkButton(header, text='👥', width=32, height=30,
                                         corner_radius=10, fg_color='transparent',
                                         border_width=1, border_color=FIELD_BORDER,
                                         hover_color=BG_HOVER, text_color=TEXT_DIM,
                                         font=ctk.CTkFont(family=EMOJI_FONT, size=14),
                                         command=self._toggle_members)
        self.members_btn.pack(side='right', padx=4)
        self.group_btn = ctk.CTkButton(header, text='☰ 群资料/管理', width=108, height=30,
                                       corner_radius=10, fg_color='transparent',
                                       border_width=1, border_color=FIELD_BORDER,
                                       hover_color=BG_HOVER, text_color=TEXT_DIM,
                                       font=ctk.CTkFont(family=FONT, size=12),
                                       command=self._open_group_info)
        self.group_btn.pack(side='right', padx=4)
        # 进入之后任何界面都能换主题
        self._theme_menu(header, fg_color=BG_PANEL, width=104).pack(side='right', padx=4)

        # ---- 群公告横幅（只在群聊里出现） ----
        self.announce_bar = ctk.CTkFrame(self.main, fg_color=BG_ACTIVE, corner_radius=0,
                                         height=30)
        self.announce_label = ctk.CTkLabel(self.announce_bar, text='', anchor='w',
                                           text_color=REGION, cursor='hand2',
                                           font=ctk.CTkFont(family=FONT, size=12))
        self.announce_label.pack(side='left', fill='x', expand=True, padx=14)
        self.announce_label.bind('<Button-1>', lambda *a: self._open_group_info())

        bottom = ctk.CTkFrame(self.main, fg_color='transparent')
        bottom.pack(side='bottom', fill='x')
        self.bottom = bottom
        self.panel = ctk.CTkFrame(bottom, fg_color=BG_PANEL, corner_radius=12)

        # 被禁言时用它顶掉输入区（用户要求：禁言时把输入框和发送按钮收起来）
        self.mute_bar = ctk.CTkFrame(bottom, fg_color=BG_PANEL, corner_radius=12)
        ctk.CTkLabel(self.mute_bar, text='🔇', text_color=WARN, width=28,
                     font=ctk.CTkFont(family=EMOJI_FONT, size=18)).pack(side='left',
                                                                        padx=(14, 6), pady=8)
        self.mute_label = ctk.CTkLabel(self.mute_bar, text='', anchor='w', text_color=WARN,
                                       justify='left',
                                       font=ctk.CTkFont(family=FONT, size=13, weight='bold'))
        self.mute_label.pack(side='left', pady=8)
        self.mute_sub = ctk.CTkLabel(self.mute_bar, text='', anchor='w', text_color=TEXT_DIM,
                                     justify='left',
                                     font=ctk.CTkFont(family=FONT, size=11))
        self.mute_sub.pack(side='left', padx=(8, 14), pady=8)
        self.muted_view = False        # 当前是否处于「禁言」展示状态

        composer = ctk.CTkFrame(bottom, fg_color='transparent')
        composer.pack(fill='x', padx=12, pady=10)
        self.composer = composer
        self.emoji_btn = ctk.CTkButton(composer, text='😊', width=40, height=40, corner_radius=20,
                                       fg_color=BG_PANEL, hover_color=BG_HOVER,
                                       text_color=TEXT,
                                       font=ctk.CTkFont(family=EMOJI_FONT, size=18),
                                       command=self._toggle_emoji)
        self.emoji_btn.pack(side='left', padx=(0, 6))
        self.file_btn = ctk.CTkButton(composer, text='📎', width=40, height=40, corner_radius=20,
                                      fg_color=BG_PANEL, hover_color=BG_HOVER,
                                      text_color=TEXT,
                                      font=ctk.CTkFont(family=EMOJI_FONT, size=18),
                                      command=self._pick_file)
        self.file_btn.pack(side='left', padx=(0, 6))
        self.mention_btn = ctk.CTkButton(composer, text='@', width=40, height=40, corner_radius=20,
                                         fg_color=BG_PANEL, hover_color=BG_HOVER,
                                         font=ctk.CTkFont(family=FONT, size=17, weight='bold'),
                                         text_color=TEXT_DIM, command=self._toggle_mention)
        self.mention_btn.pack(side='left', padx=(0, 8))
        self.chess_btn = ctk.CTkButton(composer, text='♟', width=40, height=40, corner_radius=20,
                                       fg_color=BG_PANEL, hover_color=BG_HOVER,
                                       text_color=TEXT,
                                       font=ctk.CTkFont(family=FONT, size=18),
                                       command=self._toggle_chess_panel)
        self.chess_btn.pack(side='left', padx=(0, 8))
        self.send_btn = ctk.CTkButton(composer, text='➤', width=46, height=40, corner_radius=20,
                                      fg_color=ACCENT, hover_color=ACCENT_DIM,
                                      text_color=ON_ACCENT,
                                      font=ctk.CTkFont(size=17), command=self.send)
        self.send_btn.pack(side='right', padx=(8, 0))
        self.input = ctk.CTkTextbox(composer, height=42, corner_radius=18, wrap='word',
                                    fg_color=BG_PANEL, border_width=0,
                                    activate_scrollbars=False,
                                    font=ctk.CTkFont(family=FONT, size=14), text_color=TEXT)
        self.input.pack(side='left', fill='x', expand=True)
        self.input.bind('<Return>', self._on_return)
        self.input.bind('<KeyRelease>', self._grow_input)

        # ---- 消息区 + 右侧成员面板（QQ 风格，可以直接加好友 / @ 人） ----
        self.body = ctk.CTkFrame(self.main, fg_color='transparent')
        self.body.pack(fill='both', expand=True)

        self.members = ctk.CTkFrame(self.body, fg_color=BG_PANEL, width=216,
                                    corner_radius=0)
        self.members.pack(side='right', fill='y')
        self.members.pack_propagate(False)

        self.messages = self._make_messages()
        self.messages.pack(side='left', fill='both', expand=True)
        self._member_sig = None      # 成员面板内容的指纹（列表没变就不重建）

        self.drop_hint = ctk.CTkLabel(self.main, text='📎   松开即可发送文件',
                                      fg_color=ACCENT, corner_radius=16, text_color=ON_ACCENT,
                                      font=ctk.CTkFont(family=FONT, size=16, weight='bold'))
        self.dnd_ready = False
        self.dnd_backend = None

    # ================= 头像 =================
    def _avatar(self, nick, size=38):
        """头像：优先用服务端上的自定义头像，没有就用「首字母彩色圆」兜底。"""
        nick = nick or '?'
        path = ''
        c = self.client
        is_group = nick.startswith('群') and len(nick) > 1   # 群头像：用前缀标记
        if c is not None and nick not in ('厅', '群', '?') and not is_group:
            try:
                path = c.avatar_path(nick)
                if not path and (getattr(c, 'avatar_ver', {}).get(nick.strip().lower(), 0)
                                 or self._avatars_known(nick)):
                    c.request_avatar(nick)      # 后台拉取，到了会刷新界面
            except Exception:
                path = ''
        key = (nick, size, path)
        if key in self._avatar_cache:
            return self._avatar_cache[key]
        cimg = None
        if PIL_OK:
            try:
                if path and os.path.isfile(path):
                    img = Image.open(path)
                    img.load()
                    img = img.convert('RGBA').resize((size, size), Image.LANCZOS)
                    cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
                    self._avatar_cache[key] = cimg
                    return cimg
                color = AVATAR_COLORS[sum(ord(c) for c in nick) % len(AVATAR_COLORS)]
                img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                d.ellipse((0, 0, size - 1, size - 1), fill=color)
                letter = (nick[:1] or '?').upper()
                font = None
                for name in ('msyhbd.ttc', 'arialbd.ttf', 'arial.ttf'):
                    try:
                        font = ImageFont.truetype(name, int(size * 0.46))
                        break
                    except Exception:
                        continue
                if font is None:
                    font = ImageFont.load_default()
                box = d.textbbox((0, 0), letter, font=font)
                w, h = box[2] - box[0], box[3] - box[1]
                d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), letter,
                       font=font, fill=(255, 255, 255, 255))
                cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
            except Exception as e:
                import traceback
                self._avatar_err = f'{e!r}\n{traceback.format_exc()}'
                cimg = None
        self._avatar_cache[key] = cimg
        return cimg

    def _avatars_known(self, nick):
        """服务端告诉过我们这个人有头像吗？"""
        c = self.client
        if c is None:
            return False
        return nick.strip().lower() in (getattr(c, 'avatar_ver', None) or {})

    def _clear_avatar_cache(self, nick=None):
        if nick is None:
            self._avatar_cache.clear()
            return
        low = nick.strip().lower()
        for k in list(self._avatar_cache):
            if k[0].strip().lower() == low:
                self._avatar_cache.pop(k, None)

    def _redraw_for_avatar(self, nick=None):
        """头像变了：只换那一张头像，不做整块重绘。

        以前这里会把会话列表、整个消息区都重画一遍 —— 别人登录时头像陆续
        到达，界面就跟着一阵阵地闪，看着就是「一抽一抽」。现在只把用到
        这个人的头像控件换张图，别的什么都不动。
        """
        self._member_sig = None
        if nick:
            self._swap_avatar_images(nick)
        try:
            self._rebuild_conv_list()
        except Exception:
            pass
        try:
            self._rebuild_members()
        except Exception:
            pass
        if getattr(self, '_group_win_gid', None):
            self._render_group_window()

    def _swap_avatar_images(self, nick):
        """把界面上这个人的头像换成新的（找不到就跳过）。"""
        want = None
        try:
            want = self._avatar(nick, 38)
        except Exception:
            want = None
        for lbl in list(getattr(self, '_avatar_labels', ())):
            if getattr(lbl, '_avatar_nick', None) != nick:
                continue
            try:
                if not lbl.winfo_exists():
                    continue
                size = getattr(lbl, '_avatar_size', 38)
                img = self._avatar(nick, size)
                if img is not None:
                    lbl.configure(image=img)
            except Exception:
                continue
        return want

    # ---------- 设置自己的头像 ----------
    def _pick_avatar(self):
        if self.client is None or not self.connected:
            self._toast('还没连上服务器，无法更换头像', WARN)
            return
        path = filedialog.askopenfilename(
            title='选择头像图片' + APP_SUFFIX,
            # 写法必须和「发文件」那个对话框一致：多个后缀用**空格**分开。
            # 写成 '*.png;*.jpg' 在部分 Tk 上会被当成一个整体通配符，
            # 结果文件列表是空的、什么都选不了。
            filetypes=[('所有文件', '*.*'),
                       ('图片', '*.png *.jpg *.jpeg *.bmp *.gif *.webp')])
        if not path:
            return
        try:
            out = self._prepare_avatar(path)
        except Exception as e:
            write_diag(f'更换头像：处理图片失败 path={path!r} {e!r}')
            self._toast(f'这张图片不能用作头像：{e}', WARN)
            return
        try:
            self.client.send_avatar(out)
            try:
                write_diag(f'更换头像：已提交上传 {os.path.basename(path)!r} → '
                           f'{os.path.getsize(out)} 字节')
            except Exception:
                pass
            self._toast('头像上传中…')
        except Exception as e:
            write_diag(f'更换头像：上传失败 {e!r}')
            self._toast(f'头像上传失败：{e}', WARN)

    def _prepare_avatar(self, path):
        """把任意图片压成 256×256 的 PNG，体积可控（也避免超大图拖慢传输）。"""
        if not PIL_OK:
            raise RuntimeError('缺少图片处理库 Pillow')
        img = Image.open(path)
        img.load()
        img = img.convert('RGBA')
        side = min(img.size)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((AVATAR_SIDE, AVATAR_SIDE), Image.LANCZOS)
        d = os.path.join(tempfile.gettempdir(), 'qiaoni_avatar')
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, f'{os.urandom(6).hex()}.png')
        img.save(out, 'PNG', optimize=True)
        return out

    def _name_color(self, nick):
        return NAME_COLORS[sum(ord(c) for c in (nick or '?')) % len(NAME_COLORS)]

    # ================= 会话列表 =================
    def _bind_all_children(self, widget, handler):
        try:
            widget.bind('<Button-1>', handler)
        except Exception:
            pass
        for ch in widget.winfo_children():
            self._bind_all_children(ch, handler)

    # ---------- 控件复用 ----------
    # 以前每次刷新都是「把子控件全销毁再全新建一遍」，一个会话行要建 4~5 个
    # 控件（每个 ~3ms），几十行就是几百毫秒 —— 期间 Tk 主线程被占住，
    # 界面就一抽一抽的。现在改成：内容没变的行原地改文字，只有真的增删才
    # 新建/销毁。
    @staticmethod
    def _alive(w):
        try:
            return bool(w.winfo_exists())
        except Exception:
            return False

    def _pool_sync(self, parent, specs, pool, factories):
        """按 specs 顺序复用/新建子控件。

        specs 每项须含 'kind' 和 'key'；factories[kind] = (建, 改)，改返回
        False 表示「这个控件的形态变了，得重建」。
        """
        order, seen, made = [], set(), False
        for spec in specs:
            key = spec['key']
            seen.add(key)
            make, update = factories[spec['kind']]
            w = pool.get(key)
            if w is not None and not self._alive(w):
                w = None
            if w is not None and update is not None:
                try:
                    if not update(w, spec):
                        w = None
                except Exception as e:
                    write_log(log_path(), f'!! 更新控件失败 {spec.get("kind")}：{e!r}')
                    w = None
            if w is None:
                old = pool.pop(key, None)
                if old is not None:
                    try:
                        old.destroy()
                    except Exception:
                        pass
                try:
                    w = make(parent, spec)
                except Exception as e:
                    write_log(log_path(), f'!! 创建控件失败 {spec.get("kind")}：{e!r}')
                    continue
                pool[key] = w
                made = True
            order.append(w)
        for key in [k for k in pool if k not in seen]:
            try:
                pool.pop(key).destroy()
            except Exception:
                pass
            made = True
        return order, made

    def _pack_order(self, order, prev):
        """顺序没变就别动，变了才按存储的 pack 参数重排一遍。

        重新 pack 已经 pack 过的控件只是改位置，不会重建 Tcl 控件，
        所以比「全销毁再全新建」便宜得多，也不会闪。
        """
        if prev is not None and len(prev) == len(order) \
                and all(a is b for a, b in zip(order, prev)):
            return list(order)
        # 注意：Tk 里对**已经 pack 过**的控件再调 pack() 只是改选项，**不会换位置**。
        # 以前就是踩了这个坑：新增好友行之后，它仍然留在「群组」下面（分组错位）。
        # 必须用 after=上一个控件 明确指定位置。
        for i, w in enumerate(order):
            kw = dict(getattr(w, '_pool_pack', {'fill': 'x'}))
            try:
                if i == 0:
                    others = [x for x in w.master.pack_slaves() if x is not w]
                    if others:
                        kw['before'] = others[0]
                else:
                    kw['after'] = order[i - 1]
                w.pack(**kw)
            except Exception:
                try:
                    w.pack(**getattr(w, '_pool_pack', {'fill': 'x'}))
                except Exception:
                    pass
        return list(order)

    def _conv_row(self, parent, conv, title, subtitle='', avatar_nick=None, dot=None,
                  active=False):
        # 注意：这里不固定行高（也不用 pack_propagate(False)），
        # 否则标题+副标题两行会被压扁，副标题只剩几像素高、文字被裁切。
        row = ctk.CTkFrame(parent, fg_color=BG_ACTIVE if active else 'transparent',
                           corner_radius=10)
        row.pack(fill='x', pady=1)
        row._pool_pack = {'fill': 'x', 'pady': 1}
        nick = avatar_nick or title
        av = self._avatar(nick, 34)
        av_label = None
        if av is not None:
            av_label = ctk.CTkLabel(row, image=av, text='', fg_color='transparent',
                                    text_color=TEXT)
            av_label.pack(side='left', padx=(8, 8), pady=7)
        col = ctk.CTkFrame(row, fg_color='transparent')
        col.pack(side='left', fill='both', expand=True, pady=6)
        title_lbl = ctk.CTkLabel(col, text=title, anchor='w', height=18, text_color=TEXT,
                                 font=ctk.CTkFont(family=FONT, size=13, weight='bold'))
        title_lbl.pack(fill='x')
        sub_lbl = None
        if subtitle:
            sub_lbl = ctk.CTkLabel(col, text=subtitle, anchor='w', height=15,
                                   text_color=TEXT_DIM,
                                   font=ctk.CTkFont(family=FONT, size=11))
            sub_lbl.pack(fill='x')
        dot_lbl = None
        if dot:
            dot_lbl = ctk.CTkLabel(row, text='●', text_color=dot, width=16)
            dot_lbl.pack(side='right', padx=(0, 8))
        row._parts = {'title': title_lbl, 'sub': sub_lbl, 'dot': dot_lbl,
                      'avatar': av_label, 'nick': nick, 'active': bool(active),
                      'conv': conv}
        self._bind_all_children(row, lambda *a, cc=conv: self._select_conv(cc))
        # 好友那一行右键：删除好友 / 拉黑
        if conv_kind(conv) == 'friend':
            self._bind_right_conv(row, nick, conv)
        self._conv_row_hover(row, active)
        return row

    def _bind_right_conv(self, widget, nick, conv):
        """给好友行（及其子控件）绑右键菜单。"""
        def bind(w):
            try:
                w.bind('<Button-3>', lambda e, n=nick: self._friend_menu(e, n))
            except Exception:
                pass
            for ch in w.winfo_children():
                bind(ch)
        bind(widget)

    def _conv_row_hover(self, row, active):
        if active:
            row.configure(fg_color=BG_ACTIVE)
            try:
                row.unbind('<Enter>')
                row.unbind('<Leave>')
            except Exception:
                pass
        else:
            row.configure(fg_color='transparent')
            row.bind('<Enter>', lambda *a, r=row: r.configure(fg_color=BG_HOVER))
            row.bind('<Leave>', lambda *a, r=row: r.configure(fg_color='transparent'))

    def _conv_row_update(self, row, spec):
        """原地更新一行；返回 False 表示形态变了、需要重建。"""
        p = getattr(row, '_parts', None)
        if p is None:
            return False
        title, subtitle = spec['title'], spec.get('subtitle') or ''
        dot = spec.get('dot')
        if (p['sub'] is None) != (not subtitle) or (p['dot'] is None) != (not dot):
            return False
        nick = spec.get('avatar_nick') or title
        if p.get('nick') != nick:
            av = self._avatar(nick, 34)
            if (av is None) != (p['avatar'] is None):
                return False            # 有头像 / 没头像的形态变了
            if av is not None and p['avatar'] is not None:
                p['avatar'].configure(image=av)
            p['nick'] = nick
        if str(p['title'].cget('text')) != title:
            p['title'].configure(text=title)
        if p['sub'] is not None and str(p['sub'].cget('text')) != subtitle:
            p['sub'].configure(text=subtitle)
        if p['dot'] is not None and dot:
            p['dot'].configure(text_color=dot)
        active = bool(spec.get('active'))
        if p.get('active') != active:
            p['active'] = active
            self._conv_row_hover(row, active)
        return True

    @staticmethod
    def _cb_key(cb):
        """回调的稳定标识：绑定方法用「名字 + 所属对象」，避免 id() 复用误判。"""
        self_obj = getattr(cb, '__self__', None)
        return (getattr(cb, '__name__', repr(cb)), id(self_obj) if self_obj else 0)

    def _section(self, parent, text, action_text=None, action=None, actions=None):
        """分组标题栏。actions 是 [(文字, 回调), ...]，按顺序从右往左排。"""
        bar = ctk.CTkFrame(parent, fg_color='transparent')
        bar.pack(fill='x', padx=8, pady=(10, 2))
        bar._pool_pack = {'fill': 'x', 'padx': 8, 'pady': (10, 2)}
        lbl = ctk.CTkLabel(bar, text=text, anchor='w', height=18, text_color=TEXT_DIM,
                           font=ctk.CTkFont(family=FONT, size=11, weight='bold'))
        lbl.pack(side='left')
        items = list(actions or [])
        if action_text:
            items.append((action_text, action))
        for label, cb in reversed(items):      # 先 pack 的贴右边，所以倒着来
            btn = ctk.CTkButton(bar, text=label, width=64, height=22, corner_radius=8,
                                fg_color='transparent', hover_color=BG_HOVER,
                                text_color=ACCENT, font=ctk.CTkFont(family=FONT, size=11),
                                command=cb)
            btn.pack(side='right', padx=(4, 0))
        bar._parts = {'label': lbl,
                      'actions': tuple((l, self._cb_key(cb)) for l, cb in items)}
        return bar

    def _section_update(self, bar, spec):
        items = list(spec.get('actions') or [])
        if spec.get('action_text'):
            items.append((spec['action_text'], spec['action']))
        sig = tuple((l, self._cb_key(cb)) for l, cb in items)
        if sig != getattr(bar, '_parts', {}).get('actions'):
            return False
        text = spec['text']
        if str(bar._parts['label'].cget('text')) != text:
            bar._parts['label'].configure(text=text)
        return True

    def _empty_hint(self, parent, spec):
        padx, pady = spec.get('padx', 10), spec.get('pady', 2)
        lbl = ctk.CTkLabel(parent, text=spec['text'], anchor='w', text_color=TEXT_DIM,
                           justify='left', wraplength=spec.get('wraplength', 0),
                           font=ctk.CTkFont(family=FONT, size=11))
        lbl.pack(fill='x', padx=padx, pady=pady)
        lbl._pool_pack = {'fill': 'x', 'padx': padx, 'pady': pady}
        return lbl

    def _empty_hint_update(self, lbl, spec):
        if str(lbl.cget('text')) != spec['text']:
            lbl.configure(text=spec['text'])
        return True

    def _yes_no_pair(self, parent, yes, no, small=True):
        """「同意 / 拒绝」两颗按钮。

        以前是「透明的拒绝按钮 + 1px 描边」，在卡片右边缘会被裁掉半截、描边
        也缺一角（用户就是看到这个）。现在两颗都做成实心：同意用主色（绿），
        拒绝用暗红，宽度一致、上下居中对齐，右边留足空隙，怎么都不会压边。
        """
        w = 46 if small else 56
        h = 24 if small else 28
        btns = ctk.CTkFrame(parent, fg_color='transparent')
        btns.pack(side='right', padx=(6, 10), pady=6)
        ctk.CTkButton(btns, text='同意', width=w, height=h, corner_radius=h // 2,
                      fg_color=OK_GREEN, hover_color=OK_GREEN_DIM,
                      text_color=ON_ACCENT, font=ctk.CTkFont(family=FONT, size=11,
                                                             weight='bold'),
                      command=yes).pack(side='top', pady=(0, 4))
        ctk.CTkButton(btns, text='拒绝', width=w, height=h, corner_radius=h // 2,
                      fg_color=NO_RED, hover_color=NO_RED_DIM,
                      text_color=ON_ACCENT, font=ctk.CTkFont(family=FONT, size=11),
                      command=no).pack(side='top')
        return btns

    def _req_card(self, parent, spec, kind):
        """好友申请 / 加群申请的小卡片（数量少，内容变了整体重建最省事）。"""
        who, msg = spec['who'], spec.get('msg') or ''
        box = ctk.CTkFrame(parent, fg_color=BG_ACTIVE, corner_radius=10)
        box.pack(fill='x', padx=8, pady=2)
        box._pool_pack = {'fill': 'x', 'padx': 8, 'pady': 2}
        if kind == 'join':
            gid = spec.get('gid')
            yes = lambda: self._answer_join(gid, who, True)
            no = lambda: self._answer_join(gid, who, False)
        else:
            yes = lambda: self.client.accept_friend(who)
            no = lambda: self.client.reject_friend(who)
        # 按钮先 pack（side=right），文字块后 pack 并 expand —— 反过来的话
        # 右边的按钮可能被文字块挤出去。
        self._yes_no_pair(box, yes, no)
        col = ctk.CTkFrame(box, fg_color='transparent')
        col.pack(side='left', fill='both', expand=True, padx=(10, 4), pady=6)
        ctk.CTkLabel(col, text=who, anchor='w', height=16, text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=12, weight='bold')).pack(fill='x')
        if kind == 'join':
            ctk.CTkLabel(col, text=f"申请加入「{spec.get('gname', '')}」", anchor='w',
                         height=14, text_color=REGION,
                         font=ctk.CTkFont(family=FONT, size=10)).pack(fill='x')
        if msg:
            ctk.CTkLabel(col, text=f'“{msg}”', anchor='w', justify='left',
                         wraplength=140, text_color=TEXT_SOFT,
                         font=ctk.CTkFont(family=FONT, size=10)).pack(fill='x')
        box._card_sig = (who, msg, spec.get('gid'), spec.get('gname'))
        return box

    @staticmethod
    def _req_card_update(box, spec):
        return getattr(box, '_card_sig', None) == (spec['who'], spec.get('msg') or '',
                                                   spec.get('gid'), spec.get('gname'))

    def _conv_specs(self):
        """把侧栏要显示的内容整理成一份纯数据清单（不碰任何控件）。"""
        c = self.client
        specs = []

        def sec(title, key=None, **kw):
            specs.append({'kind': 'sec', 'key': key or ('sec', title), 'text': title, **kw})

        def row(conv, title, subtitle='', avatar_nick=None, dot=None):
            specs.append({'kind': 'conv', 'key': ('conv', conv), 'conv': conv,
                          'title': title, 'subtitle': subtitle,
                          'avatar_nick': avatar_nick, 'dot': dot,
                          'active': self.conv == conv})

        def hint(text, key):
            specs.append({'kind': 'hint', 'key': key, 'text': text})

        room_name = (c.room if c and getattr(c, 'room', None) else '公共大厅')
        sec('公共大厅', key=('sec', 'room'))
        online = len(c.online) if c else 0
        row(CONV_ROOM, room_name, f'{online} 人在线', avatar_nick='厅', dot=ONLINE)

        friends = list(c.friends) if c else []
        sec(f'好友 ({len(friends)})', key=('sec', 'friends'),
            action_text='＋ 加好友', action=self._dialog_add_friend)
        if not friends:
            hint('  还没有好友，点右上「＋ 加好友」', ('hint', 'nofriends'))
        for f in friends:
            on = f in (c.online if c else [])
            subline = '在线' if on else '离线'
            r = ((getattr(c, 'regions', None) or {}).get(f) if c else '') or ''
            if on and r:
                subline += f' · {r}'
            if f.strip().lower() in {str(x).strip().lower()
                                     for x in (getattr(c, 'blocks', None) or [])}:
                subline = '🚫 已拉黑 · ' + subline
            row(conv_user(f), f, subline, avatar_nick=f, dot=ONLINE if on else None)

        reqs = list(c.requests) if c else []
        if reqs:
            sec(f'好友申请 ({len(reqs)})', key=('sec', 'reqs'))
            for r in reqs:
                who = r.get('from', '')
                specs.append({'kind': 'req', 'key': ('req', who), 'who': who,
                              'msg': (r.get('msg') or '').strip()})

        groups = list(c.groups) if c else []
        sec(f'群组 ({len(groups)})', key=('sec', 'groups'),
            actions=[('＋ 建群', self._dialog_create_group),
                     ('＋ 加群', self._dialog_join_group)])
        if not groups:
            hint('  还没有群：点「＋ 建群」新建，或点「＋ 加群」用群号加入',
                 ('hint', 'nogroups'))
        for g in groups:
            conv = 'g:' + str(g['gid'])
            tag = '群主' if g.get('owner') else ('管理员' if g.get('admin') else '')
            subline = f"{len(g.get('members', []))} 人"
            if g.get('no'):
                subline += f" · 群号 {g['no']}"
            if tag:
                subline += f' · 我是{tag}'
            if g.get('announce'):
                subline += ' · 有公告'
            if g.get('joins'):
                subline += f" · 待审批 {len(g['joins'])}"
            row(conv, g['name'], subline, avatar_nick='群' + g['name'])

        joins = []
        for g in groups:
            for j in (g.get('joins') or []):
                joins.append((g, j))
        if joins:
            sec(f'加群申请 ({len(joins)})', key=('sec', 'joins'))
            for g, j in joins:
                who = j.get('from', '')
                specs.append({'kind': 'req', 'key': ('join', str(g.get('gid')), who),
                              'join': True, 'who': who,
                              'msg': (j.get('msg') or '').strip(),
                              'gid': str(g.get('gid')),
                              'gname': g.get('name', '')})
        return specs

    def _rebuild_conv_list(self):
        c = self.client
        if not hasattr(self, '_conv_pool'):
            self._conv_pool = {}
            self._conv_order_prev = None
        specs = self._conv_specs()
        # 侧栏里的会话清单（预加载要用：所有会话都要提前画好，点哪个都是现成的）
        self._conv_ids = [s['conv'] for s in specs if s.get('kind') == 'conv']
        order, made = self._pool_sync(self.conv_list, specs, self._conv_pool,
                                      self._conv_factories())
        self._conv_order_prev = self._pack_order(order, self._conv_order_prev)
        made_n = len(made) if isinstance(made, (list, tuple, set, dict)) else 0
        if made_n > 2:
            write_diag(f'侧栏重建：新建/更新 {made_n} 个控件（会话 {len(self._conv_ids)} 个）')

        # 顶部标题里的「N 人在线」也一起刷新：以前只重建侧栏，头部要等到下一次
        # social 事件才更新，所以别人上线后人数半天不动。
        try:
            self._refresh_header()
        except Exception as e:
            write_log(log_path(), f'!! 刷新头部失败：{e!r}\n{traceback.format_exc()}')
        try:
            self._rebuild_members()
        except Exception as e:
            write_log(log_path(), f'!! 重建成员面板失败：{e!r}\n{traceback.format_exc()}')

    def _conv_factories(self):
        f = getattr(self, '_conv_factories_cache', None)
        if f is None:
            f = {
                'sec': (lambda p, s: self._section(p, s['text'], s.get('action_text'),
                                                  s.get('action'), s.get('actions')),
                        lambda w, s: self._section_update(w, s)),
                'conv': (lambda p, s: self._conv_row(p, s['conv'], s['title'],
                                                     s.get('subtitle') or '',
                                                     s.get('avatar_nick'), s.get('dot')),
                         lambda w, s: self._conv_row_update(w, s)),
                'hint': (self._empty_hint, self._empty_hint_update),
                'req': (lambda p, s: self._req_card(p, s, 'join' if s.get('join') else 'req'),
                        self._req_card_update),
            }
            self._conv_factories_cache = f
        return f

    def _refresh_header(self):
        try:
            title, subtitle = self._conv_title(self.conv)
            self.title_label.configure(text=title)
            self.sub_label.configure(text=subtitle)
        except Exception:
            pass
        # 侧栏底部的「已登录 · 属地 | 服务器 属地」也顺手更新
        try:
            if self.connected and self.client is not None:
                me = getattr(self.client, 'me', '') or ''
                self.me_label.configure(text=f'{me}（我）')
                self.me_sub.configure(text=self._status_text(), text_color=ONLINE)
                self.me_server.configure(text=self._server_text())
                av = self._avatar(me, 40)
                if av is not None:
                    self.me_avatar.configure(image=av)
                n = int(getattr(self.client, 'offline_count', 0) or 0)
                self.offline_badge.configure(text=f'✉ 离线留言 {n}' if n else '')
        except Exception:
            pass
        # 超级管理员才有「控制台」
        try:
            super_user = bool(self.client is not None
                              and getattr(self.client, 'is_super', False))
            if super_user and self.admin_btn.winfo_manager() == '':
                self.admin_btn.pack(side='left', padx=(6, 0))
            elif not super_user and self.admin_btn.winfo_manager() != '':
                self.admin_btn.pack_forget()
        except Exception:
            pass
        # 群聊才显示「群资料/管理」按钮和公告横幅
        try:
            kind = conv_kind(self.conv)
            self.group_btn.configure(state='normal' if kind == 'group' else 'disabled')
            self._refresh_announce()
        except Exception:
            pass
        # 被禁言就把输入区换成「禁言中」
        try:
            self._apply_mute_state()
        except Exception:
            pass

    def _refresh_announce(self):
        gid = str(self.conv)[2:] if conv_kind(self.conv) == 'group' else ''
        info = {}
        if gid and self.client is not None:
            info = (getattr(self.client, 'group_infos', None) or {}).get(gid) or {}
        ann = (info.get('announce') or {}).get('text') or ''
        if ann:
            txt = ann if len(ann) <= 90 else ann[:90] + '…'
            self.announce_label.configure(text=f'📣  群公告：{txt}')
            if self.announce_bar.winfo_manager() == '':
                try:
                    self.announce_bar.pack(fill='x', before=self.body)
                except Exception:
                    self.announce_bar.pack(fill='x')
        elif self.announce_bar.winfo_manager() != '':
            self.announce_bar.pack_forget()

    # ---------- 连接信息 ----------
    def _server_where(self):
        """所连服务器的**位置**（只显示地方，不重复 IP）。

        服务端是异步解析自己的属地的，所以分几种状态显示：
        - `pending` 解析中（客户端常常在服务端解析完成前就登录了）
        - `ok`      具体城市
        - `unknown` 解析失败 → 「属地未知」，让你知道这个功能在、只是没查到
        - `off`     服务端配置里关掉了联网解析
        老版本服务端不下发这个字段就不显示。
        """
        c = self.client
        if c is None:
            return ''
        if not getattr(c, 'server_region_known', True):
            return ''
        region = getattr(c, 'server_region', '') or ''
        state = getattr(c, 'server_region_state', '') or ('ok' if region else 'unknown')
        if region:
            return region
        return {'pending': '解析中…', 'off': '已关闭属地解析'}.get(state, '属地未知')

    def _sync_status(self):
        """把侧栏底部的两行状态（我的属地 / 服务器属地）一起刷新。"""
        try:
            self._set_status(self._status_text(), ONLINE)
            self.me_server.configure(text=self._server_text())
        except Exception:
            pass

    # ---------- 我自己的属地（客户端本地解析，多源） ----------
    def _start_my_region_lookup(self, attempt=0):
        """后台解析「我自己的属地」：先问多个公网 IP 回显接口拿到我的出口 IP，
        再用 **9 个地理数据源**投票出省市。

        为什么要客户端自己也算一遍：服务端只能按「它看到的来源 IP」判定，当你在
        内网 / 开了代理 / 服务器在同机时，它看到的是内网地址（显示「本机」「局域网」），
        或者运营商出口 IP 的登记地跟你在的地方不一致。客户端自己拿到出口 IP 再查，
        通常更贴近你真实的位置。

        **失败必须重试**：这些接口是公网的，会超时、会被挡。以前只试这一次，
        一失败就永远显示服务端那份（「本机」/「局域网」/「属地未知」），
        用户看到的就是「我自己显示的属地不对」。现在最多重试 5 次（间隔递增）。
        """
        if getattr(self, '_region_lookup_running', False):
            return
        self._region_lookup_running = True

        def work():
            ip = region = ''
            try:
                import chat_geo
                try:
                    ip = chat_geo.public_ip() or ''
                except Exception:
                    ip = ''
                if ip:
                    try:
                        info = chat_geo.lookup(ip)
                        # 只认「到了省级」的结果：没有省市的返回值是运营商名字
                        # （format_region 的兜底），拿它当属地看着就是错的，
                        # 这种情况按「没查到」处理，交给上面重试。
                        if info and chat_geo.precision(info) >= 1:
                            region = chat_geo.format_region(info)
                    except Exception:
                        region = ''
            except Exception:
                ip = region = ''
            try:
                self._ui_queue.put(lambda: self._apply_my_region(ip, region, attempt))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _apply_my_region(self, ip, region, attempt=0):
        self._region_lookup_running = False
        try:
            if ip:
                self._my_public_ip = ip
            if region:
                self._my_region_local = region
            detail = ''
            try:
                import chat_geo
                detail = chat_geo.votes_text()
            except Exception:
                detail = ''
            write_diag(f'本地属地解析：IP={self._my_public_ip!r} 属地={self._my_region_local!r}'
                       f' 服务端属地={getattr(self.client, "my_region", "")!r}'
                       f' 第{attempt + 1}次'
                       + (f' 票={detail}' if detail else ''))
            self._sync_status()
        except Exception:
            pass
        if not region and attempt < 4:
            # 这次没查到（接口超时 / 被挡 / 出口 IP 拿不到）：过几秒换个时间点再试
            try:
                self.after(3000 * (attempt + 1),
                           lambda: self._start_my_region_lookup(attempt + 1))
            except Exception:
                pass

    def _status_text(self):
        """第一行：我的登录状态 + 我的属地（附服务端看到的来源 IP，便于核对）。

        谁的属地谁说了算：**客户端自己投过票的结果优先**，服务端那份只当兜底。
        原因是服务端可能还是旧版本、或者它那边的库又把移动出口 IP 记成了北京；
        客户端拿自己的出口 IP 走 9 家库投票，结论更可信（两家以上库一致才算数）。
        服务端说「本机/局域网/属地未知」时更是只能用本地的。
        也可以用 client_config.json 里的 "my_region" 手动写死自己的属地。
        """
        c = self.client
        srv_region = getattr(c, 'my_region', '') or ''
        local = getattr(self, '_my_region_local', '') or ''
        region = local or srv_region
        try:
            fixed = str(load_client_config().get('my_region') or '').strip()
            if fixed:
                region = fixed
        except Exception:
            pass
        # 显示的 IP 优先用「客户端自己查到的出口 IP」：服务端在同机/内网时看到的是
        # 127.0.0.1 / 192.168.x.x，把它显示成「我的 IP」会让用户以为属地判错了。
        ip = str(getattr(self, '_my_public_ip', '') or getattr(self, '_my_ip', '') or '')
        text = '已登录'
        if region:
            text += f' · {region}'
        if ip:
            text += f'（IP {ip}）'
        return text

    def _server_text(self):
        """第二处：所连服务器的属地（放在「更换头像」右边，小字号）。

        太长就省略，宁可显示成「服务器 加利福尼亚…」也不要挤爆/换行错位。
        """
        where = self._server_where()
        if not where:
            return ''
        text = f'服务器 {where}'
        if len(text) > 15:
            text = text[:14] + '…'
        return text

    # ---------- 被禁言：把输入区收起来，改成「禁言中」 ----------
    def _mute_left(self):
        """当前会话我被禁言还剩多少秒：0 没被禁言，-1 永久。仅群聊生效。"""
        c = self.client
        if c is None or conv_kind(self.conv) != 'group':
            return 0
        try:
            return int(c.my_mute(str(self.conv)[2:]))
        except Exception:
            return 0

    @staticmethod
    def _mute_text(left):
        if left is None or left == 0:
            return '禁言中'
        if left < 0:
            return '你已被永久禁言'
        mins = max(1, (left + 59) // 60)
        if left >= 86400:
            return f'你已被禁言（还剩 {left // 86400} 天 {left % 86400 // 3600} 小时）'
        if left >= 3600:
            return f'你已被禁言（还剩 {left // 3600} 小时 {left % 3600 // 60} 分钟）'
        return f'你已被禁言（还剩 {mins} 分钟）'

    def _lock_state(self):
        """输入区该不该锁：返回 (提示文字, 小字说明)；空文字表示可以正常发言。

        两种情况会锁：群里被禁言、私聊里已经不是好友 / 被拉黑。
        """
        left = self._mute_left()
        if left:
            hint = ('群主或管理员解禁后即可发言；这条提示会自动消失'
                    if left > 0 else '永久禁言，需要管理员解除')
            return self._mute_text(left), hint
        why = self._im_blocked(self.conv)
        if why:
            return '🔒  无法发送消息', why + '（点好友头像右键可以删除 / 解除拉黑）'
        return '', ''

    def _apply_mute_state(self, force=False):
        """按当前会话的状态，在「输入框」和「锁住的提示条」之间切换。"""
        if not hasattr(self, 'mute_bar'):
            return
        text, hint = self._lock_state()
        if not text:
            # 不锁的时候，顺手确认输入区是「能用」的：万一别处把它 disable 过
            # （比如掉线时禁用了按钮），这里一定把它还回来，不能让用户发不出消息。
            # 注意：断线时本来就该禁用，所以只在「连着服务器」时才还回来。
            try:
                if self.connected and str(self.input.cget('state')) != 'normal':
                    for w in (self.input, self.send_btn, self.emoji_btn,
                              self.file_btn, self.mention_btn, self.chess_btn):
                        try:
                            w.configure(state='normal')
                        except Exception:
                            pass
            except Exception:
                pass
        if not force and text == getattr(self, '_lock_text', None) \
                and bool(text) == bool(getattr(self, 'muted_view', False)):
            return                        # 状态没变：一个控件都不用碰
        self._lock_text = text
        try:
            if text:
                if not self.muted_view:
                    self.muted_view = True
                    try:
                        self.panel.pack_forget()
                    except Exception:
                        pass
                    self.composer.pack_forget()
                    self.mute_bar.pack(fill='x', padx=12, pady=(8, 10))
                self.mute_label.configure(text=text)
                self.mute_sub.configure(text=hint)
            else:
                if self.muted_view:
                    self.muted_view = False
                    self.mute_bar.pack_forget()
                    self.composer.pack(fill='x', padx=12, pady=10)
                    # 只在「刚解锁」这一下把输入区还回来。
                    # 以前这里是每 60ms 无脑 configure 一遍，纯属浪费。
                    if self.connected:
                        for w in (self.input, self.send_btn, self.emoji_btn,
                                  self.file_btn, self.mention_btn, self.chess_btn):
                            try:
                                w.configure(state='normal')
                            except Exception:
                                pass
        except Exception:
            pass

    # ---------- 右侧成员面板（QQ 风格） ----------
    def _toggle_members(self):
        self.members_on = not self.members_on
        self._rebuild_members()
        self._toast('已显示成员列表' if self.members_on else '已收起成员列表')

    def _member_names(self):
        """当前会话要展示的人。

        返回 (rows, is_group)；每行是 dict：nick / online / role / mute。
        群聊优先用服务端下发的群资料（带角色、禁言状态、离线的成员也在）。
        """
        c = self.client
        if c is None:
            return [], False
        kind = conv_kind(self.conv)
        online = set(c.online or [])
        if kind == 'group':
            gid = str(self.conv)[2:]
            info = (getattr(c, 'group_infos', None) or {}).get(gid) or {}
            rows = []
            for m in (info.get('members') or []):
                n = m.get('nick') or ''
                if not n:
                    continue
                rows.append({'nick': n, 'online': n in online,
                             'role': m.get('role') or 'member',
                             'mute': int(m.get('mute') or 0)})
            if not rows:      # 还没拿到群资料就先退回到简单的成员列表
                for g in (c.groups or []):
                    if str(g.get('gid')) == gid:
                        rows = [{'nick': n, 'online': n in online, 'role': 'member',
                                 'mute': 0} for n in (g.get('members') or [])]
                        break
            rows.sort(key=lambda r: (not r['online'], r['role'] != 'owner',
                                     r['role'] != 'admin', r['nick']))
            return rows, True
        return ([{'nick': n, 'online': True, 'role': 'member', 'mute': 0}
                 for n in sorted(online)], False)

    def _rebuild_members(self):
        """重建右侧成员栏；大厅/群聊显示列表，私聊或用户收起时隐藏。"""
        panel = getattr(self, 'members', None)
        if panel is None:
            return
        try:
            if not panel.winfo_exists():
                return
        except Exception:
            return

        c = self.client
        kind = conv_kind(self.conv)
        hidden = c is None or kind == 'friend' or not self.members_on
        rows, is_group = ([], False) if hidden else self._member_names()
        people = [r for r in rows if r.get('nick')]
        self._member_live_rows = people
        # 列表内容没变就不动：在线人数一变就整块重建的话，
        # 人一多（上限 200）会闪、还会把滚动位置清零。
        sig = (hidden, kind,
               tuple((r['nick'], r['online'], r['role'], r['mute']) for r in people),
               tuple(getattr(c, 'friends', None) or ()),
               tuple(sorted((getattr(c, 'regions', None) or {}).items())),
               tuple(sorted((getattr(c, 'avatar_ver', None) or {}).items())))
        if sig == getattr(self, '_member_sig', None):
            return
        self._member_sig = sig
        write_diag(f'成员面板重建：{len(people)} 人（会话 {self.conv!r} 群={is_group}）')

        if hidden:
            panel.pack_forget()
            return
        self._member_ensure(panel)
        ref = getattr(self.messages, '_parent_frame', None) or self.messages
        if panel.winfo_manager() != 'pack':
            try:
                panel.pack(side='right', fill='y', before=ref)
            except Exception:
                panel.pack(side='right', fill='y')

        others = [r for r in people if r['nick'] != c.me]
        online_n = sum(1 for r in people if r['online'])
        if is_group:
            head = f"群成员 {len(people)} 人 · {online_n} 人在线"
        else:
            head = f'在线成员 {len(people)} 人'
        if str(self._member_head.cget('text')) != head:
            self._member_head.configure(text=head)

        shown = people[:MEMBER_ROWS_MAX]
        specs = [{'kind': 'row', 'key': ('m', r['nick']), 'info': r,
                  'is_me': r['nick'] == c.me, 'is_group': is_group}
                 for r in shown]
        if not others:
            tip = ('群里还没有别人，去好友列表拉人进来吧'
                   if is_group else '现在只有你一个人在线')
            specs.append({'kind': 'hint', 'key': ('m', '__tip__'), 'text': tip,
                          'wraplength': 170, 'pady': 8, 'padx': 10})
        if len(people) > len(shown):
            specs.append({'kind': 'hint', 'key': ('m', '__more__'),
                          'text': f'…… 还有 {len(people) - len(shown)} 人',
                          'pady': 4, 'padx': 10})
        order, _made = self._pool_sync(self._member_box, specs, self._member_pool,
                                       self._member_factories())
        self._member_order_prev = self._pack_order(order, self._member_order_prev)

        foot = ('右键成员：@他 / 加好友 / 管理' if is_group
                else '右键成员：@他 / 加好友')
        if str(self._member_foot.cget('text')) != foot:
            self._member_foot.configure(text=foot)

    def _member_ensure(self, panel):
        """成员区只建一次：标题 + 滚动区 + 底部提示。以后只改里面的内容。"""
        if self._alive(getattr(self, '_member_head', None)) \
                and self._alive(getattr(self, '_member_box', None)):
            return
        for w in panel.winfo_children():
            w.destroy()
        self._member_pool = {}
        self._member_order_prev = None
        self._member_head = ctk.CTkLabel(panel, text='', anchor='w', height=24,
                                         text_color=TEXT_DIM,
                                         font=ctk.CTkFont(family=FONT, size=12,
                                                          weight='bold'))
        self._member_head.pack(fill='x', padx=12, pady=(10, 4))
        self._member_box = ctk.CTkScrollableFrame(
            panel, fg_color='transparent', corner_radius=0,
            scrollbar_fg_color='transparent', scrollbar_button_color=SCROLL_BTN,
            scrollbar_button_hover_color=SCROLL_HOVER)
        self._member_box.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        self._member_foot = ctk.CTkLabel(panel, text='', anchor='w', height=18,
                                         text_color=TEXT_DIM,
                                         font=ctk.CTkFont(family=FONT, size=10))
        self._member_foot.pack(fill='x', padx=12, pady=(0, 8))

    def _member_factories(self):
        f = getattr(self, '_member_factories_cache', None)
        if f is None:
            f = {
                'row': (lambda p, s: self._member_row(p, s['info'], s['is_me'],
                                                      s['is_group']),
                        self._member_row_update),
                'hint': (self._empty_hint, self._member_hint_update),
            }
            self._member_factories_cache = f
        return f

    @staticmethod
    def _member_hint_update(lbl, spec):
        if str(lbl.cget('text')) != spec['text']:
            lbl.configure(text=spec['text'])
        return True

    def _my_role(self, gid):
        c = self.client
        if c is None:
            return ''
        info = (getattr(c, 'group_infos', None) or {}).get(str(gid)) or {}
        if info.get('role'):
            return info.get('role')
        for g in (c.groups or []):
            if str(g.get('gid')) == str(gid):
                if g.get('owner'):
                    return 'owner'
                return 'admin' if g.get('admin') else 'member'
        return ''

    def _member_actions(self, nick, role, mute, gid=None):
        """成员右键菜单的内容：[(标签, 动作名, 回调), ...]。

        做成纯数据是为了能直接测（真的弹菜单在测试里不好断言）。
        用户反馈：行内那排「⋯ / @」按钮太鸡肋，改成右键菜单。
        """
        gid = str(gid or (str(self.conv)[2:] if conv_kind(self.conv) == 'group' else ''))
        c = self.client
        out = []
        me_role = self._my_role(gid) if gid else ''
        low = (nick or '').strip().lower()
        friends = {str(x).strip().lower() for x in (c.friends or [])} if c else set()
        blocks = {str(x).strip().lower()
                  for x in (getattr(c, 'blocks', None) or [])} if c else set()
        out.append(('@ 提及他', 'mention', lambda n=nick: self._mention_member(n)))
        if c is not None and low not in friends:
            out.append(('加为好友', 'add_friend',
                        lambda n=nick: self._dialog_add_friend(n)))
        if gid and me_role == 'owner' and role != 'owner':
            if role == 'admin':
                out.append(('取消管理员', 'demote',
                            lambda i=gid, n=nick: self._group_admin(i, n, False)))
            else:
                out.append(('设为管理员', 'promote',
                            lambda i=gid, n=nick: self._group_admin(i, n, True)))
        if gid and self._can_manage_member(gid, nick, role):
            if mute:
                out.append(('解除禁言', 'unmute',
                            lambda i=gid, n=nick: self._group_mute(i, n, -1)))
            else:
                out.append(('禁言 10 分钟', 'mute10',
                            lambda i=gid, n=nick: self._group_mute(i, n, 10)))
                out.append(('禁言 1 小时', 'mute60',
                            lambda i=gid, n=nick: self._group_mute(i, n, 60)))
                out.append(('禁言 1 天', 'mute1440',
                            lambda i=gid, n=nick: self._group_mute(i, n, 1440)))
                out.append(('永久禁言', 'mute0',
                            lambda i=gid, n=nick: self._group_mute(i, n, 0)))
            out.append(('移出本群', 'kick',
                        lambda i=gid, n=nick: self._group_kick(i, n)))
        # 已经是好友：私聊 + 拉黑/解除 + 删除好友（和好友列表右键一致）
        if c is not None and low in friends:
            out.append(('发起私聊', 'chat',
                        lambda n=nick: self._select_conv(conv_user(n))))
            if low in blocks:
                out.append(('移出黑名单', 'unblock',
                            lambda n=nick: self.client.block_friend(n, False)))
            else:
                out.append(('加入黑名单', 'block',
                            lambda n=nick: self._confirm_block(n)))
            out.append(('删除好友', 'del_friend',
                        lambda n=nick: self._confirm_del_friend(n)))
        return out

    def _member_menu(self, nick, role, mute, event=None, gid=None):
        """成员行的右键菜单：@他 / 加好友 / 设为管理员 / 禁言 / 移出群。"""
        actions = self._member_actions(nick, role, mute, gid)
        if not actions:
            return
        menu = tk.Menu(self, tearoff=0, bg=BG_PANEL, fg=TEXT, activebackground=BG_HOVER,
                       activeforeground=TEXT, bd=0, font=(FONT, 10))
        for label, _key, cb in actions:
            menu.add_command(label=label, command=cb)
        try:
            if event is not None:
                menu.tk_popup(event.x_root, event.y_root)
            else:
                menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _popup_member_menu(self, event, nick, role, mute, gid=None):
        try:
            self._member_menu(nick, role, mute, event=event, gid=gid)
        except Exception as e:
            write_log(log_path(), f'!! 弹成员菜单失败：{e!r}\n{traceback.format_exc()}')
        return 'break'

    def _member_row(self, parent, info, is_me=False, is_group=False):
        """建一行成员。绑定只在建行时做一次，里面取的数据都是「点的时候现查」，
        所以之后改文字/头像不用重新绑事件。"""
        c = self.client
        nick = info.get('nick') or ''
        online = bool(info.get('online'))
        row = ctk.CTkFrame(parent, fg_color='transparent', corner_radius=8)
        row.pack(fill='x', pady=1)
        row._pool_pack = {'fill': 'x', 'pady': 1}
        av = self._avatar(nick, 24)
        av_label = None
        if av is not None:
            av_label = ctk.CTkLabel(row, image=av, text='', fg_color='transparent',
                                    text_color=TEXT)
            av_label.pack(side='left', padx=(4, 6), pady=3)
        dot_lbl = None
        if online:
            dot_lbl = ctk.CTkLabel(row, text='●', text_color=ONLINE, width=10,
                                   font=ctk.CTkFont(family=FONT, size=9))
            dot_lbl.pack(side='left')
        col = ctk.CTkFrame(row, fg_color='transparent')
        col.pack(side='left', fill='x', expand=True)
        title, region = self._member_texts(info, is_me, is_group)
        nick_lbl = ctk.CTkLabel(col, text=title, anchor='w', height=16, text_color=TEXT,
                                font=ctk.CTkFont(family=FONT, size=12))
        nick_lbl.pack(fill='x')
        region_lbl = ctk.CTkLabel(col, text=region, anchor='w', height=13,
                                  text_color=REGION,
                                  font=ctk.CTkFont(family=FONT, size=9))
        if region:
            region_lbl.pack(fill='x')
        row._parts = {'nick': nick, 'title': nick_lbl, 'region': region_lbl,
                      'dot': dot_lbl, 'avatar': av_label, 'is_me': is_me,
                      'is_group': is_group, 'online': online}
        if is_me:
            return row

        # 行内不再放「@ / ＋ / ⋯」小按钮（用户反馈太鸡肋）：改成右键菜单
        # e 给了默认值：Tk 在极端情况下（控件正在销毁等）可能不带事件调用，
        # 这时候按鼠标当前位置弹菜单即可，不至于抛异常刷日志。
        popup = lambda e=None, n=nick: self._popup_member_menu(
            e, n, *self._member_live(n))          # 角色/禁言点的时候现查
        for w in (row, col):
            w.bind('<Button-3>', popup)
        for child in list(row.winfo_children()) + list(col.winfo_children()):
            try:
                child.bind('<Button-3>', popup)
            except Exception:
                pass
        row.bind('<Enter>', lambda *a, r=row: r.configure(fg_color=BG_HOVER))
        row.bind('<Leave>', lambda *a, r=row: r.configure(fg_color='transparent'))
        # 是好友就点一下进私聊 —— 好友关系是随时变的，所以也放到点击时判断
        self._bind_all_children(row, lambda *a, n=nick: self._member_click(n))
        return row

    def _member_live(self, nick):
        """成员行点右键时现查角色/禁言，免得重建整行来更新闭包。"""
        for r in (getattr(self, '_member_live_rows', None) or []):
            if r.get('nick') == nick:
                return r.get('role') or 'member', int(r.get('mute') or 0)
        return 'member', 0

    def _member_click(self, nick):
        c = self.client
        if c is not None and nick in (c.friends or []):
            self._select_conv(conv_user(nick))

    def _member_row_update(self, row, spec):
        """原地更新一行成员；返回 False 表示形态变了（有无绿点/头像），要重建。"""
        p = getattr(row, '_parts', None)
        info = spec['info']
        if p is None or p['is_me'] != spec['is_me'] or p['is_group'] != spec['is_group']:
            return False
        online = bool(info.get('online'))
        if bool(p.get('dot') is not None) != online:
            return False
        nick = info.get('nick') or ''
        if p.get('nick') != nick:
            return False            # 行的身份变了（正常不会），重建更保险
        title, region = self._member_texts(info, spec['is_me'], spec['is_group'])
        if str(p['title'].cget('text')) != title:
            p['title'].configure(text=title)
        if str(p['region'].cget('text')) != region:
            p['region'].configure(text=region)
        if (region == '') != (not p['region'].winfo_manager()):
            if region:
                p['region'].pack(fill='x')
            else:
                p['region'].pack_forget()
        av = self._avatar(nick, 24)
        if (av is None) != (p['avatar'] is None):
            return False
        if av is not None and p['avatar'] is not None and av is not p.get('avatar_image'):
            try:
                p['avatar'].configure(image=av)
            except Exception:
                return False
            p['avatar_image'] = av
        p['online'] = online
        return True

    def _member_texts(self, info, is_me, is_group):
        """成员行的「昵称+标记」和「属地」两段文字。"""
        c = self.client
        nick = info.get('nick') or ''
        role = info.get('role') or 'member'
        mute = int(info.get('mute') or 0)
        tail = ''
        role_cn = {'owner': '群主', 'admin': '管理员', 'member': ''}.get(role, '')
        if is_me:
            tail = f'（我{("·" + role_cn) if role_cn else ""}）'
        elif is_group and role == 'owner':
            tail = ' 👑'
        elif is_group and role == 'admin':
            tail = ' ★'
        if is_group and mute:
            tail += ' 🔇'
        region = (getattr(c, 'regions', None) or {}).get(nick, '') if c else ''
        if is_me and not region:
            region = getattr(c, 'my_region', '') or ''
        if is_group and role == 'owner':
            region = ('群主' + (' · ' + region if region else ''))
        elif is_group and role == 'admin':
            region = ('管理员' + (' · ' + region if region else ''))
        if is_group and mute:
            region = ('已禁言' + (' · ' + region if region else ''))
        return nick + tail, region

    def _can_manage_member(self, gid, nick, role):
        """我能不能管这个人（群主管所有人，管理员管普通成员）。"""
        me_role = self._my_role(gid)
        c = self.client
        if me_role not in ('owner', 'admin') or c is None:
            return False
        if nick == c.me:
            return False
        if role == 'owner':
            return False
        if role == 'admin' and me_role != 'owner':
            return False
        return True

    def _mention_member(self, nick):
        """在输入框里插入 @昵称，并聚焦，等用户接着说。"""
        try:
            self._insert('@' + nick + ' ')
            if self._panel_visible():
                self.panel.pack_forget()
            self.input.focus_set()
        except Exception:
            pass

    # ================= 群资料 / 群管理 =================
    def _answer_join(self, gid, nick, accept):
        """在主页上直接处理加群申请。"""
        if self.client is None:
            return
        self.client.group_join_answer(str(gid), nick, accept)
        self._toast(f'已{"同意" if accept else "拒绝"}「{nick}」的加群申请')

    def _open_group_info(self):
        gid = str(self.conv)[2:]
        if conv_kind(self.conv) != 'group' or not gid:
            self._toast('先在左侧选择一个群')
            return
        if self.client is None:
            return
        self.client.group_info(gid)
        win = getattr(self, '_group_win', None)
        try:
            if win is not None and win.winfo_exists() and self._group_win_gid == gid:
                win.lift()
                return
        except Exception:
            pass
        win = ctk.CTkToplevel(self)
        win.title('群资料' + APP_SUFFIX)
        win.configure(fg_color=BG_APP)
        win.geometry('560x640')
        win.transient(self)
        self._group_win = win
        self._group_win_gid = gid
        # 新开的窗口一定要真画一次：指纹是给「同一个窗口里的重复刷新」用的，
        # 不复位的话关掉再打开会得到一个空白窗口。
        self._group_win_sig = None
        win.protocol('WM_DELETE_WINDOW', lambda: self._close_group_window())
        self._render_group_window(force=True)

    def _close_group_window(self):
        try:
            if self._group_win is not None:
                self._group_win.destroy()
        except Exception:
            pass
        self._group_win = None
        self._group_win_gid = None
        self._group_win_sig = None

    def _group_ctx(self):
        gid = getattr(self, '_group_win_gid', None)
        c = self.client
        if not gid or c is None:
            return None, {}, ''
        info = (getattr(c, 'group_infos', None) or {}).get(str(gid)) or {}
        return str(gid), info, (info.get('role') or self._my_role(gid))

    def _render_group_window(self, force=False):
        win = getattr(self, '_group_win', None)
        if win is None:
            return
        try:
            if not win.winfo_exists():
                self._group_win = None
                return
        except Exception:
            self._group_win = None
            return
        gid, info, role = self._group_ctx()
        # 内容没变就不重建（不然服务端一推资料，整个窗口就闪一下）
        sig = (gid, role, repr(info))
        if not force and sig == getattr(self, '_group_win_sig', None):
            return
        self._group_win_sig = sig
        for w in win.winfo_children():
            w.destroy()
        c = self.client
        name = info.get('name') or '群聊'
        no = info.get('no') or gid
        can_manage = role in ('owner', 'admin')

        head = ctk.CTkFrame(win, fg_color=BG_PANEL, corner_radius=0)
        head.pack(fill='x')
        ctk.CTkLabel(head, text=name, anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=17, weight='bold')).pack(
            side='left', padx=(16, 8), pady=10)
        role_cn = {'owner': '群主', 'admin': '管理员', 'member': '成员'}.get(role, '')
        ctk.CTkLabel(head, text=f'群号 {no}' + (f' · 我是{role_cn}' if role_cn else ''),
                     anchor='w', text_color=REGION,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(side='left', pady=10)
        ctk.CTkButton(head, text='复制群号', width=76, height=26, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                      hover_color=BG_HOVER, text_color=TEXT_DIM,
                      font=ctk.CTkFont(family=FONT, size=11),
                      command=lambda t=no: self._copy(t)).pack(side='right', padx=(4, 14))

        body = ctk.CTkFrame(win, fg_color='transparent')
        body.pack(fill='both', expand=True, padx=12, pady=(8, 0))

        # ---- 群公告 ----
        card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12)
        card.pack(fill='x', pady=(0, 8))
        bar = ctk.CTkFrame(card, fg_color='transparent')
        bar.pack(fill='x', padx=12, pady=(8, 2))
        ctk.CTkLabel(bar, text='📣  群公告', anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(side='left')
        ann = (info.get('announce') or {}).get('text') or ''
        if can_manage:
            ctk.CTkButton(bar, text='发布 / 修改', width=88, height=24, corner_radius=8,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=self._edit_announce).pack(side='right', padx=(4, 0))
            if ann:
                ctk.CTkButton(bar, text='清除', width=52, height=24, corner_radius=8,
                              fg_color='transparent', border_width=1,
                              border_color=FIELD_BORDER, hover_color=BG_HOVER,
                              text_color=TEXT_DIM, font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda g=gid: self._group_announce(g, '')).pack(
                    side='right')
        self._group_ann_entry = None
        if ann:
            who = (info.get('announce') or {}).get('by') or ''
            txt = ann if len(ann) <= 200 else ann[:200] + '…'
            ctk.CTkLabel(card, text=txt, anchor='w', justify='left', wraplength=490,
                         text_color=TEXT_SOFT,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(
                fill='x', padx=14, pady=(2, 0))
            ctk.CTkLabel(card, text=f'—— {who}', anchor='e', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=10)).pack(
                anchor='e', padx=14, pady=(0, 8))
        else:
            ctk.CTkLabel(card, text='（还没有公告）', anchor='w', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(
                fill='x', padx=14, pady=(2, 10))

        # ---- 拉人入群：任何人都能拉自己的好友（要管理员 + 本人双方同意） ----
        if True:
            card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12)
            card.pack(fill='x', pady=(0, 8))
            bar = ctk.CTkFrame(card, fg_color='transparent')
            bar.pack(fill='x', padx=14, pady=(8, 4))
            ctk.CTkLabel(bar, text='➕  邀请好友入群', anchor='w', text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(
                side='left')
            ctk.CTkButton(bar, text='选好友', width=76, height=24, corner_radius=12,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=lambda: self._dialog_invite_friend(gid)).pack(side='right')
            ctk.CTkLabel(card, text='拉人需要「群主/管理员同意」+「对方本人同意」，'
                                    '两边都点头才会进群。',
                         anchor='w', justify='left', wraplength=490, text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=10)).pack(
                fill='x', padx=14, pady=(0, 6))

        invites = info.get('invites') or []
        if can_manage and invites:
            card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12)
            card.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(card, text=f'🤝  待批准的拉人（{len(invites)}）', anchor='w',
                         text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(
                anchor='w', padx=14, pady=(8, 4))
            for inv in invites:
                row = ctk.CTkFrame(card, fg_color='transparent')
                row.pack(fill='x', padx=10, pady=2)
                col = ctk.CTkFrame(row, fg_color='transparent')
                col.pack(side='left', fill='x', expand=True)
                ctk.CTkLabel(col, text=f"{inv.get('nick', '')}"
                                       f"（{inv.get('by', '')} 拉进来的）",
                             anchor='w', text_color=TEXT,
                             font=ctk.CTkFont(family=FONT, size=12)).pack(fill='x')
                state = '对方已同意，等你确认' if inv.get('nick_ok') else '等对方本人确认'
                ctk.CTkLabel(col, text=state, anchor='w', text_color=REGION,
                             font=ctk.CTkFont(family=FONT, size=10)).pack(fill='x')
                ctk.CTkButton(row, text='同意', width=50, height=24, corner_radius=12,
                              fg_color=OK_GREEN, hover_color=OK_GREEN_DIM,
                              text_color=ON_ACCENT,
                              font=ctk.CTkFont(family=FONT, size=11, weight='bold'),
                              command=lambda n=inv.get('nick'):
                              self.client.group_invite_ok(gid, n, True)
                              ).pack(side='right', padx=(4, 0))
                ctk.CTkButton(row, text='拒绝', width=50, height=24, corner_radius=12,
                              fg_color=NO_RED, hover_color=NO_RED_DIM,
                              text_color=ON_ACCENT,
                              font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda n=inv.get('nick'):
                              self.client.group_invite_ok(gid, n, False)
                              ).pack(side='right', padx=(4, 0))

        # ---- 加群申请（有权限才显示） ----
        joins = info.get('joins') or []
        if can_manage and joins:
            card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12)
            card.pack(fill='x', pady=(0, 8))
            ctk.CTkLabel(card, text=f'📥  加群申请（{len(joins)}）', anchor='w',
                         text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(
                anchor='w', padx=14, pady=(8, 4))
            for j in joins:
                row = ctk.CTkFrame(card, fg_color='transparent')
                row.pack(fill='x', padx=10, pady=2)
                col = ctk.CTkFrame(row, fg_color='transparent')
                col.pack(side='left', fill='x', expand=True)
                ctk.CTkLabel(col, text=j.get('from', ''), anchor='w', text_color=TEXT,
                             font=ctk.CTkFont(family=FONT, size=12)).pack(fill='x')
                if j.get('msg'):
                    ctk.CTkLabel(col, text=f'“{j["msg"]}”', anchor='w', justify='left',
                                 wraplength=330, text_color=TEXT_SOFT,
                                 font=ctk.CTkFont(family=FONT, size=10)).pack(fill='x')
                ctk.CTkButton(row, text='同意', width=50, height=24, corner_radius=12,
                              fg_color=OK_GREEN, hover_color=OK_GREEN_DIM,
                              text_color=ON_ACCENT,
                              font=ctk.CTkFont(family=FONT, size=11, weight='bold'),
                              command=lambda n=j.get('from'): self._group_join_answer(n, True)
                              ).pack(side='right', padx=(4, 0))
                ctk.CTkButton(row, text='拒绝', width=50, height=24, corner_radius=12,
                              fg_color=NO_RED, hover_color=NO_RED_DIM,
                              text_color=ON_ACCENT,
                              font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda n=j.get('from'): self._group_join_answer(n, False)
                              ).pack(side='right', padx=(4, 0))
            ctk.CTkFrame(card, height=6, fg_color='transparent').pack()

        # ---- 群文件 ----
        card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12)
        card.pack(fill='x', pady=(0, 8))
        bar = ctk.CTkFrame(card, fg_color='transparent')
        bar.pack(fill='x', padx=12, pady=(8, 2))
        files = info.get('files') or []
        ctk.CTkLabel(bar, text=f'📁  群文件（{len(files)}）', anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(side='left')
        ctk.CTkButton(bar, text='上传文件', width=76, height=24, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=11),
                      command=self._upload_group_file).pack(side='right')
        if not files:
            ctk.CTkLabel(card, text='（群文件是空的，上传的图片/文件都会出现在这里）',
                         anchor='w', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(
                fill='x', padx=14, pady=(2, 10))
        for f in files[:8]:
            row = ctk.CTkFrame(card, fg_color='transparent')
            row.pack(fill='x', padx=12, pady=2)
            icon = {'image': '🖼', 'video': '🎬'}.get(f.get('kind'), '📄')
            ctk.CTkLabel(row, text=f'{icon} {f.get("name", "")}', anchor='w',
                         text_color=TEXT, font=ctk.CTkFont(family=FONT, size=12)).pack(
                side='left')
            ctk.CTkLabel(row, text=f'{human_size(int(f.get("size") or 0))} · '
                                   f'{f.get("from", "")}', anchor='e', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=10)).pack(side='right', padx=6)
            ctk.CTkButton(row, text='下载', width=48, height=22, corner_radius=8,
                          fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                          hover_color=BG_HOVER, text_color=ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=lambda fid=f.get('fid'): self._download_group_file(fid)
                          ).pack(side='right', padx=4)
            if can_manage:
                ctk.CTkButton(row, text='删除', width=48, height=22, corner_radius=8,
                              fg_color='transparent', hover_color=BG_HOVER,
                              text_color=DANGER, font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda fid=f.get('fid'): self._del_group_file(fid)
                              ).pack(side='right')
        if len(files) > 8:
            ctk.CTkLabel(card, text=f'…… 还有 {len(files) - 8} 个', anchor='w',
                         text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(
                fill='x', padx=14, pady=(0, 8))

        # ---- 群成员 ----
        card = ctk.CTkFrame(body, fg_color=BG_PANEL, corner_radius=12)
        card.pack(fill='both', expand=True, pady=(0, 8))
        members = info.get('members') or []
        ctk.CTkLabel(card, text=f'👥  群成员（{len(members)}/{MAX_GROUP_MEMBERS}）', anchor='w',
                     text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(
            anchor='w', padx=14, pady=(8, 4))
        mbox = ctk.CTkScrollableFrame(card, fg_color='transparent', corner_radius=0,
                                      scrollbar_fg_color='transparent',
                                      scrollbar_button_color=SCROLL_BTN,
                                      scrollbar_button_hover_color=SCROLL_HOVER, height=140)
        mbox.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        me = c.me if c else ''
        for m in members:
            nick = m.get('nick') or ''
            row = ctk.CTkFrame(mbox, fg_color='transparent')
            row.pack(fill='x', pady=1)
            tag = {'owner': ' 👑群主', 'admin': ' ★管理员'}.get(m.get('role'), '')
            mute = int(m.get('mute') or 0)
            if mute:
                tag += ' 🔇'
            ctk.CTkLabel(row, text=nick + tag, anchor='w', text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(side='left', padx=4)
            if nick == me:
                continue
            # 这里保留原来的「管理 / 加好友」按钮（用户说这样也挺好），
            # 同时也能右键（和右侧成员面板一致）
            role_v = m.get('role') or 'member'
            for w in (row,) + tuple(row.winfo_children()):
                try:
                    w.bind('<Button-3>',
                           lambda e, n=nick, r=role_v, mu=mute, i=gid:
                           self._popup_member_menu(e, n, r, mu, gid=i))
                except Exception:
                    pass
            if self._can_manage_member(gid, nick, role_v):
                ctk.CTkButton(row, text='管理', width=52, height=22, corner_radius=8,
                              fg_color='transparent', border_width=1,
                              border_color=FIELD_BORDER, hover_color=BG_HOVER,
                              text_color=TEXT_DIM, font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda n=nick, r=role_v, mu=mute, i=gid:
                              self._member_menu(n, r, mu, gid=i)).pack(side='right', padx=2)
            if nick not in (c.friends or []) and c is not None:
                ctk.CTkButton(row, text='加好友', width=58, height=22, corner_radius=8,
                              fg_color='transparent', hover_color=BG_HOVER, text_color=ACCENT,
                              font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda n=nick: self._dialog_add_friend(n)).pack(
                    side='right', padx=2)

        foot = ctk.CTkFrame(win, fg_color='transparent')
        foot.pack(fill='x', padx=12, pady=(0, 12))
        ctk.CTkButton(foot, text='退出该群', height=34, corner_radius=10,
                      fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                      hover_color=BG_HOVER, text_color=DANGER,
                      font=ctk.CTkFont(family=FONT, size=12),
                      command=self._leave_group).pack(side='right')
        ctk.CTkButton(foot, text='刷新', height=34, corner_radius=10,
                      fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                      hover_color=BG_HOVER, text_color=TEXT_DIM,
                      font=ctk.CTkFont(family=FONT, size=12),
                      command=lambda g=gid: self.client.group_info(g)).pack(side='right',
                                                                           padx=(0, 8))

    # ---------- 群操作（界面侧） ----------
    def _edit_announce(self):
        gid, info, _role = self._group_ctx()
        if not gid:
            return
        cur = (info.get('announce') or {}).get('text') or ''
        box = ctk.CTkToplevel(self)
        box.title('发布群公告' + APP_SUFFIX)
        box.configure(fg_color=BG_PANEL)
        box.geometry('460x300')
        box.transient(self)
        ctk.CTkLabel(box, text='群公告', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=15, weight='bold')).pack(pady=(16, 2))
        ctk.CTkLabel(box, text=f'最多 {GROUP_ANNOUNCE_MAX} 字，留空表示清除公告',
                     text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=11)).pack()
        txt = ctk.CTkTextbox(box, height=140, corner_radius=10, wrap='word',
                             fg_color=FIELD_BG, border_width=1, border_color=FIELD_BORDER,
                             text_color=TEXT, font=ctk.CTkFont(family=FONT, size=13))
        txt.pack(fill='both', expand=True, padx=20, pady=12)
        if cur:
            txt.insert('1.0', cur)
        err = ctk.CTkLabel(box, text='', anchor='w', text_color=WARN, height=16,
                           font=ctk.CTkFont(family=FONT, size=11))
        err.pack(fill='x', padx=20)

        def submit():
            text = txt.get('1.0', 'end-1c').strip()
            if len(text) > GROUP_ANNOUNCE_MAX:
                err.configure(text=f'⚠  公告最多 {GROUP_ANNOUNCE_MAX} 字')
                return
            self._group_announce(gid, text)
            box.destroy()
        ctk.CTkButton(box, text='发布', height=38, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=13),
                      command=submit).pack(fill='x', padx=20, pady=(0, 14))
        box.after(60, lambda: (box.lift(), txt.focus_force()))

    def _group_announce(self, gid, text):
        if self.client is not None:
            self.client.group_announce(gid, text)

    def _group_admin(self, gid, nick, on):
        if self.client is not None:
            self.client.group_admin(gid, nick, on)

    def _group_mute(self, gid, nick, minutes):
        if self.client is not None:
            self.client.group_mute(gid, nick, minutes)

    def _group_kick(self, gid, nick):
        def do():
            if self.client is not None:
                self.client.group_kick(gid, nick)
        self._confirm(f'把「{nick}」移出本群？', do)

    def _group_join_answer(self, nick, accept):
        gid, _info, _role = self._group_ctx()
        if gid and self.client is not None:
            self.client.group_join_answer(gid, nick, accept)

    def _upload_group_file(self):
        gid, _info, _role = self._group_ctx()
        if not gid:
            return
        path = filedialog.askopenfilename(title='选择要上传到群文件的文件' + APP_SUFFIX)
        if not path:
            return
        try:
            self.client.send_file(path, conv_group(gid))
            self._toast('正在上传到群文件…')
        except Exception as e:
            self._toast(f'上传失败：{e}', WARN)

    def _download_group_file(self, fid):
        if not fid:
            return
        self._toast('正在下载群文件，完成后会提示')
        self._group_file_wait.add(str(fid))
        self.client.request_file(str(fid))

    def _del_group_file(self, fid):
        gid, _info, _role = self._group_ctx()
        if gid and self.client is not None:
            self.client.group_file_del(gid, fid)

    def _leave_group(self):
        gid, info, _role = self._group_ctx()
        if not gid:
            return
        name = info.get('name') or '该群'

        def do():
            if self.client is not None:
                self.client.group_leave(gid)
            self._close_group_window()
        self._confirm(f'退出群「{name}」？退群后需要重新申请才能进来。', do)

    def _copy(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(str(text))
            self._toast(f'已复制：{text}')
        except Exception:
            pass

    def _confirm(self, text, on_ok):
        win = ctk.CTkToplevel(self)
        win.title('确认' + APP_SUFFIX)
        win.configure(fg_color=BG_PANEL)
        win.geometry('380x170')
        win.transient(self)
        ctk.CTkLabel(win, text=text, text_color=TEXT, wraplength=320, justify='left',
                     font=ctk.CTkFont(family=FONT, size=13)).pack(padx=24, pady=(28, 10))
        row = ctk.CTkFrame(win, fg_color='transparent')
        row.pack(fill='x', padx=24, pady=(0, 16))

        def ok():
            win.destroy()
            try:
                on_ok()
            except Exception:
                pass
        ctk.CTkButton(row, text='确定', width=90, height=34, corner_radius=10,
                      fg_color=DANGER, hover_color=DANGER_DIM, text_color='#ffffff',
                      font=ctk.CTkFont(family=FONT, size=13), command=ok).pack(side='right')
        ctk.CTkButton(row, text='取消', width=90, height=34, corner_radius=10,
                      fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                      hover_color=BG_HOVER, text_color=TEXT_DIM,
                      font=ctk.CTkFont(family=FONT, size=13),
                      command=win.destroy).pack(side='right', padx=(0, 8))
        win.after(60, win.lift)

    # ================= 超级管理员控制台 =================
    def _on_banned(self, data):
        """自己被封号：明确告诉用户原因，然后退回登录界面。"""
        text = data.get('text') or '你的账号已被封禁'
        self._close_admin_console()
        self._popup('账号已被封禁', text, warning=True)
        try:
            self._teardown()
        except Exception:
            pass
        try:
            self._login_status(text, DANGER)
        except Exception:
            pass
        self._toast('账号已被封禁', WARN)

    def _open_admin_console(self):
        c = self.client
        if c is None or not getattr(c, 'is_super', False):
            self._toast('只有超级管理员可以打开控制台', WARN)
            return
        win = getattr(self, '_admin_win', None)
        try:
            if win is not None and win.winfo_exists():
                win.lift()
                self._admin_tab = getattr(self, '_admin_tab', 'users')
                c.admin_get()
                return
        except Exception:
            pass
        win = ctk.CTkToplevel(self)
        win.title('超级管理员控制台' + APP_SUFFIX)
        win.configure(fg_color=BG_APP)
        win.geometry('940x660')
        win.minsize(760, 520)
        win.transient(self)
        self._admin_win = win
        self._admin_tab = 'users'
        win.protocol('WM_DELETE_WINDOW', self._close_admin_console)
        c.admin_get()
        self._admin_sig = None        # 新窗口必须真画一次（指纹只用于同窗口刷新）
        self._render_admin(force=True)

    def _close_admin_console(self):
        try:
            if self._admin_win is not None:
                self._admin_win.destroy()
        except Exception:
            pass
        self._admin_win = None
        self._admin_sig = None

    def _admin_alive(self):
        win = getattr(self, '_admin_win', None)
        try:
            return win is not None and win.winfo_exists()
        except Exception:
            self._admin_win = None
            return False

    def _admin_tab_btn(self, parent, key, text):
        active = (getattr(self, '_admin_tab', 'users') == key)
        btn = ctk.CTkButton(parent, text=text, width=104, height=32, corner_radius=10,
                            fg_color=ACCENT if active else 'transparent',
                            border_width=0 if active else 1, border_color=FIELD_BORDER,
                            hover_color=ACCENT_DIM if active else BG_HOVER,
                            text_color=ON_ACCENT if active else TEXT_DIM,
                            font=ctk.CTkFont(family=FONT, size=12,
                                             weight='bold' if active else 'normal'),
                            command=lambda k=key: self._switch_admin_tab(k))
        btn.pack(side='left', padx=(0, 6))
        return btn

    def _switch_admin_tab(self, key):
        self._admin_tab = key
        self._render_admin()

    def _render_admin(self, force=False):
        if not self._admin_alive():
            return
        d = getattr(self.client, 'admin_data', None) or {}
        users = d.get('users') or []
        groups = d.get('groups') or []
        bans = [u for u in users if u.get('banned')]
        # 数据没变就别重画：自动刷新是每 5 秒一次，整块重建会让窗口一直闪、
        # 还会把滚动位置清掉（看列表的人最烦这个）。「更新于 …」的时间戳
        # 参与比较的话每次都会判定成「变了」，所以先剔掉。
        def _strip(items):
            return [{k: v for k, v in it.items() if k != 'time'} for it in items]
        sig = (self._admin_tab, repr(_strip(users)), repr(_strip(groups)),
               repr(_strip(bans)))
        if not force and sig == getattr(self, '_admin_sig', None):
            return
        self._admin_sig = sig
        win = self._admin_win
        for w in win.winfo_children():
            w.destroy()
        online = sum(1 for u in users if u.get('online'))

        head = ctk.CTkFrame(win, fg_color=BG_HEADER, corner_radius=0)
        head.pack(fill='x')
        ctk.CTkLabel(head, text='🛡  超级管理员控制台', anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=16, weight='bold')).pack(
            side='left', padx=(16, 12), pady=10)
        ctk.CTkLabel(head, text=f'账号 {len(users)} · 在线 {online} · 群聊 {len(groups)}'
                                f' · 封禁 {len(bans)}',
                     anchor='w', text_color=REGION,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(side='left', pady=10)
        ctk.CTkButton(head, text='刷新', width=64, height=28, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                      hover_color=BG_HOVER, text_color=TEXT_DIM,
                      font=ctk.CTkFont(family=FONT, size=12),
                      command=lambda: self.client.admin_get()).pack(side='right', padx=14)
        ctk.CTkLabel(head, text=f'更新于 {fmt_time(d.get("time") or 0)}', anchor='e',
                     text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=11)).pack(side='right', padx=6)

        tabs = ctk.CTkFrame(win, fg_color='transparent')
        tabs.pack(fill='x', padx=14, pady=(10, 4))
        self._admin_tab_btn(tabs, 'users', f'👤 用户 ({len(users)})')
        self._admin_tab_btn(tabs, 'groups', f'👥 群聊 ({len(groups)})')
        self._admin_tab_btn(tabs, 'bans', f'⛔ 封禁 ({len(bans)})')

        box = ctk.CTkScrollableFrame(win, fg_color=BG_PANEL, corner_radius=12,
                                     scrollbar_fg_color='transparent',
                                     scrollbar_button_color=SCROLL_BTN,
                                     scrollbar_button_hover_color=SCROLL_HOVER)
        box.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        tab = getattr(self, '_admin_tab', 'users')
        if tab == 'users':
            self._admin_users(box, users)
        elif tab == 'groups':
            self._admin_groups(box, groups)
        else:
            self._admin_bans(box, bans)
        # 打开着的时候每 5 秒自动刷一次
        if self._admin_alive():
            self.after(5000, self._admin_auto)

    def _admin_auto(self):
        if not self._admin_alive():
            return
        c = self.client
        if c is not None and getattr(c, 'is_super', False):
            c.admin_get()

    def _admin_users(self, box, users):
        me = (self.client.me if self.client else '') or ''
        if not users:
            ctk.CTkLabel(box, text='还没有注册用户', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(pady=16)
            return
        for u in users:
            nick = u.get('nick') or ''
            row = ctk.CTkFrame(box, fg_color=BG_ACTIVE if u.get('banned') else 'transparent',
                               corner_radius=10)
            row.pack(fill='x', padx=6, pady=2)
            av = self._avatar(nick, 30)
            if av is not None:
                ctk.CTkLabel(row, image=av, text='', fg_color='transparent',
                             text_color=TEXT).pack(side='left', padx=(8, 8), pady=6)
            col = ctk.CTkFrame(row, fg_color='transparent')
            col.pack(side='left', fill='x', expand=True, pady=5)
            mark = ''
            if nick == me:
                mark = '（我）'
            ctk.CTkLabel(col, text=nick + mark, anchor='w', height=17, text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(fill='x')
            bits = []
            bits.append('在线' if u.get('online') else '离线')
            if u.get('region'):
                bits.append(u['region'])
            bits.append(f"好友 {len(u.get('friends') or [])}")
            gs = u.get('groups') or []
            bits.append(f"群聊 {len(gs)}")
            if u.get('created'):
                bits.append('注册 ' + time.strftime('%Y-%m-%d',
                                                    time.localtime(u['created'])))
            if u.get('last_seen'):
                bits.append('最后在线 ' + time.strftime('%m-%d %H:%M',
                                                        time.localtime(u['last_seen'])))
            ctk.CTkLabel(col, text=' · '.join(bits), anchor='w', height=15,
                         text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            if u.get('banned'):
                left = self._ban_left(u.get('ban_until') or 0)
                why = u.get('ban_reason') or '（未填理由）'
                ctk.CTkLabel(col, text=f'⛔ {left} · {why}', anchor='w', height=15,
                             text_color=DANGER,
                             font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            elif gs:
                names = '、'.join(g.get('name') or g.get('no') or '?' for g in gs[:6])
                if len(gs) > 6:
                    names += f' 等 {len(gs)} 个'
                ctk.CTkLabel(col, text='群：' + names, anchor='w', height=15,
                             text_color=TEXT_SOFT,
                             font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            btns = ctk.CTkFrame(row, fg_color='transparent')
            btns.pack(side='right', padx=8)
            if u.get('banned'):
                ctk.CTkButton(btns, text='解封', width=60, height=26, corner_radius=8,
                              fg_color=ACCENT, hover_color=ACCENT_DIM,
                              text_color=ON_ACCENT,
                              font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda n=nick: self._admin_unban(n)).pack(pady=2)
            else:
                ctk.CTkButton(btns, text='封号', width=60, height=26, corner_radius=8,
                              fg_color='transparent', border_width=1, border_color=DANGER,
                              hover_color=BG_HOVER, text_color=DANGER,
                              font=ctk.CTkFont(family=FONT, size=11),
                              command=lambda n=nick: self._dialog_ban(n)).pack(pady=2)

    def _admin_groups(self, box, groups):
        if not groups:
            ctk.CTkLabel(box, text='还没有任何群聊', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(pady=16)
            return
        for g in groups:
            row = ctk.CTkFrame(box, fg_color='transparent', corner_radius=10)
            row.pack(fill='x', padx=6, pady=2)
            av = self._avatar(g.get('name') or '群', 30)
            if av is not None:
                ctk.CTkLabel(row, image=av, text='', fg_color='transparent',
                             text_color=TEXT).pack(side='left', padx=(8, 8), pady=6)
            col = ctk.CTkFrame(row, fg_color='transparent')
            col.pack(side='left', fill='x', expand=True, pady=5)
            ctk.CTkLabel(col, text=f"{g.get('name', '')}（群号 {g.get('no', '')}）",
                         anchor='w', height=17, text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(fill='x')
            bits = [f"群主 {g.get('owner', '')}", f"成员 {len(g.get('members') or [])}"]
            if g.get('admins'):
                bits.append('管理员 ' + '、'.join(g['admins']))
            if g.get('files'):
                bits.append(f"群文件 {g['files']}")
            if g.get('joins'):
                bits.append(f"待审批 {g['joins']}")
            if g.get('created'):
                bits.append('建群 ' + time.strftime('%Y-%m-%d', time.localtime(g['created'])))
            ctk.CTkLabel(col, text=' · '.join(bits), anchor='w', height=15,
                         text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            members = '、'.join((g.get('members') or [])[:12])
            if len(g.get('members') or []) > 12:
                members += f" 等 {len(g['members'])} 人"
            ctk.CTkLabel(col, text='成员：' + (members or '（无）'), anchor='w', height=15,
                         text_color=TEXT_SOFT,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            if g.get('announce'):
                ann = g['announce']
                if len(ann) > 60:
                    ann = ann[:60] + '…'
                ctk.CTkLabel(col, text='公告：' + ann, anchor='w', height=15,
                             text_color=TEXT_SOFT,
                             font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            ctk.CTkButton(row, text='查看', width=54, height=26, corner_radius=8,
                          fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                          hover_color=BG_HOVER, text_color=ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=lambda gg=g: self._admin_open_group(gg)).pack(
                side='right', padx=8)

    def _admin_open_group(self, g):
        """超管从控制台直接跳到这个群（先看能不能进得去）。"""
        gid = str(g.get('gid') or '')
        mine = any(str(x.get('gid')) == gid for x in ((self.client.groups or [])))
        if mine:
            self._select_conv('g:' + gid)
            self._toast(f"已切到群「{g.get('name', '')}」")
        else:
            self._toast(f"你不是群「{g.get('name', '')}」的成员，只能看资料不能发言", WARN)

    def _admin_bans(self, box, bans):
        if not bans:
            ctk.CTkLabel(box, text='当前没有被封禁的账号', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(pady=16)
            return
        for u in bans:
            nick = u.get('nick') or ''
            row = ctk.CTkFrame(box, fg_color='transparent', corner_radius=10)
            row.pack(fill='x', padx=6, pady=2)
            col = ctk.CTkFrame(row, fg_color='transparent')
            col.pack(side='left', fill='x', expand=True, padx=10, pady=6)
            ctk.CTkLabel(col, text=nick, anchor='w', height=17, text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13, weight='bold')).pack(fill='x')
            ctk.CTkLabel(col, text=self._ban_left(u.get('ban_until') or 0), anchor='w',
                         height=15, text_color=DANGER,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            ctk.CTkLabel(col, text='理由：' + (u.get('ban_reason') or '（未填）'), anchor='w',
                         height=15, text_color=TEXT_SOFT,
                         font=ctk.CTkFont(family=FONT, size=11)).pack(fill='x')
            ctk.CTkButton(row, text='解封', width=60, height=26, corner_radius=8,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=lambda n=nick: self._admin_unban(n)).pack(
                side='right', padx=8)

    @staticmethod
    def _ban_left(until):
        if not until:
            return '永久封禁'
        left = int(until - time.time())
        if left <= 0:
            return '已到期'
        if left >= 86400:
            return f'还剩 {left // 86400} 天 {left % 86400 // 3600} 小时'
        if left >= 3600:
            return f'还剩 {left // 3600} 小时 {left % 3600 // 60} 分钟'
        return f'还剩 {max(1, left // 60)} 分钟'

    def _admin_unban(self, nick):
        if self.client is not None:
            self.client.admin_unban(nick)
            self._toast(f'已请求解封「{nick}」')

    def _dialog_ban(self, nick):
        win = ctk.CTkToplevel(self)
        win.title('封禁用户' + APP_SUFFIX)
        win.configure(fg_color=BG_PANEL)
        win.geometry('460x330')
        win.transient(self)
        ctk.CTkLabel(win, text=f'封禁「{nick}」', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=16, weight='bold')).pack(pady=(16, 2))
        ctk.CTkLabel(win, text='被封用户会被立刻踢下线，并在登录时看到封禁理由',
                     text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=11)).pack()
        dur = ctk.CTkOptionMenu(win, values=[c[0] for c in BAN_CHOICES],
                                height=36, corner_radius=10, fg_color=FIELD_BG,
                                button_color=BG_HEADER, button_hover_color=BG_HOVER,
                                text_color=TEXT, dropdown_fg_color=BG_PANEL,
                                dropdown_text_color=TEXT,
                                dropdown_hover_color=BG_HOVER,
                                font=ctk.CTkFont(family=FONT, size=13))
        dur.set(BAN_CHOICES[1][0])
        dur.pack(fill='x', padx=20, pady=(14, 8))
        reason = ctk.CTkEntry(win, height=38, corner_radius=10, fg_color=FIELD_BG,
                              border_color=FIELD_BORDER, border_width=1, text_color=TEXT,
                              placeholder_text='封禁理由（会展示给对方）',
                              font=ctk.CTkFont(family=FONT, size=13))
        reason.pack(fill='x', padx=20)
        err = ctk.CTkLabel(win, text='', anchor='w', text_color=WARN, height=18,
                           font=ctk.CTkFont(family=FONT, size=12))
        err.pack(fill='x', padx=20)

        def submit():
            label = dur.get()
            minutes = dict(BAN_CHOICES).get(label, 0)
            text = reason.get().strip()
            if not text:
                err.configure(text='⚠  请填写封禁理由，让对方知道为什么被封')
                self._flash_warn(reason)
                return
            if self.client is not None:
                self.client.admin_ban(nick, minutes, text)
                self._toast(f'已封禁「{nick}」（{label}）')
            win.destroy()
        ctk.CTkButton(win, text='确认封禁', height=40, corner_radius=10, fg_color=DANGER,
                      hover_color=DANGER_DIM, text_color='#ffffff',
                      font=ctk.CTkFont(family=FONT, size=14),
                      command=submit).pack(fill='x', padx=20, pady=(6, 16))
        reason.bind('<Return>', lambda e: submit())
        win.after(60, lambda: (win.lift(), reason.focus_force()))

    # ---------- 用群号加群 ----------
    def _dialog_join_group(self):
        win = ctk.CTkToplevel(self)
        win.title('加入群聊' + APP_SUFFIX)
        win.configure(fg_color=BG_PANEL)
        win.geometry('440x330')
        win.transient(self)
        ctk.CTkLabel(win, text='加入群聊', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=16, weight='bold')).pack(pady=(16, 2))
        ctk.CTkLabel(win, text='输入群号申请加入，由群主或管理员同意后即可进群',
                     text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=12)).pack()
        no_entry = ctk.CTkEntry(win, height=38, corner_radius=10, fg_color=FIELD_BG,
                                border_color=FIELD_BORDER, border_width=1, text_color=TEXT,
                                placeholder_text='群号（6 位数字）',
                                font=ctk.CTkFont(family=FONT, size=13))
        no_entry.pack(fill='x', padx=20, pady=(14, 6))
        msg_entry = ctk.CTkEntry(win, height=38, corner_radius=10, fg_color=FIELD_BG,
                                 border_color=FIELD_BORDER, border_width=1, text_color=TEXT,
                                 placeholder_text='申请留言（选填）',
                                 font=ctk.CTkFont(family=FONT, size=13))
        msg_entry.pack(fill='x', padx=20, pady=(0, 6))
        err = ctk.CTkLabel(win, text='', anchor='w', text_color=WARN, height=18,
                           font=ctk.CTkFont(family=FONT, size=12))
        err.pack(fill='x', padx=20)

        def submit():
            no = no_entry.get().strip()
            if not no:
                err.configure(text='⚠  请先填写群号')
                self._flash_warn(no_entry)
                return
            if not no.isdigit():
                err.configure(text='⚠  群号只能是数字')
                self._flash_warn(no_entry)
                return
            msg = msg_entry.get().strip()
            if len(msg) > GROUP_JOIN_MSG_MAX:
                err.configure(text=f'⚠  留言最多 {GROUP_JOIN_MSG_MAX} 字')
                return
            if self.client is None or not self.connected:
                err.configure(text='⚠  还没连上服务器')
                return
            self.client.group_join(no, msg)
            win.destroy()
        ctk.CTkButton(win, text='发送加群申请', height=40, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=14),
                      command=submit).pack(fill='x', padx=20, pady=(4, 8))
        no_entry.bind('<Return>', lambda e: submit())
        msg_entry.bind('<Return>', lambda e: submit())
        win.after(60, lambda: (win.lift(), no_entry.focus_force()))

    def _conv_title(self, conv):
        c = self.client
        kind = conv_kind(conv)
        if kind == 'friend':
            want = str(conv)[2:]
            disp = want
            for f in (c.friends if c else []):
                if f.lower() == want:
                    disp = f
                    break
            on = disp in (c.online if c else [])
            return disp, ('在线' if on else '离线')
        if kind == 'group':
            gid = str(conv)[2:]
            info = ((getattr(c, 'group_infos', None) or {}).get(gid) if c else None) or {}
            for g in (c.groups if c else []):
                if str(g['gid']) == gid:
                    sub = f"{len(g.get('members', []))} 人"
                    if g.get('no'):
                        sub += f" · 群号 {g['no']}"
                    return g['name'], sub
            if info:
                return info.get('name') or '群聊', f"群号 {info.get('no') or gid}"
            return '群聊', ''
        name = getattr(c, 'room', None) or '公共大厅'
        return name, f'{len(c.online) if c else 0} 人在线'

    def _select_conv(self, conv):
        self.conv = conv
        if self.client is not None:
            self.client.open_conv(conv)
            ask = getattr(self.client, 'group_info', None)
            if conv_kind(conv) == 'group' and callable(ask):
                # 群资料（公告/群文件/角色）不是每次都推，进群时主动要一份
                ask(str(conv)[2:])
        # 不要再无脑清空成员面板指纹：切会话时如果成员列表其实没变（比如好友之间
        # 互切，右侧本来就是隐藏的），重建一次就是白建几十个控件、白重画一遍。
        # 指纹里已经带了会话类型，真变了自然会重建。
        self._rebuild_conv_list()
        # 切进一个会话就该看到最后一条消息：这里直接钉底，不看「之前贴不贴底」
        # （用户要的就是这个行为），而且会连续校正几次，抗住迟到的布局更新。
        self._scroll_stick = True
        self._render_conv()
        self._pin_bottom()
        if getattr(self, '_group_win_gid', None) and str(self._group_win_gid) == str(conv)[2:]:
            self._render_group_window()
        # 空闲时把别的会话也先画好：下次点进去就是现成的（零等待）
        self._schedule_preload()

    def _tail_limit(self, conv=None):
        """当前会话最多画多少条历史：默认 RENDER_TAIL，点「显示更早的」再加一段。"""
        conv = self.conv if conv is None else conv
        base = min(RENDER_TAIL, 8) if getattr(self, 'calm', False) else RENDER_TAIL
        return base + int((getattr(self, '_tail_extra', None) or {})
                          .get(conv, 0))

    def _more_history(self, add=None):
        """补画更早的历史（重新整块画一遍，只是范围更大）。"""
        extra = getattr(self, '_tail_extra', None)
        if extra is None:
            extra = self._tail_extra = {}
        extra[self.conv] = extra.get(self.conv, 0) + int(add or RENDER_TAIL)
        self._render_conv(force=True)     # 用户主动要的，别被重建限速挡住

    # ---------- 「还没选会话」的空状态 ----------
    def _empty_view_obj(self):
        """空状态自己也是一块「视图」，这样才能和消息区共用同一套状态管理。

        注意：它必须走 `_views` + `_bind_view_state`，否则 `self.messages` 会指到
        一块已经被销毁的旧控件上（那会连带后面所有渲染/发送都报错）。
        """
        view = self._views.get('')
        if view is not None:
            try:
                if self._alive(view['frame']):
                    return view
            except Exception:
                pass
            self._views.pop('', None)
        view = self._new_view('')
        self._views[''] = view
        try:
            box = ctk.CTkFrame(view['frame'], fg_color='transparent')
            box.place(relx=0.5, rely=0.5, anchor='center')
            ctk.CTkLabel(box, text='💬', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=44)).pack()
            ctk.CTkLabel(box, text='请选择聊天会话', text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=18,
                                          weight='bold')).pack(pady=(10, 4))
            ctk.CTkLabel(box,
                         text='点左侧的「公共大厅」、好友或群聊开始聊天\n'
                              '（未读消息会显示在侧栏）',
                         text_color=TEXT_DIM, justify='center',
                         font=ctk.CTkFont(family=FONT, size=12)).pack()
        except Exception:
            pass
        return view

    def _render_empty_state(self):
        """把右侧切成「请选择聊天会话」。"""
        try:
            self.title_label.configure(text='请选择聊天会话')
            self.sub_label.configure(text='左侧点一个会话开始')
        except Exception:
            pass
        try:
            self._activate_view(self._empty_view_obj())
        except Exception:
            pass

    def _has_conv(self):
        return bool(str(getattr(self, 'conv', '') or ''))

    def _render_conv(self, force=False):
        if not self._has_conv():
            self._render_empty_state()
            return
        self._force_rebuild = bool(force)
        try:
            title, subtitle = self._conv_title(self.conv)
            self.title_label.configure(text=title)
            self.sub_label.configure(text=subtitle)
        except Exception:
            pass
        # 换一个全新的消息区（滚动区从零算起，不会残留上一次的高度）。
        # 如果这个会话之前已经画好、而且内容没变，这里会直接复用（零重绘）。
        if self._recreate_messages() is not None:
            self._scroll_stick = True
            self._pin_bottom()
            self._upgrade_visible_images()
            return
        msgs = [m for m in (self.msgs.get(self.conv) or [])
                if not m.get('conv') or str(m.get('conv')) == str(self.conv)]
        # 消息太多时只重绘最近的一段：每条气泡要新建十来个控件，几百条一起画
        # 会把主线程占住好几秒（切会话/重连时最明显，看起来就是界面卡死）。
        # 更早的消息只是不画，数据还在。
        dropped = max(0, len(msgs) - self._tail_limit())
        msgs = msgs[-self._tail_limit():] if dropped else msgs
        if dropped:
            # 更早的那些点一下就能补出来（一次性画太多会占住主线程，
            # 所以默认只画最近一段，剩下的让用户自己决定要不要看）
            self._add_tail_hint(dropped)
        if not msgs:
            self._add_empty_hint()
            self._flush_pending_map()
            self._schedule_scroll()
            return
        # 分帧画：先画一批，剩下的每隔一帧补一批。整块一次性画会占住主线程
        # （120 条要一秒多），界面看起来就是卡住不动。画的时候先不滚动，
        # 免得每加一条都重排一次滚动区。
        # 令牌**全局唯一**：不同会话各有自己的分帧任务，令牌不能撞车，否则
        # 上一个会话遗留的回调可能把消息画进另一个会话里。
        self._render_seq = getattr(self, '_render_seq', 0) + 1
        self._render_token = self._render_seq
        self._render_queue = list(msgs)
        self._render_bulk = True
        self._force_rebuild = False
        if self._current_view is not None:
            # 队列/令牌都记到「这个会话自己的状态」里：切走再切回来能接着画，
            # 而且别人拿到的是**同一个对象**（用 is 判断归属，杜绝串会话）
            self._current_view['token'] = self._render_token
            self._current_view['queue'] = self._render_queue
            self._current_view['render_bulk'] = True
        token = self._render_token
        self._render_chunk(token, first=True)

    def _render_chunk(self, token, first=False):
        """画一批消息，然后立刻把主线程交还出去。

        两件事一起做，才有「点开就是现成的、点开也不卡」：
        1. **批次按时间切**：一批消息要建十来个控件、还让 Tk 重排一次，实测一条约
           12 ms；固定画 20 条就是 200~300 ms 的僵住。现在每帧最多占
           CHUNK_SECONDS（12 ms）就停手，界面始终能响应。
        2. **先画好再显示**（`_pending_map_frame`）：往**已经显示出来**的滚动区里一条条
           加，Tk 每加一条都要把整块重新排版，20 条实测要 2.3 秒（这就是用户看到的
           「点开要加载一会儿」）。所以先把新的滚动区在屏幕外画完（不显示时 Tk 不算
           布局，20 条约 0.25 秒），全部画好再一次性显示出来 —— 实测从 2.3 秒降到
           0.3 秒左右，而且不会看到一条条蹦出来的过程。
        """
        if token != getattr(self, '_render_token', None):
            # 期间又切了会话/又发起了一轮渲染，这一批作废。但如果队列里还有没画完的
            # 内容，说明**这一轮是真的被打断了**：记一笔，下次排查「消息没出来」
            # 就能一眼看出是被谁打断的。
            if getattr(self, '_render_queue', None):
                write_diag(f'!! 分帧渲染被打断：令牌过期（{token}→{self._render_token}），'
                           f'还剩 {len(self._render_queue)} 条没画')
            return
        view = self._current_view
        if view is None:
            write_diag('!! 分帧渲染被打断：当前视图为空')
            return
        if view.get('queue') is not self._render_queue:
            # 状态刚被切过（后台预热会切换视图状态）。这里**不能**直接停手：停手就
            # 意味着这一批永远画不完，界面上只剩开头一两条 —— 用户看到的就是
            # 「消息加载不出来」。令牌一致说明这就是当前这一轮的渲染，把队列
            # 认领回当前视图，接着画完。
            # 队列不是当前会话的：**绝对不能接着画**，否则另一个会话的消息就会被
            # 画进这个会话里（用户看到的「好友会话里出现别人的聊天内容」就是这么来的）。
            # 正确做法是停手，并把这个会话标记成「需要重画」，下次显示时干净地重画一遍。
            write_diag(f'分帧队列不属于当前会话：conv={view.get("conv")!r} '
                       f'旧队列={len(self._render_queue or [])} '
                       f'新队列={len(view.get("queue") or [])} → 丢弃这一批并标记重画')
            self._render_bulk = False
            view['render_bulk'] = False
            view['sig'] = None
            if getattr(self, '_pending_map_frame', None) is not None:
                self._flush_pending_map()
            return
        queue = self._render_queue
        t0 = time.perf_counter()
        drawn = 0
        least = max(1, min(int(RENDER_FIRST if first else CHUNK_MIN), RENDER_CHUNK))
        while queue and drawn < RENDER_CHUNK:
            if drawn >= least and (time.perf_counter() - t0) >= CHUNK_SECONDS:
                break                    # 这一帧的预算用完了，剩下的下一帧再画
            m = queue.pop(0)
            drawn += 1
            try:
                self._render(m, animate=False)
            except Exception as e:
                # 单条消息渲染失败不能连累后面的消息（以前会直接中断整个重绘，
                # 界面上就只剩半截内容，看起来像「消息丢了」）
                write_log(log_path(),
                          f'!! 渲染消息失败 {m.get("t")!r}：{e!r}\n{traceback.format_exc()}')
        if queue:
            self.after(1, lambda: self._render_chunk(token))
        else:
            self._render_bulk = False
            self._flush_pending_map()
            # 整批画完了才定「贴不贴底」：进来这一趟就该停在最后一条消息上
            self._upgrade_visible_images()
            if self._current_view is not None:
                try:
                    self._current_view['sig'] = self._view_sig()
                except Exception:
                    pass
            if getattr(self, '_scroll_stick', True):
                self._pin_bottom()
            else:
                self._schedule_scroll()

    # ================= 界面切换 =================
    def show_login(self):
        self.chat.pack_forget()
        self.login.pack(fill='both', expand=True)
        self.after(60, self._start_bg)
        self.after(120, self._focus_login)

    def _focus_login(self):
        """自动聚焦到第一个还没填的输入框，方便直接敲字 + 回车。"""
        try:
            for e in (self.host_entry, self.port_entry, self.nick_entry, self.pwd_entry):
                if not e.get().strip():
                    e.focus_set()
                    return
            self.pwd_entry.focus_set()
        except Exception:
            pass

    def show_chat(self):
        self.mode = 'chat'
        self._stop_bg()
        self.login.pack_forget()
        self.chat.pack(fill='both', expand=True)
        # 进聊天界面时**不自动进任何会话**：右侧显示「请选择聊天会话」，
        # 由用户自己点。以前这里会落到大厅，而第一次渲染经常来不及显示。
        self.conv = '' if not self._has_conv() else self.conv
        if not self._has_conv():
            try:
                self._render_empty_state()
            except Exception:
                pass
        self.input.focus_set()

    def _set_status(self, text, color):
        self.me_sub.configure(text=text, text_color=color)

    def disconnect(self):
        if self._confirm_quit_with_game('退出登录'):
            return
        self._teardown()

    def _unfinished_games(self):
        """还没下完的棋局窗口（用来提示「退出等于认输」）。"""
        out = []
        for win in list(self.chess_windows.values()):
            try:
                if win.winfo_exists() and not win.finished:
                    out.append(win)
            except Exception:
                pass
        return out

    def _confirm_quit_with_game(self, action):
        """有棋局没下完就退出：先问一次，并说明等于认输。"""
        pending = self._unfinished_games()
        if not pending:
            return False
        if getattr(self, '_quit_confirm_win', None) is not None:
            try:
                if self._quit_confirm_win.winfo_exists():
                    self._quit_confirm_win.lift()
                    return True
            except Exception:
                pass
        names = '、'.join(w._opponent_name() for w in pending)
        self._quit_confirm_win = chess_ui.ConfirmDialog(
            self,
            title=f'{action}前请确认',
            message=(f'你还有 {len(pending)} 局棋没下完（对手：{names}）。\n\n'
                     f'现在{action}将视为**认输**，对方直接获胜。'),
            ok_text=f'认输并{action}',
            cancel_text='继续下棋',
            palette=self._chess_palette(),
            on_ok=lambda: self._quit_after_game_confirm(action),
        )
        return True

    def _quit_after_game_confirm(self, action):
        self._quit_confirm_win = None
        for win in self._unfinished_games():
            try:
                win.hooks['on_resign'](win.game.get('gid'))
                win._closed = True
            except Exception:
                pass
        if action == '退出登录':
            self._teardown()
        else:
            self._real_close()

    def _teardown(self):
        c = self.client
        self.client = None
        self.connected = False
        self._pending_auth = False
        self._reconnecting = False      # 主动退出：别让重连逻辑又把我拉回去
        self._rec_attempt = 0
        self._close_chess_windows()
        if c is not None:
            try:
                c.disconnect()
            except Exception:
                pass
        self._show_offline(False)
        try:
            self.panel.pack_forget()
        except Exception:
            pass
        self._clear_view()
        self.msgs.clear()
        self.conv = CONV_ROOM
        self.auth_btn.configure(state='normal')
        self._login_status('')
        self.show_login()

    def _on_close(self):
        if self._confirm_quit_with_game('退出程序'):
            return
        self._real_close()

    def _real_close(self):
        try:
            if self.notify is not None:
                self.notify.detach()
        except Exception:
            pass
        try:
            if self.client:
                self.client.disconnect()
        except Exception:
            pass
        self.destroy()

    def _trace(self, msg):
        """排查用的流水日志（环境变量 QIAONI_DEBUG=1 或配置里 debug=true 时才写）。"""
        if self._trace_on:
            write_log(trace_path(), msg)

    # ================= 断线处理 =================
    def _pack_above_messages(self, widget):
        """把控件插到消息区上方。

        注意：self.messages 是 CTkScrollableFrame，它真正的容器是内部的
        _parent_frame（本身被放在一个 canvas 里），直接拿 self.messages 当
        pack(before=...) 的参照会报 "isn't packed"。
        """
        ref = getattr(self.messages, '_parent_frame', None) or self.messages
        try:
            widget.pack(fill='x', before=ref)
            return True
        except Exception:
            try:
                widget.pack(fill='x')
                return True
            except Exception:
                return False

    def _show_offline(self, offline):
        """顶部挂一条醒目的离线横幅，并禁用输入区。"""
        try:
            if offline:
                text = ('⚠  连接中断，正在自动重连…（期间对方发的消息会存在服务器上，'
                        '重连后自动补回来）'
                        if self._reconnecting else
                        '⚠  已与服务器断开连接，消息无法收发 —— '
                        '请点右上角「退出登录」重新登录')
                color = WARN
                if self._offline_bar is None or not self._offline_bar.winfo_exists():
                    self._offline_bar = ctk.CTkLabel(
                        self.body, text=text, fg_color=color, corner_radius=0,
                        text_color='#1b1b1b', height=26,
                        font=ctk.CTkFont(family=FONT, size=12, weight='bold'))
                else:
                    self._offline_bar.configure(text=text, fg_color=color)
                if self._offline_bar.winfo_manager() == '':
                    self._pack_above_messages(self._offline_bar)
            elif self._offline_bar is not None:
                self._offline_bar.pack_forget()
            state = 'disabled' if offline else 'normal'
            for w in (self.input, self.send_btn, self.emoji_btn,
                      self.file_btn, self.mention_btn, self.chess_btn):
                try:
                    w.configure(state=state)
                except Exception:
                    pass
        except Exception:
            pass

    def _on_connection_lost(self, reason=''):
        if not self.connected:
            return
        self.connected = False
        # 先决定「自动重连」还是「直接放弃」，再画横幅 ——
        # 横幅文案要看 _reconnecting，顺序反了就会显示成「请手动重新登录」。
        self._start_reconnect(reason)
        self._show_offline(True)
        head = reason or '与服务器断开连接'
        if self._reconnecting:
            self._add_sys(f'⚠ {head}；正在自动重连，期间消息发不出去'
                          '（对方发的会存在服务器上，重连后补回来）')
        else:
            self._add_sys(f'⚠ {head}：消息已经发不出去也收不到，'
                          '请点右上角「退出登录」重新登录')

    # ---------- 掉线自动重连 ----------
    def _start_reconnect(self, reason=''):
        if self._reconnecting:
            return
        if self.mode != 'chat' or not getattr(self, '_auth_args', None):
            self._reconnect_failed(reason)
            return
        self._reconnecting = True
        self._rec_attempt = 0
        self._reconnect_step()

    def _reconnect_step(self):
        if self.connected or not self._reconnecting:
            return
        args = getattr(self, '_auth_args', None)
        if not args or self.mode != 'chat':
            self._reconnect_failed('')
            return
        self._rec_attempt += 1
        if self._rec_attempt > RECONNECT_TRIES:
            self._reconnect_failed('')
            return
        delay = (2, 4, 8, 15, 25)[min(self._rec_attempt - 1, 4)]
        self._set_status(f'连接中断，{delay} 秒后自动重连'
                         f'（第 {self._rec_attempt}/{RECONNECT_TRIES} 次）…', WARN)
        self.after(delay * 1000, self._reconnect_now)

    def _reconnect_now(self):
        if self.connected or not self._reconnecting:
            return
        args = getattr(self, '_auth_args', None)
        if not args:
            self._reconnect_failed('')
            return
        host, port, nick, pwd, _mode = args
        self._pending_auth = True
        try:
            c = ChatClient(host, port)
        except Exception as e:
            self._add_sys(f'重连时地址解析失败：{e}')
            self._pending_auth = False
            self._reconnect_step()
            return
        c.on_error = self._note_client_error
        self.client = c
        c.login(nick, pwd)
        self.after(7000, self._check_auth_timeout)

    def _reconnect_failed(self, reason=''):
        self._reconnecting = False
        self._pending_auth = False
        self._set_status('已断开', DANGER)
        hint = reason or '自动重连失败，与服务器断开连接'
        self._add_sys(f'⚠ {hint}：请点右上角「退出登录」手动重新登录'
                      '（之前的消息存在服务器上，重新登录后会补回来）')
        self._show_offline(True)

    def _check_link(self):
        """核心信道已经判死、但界面还以为是好的 —— 把界面同步过来。"""
        c = self.client
        if c is None or not self.connected:
            return
        if not getattr(c, 'connected', True):
            info = {}
            try:
                info = c.health()
            except Exception:
                pass
            self._on_connection_lost(info.get('reason') or '与服务器断开连接')

    # ================= 事件轮询 =================
    def _poll(self):
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        c = self.client
        if c is not None:
            # 一个 tick 最多处理这么多事件：一口气收到几十条消息时，
            # 全在这一个 60ms 里渲染会把主线程占住（每条气泡 ~15ms），
            # 界面就是「卡一下」。剩下的留到下一个 tick，界面始终能响应。
            budget = EVENTS_PER_TICK
            while budget > 0:
                try:
                    ev = c.events.get_nowait()
                except queue.Empty:
                    break
                budget -= 1
                try:
                    self._handle_event(ev)
                except Exception as e:
                    # 这里以前是 pass —— 一旦某个事件处理抛异常，消息就凭空消失了，
                    # 而且一点痕迹都不留。现在至少写进日志，方便排查。
                    tag = ev[0] if isinstance(ev, tuple) else ev
                    write_log(log_path(),
                              f'!! 处理事件 {tag!r} 出错：{e!r}\n{traceback.format_exc()}')
                    self._trace(f'事件处理异常 {tag!r}: {e!r}')
            if c.rtt is not None and c.connected:
                txt = f'{c.rtt * 1000:.0f} ms'
                if txt != getattr(self, '_rtt_text', None):
                    self._rtt_text = txt
                    self.rtt_label.configure(text=txt)
            self._check_link()
        # 定期在主线程里回收一次：TK 的 Font 等对象在 __del__ 里要回调 Tcl，
        # 而 Tcl 不是线程安全的 —— 万一它们在网络线程（json.dumps 之类）里被 GC
        # 撞上，那条线程会直接卡住，表现就是「消息发不出去/收不到」。
        now = time.time()
        if now - self._last_gc >= 5.0:
            self._last_gc = now
            try:
                gc.collect()
            except Exception:
                pass
        # 兜底 1：分帧渲染链断了 / 画好的那块没人显示 → 把界面强行恢复成
        #         「点一次会话」之后的样子。用户报的「登录后发消息没反应、
        #         反复点左侧会话栏才出来」根子就在这条链上：一旦断掉，
        #         那块消息区就永远不显示，后面所有消息都画进了一个看不见的区域。
        self._heal_stuck_render(now)
        # 兜底 2：当前会话的界面是空的、但会话里明明有消息 → 强制重画一次
        self._heal_empty_view()
        # 兜底 3：显示自检 —— 界面上「本该看得见的东西」要是没挂着 / 高度为 0，
        # 就地挂回去。用户报的「消息区一片空白、发消息毫无反应」就是这一路。
        self._heal_display()
        # 禁言倒计时 / 好友关系变化：输入区该锁就锁，该还给用户就还
        self._apply_mute_state()
        # 心跳诊断：每 10 秒记一行当前状态（排查「卡/黑/发不出消息」时的现场）
        if now - getattr(self, '_diag_at', 0.0) >= 10.0:
            self._diag_at = now
            try:
                n_rows = len(self.messages.winfo_children()) if self._alive(self.messages) else -1
                view = getattr(self, '_current_view', None)
                frame = view.get('frame') if isinstance(view, dict) else None
                write_diag(f'状态 conv={self.conv!r} 连接={self.connected} '
                           f'视图={len(self._views)} 当前行数={n_rows} '
                           f'待画={len(self._render_queue or [])} 预热中={self._preload_target!r} '
                           f'遮罩={"开" if self._veil_up() else "关"} '
                           f'锁输入={bool(getattr(self, "muted_view", False))} '
                           f'最小化={not self.winfo_viewable()} '
                           f'消息区={self._pack_state(frame)} '
                           f'底栏={self._pack_state(getattr(self, "bottom", None))} '
                           f'输入区={self._pack_state(getattr(self, "composer", None))}')
            except Exception:
                pass
        self.after(60, self._poll)

    @staticmethod
    def _pack_state(w):
        """给诊断日志用：这个控件现在挂在界面上吗、有多大。

        注意：消息区是 CTkScrollableFrame，它**自己**是挂在内部 canvas 上的
        （winfo_manager()=='canvas'），真正被 pack 的是它的外层 `_parent_frame`。
        所以这里先看外层。
        """
        try:
            if w is None:
                return '无'
            outer = getattr(w, '_parent_frame', None) or w
            mgr = outer.winfo_manager()
            if mgr != 'pack':
                return '没挂(%s)' % (mgr or '空')
            return '挂%dx%d' % (int(outer.winfo_width()), int(outer.winfo_height()))
        except Exception:
            return '?'

    def _heal_stuck_render(self, now):
        """渲染链断了：清掉卡住的标记、把「画好却没显示」的那块挂上去。

        现场（用户日志里的原话）：`分帧渲染标记卡住（队列已空），已自动清理`
        ＋ `当前行数` 一直在涨，可界面上一片空白，用户只能反复点左侧会话栏
        才看得到消息。

        两件事，都只在**队列已经空了**（渲染确实停了）时才做：
        A. `_render_bulk` 卡住 → 清掉；
        B. 有一块「画好了等着显示」超过 1 秒还没显示 → 强行 flush
           （`_flush_pending_map` 内部若发现那块不是当前会话的，会改挂当前会话那块）。

        刻意**不**在这里做「重挂控件」这种重活：试过，会在正常渲染/预热的
        中间态里误伤（`test_preload` / `test_scroll` 当场变红）。
        那件事交给 `_ensure_messages_shown()`（它只在「确实没挂着」时动手）。
        """
        if getattr(self, '_render_queue', None):
            return                       # 正在分帧画：中间态，不碰
        stuck_bulk = bool(getattr(self, '_render_bulk', False))
        pending = getattr(self, '_pending_map_frame', None)
        pending_stale = (pending is not None
                         and now - getattr(self, '_pending_map_at', now) > 1.0)
        if not (stuck_bulk or pending_stale):
            return
        if stuck_bulk:
            self._render_bulk = False
            view = getattr(self, '_current_view', None)
            if isinstance(view, dict):
                view['render_bulk'] = False
            write_diag('分帧渲染标记卡住（队列已空），已自动清理')
        if pending is not None:
            write_diag('兜底：画好的消息区一直没显示，强行挂上去')
            self._flush_pending_map()
        # 最后再确认一次：当前会话那块确实没挂在界面上就挂回去（没挂着才动手）
        self._ensure_messages_shown()

    def _messages_area_looks_empty(self, frame):
        """消息区「明明有内容，画出来却是空白」的判据。

        只认两个硬信号：画布自身没有高度、或者滚动区高度是 0（内容被挤没了）。
        **不要把画布窗口项的高度当成判据**：那玩意儿的默认值 0 表示「用控件自身
        大小」，是正常状态（早先按 0 判空，结果每 2 秒误报一次）。
        """
        try:
            if not frame.winfo_children():
                return False                # 本来就没内容，不算异常
            cv = frame._parent_canvas
            if cv.winfo_height() <= 1:
                return True
            sr = str(cv.cget('scrollregion') or '').split()
            if len(sr) == 4 and float(sr[3]) <= 1:
                return True
        except Exception:
            return False
        return False

    def _heal_display(self):
        """显示自检：该看见的东西看不见，就地把它挂回来。

        为什么需要它：用户报的「大厅发消息毫无反应」，实际现场是 ——
        标题栏、侧栏、在线人数、延迟全都正常，**整个消息区和输入区一片空白**，
        而程序自己以为一切正常（消息行数在涨、连接正常）。这类「挂载状态漂了」
        的问题只要发生一次，用户就完全没法用了；而且它的触发时序很难复现，
        所以这里做一道廉价的周期性自检：只在**确实不对**时动手，
        正常情况一个控件都不碰，每次动手都写一行日志，便于下次定位。

        检查三件事：
        1. 正文区(self.body)还挂在界面上吗；
        2. 当前会话的消息区挂着吗、高度是不是 0；
        3. 底部输入区还挂着吗（没被禁言/掉线提示条顶掉时）。

        闸门：最小化时不动手；**正在渲染/正在预热时不动手**（那是中间态）；
        每 2 秒最多查一次。
        """
        try:
            if not self.winfo_viewable():
                return                      # 最小化了：恢复时系统会重画，别插手
        except Exception:
            return
        # 正在画 / 正等着把画好的那块挂上去的时候，状态本来就是「中间态」，
        # 这时候绝不能插手（插了反而会把渲染链搅乱）。
        if (getattr(self, '_render_queue', None)
                or getattr(self, '_render_bulk', False)
                or getattr(self, '_pending_map_frame', None) is not None
                or getattr(self, '_preloading', False)):
            return
        now = time.monotonic()
        if now - getattr(self, '_heal_disp_at', 0.0) < 2.0:
            return
        self._heal_disp_at = now

        # 1) 正文区
        try:
            if self.body.winfo_manager() != 'pack' and self.main.winfo_height() > 60:
                write_diag('显示自检：正文区没挂着，重新挂上')
                self.body.pack(fill='both', expand=True)
                self._ensure_messages_shown()
        except Exception:
            pass

        # 2) 当前会话的消息区
        try:
            view = getattr(self, '_current_view', None)
            frame = view.get('frame') if isinstance(view, dict) else None
            if frame is not None and self._alive(frame):
                if (frame._parent_frame.winfo_manager() != 'pack'
                        and getattr(self, '_pending_map_frame', None) is None):
                    write_diag('显示自检：当前会话的消息区没挂着，重新挂上')
                    self._show_only(frame)
                    self._sync_scrollregion(frame)
                    if getattr(self, '_scroll_stick', True):
                        self._pin_bottom()
                elif self.body.winfo_height() > 60 and self._messages_area_looks_empty(frame):
                    write_diag('显示自检：消息区有内容却显示成空白，重新校正滚动区')
                    self._sync_scrollregion(frame)
                    if getattr(self, '_scroll_stick', True):
                        self._pin_bottom()
        except Exception:
            pass

        # 3) 底部输入区（被禁言/断线提示条顶掉时不算）
        try:
            if (self.composer.winfo_manager() != 'pack'
                    and not getattr(self, 'muted_view', False)
                    and self.main.winfo_width() > 100):
                write_diag('显示自检：输入区没挂着，重新挂上')
                self.composer.pack(fill='x', padx=12, pady=10)
        except Exception:
            pass

    def _handle_event(self, ev):
        t, data = ev
        if t == 'welcome':
            try:
                self._my_ip = str(data.get('my_ip') or '')
            except Exception:
                self._my_ip = ''
            self.connected = True
            self._pending_auth = False
            self._save_login_info()          # 登录成功：记住这次的地址/端口/昵称
            reconnected = self._reconnecting
            self._reconnecting = False
            self._show_offline(False)
            self.client.room = data.get('room', '公共大厅')
            self.me_label.configure(text=f'{data.get("you", "")}（我）')
            self._sync_status()
            self.auth_btn.configure(state='normal')
            self._login_status('')
            self.connected = True
            self.show_chat()
            self._rebuild_conv_list()
            self._render_empty_state()    # 不自动进会话：右侧显示「请选择聊天会话」
            self.after(1500, self._start_my_region_lookup)   # 后台查「我的属地」
            self._schedule_preload()      # 空闲时把各会话都预热好，点哪个都秒开
            if reconnected:
                # 放进消息流里（而不是只弹一下），重连这件事在记录里留痕
                self._msgs_append({'t': 'system', 'conv': self.conv, 'kind': 'reconnect',
                                   'text': '✅ 已重新连接上服务器',
                                   'time': now_ts()})
                self._toast('已重新连接')
        elif t == 'register_ok':
            self._login_status('注册成功，正在登录…', ONLINE)
        elif t == 'register_err':
            self._login_status(f'注册失败：{data}')
            self._reset_login()
        elif t == 'deny':
            self._login_status(f'{data}')
            self._reset_login()
        elif t == 'recall':
            conv = data.get('conv') or self.conv
            self._apply_recall(conv, data.get('mid'), data.get('by'))
        elif t == 'social':
            self._rebuild_conv_list()
            title, subtitle = self._conv_title(self.conv)
            self.title_label.configure(text=title)
            self.sub_label.configure(text=subtitle)
            self._check_invites(data.get('invites') or [])
        elif t == 'group_info':
            info = data.get('info') or {}
            gid = str(info.get('gid') or '')
            if gid:
                self._member_sig = None      # 角色/禁言变了，成员面板要重画
            self._rebuild_conv_list()        # 里面会顺带 _apply_mute_state()
            if gid and gid == str(getattr(self, '_group_win_gid', '') or ''):
                self._render_group_window()
        elif t == 'avatar':
            nick = data.get('nick') or ''
            self._clear_avatar_cache(nick)
            self._redraw_for_avatar(nick)
        elif t == 'avatar_data':
            nick = data.get('nick') or ''
            self._clear_avatar_cache(nick)
            self._redraw_for_avatar(nick)
        elif t == 'kicked':
            name = data.get('group') or '群聊'
            gid = str(data.get('gid') or '')
            if str(self.conv) == 'g:' + gid:
                self._select_conv(CONV_ROOM)
            self._group_win_gid = None
            self._close_group_window()
            self._member_sig = None
            self._rebuild_conv_list()
            self._toast(f'你已被移出群「{name}」', WARN)
            self._add_sys(f'⚠ 你已被管理员移出群「{name}」')
            self._sound('message')
        elif t == 'muted':
            # 被禁言：立刻把输入框和发送按钮收起来，显示「禁言中」
            gid = str(data.get('gid') or '')
            self._member_sig = None
            self._rebuild_members()
            self._apply_mute_state()
            self._sound('message')
            left = int(data.get('left') or 0)
            mins = int(data.get('minutes') or 0)
            if gid == str(self.conv)[2:]:
                self._toast('你已被禁言，暂时不能在群里发言', WARN)
        elif t == 'unmuted':
            self._member_sig = None
            self._rebuild_members()
            self._apply_mute_state()
            self._toast('你的禁言已解除，可以发言了')
            self._sound('message')
        elif t == 'server_info':
            self._refresh_header()
            if data.get('state') == 'unknown' and not getattr(self, '_geo_warned', False):
                self._geo_warned = True
                why = data.get('reason') or ''
                self._toast('服务器属地没查出来' + (f'：{why}' if why else ''), WARN)
                self._add_sys('⚠ 服务器没能查出自己的 IP 属地'
                              + (f'（{why}）' if why else '')
                              + '；可在服务端控制台敲 geo self 复查')
        elif t == 'admin_data':
            if self._admin_alive():
                self._render_admin()
        elif t == 'banned':
            self._on_banned(data)
        elif t == 'history':
            conv = data.get('conv')
            self._merge_history(conv, data.get('items', []))
            if conv == self.conv:
                self._render_conv()
        elif t in ('chat', 'me', 'system', 'file_msg'):
            conv = data.get('conv') or ''
            if t == 'system' and data.get('kind') == 'notice' and not conv:
                # 没有归属会话的系统提示（头像已更新 / 离线留言提示 / 各种操作回执）：
                # **只弹浮层，绝不写进任何会话**。以前服务端把这类提示的 conv
                # 默认成「公共大厅」，切回大厅就会看到一堆跟大厅无关的内容
                # —— 用户报的「聊天内容串到别的会话里」就是这么来的。
                self._toast(data.get('text') or '')
            else:
                self._msgs_append(data)
                if t == 'system' and data.get('toast') and conv != self.conv:
                    # 系统提示属于某个群 / 好友会话：记录写到那个会话里，
                    # 用户没停在那儿时再浮一条，别让「你在群里被禁言了」这种
                    # 消息只躺在看不见的地方（更不能跑到大厅去）。
                    self._toast(data.get('text') or '')
            self._notify_message(t, data, conv or CONV_ROOM)
        elif t == 'presence':
            self._rebuild_conv_list()
        elif t == 'users':
            self._rebuild_conv_list()
        elif t == 'search_result':
            self._show_search_results(data.get('users', []))
        elif t == 'chess':
            self._on_chess_event(data)
        elif t == 'file_data':
            self._fill_file(data)
        elif t == 'disconnected':
            self._on_connection_lost()
        elif t == 'link':
            self._on_link_state(data)

    # ================= 消息渲染 =================
    def _on_link_state(self, data):
        """「网络暂时收不到包」/「恢复了」。

        这**不是**断线：不锁输入框、不触发重连，只在顶部挂一条提示，
        恢复后自动收掉。跨洋链路的抖动就这么过去了，用户不会再看到
        「莫名其妙断开又重连」。
        """
        silent = bool(data.get('silent'))
        secs = float(data.get('seconds') or 0)
        try:
            if silent:
                text = (f'📶  网络不稳：已经 {secs:.0f} 秒没有收到服务器回应，'
                        f'正在自动重试（消息会补发，不用重新登录）')
                if self._offline_bar is None or not self._offline_bar.winfo_exists():
                    self._offline_bar = ctk.CTkLabel(
                        self.body, text=text, fg_color=BG_HOVER, corner_radius=0,
                        text_color=WARN, height=26,
                        font=ctk.CTkFont(family=FONT, size=12, weight='bold'))
                else:
                    self._offline_bar.configure(text=text, fg_color=BG_HOVER,
                                                text_color=WARN)
                if self._offline_bar.winfo_manager() == '':
                    self._pack_above_messages(self._offline_bar)
                self._toast('网络不稳，正在自动重试…', WARN)
            else:
                if self._offline_bar is not None and self.connected \
                        and self._offline_bar.winfo_manager():
                    self._offline_bar.pack_forget()
                if self.connected:
                    self._toast(f'网络已恢复（中断约 {secs:.0f} 秒）', ONLINE)
        except Exception:
            pass

    def _at_bottom(self, tol=0.99):
        try:
            _first, last = self.messages._parent_canvas.yview()
            return last >= tol
        except Exception:
            return True

    def _schedule_scroll(self):
        # 整块重绘期间先不滚：几十条气泡一条条滚一次，会让滚动区反复重排重画，
        # 光这一项就能吃掉好几秒（实测 80 条从 5.8 秒降到 1 秒出头）。
        # 记住「贴不贴底」，等这批画完再滚一次。
        if getattr(self, '_preloading', False):
            return               # 预加载画的是别的会话，不能碰当前视图的滚动
        if getattr(self, '_render_bulk', False):
            # 整批重绘期间不动：贴不贴底由「进入这个会话/自己发消息」时定，
            # 画的过程里每一帧都重记会把那个决定冲掉。
            return
        if getattr(self, '_scroll_pending', False):
            return
        # 记下「加这条新内容之前」是不是贴着底：贴着底才自动跟下去，
        # 正在往上翻旧消息的时候别把人拽回底部。
        self._scroll_stick = self._at_bottom()
        self._scroll_pending = True
        self.after(30, self._do_scroll)

    def _do_scroll(self):
        self._scroll_pending = False
        # 内容高度变了：隔几帧把滚动区/内嵌窗口的高度校正过来。**不碰滚动位置**，
        # 所以用户翻着旧消息时也照样能校正（不校正的话整块消息区会被旧高度压扁，
        # 眼前只剩一片背景）。
        self._schedule_sync_scrollregion()
        if not getattr(self, '_scroll_stick', True):
            return
        self._pin_bottom()

    def _schedule_sync_scrollregion(self):
        """内容高度变化后，隔几帧校正一次滚动区高度（只在确实过期时动手）。

        为什么不能只查一次：Tk 的「请求高度」是懒算的，刚 pack 完那一瞬间
        winfo_reqheight() 还可能是旧值，查一次就查了个寂寞 —— 滚动区会一直停在
        旧高度上，消息区看起来就是一片空白。
        """
        holder = getattr(self, 'messages', None)
        if holder is None:
            return
        for gap in SYNC_GAPS:
            self.after(gap, lambda h=holder: self._sync_if_stale(h))

    def _sync_if_stale(self, holder):
        """这一块消息区的内容高度跟滚动区对不上了 → 校正一次。

        注意：校正滚动区会让视图「相对内容」往上跑一点（滚动区变高了，Tk 的
        视图原点没变）。所以贴底的时候要顺手再贴回底部；用户自己翻着旧消息
        （`_scroll_stick=False`）时，只校正高度、绝不改变滚动位置。
        """
        try:
            if not self._alive(holder) or holder is not getattr(self, 'messages', None):
                return
            if not self._scrollregion_stale():
                return
            self._sync_scrollregion(holder)
            if getattr(self, '_scroll_stick', True):
                holder._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _pin_bottom(self):
        """把视图钉到最后一条消息，并连续校正几次。

        为什么不能只滚一次：新气泡 pack 进去之后，滚动区(scrollregion)是过一会儿
        才由 CTk 更新到位的。只滚一次的话我们滚的是**旧的**底部 —— 表现就是
        「滚动条明明在底下，可新消息就是看不见」。所以这里隔几十毫秒再校正几遍，
        期间只要用户自己往上滚了就立刻停手。
        """
        self._pin_token = getattr(self, '_pin_token', 0) + 1
        token = self._pin_token
        for i, gap in enumerate(PIN_GAPS):
            self.after(gap, lambda t=token, k=i: self._pin_step(t, k))

    def _make_messages(self):
        """新建一个消息滚动区（父容器和排布位置跟原来一致）。"""
        return ctk.CTkScrollableFrame(
            self.body, fg_color=BG_APP, corner_radius=0,
            scrollbar_fg_color='transparent', scrollbar_button_color=SCROLL_BTN,
            scrollbar_button_hover_color=SCROLL_HOVER)

    # ---------- 每个会话一份「已经画好的消息区」（预加载：切回来零重绘） ----------
    def _new_view(self, conv):
        return {'conv': conv, 'frame': self._make_messages(), 'sig': None,
                'msg_rows': {}, 'file_rows': {}, 'img_refs': [], 'avatar_labels': [],
                'img_pending': {}, 'render_bulk': False,
                'order_prev': None, 'token': 0, 'queue': None}

    def _bind_view_state(self, view):
        """让 self.* 指向这个视图自己的那套状态（每个会话互不干扰）。

        切走之前要把**当前正在画到一半的进度**存回上一个视图 —— 否则那半批消息
        会连着队列一起丢掉：界面上只剩前两条，而且这个「残缺」的视图还会被当成
        画好了（用户看到的就是「消息少了/点回去还是少的」）。
        """
        cur = getattr(self, '_current_view', None)
        if cur is not None and cur is not view:
            try:
                if self._alive(cur['frame']):
                    cur['queue'] = self._render_queue
                    cur['token'] = getattr(self, '_render_token', 0)
                    cur['render_bulk'] = getattr(self, '_render_bulk', False)
            except Exception:
                pass
        self.messages = view['frame']
        self._msg_rows = view['msg_rows']
        self._file_rows = view['file_rows']
        self._img_refs = view['img_refs']
        self._avatar_labels = view['avatar_labels']
        self._img_pending = view['img_pending']
        self._render_bulk = view['render_bulk']
        self._render_token = view['token']
        self._render_queue = view['queue']
        self._current_view = view
        # 这个视图上次只画了一半：接着画完（放到下一帧做，别在这里递归）
        try:
            if self._render_queue and self._render_bulk:
                token = self._render_token
                self.after(1, lambda: self._render_chunk(token))
        except Exception:
            pass

    def _show_only(self, frame):
        """让 body 里只剩这个会话的消息区。

        为什么必须这么做：每个会话各有一块自己的滚动区（缓存/预加载），显示一个
        就得把别的收起来；而且**窗口刚建好时那一块**不属于任何会话的缓存，
        以前没人管它，它会一直占着半个宽度（实测切一次会话后消息区只剩 438px，
        另一半被一块空白占着，用户看到的就是「黑块/显示不对」）。
        正文区里除成员栏以外的东西都是消息区，所以这里只留成员栏和要显示的那块。
        """
        try:
            keep = frame._parent_frame
        except Exception:
            keep = frame
        for w in list(self.body.pack_slaves()):
            if w is keep or w is self.members:
                continue
            try:
                w.pack_forget()
                # 只销毁「不属于任何会话缓存」的旧消息区；缓存的那种留着复用
                if not any(w is v['frame']._parent_frame
                           for v in self._views.values() if self._alive(v['frame'])):
                    w.destroy()
            except Exception:
                pass
        try:
            if keep.winfo_manager() != 'pack':
                if self.members.winfo_manager() == 'pack':
                    keep.pack(side='left', fill='both', expand=True, before=self.members)
                else:
                    keep.pack(side='left', fill='both', expand=True)
        except Exception:
            pass

    def _activate_view(self, view):
        """显示这个会话的滚动区，收起其它会话的。"""
        self._show_only(view['frame'])
        self._veil_hide()
        self._bind_view_state(view)
        self._hook_scroll_events()
        # 这个会话上次只画了一半（画到一半被切走/最小化）：接着画完
        try:
            if self._render_queue:
                self._render_chunk(self._render_token)
        except Exception:
            pass
        # 内容框高度也校正一次：空状态那种 place 居中的占位不参与 reqheight，
        # 不校正的话内嵌窗口只有 1px 高，整块占位被裁掉 → 右侧一片空白。
        self._schedule_sync_scrollregion()
        return view

    def _ensure_view(self, conv):
        """取（或建）某个会话的视图；超过上限就把最久没用过的丢掉。"""
        view = self._views.get(conv)
        if view is not None:
            try:
                if self._alive(view['frame']):
                    if conv in self._view_lru:
                        self._view_lru.remove(conv)
                    self._view_lru.append(conv)
                    return view
            except Exception:
                pass
            self._views.pop(conv, None)
        view = self._new_view(conv)
        self._views[conv] = view
        self._view_lru.append(conv)
        while len(self._view_lru) > VIEW_CACHE_MAX:
            self._drop_view(self._view_lru.pop(0))
        return view

    def _drop_view(self, conv):
        """丢掉一个会话的缓存视图（内存里的图片引用一起放掉）。"""
        view = self._views.pop(conv, None)
        if view is not None:
            write_diag(f'丢弃缓存视图 {conv!r}（现有 {len(self._views)} 个）')
        try:
            if conv in self._view_lru:
                self._view_lru.remove(conv)
        except Exception:
            pass
        if view is None:
            return
        view['img_refs'] = []
        view['avatar_labels'] = []
        view['img_pending'] = {}
        try:
            view['frame']._parent_frame.destroy()
        except Exception:
            pass

    def _forget_all_views(self):
        for conv in list(self._views.keys()):
            self._drop_view(conv)
        self._views = {}
        self._view_lru = []
        self._current_view = None

    def _view_sig(self):
        """「这个会话画出来应该长什么样」的指纹。"""
        return self._sig_of(self.conv)

    def _sig_of(self, conv):
        """某个会话的界面指纹（内容/范围/改动次数）。"""
        msgs = self.msgs.get(conv) or []
        last = msgs[-1] if msgs else {}
        return (len(msgs), str(last.get('mid') or last.get('text') or ''),
                self._tail_limit(conv), self._conv_rev.get(conv, 0))

    # ---------- 预加载：空闲时先把别的会话画好（点进去就是现成的） ----------
    def _schedule_preload(self, delay=None, restart=True):
        """安排一轮预加载。token 一换，上一轮的切片全部作废。

        restart=False 用于「别的会话来了新消息」这种刷新：正在预热别的会话时
        不打断它（不然消息一多就一直在重头画）；画完这一轮自然会带上新内容。
        """
        if self.calm:
            return                        # 省电模式：完全不在后台预热
        if not restart and getattr(self, '_preload_target', None) is not None:
            return
        self._preload_token = getattr(self, '_preload_token', 0) + 1
        self._preload_target = None
        self._preload_msgs = None
        self._preload_first = True
        self._preload_built = 0
        self._preload_skip = set()
        token = self._preload_token
        gap = PRELOAD_FIRST_GAP if delay is None else delay
        try:
            self.after(max(1, int(gap)), lambda: self._preload_step(token))
        except Exception:
            pass

    def _all_convs(self):
        """侧栏里所有会话（大厅 + 好友 + 群），按「最近说过话」排序。"""
        out = []
        seen = set()

        def add(conv, t):
            conv = str(conv or '')
            if not conv or conv in seen:
                return
            seen.add(conv)
            out.append((t, conv))

        for conv in (getattr(self, '_conv_ids', None) or []):
            items = self.msgs.get(conv) or []
            add(conv, items[-1].get('time') if items else 0)
        for conv, items in list(self.msgs.items()):        # 侧栏里暂时没有的会话也别漏
            add(conv, items[-1].get('time') if items else 0)
        out.sort(reverse=True)                             # 最近说话的排前面
        return [c for _t, c in out]

    def _next_preload(self):
        """挑一个「还没画好」的会话（侧栏里的全部会话都要提前画好）。"""
        cur = self.conv
        skip = getattr(self, '_preload_skip', None) or set()
        for conv in self._all_convs():
            if conv == cur or conv in skip:
                continue
            view = self._views.get(conv)
            if view is not None and view.get('sig') == self._sig_of(conv):
                continue                    # 已经是现成的，不用再画
            return conv
        return None

    def _preload_step(self, token):
        """一个预加载切片：画几条就把主线程交还出去，界面不会卡。"""
        if token != getattr(self, '_preload_token', None):
            return                          # 期间切了会话/来了新消息，这一轮作废
        try:
            self._preload_step_inner(token)
        except Exception as e:
            # 任何异常都不能让「预热」这条链断掉（以前断了就再也不预热，
            # 结果每个会话都要现画 —— 用户看到的就是「每次点开都重新渲染」）
            write_diag(f'!! 预热出错（已继续）：{e!r}')
            write_log(log_path(), f'!! 预热出错：{e!r}\n{traceback.format_exc()}')
            self._preload_target = None
            self._preload_msgs = None
            try:
                self.after(PRELOAD_GAP * 4, lambda: self._preload_step(token))
            except Exception:
                pass

    def _preload_step_inner(self, token):
        try:
            if not self.winfo_exists() or not self.connected:
                return                      # 窗口关了/断线了，不用再预热
        except Exception:
            return
        if getattr(self, '_render_bulk', False) or getattr(self, '_render_queue', None):
            self.after(PRELOAD_GAP, lambda: self._preload_step(token))
            return                          # 当前会话还在画，先让路
        # 你正在用（打字/点击/滚轮）、或者窗口刚恢复：先别预热，
        # 免得跟「把窗口重绘出来」抢主线程
        if time.monotonic() - getattr(self, '_last_input', 0.0) < PRELOAD_IDLE \
                or time.monotonic() < getattr(self, '_veil_until', 0.0):
            self.after(120, lambda: self._preload_step(token))
            return
        try:
            if not self.winfo_viewable():
                self.after(300, lambda: self._preload_step(token))
                return                      # 最小化了/被藏起来了：先不干活
        except Exception:
            pass
        if self._preload_target is None:
            if getattr(self, '_preload_built', 0) >= PRELOAD_LIMIT:
                return                      # 这一轮够本了，等下一次切会话/新消息
            conv = self._next_preload()
            if conv is None:
                return
            if self._preload_begin(conv) is False:
                # 这个会话现在不能当后台任务（正在看/正在画）：本轮先跳过它
                if not hasattr(self, '_preload_skip'):
                    self._preload_skip = set()
                self._preload_skip.add(conv)
                self.after(PRELOAD_GAP, lambda: self._preload_step(token))
                return
        first_slice = bool(self._preload_first)
        budget = PRELOAD_FIRST if first_slice else PRELOAD_CHUNK
        self._preload_first = False
        # 切片开始：把界面状态切到目标会话（画完立刻切回来，别影响当前会话）
        live_view, live_conv = self._current_view, self.conv
        live_msgs = getattr(self, 'messages', None)
        live_stick = getattr(self, '_scroll_stick', True)
        view = self._views.get(self._preload_target)
        if view is None:
            self._preload_target = None
            return
        self._bind_view_state(view)
        self.conv = self._preload_target
        self._preloading = True
        self._scroll_stick = False
        if first_slice:                     # 和「真的切进去」画出来的东西保持一致
            try:
                if getattr(self, '_preload_dropped', 0):
                    self._add_tail_hint(self._preload_dropped)
                elif not self._preload_msgs:
                    self._add_empty_hint()
            except Exception:
                pass
        try:
            q = self._preload_msgs
            drawn = 0
            t0 = time.perf_counter()
            while q and drawn < budget:
                # 后台预加载也不能让界面卡：每片最多占 PRELOAD_SECONDS
                if drawn and (time.perf_counter() - t0) >= PRELOAD_SECONDS:
                    break
                m = q.pop(0)
                drawn += 1
                try:
                    self._render(m, animate=False)
                except Exception as e:
                    write_log(log_path(), f'!! 预加载渲染失败 {m.get("t")!r}：{e!r}\n'
                                          f'{traceback.format_exc()}')
        finally:
            self._preloading = False
            self.conv = live_conv
            # 一定要把「当前在看的那块消息区」还回去：预加载画的都是别的会话，
            # 万一还错了，界面上就会显示成别人的聊天记录（只在极端时序下才会碰到，
            # 但显示串会话是绝对不能接受的，所以这里双保险）。
            if live_view is not None:
                self._bind_view_state(live_view)
            elif live_msgs is not None:
                self.messages = live_msgs
            self._scroll_stick = live_stick
        if q:
            self.after(PRELOAD_GAP, lambda: self._preload_step(token))
            return
        # 这个会话画完了：登记指纹，接着画下一个
        try:
            view['sig'] = self._sig_of(view['conv'])
            self._sync_offscreen(view)
        except Exception:
            pass
        write_diag(f'预热完成：{view["conv"]!r}（已有视图 {len(self._views)} 个）')
        self._preload_target = None
        self._preload_msgs = None
        self._preload_built = getattr(self, '_preload_built', 0) + 1
        self.after(PRELOAD_GAP, lambda: self._preload_step(token))

    def _preload_begin(self, conv):
        """给一个会话准备一块只在后台画的消息区（不显示出来）。

        正在被用户看着的、或者正在分帧画着的会话，绝不能当后台任务来对待：
        那会把它的渲染状态和队列踩掉（用户看到的就是「这个会话只剩一两条消息」）。
        """
        if conv == self.conv:
            return False
        view = self._views.get(conv)
        if view is not None and (view.get('queue') or view.get('render_bulk')):
            return False
        view = self._ensure_view(conv)
        old = view['frame']
        frame = self._make_messages()
        view.update({'frame': frame, 'msg_rows': {}, 'file_rows': {}, 'img_refs': [],
                     'avatar_labels': [], 'img_pending': {}, 'render_bulk': False,
                     'token': 0, 'queue': None, 'sig': None})
        try:
            old._parent_frame.destroy()
        except Exception:
            pass
        msgs = list(self.msgs.get(conv) or [])
        dropped = max(0, len(msgs) - self._tail_limit(conv))
        self._preload_target = conv
        self._preload_first = True
        self._preload_msgs = msgs[-self._tail_limit(conv):] if dropped else msgs
        self._preload_dropped = dropped
        return view

    def _sync_offscreen(self, view):
        """预加载画好的滚动区：把滚动区按真实高度定下来（它还没显示，量不到宽度）。"""
        try:
            holder = view['frame']
            cv = holder._parent_canvas
            h = max(int(holder.winfo_reqheight()), 1)
            w = max(int(cv.winfo_reqwidth()), 1)
            cv.configure(scrollregion=(0, 0, w, h))
        except Exception:
            pass

    def _cancel_preload(self, conv=None):
        """这个会话马上就要「直接显示」了，后台那一轮预加载就别再画它。

        不取消的话会出现两份同时在往同一个滚动区里塞消息：表现就是同一句话
        画了两遍，或者点开之后还要闪一下重画（用户说的「又要重新渲染」）。
        """
        if getattr(self, '_preload_target', None) is None:
            return
        if conv is not None and self._preload_target != conv:
            return
        self._preload_target = None
        self._preload_msgs = None

    def _show_loading(self):
        """整块重绘期间先摆一个「正在打开…」占位（现在由加载遮罩负责，这里兜底）。"""
        self._veil_show('正在打开', full=False)

    # ---------- 加载遮罩：盖住「还没画出来」的地方，别让用户看到黑块 ----------
    def _paint_window_bg(self):
        """把窗口自己的底色设成主题色。

        没画出来的区域显示的是**父窗口的底色**，Tk 默认是黑的 —— 主线程一忙
        （重绘、换肤、从任务栏恢复），用户看到的就是一片黑块。把窗口底色改成
        主题背景色，最差也只是「一块和背景同色的空白」，不会突兀。
        """
        try:
            tk.Tk.configure(self, bg=BG_APP)
        except Exception:
            try:
                self.configure(bg=BG_APP)
            except Exception:
                pass
        for name in ('main', 'chat', 'login'):
            w = getattr(self, name, None)
            try:
                if w is not None and self._alive(w):
                    w.configure(fg_color=BG_APP)
            except Exception:
                pass

    def _veil_build(self):
        """遮罩用**纯 tk 控件**：CTk 的每个控件都是一块 canvas，画一层要几十毫秒；
        恢复窗口时我们要的是「最快速度先盖上一层」，所以这里越简单越好。"""
        f = tk.Frame(self, bg=BG_APP, highlightthickness=0, bd=0)
        box = tk.Frame(f, bg=BG_APP)
        box.place(relx=0.5, rely=0.5, anchor='center')
        lbl = tk.Label(box, text='正在打开', bg=BG_APP, fg=TEXT_DIM, bd=0,
                       font=(FONT, 13))
        lbl.pack(pady=(0, 10))
        track = tk.Frame(box, bg=BG_PANEL, width=180, height=4)
        track.pack()
        track.pack_propagate(False)
        bar = tk.Frame(track, bg=ACCENT, width=56, height=4)
        bar.place(x=0, y=0)
        self._veil = f
        self._veil_label, self._veil_track, self._veil_bar = lbl, track, bar
        return f

    def _veil_show(self, text='正在打开', full=True):
        """显示加载遮罩。full=True 盖整个窗口（换肤），否则只盖正文区。

        为什么要遮罩：CTk 的每个控件都是一块 canvas，主线程忙着建控件时，那些
        区域在屏幕上就是**没画出来的黑块**（用户截图里那种）。遮罩本身是一整块
        主题色 + 一条来回跑的进度条：先把它画出来再干活，用户看到的就是
        「正在打开」，而不是一片黑。
        """
        try:
            if self.calm:
                return                    # 省电模式：不铺遮罩
            if not self._alive(getattr(self, '_veil', None)):
                self._veil_build()
            write_diag(f'显示加载遮罩：{text}（full={full}）')
            self._veil_until = time.monotonic() + 0.7    # 这段时间先别预热
            self._veil_text = text
            self._veil_label.configure(text=text)
            if full:
                self._veil.place(in_=self, relx=0, rely=0, relwidth=1, relheight=1)
            else:
                self._veil.place(in_=self.body, relx=0, rely=0, relwidth=1, relheight=1)
            self._veil.lift()
            # 最少显示一会儿：画得特别快时（几十毫秒）别让遮罩闪一下就没了
            self._veil_min_until = time.monotonic() + VEIL_MIN_SHOW
            self._veil_token = getattr(self, '_veil_token', 0) + 1
            self._veil_step(self._veil_token, 0)
            stop = getattr(self, '_veil_stop', None)
            if stop is not None:
                try:
                    self.after_cancel(stop)
                except Exception:
                    pass
            # 兜底：万一哪条路径忘了收，最多 1.2 秒后自己消失（遮罩绝不能久留，
            # 它是盖在界面上的，留久了既像黑块又会挡住输入）
            self._veil_stop = self.after(1200, self._veil_hide)
        except Exception:
            pass

    def _veil_up(self):
        try:
            v = getattr(self, '_veil', None)
            return v is not None and self._alive(v) and v.winfo_manager() != ''
        except Exception:
            return False

    def _veil_step(self, token, i):
        if token != getattr(self, '_veil_token', None):
            return
        v = getattr(self, '_veil', None)
        if not self._alive(v):
            return
        try:
            if v.winfo_manager() == '':
                return                       # 已经收起来了，停止动画
            span = 180 - 56
            k = i % 20
            pos = int(span * k / 9.0) if k <= 9 else int(span * (19 - k) / 9.0)
            self._veil_bar.place(x=min(span, max(0, pos)), y=0)
            self._veil_label.configure(
                text=getattr(self, '_veil_text', '正在打开') + '·' * (i % 4))
        except Exception:
            pass
        self.after(110, lambda: self._veil_step(token, i + 1))

    def _veil_hide(self):
        """收起遮罩（如果它刚显示不到 VEIL_MIN_SHOW，就等够再收，免得闪一下）。"""
        wait = getattr(self, '_veil_min_until', 0.0) - time.monotonic()
        if wait > 0.01:
            stop = getattr(self, '_veil_stop2', None)
            if stop is not None:
                try:
                    self.after_cancel(stop)
                except Exception:
                    pass
            self._veil_stop2 = self.after(int(wait * 1000) + 5, self._veil_hide)
            return
        if getattr(self, '_veil_min_until', 0.0):
            write_diag('收起加载遮罩')
        self._veil_min_until = 0.0
        self._veil_token = getattr(self, '_veil_token', 0) + 1
        stop = getattr(self, '_veil_stop', None)
        if stop is not None:
            try:
                self.after_cancel(stop)
            except Exception:
                pass
            self._veil_stop = None
        v = getattr(self, '_veil', None)
        if self._alive(v):
            try:
                v.place_forget()
            except Exception:
                pass

    # ---------- 从任务栏/被遮住的状态回来：什么都别动 ----------
    def _on_unmap(self, event=None):
        if getattr(event, 'widget', None) is not self:
            return
        self._was_unmapped = True
        # 最小化期间先不预热（恢复时系统要重画整个窗口，别跟它抢 CPU）
        self._last_input = time.monotonic()
        write_diag(f'窗口被最小化/隐藏（conv={self.conv!r} 视图={len(self._views)} '
                   f'当前消息区控件={len(getattr(self, "messages", None).winfo_children()) if self._alive(getattr(self, "messages", None)) else -1}）')

    def _on_map(self, event=None):
        """窗口重新显示出来。

        **这里绝对不能再动一次布局/显示**：之前「最小化时把消息区收起来、
        恢复后再放回来」的做法，会让窗口在恢复之后**又整体重排重画一遍**
        —— 用户看到的就是「一瞬间没事，很快又一片黑」。现在恢复时只做两件
        不涉及重绘的事：把预热推迟一会儿、确认消息区还挂在原位。
        """
        if getattr(event, 'widget', None) is not self:
            return
        was = self._was_unmapped
        self._was_unmapped = False
        write_diag(f'窗口显示出来（was_unmapped={was} conv={self.conv!r}）')
        self._ensure_messages_shown()          # 兜底，正常情况下是空操作
        if was:
            # 真的是从最小化/隐藏回来的：2 秒内不预热，别跟系统重画抢主线程
            self._last_input = time.monotonic()
            self._veil_until = self._last_input + 2.0

    def _ensure_messages_shown(self):
        """兜底：万一消息区没挂在界面上，把同一块已画好的区域放回去。

        正常流程不会走到这里；就算走到了，也只是重新 pack 现成的区域，
        不做任何重绘/重建工作。
        """
        try:
            view = self._current_view
            frame = view['frame'] if view is not None else getattr(self, 'messages', None)
            if frame is None or not self._alive(frame):
                return
            if frame._parent_frame.winfo_manager() == 'pack':
                return
            write_diag(f'恢复：消息区没挂着，重新放进界面 conv={self.conv!r}')
            self._show_only(frame)
            self._sync_scrollregion(frame)
        except Exception:
            pass

    def _flush_pending_map(self):
        """新的消息区在屏幕外画完了：这时候才显示出来（只这一次排版，很快）。"""
        frame = getattr(self, '_pending_map_frame', None)
        if frame is None:
            return
        self._pending_map_frame = None
        self._veil_hide()                  # 画好了：把遮罩收掉
        view = self._current_view
        if view is None:
            return
        if view['frame'] is not frame:
            # 画好的这块不是当前会话的（画的期间用户又切走了）。
            # **这里绝对不能直接 return**：切会话时我们已经把「上一个会话那块」
            # 收起来了（为了不串会话），直接返回就等于把界面留成一大片空白 ——
            # 用户看到的就是「发消息毫无反应、点几次会话栏才出来」。
            # 正确做法：改挂当前会话那块。
            write_diag('要显示的块不是当前会话的，改挂当前会话那块')
            frame = view['frame']
            try:
                if frame is None or not self._alive(frame):
                    return
            except Exception:
                return
        else:
            try:
                if not self._alive(frame):
                    return
            except Exception:
                return
        # 直接挂上去。**不能**在这里「等它自己变成已挂载」——pack 的动作就在
        # 下面这行 _show_only 里，等是等不来的：以前那段「重试 8 次、每次 80ms」
        # 的代码等于每次整块重绘都先白等 0.64 秒，界面上那段时间什么都没有
        # （日志里成片的「消息区画好但未挂上，第 N 次重试」就是它）。
        # 现在先挂，挂不上才真的重试。
        self._show_only(frame)
        packed = True
        try:
            packed = frame._parent_frame.winfo_manager() == 'pack'
        except Exception:
            packed = True                  # 查不出来就当挂上了，别反复折腾
        if not packed:
            tries = getattr(self, '_map_retry', 0) + 1
            self._map_retry = tries
            if tries <= 8:
                write_diag(f'消息区画好但未挂上，第 {tries} 次重试显示 conv={self.conv!r}')
                self._pending_map_frame = frame
                self._pending_map_at = time.monotonic()
                self.after(80, self._flush_pending_map)
                return
            write_diag(f'消息区重试 8 次仍未挂上，放弃 conv={self.conv!r}')
        self._map_retry = 0
        self._sync_scrollregion(frame)
        if getattr(self, '_scroll_stick', True):
            self._pin_bottom()

    def _hide_other_frames(self, keep):
        """把界面上「别的会话」的消息区先收起来（**只收起，不销毁**，缓存还在）。

        为什么要它：新会话的内容是在屏幕外画好再一次性显示的，画的那几百毫秒里
        标题已经换成新会话了，如果上一个会话的消息区还挂在界面上，用户看到的就是
        「顶着 A 的标题、显示着 B 的聊天记录」—— 也就是他报的「聊天内容串到别的
        会话里」。宁可先空一下（就几百毫秒），也绝不能显示错会话的内容。
        """
        try:
            keep_pf = keep._parent_frame
        except Exception:
            keep_pf = None
        for w in list(self.body.pack_slaves()):
            if w is self.members or w is keep_pf:
                continue
            try:
                w.pack_forget()
            except Exception:
                pass

    def _recreate_messages(self):
        """切会话：优先复用之前画好的视图（预加载）。

        以前每次切会话都整块重绘：几十上百条消息要重新建控件、Tk 再把整个
        滚动区重排一遍，主线程被占住几百毫秒到几秒 —— 那段时间窗口上就是
        一片还没画出来的黑块，也就是用户看到的「加载界面」。
        现在每个会话各自留一份画好的滚动区，切回来直接显示；只有内容真的
        变了（来了新消息、撤回、改了显示范围）才重画这一个会话。
        """
        conv = self.conv
        self._cancel_preload(conv)
        view = self._ensure_view(conv)
        if view['sig'] == self._view_sig():
            self._activate_view(view)          # 内容没变：零重绘
            return view
        # 限速：同一个会话 1.5 秒内只重建一次。没有这道闸，任何「以为界面是空的」
        # 的自检都会把消息区反复重建，界面就会一直空着（用户说的「啥都没有」）。
        now = time.monotonic()
        last = getattr(self, '_rebuild_at', {}).get(conv, 0.0)
        if (not getattr(self, '_force_rebuild', False)
                and now - last < 1.5
                and getattr(self, '_pending_map_frame', None) is None):
            if self._alive(view['frame']):
                view['sig'] = self._view_sig()
                self._activate_view(view)
            return None
        if not hasattr(self, '_rebuild_at'):
            self._rebuild_at = {}
        self._rebuild_at[conv] = now
        write_diag(f'整块重绘消息区：conv={conv!r} 条数={len(self.msgs.get(conv) or [])} '
                   f'原因=内容变了（sig {view["sig"]} -> {self._view_sig()}）')
        # 内容变了：给这个会话换一个干净的消息区，**先在屏幕外画**
        # （显示的滚动区里一条条加，Tk 每加一条都要整块重排，20 条要 2.3 秒；
        #   屏幕外画完再一次性显示只要 0.3 秒左右）
        old = view['frame']
        frame = self._make_messages()
        if view.get('queue'):
            write_diag(f'重建消息区，丢弃未画完的 {len(view["queue"])} 条 '
                       f'conv={view.get("conv")!r}')
        view.update({'frame': frame, 'msg_rows': {}, 'file_rows': {}, 'img_refs': [],
                     'avatar_labels': [], 'img_pending': {}, 'render_bulk': False,
                     'token': 0, 'queue': None})
        self._pending_map_frame = frame
        self._pending_map_at = time.monotonic()   # 兜底显示用的「等了多久」起点
        # 新内容还在屏幕外画，这里**立刻把上一个会话那块收起来**：不收的话，
        # 标题已经换成新会话了，界面却还显示着上一个会话的聊天记录
        # —— 用户看到的就是「聊天内容串到别的会话里」。收起（不销毁）缓存还在。
        self._hide_other_frames(frame)
        self._bind_view_state(view)
        try:
            old._parent_frame.destroy()
        except Exception:
            pass
        self._hook_scroll_events()
        view['sig'] = self._view_sig()
        return None

    def _content_box_height(self, holder=None):
        """内容框该有多高：内容真实高度，但至少撑满可视高度。

        为什么要「至少撑满」：空状态那句「请选择聊天会话」是用 place 居中摆的，
        而 **place 的控件不参与 `winfo_reqheight()`** —— 只用内容高（1px）去钉
        内嵌窗口高度的话，整块占位会被裁掉，右侧看起来就是一片空白（登录后
        第一眼就是这个画面）。实测：滚动区 '0 0 684 1'，截图像素是纯色。
        """
        holder = holder or self.messages
        h = max(int(holder.winfo_reqheight()), 1)
        try:
            h = max(h, int(holder._parent_canvas.winfo_height()))
        except Exception:
            pass
        return h

    def _scrollregion_stale(self):
        """内容高度变了、滚动区/内嵌窗口却还停在旧高度？

        现场（实测抓到的）：空会话时 _sync_scrollregion() 会把内嵌窗口的高度钉成
        当时的内容高（1px）；之后来了第一条消息，Tk 已经算出内容高 141px，可没人
        再同步一次 —— 内嵌窗口还是 1px，**整块消息区被压成一条线**，用户看到的就是
        「发了消息界面一片空白、点一下左侧会话栏才出来」（点会话栏会走
        _flush_pending_map，那里会同步一次）。这里只做一次便宜的比对，
        对得上就什么都不做。
        """
        try:
            holder = self.messages
            cv = holder._parent_canvas
            want = self._content_box_height(holder)
            sr = str(cv.cget('scrollregion') or '').split()
            if len(sr) != 4 or abs(float(sr[3]) - want) > 1:
                return True
            try:
                cur = int(float(cv.itemcget(holder._create_window_id, 'height')))
            except Exception:
                cur = want
            return cur != want
        except Exception:
            return False

    def _sync_scrollregion(self, holder=None, pin_height=True):
        """按「真实内容高度」重算滚动区（**不强制重排**）。

        CTk 只在内部 frame 收到 <Configure> 时才更新 scrollregion，而 frame 一旦
        被 canvas 的窗口项撑大，**不会自己缩回去** —— 实测切会话时越切越大：
        40 条消息的 frame 高 4640，切到 3 条的会话后仍停在 4640，再切回来变成
        7760。后果就是滚动条明明拉到底，眼前却是一整屏空白（用户反馈的
        「点进去发消息看不到 / 滚动条在底下」）。
        这里按内容真实高度手动校正，并把内嵌窗口的高度也钉回去。

        注意：**这里绝不能调 update_idletasks()** —— 它会在 after 回调里被调用，
        在定时器回调里强制重排会让 Tk 重入，实测直接把界面卡死（测试套件挂住
        十几分钟）。贴底分了几帧做，帧与帧之间 Tk 自己会把布局算完，足够了。
        """
        holder = holder or self.messages
        try:
            cv = holder._parent_canvas
            h = self._content_box_height(holder)
            w = max(int(cv.winfo_width()), 1)
            cv.configure(scrollregion=(0, 0, w, h))
            if pin_height:
                try:
                    cv.itemconfigure(holder._create_window_id, height=h)
                except Exception:
                    pass
            return h
        except Exception:
            return 0

    def _last_row_visible(self):
        """最后一行消息是不是真的落在可视区里（贴底的自检标准）。

        用内容坐标算，不依赖屏幕位置 —— 窗口还没摆好时屏幕坐标会乱报。
        """
        try:
            cv = self.messages._parent_canvas
            kids = self.messages.winfo_children()
            if not kids:
                return True
            total = max(int(self.messages.winfo_reqheight()), 1)
            f, _l = cv.yview()
            view_h = max(int(cv.winfo_height()), 1)
            start, end = f * total, f * total + view_h
            row = kids[-1]
            y, h = row.winfo_y(), row.winfo_height()
            return (y + h) <= (end + 2) and y >= (start - 2)
        except Exception:
            return True

    def _pin_step(self, token, i):
        if token != getattr(self, '_pin_token', None):
            return                       # 又切了会话/又发了消息，这一轮作废
        # 1) 内容长高了、滚动区/内嵌窗口却还停在旧高度 → 立刻同步回来。
        #    这一步和「用户有没有滚动」无关：它是「发了消息界面一片空白」的根因
        #    （空会话时内嵌窗口被钉成 1px，第一条消息进来后没人再同步），
        #    所以放在下面那条「别跟用户抢滚动条」的判断之前。
        try:
            stale = self._scrollregion_stale()
            if stale:
                self._sync_scrollregion()
        except Exception:
            return
        # 2) 用户自己滚过（滚轮/拖滚动条）就别再跟他抢 —— 用「意图」判断，而不是
        # 「现在到没到底」：布局还没算完时 yview 也到不了底，那样会误判成用户滚了，
        # 于是校正提前收手，消息就留在视野外面（这正是「发消息看不到」的原因）。
        if i > 0 and time.monotonic() - getattr(self, '_user_scrolled_at', 0.0) < 0.5:
            return
        try:
            canvas = self.messages._parent_canvas
            canvas.yview_moveto(1.0)
            # 只有「滚动区过期」或「最后一条确实看不见」时才再动一次滚动区 ——
            # 每次 itemconfigure 都会让 Tk 把整个消息区重新排一遍（几十条消息就是
            # 上百毫秒），大多数情况滚动区本来就是对的，不用白花这个钱。
            if stale or not self._last_row_visible():
                self._sync_scrollregion()
                canvas.yview_moveto(1.0)
            self._upgrade_visible_images()
        except Exception:
            return

    def _hook_scroll_events(self):
        """监听滚动区：用户自己滚动时记一笔时间。

        贴底校正会看这个时间戳，避免和用户抢滚动条（也不影响 CTk 自己的滚动）。
        """
        try:
            cv = self.messages._parent_canvas
            for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                cv.bind(seq, self._note_user_scroll, add='+')
        except Exception:
            pass
        try:
            bar = getattr(self.messages, '_scrollbar', None)
            if bar is not None:
                bar.configure(command=self._on_scrollbar)
        except Exception:
            pass

    def _note_user_scroll(self, event=None):
        self._user_scrolled_at = time.monotonic()
        self._last_input = self._user_scrolled_at
        self.after(20, self._upgrade_visible_images)   # 滚过来就把图片补上
        return None                      # 不吞掉事件，CTk 照常滚动

    def _note_input(self, event=None):
        """任何键鼠操作都记一下时间（预加载靠它判断「你是不是正在用」）。

        顺手把加载遮罩收掉：遮罩是盖在界面上的，万一哪条路径忘了收，用户一动手
        就立刻让路 —— 绝不能让「遮罩」反过来挡住输入（那看起来就是「发不出消息」）。
        """
        self._last_input = time.monotonic()
        if self._veil_up():
            self._veil_min_until = 0.0
            self._veil_hide()
        return None                      # 不吞掉事件

    def _on_scrollbar(self, *args):
        self._user_scrolled_at = self._last_input = time.monotonic()
        try:
            self.messages._parent_canvas.yview(*args)
        except Exception:
            pass

    @staticmethod
    def _scroll_to_bottom(canvas):
        try:
            _first, last = canvas.yview()
            if last < 0.999:
                canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _clear_view(self):
        for w in self.messages.winfo_children():
            w.destroy()
        self._file_rows.clear()
        self._img_refs.clear()
        self._avatar_labels = []         # 消息区里的头像控件（换头像时原地更新）
        self._msg_rows = {}              # mid -> 这一条消息的行控件（撤回时原地换掉）
        self._views = {}                 # conv -> 已画好的视图（预加载）
        self._view_lru = []              # 最近用过的会话（末尾最新）
        self._current_view = None
        self._conv_rev = {}              # conv -> 内容改动次数（撤回等）
        self._preload_done = set()       # 这一轮已经提前画好的会话
        self._preload_target = None
        self._preload_msgs = None
        self._preloading = False
        self._conv_ids = []
        self._pending_map_frame = None
        self._loading_frame = None
        self._img_pending = {}           # fid -> 等着滚到眼前才画的图片
        self._render_bulk = False        # 免得上一轮没画完就把滚动一直关着
        self._sync_scrollregion()        # 内容清空了，滚动区也要缩回去

    def _add_sys(self, text):
        lbl = ctk.CTkLabel(self.messages, text=text, fg_color=BG_PANEL, corner_radius=12,
                           text_color=TEXT_DIM, font=ctk.CTkFont(family=FONT, size=11))
        lbl.pack(pady=5, padx=20)
        self._schedule_scroll()
        return lbl

    def _add_empty_hint(self):
        """「这里还没有消息，打个招呼吧～」占位。打上标记，真有消息时好删掉。"""
        lbl = self._add_sys('这里还没有消息，打个招呼吧～')
        try:
            lbl._empty_hint = True
        except Exception:
            pass
        return lbl

    def _drop_empty_hint(self):
        """真的有消息进来了：把「这里还没有消息」那行占位删掉。

        以前它一直留在最上面，第一条消息下面挂着「这里还没有消息，打个招呼吧～」，
        看着就像界面没刷新。
        """
        try:
            for w in self.messages.winfo_children():
                if getattr(w, '_empty_hint', False):
                    w.destroy()
        except Exception:
            pass

    def _add_tail_hint(self, dropped):
        """「更早的 N 条没有显示，点这里显示」那一行（普通重绘和预加载共用）。"""
        hint = self._add_sys(f'（更早的 {dropped} 条没有显示，点这里显示）')
        try:
            hint.configure(text_color=ACCENT, cursor='hand2')
            hint.bind('<Button-1>', lambda *a: self._more_history())
        except Exception:
            pass
        return hint

    def _plain(self, parent):
        """一个「透明」的纯 tk 容器。

        CTk 的 Frame 每个都要额外建 canvas + 一堆 item，切会话时几十条消息的
        布局开销主要就花在这上面（实测 40 条约 1.4 秒在布局/重画）。这些容器
        本来就只是排版用的（不圆角、不上色），换成 tk.Frame 视觉上一模一样。
        """
        try:
            return tk.Frame(parent, bg=BG_APP, bd=0, highlightthickness=0)
        except Exception:
            return ctk.CTkFrame(parent, fg_color='transparent')

    def _bubble(self, sender, segs, mine, time_ts=None, mention=False, animate=True,
                region=None, mid=None, conv=None):
        row = self._plain(self.messages)
        row.pack(fill='x', padx=12, pady=3)
        row._mid = mid
        row._sender = sender
        row._mine = bool(mine)
        row._conv = conv or self.conv
        row._time = time_ts or now_ts()
        row._text = ' '.join(str(t) for t, _s in segs)
        if mid:
            self._msg_rows[mid] = row
        # 右键消息：撤回（服务端还会再判一次权限和时间）
        row.bind('<Button-3>', lambda e, r=row: self._popup_msg_menu(e, r))
        for ch in row.winfo_children():
            try:
                self._bind_right(ch, row)
            except Exception:
                pass
        if mine:
            col = self._plain(row)
            col.pack(side='right', anchor='e')
        else:
            av = self._avatar(sender, 38)
            if av is not None:
                av_lbl = ctk.CTkLabel(row, image=av, text='', width=38,
                                      fg_color='transparent', text_color=TEXT)
                av_lbl.pack(side='left', anchor='n', padx=(0, 8))
                av_lbl._avatar_nick = sender      # 头像到手时原地换图，不整块重绘
                av_lbl._avatar_size = 38
                self._avatar_labels.append(av_lbl)
            col = self._plain(row)
            col.pack(side='left', anchor='w')
            meta = self._plain(col)
            meta.pack(anchor='w', padx=8)
            ctk.CTkLabel(meta, text=sender, anchor='w', height=18,
                         text_color=self._name_color(sender),
                         font=ctk.CTkFont(family=FONT, size=12, weight='bold')).pack(side='left')
            if region:      # IP 属地：由服务端下发，界面上强制显示
                ctk.CTkLabel(meta, text=region, anchor='w', height=18, text_color=REGION,
                             font=ctk.CTkFont(family=FONT, size=10)).pack(
                    side='left', padx=(6, 0))

        color = BUBBLE_OUT if mine else (BUBBLE_MENTION if mention else BUBBLE_IN)
        bubble = ctk.CTkFrame(col, fg_color=color, corner_radius=POP_FROM)
        bubble.pack(anchor='e' if mine else 'w')
        if animate:
            self._pop(row, bubble, mine, color)
        else:
            bubble.configure(corner_radius=BUBBLE_RADIUS)

        # 表情就用文字渲染（用户要求恢复文字形式）。
        # 纯表情的消息用大一号的 emoji 字体，看着像表情而不是小字。
        if len(segs) == 1 and self._is_emoji_only(segs[0][0]):
            ctk.CTkLabel(bubble, text=segs[0][0].strip(), justify='left', anchor='w',
                         wraplength=470, text_color=TEXT,
                         font=ctk.CTkFont(family=EMOJI_FONT, size=20)).pack(
                anchor='w', padx=12, pady=(6, 2))
        else:
            for idx, (text, style) in enumerate(segs):
                lbl = ctk.CTkLabel(bubble, text=text, justify='left', anchor='w',
                                   wraplength=470,
                                   text_color=style.get('color', TEXT),
                                   font=ctk.CTkFont(family=FONT,
                                                    size=style.get('size', 14),
                                                    weight='bold' if style.get('bold')
                                                    else 'normal'))
                lbl.pack(anchor='w', padx=12, pady=(8 if idx == 0 else 2, 0))
        if time_ts:
            ctk.CTkLabel(bubble, text=fmt_time(time_ts), anchor='e', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=10)).pack(
                anchor='e', padx=12, pady=(1, 6))
        else:
            ctk.CTkFrame(bubble, height=4, fg_color='transparent').pack()
        self._schedule_scroll()
        return bubble

    def _bind_right(self, widget, row):
        """把右键菜单绑到这一行的所有子控件上（Tk 事件不会冒泡到父控件）。"""
        try:
            widget.bind('<Button-3>', lambda e, r=row: self._popup_msg_menu(e, r))
        except Exception:
            pass
        for ch in widget.winfo_children():
            self._bind_right(ch, row)

    def _msg_row_of(self, widget):
        """从被点的控件往上找到属于某条消息的那一行。"""
        p = widget
        for _ in range(6):
            if p is None:
                return None
            if getattr(p, '_mid', None):
                return p
            p = getattr(p, 'master', None)
        return None

    def _can_recall(self, row):
        """我能不能撤回这条消息（服务端还会再验一次）。"""
        c = self.client
        if c is None or not row._mid:
            return False
        mine = row._mine or (row._sender or '').strip().lower() == (c.me or '').lower()
        if mine:
            t = getattr(row, '_time', 0) or 0
            return (not t) or (time.time() - float(t) <= RECALL_WINDOW + 1)
        # 群里：群主/管理员可以不限时间撤回普通成员的消息
        if conv_kind(row._conv) != 'group':
            return False
        gid = str(row._conv)[2:]
        me_role = self._my_role(gid)
        his_role = 'member'
        info = (getattr(c, 'group_infos', None) or {}).get(gid) or {}
        for m in (info.get('members') or []):
            if (m.get('nick') or '').strip().lower() == (row._sender or '').strip().lower():
                his_role = m.get('role') or 'member'
                break
        return me_role in ('owner', 'admin') and his_role == 'member'

    def _popup_msg_menu(self, event, row):
        """右键消息：撤回 / 复制。"""
        try:
            row = row or self._msg_row_of(event.widget)
            if row is None or not getattr(row, '_mid', None):
                return
            menu = tk.Menu(self, tearoff=0, bg=BG_PANEL, fg=TEXT,
                           activebackground=BG_HOVER, activeforeground=TEXT, bd=0,
                           font=(FONT, 10))
            if self._can_recall(row):
                menu.add_command(
                    label='撤回这条消息',
                    command=lambda r=row: self._recall_msg(r))
            menu.add_command(label='复制文字',
                             command=lambda r=row: self._copy_msg(r))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        except Exception as e:
            write_log(log_path(), f'!! 消息右键菜单出错：{e!r}\n{traceback.format_exc()}')

    def _copy_msg(self, row):
        text = getattr(row, '_text', '') or ''
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._toast('已复制')
        except Exception:
            pass

    def _recall_msg(self, row):
        try:
            self.client.recall(row._conv, row._mid)
            self._toast('撤回请求已发出')
        except Exception as e:
            self._toast(f'撤回失败：{e}', WARN)

    def _apply_recall(self, conv, mid, by):
        """把一条消息换成「XX 撤回了一条消息」（原地换，不整块重绘）。"""
        self._conv_rev[conv] = self._conv_rev.get(conv, 0) + 1   # 内容变了，视图作废
        msgs = self.msgs.get(conv) or []
        replaced = False
        for i, m in enumerate(msgs):
            if str(m.get('mid') or '') == str(mid):
                who = m.get('from') or by or ''
                me = (self.client.me if self.client else '') or ''
                text = ('你撤回了一条消息'
                        if who.strip().lower() == me.strip().lower()
                        else f'{who} 撤回了一条消息')
                msgs[i] = {'t': 'system', 'conv': conv, 'kind': 'recall',
                           'text': text, 'time': m.get('time') or now_ts(),
                           'mid': mid}
                replaced = True
                break
        if conv != self.conv:
            # 别的会话被撤回了，缓存作废，重排（正在画它才打断，否则等这轮画完）
            self._schedule_preload(PRELOAD_GAP, restart=(self._preload_target == conv))
            return
        row = (getattr(self, '_msg_rows', None) or {}).get(str(mid))
        if row is not None and self._alive(row):
            try:
                nxt = self._next_widget(row)
                row.destroy()
                lbl = ctk.CTkLabel(self.messages, text=self._recall_text(conv, mid, by),
                                   fg_color=BG_PANEL, corner_radius=12, text_color=TEXT_DIM,
                                   font=ctk.CTkFont(family=FONT, size=11))
                if nxt is not None:
                    lbl.pack(pady=5, padx=20, before=nxt)
                else:
                    lbl.pack(pady=5, padx=20)
                self._msg_rows.pop(str(mid), None)
                self._schedule_scroll()
                return
            except Exception:
                pass
        if replaced:
            self._render_conv()      # 找不到那一行（比如已经被重画过）就整块重画

    def _recall_text(self, conv, mid, by):
        for m in (self.msgs.get(conv) or []):
            if str(m.get('mid') or '') == str(mid):
                return m.get('text') or '消息已撤回'
        who = by or ''
        me = (self.client.me if self.client else '') or ''
        return '你撤回了一条消息' if who == me else f'{who} 撤回了一条消息'

    def _next_widget(self, row):
        """row 后面紧挨着的那一行（用来把新控件插回原来的位置）。"""
        try:
            kids = self.messages.winfo_children()
            i = kids.index(row)
            return kids[i + 1] if i + 1 < len(kids) else None
        except Exception:
            return None

    def _pop(self, row, bubble, mine, color):
        """新消息的气泡特效：从自己那一侧滑进来 + 圆角收拢 + 亮一下再落定。

        为什么是这个组合（都是实测过的）：
          · 横向滑动（pack 的 padx）一帧约 25ms，可以接受 —— 而且每行都是
            fill='x'，横向变化不会推动上下其他消息；
          · 纵向滑动（pady）一帧 145ms，会把整列消息都推一遍，坚决不用；
          · 圆角/颜色是纯绘制，一帧几毫秒，随便加。
        消息一次涌进来好几条时（POP_MAX 封顶）直接落定，优先保流畅。
        """
        final_pad = (12, 12)

        def settle():
            try:
                row.pack_configure(padx=final_pad)
                bubble.configure(corner_radius=BUBBLE_RADIUS, fg_color=color)
            except Exception:
                pass

        if getattr(self, '_pops', 0) >= POP_MAX:
            settle()
            return
        self._pops = getattr(self, '_pops', 0) + 1
        left, right = final_pad

        def step(i):
            if i >= len(POP_FRAMES):
                settle()
                self._pops = max(0, getattr(self, '_pops', 1) - 1)
                return
            off, radius, lift = POP_FRAMES[i]
            try:
                if mine:
                    row.pack_configure(padx=(left, right + off))
                else:
                    row.pack_configure(padx=(left + off, right))
                bubble.configure(corner_radius=radius,
                                 fg_color=_shade(color, lift))
            except Exception:
                self._pops = max(0, getattr(self, '_pops', 1) - 1)
                return
            self.after(POP_INTERVAL, lambda: step(i + 1))
        step(0)

    def _render(self, m, animate=True):
        t = m.get('t')
        ts = m.get('time', 0)
        me = self.client.me if self.client else ''
        # animate：只有「刚收到的新消息」才淡入。整块重绘（切会话、拉历史、
        # 重连）时如果每条都重放一次淡入动画，屏幕上就是一片一抽一抽的闪，
        # 而且每次 configure 都要重画，几十条就能卡好几秒。
        animate = animate and not m.get('history')
        mid = m.get('mid')
        conv = m.get('conv') or self.conv
        if t == 'chat':
            sender = m.get('from', '')
            mine = bool(m.get('self')) or sender == me
            mention = (not mine) and (me in (m.get('mentions') or []))
            segs = []
            if mention:
                segs.append(('@你', {'size': 11, 'color': MENTION_TEXT, 'bold': True}))
            segs.append((m.get('text', ''), {'size': 14}))
            return self._bubble(sender, segs, mine, ts, mention=mention,
                                animate=animate, region=m.get('region'),
                                mid=mid, conv=conv)
        elif t == 'me':
            sender = m.get('from', '')
            return self._bubble(sender,
                                [(f'* {m.get("text", "")}', {'size': 13, 'color': ME_TEXT})],
                                sender == me, ts, animate=animate,
                                region=m.get('region'), mid=mid, conv=conv)
        elif t == 'system':
            return self._add_sys(m.get('text', ''))
        elif t == 'file_msg':
            return self._render_file_msg(m, animate=animate)
        return None

    def _render_file_msg(self, m, animate=True):
        ts = m.get('time', 0)
        kind = m.get('kind', 'file')
        icon = {'image': '🖼', 'video': '🎬', 'file': '📄'}.get(kind, '📄')
        label = {'image': '图片', 'video': '视频', 'file': '文件'}.get(kind, '文件')
        who = m.get('from', '')
        me = self.client.me if self.client else ''
        mine = bool(m.get('self')) or who == me
        fid = m.get('fid', '')
        segs = [(f'{icon}  {label}', {'size': 12, 'color': TEXT_DIM, 'bold': True}),
                (m.get('name', ''), {'size': 13}),
                (human_size(m.get('size', 0)), {'size': 11, 'color': TEXT_DIM})]
        bubble = self._bubble(who, segs, mine, ts, animate=animate,
                              region=m.get('region'), mid=m.get('mid'),
                              conv=m.get('conv') or self.conv)
        ph = ctk.CTkLabel(bubble, text='', anchor='w', text_color=TEXT_DIM,
                          font=ctk.CTkFont(family=FONT, size=11))
        ph.pack(anchor='w', padx=12, pady=(2, 8))
        self._file_rows[fid] = {'bubble': bubble, 'ph': ph}

        local = self._local_path_of(fid)
        if local:
            # 先把图片登记成「待加载」，只有滚到附近才真的解码 + 画出来。
            # 一屏其实只放得下几张图，一次性把几十张 280px 的缩略图都塞进
            # 滚动区，光布局就要上百毫秒一张（实测 12 张图 ≈ 1.1 秒），
            # 切会话就卡在这儿。滚动的回调里会补上附近的那些。
            self._img_pending[fid] = {'fid': fid, 'info': m, 'path': local,
                                      'rec': self._file_rows[fid],
                                      'row': self._file_rows[fid]['bubble'].master}
            ph.configure(text='🖼  图片（滚到这里自动加载）', text_color=TEXT_DIM)
            self._upgrade_visible_images()
        elif m.get('history'):
            ph.configure(text='点击加载', text_color=ACCENT, cursor='hand2')
            ph.bind('<Button-1>', lambda e, f=fid: self._request_file(f))
        else:
            ph.configure(text='⏳ 接收中…')

    def _view_span(self):
        """当前可视区在内容坐标里的范围（起, 止, 总高）。"""
        try:
            frame = self.messages
            cv = frame._parent_canvas
            total = max(int(frame.winfo_reqheight()), 1)
            f, _l = cv.yview()
            view_h = max(int(cv.winfo_height()), 1)
            return f * total, f * total + view_h, total
        except Exception:
            return 0.0, 1.0, 1

    def _upgrade_visible_images(self):
        """把「快滚到眼前」的图片真正画出来（其余仍是占位文字）。

        这样切会话只解码/布局看得见的那几张图，往上翻的时候再逐张补上。
        """
        pend = getattr(self, '_img_pending', None)
        if not pend:
            return
        if getattr(self, '_preloading', False):
            return              # 预加载画的是屏幕外的会话，量不到可视区，等显示出来再补图
        try:
            start, end, total = self._view_span()
            margin = max(1, int(IMG_VIEW_MARGIN)) * max(200, end - start)
            lo, hi = start - margin, end + margin
            for fid in list(pend.keys()):
                item = pend.get(fid)
                if item is None:
                    continue
                row = item.get('row')
                try:
                    if row is None or not self._alive(row):
                        pend.pop(fid, None)
                        continue
                    y, h = row.winfo_y(), row.winfo_height()
                except Exception:
                    pend.pop(fid, None)
                    continue
                if y + h >= lo and y <= hi:
                    pend.pop(fid, None)
                    rec = item.get('rec')
                    if rec is not None:
                        self._show_file_content(fid, item['info'], item['path'])
        except Exception:
            pass

    def _local_path_of(self, fid):
        c = self.client
        if not c:
            return None
        p = c.received.get(fid) or c._local_files.get(fid)
        return p if p and os.path.isfile(p) else None

    def _request_file(self, fid):
        c = self.client
        if c is None:
            return
        rec = self._file_rows.get(fid)
        if rec:
            rec['ph'].configure(text='⏳ 正在加载…', text_color=TEXT_DIM)
        c.request_file(fid)

    def _fill_file(self, d):
        fid = str(d.get('fid') or '')
        info = d.get('info') or {}
        path = d.get('path') or ''
        conv = info.get('conv', CONV_ROOM)
        if fid in self._group_file_wait:
            self._group_file_wait.discard(fid)
            self._toast(f'群文件已下载：{os.path.basename(path)}')
            self._add_sys(f'📁 群文件已保存到 {path}')
        if conv == self.conv and fid in self._file_rows:
            self._show_file_content(fid, info, path)

    def _thumb_of(self, fid, path, size=280):
        """图片缩略图（按 fid 缓存）。

        以前每次重绘消息区都要重新 open + thumbnail + 造 CTkImage，一张图
        十几毫秒，切一次会话几十张图就很卡。现在按 fid 缓存住，重绘只是复用。
        """
        key = (str(fid), int(size))
        cache = getattr(self, '_thumb_cache', None)
        if cache is None:
            cache = self._thumb_cache = {}
        if key in cache:                  # 注意：失败也要缓存（存成 False），
            return cache[key] or None     # 否则每次重绘都会再解码一遍坏图
        cimg = None
        try:
            img = Image.open(path)
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA')
            img.thumbnail((size, size))
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
        except Exception:
            cimg = None
        cache[key] = cimg if cimg is not None else False
        if len(cache) > 120:                  # 别无限涨
            for k in list(cache.keys())[:40]:
                cache.pop(k, None)
        return cimg

    def _show_file_content(self, fid, info, path):
        rec = self._file_rows.get(fid)
        if not rec or rec.get('_filled'):
            return
        rec['_filled'] = True
        bubble = rec['bubble']
        try:
            rec['ph'].destroy()
        except Exception:
            pass
        name = info.get('name') or os.path.basename(path)
        kind = info.get('kind') or 'file'
        if kind == 'image' and path and os.path.isfile(path) \
                and os.path.getsize(path) <= FILE_INLINE_MAX:
            cimg = self._thumb_of(fid, path)
            if cimg is not None:
                try:
                    self._img_refs.append(cimg)
                    lbl = ctk.CTkLabel(bubble, image=cimg, text='', cursor='hand2',
                                       fg_color='transparent', text_color=TEXT)
                    lbl.pack(padx=6, pady=(4, 4))
                    lbl.bind('<Button-1>',
                             lambda e, p=path, n=name: self._open_preview(p, n))
                    link = ctk.CTkLabel(bubble, text='打开原图', anchor='w',
                                        text_color=ACCENT, cursor='hand2',
                                        font=ctk.CTkFont(family=FONT, size=11,
                                                         underline=True))
                    link.pack(anchor='w', padx=12, pady=(0, 6))
                    link.bind('<Button-1>', lambda e, p=path: self._open_path(p))
                    self._schedule_scroll()
                    return
                except Exception:
                    pass
        icon = {'image': '🖼', 'video': '🎬'}.get(kind, '📄')
        link = ctk.CTkLabel(bubble, text=f'{icon}  点击打开 {name}', anchor='w',
                            text_color=ACCENT, cursor='hand2',
                            font=ctk.CTkFont(family=FONT, size=13, underline=True))
        link.pack(anchor='w', padx=12, pady=(2, 8))
        link.bind('<Button-1>', lambda e, p=path: self._open_path(p))
        self._schedule_scroll()

    # ================= 图片放大预览 =================
    def _open_preview(self, path, name=''):
        if not path or not os.path.exists(path):
            self._add_sys('文件不存在或已被清理')
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            self._open_path(path)
            return
        win = ctk.CTkToplevel(self)
        win.title((name or '图片预览') + APP_SUFFIX)
        win.configure(fg_color=BG_APP)
        win.transient(self)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        max_w, max_h = int(sw * 0.85), int(sh * 0.82)
        base_ratio = min(max_w / img.width, max_h / img.height, 1.0)
        state = {'zoom': 1.0}
        label = ctk.CTkLabel(win, text='', fg_color='transparent', text_color=TEXT)
        label.pack(expand=True, fill='both', padx=12, pady=(12, 4))

        def render():
            ratio = base_ratio * state['zoom']
            size = (max(20, int(img.width * ratio)), max(20, int(img.height * ratio)))
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            label.configure(image=cimg)
            win._img = cimg
            win.geometry(f'{max(360, size[0] + 40)}x{max(240, size[1] + 110)}')

        def zoom(factor):
            state['zoom'] = min(6.0, max(0.15, state['zoom'] * factor))
            render()

        bar = ctk.CTkFrame(win, fg_color='transparent')
        bar.pack(fill='x', pady=(0, 12))
        ctk.CTkLabel(bar, text=f'{img.width}×{img.height}', text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(side='left', padx=16)
        ctk.CTkButton(bar, text='关闭', width=70, corner_radius=10, fg_color=BG_PANEL,
                      hover_color=BG_HOVER, text_color=TEXT,
                      font=ctk.CTkFont(family=FONT, size=12),
                      command=win.destroy).pack(side='right', padx=(6, 16))
        ctk.CTkButton(bar, text='系统打开', width=90, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=12),
                      command=lambda: self._open_path(path)).pack(side='right', padx=6)
        ctk.CTkButton(bar, text='＋', width=40, corner_radius=10, fg_color=BG_PANEL,
                      hover_color=BG_HOVER, text_color=TEXT, font=ctk.CTkFont(size=14),
                      command=lambda: zoom(1.25)).pack(side='right', padx=2)
        ctk.CTkButton(bar, text='－', width=40, corner_radius=10, fg_color=BG_PANEL,
                      hover_color=BG_HOVER, text_color=TEXT, font=ctk.CTkFont(size=14),
                      command=lambda: zoom(0.8)).pack(side='right', padx=2)
        win.bind('<MouseWheel>', lambda e: zoom(1.1 if e.delta > 0 else 0.9))
        win.bind('<Escape>', lambda e: win.destroy())
        render()
        win.after(50, lambda: (win.lift(), win.focus_force()))

    # ================= 加好友 / 建群 弹窗 =================
    def _dialog_invite_friend(self, gid):
        """选一个好友拉进群（要管理员 + 对方本人双方同意）。"""
        c = self.client
        if c is None:
            return
        info = (getattr(c, 'group_infos', None) or {}).get(str(gid)) or {}
        already = {(m.get('nick') or '').strip().lower()
                   for m in (info.get('members') or [])}
        pending = {(i.get('nick') or '').strip().lower()
                   for i in (info.get('invites') or [])}
        cand = [f for f in (c.friends or [])
                if f.strip().lower() not in already and f.strip().lower() not in pending]
        win = ctk.CTkToplevel(self)
        win.title('邀请好友入群' + APP_SUFFIX)
        win.configure(fg_color=BG_APP)
        win.geometry('420x420')
        win.transient(self)
        try:
            win.after(60, win.grab_set)
        except Exception:
            pass
        ctk.CTkLabel(win, text='➕  选择要拉进群的好友', anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=15, weight='bold')).pack(
            anchor='w', padx=18, pady=(14, 2))
        ctk.CTkLabel(win, text='拉人需要群主/管理员同意 + 对方本人同意，'
                               '两边都点头才会进群。',
                     anchor='w', justify='left', wraplength=380, text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=11)).pack(
            anchor='w', padx=18, pady=(0, 8))
        box = ctk.CTkScrollableFrame(win, fg_color=BG_PANEL, corner_radius=12,
                                     scrollbar_button_color=SCROLL_BTN)
        box.pack(fill='both', expand=True, padx=14, pady=(0, 12))
        if not cand:
            ctk.CTkLabel(box, text='没有可以拉的好友了（可能都已在群里或已在等确认）',
                         wraplength=340, justify='left', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(
                anchor='w', padx=12, pady=12)
        for f in cand:
            row = ctk.CTkFrame(box, fg_color='transparent')
            row.pack(fill='x', padx=6, pady=2)
            ctk.CTkLabel(row, text=f, anchor='w', text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(side='left', padx=8)
            ctk.CTkButton(row, text='拉进群', width=64, height=24, corner_radius=12,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=lambda n=f, w=win: (c.group_invite(gid, n), w.destroy())
                          ).pack(side='right', padx=6)

    def _check_invites(self, invites):
        """别人拉我进群：弹一次窗问同意不同意（管理员那边还要单独同意）。"""
        seen = getattr(self, '_invite_seen', None)
        if seen is None:
            seen = self._invite_seen = set()
        for inv in invites or []:
            key = (str(inv.get('gid')), (inv.get('nick') or '').lower())
            if key in seen:
                continue
            seen.add(key)
            self._dialog_group_invite(inv)

    def _dialog_group_invite(self, inv):
        gid = str(inv.get('gid') or '')
        me = inv.get('nick') or ''
        who = inv.get('by') or ''
        gname = inv.get('group') or '群聊'
        win = ctk.CTkToplevel(self)
        win.title('入群邀请' + APP_SUFFIX)
        win.configure(fg_color=BG_APP)
        win.geometry('460x250')
        win.transient(self)
        try:
            win.after(60, win.grab_set)
        except Exception:
            pass
        ctk.CTkLabel(win, text='👥  入群邀请', anchor='w', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=16, weight='bold')).pack(
            anchor='w', padx=20, pady=(16, 4))
        ctk.CTkLabel(win, text=f'「{who}」邀请你加入群「{gname}」。\n'
                               f'群主或管理员同意后即可进群。',
                     anchor='w', justify='left', text_color=TEXT_SOFT,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(
            anchor='w', padx=20, pady=(0, 10))
        row = ctk.CTkFrame(win, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=(4, 0))
        ctk.CTkButton(row, text='✓  同意', width=110, height=32, corner_radius=16,
                      fg_color=OK_GREEN, hover_color=OK_GREEN_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=12, weight='bold'),
                      command=lambda: (self.client.group_invite_me(gid, me, True),
                                       win.destroy())).pack(side='left')
        ctk.CTkButton(row, text='✕  拒绝', width=110, height=32, corner_radius=16,
                      fg_color=NO_RED, hover_color=NO_RED_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=12),
                      command=lambda: (self.client.group_invite_me(gid, me, False),
                                       win.destroy())).pack(side='left', padx=(10, 0))

    # ---------- 好友：删除 / 拉黑 ----------
    def _friend_menu(self, event, nick):
        """好友列表右键：删除好友 / 拉黑（或移出黑名单）。"""
        try:
            c = self.client
            if c is None or not nick:
                return
            blocked = nick.strip().lower() in {
                str(x).strip().lower() for x in (getattr(c, 'blocks', None) or [])}
            menu = tk.Menu(self, tearoff=0, bg=BG_PANEL, fg=TEXT,
                           activebackground=BG_HOVER, activeforeground=TEXT, bd=0,
                           font=(FONT, 10))
            menu.add_command(label='发起私聊',
                             command=lambda n=nick: self._select_conv(conv_user(n)))
            menu.add_separator()
            if blocked:
                menu.add_command(
                    label='移出黑名单',
                    command=lambda n=nick: self.client.block_friend(n, False))
            else:
                menu.add_command(
                    label='加入黑名单',
                    command=lambda n=nick: self._confirm_block(n))
            menu.add_command(label='删除好友',
                             command=lambda n=nick: self._confirm_del_friend(n))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        except Exception as e:
            write_log(log_path(), f'!! 好友菜单出错：{e!r}\n{traceback.format_exc()}')

    def _confirm_del_friend(self, nick):
        """删除好友：先问一句，确认后告诉服务端。

        以前这里会因为 messagebox 没 import 而抛 NameError —— Tk 把回调异常
        吞掉，用户看到的就是「点了没反应」。现在所有回调异常都会走
        report_callback_exception，而且这里自己再兜一层。
        """
        try:
            ok = messagebox.askyesno(
                '删除好友' + APP_SUFFIX,
                f'确定删除好友「{nick}」吗？\n\n'
                f'删除后你们就不能再互发消息了（对话框会被锁住）。\n'
                f'对方以后仍然可以再申请加你为好友。')
        except Exception as e:
            write_log(log_path(), f'!! 弹确认框失败：{e!r}\n{traceback.format_exc()}')
            self._toast('弹不出确认框，已按「确定」处理', WARN)
            ok = True
        if not ok:
            return
        try:
            self.client.del_friend(nick)
            self._toast(f'已请求删除好友「{nick}」')
        except Exception as e:
            write_log(log_path(), f'!! 删除好友失败：{e!r}\n{traceback.format_exc()}')
            self._toast(f'删除好友失败：{e}', WARN)

    def _confirm_block(self, nick):
        try:
            ok = messagebox.askyesno(
                '加入黑名单' + APP_SUFFIX,
                f'确定把「{nick}」加入黑名单吗？\n\n'
                f'对方将无法再给你发消息、也无法再发好友申请。')
        except Exception as e:
            write_log(log_path(), f'!! 弹确认框失败：{e!r}\n{traceback.format_exc()}')
            self._toast('弹不出确认框，已按「确定」处理', WARN)
            ok = True
        if not ok:
            return
        try:
            self.client.block_friend(nick, True)
            self._toast(f'已把「{nick}」加入黑名单')
        except Exception as e:
            write_log(log_path(), f'!! 拉黑失败：{e!r}\n{traceback.format_exc()}')
            self._toast(f'拉黑失败：{e}', WARN)

    def _im_blocked(self, conv):
        """我和这个好友之间是不是已经不能说话了（删了或者拉黑了）。

        注意：没收到过社交数据（social_ready）时不判断「不是好友」——
        刚登录还没同步好友列表就锁住输入框是误伤。
        """
        c = self.client
        if c is None or conv_kind(conv) != 'friend':
            return ''
        nick = str(conv)[2:]
        me = c.me or ''
        if nick.strip().lower() == me.strip().lower():
            return ''
        if not getattr(c, 'social_ready', False):
            return ''
        low = nick.strip().lower()
        blocks = [str(x).strip().lower() for x in (getattr(c, 'blocks', None) or [])]
        friends = [str(x).strip().lower() for x in (c.friends or [])]
        if low in blocks:
            return f'你已把「{nick}」拉黑，解除后才能发消息'
        if low not in friends:
            return '你们已经不是好友了，无法发送消息'
        return ''

    def _dialog_add_friend(self, nick=None):
        win = ctk.CTkToplevel(self)
        win.title('添加好友' + APP_SUFFIX)
        win.configure(fg_color=BG_PANEL)
        win.geometry('470x500')
        win.transient(self)
        ctk.CTkLabel(win, text='添加好友', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=16, weight='bold')).pack(pady=(16, 2))
        ctk.CTkLabel(win, text='输入对方昵称搜索，或直接发送申请', text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=12)).pack()
        row = ctk.CTkFrame(win, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=(12, 6))
        entry = ctk.CTkEntry(row, height=38, corner_radius=10, fg_color=FIELD_BG,
                             border_color=FIELD_BORDER, border_width=1, text_color=TEXT,
                             placeholder_text='对方昵称', font=ctk.CTkFont(family=FONT, size=13))
        entry.pack(side='left', fill='x', expand=True)
        msg_entry = ctk.CTkEntry(win, height=38, corner_radius=10, fg_color=FIELD_BG,
                                 border_color=FIELD_BORDER, border_width=1, text_color=TEXT,
                                 placeholder_text='申请信息（选填）：一句话介绍自己',
                                 font=ctk.CTkFont(family=FONT, size=13))
        msg_entry.pack(fill='x', padx=20, pady=(0, 6))
        err = ctk.CTkLabel(win, text='', anchor='w', text_color=WARN, height=18,
                           font=ctk.CTkFont(family=FONT, size=12))
        err.pack(fill='x', padx=20)
        res = ctk.CTkScrollableFrame(win, fg_color=BG_APP, corner_radius=10,
                                     scrollbar_fg_color='transparent',
                                     scrollbar_button_color=SCROLL_BTN,
                                     scrollbar_button_hover_color=SCROLL_HOVER)
        res.pack(fill='both', expand=True, padx=20, pady=(6, 16))
        self._search_box = res
        self._search_win = win
        self._add_friend_win = win
        if nick:
            entry.insert(0, nick)

        def complain(text, widget=None):
            try:
                err.configure(text='⚠  ' + text)
            except Exception:
                pass
            self._flash_warn(widget or entry)

        def do_search():
            for w in res.winfo_children():
                w.destroy()
            try:
                err.configure(text='')
            except Exception:
                pass
            q = entry.get().strip()
            if not q:
                complain('请先填写对方昵称，再点搜索')
                return
            self.client.search_users(q)

        def do_add(target=None):
            n = (target or entry.get()).strip()
            if not n:
                complain('请先填写对方昵称')
                return
            if self.client is None or not self.connected:
                complain('还没连上服务器，无法发送申请')
                return
            self.client.add_friend(n, msg_entry.get().strip())
            try:
                win.destroy()
            except Exception:
                pass

        ctk.CTkButton(row, text='搜索', width=64, height=38, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=13), command=do_search).pack(
            side='left', padx=(8, 0))
        ctk.CTkButton(win, text='直接发送好友申请', height=38, corner_radius=10,
                      fg_color='transparent', border_width=1, border_color=FIELD_BORDER,
                      hover_color=BG_HOVER, text_color=TEXT,
                      font=ctk.CTkFont(family=FONT, size=13),
                      command=do_add).pack(fill='x', padx=20, pady=(0, 16))
        self._add_friend_send = lambda n: do_add(n)
        entry.bind('<Return>', lambda e: do_search())
        msg_entry.bind('<Return>', lambda e: do_add())
        win.after(60, lambda: (win.lift(), entry.focus_force()))

    def _show_search_results(self, users):
        box = getattr(self, '_search_box', None)
        if box is None or not box.winfo_exists():
            return
        for w in box.winfo_children():
            w.destroy()
        if not users:
            ctk.CTkLabel(box, text='没有找到匹配的用户', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(pady=10)
            return
        for u in users:
            r = ctk.CTkFrame(box, fg_color='transparent')
            r.pack(fill='x', pady=2)
            av = self._avatar(u, 28)
            if av is not None:
                ctk.CTkLabel(r, image=av, text='', fg_color='transparent',
                             text_color=TEXT).pack(side='left', padx=(4, 6))
            ctk.CTkLabel(r, text=u, anchor='w', text_color=TEXT,
                         font=ctk.CTkFont(family=FONT, size=13)).pack(side='left')
            ctk.CTkButton(r, text='加好友', width=64, height=26, corner_radius=8,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                          font=ctk.CTkFont(family=FONT, size=11),
                          command=lambda n=u: self._add_friend_from_search(n)).pack(
                side='right', padx=4)

    def _add_friend_from_search(self, nick):
        send = getattr(self, '_add_friend_send', None)
        if callable(send):
            send(nick)
        else:
            self.client.add_friend(nick)

    def _dialog_create_group(self):
        friends = list(self.client.friends) if self.client else []
        win = ctk.CTkToplevel(self)
        win.title('创建群聊' + APP_SUFFIX)
        win.configure(fg_color=BG_PANEL)
        win.geometry('440x500')
        win.transient(self)
        ctk.CTkLabel(win, text='创建群聊', text_color=TEXT,
                     font=ctk.CTkFont(family=FONT, size=16, weight='bold')).pack(pady=(16, 2))
        ctk.CTkLabel(win, text='填写群名称，并勾选要拉进来的好友', text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=12)).pack()
        name_entry = ctk.CTkEntry(win, height=38, corner_radius=10, fg_color=FIELD_BG,
                                  border_color=FIELD_BORDER, border_width=1, text_color=TEXT,
                                  placeholder_text='群名称', font=ctk.CTkFont(family=FONT, size=13))
        name_entry.pack(fill='x', padx=20, pady=(12, 4))
        err = ctk.CTkLabel(win, text='', anchor='w', text_color=WARN, height=18,
                           font=ctk.CTkFont(family=FONT, size=12))
        err.pack(fill='x', padx=20, pady=(0, 4))
        box = ctk.CTkScrollableFrame(win, fg_color=BG_APP, corner_radius=10,
                                     scrollbar_fg_color='transparent',
                                     scrollbar_button_color=SCROLL_BTN,
                                     scrollbar_button_hover_color=SCROLL_HOVER)
        box.pack(fill='both', expand=True, padx=20, pady=(0, 10))
        vars_ = {}
        if not friends:
            ctk.CTkLabel(box, text='还没有好友，先添加好友吧', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(pady=10)
        for f in friends:
            v = tk.BooleanVar(value=False)
            vars_[f] = v
            ctk.CTkCheckBox(box, text=f, variable=v, text_color=TEXT,
                            font=ctk.CTkFont(family=FONT, size=13),
                            fg_color=ACCENT, hover_color=ACCENT_DIM,
                            border_color=FIELD_BORDER, checkmark_color=ON_ACCENT).pack(
                anchor='w', padx=8, pady=4)

        def create():
            name = name_entry.get().strip()
            if not name:      # 以前是静默 return，用户以为「点了没反应」
                try:
                    err.configure(text='⚠  请先填写群名称，再点创建')
                except Exception:
                    pass
                self._flash_warn(name_entry)
                name_entry.focus_set()
                return
            if self.client is None or not self.connected:
                try:
                    err.configure(text='⚠  还没连上服务器，无法创建群聊')
                except Exception:
                    pass
                return
            members = [f for f, v in vars_.items() if v.get()]
            self.client.create_group(name, members)
            try:
                win.destroy()
            except Exception:
                pass
        ctk.CTkButton(win, text='创建', height=40, corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                      font=ctk.CTkFont(family=FONT, size=14),
                      command=create).pack(fill='x', padx=20, pady=(0, 16))
        name_entry.bind('<Return>', lambda e: create())
        win.after(60, lambda: (win.lift(), name_entry.focus_force()))

    def _flash_warn(self, widget, attr='border_color', steps=4):
        """把输入框边框闪成警告色 —— 空输入时给一点视觉反馈。"""
        def step(i):
            try:
                widget.configure(**{attr: WARN if i % 2 else FIELD_BORDER})
            except Exception:
                return
            if i < steps:
                self.after(110, lambda: step(i + 1))
        step(1)

    # ================= 表情 / 提及面板 =================
    def _panel_visible(self):
        return bool(self.panel.winfo_manager())

    def _toggle_emoji(self):
        if self._panel_visible():
            self.panel.pack_forget()
            return
        # 面板只建一次，之后只是 pack/forget —— 以前每次点开都要新建近百个
        # 按钮（每个按钮内部还有 canvas/文字标签），点一下要几百毫秒，很卡。
        if getattr(self, '_emoji_grid', None) is None:
            self._build_emoji_panel()
        self.panel.pack(fill='x', padx=12, pady=(6, 0))

    def _build_emoji_panel(self):
        for w in self.panel.winfo_children():
            w.destroy()
        grid = ctk.CTkFrame(self.panel, fg_color='transparent')
        grid.pack(fill='x', padx=10, pady=8)
        self._emoji_grid = grid
        # 就用文字形式的表情（用户要求：不要图片）。面板依然只建一次，
        # 之后只是 pack/forget —— 以前每次点开都要重建近百个按钮，
        # 点一下要几百毫秒，那才是「打开表情很卡」的原因。
        for i, e in enumerate(EMOJIS):
            ctk.CTkButton(grid, text=e, width=34, height=32, corner_radius=8,
                          fg_color='transparent', hover_color=BG_HOVER,
                          text_color=TEXT,
                          font=ctk.CTkFont(family=EMOJI_FONT, size=16),
                          command=lambda ch=e: self._insert(ch)).grid(
                row=i // EMOJI_COLS, column=i % EMOJI_COLS, padx=1, pady=1)

    def _emoji_sheet(self, cell=34, cols=None):
        return None                          # 表情用文字按钮画，不再整版作图

    def _toggle_mention(self):
        if self._panel_visible():
            self.panel.pack_forget()
            return
        # @ 面板依赖「当前在线的人」，每次都要重建；但顺手清掉表情面板的缓存标记，
        # 免得下次点表情时把 @ 面板当成表情面板复用。
        self._emoji_grid = None
        for w in self.panel.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.panel, text='选择要 @ 的人', anchor='w', text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill='x', padx=12, pady=(8, 4))
        grid = ctk.CTkFrame(self.panel, fg_color='transparent')
        grid.pack(fill='x', padx=10, pady=(0, 8))
        c = self.client
        if c is None:
            names = []
        else:
            try:
                rows, _g = self._member_names()
                names = [n for n, _o in rows if n and n != c.me]
            except Exception:
                names = [u for u in (c.online or []) if u != c.me]
        if not names:
            ctk.CTkLabel(grid, text='（暂无其他在线用户）', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(anchor='w', padx=4)
        for i, n in enumerate(names):
            ctk.CTkButton(grid, text='@' + n, width=110, height=30, corner_radius=15,
                          fg_color=BG_HEADER, hover_color=BG_HOVER, text_color=TEXT,
                          font=ctk.CTkFont(family=FONT, size=12),
                          command=lambda x=n: self._insert_mention(x)).grid(
                row=i // 6, column=i % 6, padx=3, pady=3)
        self.panel.pack(fill='x', padx=12, pady=(6, 0))

    def _insert(self, s):
        try:
            self.input.insert('insert', s)
        except Exception:
            self.input.insert('end', s)
        self.input.focus_set()

    # ================= 中国象棋 =================
    def _chess_palette(self):
        """给棋盘窗口的配色（跟当前界面主题一致）。"""
        s = 1.0
        try:
            from customtkinter import ScalingTracker
            s = float(ScalingTracker.get_widget_scaling(self))
        except Exception:
            pass
        try:
            max_h = self.winfo_screenheight() * 0.86
            max_w = self.winfo_screenwidth() * 0.92
            s = min(s, (max_h - 130) / chess_ui.BOARD_H, (max_w - 320) / chess_ui.BOARD_W)
        except Exception:
            pass
        s = max(0.52, s)
        return {
            'font': FONT, 'scale': s,
            'app_title': APP_TITLE, 'title_suffix': APP_SUFFIX,
            'bg_app': BG_APP, 'bg_panel': BG_PANEL, 'bg_header': BG_HEADER,
            'bg_hover': BG_HOVER, 'bg_active': BG_ACTIVE,
            'field_bg': FIELD_BG, 'field_border': FIELD_BORDER,
            'scroll_btn': SCROLL_BTN, 'scroll_hover': SCROLL_HOVER,
            'text': TEXT, 'text_dim': TEXT_DIM, 'text_soft': TEXT_SOFT,
            'region': REGION, 'warn': WARN,
            'accent': ACCENT, 'accent_dim': ACCENT_DIM, 'on_accent': ON_ACCENT,
            'danger': DANGER, 'danger_dim': DANGER_DIM,
            'ok': OK_GREEN, 'ok_dim': OK_GREEN_DIM,
        }

    def _chess_hooks(self):
        def guard(fn):
            def call(*a):
                if self.client is not None:
                    try:
                        fn(*a)
                    except Exception:
                        pass
            return call

        def answer(gid, kind, accept):
            if kind == 'draw':
                self.client.chess_answer_draw(gid, accept)
            else:
                self.client.chess_answer_undo(gid, accept)

        return {
            'on_move': guard(lambda gid, fr, fc, tr, tc:
                             self.client.chess_move(gid, fr, fc, tr, tc)),
            'on_resign': guard(lambda gid: self.client.chess_resign(gid)),
            'on_draw': guard(lambda gid: self.client.chess_offer_draw(gid)),
            'on_undo': guard(lambda gid: self.client.chess_request_undo(gid)),
            'on_answer': guard(answer),
            'on_close': self._chess_window_closed,
        }

    def _toggle_chess_panel(self):
        """在输入框上方弹出「选对手」面板；有对局时先给「回到对局」。"""
        if self._panel_visible():
            self.panel.pack_forget()
            return
        for w in self.panel.winfo_children():
            w.destroy()
        c = self.client
        gid = getattr(c, 'my_gid', None) if c else None
        game = (getattr(c, 'games', None) or {}).get(gid) if gid else None
        if game and (game.get('status') or 'playing') == 'playing':
            ctk.CTkButton(self.panel, text='⚔  回到当前对局', height=36, corner_radius=10,
                          fg_color=ACCENT, hover_color=ACCENT_DIM, text_color=ON_ACCENT,
                          font=ctk.CTkFont(family=FONT, size=13, weight='bold'),
                          command=lambda g=game: self._open_chess_window(g)).pack(
                fill='x', padx=12, pady=(8, 4))
        ctk.CTkLabel(self.panel, text='选择对手开始象棋对局', anchor='w', text_color=TEXT_DIM,
                     font=ctk.CTkFont(family=FONT, size=12)).pack(fill='x', padx=12,
                                                                  pady=(6, 4))
        grid = ctk.CTkFrame(self.panel, fg_color='transparent')
        grid.pack(fill='x', padx=10, pady=(0, 8))
        names = [u for u in (c.online if c else []) if u != (c.me if c else None)]
        if not names:
            ctk.CTkLabel(grid, text='（暂无其他在线用户）', text_color=TEXT_DIM,
                         font=ctk.CTkFont(family=FONT, size=12)).pack(anchor='w', padx=4)
        for i, n in enumerate(names):
            ctk.CTkButton(grid, text='♟ ' + n, width=118, height=30, corner_radius=15,
                          fg_color=BG_HEADER, hover_color=BG_HOVER, text_color=TEXT,
                          font=ctk.CTkFont(family=FONT, size=12),
                          command=lambda x=n: self._challenge_chess(x)).grid(
                row=i // 5, column=i % 5, padx=3, pady=3)
        self.panel.pack(fill='x', padx=12, pady=(6, 0))

    def _challenge_chess(self, nick):
        self.panel.pack_forget()
        if self.client is None:
            return
        self.client.chess_challenge(nick)
        self._toast(f'已向 {nick} 发起象棋约战，等待对方选择红黑…')

    def _toast(self, text, color=None):
        """底部浮出一条提示，几秒后自动消失。"""
        try:
            if self._toast_label is not None:
                self._toast_label.destroy()
        except Exception:
            pass
        # 给每条提示编号：旧的提示到点时不能把新提示关掉
        self._toast_seq = getattr(self, '_toast_seq', 0) + 1
        seq = self._toast_seq
        try:
            self._toast_label = ctk.CTkLabel(
                self.main, text=text, fg_color=BG_HEADER, corner_radius=14,
                text_color=color or TEXT, font=ctk.CTkFont(family=FONT, size=13))
            self._toast_label.place(relx=0.5, rely=0.9, anchor='center')
            self.after(4200, lambda s=seq: self._toast_hide(s))
        except Exception:
            self._toast_label = None

    def _toast_hide(self, seq=None):
        if seq is not None and seq != getattr(self, '_toast_seq', 0):
            return          # 这是更早那条提示安排的定时器，别误伤新提示
        try:
            if self._toast_label is not None:
                self._toast_label.destroy()
        except Exception:
            pass
        self._toast_label = None

    def _open_chess_window(self, game):
        gid = game.get('gid')
        if not gid:
            return
        game = dict(game)
        me = (self.client.me if self.client else '') or ''
        game['me'] = me
        if not game.get('my_color') and self.client is not None:
            game['my_color'] = self.client.games.get(gid, {}).get('my_color')
        if not game.get('my_color') and me:
            if me == game.get('red'):
                game['my_color'] = 'r'
            elif me == game.get('black'):
                game['my_color'] = 'b'
        win = self.chess_windows.get(gid)
        if win is None or not win.winfo_exists():
            win = chess_ui.ChessWindow(self, game, self._chess_palette(), self._chess_hooks())
            self.chess_windows[gid] = win
        else:
            win.update_game(game)
        try:
            win.lift()
        except Exception:
            pass

    def _chess_window_closed(self, gid):
        self.chess_windows.pop(gid, None)
        if self.client is not None:
            try:
                self.client.chess_leave(gid)
            except Exception:
                pass

    def _show_challenge(self, obj):
        try:
            if self._chal_win is not None and self._chal_win.winfo_exists():
                self._chal_win.destroy()
        except Exception:
            pass
        cid = obj.get('cid')

        def pick(color):
            if self.client is not None and cid:
                self.client.chess_accept(cid, color)

        def reject():
            if self.client is not None and cid:
                self.client.chess_reject(cid)

        self._chal_win = chess_ui.ChallengeDialog(self, obj, self._chess_palette(),
                                                  pick, reject)
        self._sound('challenge')

    def _on_chess_event(self, obj):
        act = obj.get('act')
        game = obj.get('game') or {}
        if act == 'challenged':
            self._show_challenge(obj)
        elif act == 'challenge_sent':
            if not obj.get('again'):
                self._toast(f'已向 {obj.get("to", "")} 发起象棋约战…')
        elif act == 'challenge_rejected':
            self._toast(f'{obj.get("by", "")} 拒绝了你的象棋约战', WARN)
        elif act == 'challenge_cancelled':
            self._toast('对方取消了象棋约战', WARN)
        elif act == 'challenge_expired':
            self._toast('约战长时间没有回应，已失效', WARN)
        elif act == 'error':
            self._toast(obj.get('text') or '象棋操作失败', WARN)
            if game:
                self._open_chess_window(game)
        elif act == 'notice':
            text = obj.get('text') or ''
            self._toast(text)
            win = self.chess_windows.get(obj.get('gid'))
            if win is not None and win.winfo_exists():
                try:
                    win.tip_label.configure(text=text)
                except Exception:
                    pass
        elif act == 'check':
            self._toast('将军！', WARN)
        elif act in ('start', 'update', 'end'):
            gid = game.get('gid')
            now_no = int(game.get('move_no') or 0)
            prev = self._chess_seen_moves.get(gid)
            # 走子音效：红黑双方都响（服务端对双方都推 update）
            if act == 'update' and prev is not None:
                if now_no > prev:
                    self._sound('chess_check' if game.get('check') else 'chess_move')
                elif now_no < prev:
                    self._sound('chess_undo')
            elif act == 'end':
                self._sound('chess_end')
            if gid is not None:
                self._chess_seen_moves[gid] = now_no
            self._open_chess_window(game)
            if act == 'start':
                self._toast('棋局开始，点击棋子走棋')
            elif act == 'end':
                res = {'red_win': '红方胜', 'black_win': '黑方胜',
                       'draw': '和棋'}.get(game.get('status'), '对局结束')
                self._toast(f'{res}（{chess_ui.reason_cn(game.get("reason"))}）')
        elif act == 'closed':
            win = self.chess_windows.pop(obj.get('gid'), None)
            if win is not None:
                try:
                    win.force_close()
                except Exception:
                    pass

    def _close_chess_windows(self):
        for win in list(self.chess_windows.values()):
            try:
                win.force_close()
            except Exception:
                pass
        self.chess_windows.clear()
        try:
            if self._chal_win is not None and self._chal_win.winfo_exists():
                self._chal_win.destroy()
        except Exception:
            pass
        self._chal_win = None

    def _insert_mention(self, nick):
        self._insert('@' + nick + ' ')
        self.panel.pack_forget()

    # ================= 输入与发送 =================
    def _input_text(self):
        try:
            return self.input.get('1.0', 'end-1c')
        except Exception:
            return ''

    def _grow_input(self, event=None):
        if self._grow_pending:
            return
        self._grow_pending = True
        self.after_idle(self._do_grow)

    def _do_grow(self):
        self._grow_pending = False
        try:
            n = self.input._textbox.count('1.0', 'end-1c', 'displaylines')
            dl = (n[0] if isinstance(n, (tuple, list)) else n) or 1
        except Exception:
            dl = 1
        try:
            logical = int(str(self.input.index('end-1c')).split('.')[0])
        except Exception:
            logical = 1
        lines = max(int(dl), logical, 1)
        h = min(max(42, 20 + 19 * lines), 168)
        if h != self._input_h:
            self._input_h = h
            try:
                self.input.configure(height=h)
            except Exception:
                pass

    def _on_return(self, event):
        if event.state & 0x0001:
            return None
        self.send()
        return 'break'

    def send(self):
        if not self._has_conv():
            # 只弹提示，**不往消息区写系统行**：空状态那块是共用的，写进去会把
            # 居中的图标/文字顶偏，点几次就堆出一排「请先选择会话」。
            self._toast('请先在左侧选择一个聊天会话', WARN)
            self._render_empty_state()
            return
        c = self.client
        if c is not None and not self.connected and getattr(c, 'connected', False):
            # 界面以为掉线、底层信道其实是通的（偶发状态不同步）：就地纠正再发，
            # 否则会出现「所有会话都发不出消息」。
            self.connected = True
            self._reconnecting = False
            self._rec_attempt = 0
            try:
                self._show_offline(False)
                self._sync_status()
            except Exception:
                pass
            write_diag('发送前发现「界面显示掉线但信道在线」：已自动恢复连接状态')
        if c is None or not self.connected:
            # 以前这里是直接 return —— 断线时按回车什么都不发生，看起来就像「消息发不出去也不显示」
            self._toast('未连接服务器，消息没有发出去', WARN)
            self._add_sys('⚠ 未连接服务器，这条消息没有发出去。'
                          '请点右上角「退出登录」重新登录')
            self._trace('发送被拒：未连接服务器')
            return
        text = self._input_text().strip()
        if not text:
            return
        lock_text, hint = self._lock_state()
        if lock_text:
            self._toast(hint or lock_text, WARN)
            self._apply_mute_state()
            return
        try:
            self.input.delete('1.0', 'end')
            self.input.configure(height=42)
            self._input_h = 42
        except Exception:
            pass
        if text.startswith('/'):
            self._command(text)
            return
        if len(text) > MAX_TEXT:
            self._add_sys(f'消息过长（最多 {MAX_TEXT} 字符）')
            return
        c.send_text(self.conv, text)
        self._msgs_append({'t': 'chat', 'conv': self.conv, 'from': c.me, 'text': text,
                           'time': now_ts(), 'self': True,
                           'kind': conv_kind(self.conv)}, optimistic=True)
        self._pulse(self.send_btn)

    def _heal_empty_view(self):
        """界面是空的、但会话里其实有消息 —— 最多自愈两次，而且必须间隔够久。

        这条自愈以前太激进：只要界面上 ≤1 行就重画，而重画期间界面本来就可能是空的，
        于是「自愈 → 重画 → 又被判成空的 → 再自愈」死循环，每秒把消息区整个重建十几遍
        —— 用户看到的就是「进大厅啥都没有 / 发的消息也看不到 / 发消息发不出去」。
        现在加了四道闸：不在地图待显示时动手、正在画时不动手、同一会话 8 秒冷却、
        每个会话最多自愈 2 次（之后只在日志里记一行，不再动手）。
        """
        try:
            view = getattr(self, '_current_view', None)
            if view is None or not self._alive(view.get('frame')):
                return
            if getattr(self, '_pending_map_frame', None) is not None:
                return                      # 有新滚动区等着显示，别插手
            if getattr(self, '_render_bulk', False) or getattr(self, '_render_queue', None):
                return                      # 正在画，别插手
            msgs = self.msgs.get(self.conv) or []
            if len(msgs) < 2:
                return
            kids = len(view['frame'].winfo_children())
            if kids > 1:
                return
            now = time.monotonic()
            last = getattr(self, '_heal_at', {}).get(self.conv, 0.0)
            if now - last < 8.0:
                return                      # 冷却期内不再动手
            counts = getattr(self, '_heal_n', {})
            if counts.get(self.conv, 0) >= 2:
                return                      # 这个会话已经自愈过两次，别再折腾
            if not hasattr(self, '_heal_at'):
                self._heal_at, self._heal_n = {}, {}
            self._heal_at[self.conv] = now
            self._heal_n[self.conv] = counts.get(self.conv, 0) + 1
            write_diag(f'自愈（第 {self._heal_n[self.conv]} 次）：会话 {self.conv!r} '
                       f'有 {len(msgs)} 条消息，界面上只有 {kids} 行 → 重画一次')
            view['sig'] = None
            self._render_conv()
        except Exception:
            pass

    def _msgs_append(self, m, optimistic=False):
        """把一条消息追加到本机会话并渲染。

        optimistic=True 表示这是「我发出去、界面先显示」的乐观回显：
        要登记一笔，等会儿服务端把同一条消息回显回来时去重，避免出现两个气泡。
        """
        conv = m.get('conv', CONV_ROOM)
        if optimistic:
            self._note_pending_echo(conv, m)
        elif self._is_own_echo(conv, m):
            self._trace(f'回显去重：丢弃 {conv} 的一条重复消息 {m.get("text")!r}')
            return False          # 服务端回显的这条本机已经显示过了
        self.msgs.setdefault(conv, []).append(m)
        shown = (conv == self.conv)
        if shown:
            if m.get('t') != 'system':
                self._drop_empty_hint()    # 真有消息了：删掉「这里还没有消息」占位
            self._cancel_preload(conv)     # 正在显示的会话由界面自己画，后台别插手
            # 自己刚发出去的消息必须看得见 —— 哪怕之前正在往上翻旧消息，
            # 也要自动跟到底部（用户反馈「点进去发消息看不到」就是这个）。
            me = (self.client.me if self.client else '') or ''
            mine = bool(m.get('self')) or (m.get('from') or '') == me
            if mine or optimistic:
                self._scroll_stick = True
            self._render(m)
            if mine or optimistic:
                self._pin_bottom()
            # 记住「这个会话当前画到哪儿了」：下次切回来直接复用，不用重画
            if self._current_view is not None and not self._render_queue:
                try:
                    self._current_view['sig'] = self._view_sig()
                except Exception:
                    pass
        else:
            # 别的会话来了新消息：它缓存的界面已经过期，重新排队预加载
            # （正在预热别的会话时不打断，画完那轮自然会轮到它）
            self._schedule_preload(PRELOAD_GAP, restart=(self._preload_target == conv))
        self._trace(f'收到/发送消息 conv={conv!r} shown={shown} '
                    f'from={m.get("from")!r} text={str(m.get("text"))[:40]!r} '
                    f'msgs={len(self.msgs.get(conv, []))}')
        return True

    # ---------- 自己发出去的消息：乐观回显去重 ----------
    @staticmethod
    def _msg_sig(m):
        """消息指纹。

        不含时间（两端时钟可能有偏差），也不含 kind —— 本机乐观回显用的是
        conv_kind（'friend'），服务端回显用的是 'pm'，带上就永远匹配不上。
        同一个会话里不存在「文本相同但类别不同」的两条消息，所以去掉是安全的。
        """
        return (str(m.get('from') or ''), str(m.get('text') or ''),
                str(m.get('fid') or ''), str(m.get('name') or ''))

    def _note_pending_echo(self, conv, m):
        """记一笔「这条是我刚发出去的，等服务端回显回来时别再画一遍」。

        时间戳用**本机单调时钟**：乐观回显和服务端回显的时间字段来自两台机器，
        时钟不同步时根本没法比。这里只关心「本机等了多久」，和时钟无关。
        """
        lst = self._pending_echo.setdefault(conv, [])
        lst.append({'sig': self._msg_sig(m), 'at': time.monotonic()})
        del lst[:-8]

    def _is_own_echo(self, conv, m):
        """这条是不是「我刚发出去、已经在界面上显示过」的那条的服务端回显。

        只按本机等待时长判断，**绝不比较两端的时间戳** —— 之前拿本机时间和服务端
        时间相减，两端时钟差超过 30 秒就直接判成「不是回显」，于是私聊里自己发的
        每条消息都会变成两个气泡（大厅/群聊服务端不回显给发送者，所以看不出问题）。
        """
        me = (self.client.me if self.client else '') or ''
        frm = m.get('from') or ''
        if not (m.get('self') or (me and frm == me)):
            return False
        pend = self._pending_echo.get(conv)
        if not pend:
            return False
        now = time.monotonic()
        # 先丢掉等太久的登记（正常回显几百毫秒就到，这只是防止登记表无限期生效）
        pend[:] = [p for p in pend
                   if now - float(p.get('at') or now) <= ECHO_MATCH_WINDOW]
        if not pend:
            return False
        sig = self._msg_sig(m)
        for i, p in enumerate(pend):
            if p['sig'] != sig:
                continue
            pend.pop(i)
            return True
        return False

    def _merge_history(self, conv, items):
        # 只接受属于这个会话的消息：任何串会话的内容都不许进这个会话
        items = [m for m in (items or [])
                 if not m.get('conv') or str(m.get('conv')) == str(conv)]
        """用服务端历史刷新会话，但**不能冲掉比这份历史更新的本地消息**。

        高延迟下很容易出现：刚点进会话（历史请求在途）→ 马上发一条 / 对方发来一条 →
        历史回包到得比它们晚。旧的写法 msgs[conv] = 历史 会把它们擦掉，
        于是「对面收得到、自己看不到」。
        """
        items = list(items or [])
        old = list(self.msgs.get(conv) or [])
        counts = {}
        for m in items:
            sig = self._msg_sig(m)
            counts[sig] = counts.get(sig, 0) + 1
        now = now_ts()
        extra = []
        for m in old:
            # 本身就是上一次历史带回来的 → 让新历史覆盖它，避免越积越多
            if m.get('history'):
                continue
            t = int(m.get('time') or 0)
            if t and now - t > 300:
                continue          # 太久远的本地残留不要了
            sig = self._msg_sig(m)
            if counts.get(sig, 0) > 0:
                counts[sig] -= 1  # 历史里已经有同样的了
                continue
            extra.append(m)
        self.msgs[conv] = items + extra
        self._trace(f'合并历史 conv={conv!r} 服务端={len(items)} 保留本地={len(extra)} '
                    f'合计={len(self.msgs[conv])}')

    def _command(self, text):
        c = self.client
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        if cmd in ('/help', '/?', '/帮助'):
            for line in HELP_TEXT.splitlines():
                self._add_sys(line)
        elif cmd in ('/clear', '/清屏'):
            self.msgs[self.conv] = []
            self._clear_view()
        elif cmd == '/ping':
            rtt = c.rtt
            self._add_sys(f'当前延迟：{rtt * 1000:.0f} ms' if rtt is not None else '尚未测量到延迟')
        elif cmd in ('/users', '/list', '/在线'):
            c.request_list()
            self._add_sys('在线：' + ('、'.join(c.online) or '（无）'))
        elif cmd in ('/quit', '/exit', '/退出'):
            self.disconnect()
        elif cmd == '/me':
            if conv_kind(self.conv) != 'room':
                self._add_sys('/me 只能在公共大厅使用')
            elif len(parts) < 2:
                self._add_sys('用法：/me <动作>')
            else:
                c.send_me(parts[1])
                self._msgs_append({'t': 'me', 'conv': CONV_ROOM, 'from': c.me,
                                   'text': parts[1], 'time': now_ts(), 'self': True})
        else:
            self._add_sys(f'未知命令：{cmd}，输入 /help 查看帮助')

    # ================= 文件 =================
    def _pick_file(self):
        if self.client is None or not self.connected:
            return
        path = filedialog.askopenfilename(
            title='选择要发送的文件',
            filetypes=[('所有文件', '*.*'),
                       ('图片', '*.png *.jpg *.jpeg *.gif *.bmp *.webp'),
                       ('视频', '*.mp4 *.avi *.mkv *.mov *.webm *.flv *.wmv *.m4v')])
        if path:
            self._send_file_async(path)

    def _send_file_async(self, path):
        c = self.client
        if c is None or not self.connected:
            return
        try:
            size = os.path.getsize(path)
        except OSError as e:
            self._add_sys(f'无法读取文件：{e}')
            return
        if size <= 0:
            self._add_sys('文件为空')
            return
        name = os.path.basename(path)
        conv = self.conv
        self._add_sys(f'📤 正在发送 {name}（{human_size(size)}）…')

        def work():
            try:
                c.send_file(path, conv)
            except Exception as e:
                self._ui_queue.put(lambda: self._add_sys(f'发送失败：{e}'))

        threading.Thread(target=work, daemon=True).start()

    def _open_path(self, path):
        if not path or not os.path.exists(path):
            self._add_sys('文件不存在或已被清理')
            return
        try:
            os.startfile(path)
        except AttributeError:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        except Exception as e:
            self._add_sys(f'打开失败：{e}')

    # ================= 拖拽 / 粘贴 =================
    def _bind_global(self):
        self.bind_all('<Control-v>', self._on_paste)
        self.bind_all('<Control-V>', self._on_paste)
        # 记录「你刚动过界面」：预加载会避开这段时间，不跟你抢主线程
        for seq in ('<KeyPress>', '<Button-1>', '<ButtonPress>', '<MouseWheel>'):
            try:
                self.bind_all(seq, self._note_input, add='+')
            except Exception:
                pass
        # 最小化/被遮住再回来：这段时间别抢主线程，先让系统把窗口重绘出来
        try:
            self.bind('<Unmap>', self._on_unmap, add='+')
            self.bind('<Map>', self._on_map, add='+')
        except Exception:
            pass
        self.update_idletasks()
        if DND_OK:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self._on_drop)
                self.dnd_bind('<<DropEnter>>', self._on_drag_enter)
                self.dnd_bind('<<DropLeave>>', self._on_drag_leave)
                self.dnd_ready = True
                self.dnd_backend = 'tkinterdnd2'
            except Exception:
                self.dnd_ready = False
        if not self.dnd_ready and WINDND_OK:
            try:
                windnd.hook_dropfiles(self.winfo_id(), func=self._on_windnd_drop)
                self.dnd_ready = True
                self.dnd_backend = 'windnd'
            except Exception:
                self.dnd_ready = False

    def _on_windnd_drop(self, files):
        for f in files:
            p = f
            if isinstance(f, (bytes, bytearray)):
                p = None
                for enc in ('utf-8', 'gbk', 'mbcs'):
                    try:
                        p = bytes(f).decode(enc)
                        break
                    except Exception:
                        continue
                if p is None:
                    continue
            if os.path.isfile(str(p)):
                self._send_file_async(str(p))

    def _on_drag_enter(self, event):
        if self.connected:
            self.drop_hint.place(relx=0.5, rely=0.5, anchor='center')
        return event.action

    def _on_drag_leave(self, event):
        self.drop_hint.place_forget()
        return event.action

    def _on_drop(self, event):
        self.drop_hint.place_forget()
        if not (self.client and self.connected):
            return event.action
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        for p in paths:
            p = str(p)
            if os.path.isfile(p):
                self._send_file_async(p)
        return event.action

    def _on_paste(self, event=None):
        if not (self.client and self.connected):
            return None
        try:
            clip = ImageGrab.grabclipboard()
        except Exception:
            return None
        try:
            if isinstance(clip, Image.Image):
                os.makedirs(self._paste_dir, exist_ok=True)
                path = os.path.join(self._paste_dir,
                                    f'截图_{time.strftime("%Y%m%d_%H%M%S")}.png')
                clip.convert('RGB').save(path, 'PNG')
                self._send_file_async(path)
                return 'break'
            if isinstance(clip, list) and clip:
                sent = False
                for p in clip:
                    if isinstance(p, str) and os.path.isfile(p):
                        self._send_file_async(p)
                        sent = True
                if sent:
                    return 'break'
        except Exception as e:
            self._add_sys(f'粘贴发送失败：{e}')
        return None

    # ================= 杂项 =================
    def _toggle_sound(self):
        self.sound_on = bool(self.sound_switch.get())
        try:
            self.sound.enabled = self.sound_on
        except Exception:
            pass
        if self.sound_on:
            self._sound('message')      # 打开时给个反馈

    def _ding(self, mention=False):
        """旧接口：保留给别处调用，统一走 _sound。"""
        return self._sound('mention' if mention else 'message')


def main():
    App().mainloop()


if __name__ == '__main__':
    main()
