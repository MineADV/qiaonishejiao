"""UDP 聊天室 —— 可靠传输信道。

在不可靠的 UDP 之上实现：
- 滑动窗口 + 累积确认 + 选择性重传 + 接收端乱序缓存（兼顾速度与抗丢包）
- 单包尺寸受控，避免 IP 分片带来的“丢一片即整包丢”放大效应
- AES-GCM 负载加密（按报文 F_ENC 标志判定）
- 心跳 PING/PONG 与 RTT 测量
- 宽容的死亡判定：只有“长时间收不到任何报文”或“窗口长时间毫无确认进展”才判死，
  不再因为几次重传失败就断开（这正是发文件时误报超时的根因）。
"""
import queue
import socket
import struct
import threading
import time

from chat_common import (
    build_packet, parse_packet, encrypt_payload, decrypt_payload,
    K_DATA, K_ACK, K_PING, K_PONG, F_ENC,
    RTO_MIN, RTO_MAX, RTO_INITIAL, RTO_BACKOFF_CAP, MAX_RETRIES,
    TAIL_PROBE_MIN, TAIL_PROBE_MAX, STARVE_GAP,
    FAST_RESEND_DUPACK, IDLE_PING, DEAD_TIMEOUT, TICK, PACE_PER_TICK,
    WINDOW, MAX_REORDER, NO_PROGRESS_TIMEOUT, SILENT_WARN, IDLE_TICK,
)


class ReliableChannel:
    """一条与单个对端通信的可靠信道。"""

    def __init__(self, sock: socket.socket, addr, sid: bytes, key: bytes,
                 enc_out: bool = False, on_deliver=None, on_dead=None, on_error=None,
                 on_session_lost=None, on_silent=None):
        self.sock = sock
        self.addr = addr
        self.sid = sid
        self.key = key
        self.enc_out = enc_out      # 是否加密发出的数据
        self.secure = False         # 认证后仅接受加密入站数据
        self.send_marker = False    # 只服务端用：用 1 字节 PONG 标记「不认识这个会话」
        self.check_marker = False   # 只客户端用：收到 1 字节 PONG 就认为会话失效
        self.peer_ready = False     # 服务端：这个连接已经登录过了
        self.session_lost = False   # 对端明确表示：这个会话不存在了
        self.on_deliver = on_deliver
        self.on_dead = on_dead
        self.on_error = on_error    # 内部异常上报（默认静默）
        self.on_session_lost = on_session_lost
        self.on_silent = on_silent  # 「暂时收不到包」/「恢复了」的通知（默认无）
        # 判死阈值做成实例属性：既方便按环境调，也方便测试里缩短
        self.silent_warn = SILENT_WARN
        self.dead_timeout = DEAD_TIMEOUT
        self.no_progress_timeout = NO_PROGRESS_TIMEOUT
        self.silent = False         # 当前是不是处于「暂时收不到」状态
        self.last_silent_for = 0.0  # 刚恢复时记录一下中断了多久
        self.starved_total = 0.0    # 本进程被饿住的总时长（不含最后的 gap）
        self.max_gap = 0.0          # 发送循环两次迭代之间的最大间隔
        self._last_loop = time.monotonic()

        self.lock = threading.Lock()
        self.send_queue = queue.Queue()   # 元素 (payload_bytes, encrypt_bool)
        self.send_seq = 0                 # 下一个要分配的数据序号
        self.window = {}                  # 在途未确认：seq -> [pkt, sent_at, retries]
        self.next_seq = 0                 # 期望收到的下一个序号
        self.recv_buf = {}                # 乱序缓存：seq -> payload

        self.last_recv = time.monotonic()
        self.last_sent = time.monotonic()
        self.rtt = None
        self.dead = False
        self._stop = threading.Event()
        self._wake = threading.Event()    # 事件驱动：有新数据或收到确认时立刻唤醒
        self._dead_reported = False
        self._last_progress = time.monotonic()
        self._last_ack = 0                # 快速重传用：最近一次确认号
        self._dup_ack = 0                 # 快速重传用：重复确认计数
        self.srtt = None                  # 平滑 RTT（秒）
        self.rttvar = None                # RTT 偏差
        self._rtt_samples = 0

        self.sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self.sender_thread.start()

    # ---------- 发送 ----------
    def send_json(self, obj, force_plain: bool = False):
        """入队一条 JSON 应用消息。force_plain 用于 HELLO/DENY 等未认证报文。"""
        from chat_common import encode_json
        self.send_queue.put((encode_json(obj), self.enc_out and not force_plain))
        self._wake.set()

    def enable_secure(self):
        """认证成功：此后发出的数据加密，且只接受加密入站数据。"""
        self.enc_out = True
        self.secure = True

    def pending(self):
        """尚未发送完成的消息数（排队中 + 在途），用于大文件流式发送的背压。"""
        with self.lock:
            n = len(self.window)
        return self.send_queue.qsize() + n

    def close(self):
        self._stop.set()
        self._wake.set()

    # ---------- 入站处理（由拥有者的接收线程调用） ----------
    def handle_incoming(self, pkt):
        now = time.monotonic()
        gap = now - getattr(self, 'last_recv', now)
        self.last_recv = now
        # 链路刚从「收不到包」里缓过来：这时候对端明明活着，在途的包别按指数退避
        # 干等 —— 那会让黑洞结束后的消息还要再卡好几秒（实测最长 9 秒）。
        # 立刻清掉退避、把在途包重发一遍，恢复几乎是瞬时的。
        if gap >= STARVE_GAP and self.window:
            with self.lock:
                for entry in self.window.values():
                    entry[1] = 0.0           # 下一次发送循环立刻重传
                    entry[2] = 0             # 退避清零
            self._wake.set()
        kind = pkt['kind']

        if kind in (K_DATA, K_ACK):
            self._process_ack(pkt['ack'])

        if kind == K_DATA:
            self._on_data(pkt)
        elif kind == K_PING:
            # 心跳应答。已登录的会话原样回负载；没登录的（典型情况：服务端刚重启，
            # 客户端还拿着旧 sid 在心跳）回一个 1 字节标记，客户端一看就知道
            # 「这个会话已经不存在了」，可以立刻重连，不用干等 20 秒判超时。
            if self.send_marker and not self.peer_ready:
                payload = b'\x00'
            else:
                payload = pkt['payload']
            self._sendto(build_packet(K_PONG, 0, 0, self.next_seq, self.sid, payload))
        elif kind == K_PONG:
            if self.check_marker and len(pkt['payload']) != 8:
                # 标记包：对端不认识这个会话了
                self.session_lost = True
                if self.on_session_lost:
                    try:
                        self.on_session_lost()
                    except Exception:
                        pass
                return
            try:
                t = struct.unpack('<d', pkt['payload'])[0]
                self.rtt = time.monotonic() - t
            except Exception:
                pass

    def _process_ack(self, ack):
        """累积确认 + 快速重传：连续收到重复确认说明中间有缺口，立刻补发该包。

        同时用「最早那个没有重传过的被确认包」做 RTT 采样（Karn 算法：
        重传过的包不采样，否则会把 RTT 算小，导致 RTO 越来越激进）。
        """
        resend = None
        sample = None
        now = time.monotonic()
        with self.lock:
            done = sorted(s for s in self.window if s < ack)
            for s in done:
                entry = self.window[s]
                if entry[2] == 0:
                    sample = now - entry[1]
                    break
            for s in done:
                del self.window[s]
            if done:
                self._last_progress = now
                self._last_ack = ack
                self._dup_ack = 0
                self._wake.set()
            elif ack == self._last_ack:
                self._dup_ack += 1
                if self._dup_ack >= FAST_RESEND_DUPACK and ack in self.window:
                    self._dup_ack = 0
                    entry = self.window[ack]
                    entry[1] = now
                    entry[2] += 1
                    resend = entry[0]
            else:
                self._last_ack = ack
                self._dup_ack = 0
        if sample is not None:
            self._update_rtt(sample)
        if resend is not None:
            self._sendto(resend)

    # ---------- RTT 估计 / 自适应超时 ----------
    def _update_rtt(self, sample):
        if not (0 < sample < 60):
            return
        with self.lock:
            self._rtt_samples += 1
            if self.srtt is None:
                self.srtt = sample
                self.rttvar = max(sample / 2.0, 0.01)
            else:
                self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - sample)
                self.srtt = 0.875 * self.srtt + 0.125 * sample
            self.rtt = self.srtt

    def current_rto(self):
        """当前重传超时：srtt + 4*rttvar，限制在 [RTO_MIN, RTO_MAX]。"""
        with self.lock:
            srtt, var = self.srtt, self.rttvar
        if srtt is None:
            base = RTO_INITIAL
        else:
            base = srtt + max(0.05, 4.0 * (var or 0.0))
        return min(max(base, RTO_MIN), RTO_MAX)

    def _on_data(self, pkt):
        if self.secure and not (pkt['flags'] & F_ENC):
            return  # 认证后拒绝明文注入
        seq = pkt['seq']
        if seq < self.next_seq:
            self._send_ack()                    # 重复包
            return
        if seq > self.next_seq + MAX_REORDER:
            self._send_ack()                    # 太超前，丢弃但回报当前进度
            return
        payload = self._decode(pkt)
        if payload is None:
            return
        if seq == self.next_seq:
            self._deliver(payload)
            self.next_seq += 1
            while self.next_seq in self.recv_buf:   # 交付缓存的后续包
                self._deliver(self.recv_buf.pop(self.next_seq))
                self.next_seq += 1
            self._send_ack()
        else:
            if len(self.recv_buf) < MAX_REORDER:
                self.recv_buf[seq] = payload
            self._send_ack()

    def _decode(self, pkt):
        payload = pkt['payload']
        if pkt['flags'] & F_ENC:
            if not self.key:
                return None
            return decrypt_payload(self.key, payload)
        return payload

    def _deliver(self, payload):
        if self.on_deliver:
            try:
                self.on_deliver(payload)
            except Exception:
                pass

    # ---------- 内部 ----------
    def _sendto(self, data):
        try:
            self.sock.sendto(data, self.addr)
        except OSError:
            pass

    def _send_ack(self):
        self._sendto(build_packet(K_ACK, 0, 0, self.next_seq, self.sid, b''))

    def _mark_dead(self):
        self.dead = True
        self._stop.set()
        self._wake.set()
        if not self._dead_reported:
            self._dead_reported = True
            if self.on_dead:
                try:
                    self.on_dead()
                except Exception:
                    pass

    def _build_data(self, seq, payload, encrypt):
        if encrypt and self.key:
            wire = encrypt_payload(self.key, payload)
            flags = F_ENC
        else:
            wire = payload
            flags = 0
        return build_packet(K_DATA, flags, seq, self.next_seq, self.sid, wire)

    def _sender_loop(self):
        self._last_loop = time.monotonic()
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                gap = now - self._last_loop
                self._last_loop = now
                if gap > STARVE_GAP:
                    # 本进程自己被饿住了（GC、杀软扫描、CPU 被抢）。
                    # 这段时间我们根本没在跑，收不到包不是对端的错，
                    # 所以把「判死计时」往后推一点，避免误判掉线。
                    self.starved_total += gap
                    self.max_gap = max(self.max_gap, gap)
                    grace = min(gap, self.dead_timeout * 0.5)
                    self.last_recv = max(self.last_recv, now - grace)
                    pgrace = min(gap, self.no_progress_timeout * 0.5)
                    self._last_progress = max(self._last_progress, now - pgrace)
                    if self.on_error and gap > STARVE_GAP * 4:
                        self.on_error(f'本机卡顿 {gap:.1f} 秒（GC/CPU 抢占），'
                                      f'已按此顺延判死计时')
                self._sender_once()
            except Exception:
                # 发送线程死了 = 再也发不出任何东西，但界面看上去还连着，
                # 直到 20 秒后被判离线。所以这里绝不能让它退出。
                if self.on_error:
                    try:
                        import traceback
                        self.on_error(f'发送循环异常：{traceback.format_exc()}')
                    except Exception:
                        pass
                time.sleep(0.05)

    def _sender_once(self):
        # 空闲时把循环放慢：没有任何在途包/待发包时，5ms 一次纯属浪费 CPU
        # （一个会话 200 次/秒，20 个会话就是 4000 次/秒，小服务器会被拖住，
        #  结果就是心跳回不及时、大家都被判「网络不稳」）。
        # 有活干就回到 5ms；空闲 50ms 一次，心跳(3s)和重传(≥200ms) 都不受影响。
        with self.lock:
            busy = bool(self.window) or not self.send_queue.empty()
        self._wake.wait(TICK if busy else IDLE_TICK)
        self._wake.clear()
        if self._stop.is_set():
            return
        now = time.monotonic()

        # --- 0) 「暂时收不到」和「真的断了」分开处理 ---
        # 先只提示「网络不稳」，继续重传/心跳；只有超过 dead_timeout 才真判死。
        # 这样十几秒的黑洞（跨洋抖动、切 Wi-Fi、NAT 重绑）能自己恢复，不再
        # 无谓地断开重登。
        silent_for = now - self.last_recv
        if not self.silent and silent_for >= self.silent_warn:
            self.silent = True
            if self.on_silent:
                try:
                    self.on_silent(True, silent_for)
                except Exception:
                    pass
        elif self.silent and silent_for < self.silent_warn * 0.5:
            self.silent = False
            self.last_silent_for = silent_for
            if self.on_silent:
                try:
                    self.on_silent(False, silent_for)
                except Exception:
                    pass

        # --- 判死 1：长时间收不到任何报文 ---
        if silent_for > self.dead_timeout:
            self._mark_dead()
            return
        with self.lock:
            inflight = len(self.window)
            stalled = now - self._last_progress
        # --- 判死 2：窗口长时间毫无确认进展 ---
        if inflight and stalled > self.no_progress_timeout:
            self._mark_dead()
            return

        # --- 1) 填满滑动窗口（限速削峰，避免一次性灌爆链路队列） ---
        sent_new = 0
        while sent_new < PACE_PER_TICK:
            with self.lock:
                if len(self.window) >= WINDOW:
                    break
            try:
                payload, encrypt = self.send_queue.get_nowait()
            except queue.Empty:
                break
            with self.lock:
                seq = self.send_seq
                self.send_seq += 1
            pkt = self._build_data(seq, payload, encrypt)
            with self.lock:
                self.window[seq] = [pkt, now, 0]
            self._sendto(pkt)
            self.last_sent = now
            sent_new += 1

        # --- 2) 超时重传（选择性重传 + 每包独立指数退避） ---
        rto = self.current_rto()
        with self.lock:
            items = sorted(self.window.items(), key=lambda kv: kv[1][1])  # 按发送时间排序
            srtt = self.srtt
        # 尾包快速补发：只在途很少几个包（典型的聊天消息）时，别等指数退避 ——
        # 最后那个包丢了没有后续包能触发快速重传，干等几十秒就是「消息卡住」。
        tail = len(items) <= TAIL_PROBE_MAX
        probe = max(TAIL_PROBE_MIN, 2.0 * (srtt if srtt else RTO_INITIAL))
        resent = 0
        for seq, entry in items:
            wait = rto * (2 ** min(entry[2], RTO_BACKOFF_CAP))
            if tail:
                wait = min(wait, probe)
            if now - entry[1] < wait:
                continue            # 注意：不能 break，否则较新的包会挡住更早超时的包
            if MAX_RETRIES and entry[2] >= MAX_RETRIES:
                continue            # 只有在显式限制重传次数时才放弃（默认 0 = 不放弃）
            self._sendto(entry[0])
            with self.lock:
                if seq in self.window:
                    self.window[seq][1] = now
                    self.window[seq][2] += 1
            resent += 1
            if resent >= PACE_PER_TICK:   # 一轮最多补发这么多，避免突发
                break

        # --- 3) 空闲心跳 ---
        if now - self.last_sent >= IDLE_PING:
            self._sendto(build_packet(K_PING, 0, 0, self.next_seq, self.sid,
                                      struct.pack('<d', now)))
            self.last_sent = now
