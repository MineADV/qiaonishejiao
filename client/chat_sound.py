"""悄匿社交 —— 提示音（内存里合成波形，不需要带音频文件）。

为什么要自己合成：打包成 exe 后要是再带一堆 .wav，既占体积又容易漏文件；
这里用 wave 模块现场生成 PCM，再交给 winsound 以 SND_MEMORY 播放，
打包后一定在、也不依赖任何第三方库。

音色设计：
    message      好友/群聊新消息：柔和的两声「叮咚」
    mention      被 @ 到：更亮的三声
    chess_move   落子：短促的木质「啪」
    chess_check  将军：两声上扬的警示
    chess_undo   悔棋：下滑的轻声
    chess_end    棋局结束：三声小琶音
    challenge    收到约战：跟 mention 类似但更轻快
"""
import io
import math
import queue
import random
import struct
import sys
import threading
import time
import wave

SR = 22050          # 采样率


# ---------------------------------------------------------------- 波形合成
def _env(i, n, attack=0.012, decay=4.5):
    """起音淡入 + 指数衰减，避免爆音、也更像敲击声。"""
    a = max(1, int(n * attack))
    e = 1.0 if i >= a else (i / a)
    return e * math.exp(-decay * i / float(n))


def _tone(freq, ms, vol=0.5, decay=4.5, harm=0.18, glide=None):
    """一个音符。glide 给终点频率就做滑音。"""
    n = max(1, int(SR * ms / 1000.0))
    out = [0.0] * n
    phase = 0.0
    for i in range(n):
        f = freq if glide is None else freq + (glide - freq) * (i / float(n))
        phase += 2.0 * math.pi * f / SR
        s = math.sin(phase)
        if harm:
            s += harm * math.sin(2.0 * phase)
        out[i] = vol * _env(i, n, decay=decay) * s
    return out


def _silence(ms):
    return [0.0] * max(1, int(SR * ms / 1000.0))


def _mix(*tracks):
    n = max(len(t) for t in tracks)
    out = [0.0] * n
    for t in tracks:
        for i, v in enumerate(t):
            out[i] += v
    return out


def _seq(notes, gap=0.0):
    """按顺序拼接若干音符。"""
    out = []
    for note in notes:
        out.extend(note)
        if gap:
            out.extend(_silence(gap))
    return out


def _wood_hit(ms=175, vol=0.92):
    """落子声：木质棋子「啪」地磕在棋盘上。

    以前只有 95ms、能量只有消息提示音的 1/6，实测基本听不见（用户反馈「落子
    没音效」）。现在做成：一记干脆的起手脆响 + 厚实的木腔共鸣 + 一点尾音，
    时长和能量都拉到和「消息」提示音一个量级。
    """
    n = max(1, int(SR * ms / 1000.0))
    out = [0.0] * n
    rnd = random.Random(20240921)
    phase = 0.0
    lp = 0.0
    for i in range(n):
        k = i / float(n)
        # 木腔：音高从 420Hz 滑到 190Hz，衰减慢一点，听着更有「木头味」
        f = 420.0 - 230.0 * k
        phase += 2.0 * math.pi * f / SR
        body = math.sin(phase) * math.exp(-5.0 * k)
        body += 0.28 * math.sin(2.0 * phase) * math.exp(-8.0 * k)
        # 起手脆响：低通噪声，衰减很快（就是那声「啪」）
        lp += 0.45 * (rnd.uniform(-1.0, 1.0) - lp)
        click = lp * math.exp(-22.0 * k)
        # 棋盘回弹：一个稍晚出现的小回音，增加厚度
        echo = 0.0
        if k > 0.18:
            ke = (k - 0.18) / 0.82
            echo = 0.35 * math.sin(2.0 * math.pi * 260.0 * i / SR) * math.exp(-9.0 * ke)
        out[i] = vol * (0.85 * body + 0.7 * click + echo) * _env(i, n, 0.0015, 1.0)
    return out


def _pcm_to_wav(samples, vol=0.92):
    peak = max(1e-9, max(abs(v) for v in samples))
    scale = min(1.0, vol / peak) * 32767.0
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b''.join(
            struct.pack('<h', int(max(-32768, min(32767, v * scale))))
            for v in samples))
    return buf.getvalue()


def _build():
    """生成所有提示音的 wav 数据（只在第一次用到时算一次）。"""
    return {
        'message': _pcm_to_wav(_seq([
            _tone(880, 90, 0.45, 5.0),
            _tone(1174.7, 140, 0.42, 4.0),
        ], gap=18)),
        'mention': _pcm_to_wav(_seq([
            _tone(987.8, 80, 0.50, 5.0),
            _tone(1318.5, 80, 0.50, 5.0),
            _tone(1568.0, 150, 0.46, 3.6),
        ], gap=12)),
        'challenge': _pcm_to_wav(_seq([
            _tone(880, 90, 0.48, 5.0),
            _tone(1108.7, 90, 0.48, 5.0),
            _tone(1479.98, 170, 0.44, 3.4),
        ], gap=14)),
        'chess_move': _pcm_to_wav(_wood_hit()),
        'chess_check': _pcm_to_wav(_seq([
            _tone(740, 130, 0.50, 4.0),
            _tone(988, 200, 0.50, 3.2),
        ], gap=10)),
        'chess_undo': _pcm_to_wav(_seq([
            _tone(620, 90, 0.40, 6.0, glide=520),
            _tone(470, 130, 0.36, 5.0, glide=392),
        ], gap=10)),
        'chess_end': _pcm_to_wav(_seq([
            _tone(784, 110, 0.45, 4.5),
            _tone(987.8, 110, 0.45, 4.5),
            _tone(1174.7, 200, 0.42, 3.0),
        ], gap=12)),
    }


# ---------------------------------------------------------------- 播放
class SoundPlayer:
    """提示音播放器；mute 时完全不出声。

    注意：Windows 的 PlaySound **不允许** SND_MEMORY 和 SND_ASYNC 同时用
    （会报 "Cannot play asynchronously from memory"）。所以这里在一条专用
    线程上同步播放：既不卡住界面，连续来的提示音也会排队依次响，
    不会互相打断。
    """

    MAX_QUEUE = 8

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self._cache = {}
        self._lock = threading.Lock()
        self._ok = None          # winsound 是否可用（探测一次）
        self._queue = queue.Queue()
        self._thread = None
        self._thread_lock = threading.Lock()
        self._busy = threading.Event()
        self.last_played = None  # 供测试/排查用
        self.play_count = 0

    def _ensure(self):
        if self._ok is None:
            try:
                import winsound as _w      # noqa: F401
                self._ok = True
            except Exception:
                self._ok = False
        return self._ok

    def wav(self, kind):
        with self._lock:
            if not self._cache:
                self._cache = _build()
            return self._cache.get(kind)

    # ---------- 播放 ----------
    def play(self, kind='message'):
        """请求播放一个提示音；立即返回，实际发声在后台线程。"""
        if not self.enabled:
            return False
        if not self._ensure():
            return False
        if self.wav(kind) is None:
            kind = 'message'
        try:
            if self._queue.qsize() >= self.MAX_QUEUE:
                return False          # 积压太多就丢掉，别让提示音排队排到天荒地老
            self._queue.put_nowait(kind)
        except Exception:
            return False
        self._ensure_thread()
        return True

    def _ensure_thread(self):
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()

    def _loop(self):
        while True:
            kind = self._queue.get()
            try:
                data = self.wav(kind)
                if not data:
                    continue
                self._busy.set()
                self.last_played = kind
                self.play_count += 1
                self._emit(data)
            except Exception:
                pass
            finally:
                self._busy.clear()

    def wait_idle(self, timeout=3.0):
        """等当前提示音放完（测试用）。"""
        end = time.time() + timeout
        while time.time() < end:
            if self._busy.is_set() or not self._queue.empty():
                time.sleep(0.01)
                continue
            time.sleep(0.02)
            if not self._busy.is_set() and self._queue.empty():
                return True
        return False

    def _emit(self, data):
        """真正出声的一步（同步；测试里可以替换掉它）。"""
        import winsound
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


_DEFAULT = None


def default_player():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = SoundPlayer()
    return _DEFAULT


def play(kind='message'):
    return default_player().play(kind)


def kinds():
    return sorted(_build().keys())


def _selftest():
    """命令行自检：py chat_sound.py [kind]"""
    print('可用音效：', '、'.join(kinds()))
    which = sys.argv[1] if len(sys.argv) > 1 else None
    p = SoundPlayer()
    todo = [which] if which else kinds()
    for k in todo:
        d = p.wav(k)
        ok = p.play(k)
        print(f'  {k:12s} {len(d):6d} 字节  {"已播放" if ok else "（不可用）"}')
        p.wait_idle()
        time.sleep(0.12)


if __name__ == '__main__':
    _selftest()
