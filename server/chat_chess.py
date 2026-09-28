"""悄匿社交 —— 中国象棋规则引擎（纯逻辑，无界面、无网络）。

棋盘坐标：10 行 × 9 列，row 0 在最上方（黑方底线），row 9 在最下方（红方底线）。
棋子编码：一个字符一格，'.' 表示空；大写为红方、小写为黑方，字母为兵种：
    K/k 帥將   A/a 仕士   B/b 相象   N/n 馬   R/r 車   C/c 炮   P/p 兵卒

本模块只负责「规则」：走法生成、将军判定、绝杀/困毙判定、中文记谱。
对局状态（谁执红、历史、悔棋、和棋、认输）由 ChessGame 维护，服务端直接调用。
"""

BOARD_ROWS = 10
BOARD_COLS = 9

SIDE_RED = 'r'
SIDE_BLACK = 'b'

PIECE_NAMES = {
    'r': {'K': '帥', 'A': '仕', 'B': '相', 'N': '馬', 'R': '車', 'C': '炮', 'P': '兵'},
    'b': {'K': '將', 'A': '士', 'B': '象', 'N': '馬', 'R': '車', 'C': '砲', 'P': '卒'},
}
# 走法记谱里的兵种名（黑方传统上写作 車馬砲，这里统一用简体常见写法）
PIECE_MARK = {
    'r': {'K': '帥', 'A': '仕', 'B': '相', 'N': '馬', 'R': '車', 'C': '炮', 'P': '兵'},
    'b': {'K': '將', 'A': '士', 'B': '象', 'N': '馬', 'R': '車', 'C': '炮', 'P': '卒'},
}

CN_NUM = '一二三四五六七八九'

INITIAL_BOARD = [
    'rnbakabnr',
    '.........',
    '.c.....c.',
    'p.p.p.p.p',
    '.........',
    '.........',
    'P.P.P.P.P',
    '.C.....C.',
    '.........',
    'RNBAKABNR',
]


# ---------------------------------------------------------------- 基础工具
def other(side):
    return SIDE_BLACK if side == SIDE_RED else SIDE_RED


def side_of(ch):
    """棋子字符 → 'r' / 'b'（空格返回 None）。"""
    if not ch or ch == '.':
        return None
    return SIDE_RED if ch.isupper() else SIDE_BLACK


def kind_of(ch):
    return ch.upper() if ch and ch != '.' else ''


def forward_delta(side):
    """「向前」对应的行增量：红方向上（-1），黑方向下（+1）。"""
    return -1 if side == SIDE_RED else 1


def in_palace(side, r, c):
    if c < 3 or c > 5:
        return False
    return (7 <= r <= 9) if side == SIDE_RED else (0 <= r <= 2)


def own_half(side, r):
    """是否还在自己这边河界内。"""
    return r >= 5 if side == SIDE_RED else r <= 4


def on_board(r, c):
    return 0 <= r < BOARD_ROWS and 0 <= c < BOARD_COLS


def initial_board():
    return list(INITIAL_BOARD)


def board_lines(board):
    """统一成 10 个长度 9 的字符串。"""
    out = []
    for r in range(BOARD_ROWS):
        row = board[r] if r < len(board) else ''
        row = ''.join(ch if ch and ch != ' ' else '.' for ch in str(row))
        row = (row + '.' * BOARD_COLS)[:BOARD_COLS]
        out.append(row)
    return out


def apply_move(board, mv):
    """返回走子后的新棋盘（不修改原棋盘）。"""
    fr, fc, tr, tc = mv
    rows = [list(r) for r in board_lines(board)]
    rows[tr][tc] = rows[fr][fc]
    rows[fr][fc] = '.'
    return [''.join(r) for r in rows]


def find_king(board, side):
    want = 'K' if side == SIDE_RED else 'k'
    for r in range(BOARD_ROWS):
        c = board[r].find(want)
        if c >= 0:
            return (r, c)
    return None


def kings_face(board):
    """白脸将：两个将帅在同一列且中间没有棋子。"""
    rk = find_king(board, SIDE_RED)
    bk = find_king(board, SIDE_BLACK)
    if rk is None or bk is None:
        return False
    if rk[1] != bk[1]:
        return False
    lo, hi = sorted((rk[0], bk[0]))
    for r in range(lo + 1, hi):
        if board[r][rk[1]] != '.':
            return False
    return True


# ---------------------------------------------------------------- 走法生成
def _steps(board, r, c, deltas, side):
    out = []
    for dr, dc in deltas:
        tr, tc = r + dr, c + dc
        if not on_board(tr, tc):
            continue
        tgt = board[tr][tc]
        if tgt != '.' and side_of(tgt) == side:
            continue
        out.append((r, c, tr, tc))
    return out


def _slide(board, r, c, dirs, side):
    out = []
    for dr, dc in dirs:
        tr, tc = r + dr, c + dc
        while on_board(tr, tc):
            tgt = board[tr][tc]
            if tgt == '.':
                out.append((r, c, tr, tc))
            else:
                if side_of(tgt) != side:
                    out.append((r, c, tr, tc))
                break
            tr += dr
            tc += dc
    return out


def _cannon(board, r, c, dirs, side):
    out = []
    for dr, dc in dirs:
        tr, tc = r + dr, c + dc
        jumped = False
        while on_board(tr, tc):
            tgt = board[tr][tc]
            if not jumped:
                if tgt == '.':
                    out.append((r, c, tr, tc))
                else:
                    jumped = True
            else:
                if tgt != '.':
                    if side_of(tgt) != side:
                        out.append((r, c, tr, tc))
                    break
            tr += dr
            tc += dc
    return out


def piece_moves(board, r, c):
    """单个棋子的伪合法走法（不检查走后是否自己被将军）。"""
    ch = board[r][c]
    side = side_of(ch)
    if side is None:
        return []
    kind = kind_of(ch)
    f = forward_delta(side)
    if kind == 'K':
        out = []
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tr, tc = r + dr, c + dc
            if not in_palace(side, tr, tc):
                continue
            tgt = board[tr][tc]
            if tgt != '.' and side_of(tgt) == side:
                continue
            out.append((r, c, tr, tc))
        return out
    if kind == 'A':
        out = []
        for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            tr, tc = r + dr, c + dc
            if not in_palace(side, tr, tc):
                continue
            tgt = board[tr][tc]
            if tgt != '.' and side_of(tgt) == side:
                continue
            out.append((r, c, tr, tc))
        return out
    if kind == 'B':
        out = []
        for dr, dc in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
            tr, tc = r + dr, c + dc
            if not on_board(tr, tc) or not own_half(side, tr):
                continue
            if board[r + dr // 2][c + dc // 2] != '.':   # 塞象眼
                continue
            tgt = board[tr][tc]
            if tgt != '.' and side_of(tgt) == side:
                continue
            out.append((r, c, tr, tc))
        return out
    if kind == 'N':
        out = []
        for dr, dc, lr, lc in ((2, 1, 1, 0), (2, -1, 1, 0), (-2, 1, -1, 0), (-2, -1, -1, 0),
                               (1, 2, 0, 1), (-1, 2, 0, 1), (1, -2, 0, -1), (-1, -2, 0, -1)):
            tr, tc = r + dr, c + dc
            if not on_board(tr, tc):
                continue
            if board[r + lr][c + lc] != '.':             # 蹩马腿
                continue
            tgt = board[tr][tc]
            if tgt != '.' and side_of(tgt) == side:
                continue
            out.append((r, c, tr, tc))
        return out
    if kind == 'R':
        return _slide(board, r, c, ((1, 0), (-1, 0), (0, 1), (0, -1)), side)
    if kind == 'C':
        return _cannon(board, r, c, ((1, 0), (-1, 0), (0, 1), (0, -1)), side)
    if kind == 'P':
        out = []
        tr = r + f
        if on_board(tr, c):
            tgt = board[tr][c]
            if tgt == '.' or side_of(tgt) != side:
                out.append((r, c, tr, c))
        if not own_half(side, r):        # 过河后才能横走
            for dc in (-1, 1):
                tc = c + dc
                if not on_board(r, tc):
                    continue
                tgt = board[r][tc]
                if tgt == '.' or side_of(tgt) != side:
                    out.append((r, c, r, tc))
        return out
    return []


def pseudo_moves(board, side):
    out = []
    for r in range(BOARD_ROWS):
        row = board[r]
        for c in range(BOARD_COLS):
            ch = row[c]
            if ch != '.' and side_of(ch) == side:
                out.extend(piece_moves(board, r, c))
    return out


def in_check(board, side):
    """己方是否被将军（含「白脸将」）。"""
    if kings_face(board):
        return True
    k = find_king(board, side)
    if k is None:
        return True
    for mv in pseudo_moves(board, other(side)):
        if (mv[2], mv[3]) == k:
            return True
    return False


def is_legal(board, mv, side=None):
    """走法是否合法：棋子归属正确、伪合法、且走完自己不被将军。"""
    fr, fc, tr, tc = mv
    if not (on_board(fr, fc) and on_board(tr, tc)):
        return False
    ch = board[fr][fc]
    s = side_of(ch)
    if s is None:
        return False
    if side is not None and s != side:
        return False
    if (mv[0], mv[1], mv[2], mv[3]) not in piece_moves(board, fr, fc):
        return False
    return not in_check(apply_move(board, mv), s)


def legal_moves(board, side):
    return [mv for mv in pseudo_moves(board, side) if is_legal(board, mv, side)]


def legal_moves_from(board, side, fr, fc):
    """某个棋子的全部合法走法（界面用来画提示点）。"""
    if not on_board(fr, fc):
        return []
    ch = board[fr][fc]
    if ch == '.' or side_of(ch) != side:
        return []
    return [mv for mv in piece_moves(board, fr, fc) if is_legal(board, mv, side)]


def has_legal_move(board, side):
    for mv in pseudo_moves(board, side):
        if is_legal(board, mv, side):
            return True
    return False


def game_status(board, side):
    """按「轮到谁走」判断局势：'playing' / 'red_win' / 'black_win'。

    中国象棋里「困毙」（无棋可走但未被将军）同样判负，所以两种情况都算输。
    """
    if has_legal_move(board, side):
        return 'playing'
    return 'black_win' if side == SIDE_RED else 'red_win'


def end_reason(board, side):
    """无棋可走时的原因：将军 → 绝杀，否则 → 困毙。"""
    return 'checkmate' if in_check(board, side) else 'stalemate'


# ---------------------------------------------------------------- 中文记谱
def file_no(side, col):
    """列号 → 该方视角的「第几路」（双方都从自己右手边数起）。"""
    return (BOARD_COLS - col) if side == SIDE_RED else (col + 1)


def num_str(side, n):
    """红方用汉字数字，黑方用阿拉伯数字（传统写法）。"""
    n = int(n)
    if side == SIDE_RED:
        return CN_NUM[n - 1] if 1 <= n <= 9 else str(n)
    return str(n)


def move_notation(board, mv):
    """把一步棋写成中文记谱，如「炮二平五」「馬8进7」「前車退一」。"""
    board = board_lines(board)
    fr, fc, tr, tc = mv
    ch = board[fr][fc]
    side = side_of(ch)
    if side is None:
        return ''
    kind = kind_of(ch)
    name = PIECE_MARK[side][kind]

    same = [r for r in range(BOARD_ROWS) if board[r][fc] == ch]
    if len(same) >= 2:
        # 同一路上有多个同类子：用 前/中/后 定位（更靠对方的一侧为「前」）
        order = sorted(same) if side == SIDE_RED else sorted(same, reverse=True)
        idx = order.index(fr)
        if len(order) == 2:
            prefix = '前' if idx == 0 else '后'
        elif len(order) == 3:
            prefix = ('前', '中', '后')[idx]
        else:
            prefix = num_str(side, idx + 1)
        head = prefix + name
    else:
        head = name + num_str(side, file_no(side, fc))

    if fr == tr:
        return head + '平' + num_str(side, file_no(side, tc))
    advancing = (tr - fr) * forward_delta(side) > 0
    action = '进' if advancing else '退'
    if kind in ('N', 'B', 'A'):
        val = file_no(side, tc)      # 斜行子记「到第几路」
    else:
        val = abs(tr - fr)
    return head + action + num_str(side, val)


def side_name(side):
    return '红方' if side == SIDE_RED else '黑方'


# ---------------------------------------------------------------- 对局状态
class ChessGame:
    """一局棋：谁执红黑、历史、悔棋、和棋、认输、绝杀判定。"""

    def __init__(self, gid, red, black):
        self.gid = str(gid)
        self.red = red            # 红方昵称（先行）
        self.black = black
        self.history = [initial_board()]     # 依次是每一步之后的棋盘
        self.moves = []                      # 每一步 (fr,fc,tr,tc)
        self.notations = []
        self.turn = SIDE_RED
        self.result = None        # None / 'red' / 'black' / 'draw'
        self.reason = ''
        self.pending = None       # {'kind': 'draw'|'undo', 'by': 昵称}
        self.undo_count = 0
        self.draw_offers = 0
        self.created = 0.0
        self.finished = 0.0

    # ---------- 基本查询 ----------
    @property
    def board(self):
        return self.history[-1]

    @property
    def over(self):
        return self.result is not None

    def side_of(self, nick):
        if nick and self.red and nick.lower() == self.red.lower():
            return SIDE_RED
        if nick and self.black and nick.lower() == self.black.lower():
            return SIDE_BLACK
        return None

    def nick_of(self, side):
        return self.red if side == SIDE_RED else self.black

    def opponent_of(self, nick):
        s = self.side_of(nick)
        return self.nick_of(other(s)) if s else None

    def last_move(self):
        return self.moves[-1] if self.moves else None

    def in_check_now(self):
        if self.over:
            return False
        return in_check(self.board, self.turn)

    def snapshot(self):
        """下发给客户端的完整对局快照。"""
        last = self.last_move()
        return {
            'gid': self.gid,
            'red': self.red,
            'black': self.black,
            'board': list(self.board),
            'turn': self.turn,
            'last': list(last) if last else None,
            'notations': list(self.notations),
            'check': self.in_check_now(),
            'status': self.status_word(),
            'reason': self.reason,
            'pending': dict(self.pending) if self.pending else None,
            'can_undo': bool(self.moves) and not self.over,
            'move_no': len(self.moves),
        }

    def status_word(self):
        if self.result == 'draw':
            return 'draw'
        if self.result == 'red':
            return 'red_win'
        if self.result == 'black':
            return 'black_win'
        return 'playing'

    # ---------- 走子 ----------
    def do_move(self, nick, fr, fc, tr, tc):
        """返回 (ok, 错误信息)。成功后自动判定绝杀 / 困毙。"""
        if self.over:
            return False, '棋局已经结束'
        side = self.side_of(nick)
        if side is None:
            return False, '你不在这一局里'
        if side != self.turn:
            return False, '还没轮到你走'
        try:
            mv = (int(fr), int(fc), int(tr), int(tc))
        except (TypeError, ValueError):
            return False, '走法格式不对'
        if mv[0] == mv[2] and mv[1] == mv[3]:
            return False, '原地不动不算走棋'
        if not is_legal(self.board, mv, side):
            return False, '这一步不合规则'
        # 走棋即视为放弃自己提出的和棋 / 悔棋请求
        self.pending = None
        self.history.append(apply_move(self.board, mv))
        self.moves.append(mv)
        self.notations.append(move_notation(self.history[-2], mv))
        self.turn = other(side)
        self._check_end()
        return True, ''

    def _check_end(self):
        st = game_status(self.board, self.turn)
        if st == 'playing':
            return
        self.result = 'red' if st == 'red_win' else 'black'
        self.reason = end_reason(self.board, self.turn)

    # ---------- 悔棋 ----------
    def request_undo(self, nick):
        if self.over:
            return False, '棋局已经结束'
        s = self.side_of(nick)
        if s is None:
            return False, '你不在这一局里'
        if not self.moves:
            return False, '还没有走过棋'
        if self.pending:
            return False, '已经有一个待对方确认的请求了'
        self.pending = {'kind': 'undo', 'by': nick}
        return True, ''

    def apply_undo(self, by_nick):
        """同意悔棋：撤销到「请求方最近那一步之前」，让对方重新应对。

        - 请求方刚落子完（轮到对方）：撤 1 步
        - 对方已经应了一手（轮到请求方）：撤 2 步
        这样才符合「悔棋 = 把自己那步收回来重走」的直觉。
        """
        by_side = self.side_of(by_nick)
        if by_side is None or not self.moves:
            self.pending = None
            return 0
        idx = None
        for i in range(len(self.moves) - 1, -1, -1):
            # 红先，所以偶数手是红方走的
            if (SIDE_RED if i % 2 == 0 else SIDE_BLACK) == by_side:
                idx = i
                break
        if idx is None:
            self.pending = None
            return 0
        n = len(self.moves) - idx
        for _ in range(n):
            self.history.pop()
            self.moves.pop()
            self.notations.pop()
        self.turn = SIDE_RED if len(self.moves) % 2 == 0 else SIDE_BLACK
        self.undo_count += 1
        self.pending = None
        self.result = None
        self.reason = ''
        return n

    # ---------- 和棋 / 认输 ----------
    def offer_draw(self, nick):
        if self.over:
            return False, '棋局已经结束'
        if self.side_of(nick) is None:
            return False, '你不在这一局里'
        if self.pending:
            return False, '已经有一个待对方确认的请求了'
        self.pending = {'kind': 'draw', 'by': nick}
        self.draw_offers += 1
        return True, ''

    def agree_draw(self, nick):
        """两人都同意才判和棋。"""
        if self.over:
            return False, '棋局已经结束'
        if self.side_of(nick) is None:
            return False, '你不在这一局里'
        if not self.pending or self.pending.get('kind') != 'draw':
            return False, '现在没有待确认的和棋请求'
        if self.pending.get('by', '').lower() == (nick or '').lower():
            return False, '和棋需要对方同意，不能自己同意自己'
        self.pending = None
        self.result = 'draw'
        self.reason = 'agreement'
        return True, ''

    def reject_pending(self, nick):
        if not self.pending:
            return False, '没有待确认的请求'
        if self.pending.get('by', '').lower() == (nick or '').lower():
            return False, '这是你自己发起的请求'
        self.pending = None
        return True, ''

    def resign(self, nick):
        side = self.side_of(nick)
        if side is None:
            return False, '你不在这一局里'
        if self.over:
            return False, '棋局已经结束'
        self.result = 'black' if side == SIDE_RED else 'red'
        self.reason = 'resign'
        self.pending = None
        return True, ''

    def abort(self, reason='abort'):
        """一方掉线/离开导致棋局终止：判仍在场的一方胜；两人都不在则作废。"""
        if self.over:
            return False
        self.result = 'draw'
        self.reason = reason
        self.pending = None
        return True

    def win_by(self, nick, reason='leave'):
        side = self.side_of(nick)
        if side is None or self.over:
            return False
        self.result = 'red' if side == SIDE_RED else 'black'
        self.reason = reason
        self.pending = None
        return True
