"""悄匿社交 —— 客户端网络核心（无界面，可被 GUI / CLI 复用）。"""
import base64
import json
import os
import queue
import socket
import tempfile
import threading
import time

from chat_common import (
    derive_key_salted, auth_proof, decode_json, parse_packet,
    file_kind, tune_udp_socket, conv_kind, conv_filename,
    normalize_host, resolve_host,
    CONV_ROOM, CONV_AVATAR,
    MAX_FILE_SIZE, FILE_CHUNK_RAW, AVATAR_FID_PREFIX, FILE_INDEX_MAX,
)
from chat_net import ReliableChannel


class ChatClient:
    def __init__(self, host, port, addr=None):
        """host 可以是 IP、域名，甚至直接粘进来的 http://域名:端口/ 也能认。

        解析优先 IPv4，只有 AAAA 记录的域名（纯 IPv6 服务器）也能连上。
        addr 可以直接给一个已解析好的 (family, sockaddr)，用于多地址重试。
        """
        h, p = normalize_host(host)
        self.host = h or (host or '').strip()
        self.port = int(p or port)
        self.key = None
        self.sid = os.urandom(16)

        if addr:
            self.candidates = [addr]
        else:
            self.candidates = resolve_host(self.host, self.port)
        self.family, self.server_addr = self.candidates[0]

        self.sock = socket.socket(self.family, socket.SOCK_DGRAM)
        tune_udp_socket(self.sock)
        self.sock.bind(('0.0.0.0', 0) if self.family == socket.AF_INET else ('::', 0))
        self.sock.settimeout(0.2)

        self.events = queue.Queue()
        self.connected = False
        self.denied = None
        self.me = None
        self.users = []
        self.friends = []
        self.blocks = []
        self.invites = []
        self.social_ready = False
        self.requests = []
        self.groups = []
        self.online = []
        self.regions = {}          # 昵称 -> IP 属地（由服务端判定后下发）
        self.avatar_ver = {}       # 昵称小写 -> 头像版本号（0 = 没有头像）
        self.group_infos = {}      # gid -> 群资料（公告 / 群文件 / 成员 / 待审批）
        self.mutes = {}            # gid -> 我被禁言的剩余秒数（-1 = 永久，0/缺失 = 没被禁言）
        self._mute_deadline = {}   # gid -> 单调时钟上的解禁时刻
        self.offline_count = 0     # 服务端替我留着的离线留言条数
        self.is_super = False      # 我是不是超级管理员（服务端下发）
        self.admin_data = {}       # 超管控制台数据（用户 / 群聊 / 封禁）
        self._avatar_req = {}      # 昵称小写 -> 上次索取头像的时间
        self.my_region = ''
        self.server_ip = ''        # 所连服务端自己的对外 IP（服务端下发）
        self.server_region = ''    # 所连服务端自己所在的城市
        self.server_region_known = False   # 服务端有没有下发过这个字段（老版本没有）
        self.server_region_state = ''      # pending / ok / unknown / off
        self.server_region_reason = ''
        self.server_port = self.port
        self.conv = CONV_ROOM
        self.stop = threading.Event()
        self.games = {}            # gid -> 最近一次棋局快照（界面用）
        self.my_gid = None         # 我正在下的那局

        self._pending_nick = None
        self._pending_password = None
        self.error_log = []       # 网络层异常留痕（界面会写进 client_error.log）
        self.on_error = None      # 回调：由界面挂上，用来落盘
        self.dead_reason = ''     # 掉线原因（界面提示用）
        self._session_lost = False
        self.last_alive = time.time()
        self._recv_dir = os.path.join(tempfile.gettempdir(), 'qiaoni_recv')
        self._files = {}          # 正在接收：fid -> {info, fh, path, got, total}
        self._local_files = {}    # 自己发出的文件：fid -> 本地路径
        self._local_order = []
        self.received = {}        # 已收完的文件：fid -> 本地路径（供界面反复渲染）
        self._file_meta = {}      # fid -> {name/kind/size/time}（落盘索引用）
        self.load_file_index()    # 上次收到的图片/文件：启动就认出来，不用重新下载

        self.channel = ReliableChannel(
            self.sock, self.server_addr, self.sid, key=None, enc_out=False,
            on_deliver=self._on_deliver, on_dead=self._on_dead,
            on_error=self._error, on_session_lost=self._on_session_lost,
            on_silent=self._on_silent,
        )
        self.channel.check_marker = True   # 服务端说「会话没了」时立刻重连
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        """看住两个网络线程：万一哪个死了，别的都白搭（界面还以为连着）。"""
        while not self.stop.is_set() and not self.channel._stop.is_set():
            time.sleep(1.0)
            # 睡这一秒里被主动停掉了（退出登录 / 重连时重建客户端）：收包线程这时
            # 本来就会正常结束，绝不能当成「线程死了」再拉起来，否则每次重连都会
            # 往 client_error.log 里写一条「收包线程已退出，正在重启」，看着像故障。
            if self.stop.is_set() or self.channel._stop.is_set():
                return
            try:
                if not self.recv_thread.is_alive():
                    self._error('收包线程已退出，正在重启')
                    self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
                    self.recv_thread.start()
                if not self.channel.sender_thread.is_alive() and not self.channel._stop.is_set():
                    self._error('发送线程已退出，正在重启')
                    self.channel.sender_thread = threading.Thread(
                        target=self.channel._sender_loop, daemon=True)
                    self.channel.sender_thread.start()
            except Exception:
                pass

    # ---------- 收包 ----------
    def _recv_loop(self):
        while not self.stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if self.stop.is_set():
                    break
                continue        # 单次网络错误不终止收包线程
            pkt = parse_packet(data)
            if not pkt or pkt['sid'] != self.sid:
                continue        # 会话 id 是 16 字节随机数，对不上就不是我们的包
            # 注意：这里**不再要求来源地址完全等于当初解析出的地址**。
            # 云服务器常常是多网卡 / 走 NAT，回包可能来自另一个 IP；家里路由器
            # 也会给 UDP 重新分配端口。死守旧地址的结果就是「单方向收不到包 →
            # 20 秒后判定掉线」，也就是用户看到的「经常突然断开」。
            # 安全性由 sid + AES-GCM 认证保证，不靠源地址。
            if addr != self.server_addr:
                self._follow_addr(addr)
            try:
                self.channel.handle_incoming(pkt)
            except Exception as e:
                self._error(f'处理入站报文异常：{e!r}\n{traceback.format_exc()}')

    def _follow_addr(self, addr):
        """对端地址变了（多网卡 / NAT 重绑）：跟着换，别把自己憋死。"""
        old = self.server_addr
        if isinstance(old, tuple) and isinstance(addr, tuple) and old[0] == addr[0] \
                and len(addr) > 1 and old[1] != addr[1]:
            # 同一个 IP 只换了端口（典型的 NAT 重绑）
            self.server_addr = addr
            self.channel.addr = addr
            self._error(f'对端端口变化 {old[1]} → {addr[1]}，已跟随')
        elif addr[0] != (old[0] if isinstance(old, tuple) else old):
            self.server_addr = addr
            self.channel.addr = addr
            self._error(f'对端地址变化 {old} → {addr}，已跟随')

    def _error(self, text):
        """把网络层的异常记下来（界面会读 client_error.log）。"""
        try:
            self.error_log.append(f'[{time.strftime("%H:%M:%S")}] {text}')
            if len(self.error_log) > 200:
                del self.error_log[:-200]
        except Exception:
            pass
        cb = getattr(self, 'on_error', None)
        if cb:
            try:
                cb(text)
            except Exception:
                pass

    def _on_deliver(self, payload):
        try:
            obj = decode_json(payload)
        except Exception:
            return
        t = obj.get('t')
        if t == 'challenge':
            self._on_challenge(obj)
        elif t == 'register_result':
            if obj.get('ok'):
                self.events.put(('register_ok', obj))
                if self._pending_nick:      # 注册成功后自动登录
                    self.login(self._pending_nick, self._pending_password or '')
            else:
                self.events.put(('register_err', obj.get('error') or '注册失败'))
        elif t == 'deny':
            self.denied = obj.get('reason', '未知原因')
            self.events.put(('deny', self.denied))
        elif t == 'welcome':
            self.connected = True
            self.me = obj.get('you', self.me)
            self.server_ip = obj.get('server_ip') or self.server_ip
            if 'server_region' in obj:
                self.server_region = obj.get('server_region') or ''
                self.server_region_known = True
                self.server_region_state = obj.get('server_region_state') or \
                    ('ok' if self.server_region else 'unknown')
                self.server_region_reason = obj.get('server_region_reason') or ''
            self.server_port = obj.get('server_port') or self.server_port
            self.offline_count = int(obj.get('offline') or 0)
            self.is_super = bool(obj.get('super'))
            self._absorb_users(obj.get('users', []))
            self._absorb_avatars(obj.get('avatars'))
            self.channel.enable_secure()
            self.events.put(('welcome', obj))
        elif t == 'social':
            self.social_ready = True      # 收到过社交数据，才能据此判断「是不是好友」
            self.friends = obj.get('friends', [])
            self.requests = obj.get('requests', [])
            self.groups = obj.get('groups', [])
            self.blocks = obj.get('blocks', [])
            self.invites = obj.get('invites', [])
            self.online = obj.get('online', []) or self.online
            for n, r in (obj.get('regions') or {}).items():
                if r:
                    self.regions[n] = r
            if self.me in self.regions:
                self.my_region = self.regions[self.me]
            self._absorb_avatars(obj.get('avatars'))
            if 'offline' in obj:
                self.offline_count = int(obj.get('offline') or 0)
            if not self.users and self.online:
                self.users = [{'nick': n} for n in self.online]
            self.events.put(('social', obj))
        elif t == 'history':
            self.events.put(('history', obj))
        elif t in ('chat', 'me', 'system', 'recall'):
            self.events.put((t, obj))
        elif t == 'presence':
            nick = obj.get('nick')
            if obj.get('online'):
                if nick not in self.online:
                    self.online.append(nick)
            elif nick in self.online:
                self.online.remove(nick)
            self.users = [{'nick': n} for n in self.online]
            self.events.put(('presence', obj))
        elif t == 'users':
            self._absorb_users(obj.get('list', []))
            self.events.put(('users', self.users))
        elif t == 'avatar':
            self._absorb_avatar(obj.get('nick'), obj.get('ver'))
            self.events.put(('avatar', obj))
        elif t == 'group_info':
            info = obj.get('info') or {}
            gid = str(info.get('gid') or '')
            if gid:
                self.group_infos[gid] = info
                self._absorb_my_mute(gid, info)
            self.events.put(('group_info', obj))
        elif t == 'muted':
            gid = str(obj.get('gid') or '')
            left = int(obj.get('left') or 0)
            if gid:
                self.mutes[gid] = -1 if (left == 0 and int(obj.get('minutes') or 0) == 0) \
                    else max(0, left)
                self._mute_deadline[gid] = time.monotonic() + max(0, left)
            self.events.put(('muted', obj))
        elif t == 'unmuted':
            gid = str(obj.get('gid') or '')
            self.mutes.pop(gid, None)
            self._mute_deadline.pop(gid, None)
            self.events.put(('unmuted', obj))
        elif t == 'kicked':
            gid = str(obj.get('gid') or '')
            self.group_infos.pop(gid, None)
            self.events.put(('kicked', obj))
        elif t == 'admin_data':
            self.admin_data = obj
            self.events.put(('admin_data', obj))
        elif t == 'banned':
            self.connected = False
            self.denied = obj.get('text') or '账号已被封禁'
            self.events.put(('banned', obj))
        elif t == 'server_info':
            # 服务端异步解析完自己的属地后补推的：客户端不用重登就能更新左下角
            self.server_ip = obj.get('server_ip') or self.server_ip
            if 'server_region' in obj:
                self.server_region = obj.get('server_region') or ''
                self.server_region_known = True
            self.server_region_state = obj.get('state') or self.server_region_state
            self.server_region_reason = obj.get('reason') or ''
            self.events.put(('server_info', obj))
        elif t == 'search_result':
            self.events.put(('search_result', obj))
        elif t == 'chess':
            self._absorb_chess(obj)
            self.events.put(('chess', obj))
        elif t == 'file_msg':
            self._handle_file_msg(obj)
        elif t == 'file_info':
            self._handle_file_info(obj)
        elif t == 'file_chunk':
            self._handle_file_chunk(obj)

    def _absorb_my_mute(self, gid, info):
        """从群资料里读出「我」的禁言状态（服务端是权威）。"""
        me = (self.me or '').strip().lower()
        for m in (info.get('members') or []):
            if str(m.get('nick') or '').strip().lower() != me:
                continue
            mute = int(m.get('mute') or 0)
            if mute:
                self.mutes[gid] = -1 if mute < 0 else mute
                self._mute_deadline[gid] = time.monotonic() + (0 if mute < 0 else mute)
            else:
                self.mutes.pop(gid, None)
                self._mute_deadline.pop(gid, None)
            return

    def my_mute(self, gid):
        """我在这个群里被禁言还剩多少秒：0 = 没被禁言，-1 = 永久。"""
        gid = str(gid)
        left = self.mutes.get(gid, 0)
        if left == 0:
            return 0
        if left < 0:
            return -1
        dl = self._mute_deadline.get(gid)
        if dl is None:
            return left
        remain = int(dl - time.monotonic())
        if remain <= 0:
            self.mutes.pop(gid, None)
            self._mute_deadline.pop(gid, None)
            return 0
        return remain

    def _absorb_avatars(self, mapping):
        """服务端下发的「昵称 → 头像版本号」。"""
        if not isinstance(mapping, dict):
            return
        for n, v in mapping.items():
            self._absorb_avatar(n, v)

    def _absorb_avatar(self, nick, ver):
        if not nick:
            return
        try:
            v = int(ver or 0)
        except (TypeError, ValueError):
            v = 0
        key = str(nick).strip().lower()
        if v > 0 and self.avatar_ver.get(key) != v:
            self.avatar_ver[key] = v
            self._avatar_req.pop(key, None)     # 换头像了，允许重新拉取

    def _absorb_users(self, users):
        """吸收服务端下发的在线列表（含 IP 属地、头像版本）。"""
        self.users = list(users or [])
        self.online = [u.get('nick') for u in self.users if u.get('nick')]
        for u in self.users:
            n, r = u.get('nick'), u.get('region')
            if n and r:
                self.regions[n] = r
            if n and u.get('avatar'):
                self._absorb_avatar(n, u.get('avatar'))
        if self.me and self.me in self.regions:
            self.my_region = self.regions[self.me]

    def region_of(self, nick):
        return self.regions.get(nick, '')

    def _on_challenge(self, obj):
        try:
            salt = base64.b64decode(obj.get('salt') or '')
            nonce = base64.b64decode(obj.get('nonce') or '')
        except Exception:
            self.events.put(('deny', '服务器认证数据异常'))
            return
        self.key = derive_key_salted(self._pending_password or '', salt)
        self.channel.key = self.key      # 用于解密随后的 welcome
        self.channel.send_json({'t': 'auth', 'proof': auth_proof(self.key, nonce)},
                               force_plain=True)

    def _on_silent(self, silent, seconds):
        """「暂时收不到包」/「恢复了」的通知。

        这不是掉线：链路抖动十几秒很常见，这里只让界面提示一下，同时记一笔日志。
        真正确认断了才会走 _on_dead。
        """
        if self.stop.is_set():
            return
        try:
            if silent:
                self._error(f'网络不稳：已经 {seconds:.0f} 秒没有收到服务器任何报文'
                            f'（在途 {len(self.channel.window)} 包，'
                            f'待发 {self.channel.send_queue.qsize()} 条）——'
                            f'继续重传/心跳，先不断开')
                self.events.put(('link', {'silent': True, 'seconds': seconds}))
            else:
                how = getattr(self.channel, 'last_silent_for', 0.0)
                self._error(f'网络已恢复（中断 {how:.0f} 秒，未断开、未重登）')
                self.events.put(('link', {'silent': False, 'seconds': seconds}))
        except Exception:
            pass

    def _on_dead(self):
        if self.stop.is_set():
            return
        if getattr(self, '_session_lost', False):
            return          # 已经按「会话失效」报过了，别再用超时口径报一遍
        ch = self.channel
        silent = time.monotonic() - ch.last_recv
        extra = ''
        if ch.starved_total > 2.0:
            extra = (f'；期间本机卡顿过 {ch.starved_total:.0f} 秒'
                     f'（最长一次 {ch.max_gap:.1f} 秒）')
        why = (f'与服务器失去连接（{silent:.0f} 秒没有收到任何报文'
               f'，在途 {len(ch.window)} 包，待发 {ch.send_queue.qsize()} 条{extra}）')
        self.dead_reason = why
        self.connected = False
        self._error(f'判定掉线：{why}；线程 recv={self.recv_thread.is_alive()} '
                    f'send={ch.sender_thread.is_alive()}')
        self.events.put(('disconnected', why))

    def _on_session_lost(self):
        """服务端明确说「这个会话不认识了」（多半是服务端重启过）。

        这种情况不用干等 20 秒超时，立刻告诉界面去重连。
        """
        if self.stop.is_set() or not self.connected:
            return
        self._session_lost = True
        self.connected = False
        self.dead_reason = '服务器表示这个会话已失效（通常是服务端重启过），正在重新登录'
        self._error(f'会话失效：{self.dead_reason}')
        self.events.put(('disconnected', self.dead_reason))
        try:
            self.channel._mark_dead()      # 停掉重传，让通道彻底安静下来
        except Exception:
            pass

    def health(self):
        """给界面看的连接体检结果（排查「突然断开」用）。"""
        ch = self.channel
        return {
            'connected': self.connected,
            'dead': ch.dead,
            'silent': time.monotonic() - ch.last_recv,
            'window': len(ch.window),
            'queued': ch.send_queue.qsize(),
            'rtt': ch.rtt,
            'recv_alive': self.recv_thread.is_alive(),
            'send_alive': ch.sender_thread.is_alive(),
            'addr': self.server_addr,
            'reason': self.dead_reason,
        }

    # ---------- 认证 ----------
    def login(self, nick, password):
        self._pending_nick = nick
        self._pending_password = password
        self.channel.send_json({'t': 'hello', 'nick': nick}, force_plain=True)

    def register(self, nick, password):
        self._pending_nick = nick
        self._pending_password = password
        self.channel.send_json({'t': 'register', 'nick': nick, 'password': password},
                               force_plain=True)

    # ---------- 会话发送 ----------
    def send_text(self, conv, text):
        kind = conv_kind(conv)
        if kind == 'friend':
            self.channel.send_json({'t': 'pm', 'to': str(conv)[2:], 'text': text})
        elif kind == 'group':
            self.channel.send_json({'t': 'group_msg', 'gid': str(conv)[2:], 'text': text})
        else:
            self.channel.send_json({'t': 'chat', 'text': text})

    def send_me(self, text):
        self.channel.send_json({'t': 'me', 'text': text})

    def open_conv(self, conv):
        self.conv = conv
        self.channel.send_json({'t': 'open', 'conv': conv})

    def request_list(self):
        self.channel.send_json({'t': 'list'})

    # ---------- 社交操作 ----------
    def add_friend(self, nick, msg=''):
        self.channel.send_json({'t': 'friend_add', 'nick': nick, 'msg': msg})

    def accept_friend(self, nick):
        self.channel.send_json({'t': 'friend_accept', 'nick': nick})

    def reject_friend(self, nick):
        self.channel.send_json({'t': 'friend_reject', 'nick': nick})

    def remove_friend(self, nick):
        self.channel.send_json({'t': 'friend_remove', 'nick': nick})

    def del_friend(self, nick):
        """删除好友（对方以后还能再申请加你）。"""
        self.channel.send_json({'t': 'friend_del', 'nick': nick})

    def block_friend(self, nick, on=True):
        """拉黑 / 取消拉黑：拉黑后对方不能给你发消息和好友申请。"""
        self.channel.send_json({'t': 'friend_block', 'nick': nick, 'on': bool(on)})

    def recall(self, conv, mid):
        """撤回一条消息（自己的 2 分钟内；群主/管理员撤普通成员不限时间）。"""
        self.channel.send_json({'t': 'recall', 'conv': conv, 'mid': mid})

    def group_invite(self, gid, nick):
        """拉好友进群（要管理员和被拉人双方同意）。"""
        self.channel.send_json({'t': 'group_invite', 'gid': str(gid), 'nick': nick})

    def group_invite_me(self, gid, nick, accept=True):
        """我是被拉的那个人，表态。"""
        self.channel.send_json({'t': 'group_invite_me', 'gid': str(gid), 'nick': nick,
                                'accept': bool(accept)})

    def group_invite_ok(self, gid, nick, accept=True):
        """我是群主/管理员，批准别人拉人进群。"""
        self.channel.send_json({'t': 'group_invite_ok', 'gid': str(gid), 'nick': nick,
                                'accept': bool(accept)})

    def create_group(self, name, members):
        self.channel.send_json({'t': 'group_create', 'name': name, 'members': list(members)})

    def group_add(self, gid, nick):
        self.channel.send_json({'t': 'group_add', 'gid': str(gid), 'nick': nick})

    def group_leave(self, gid):
        self.channel.send_json({'t': 'group_leave', 'gid': str(gid)})

    # ---------- 群资料 / 群管理 ----------
    def group_info(self, gid):
        self.channel.send_json({'t': 'group_info', 'gid': str(gid)})

    def group_announce(self, gid, text):
        self.channel.send_json({'t': 'group_announce', 'gid': str(gid), 'text': text})

    def group_admin(self, gid, nick, on=True):
        self.channel.send_json({'t': 'group_admin', 'gid': str(gid), 'nick': nick,
                                'on': bool(on)})

    def group_mute(self, gid, nick, minutes=0):
        self.channel.send_json({'t': 'group_mute', 'gid': str(gid), 'nick': nick,
                                'minutes': int(minutes)})

    def group_kick(self, gid, nick):
        self.channel.send_json({'t': 'group_kick', 'gid': str(gid), 'nick': nick})

    def group_join(self, no, msg=''):
        """用群号申请加群。"""
        self.channel.send_json({'t': 'group_join', 'no': str(no), 'msg': msg})

    def group_join_answer(self, gid, nick, accept=True):
        self.channel.send_json({'t': 'group_join_answer', 'gid': str(gid), 'nick': nick,
                                'accept': bool(accept)})

    def group_file_del(self, gid, fid):
        self.channel.send_json({'t': 'group_file_del', 'gid': str(gid), 'fid': fid})

    # ---------- 头像 ----------
    def send_avatar(self, path):
        """上传一张已经处理好的头像图片（客户端会先缩到 256×256）。"""
        return self.send_file(path, CONV_AVATAR)

    def request_avatar(self, nick, ver=None):
        who = (nick or '').strip()
        if not who or self.me == who:
            pass
        if not who:
            return
        if ver is None:
            ver = self.avatar_ver.get(who.lower(), 0)
        now = time.time()
        key = who.lower()
        if now - self._avatar_req.get(key, 0) < 3.0:
            return          # 3 秒内不重复要同一张，避免刷屏
        if self._avatar_req.get(key) is None and self.avatar_path(who):
            return
        self._avatar_req[key] = now
        try:
            self.channel.send_json({'t': 'avatar_get', 'nick': who, 'ver': ver})
        except Exception:
            pass

    def avatar_dir(self):
        d = os.path.join(self._recv_dir, 'avatars')
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = self._recv_dir
        return d

    def avatar_path(self, nick):
        """本地已缓存的头像文件路径（没有则返回 ''）。"""
        k = conv_filename((nick or '').strip().lower())
        ver = self.avatar_ver.get((nick or '').strip().lower(), 0)
        if ver <= 0:
            return ''
        path = os.path.join(self.avatar_dir(), f'{k}.{ver}.png')
        return path if os.path.isfile(path) else ''

    # ---------- 超级管理员 ----------
    def admin_get(self):
        self.channel.send_json({'t': 'admin_get'})

    def admin_ban(self, nick, minutes, reason=''):
        """minutes > 0 限时封号；0 = 永久；< 0 = 解封。"""
        self.channel.send_json({'t': 'admin_ban', 'nick': nick,
                                'minutes': int(minutes), 'reason': reason})

    def admin_unban(self, nick):
        self.channel.send_json({'t': 'admin_unban', 'nick': nick})

    def search_users(self, q):
        self.channel.send_json({'t': 'search', 'q': q})

    # ---------- 中国象棋 ----------
    def _absorb_chess(self, obj):
        """把服务端下发的棋局快照存起来（界面随时可以重新打开棋盘）。"""
        g = obj.get('game')
        if not isinstance(g, dict):
            return
        gid = g.get('gid')
        if not gid:
            return
        if self.me and gid in self.games:
            g = dict(g, my_color=self.games[gid].get('my_color'))
        self.games[gid] = g
        if self.me:
            if self.me == g.get('red'):
                g['my_color'] = 'r'
            elif self.me == g.get('black'):
                g['my_color'] = 'b'
            if g.get('my_color'):
                self.my_gid = gid
        if obj.get('act') in ('end',):
            self.my_gid = None
        if obj.get('act') == 'closed':
            self.games.pop(gid, None)
            if self.my_gid == gid:
                self.my_gid = None

    def chess_challenge(self, nick):
        self.channel.send_json({'t': 'chess', 'act': 'challenge', 'to': nick})

    def chess_accept(self, cid, color):
        self.channel.send_json({'t': 'chess', 'act': 'accept', 'cid': cid,
                                'color': 'r' if color == 'r' else 'b'})

    def chess_reject(self, cid):
        self.channel.send_json({'t': 'chess', 'act': 'reject', 'cid': cid})

    def chess_cancel(self, cid):
        self.channel.send_json({'t': 'chess', 'act': 'cancel', 'cid': cid})

    def chess_move(self, gid, fr, fc, tr, tc):
        self.channel.send_json({'t': 'chess', 'act': 'move', 'gid': str(gid),
                                'from': [int(fr), int(fc)], 'to': [int(tr), int(tc)]})

    def chess_resign(self, gid):
        self.channel.send_json({'t': 'chess', 'act': 'resign', 'gid': str(gid)})

    def chess_offer_draw(self, gid):
        self.channel.send_json({'t': 'chess', 'act': 'draw', 'gid': str(gid)})

    def chess_answer_draw(self, gid, accept):
        self.channel.send_json({'t': 'chess', 'act': 'draw_answer', 'gid': str(gid),
                                'accept': bool(accept)})

    def chess_request_undo(self, gid):
        self.channel.send_json({'t': 'chess', 'act': 'undo', 'gid': str(gid)})

    def chess_answer_undo(self, gid, accept):
        self.channel.send_json({'t': 'chess', 'act': 'undo_answer', 'gid': str(gid),
                                'accept': bool(accept)})

    def chess_state(self, gid):
        self.channel.send_json({'t': 'chess', 'act': 'state', 'gid': str(gid)})

    def chess_leave(self, gid):
        self.channel.send_json({'t': 'chess', 'act': 'leave', 'gid': str(gid)})

    # ---------- 文件（磁盘流式，不限制大小） ----------
    def send_file(self, path, conv=None):
        """流式分块发送文件到指定会话，返回 (fid, name, kind, size)。"""
        conv = conv or self.conv or CONV_ROOM
        size = os.path.getsize(path)
        if size <= 0:
            raise ValueError('文件为空')
        if size > MAX_FILE_SIZE:
            raise ValueError('文件超出可接受范围')
        name = os.path.basename(path)
        kind = file_kind(name)
        fid = os.urandom(8).hex()
        self._local_files[fid] = path
        self._local_order.append(fid)
        while len(self._local_order) > 5:
            self._local_files.pop(self._local_order.pop(0), None)

        self.channel.send_json({'t': 'file_begin', 'fid': fid, 'name': name,
                                'kind': kind, 'size': size, 'conv': conv})
        with open(path, 'rb') as f:
            i = 0
            while True:
                chunk = f.read(FILE_CHUNK_RAW)
                if not chunk:
                    break
                while self.channel.pending() > 256 and not self.stop.is_set():
                    time.sleep(0.01)
                if self.stop.is_set():
                    return fid, name, kind, size
                self.channel.send_json({'t': 'file_chunk', 'fid': fid, 'i': i,
                                        'data': base64.b64encode(chunk).decode('ascii')})
                i += 1
        self.channel.send_json({'t': 'file_end', 'fid': fid})
        return fid, name, kind, size

    def request_file(self, fid):
        self.channel.send_json({'t': 'file_get', 'fid': fid})

    def recv_dir(self):
        d = self._recv_dir
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = os.path.dirname(self._recv_dir) or '.'
        return d

    def _recv_path(self, fid, name):
        base = os.path.basename(str(name or 'file')) or 'file'
        base = ''.join(c for c in base if c not in '\\/:*?"<>|') or 'file'
        return os.path.join(self.recv_dir(), f'{(fid or "f")[:8]}_{base}')

    # ---------- 本地文件缓存 ----------
    def _file_index_path(self):
        return os.path.join(self._recv_dir, 'index.json')

    def load_file_index(self):
        """把上次收到的文件索引读回内存。

        这样切会话 / 重启客户端都不用再从服务器把图片重新下一遍 —— 图片本来
        就在本机，界面每次重绘都要等一遍下载加解码，看起来就是「很卡」。
        """
        try:
            with open(self._file_index_path(), 'r', encoding='utf-8-sig') as f:
                data = json.load(f) or {}
        except Exception:
            return 0
        n = 0
        for fid, rec in list(data.items()):
            try:
                p = rec.get('path') if isinstance(rec, dict) else rec
            except Exception:
                p = None
            if p and os.path.isfile(p):
                self.received[str(fid)] = p
                if isinstance(rec, dict):
                    self._file_meta[str(fid)] = {k: v for k, v in rec.items()
                                                 if k != 'path'}
                n += 1
        if n:
            self._error(f'本地文件缓存：{n} 个文件可以直接用（不用重新下载）')
        return n

    def save_file_index(self):
        """把「收到过哪些文件」落盘（只留最近的一批，且文件还在的）。"""
        try:
            items = list(self.received.items())[-FILE_INDEX_MAX:]
            data = {}
            for fid, p in items:
                if p and os.path.isfile(p):
                    rec = dict(self._file_meta.get(fid) or {})
                    rec['path'] = p
                    data[str(fid)] = rec
            d = os.path.dirname(self._file_index_path())
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self._file_index_path() + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self._file_index_path())
            return True
        except Exception:
            return False

    def _known_file(self, obj):
        """本地已经有这个文件了吗（查缓存 + 按 fid 算出来的固定路径）。"""
        fid = str(obj.get('fid') or '')
        if not fid:
            return None
        p = self.received.get(fid) or self._local_files.get(fid)
        if p and os.path.isfile(p):
            return p
        try:
            cand = self._recv_path(fid, obj.get('name'))
        except Exception:
            return None
        if os.path.isfile(cand):
            self.received[fid] = cand
            return cand
        return None

    def _handle_file_msg(self, obj):
        self.events.put(('file_msg', obj))
        fid = obj.get('fid')
        # 本地有的直接用（含历史消息）：这样切会话时图片立刻就在，不用等下载
        local = self._known_file(obj)
        if local:
            self.received[fid] = local
            self.events.put(('file_data', {'fid': fid, 'info': obj, 'path': local}))
            return
        if obj.get('history'):
            return  # 历史文件、本地又没缓存：等用户点一下再拉
        if obj.get('from') == self.me and fid in self._local_files:
            self.events.put(('file_data', {'fid': fid, 'info': obj,
                                           'path': self._local_files[fid]}))
        else:
            self.request_file(fid)

    def _handle_file_info(self, obj):
        fid = obj.get('fid')
        if str(fid or '').startswith(AVATAR_FID_PREFIX):
            path = self._avatar_recv_path(fid)
        else:
            path = self._recv_path(fid, obj.get('name'))
        try:
            fh = open(path, 'wb')
        except OSError:
            fh = None
        self._files[fid] = {'info': obj, 'got': 0, 'total': int(obj.get('total') or 0),
                            'path': path, 'fh': fh,
                            'avatar': str(fid or '').startswith(AVATAR_FID_PREFIX)}

    def _avatar_recv_path(self, fid):
        """头像下载的落地路径：avatars/<昵称>.<版本>.png。"""
        body = str(fid)[len(AVATAR_FID_PREFIX):]
        key, _sep, ver = body.partition(':')
        return os.path.join(self.avatar_dir(), f'{conv_filename(key)}.{ver or 0}.png')

    def _handle_file_chunk(self, obj):
        fid = obj.get('fid')
        rec = self._files.get(fid)
        if rec is None:
            self._handle_file_info({'fid': fid, 'name': str(fid) + '.bin',
                                    'total': obj.get('total')})
            rec = self._files.get(fid)
            if rec is None:
                return
        try:
            data = base64.b64decode(obj.get('data') or '')
        except Exception:
            return
        if rec['fh'] is not None:
            try:
                rec['fh'].write(data)
            except OSError:
                pass
        rec['got'] += 1
        if rec['total'] and rec['got'] >= rec['total']:
            try:
                if rec['fh'] is not None:
                    rec['fh'].close()
            except Exception:
                pass
            if rec.get('avatar'):
                nick = (rec['info'].get('from') or '').strip()
                self.received[fid] = rec['path']
                del self._files[fid]
                self.events.put(('avatar_data', {'nick': nick, 'path': rec['path'],
                                                 'fid': fid}))
                return
            self.events.put(('file_data', {'fid': fid, 'info': rec['info'], 'path': rec['path']}))
            self.received[fid] = rec['path']
            info = rec['info'] or {}
            self._file_meta[fid] = {'name': info.get('name', ''),
                                    'kind': info.get('kind', 'file'),
                                    'size': info.get('size', 0),
                                    'time': info.get('time', 0)}
            del self._files[fid]
            self.save_file_index()      # 落盘：下次切会话/重启直接读本地，不再下载

    # ---------- 工具 ----------
    @property
    def rtt(self):
        return self.channel.rtt

    def wait_event(self, etype, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = self.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if ev[0] == etype:
                return ev
        return None

    def disconnect(self):
        # 未登录也发一次 bye，让服务端立即回收半开连接
        try:
            self.channel.send_json({'t': 'bye'})
            time.sleep(0.1)
        except Exception:
            pass
        self.stop.set()
        self.channel.close()
        try:
            self.sock.close()
        except OSError:
            pass
