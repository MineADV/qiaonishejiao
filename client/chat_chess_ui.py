"""悄匿社交 —— 中国象棋对局窗口（棋盘绘制 + 交互）。

棋盘用 PIL 渲染（超采样后缩放，线条和棋子都是抗锯齿的），比 tk 直接画线好看很多；
窗口其余部分用 customtkinter，配色由 chat_gui 传入，跟着界面主题走。
"""
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from chat_chess import (
    BOARD_ROWS, BOARD_COLS, PIECE_NAMES, side_of, kind_of,
    legal_moves_from, SIDE_RED, SIDE_BLACK,
)

# ---------- 棋盘配色（固定的木质色，不跟界面主题变，象棋盘本来就该是木头色） ----------
WOOD_TOP = (247, 228, 188)
WOOD_BOT = (230, 199, 143)
WOOD_EDGE = (196, 158, 104)
LINE = (146, 100, 52)
FRAME = (128, 84, 40)
RED_INK = (170, 38, 32)
BLACK_INK = (32, 28, 26)
FACE = (253, 245, 226)
FACE_EDGE = (206, 178, 132)
SEL_RING = (238, 172, 46)
HINT_DOT = (56, 146, 92)
LAST_MARK = (250, 206, 96)
CHECK_RING = (222, 62, 52)

# 这些颜色是刻意固定的（棋盘木色、执红/执黑的按钮色），不跟着界面主题走
SIDE_RED_BTN = '#c0392b'
SIDE_RED_BTN_HOVER = '#a93226'
SIDE_BLACK_BTN = '#2c3e50'
SIDE_BLACK_BTN_HOVER = '#1f2d3a'
SIDE_BTN_TEXT = '#ffffff'          # 红/黑按钮上的白字（固定，不跟主题）
CANVAS_BG = '#c49e68'


def fixed_colors():
    return {SIDE_RED_BTN, SIDE_RED_BTN_HOVER, SIDE_BLACK_BTN, SIDE_BLACK_BTN_HOVER,
            SIDE_BTN_TEXT, CANVAS_BG}

CELL = 56
MARGIN = 42
RADIUS = 24
SS = 2                      # 超采样倍数
# 外框画在棋子外侧（不然边线上的棋子会压住边框）
FRAME_OUT = 38
FRAME_IN = 34
BOARD_W = (BOARD_COLS - 1) * CELL + MARGIN * 2
BOARD_H = (BOARD_ROWS - 1) * CELL + MARGIN * 2


def load_font(size):
    """优先用楷体（写象棋棋子最好看），没有就退回系统字体。"""
    for name in ('simkai.ttf', 'simhei.ttf', 'msyhbd.ttc', 'msyh.ttc', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_board(board, scale, sel=None, hints=(), last=None, check_side=None,
               movable_side=None, result_banner=None, flip=False):
    """把整张棋盘画成一张 PIL 图片（已按 scale 缩放好）。

    flip=True 时把棋盘转 180°（行列都镜像），让执黑的一方看到黑方在下方 ——
    下棋习惯就是自己那边永远在下面。
    棋子、提示、上一步标记传进来的都是**棋盘坐标**，翻转只发生在绘制这一步。
    """
    w = max(2, int(round(BOARD_W * scale)))
    h = max(2, int(round(BOARD_H * scale)))
    W, H = w * SS, h * SS
    k = scale * SS                      # 逻辑坐标 → 绘制坐标
    img = Image.new('RGB', (W, H), WOOD_BOT)
    d = ImageDraw.Draw(img)

    # 木质底色：竖向渐变 + 一点木纹
    for y in range(H):
        t = y / max(1, H - 1)
        d.line([(0, y), (W, y)],
               fill=tuple(int(WOOD_TOP[i] + (WOOD_BOT[i] - WOOD_TOP[i]) * t) for i in range(3)))
    for i in range(0, W, 11):
        shade = 5 if (i // 11) % 3 else -4
        d.line([(i, 0), (i, H)],
               fill=tuple(max(0, min(255, WOOD_BOT[j] + shade)) for j in range(3)))

    def X(c):
        if flip:
            c = BOARD_COLS - 1 - c
        return (MARGIN + c * CELL) * k

    def Y(r):
        if flip:
            r = BOARD_ROWS - 1 - r
        return (MARGIN + r * CELL) * k

    lw = max(1, int(round(1.1 * k)))
    # 外框（在棋子外侧，避免边线上的棋子压住边框）；翻转后 X/Y 会反向，用 min/max 兜底
    x_lo, x_hi = sorted((X(0), X(8)))
    y_lo, y_hi = sorted((Y(0), Y(9)))
    d.rectangle([x_lo - FRAME_OUT * k, y_lo - FRAME_OUT * k,
                 x_hi + FRAME_OUT * k, y_hi + FRAME_OUT * k],
                outline=FRAME, width=max(2, int(round(2.8 * k))))
    d.rectangle([x_lo - FRAME_IN * k, y_lo - FRAME_IN * k,
                 x_hi + FRAME_IN * k, y_hi + FRAME_IN * k],
                outline=WOOD_EDGE, width=lw)

    # 横线
    for r in range(BOARD_ROWS):
        d.line([(X(0), Y(r)), (X(8), Y(r))], fill=LINE, width=lw)
    # 竖线（河界处断开，只留最左最右两条通到底）
    for c in range(BOARD_COLS):
        if c in (0, 8):
            d.line([(X(c), Y(0)), (X(c), Y(9))], fill=LINE, width=lw)
        else:
            d.line([(X(c), Y(0)), (X(c), Y(4))], fill=LINE, width=lw)
            d.line([(X(c), Y(5)), (X(c), Y(9))], fill=LINE, width=lw)

    # 九宫斜线
    for (r0, c0, r1, c1) in ((0, 3, 2, 5), (0, 5, 2, 3), (7, 3, 9, 5), (7, 5, 9, 3)):
        d.line([(X(c0), Y(r0)), (X(c1), Y(r1))], fill=LINE, width=lw)

    # 炮位 / 兵位的「十字准星」
    for (r, c) in ((2, 1), (2, 7), (7, 1), (7, 7)):
        for dc in (-1, 1):
            if c + dc < 0 or c + dc > 8:
                continue
            x = X(c) + dc * 4.5 * k
            d.line([(x, Y(r) - 4.5 * k), (x, Y(r) - 4.5 * k - 9 * k)], fill=LINE, width=lw)
            d.line([(x, Y(r) + 4.5 * k), (x, Y(r) + 4.5 * k + 9 * k)], fill=LINE, width=lw)
    for (r, c) in ((3, 0), (3, 2), (3, 4), (3, 6), (3, 8),
                   (6, 0), (6, 2), (6, 4), (6, 6), (6, 8)):
        for dc in (-1, 1):
            if c + dc < 0 or c + dc > 8:
                continue
            x = X(c) + dc * 4.5 * k
            d.line([(x, Y(r) - 4.5 * k), (x, Y(r) - 4.5 * k - 9 * k)], fill=LINE, width=lw)
            d.line([(x, Y(r) + 4.5 * k), (x, Y(r) + 4.5 * k + 9 * k)], fill=LINE, width=lw)

    # 楚河汉界（翻转后左右对调，跟真实棋子方位一致）
    left_text, right_text = ('汉 界', '楚 河') if flip else ('楚 河', '汉 界')
    f_river = load_font(max(10, int(round(21 * k))))
    d.text(((X(0) + X(8)) / 2 - CELL * k * 1.35, (Y(4) + Y(5)) / 2), left_text,
           font=f_river, fill=LINE, anchor='mm')
    d.text(((X(0) + X(8)) / 2 + CELL * k * 1.35, (Y(4) + Y(5)) / 2), right_text,
           font=f_river, fill=LINE, anchor='mm')

    # 上一步的起止点
    if last:
        fr, fc, tr, tc = last
        for (r, c) in ((fr, fc), (tr, tc)):
            d.rounded_rectangle(
                [X(c) - CELL * k * 0.46, Y(r) - CELL * k * 0.46,
                 X(c) + CELL * k * 0.46, Y(r) + CELL * k * 0.46],
                radius=CELL * k * 0.22, outline=LAST_MARK,
                width=max(2, int(round(3.0 * k))))

    # 可走点提示：空格画圆点，能吃子画外圈（画在棋子之后，否则会被棋子盖住）
    dots = []
    rings = []
    for (hfr, hfc, htr, htc) in hints:
        target = board[htr][htc] if 0 <= htr < BOARD_ROWS else '.'
        if target == '.':
            dots.append((htr, htc))
        else:
            rings.append((htr, htc))

    # 棋子
    f_piece = load_font(max(10, int(round(RADIUS * 1.24 * k))))
    for r in range(BOARD_ROWS):
        for c in range(BOARD_COLS):
            ch = board[r][c]
            if ch == '.':
                continue
            side = side_of(ch)
            cx, cy = X(c), Y(r)
            rr = RADIUS * k
            # 阴影
            d.ellipse([cx - rr + 2 * k, cy - rr + 3 * k, cx + rr + 2 * k, cy + rr + 3 * k],
                      fill=(196, 166, 118))
            face = FACE if side == SIDE_RED else (246, 240, 226)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=face,
                      outline=FACE_EDGE, width=max(1, int(round(1.2 * k))))
            inner = rr * 0.80
            d.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
                      outline=RED_INK if side == SIDE_RED else BLACK_INK,
                      width=max(1, int(round(1.6 * k))))
            if sel == (r, c):
                d.ellipse([cx - rr - 3 * k, cy - rr - 3 * k, cx + rr + 3 * k, cy + rr + 3 * k],
                          outline=SEL_RING, width=max(2, int(round(3.4 * k))))
            if check_side and kind_of(ch) == 'K' and side == check_side:
                d.ellipse([cx - rr - 4 * k, cy - rr - 4 * k, cx + rr + 4 * k, cy + rr + 4 * k],
                          outline=CHECK_RING, width=max(2, int(round(3.6 * k))))
            d.text((cx, cy + 1 * k), PIECE_NAMES[side][kind_of(ch)],
                   font=f_piece, fill=RED_INK if side == SIDE_RED else BLACK_INK,
                   anchor='mm')

    # 提示：空格点
    for (r, c) in dots:
        cx, cy = X(c), Y(r)
        rr = 5.5 * k
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=HINT_DOT)
    # 提示：可吃的子，在棋子外面套一圈
    for (r, c) in rings:
        cx, cy = X(c), Y(r)
        rr = RADIUS * k * 1.09
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=HINT_DOT,
                  width=max(2, int(round(3.4 * k))))

    img = img.resize((w, h), Image.LANCZOS)
    if result_banner:
        ov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        band = int(h * 0.16)
        top = (h - band) // 2
        od.rectangle([0, top, w, top + band], fill=(20, 16, 12, 190))
        img = img.convert('RGBA')
        img.alpha_composite(ov)
        img = img.convert('RGB')
        od2 = ImageDraw.Draw(img)
        f_ban = load_font(max(12, int(round(30 * scale))))
        od2.text((w / 2, h / 2), result_banner, font=f_ban, fill=(255, 236, 196), anchor='mm')
    return img


class ChessBoardView:
    """棋盘控件：负责把 PIL 图贴到 Canvas 上，并把点击换算成棋盘坐标。"""

    def __init__(self, master, on_click):
        self.canvas = tk.Canvas(master, highlightthickness=0, bd=0, bg=CANVAS_BG)
        self.on_click = on_click
        self.scale = 1.0
        self.flip = False          # True = 转 180°，让执黑的一方在自己下方
        self.board = None
        self.sel = None
        self.hints = []
        self.last = None
        self.check_side = None
        self.banner = None
        self._photo = None
        self._item = None
        self.canvas.bind('<Button-1>', self._click)
        self.canvas.bind('<Configure>', lambda e: None)

    def set_flip(self, flip):
        self.flip = bool(flip)

    def set_scale(self, scale):
        scale = max(0.5, float(scale))
        if abs(scale - self.scale) < 1e-6:
            return
        self.scale = scale
        self.canvas.configure(width=int(round(BOARD_W * self.scale)),
                              height=int(round(BOARD_H * self.scale)))

    def redraw(self, board, sel=None, hints=(), last=None, check_side=None, banner=None):
        self.board = board
        self.sel = sel
        self.hints = list(hints or [])
        self.last = last
        self.check_side = check_side
        self.banner = banner
        img = draw_board(board, self.scale, sel=sel, hints=self.hints, last=last,
                         check_side=check_side, result_banner=banner, flip=self.flip)
        self._photo = ImageTk.PhotoImage(img)
        if self._item is None:
            self._item = self.canvas.create_image(0, 0, anchor='nw', image=self._photo)
        else:
            self.canvas.itemconfigure(self._item, image=self._photo)

    def point_at(self, x, y):
        """画布坐标 → 棋盘 (row, col)，不在交叉点附近返回 None。

        翻转时要把「屏幕上的行列」换算回棋盘坐标，否则点子和落子会上下颠倒。
        """
        s = self.scale
        dc = round((x / s - MARGIN) / CELL)
        dr = round((y / s - MARGIN) / CELL)
        if not (0 <= dr < BOARD_ROWS and 0 <= dc < BOARD_COLS):
            return None
        dx = x / s - (MARGIN + dc * CELL)
        dy = y / s - (MARGIN + dr * CELL)
        if (dx * dx + dy * dy) ** 0.5 > CELL * 0.52:
            return None
        if self.flip:
            return (BOARD_ROWS - 1 - dr, BOARD_COLS - 1 - dc)
        return (dr, dc)

    def _click(self, event):
        pt = self.point_at(event.x, event.y)
        if pt is not None:
            self.on_click(pt)


class ChessWindow(ctk.CTkToplevel):
    """一局象棋的窗口。"""

    def __init__(self, master, game, palette, hooks):
        super().__init__(master)
        self.game = dict(game)
        self.pal = dict(palette)
        self.hooks = hooks            # on_move/on_resign/on_draw/on_undo/on_answer/on_close
        self.sel = None
        self.hints = []
        self.my_side = self.game.get('my_color')
        self.finished = bool(self.game.get('status') not in (None, 'playing'))
        self._closed = False
        self._confirm_win = None

        self.title('中国象棋 · ' + self.pal.get('app_title', '悄匿社交'))
        self.configure(fg_color=self.pal['bg_app'])
        self.resizable(False, False)
        self.transient(master)
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        self._build()
        self.apply_palette(self.pal)
        self.refresh()

    # ---------- 界面搭建 ----------
    def _build(self):
        head = ctk.CTkFrame(self, fg_color=self.pal['bg_header'], corner_radius=0, height=52)
        head.pack(fill='x')
        head.pack_propagate(False)
        self.head_icon = ctk.CTkLabel(head, text='♟  中国象棋', height=24,
                                      font=ctk.CTkFont(family=self.pal['font'], size=15,
                                                       weight='bold'))
        self.head_icon.pack(side='left', padx=14)
        self.head_info = ctk.CTkLabel(head, text='', height=22,
                                      font=ctk.CTkFont(family=self.pal['font'], size=12))
        self.head_info.pack(side='left', padx=6)

        body = ctk.CTkFrame(self, fg_color='transparent')
        body.pack(fill='both', expand=True)

        self.view = ChessBoardView(body, self._on_board_click)
        self.view.set_scale(self.pal.get('scale', 1.0))
        self.view.canvas.pack(side='left', padx=(14, 8), pady=(8, 6))

        side = ctk.CTkFrame(body, fg_color=self.pal['bg_panel'], corner_radius=14, width=232)
        side.pack(side='left', fill='y', padx=(4, 14), pady=(8, 6))
        side.pack_propagate(False)

        self.turn_label = ctk.CTkLabel(side, text='', anchor='w',
                                       font=ctk.CTkFont(family=self.pal['font'], size=15,
                                                        weight='bold'))
        self.turn_label.pack(fill='x', padx=14, pady=(14, 2))
        self.tip_label = ctk.CTkLabel(side, text='', anchor='w', wraplength=200,
                                      justify='left',
                                      font=ctk.CTkFont(family=self.pal['font'], size=11))
        self.tip_label.pack(fill='x', padx=14, pady=(0, 8))

        self.moves_box = ctk.CTkTextbox(side, height=250, corner_radius=10,
                                        border_width=0, activate_scrollbars=True,
                                        font=ctk.CTkFont(family=self.pal['font'], size=12))
        self.moves_box.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.moves_box.configure(state='disabled')

        # 和棋 / 悔棋的确认区：单独做成一张带边框的小卡片，和下面的
        # 「认输 / 求和 / 悔棋 / 关闭」那排按钮明显分开，不然挤在一起看不出
        # 哪两颗按钮是在回答对方。
        self.pending_bar = ctk.CTkFrame(side, fg_color='transparent', corner_radius=10,
                                        border_width=1)
        self.pending_bar.pack(fill='x', padx=12, pady=(0, 12))
        self.pending_label = ctk.CTkLabel(self.pending_bar, text='', anchor='w',
                                          wraplength=200, justify='left',
                                          font=ctk.CTkFont(family=self.pal['font'], size=12,
                                                           weight='bold'))
        self.pending_label.pack(fill='x', padx=10, pady=(8, 0))
        self.pending_btns = ctk.CTkFrame(self.pending_bar, fg_color='transparent')
        self.pending_btns.pack(fill='x', padx=10, pady=(8, 10))
        self.agree_btn = ctk.CTkButton(self.pending_btns, text='✓  同意', height=32,
                                       corner_radius=16, width=96,
                                       font=ctk.CTkFont(family=self.pal['font'], size=12,
                                                        weight='bold'),
                                       command=lambda: self._answer(True))
        self.agree_btn.pack(side='left')
        self.reject_btn = ctk.CTkButton(self.pending_btns, text='✕  拒绝', height=32,
                                        corner_radius=16, width=96,
                                        font=ctk.CTkFont(family=self.pal['font'], size=12),
                                        command=lambda: self._answer(False))
        self.reject_btn.pack(side='left', padx=(8, 0))

        btns = ctk.CTkFrame(side, fg_color='transparent')
        btns.pack(fill='x', padx=12, pady=(0, 12))
        self.action_bar = btns
        self.resign_btn = ctk.CTkButton(btns, text='认输', height=34, corner_radius=10,
                                        font=ctk.CTkFont(family=self.pal['font'], size=12),
                                        command=self._resign)
        self.resign_btn.pack(fill='x', pady=(0, 6))
        row = ctk.CTkFrame(btns, fg_color='transparent')
        row.pack(fill='x')
        self.draw_btn = ctk.CTkButton(row, text='求和', height=34, corner_radius=10,
                                      font=ctk.CTkFont(family=self.pal['font'], size=12),
                                      command=self._offer_draw)
        self.draw_btn.pack(side='left', expand=True, fill='x')
        self.undo_btn = ctk.CTkButton(row, text='悔棋', height=34, corner_radius=10,
                                      font=ctk.CTkFont(family=self.pal['font'], size=12),
                                      command=self._request_undo)
        self.undo_btn.pack(side='left', expand=True, fill='x', padx=(6, 0))
        self.close_btn = ctk.CTkButton(btns, text='关闭', height=32, corner_radius=10,
                                       fg_color='transparent', border_width=1,
                                       font=ctk.CTkFont(family=self.pal['font'], size=12),
                                       command=self._on_close)
        self.close_btn.pack(fill='x', pady=(6, 0))

    # ---------- 配色 ----------
    def apply_palette(self, palette):
        self.pal = dict(palette)
        p = self.pal
        f = p['font']
        self.configure(fg_color=p['bg_app'])

        def paint(widget, **kw):
            try:
                widget.configure(**kw)
            except Exception:
                pass

        try:
            self.winfo_children()[0].configure(fg_color=p['bg_header'])
            self.turn_label.master.configure(fg_color=p['bg_panel'])
        except Exception:
            pass
        paint(self.head_icon, text_color=p['text'])
        paint(self.head_info, text_color=p['text_dim'])
        paint(self.turn_label, text_color=p['text'])
        paint(self.tip_label, text_color=p['text_dim'])
        paint(self.moves_box, fg_color=p['field_bg'], text_color=p['text'],
              scrollbar_button_color=p['scroll_btn'],
              scrollbar_button_hover_color=p['scroll_hover'])
        paint(self.pending_label, text_color=p['warn'])
        # 同意＝绿、拒绝＝红（都是实心），一眼能看出哪个是「答应」哪个是「不答应」
        paint(self.pending_bar, fg_color=p['bg_panel'], border_color=p['field_border'])
        paint(self.agree_btn, fg_color=p.get('ok', p['accent']),
              hover_color=p.get('ok_dim', p['accent_dim']),
              text_color=p['on_accent'])
        paint(self.reject_btn, fg_color=p['danger'], hover_color=p['danger_dim'],
              text_color=p['on_accent'])
        paint(self.resign_btn, fg_color=p['danger'], hover_color=p['danger_dim'],
              text_color=p['on_accent'])
        paint(self.draw_btn, fg_color=p['accent'], hover_color=p['accent_dim'],
              text_color=p['on_accent'])
        paint(self.undo_btn, fg_color=p['bg_active'], hover_color=p['bg_hover'],
              text_color=p['text'])
        paint(self.close_btn, border_color=p['field_border'], hover_color=p['bg_hover'],
              text_color=p['text_dim'])
        for w in (self.head_icon, self.head_info, self.turn_label, self.tip_label,
                  self.moves_box, self.pending_label, self.agree_btn, self.reject_btn,
                  self.resign_btn, self.draw_btn, self.undo_btn, self.close_btn):
            try:
                w.configure(font=ctk.CTkFont(family=f, size=w.cget('font').cget('size'),
                                             weight=w.cget('font').cget('weight')))
            except Exception:
                pass
        self._paint_frames()
        self.refresh()

    def _paint_frames(self):
        try:
            self.winfo_children()[0].configure(fg_color=self.pal['bg_header'])
        except Exception:
            pass
        try:
            self.turn_label.master.configure(fg_color=self.pal['bg_panel'])
        except Exception:
            pass

    def force_close(self):
        """不做「还没下完」的确认，直接关掉（退出登录 / 主题重建时用）。"""
        self._closed = True
        try:
            self.destroy()
        except Exception:
            pass

    # ---------- 状态刷新 ----------
    def update_game(self, game):
        self.game = dict(game)
        self.my_side = self.game.get('my_color') or self.my_side
        if self.game.get('status') not in (None, 'playing'):
            self.finished = True
            self.sel = None
            self.hints = []
        self.refresh()

    def _name_line(self):
        g = self.game
        me = self.my_side
        red, black = g.get('red', ''), g.get('black', '')
        tag_r = '（我）' if me == SIDE_RED else ''
        tag_b = '（我）' if me == SIDE_BLACK else ''
        return f'红 {red}{tag_r}   vs   黑 {black}{tag_b}'

    def refresh(self):
        g = self.game
        board = g.get('board') or []
        if not board:
            return
        status = g.get('status') or 'playing'
        turn = g.get('turn') or 'r'
        self.finished = status != 'playing'
        # 自己执黑就把棋盘转过来，让黑方在下方（下棋习惯）
        self.view.set_flip(self.my_side == SIDE_BLACK)
        self.head_info.configure(text=self._name_line())

        banner = None
        if status == 'red_win':
            banner = f'红方胜（{reason_cn(g.get("reason"))}）'
        elif status == 'black_win':
            banner = f'黑方胜（{reason_cn(g.get("reason"))}）'
        elif status == 'draw':
            banner = f'和棋（{reason_cn(g.get("reason"))}）'

        if self.finished:
            winner_side = {'red_win': SIDE_RED, 'black_win': SIDE_BLACK}.get(status)
            if winner_side:
                self.turn_label.configure(
                    text=('🎉 你赢了' if winner_side == self.my_side else '😵 你输了'))
            else:
                self.turn_label.configure(text='🤝 和棋')
            self.tip_label.configure(text=f'对局结束：{reason_cn(g.get("reason"))}')
        else:
            mine = (turn == self.my_side)
            who = '红方' if turn == SIDE_RED else '黑方'
            self.turn_label.configure(text=('轮到你走（%s）' % who) if mine
                                      else f'等待对方走棋（{who}）')
            my_side_cn = '红' if self.my_side == SIDE_RED else '黑'
            if g.get('check'):
                self.tip_label.configure(text='⚠ 将军！')
            else:
                self.tip_label.configure(
                    text=f'你执{my_side_cn}（{my_side_cn}方在下方）· 点自己的棋子，再点绿点落子')

        self._refresh_moves()
        self._refresh_pending()
        for b in (self.resign_btn, self.draw_btn, self.undo_btn):
            b.configure(state='disabled' if self.finished else 'normal')
        if self.finished:
            self.draw_btn.configure(state='disabled')
            self.undo_btn.configure(state='disabled')

        self.view.set_scale(self.pal.get('scale', 1.0))
        self.view.redraw(board, sel=self.sel, hints=self.hints, last=g.get('last'),
                         check_side=(turn if g.get('check') else None), banner=banner)

    def _refresh_moves(self):
        g = self.game
        nots = g.get('notations') or []
        lines = []
        for i in range(0, len(nots), 2):
            n = i // 2 + 1
            red = nots[i]
            black = nots[i + 1] if i + 1 < len(nots) else ''
            lines.append(f'{n:>2}. {red:<7}{black}')
        text = '\n'.join(lines) if lines else '（还没有走子）'
        self.moves_box.configure(state='normal')
        self.moves_box.delete('1.0', 'end')
        self.moves_box.insert('1.0', text)
        self.moves_box.see('end')
        self.moves_box.configure(state='disabled')

    def _refresh_pending(self):
        g = self.game
        pend = g.get('pending')
        if self.finished or not pend:
            # 没有待确认的事就把整张卡片收起来，别留一个空框占地方
            self.pending_bar.pack_forget()
            return
        kind = '和棋' if pend.get('kind') == 'draw' else '悔棋'
        mine = (pend.get('by') or '').lower() == (g.get('me') or '').lower()
        if not self.pending_bar.winfo_manager():
            try:
                self.pending_bar.pack(fill='x', padx=12, pady=(0, 12),
                                      before=self.action_bar)
            except Exception:
                self.pending_bar.pack(fill='x', padx=12, pady=(0, 12))
        if mine:
            self.pending_label.configure(text=f'⏳  你请求{kind}，等待对方确认…')
            self.agree_btn.pack_forget()
            self.reject_btn.pack_forget()
        else:
            self.pending_label.configure(text=f'⚖  对方请求{kind}，同意吗？')
            self.agree_btn.pack(side='left')
            self.reject_btn.pack(side='left', padx=(8, 0))

    # ---------- 交互 ----------
    def _on_board_click(self, pt):
        g = self.game
        if self.finished or (g.get('status') or 'playing') != 'playing':
            return
        if g.get('turn') != self.my_side:
            return
        board = g.get('board') or []
        if not board:
            return
        r, c = pt
        ch = board[r][c]
        if self.sel is not None:
            for (fr, fc, tr, tc) in self.hints:
                if (tr, tc) == (r, c):
                    self.sel = None
                    self.hints = []
                    self.hooks['on_move'](g.get('gid'), fr, fc, tr, tc)
                    return
        if ch != '.' and side_of(ch) == self.my_side:
            self.sel = (r, c)
            self.hints = legal_moves_from(board, self.my_side, r, c)
        else:
            self.sel = None
            self.hints = []
        self.view.redraw(board, sel=self.sel, hints=self.hints, last=g.get('last'),
                         check_side=(g.get('turn') if g.get('check') else None),
                         banner=None)

    def _answer(self, accept):
        pend = (self.game.get('pending') or {})
        self.hooks['on_answer'](self.game.get('gid'), pend.get('kind'), accept)

    def _resign(self):
        self.hooks['on_resign'](self.game.get('gid'))

    def _offer_draw(self):
        self.hooks['on_draw'](self.game.get('gid'))

    def _request_undo(self):
        self.hooks['on_undo'](self.game.get('gid'))

    def _on_close(self):
        if self._closed:
            return
        g = self.game
        if (g.get('status') or 'playing') == 'playing':
            self._ask_leave()
            return
        self._finish_close()

    def _ask_leave(self):
        """棋局还没结束就退出：弹一个确认框，并明确说明这等于认输。"""
        if self._confirm_win is not None:
            try:
                if self._confirm_win.winfo_exists():
                    self._confirm_win.lift()
                    return
            except Exception:
                pass
        self._confirm_win = ConfirmDialog(
            self,
            title='退出这一局？',
            message=('棋局还在进行中。\n\n'
                     f'确定要退出吗？退出将视为**认输**，'
                     f'{self._opponent_name()} 直接获胜。'),
            ok_text='认输并退出',
            cancel_text='继续下棋',
            palette=self.pal,
            on_ok=self._confirm_leave,
        )

    def _opponent_name(self):
        g = self.game
        if self.my_side == SIDE_RED:
            return g.get('black') or '对手'
        if self.my_side == SIDE_BLACK:
            return g.get('red') or '对手'
        return '对手'

    def _confirm_leave(self):
        self._confirm_win = None
        g = self.game
        if (g.get('status') or 'playing') == 'playing':
            self.hooks['on_resign'](g.get('gid'))
        self._finish_close()

    def _cancel_leave(self):
        self._confirm_win = None

    def _finish_close(self):
        if self._closed:
            return
        self._closed = True
        self.hooks['on_close'](self.game.get('gid'))
        try:
            self.destroy()
        except Exception:
            pass


def reason_cn(reason):
    return {'checkmate': '绝杀', 'stalemate': '困毙', 'resign': '认输',
            'agreement': '双方同意和棋', 'leave': '对方离线', 'abort': '中止'}.get(
        reason or '', reason or '')


class ConfirmDialog(ctk.CTkToplevel):
    """居中的确认框（**加粗** 标记会渲染成强调色）。"""

    def __init__(self, master, title, message, ok_text, cancel_text, palette,
                 on_ok, on_cancel=None, danger=True):
        super().__init__(master)
        p = palette or {}
        f = p.get('font', 'Microsoft YaHei UI')
        self._on_ok = on_ok
        self._on_cancel = on_cancel
        self.title(title)
        self.configure(fg_color=p.get('bg_panel', '#17212b'))
        self.resizable(False, False)
        self.transient(master)
        self.protocol('WM_DELETE_WINDOW', self._cancel)

        ctk.CTkLabel(self, text='⚠', text_color=p.get('warn', '#e5a54b'),
                     font=ctk.CTkFont(family=f, size=30)).pack(pady=(18, 2))
        ctk.CTkLabel(self, text=title, text_color=p.get('text', '#ffffff'),
                     font=ctk.CTkFont(family=f, size=15, weight='bold')).pack()
        # 把 **强调** 拆出来单独上色
        for piece, strong in self._split(message):
            ctk.CTkLabel(self, text=piece, justify='left', wraplength=320,
                         text_color=p.get('danger' if (strong and danger)
                                          else p.get('text_dim', '#7f91a4')),
                         font=ctk.CTkFont(family=f, size=12,
                                          weight='bold' if strong else 'normal')).pack(
                anchor='w', padx=24, pady=(6 if strong else 0, 0))

        row = ctk.CTkFrame(self, fg_color='transparent')
        row.pack(fill='x', padx=22, pady=(16, 18))
        self.ok_btn = ctk.CTkButton(
            row, text=ok_text, height=38, corner_radius=10,
            fg_color=p.get('danger', '#e06c75') if danger else p.get('accent', '#3390ec'),
            hover_color=p.get('danger_dim', '#b0555d') if danger
            else p.get('accent_dim', '#2b6fb0'),
            text_color=p.get('on_accent', '#ffffff'),
            font=ctk.CTkFont(family=f, size=13, weight='bold'), command=self._ok)
        self.ok_btn.pack(side='right')
        self.cancel_btn = ctk.CTkButton(
            row, text=cancel_text, height=38, corner_radius=10, width=100,
            fg_color='transparent', border_width=1,
            border_color=p.get('field_border', '#2b3a4a'),
            hover_color=p.get('bg_hover', '#202b36'),
            text_color=p.get('text_dim', '#7f91a4'),
            font=ctk.CTkFont(family=f, size=13), command=self._cancel)
        self.cancel_btn.pack(side='right', padx=(0, 8))
        self.bind('<Escape>', lambda e: self._cancel())
        self.bind('<Return>', lambda e: self._ok())
        self.after(60, self._place)

    @staticmethod
    def _split(message):
        """把 **加粗** 段落拆成 (文本, 是否强调)。"""
        out = []
        for i, part in enumerate(str(message).split('**')):
            if part:
                out.append((part, i % 2 == 1))
        return out or [('', False)]

    def _place(self):
        try:
            self.update_idletasks()
            m = self.master
            x = m.winfo_rootx() + (m.winfo_width() - self.winfo_width()) // 2
            y = m.winfo_rooty() + (m.winfo_height() - self.winfo_height()) // 3
            self.geometry(f'+{max(0, x)}+{max(0, y)}')
            self.lift()
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    def _ok(self):
        cb = self._on_ok
        self._close()
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _cancel(self):
        cb = self._on_cancel
        self._close()
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass



class ChallengeDialog(ctk.CTkToplevel):
    """收到约战：被挑战方选执红还是执黑。"""

    def __init__(self, master, info, palette, on_pick, on_reject):
        super().__init__(master)
        self.hooks = (on_pick, on_reject)
        p = palette
        f = p['font']
        self.title('象棋约战' + p.get('title_suffix', ''))
        self.configure(fg_color=p['bg_panel'])
        self.resizable(False, False)
        self.transient(master)
        self.geometry('380x300')
        self.protocol('WM_DELETE_WINDOW', lambda: self._done(None))

        ctk.CTkLabel(self, text='♟', fg_color='transparent', text_color=p['accent'],
                     font=ctk.CTkFont(family=f, size=40)).pack(pady=(20, 0))
        ctk.CTkLabel(self, text=f'{info.get("from", "")} 邀你对弈中国象棋',
                     text_color=p['text'],
                     font=ctk.CTkFont(family=f, size=16, weight='bold')).pack(pady=(4, 2))
        region = info.get('region') or ''
        ctk.CTkLabel(self, text=(f'对方属地：{region}' if region else ''),
                     text_color=p['region'],
                     font=ctk.CTkFont(family=f, size=11)).pack()
        ctk.CTkLabel(self, text='你要执哪一方？（红方先行）', text_color=p['text_dim'],
                     font=ctk.CTkFont(family=f, size=12)).pack(pady=(12, 6))

        row = ctk.CTkFrame(self, fg_color='transparent')
        row.pack(fill='x', padx=26)
        self.red_btn = ctk.CTkButton(row, text='● 执红先行', height=42, corner_radius=12,
                                     fg_color=SIDE_RED_BTN, hover_color=SIDE_RED_BTN_HOVER,
                                     text_color='#ffffff',
                                     font=ctk.CTkFont(family=f, size=14, weight='bold'),
                                     command=lambda: self._done('r'))
        self.red_btn.pack(side='left', expand=True, fill='x')
        self.black_btn = ctk.CTkButton(row, text='○ 执黑后行', height=42, corner_radius=12,
                                       fg_color=SIDE_BLACK_BTN,
                                       hover_color=SIDE_BLACK_BTN_HOVER,
                                       text_color='#ffffff',
                                       font=ctk.CTkFont(family=f, size=14, weight='bold'),
                                       command=lambda: self._done('b'))
        self.black_btn.pack(side='left', expand=True, fill='x', padx=(10, 0))
        self.reject_btn = ctk.CTkButton(self, text='拒绝', height=34, corner_radius=10,
                                        fg_color='transparent', border_width=1,
                                        border_color=p['field_border'],
                                        hover_color=p['bg_hover'], text_color=p['text_dim'],
                                        font=ctk.CTkFont(family=f, size=13),
                                        command=lambda: self._done(None))
        self.reject_btn.pack(fill='x', padx=26, pady=(14, 0))
        self.after(80, lambda: (self.lift(), self.focus_force()))

    def _done(self, color):
        pick, reject = self.hooks
        try:
            self.destroy()
        except Exception:
            pass
        if color:
            pick(color)
        else:
            reject()
