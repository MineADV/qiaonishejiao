"""悄匿社交 —— 服务端。

- 账号体系：昵称全服唯一，注册/登录，挑战-应答认证（密码不上网）
- 会话：公共大厅 / 好友私聊 / 群聊，各自独立历史（群/私聊历史落盘，重启不丢）
- 头像：图片存在服务端 avatars/ 目录，所有客户端按版本号按需拉取
- 文件：按会话收发，服务端磁盘流式缓存；群里的文件同时进「群文件」
- 离线留言：好友不在线时消息先存服务端，对方下次登录一次性送达
- 群管理：群号加群申请、群公告、群文件、管理员、禁言、移出成员
- 象棋：大厅内约战，服务端做裁判（合法性 / 绝杀 / 困毙都由服务端判定）
"""
import argparse
import base64
import hmac
import json
import os
import queue
import secrets
import socket
import sys
import tempfile
import threading
import time
from collections import deque

from chat_common import (
    valid_nick, nick_error, valid_text, now_ts, decode_json, parse_packet,
    parse_mentions, file_kind, human_size, tune_udp_socket, auth_proof,
    CONV_ROOM, CONV_AVATAR, conv_user, conv_group, conv_kind, conv_filename,
    MAX_HISTORY, MAX_CONV_HISTORY, MAX_CLIENTS, MAX_PER_IP, MAX_PENDING, AUTH_TIMEOUT,
    MAX_FILE_SIZE, FILE_CHUNK_RAW, FILE_CACHE_COUNT, FILE_CACHE_BYTES,
    AVATAR_MAX, AVATAR_FID_PREFIX, GROUP_ANNOUNCE_MAX, GROUP_HISTORY_ON_JOIN,
    HISTORY_KEEP, MAX_GROUP_MEMBERS, RECALL_WINDOW, new_mid,
)
from chat_net import ReliableChannel
from chat_social import Social, group_no, parse_group_no
from chat_geo import (own_region, region_for, clear_ip, failed_reason, set_custom_api,
                      set_overrides, set_override, overrides as geo_overrides,
                      probe as geo_probe, format_region, short_name, UNKNOWN,
                      votes_text as geo_votes)
from chat_chess import ChessGame, SIDE_RED, SIDE_BLACK, side_name
APP_NAME = '悄匿社交'

CHALLENGE_TTL = 60.0      # 约战邀请多久没人理就作废（秒）
MAX_GAMES = 200           # 服务端同时存在的棋局上限


class ClientSession:
    """一个已认证 / 正在认证的客户端连接。"""

    def __init__(self, server, sid, addr):
        self.server = server
        self.sid = sid
        self.addr = addr
        self.nick = None
        self.key_lower = None
        self.region = '未知'        # IP 属地（由服务端按来源地址判定，客户端无法伪造）
        self.authenticated = False
        self.state = 'new'          # new -> challenged -> ready
        self.pending_nick = None
        self.nonce = None
        self.upload = None
        self.counted = False        # 是否已计入单 IP 已登录连接数
        self.game_id = None         # 正在进行的棋局 id
        self.created = time.monotonic()
        self.inbox = queue.Queue()
        self.stop_flag = threading.Event()
        self.channel = ReliableChannel(
            server.sock, addr, sid, key=None, enc_out=False,
            on_deliver=self.inbox.put,
            on_dead=lambda: server.drop(self.sid, f'{self.nick or "未知用户"} 离线了（超时）'),
            on_silent=self._on_silent,
        )
        self.channel.send_marker = True    # 未登录的会话用心跳标记告诉对方「会话没了」
        self.silent = False                # 对端暂时收不到（还没判死）
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _on_silent(self, silent, seconds):
        """对端十几秒没动静：记一笔就行，先别踢人。

        以前服务端 20 秒收不到包就把会话丢掉，客户端那边（尤其跨洋链路）可能
        只是抖了一下 —— 会话一丢，对面回来就得重新登录，用户看到的就是
        「莫名其妙断开重连」。现在服务端也按同一套阈值：先观察，超时才清理。
        """
        self.silent = bool(silent)
        try:
            if silent:
                self.server.log(f'… {self.nick or "（未登录）"} 已 {seconds:.0f} 秒'
                                f'没有回应（先保留会话，继续等待）')
            else:
                self.server.log(f'✓ {self.nick or "（未登录）"} 恢复通信'
                                f'（中断 {getattr(self.channel, "last_silent_for", 0):.0f} 秒）')
        except Exception:
            pass

    # ---------- 应用层处理线程 ----------
    def _serve(self):
        while not self.channel.dead and not self.server.stop.is_set() and not self.stop_flag.is_set():
            # 未登录连接超时清理，避免半开连接堆积
            if not self.authenticated and time.monotonic() - self.created > AUTH_TIMEOUT:
                self._notice('登录超时，请重新连接')
                break
            try:
                payload = self.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._handle(payload)
            except Exception:
                pass
        self.server.drop(self.sid, f'{self.nick or "未知用户"} 离开')

    def _send(self, obj, plain=False):
        try:
            self.channel.send_json(obj, force_plain=plain)
        except Exception:
            pass

    def _notice(self, text, conv=None, toast=False):
        """给这个连接发一条系统提示。

        **没有归属会话的提示一律不带 conv**（不能默认塞给公共大厅！）。
        以前这里把 conv 默认成「公共大厅」，于是「头像已更新」「对方不在线，
        已离线留存」这类跟大厅毫无关系的回执，都被客户端当成大厅消息存了下来
        —— 用户切回大厅就看到一堆莫名其妙的内容，也就是他报的
        「聊天内容串到别的会话里」。现在这类提示只做浮层提醒，不进任何聊天记录。

        带 conv 的（群里的禁言 / 公告 / 拉人等）照旧落到那个会话里；
        toast=True 表示还要立刻弹一条浮层（不依赖用户正好在那个会话里）。
        """
        msg = {'t': 'system', 'kind': 'notice', 'text': text, 'time': now_ts(),
               'conv': conv or ''}
        if toast or not conv:
            # 没有归属会话的提示必须弹出来，否则用户什么反馈都看不到
            msg['toast'] = True
        self._send(msg)

    def _handle(self, payload):
        try:
            obj = decode_json(payload)
        except Exception:
            return
        t = obj.get('t')

        # ---- 认证阶段 ----
        if t == 'register':
            self._handle_register(obj)
            return
        if t == 'hello':
            self._handle_hello(obj)
            return
        if t == 'auth':
            self._handle_auth(obj)
            return
        if t == 'bye':                 # 未登录也可以主动告别，便于服务端立即回收
            self.server.drop(self.sid, f'{self.nick} 离开了' if self.authenticated else None)
            return
        if not self.authenticated:
            return

        # ---- 会话 / 社交 ----
        if t == 'chat':
            self.server.room_message(self, (obj.get('text') or '').strip(), 'chat')
        elif t == 'me':
            self.server.room_message(self, (obj.get('text') or '').strip(), 'me')
        elif t == 'pm':
            self.server.friend_message(self, (obj.get('to') or '').strip(), (obj.get('text') or '').strip())
        elif t == 'group_msg':
            self.server.group_message(self, str(obj.get('gid') or ''), (obj.get('text') or '').strip())
        elif t == 'open':
            self.server.send_history(self, str(obj.get('conv') or CONV_ROOM))
        elif t == 'friend_add':
            self.server.friend_add(self, (obj.get('nick') or '').strip(),
                                   (obj.get('msg') or '').strip())
        elif t == 'friend_accept':
            self.server.friend_accept(self, (obj.get('nick') or '').strip())
        elif t == 'friend_reject':
            self.server.friend_reject(self, (obj.get('nick') or '').strip())
        elif t == 'friend_remove':
            self.server.friend_remove(self, (obj.get('nick') or '').strip())
        elif t == 'group_create':
            self.server.group_create(self, obj.get('name'), obj.get('members') or [])
        elif t == 'group_add':
            self.server.group_add(self, str(obj.get('gid') or ''), (obj.get('nick') or '').strip())
        elif t == 'group_leave':
            self.server.group_leave(self, str(obj.get('gid') or ''))
        # ---- 群资料 / 群管理 ----
        elif t == 'group_info':
            self.server.group_info_get(self, str(obj.get('gid') or ''))
        elif t == 'group_announce':
            self.server.group_announce(self, str(obj.get('gid') or ''),
                                       str(obj.get('text') or ''))
        elif t == 'group_admin':
            self.server.group_admin(self, str(obj.get('gid') or ''),
                                    (obj.get('nick') or '').strip(), bool(obj.get('on')))
        elif t == 'group_mute':
            try:
                minutes = int(obj.get('minutes'))
            except (TypeError, ValueError):
                minutes = -1
            self.server.group_mute(self, str(obj.get('gid') or ''),
                                   (obj.get('nick') or '').strip(), minutes)
        elif t == 'group_kick':
            self.server.group_kick(self, str(obj.get('gid') or ''),
                                   (obj.get('nick') or '').strip())
        elif t == 'group_join':
            self.server.group_join(self, str(obj.get('no') or ''),
                                   (obj.get('msg') or '').strip())
        elif t == 'group_join_answer':
            self.server.group_join_answer(self, str(obj.get('gid') or ''),
                                          (obj.get('nick') or '').strip(),
                                          bool(obj.get('accept')))
        elif t == 'group_file_del':
            self.server.group_file_del(self, str(obj.get('gid') or ''),
                                       str(obj.get('fid') or ''))
        # ---- 撤回 / 好友管理 ----
        elif t == 'recall':
            self.server.recall(self, str(obj.get('conv') or ''), str(obj.get('mid') or ''))
        elif t == 'friend_del':
            self.server.friend_del(self, (obj.get('nick') or '').strip())
        elif t == 'friend_block':
            self.server.friend_block(self, (obj.get('nick') or '').strip(),
                                     bool(obj.get('on', True)))
        elif t == 'group_invite':
            self.server.group_invite(self, str(obj.get('gid') or ''),
                                     (obj.get('nick') or '').strip())
        elif t == 'group_invite_me':
            self.server.group_invite_answer(self, str(obj.get('gid') or ''),
                                            (obj.get('nick') or '').strip(),
                                            bool(obj.get('accept')))
        elif t == 'group_invite_ok':
            self.server.group_invite_admin(self, str(obj.get('gid') or ''),
                                           (obj.get('nick') or '').strip(),
                                           bool(obj.get('accept')))
        # ---- 头像 ----
        elif t == 'avatar_get':
            self.server.avatar_get(self, (obj.get('nick') or '').strip(),
                                   obj.get('ver'))
        # ---- 超级管理员 ----
        elif t == 'admin_get':
            self.server.admin_get(self)
        elif t == 'admin_ban':
            try:
                minutes = int(obj.get('minutes'))
            except (TypeError, ValueError):
                minutes = 0
            self.server.admin_ban(self, (obj.get('nick') or '').strip(), minutes,
                                  str(obj.get('reason') or ''))
        elif t == 'admin_unban':
            self.server.admin_ban(self, (obj.get('nick') or '').strip(), -1)
        elif t == 'search':
            self.server.search_users(self, (obj.get('q') or '').strip())
        elif t == 'chess':
            self.server.chess(self, obj)
        elif t == 'list':
            self._send({'t': 'users', 'list': self.server.user_list()})
        # ---- 文件 ----
        elif t == 'file_begin':
            self.server.begin_upload(self, obj)
        elif t == 'file_chunk':
            self.server.push_chunk(self, obj)
        elif t == 'file_end':
            self.server.finish_upload(self, obj)
        elif t == 'file_get':
            self.server.send_file(self, str(obj.get('fid') or ''))
        elif t == 'bye':
            self.server.drop(self.sid, f'{self.nick} 离开了')

    # ---------- 注册 ----------
    def _handle_register(self, obj):
        if self.authenticated:
            return
        nick = (obj.get('nick') or '').strip()
        password = obj.get('password') or ''
        ok, err = self.server.social.register(nick, password)
        if ok:
            self.server.log(f'＋ 新账号「{nick}」注册    （{self.server.counts()}）')
        self._send({'t': 'register_result', 'ok': ok, 'error': err or ''}, plain=True)

    # ---------- 登录：hello → challenge ----------
    def _handle_hello(self, obj):
        if self.authenticated:
            return
        nick = (obj.get('nick') or '').strip()
        if not valid_nick(nick):
            self._deny(nick_error(nick) or '昵称不合法')
            return
        acct = self.server.social.get(nick)
        if not acct:
            self._deny('该昵称尚未注册，请先注册账号')
            return
        # 封号检查放在发 challenge 之前：被封的账号连密码都不用验
        if self.server.social.is_banned(acct['nick']):
            self._deny(self.server.ban_text(acct['nick']))
            return
        self.pending_nick = acct['nick']
        self.nonce = secrets.token_bytes(16)
        self.state = 'challenged'
        self._send({'t': 'challenge', 'nick': acct['nick'], 'salt': acct['salt'],
                    'nonce': base64.b64encode(self.nonce).decode()}, plain=True)

    def _handle_auth(self, obj):
        if self.authenticated or self.state != 'challenged' or not self.pending_nick:
            self._deny('认证流程异常，请重新登录')
            return
        key = self.server.social.account_key(self.pending_nick)
        if not key:
            self._deny('账号数据异常')
            return
        expected = auth_proof(key, self.nonce)
        if not hmac.compare_digest(str(obj.get('proof') or ''), expected):
            self.state = 'new'
            self._deny('密码错误')
            return
        self.server.complete_login(self, self.pending_nick, key)

    def _deny(self, reason):
        self._send({'t': 'deny', 'reason': reason}, plain=True)
        threading.Timer(0.6, lambda: self.server.drop(self.sid, None)).start()


class Server:
    REGION_RETRY_WAITS = (12.0, 40.0, 120.0)   # 属地没查到时，隔多久重试（测试里会调小）

    def __init__(self, host='0.0.0.0', port=26000, room='公共大厅', data_path=None,
                 geo_lookup=True, public_ip='', super_admins=None):
        self.host = host
        self.port = port
        self.room = room
        self.geo_lookup = geo_lookup      # 公网 IP 是否调用在线接口解析省市
        try:
            src = (cfg.get('geo_sources') if isinstance(cfg, dict) else '')
            if src:
                chat_geo.set_sources(src)
        except Exception:
            pass
        self.public_ip = (public_ip or '').strip()   # 可在配置里写死，省一次联网
        self.server_ip = self.public_ip
        self.server_region = ''           # 服务端自己的 IP 属地（异步解析）
        self.server_region_state = 'pending'   # pending / ok / unknown / off
        self.server_region_reason = ''
        # 超级管理员：配置里写死的昵称（小写）。可以在控制台用 admin add/del 增删。
        self.super_admins = {str(n).strip().lower() for n in (super_admins or []) if str(n).strip()}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tune_udp_socket(self.sock)
        self.sock.bind((host, port))
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]

        base = os.path.dirname(os.path.abspath(__file__))
        self.data_path = data_path or os.path.join(base, 'social_data.json')
        self.social = Social(self.data_path)
        self.data_dir = os.path.dirname(os.path.abspath(self.data_path)) or base
        self.avatar_dir_path = os.path.join(self.data_dir, 'avatars')
        self.history_dir = os.path.join(self.data_dir, 'history')

        self.clients = {}
        self.history = {CONV_ROOM: deque(maxlen=MAX_HISTORY)}   # conv -> deque
        self.files = {}          # fid -> {conv, from, name, kind, size, time, path}
        self.file_order = deque()
        self.games = {}          # gid -> ChessGame（服务端权威棋局）
        self.challenges = {}     # cid -> 约战邀请
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.recv_thread = None
        self._ip_counts = {}
        self._log_lock = threading.Lock()   # 控制台日志串行化，避免多线程交错
        self.load_history()

    def start(self):
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        threading.Thread(target=self._resolve_self, daemon=True).start()
    def _resolve_self(self):
        """解析「服务端自己在哪」，放到后台线程，绝不拖慢启动和登录。

        客户端登录后会看到自己连的是哪台服务器、那台服务器在哪个城市。
        注意这里是**异步**的：客户端经常在解析完成前就登录了，所以解析完要
        主动推一条 server_info 给所有在线客户端，不然它们会一直显示
        「解析中…／属地未知」直到重新登录。
        """
        reason = ''
        try:
            if self.public_ip:
                self.server_ip = self.public_ip
                text = region_for(self.public_ip, self.geo_lookup)
                self.server_region = '' if text in ('公网', '内网', '本机', UNKNOWN) else text
                if not self.server_region:
                    reason = failed_reason()
            else:
                self.server_ip, self.server_region = own_region(online=self.geo_lookup)
                if not self.server_ip:
                    reason = '取不到本机对外 IP（回显接口都不通），请检查服务器能否访问外网'
                elif not self.server_region:
                    reason = failed_reason()
        except Exception as e:
            reason = f'{type(e).__name__}: {e}'
        if not self.geo_lookup:
            self.server_region_state = 'off'
            self.server_region_reason = '配置里关掉了联网属地解析（geo_lookup=false）'
        elif self.server_region:
            self.server_region_state = 'ok'
            self.server_region_reason = ''
        else:
            self.server_region_state = 'unknown'
            self.server_region_reason = reason or '解析失败'
        if self.server_ip:
            where = f'{self.server_ip}（{self.server_region}）' if self.server_region \
                else self.server_ip
            self.log(f'◆ 本机对外地址：{where}')
        if self.server_region_state == 'unknown':
            self.log(f'⚠ 本机属地没解析出来（{self.server_region_reason}）；'
                     f'客户端左下角会显示「服务器 属地未知」。'
                     f'可用 `geo self` 复查，或把 geo_lookup 关掉避免等待')
        # 解析是异步的：登录早的客户端还在显示「解析中」，补推一条
        try:
            self.push_server_info()
        except Exception:
            pass

    def server_info(self):
        return {'t': 'server_info',
                'server_ip': self.server_ip,
                'server_region': self.server_region,
                'state': self.server_region_state,
                'reason': self.server_region_reason,
                'port': self.port}

    def push_server_info(self):
        msg = self.server_info()
        for cs in self.sessions():
            if cs.authenticated:
                cs._send(msg)

    # ---------- 超级管理员 ----------
    def is_super(self, nick):
        return (nick or '').strip().lower() in self.super_admins

    def add_super(self, nick):
        n = self.social.display(nick) if self.social.exists(nick) else (nick or '').strip()
        if not n:
            return False, '请填写昵称'
        self.super_admins.add(n.lower())
        return True, n

    def del_super(self, nick):
        k = (nick or '').strip().lower()
        if k not in self.super_admins:
            return False, '该昵称不是超级管理员'
        self.super_admins.discard(k)
        return True, ''

    def admin_payload(self):
        """给超级管理员面板用的全量数据。"""
        return {
            't': 'admin_data',
            'users': self.social.all_users(region_of=self.region_map()),
            'groups': self.social.all_groups(),
            'bans': self.social.ban_list(),
            'online': len(self.online_nicks()),
            'time': now_ts(),
        }

    def push_admin(self, only=None):
        """把面板数据推给所有在线的超级管理员。"""
        msg = self.admin_payload()
        for cs in self.sessions():
            if cs.authenticated and self.is_super(cs.nick) and (only is None or cs is only):
                cs._send(msg)

    def admin_get(self, cs):
        if not self.is_super(cs.nick):
            cs._notice('你不是超级管理员，无权查看管理数据')
            return
        cs._send(self.admin_payload())

    def admin_ban(self, cs, nick, minutes, reason=''):
        if not self.is_super(cs.nick):
            cs._notice('只有超级管理员可以封号')
            return
        target = self.social.display(nick)
        if not self.social.exists(target):
            cs._notice('该用户不存在')
            return
        if self.is_super(target):
            cs._notice('不能封禁超级管理员')
            return
        ok, err = self.social.set_ban(target, minutes, reason, by=cs.nick)
        if not ok:
            cs._notice(err)
            return
        m = int(minutes)
        if m < 0:
            cs._notice(f'已解封「{target}」')
            self.log(f'⚑ {cs.nick} 解封了 {target}')
        else:
            how = '永久封禁' if m == 0 else f'封禁 {m} 分钟'
            tail = f'，理由：{reason}' if (reason or '').strip() else ''
            cs._notice(f'已{how}「{target}」{tail}')
            self.log(f'⚑ {cs.nick} {how} {target}{tail}')
            # 在线的话立刻踢下线（先明确告诉客户端「你被封了」，别让它以为是掉线）
            tgt = self.session_of(target)
            if tgt is not None:
                text = self.ban_text(target)
                tgt._send({'t': 'banned', 'nick': target, 'until': self.social.ban_info(target)[1],
                           'reason': self.social.ban_info(target)[2], 'text': text})
                tgt._notice(text)
                threading.Timer(0.8, lambda s=tgt.sid: self.drop(s, None)).start()
        self.push_admin()

    def ban_text(self, nick):
        """被封禁的人登录/被踢时看到的说明。"""
        on, until, reason = self.social.ban_info(nick)
        if not on:
            return ''
        if until:
            left = max(1, int((until - now_ts()) // 60) + 1)
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(until))
            text = f'你的账号已被封禁（{when} 到期，约 {left} 分钟）'
        else:
            text = '你的账号已被永久封禁'
        if reason:
            text += f'。理由：{reason}'
        text += '。如有疑问请联系管理员。'
        return text

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
                continue        # 单次网络错误不能终止收包线程
            pkt = parse_packet(data)
            if not pkt:
                continue
            sid = pkt['sid']
            with self.lock:
                cs = self.clients.get(sid)
                if cs is None:
                    if len(self.clients) >= MAX_CLIENTS:
                        continue
                    pending = sum(1 for c in self.clients.values() if not c.authenticated)
                    if pending >= MAX_PENDING:
                        continue
                    cs = ClientSession(self, sid, addr)
                    self.clients[sid] = cs
                fresh = cs.addr != addr
            if fresh:
                self._follow_client_addr(cs, addr)
            try:
                cs.channel.handle_incoming(pkt)
            except Exception:
                pass    # 单个报文异常不能拖垮整个收包线程

    def _follow_client_addr(self, cs, addr):
        """客户端换了来源地址（NAT 重绑 / 多网卡 / 换网络）：跟着改。

        不跟的话，回包还发去旧地址，客户端就再也收不到东西 —— 表现就是
        「用着用着突然显示已断开」。安全性由会话 id（16 字节随机）+ AES-GCM
        认证保证，和源地址无关。
        """
        old = cs.addr
        cs.addr = addr
        cs.channel.addr = addr
        if old and addr and old[0] != addr[0]:
            with self.lock:
                k = addr[0]
                self._ip_counts[k] = self._ip_counts.get(k, 0) + 1
                if old[0] in self._ip_counts and self._ip_counts[old[0]] > 0:
                    self._ip_counts[old[0]] -= 1
        try:
            self.log(f'↺ {cs.nick or "（未登录）"} 的来源地址变为 {addr[0]}:{addr[1]}')
        except Exception:
            pass

    # ---------- 在线表 ----------
    def sessions(self):
        with self.lock:
            return list(self.clients.values())

    def online_nicks(self):
        return [cs.nick for cs in self.sessions() if cs.authenticated]

    def user_list(self):
        return [{'nick': cs.nick, 'region': cs.region,
                 'avatar': self.social.avatar_ver(cs.nick)}
                for cs in self.sessions() if cs.authenticated]

    def region_map(self):
        """昵称 → 属地，供客户端在成员列表里展示。"""
        return {cs.nick: cs.region for cs in self.sessions() if cs.authenticated}

    def avatar_map(self):
        """昵称 → 头像版本号（有头像的才出现）。"""
        return self.social.avatar_map()

    # ---------- 控制台动态日志 ----------
    def log(self, msg):
        """实时打印一条带时间戳的日志（账号/群组/上下线变动都会走这里）。"""
        try:
            with self._log_lock:
                print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)
        except Exception:
            pass

    def counts(self):
        """当前数据快照：账号 / 群组 / 在线，用于每条日志后面附带最新数字。"""
        st = self.social.stats()
        return f'账号 {st["accounts"]} · 群组 {st["groups"]} · 在线 {len(self.user_list())}'

    def session_of(self, nick):
        k = (nick or '').strip().lower()
        for cs in self.sessions():
            if cs.authenticated and cs.key_lower == k:
                return cs
        return None

    def broadcast(self, msg, exclude_sid=None, only=None):
        targets = [cs for cs in self.sessions()
                   if cs.authenticated and cs.sid != exclude_sid
                   and (only is None or cs.key_lower in only)]
        for cs in targets:
            cs._send(msg)

    def push_users(self):
        self.broadcast({'t': 'users', 'list': self.user_list()})

    # ---------- 历史 ----------
    def hist_of(self, conv):
        with self.lock:
            d = self.history.get(conv)
            if d is None:
                cap = MAX_HISTORY if conv == CONV_ROOM else MAX_CONV_HISTORY
                d = deque(maxlen=cap)
                self.history[conv] = d
            return d

    def _hist_path(self, conv):
        return os.path.join(self.history_dir, conv_filename(conv) + '.jsonl')

    def add_history(self, conv, msg):
        # 每条消息发一个唯一编号：撤回、引用、定位都靠它。放在这里是因为所有
        # 消息（大厅/私聊/群聊/文件/离线留言）都要经过这一步，先编号再广播，
        # 双方拿到的 mid 就是同一个。
        try:
            if isinstance(msg, dict) and not msg.get('mid'):
                msg['mid'] = new_mid()
        except Exception:
            pass
        self.hist_of(conv).append(msg)
        self._persist_history(conv, msg)

    def _persist_recall(self, conv, mid):
        """撤回也写进历史文件（一行记录），重启后照样是撤回过状态。"""
        try:
            os.makedirs(self.history_dir, exist_ok=True)
            path = self._hist_path(conv)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'t': 'recall', 'mid': str(mid),
                                    'conv': conv, 'time': now_ts()},
                                   ensure_ascii=False) + '\n')
        except Exception:
            pass

    def _persist_history(self, conv, msg):
        """每条消息追加一行 JSONL：重启后群/私聊记录还在，新成员也能看到入群前的消息。"""
        try:
            os.makedirs(self.history_dir, exist_ok=True)
            path = self._hist_path(conv)
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')
            self._hist_lines[path] = self._hist_lines.get(path, 0) + 1
            if self._hist_lines[path] > HISTORY_KEEP * 2:
                self._compact_history(conv)
        except Exception:
            pass

    def _compact_history(self, conv):
        """文件太长了就重写成最近 HISTORY_KEEP 条。"""
        try:
            path = self._hist_path(conv)
            keep = list(self.hist_of(conv))[-HISTORY_KEEP:]
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                for m in keep:
                    f.write(json.dumps(m, ensure_ascii=False) + '\n')
            os.replace(tmp, path)
            self._hist_lines[path] = len(keep)
        except Exception:
            pass

    def load_history(self):
        """启动时把落盘的历史读回内存。"""
        self._hist_lines = {}
        try:
            names = os.listdir(self.history_dir)
        except OSError:
            return
        for fn in names:
            if not fn.endswith('.jsonl'):
                continue
            path = os.path.join(self.history_dir, fn)
            items = []
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            items.append(json.loads(line))
                        except Exception:
                            continue
            except OSError:
                continue
            self._hist_lines[path] = len(items)
            if not items:
                continue
            conv = items[-1].get('conv') or fn[:-6].replace('_', ':', 1)
            if conv == 'room_' or not conv:
                conv = CONV_ROOM
            cap = MAX_HISTORY if conv == CONV_ROOM else MAX_CONV_HISTORY
            d = deque(items[-cap:], maxlen=cap)
            self.history[conv] = d

    def send_history(self, cs, conv, limit=None):
        kind = conv_kind(conv)
        if kind == 'group':
            gid = conv[2:]
            if not self.social.in_group(gid, cs.nick):
                cs._notice('你不在该群里')
                return
        elif kind == 'friend':
            other = conv[2:]
            if not self.social.are_friends(cs.nick, other):
                cs._notice('对方不是你的好友')
                return
        items = [dict(m, history=True) for m in self.hist_of(conv)]
        if limit:
            items = items[-int(limit):]
        cs._send({'t': 'history', 'conv': conv, 'items': items})

    # ---------- 登录完成 ----------
    def complete_login(self, cs, nick, key):
        # 单 IP 已登录连接数限制（只统计已登录，避免失败重连把配额耗光）
        ip = cs.addr[0]
        with self.lock:
            if self._ip_counts.get(ip, 0) >= MAX_PER_IP:
                allowed = False
            else:
                self._ip_counts[ip] = self._ip_counts.get(ip, 0) + 1
                cs.counted = True
                allowed = True
        if not allowed:
            cs._deny(f'同一网络下登录的设备过多（上限 {MAX_PER_IP}），请稍后再试')
            return

        # 同账号重复登录：踢掉旧连接
        old = self.session_of(nick)
        if old is not None and old is not cs:
            old._notice('你的账号在另一处登录，本连接已断开')
            threading.Timer(0.5, lambda: self.drop(old.sid, None)).start()

        cs.nick = nick
        cs.key_lower = nick.strip().lower()
        cs.region = region_for(cs.addr[0], self.geo_lookup)   # 服务端判定，强制生效
        if cs.region == UNKNOWN and self.geo_lookup:
            # 别让「属地未知」一直挂着：丢到后台隔一会儿再问一次，
            # 成功就更新属地并通知所有人刷新（网络抖动/接口限流很常见）
            threading.Thread(target=self._refine_region,
                             args=(cs.sid, cs.addr[0], cs.nick), daemon=True).start()
        cs.authenticated = True
        cs.state = 'ready'
        cs.channel.key = key
        cs.channel.enable_secure()
        cs.channel.peer_ready = True      # 之后的心跳应答就是正常负载了

        cs._send({'t': 'welcome', 'you': nick, 'room': self.room,
                  'my_ip': (cs.addr[0] if getattr(cs, 'addr', None) else ''),
                  'users': self.user_list(), 'time': now_ts(),
                  'server_ip': self.server_ip, 'server_region': self.server_region,
                  'server_region_state': self.server_region_state,
                  'server_region_reason': self.server_region_reason,
                  'server_port': self.port,
                  'avatars': self.avatar_map(),
                  'offline': self.social.offline_count(nick),
                  'super': self.is_super(nick)})
        self.social.touch(nick)
        self.push_social(cs)
        self.send_history(cs, CONV_ROOM)
        self.deliver_offline(cs)
        if self.is_super(nick):
            self.log(f'★ 超级管理员 {nick} 上线')
            self.push_admin(only=cs)

        self.add_history(CONV_ROOM, {'t': 'system', 'kind': 'join', 'conv': CONV_ROOM,
                                     'text': f'{nick}（{cs.region}）进入了公共大厅',
                                     'time': now_ts()})
        self.broadcast({'t': 'system', 'kind': 'join', 'conv': CONV_ROOM,
                        'text': f'{nick}（{cs.region}）进入了公共大厅', 'time': now_ts()},
                       exclude_sid=cs.sid)
        self.push_users()
        self.notify_presence(cs.nick, True)
        self.log(f'● {nick} 上线    （{self.counts()}）')

    def _refine_region(self, sid, ip, nick):
        """后台重解析属地：登录时没查到就隔一会儿再试，成功则全员刷新。

        「属地未知」通常只是接口抖动/限流，重试一次基本就好了；
        重试成功后把 region 推给所有人，客户端不用重登也能看到具体城市。
        """
        for wait in self.REGION_RETRY_WAITS:
            time.sleep(wait)
            cs = self.clients.get(sid)
            if cs is None or not cs.authenticated or cs.region != UNKNOWN:
                return
            clear_ip(ip)
            try:
                text = region_for(ip, True, budget=8.0)
            except Exception:
                text = UNKNOWN
            if text and text != UNKNOWN:
                cs.region = text
                self.log(f'◆ 补上了 {nick} 的属地：{text}')
                self.push_users()          # 成员列表 / 属地映射全员刷新
                self.push_social_all()
                return
        self.log(f'⚠ {nick} 的属地解析一直失败（{failed_reason()}）')

    def push_social(self, cs):
        cs._send({'t': 'social',
                  'friends': self.social.friend_nicks(cs.nick),
                  'requests': self.social.requests(cs.nick),
                  'groups': self.social.groups_of(cs.nick),
                  'online': self.online_nicks(),
                  'regions': self.region_map(),
                  'avatars': self.avatar_map(),
                  'blocks': self.social.block_list(cs.nick),
                  'invites': self.social.my_invites(cs.nick),
                  'offline': self.social.offline_count(cs.nick)})

    def push_social_all(self):
        for cs in self.sessions():
            if cs.authenticated:
                self.push_social(cs)

    def notify_presence(self, nick, online):
        for f in self.social.friend_nicks(nick):
            tgt = self.session_of(f)
            if tgt is not None:
                tgt._send({'t': 'presence', 'nick': nick, 'online': online,
                           'time': now_ts()})

    # ---------- 公共大厅 ----------
    def room_message(self, sender, text, kind='chat'):
        if not valid_text(text):
            return
        msg = {'t': kind, 'conv': CONV_ROOM, 'from': sender.nick, 'text': text,
               'region': sender.region, 'time': now_ts()}
        mentions = [n for n in parse_mentions(text, self.online_nicks()) if n != sender.nick]
        if mentions:
            msg['mentions'] = mentions
        self.add_history(CONV_ROOM, msg)
        self.broadcast(msg, exclude_sid=sender.sid)

    # ---------- 好友私聊 ----------
    def friend_message(self, sender, to, text):
        if not valid_text(text):
            return
        if not self.social.are_friends(sender.nick, to):
            sender._notice(f'「{to}」不是你的好友，无法私聊')
            return
        if self.social.blocked_between(sender.nick, to):
            # 分开说：是我拉黑了对方，还是对方拉黑了我 —— 别直接替对方
            # 「宣布」他把人拉黑了（把话说得客气一点）。
            if self.social.blocked(sender.nick, to):
                sender._notice(f'你已把「{self.social.display(to)}」拉黑，'
                               f'解除后才能发消息')
            else:
                sender._notice(f'消息没有发出去：「{self.social.display(to)}」'
                               f'当前无法接收')
            return
        target = self.session_of(to)
        now = now_ts()
        mid = new_mid()          # 两边历史里存同一条 mid，撤回才能对上
        conv_a = conv_user(to)
        conv_b = conv_user(sender.nick)
        sender._send({'t': 'chat', 'conv': conv_a, 'from': sender.nick,
                      'text': text, 'region': sender.region, 'time': now,
                      'kind': 'pm', 'self': True, 'mid': mid})
        self.add_history(conv_a, {'t': 'chat', 'conv': conv_a, 'from': sender.nick,
                                  'text': text, 'region': sender.region, 'time': now,
                                  'kind': 'pm', 'self': True, 'mid': mid})
        if target is not None:
            target._send({'t': 'chat', 'conv': conv_b, 'from': sender.nick,
                          'text': text, 'region': sender.region, 'time': now,
                          'kind': 'pm', 'mid': mid})
            self.add_history(conv_b, {'t': 'chat', 'conv': conv_b, 'from': sender.nick,
                                      'text': text, 'region': sender.region,
                                      'time': now, 'kind': 'pm', 'mid': mid})
        else:
            # 离线留言：存服务端，对方下次登录一次性送达（服务重启也不丢）
            self.social.add_offline(to, {'from': sender.nick, 'text': text,
                                         'region': sender.region, 'time': now})
            sender._notice(f'「{self.social.display(to)}」当前不在线，'
                           f'这条消息已离线留存在服务器，对方上线后就能看到')

    def deliver_offline(self, cs):
        """登录时把积压的离线留言一次性推给客户端。"""
        try:
            items = self.social.take_offline(cs.nick)
        except Exception:
            items = []
        if not items:
            return
        for m in items:
            conv = conv_user(m.get('from'))
            msg = {'t': 'chat', 'conv': conv, 'from': m.get('from', ''),
                   'text': m.get('text', ''), 'region': m.get('region', ''),
                   'time': m.get('time', 0), 'kind': 'pm', 'offline': True}
            cs._send(msg)
            self.add_history(conv, dict(msg, conv=conv))
        cs._notice(f'有 {len(items)} 条离线留言已送达')
        self.log(f'✉ 向 {cs.nick} 送达 {len(items)} 条离线留言')

    # ---------- 群聊 ----------
    def group_message(self, sender, gid, text):
        if not valid_text(text):
            return
        gv = self.social.group(gid)
        if not gv or not self.social.in_group(gid, sender.nick):
            sender._notice('你不在该群里')
            return
        left = self.social.is_muted(gid, sender.nick)
        if left:
            if left < 0:
                sender._notice('你已被禁言（永久），无法在群里发言')
            else:
                mins = max(1, (left + 59) // 60)
                sender._notice(f'你已被禁言，还需等待约 {mins} 分钟')
            return
        conv = conv_group(gid)
        msg = {'t': 'chat', 'conv': conv, 'from': sender.nick, 'text': text,
               'region': sender.region, 'time': now_ts(), 'kind': 'group',
               'gid': str(gid), 'group': gv['name']}
        # 群里 @ 人也算「被点名」：以前只有大厅解析 @，群里 @ 完全没反应
        pool = [self.social.display(m) for m in gv['members']]
        mentions = [n for n in parse_mentions(text, pool)
                    if n.strip().lower() != sender.key_lower]
        if mentions:
            msg['mentions'] = mentions
        self.add_history(conv, msg)
        for m in gv['members']:
            if m == sender.key_lower:
                continue
            tgt = self.session_of(m)
            if tgt is not None:
                tgt._send(msg)

    # ---------- 好友操作 ----------
    def friend_add(self, cs, nick, msg=''):
        if not nick:
            cs._notice('请先填写对方的昵称')
            return
        ok, err = self.social.add_friend_request(cs.nick, nick, msg)
        if ok:
            cs._notice(f'已向「{self.social.display(nick)}」发送好友申请')
            tgt = self.session_of(nick)
            if tgt is not None:
                text = f'「{cs.nick}」请求加你为好友'
                if (msg or '').strip():
                    text += f'：{(msg or "").strip()}'
                tgt._notice(text)
                self.push_social(tgt)
            self.log(f'✉ 「{cs.nick}」申请加「{self.social.display(nick)}」为好友')
        else:
            cs._notice(err)

    def friend_accept(self, cs, nick):
        ok, err = self.social.accept_friend(cs.nick, nick)
        if not ok:
            cs._notice(err)
            return
        self.push_social(cs)
        tgt = self.session_of(nick)
        if tgt is not None:
            tgt._notice(f'「{cs.nick}」已同意你的好友申请')
            self.push_social(tgt)
        self.log(f'♥ 「{cs.nick}」与「{self.social.display(nick)}」成为好友')

    def friend_reject(self, cs, nick):
        self.social.reject_friend(cs.nick, nick)
        self.push_social(cs)

    def friend_remove(self, cs, nick):
        # 老的 friend_remove 客户端命令：和新的「删除好友」走同一条路
        self.friend_del(cs, nick)

    # ---------- 群操作 ----------
    def group_create(self, cs, name, members):
        ok, err, gid = self.social.create_group(cs.nick, name, members)
        if not ok:
            cs._notice(err)
            return
        cs._notice(f'群「{name}」创建成功，群号 {group_no(gid)}'
                   f'（把群号告诉朋友，他们就能申请加入）')
        for m in self.social.group_members(gid):
            tgt = self.session_of(m)
            if tgt is not None:
                self.push_social(tgt)
        members = '、'.join(self.social.display(m) for m in self.social.group_members(gid))
        self.log(f'＋ 群「{name}」由 {cs.nick} 创建，群号 {group_no(gid)}，'
                 f'成员：{members}    （{self.counts()}）')

    def group_add(self, cs, gid, nick):
        gconv = conv_group(gid)
        gv = self.social.group(gid)
        if not gv:
            cs._notice('群不存在')
            return
        if not self.social.can_manage(gid, cs.nick):
            cs._notice('只有群主或管理员可以拉人', conv=gconv, toast=True)
            return
        ok, err = self.social.add_to_group(gid, nick)
        if not ok:
            cs._notice(err, conv=gconv, toast=True)
            return
        cs._notice(f'已把「{self.social.display(nick)}」拉进群', conv=gconv)
        self.group_push(gid)
        self.group_welcome(gid, nick)
        self.log(f'＋ 「{self.social.display(nick)}」被 {cs.nick} 拉进群「{gv["name"]}」'
                 f'（{len(self.social.group_members(gid))} 人）    （{self.counts()}）')

    def group_leave(self, cs, gid):
        ok, err = self.social.leave_group(gid, cs.nick)
        if not ok:
            cs._notice(err)
            return
        cs._notice('已退出该群')
        self.push_social(cs)
        self.group_push(gid)
        self.log(f'－ {cs.nick} 退出了群    （{self.counts()}）')

    # ---------- 群：资料 / 公告 / 群文件 ----------
    def group_push(self, gid):
        """群资料变了：推给所有群成员（成员的 social 里有群简介）。"""
        members = self.social.group_members(gid)
        for m in members:
            tgt = self.session_of(m)
            if tgt is not None:
                self.push_social(tgt)
        if not self.social.group(gid):
            return
        info = self.group_info_of(gid)
        self.broadcast({'t': 'group_info', 'info': info}, only=set(members))

    def group_info_of(self, gid, viewer=None):
        gv = self.social.group(gid) or {}
        return {
            'gid': str(gid), 'no': group_no(gid), 'name': gv.get('name', ''),
            'owner': self.social.display(gv.get('owner', '')),
            'members': self.social.member_list(gid),
            'announce': gv.get('announce'),
            'files': list(gv.get('files') or []),
            'joins': self.social.join_requests(gid),
            # 拉人入群的待批准列表（只有群主/管理员看得到，普通成员拿到空表）
            'invites': ([self.social._invite_view(r, gid)
                         for r in (gv.get('invites') or [])]
                        if viewer and self.social.role(gid, viewer) in ('owner', 'admin')
                        else []),
            'my_invites': ([self.social._invite_view(r, gid)
                            for r in (gv.get('invites') or [])
                            if r.get('nick') == (viewer or '').strip().lower()]
                           if viewer else []),
            'role': self.social.role(gid, viewer) if viewer else '',
        }

    def push_group_info(self, cs, gid):
        """把最新的群资料推给某个人（拉人入群、审批后界面要立刻变）。"""
        try:
            if not self.social.in_group(gid, cs.nick):
                return
            cs._send({'t': 'group_info', 'info': self.group_info_of(gid, cs.nick)})
        except Exception:
            pass

    def group_welcome(self, gid, nick):
        """新入群的人：看得到最近 30 条群消息 + 一份群资料。"""
        tgt = self.session_of(nick)
        if tgt is None:
            return
        gv = self.social.group(gid)
        self.send_history(tgt, conv_group(gid), limit=GROUP_HISTORY_ON_JOIN)
        tgt._send({'t': 'group_info', 'info': self.group_info_of(gid, nick)})
        if gv:
            ann = (gv.get('announce') or {}).get('text')
            tip = f'你已加入群「{gv["name"]}」（群号 {group_no(gid)}）'
            if ann:
                tip += f'；群公告：{ann}'
            tgt._notice(tip, conv=conv_group(gid), toast=True)

    def group_info_get(self, cs, gid):
        gv = self.social.group(gid)
        if not gv or not self.social.in_group(gid, cs.nick):
            cs._notice('你不在该群里')
            return
        cs._send({'t': 'group_info', 'info': self.group_info_of(gid, cs.nick)})

    def group_announce(self, cs, gid, text):
        gconv = conv_group(gid)
        ok, err = self.social.set_announce(gid, cs.nick, text)
        if not ok:
            cs._notice(err, conv=gconv, toast=True)
            return
        text = (text or '').strip()
        cs._notice('群公告已更新' if text else '群公告已清除', conv=gconv)
        self.group_push(gid)
        gv = self.social.group(gid) or {}
        for m in self.social.group_members(gid):
            if m == cs.key_lower:
                continue
            tgt = self.session_of(m)
            if tgt is not None:
                tgt._notice(f'群「{gv.get("name", "")}」发布了新公告：{text[:80]}',
                            conv=gconv, toast=True)
        self.log(f'◆ {cs.nick} 更新了群「{gv.get("name", "")}」的公告')

    def group_admin(self, cs, gid, nick, on):
        gconv = conv_group(gid)
        ok, err = self.social.set_admin(gid, cs.nick, nick, bool(on))
        if not ok:
            cs._notice(err, conv=gconv, toast=True)
            return
        who = self.social.display(nick)
        cs._notice(f'已把「{who}」{"设为管理员" if on else "取消管理员"}', conv=gconv)
        self.group_push(gid)
        tgt = self.session_of(nick)
        if tgt is not None and tgt is not cs:
            tgt._notice(f'你{"被设为" if on else "被取消了"}群「'
                        f'{(self.social.group(gid) or {}).get("name", "")}」的管理员',
                        conv=gconv, toast=True)
        self.log(f'★ {cs.nick} {"设置" if on else "取消"}{who} 为群管理员')

    def group_mute(self, cs, gid, nick, minutes):
        gconv = conv_group(gid)
        ok, err = self.social.set_mute(gid, cs.nick, nick, minutes)
        if not ok:
            cs._notice(err, conv=gconv, toast=True)
            return
        who = self.social.display(nick)
        if minutes is None or int(minutes) < 0:
            cs._notice(f'已解除「{who}」的禁言', conv=gconv)
        elif int(minutes) == 0:
            cs._notice(f'已永久禁言「{who}」', conv=gconv)
        else:
            cs._notice(f'已禁言「{who}」{int(minutes)} 分钟', conv=gconv)
        self.group_push(gid)
        tgt = self.session_of(nick)
        if tgt is not None and tgt is not cs:
            if minutes is None or int(minutes) < 0:
                tgt._notice('你的禁言已被解除', conv=gconv, toast=True)
                tgt._send({'t': 'unmuted', 'gid': str(gid),
                           'group': (self.social.group(gid) or {}).get('name', ''),
                           'by': cs.nick})
            else:
                m = int(minutes)
                tgt._notice('你被' + ('永久禁言' if m == 0 else f'禁言 {m} 分钟'),
                            conv=gconv, toast=True)
                # 结构化下发：客户端据此把输入框/发送按钮收起来并显示「禁言中」
                tgt._send({'t': 'muted', 'gid': str(gid),
                           'group': (self.social.group(gid) or {}).get('name', ''),
                           'minutes': m, 'left': 0 if m == 0 else m * 60,
                           'by': cs.nick, 'time': now_ts()})
        self.log(f'⊘ {cs.nick} 禁言 {who}（{minutes}）')

    def group_kick(self, cs, gid, nick):
        gconv = conv_group(gid)
        gv = self.social.group(gid) or {}
        gname = gv.get('name', '')
        ok, err = self.social.kick(gid, cs.nick, nick)
        if not ok:
            cs._notice(err, conv=gconv, toast=True)
            return
        who = self.social.display(nick)
        cs._notice(f'已把「{who}」移出群', conv=gconv)
        tgt = self.session_of(nick)
        if tgt is not None:
            tgt._notice(f'你已被移出群「{gname}」', conv=gconv, toast=True)
            self.push_social(tgt)
            tgt._send({'t': 'kicked', 'gid': str(gid), 'group': gname})
        self.group_push(gid)
        self.log(f'✂ {cs.nick} 把 {who} 移出群「{gname}」')

    def group_join(self, cs, no, msg=''):
        gv, gid = self.social.find_by_no(no)
        if not gv:
            cs._notice('群号不存在，请检查后重试')
            return
        ok, err = self.social.join_request(gid, cs.nick, msg)
        if not ok:
            cs._notice(err)
            return
        cs._notice(f'已申请加入群「{gv["name"]}」（群号 {group_no(gid)}），等待群主或管理员同意')
        for m in self.social.group_members(gid):
            if not self.social.can_manage(gid, m):
                continue
            tgt = self.session_of(m)
            if tgt is not None:
                tgt._notice(f'「{cs.nick}」申请加入群「{gv["name"]}」'
                            + (f'：{msg}' if msg else '')
                            + '（可在左侧「加群申请」里处理）',
                            conv=conv_group(gid), toast=True)
                self.push_social(tgt)
        self.group_push(gid)
        self.log(f'✉ {cs.nick} 申请加入群「{gv["name"]}」（群号 {group_no(gid)}）')

    # ---------- 撤回 ----------
    def recall(self, cs, conv, mid):
        """撤回一条消息。

        · 自己的消息：2 分钟内可撤回；
        · 群里：群主 / 管理员可以不限时间撤回**普通成员**的消息（互相之间不行）。
        """
        if not conv or not mid:
            return
        target = None
        for m in list(self.hist_of(conv)):
            if str(m.get('mid') or '') == str(mid):
                target = m
                break
        if target is None or target.get('recalled'):
            cs._notice('这条消息已经不在服务器记录里了')
            return
        sender = target.get('from') or ''
        mine = sender.strip().lower() == cs.key_lower
        kind = conv_kind(conv)
        if conv == CONV_ROOM:
            if not mine:
                cs._notice('大厅里只能撤回自己发的消息')
                return
            self._check_window(cs, target)
            if self._recall_blocked:
                return
        elif kind == 'group':
            gid = conv[2:]
            if not self.social.in_group(gid, cs.nick):
                cs._notice('你不在该群里')
                return
            if mine:
                self._check_window(cs, target)
                if self._recall_blocked:
                    return
            else:
                my_role = self.social.role(gid, cs.nick)
                his_role = self.social.role(gid, sender)
                if my_role not in ('owner', 'admin'):
                    cs._notice('只有群主或管理员能撤回别人的消息')
                    return
                if his_role != 'member':
                    cs._notice('群主/管理员只能撤回普通成员的消息')
                    return
        else:
            if not mine:
                cs._notice('只能撤回自己发的消息')
                return
            self._check_window(cs, target)
            if self._recall_blocked:
                return

        target['recalled'] = True
        target['text'] = ''
        target.pop('mentions', None)
        target['recalled_by'] = cs.nick
        self._persist_recall(conv, mid)
        ev = {'t': 'recall', 'conv': conv, 'mid': str(mid), 'by': cs.nick,
              'from': sender, 'time': now_ts()}
        self._send_recall(conv, ev)
        self.log(f'↩ 「{cs.nick}」撤回了 {conv} 里的一条消息')

    def _check_window(self, cs, target):
        self._recall_blocked = False
        age = now_ts() - int(target.get('time') or 0)
        if age > RECALL_WINDOW:
            cs._notice(f'发出超过 {RECALL_WINDOW // 60} 分钟的消息不能撤回了')
            self._recall_blocked = True

    _recall_blocked = False

    def _send_recall(self, conv, ev):
        """把撤回通知推给这条会话相关的所有人。

        私聊两边的会话名不一样（各自的 'u:对方'），所以两边要分别带自己的
        会话名推过去 —— 两边的历史里存的是同一条 mid。
        """
        kind = conv_kind(conv)
        if conv == CONV_ROOM:
            self.broadcast(ev)
            return
        if kind == 'group':
            gid = conv[2:]
            gv = self.social.group(gid) or {}
            for m in gv.get('members', []):
                tgt = self.session_of(m)
                if tgt is not None:
                    tgt._send(ev)
            return
        # 私聊：conv = 'u:对方'，发送方是历史里记的 from
        other = conv[2:]
        sender = ev.get('from') or ''
        for nick in {other, sender}:
            tgt = self.session_of(nick)
            if tgt is None:
                continue
            own = conv if nick.lower() == sender.lower() else conv_user(sender)
            tgt._send(dict(ev, conv=own))

    # ---------- 好友：删除 / 拉黑 ----------
    def friend_del(self, cs, nick):
        """删好友：双向解除，对方以后还能再申请加回来。"""
        ok, err = self.social.remove_friend(cs.nick, nick)
        if not ok:
            cs._notice(err)
            return
        cs._notice(f'已把「{self.social.display(nick)}」从好友里删除')
        tgt = self.session_of(nick)
        if tgt is not None:
            tgt._notice(f'「{cs.nick}」把你从好友里删除了')
            self.push_social(tgt)
        self.push_social(cs)
        self.log(f'✂ 「{cs.nick}」删除了好友「{self.social.display(nick)}」')

    def friend_block(self, cs, nick, on=True):
        """拉黑 / 取消拉黑：拉黑后对方不能给你发好友申请，也不能给你发消息。"""
        ok, err = self.social.set_block(cs.nick, nick, on)
        if not ok:
            cs._notice(err)
            return
        if on:
            cs._notice(f'已把「{self.social.display(nick)}」拉黑：'
                       f'对方无法再给你发消息和好友申请')
        else:
            cs._notice(f'已把「{self.social.display(nick)}」移出黑名单')
        tgt = self.session_of(nick)
        if tgt is not None:
            self.push_social(tgt)
        self.push_social(cs)
        self.log(f'🚫 「{cs.nick}」{"拉黑" if on else "取消拉黑"}了'
                 f'「{self.social.display(nick)}」')

    # ---------- 群：拉好友入群（管理员 + 被拉人 双方同意） ----------
    def group_invite(self, cs, gid, nick):
        ok, err = self.social.invite_to_group(gid, cs.nick, nick)
        if not ok:
            cs._notice(err)
            return
        gv = self.social.group(gid) or {}
        name = gv.get('name') or '群聊'
        cs._notice(f'已邀请「{self.social.display(nick)}」加入「{name}」，'
                   f'等对方和管理员都同意后就进群')
        tgt = self.session_of(nick)
        if tgt is not None:
            tgt._notice(f'「{cs.nick}」邀请你加入群「{name}」，'
                        f'在群资料里同意后即可进群')
            self.push_social(tgt)
        for m in gv.get('admins') or []:
            adm = self.session_of(m)
            if adm is not None:
                self.push_social(adm)
        owner = self.session_of(gv.get('owner') or '')
        if owner is not None:
            self.push_social(owner)
        self.push_social(cs)
        self.log(f'➕ 「{cs.nick}」邀请「{self.social.display(nick)}」加入「{name}」')

    def group_invite_answer(self, cs, gid, nick, accept):
        """被拉的人表态。"""
        ok, err, done = self.social.answer_invite(gid, nick, 'nick', accept, cs.nick)
        if not ok:
            cs._notice(err)
            return
        gv = self.social.group(gid) or {}
        name = gv.get('name') or '群聊'
        if not accept:
            cs._notice(f'你拒绝了加入「{name}」的邀请')
        elif done:
            cs._notice(f'管理员也同意了，你已经加入「{name}」')
            self._group_joined(gid, nick)
        else:
            cs._notice(f'已同意，等管理员确认后就能进「{name}」')
        self.push_social(cs)
        self._push_group_invite(gid)

    def group_invite_admin(self, cs, gid, nick, accept):
        """群主 / 管理员表态。"""
        ok, err, done = self.social.answer_invite(gid, nick, 'admin', accept, cs.nick)
        if not ok:
            cs._notice(err)
            return
        gv = self.social.group(gid) or {}
        name = gv.get('name') or '群聊'
        if not accept:
            cs._notice(f'已拒绝「{self.social.display(nick)}」加入「{name}」')
        elif done:
            cs._notice(f'「{self.social.display(nick)}」已加入「{name}」')
            self._group_joined(gid, nick)
        else:
            cs._notice(f'已同意，等「{self.social.display(nick)}」本人确认')
        self._push_group_invite(gid)

    def _group_joined(self, gid, nick):
        """双方都同意了：真正把人加进群。"""
        gv = self.social.group(gid) or {}
        name = gv.get('name') or '群聊'
        self.social.add_member(gid, nick)
        ev = {'t': 'system', 'conv': conv_group(gid), 'kind': 'join',
              'text': f'👋 {nick} 加入了群聊', 'time': now_ts()}
        self.add_history(conv_group(gid), ev)
        for m in (self.social.group(gid) or {}).get('members', []):
            tgt = self.session_of(m)
            if tgt is not None:
                tgt._send(dict(ev))
                self.push_social(tgt)
                self.send_history(tgt, conv_group(gid), limit=GROUP_HISTORY_ON_JOIN)
                self.push_group_info(tgt, gid)
        self.log(f'👋 「{nick}」加入了「{name}」')

    def _push_group_invite(self, gid):
        gv = self.social.group(gid) or {}
        for m in (gv.get('members') or []):
            tgt = self.session_of(m)
            if tgt is not None:
                self.push_social(tgt)
                self.push_group_info(tgt, gid)

    def group_join_answer(self, cs, gid, nick, accept):
        gconv = conv_group(gid)
        gv = self.social.group(gid)
        if not gv:
            cs._notice('群不存在')
            return
        ok, err = self.social.answer_join(gid, cs.nick, nick, bool(accept))
        if not ok:
            cs._notice(err, conv=gconv, toast=True)
            return
        who = self.social.display(nick)
        cs._notice(f'已{"同意" if accept else "拒绝"}「{who}」的加群申请', conv=gconv)
        if accept:
            self.group_welcome(gid, nick)
            tgt = self.session_of(nick)
            if tgt is not None:
                tgt._notice(f'你已加入群「{gv["name"]}」（群号 {group_no(gid)}）',
                            conv=gconv, toast=True)
            self.log(f'＋ {cs.nick} 同意 {who} 加入群「{gv["name"]}」')
        else:
            tgt = self.session_of(nick)
            if tgt is not None:
                tgt._notice(f'你的加群申请被「{gv["name"]}」拒绝', toast=True)
            self.log(f'－ {cs.nick} 拒绝 {who} 加入群「{gv["name"]}」')
        self.group_push(gid)

    def group_file_del(self, cs, gid, fid):
        gconv = conv_group(gid)
        gv = self.social.group(gid)
        if not gv:
            cs._notice('群不存在')
            return
        if not self.social.can_manage(gid, cs.nick):
            cs._notice('只有群主或管理员可以删除群文件', conv=gconv, toast=True)
            return
        if not self.social.group_file(gid, fid):
            cs._notice('该群文件不存在', conv=gconv, toast=True)
            return
        self.social.remove_group_file(gid, fid)
        cs._notice('已从群文件移除（服务端缓存文件也会一并清掉）', conv=gconv)
        with self.lock:
            rec = self.files.pop(fid, None)
            try:
                self.file_order.remove(fid)
            except ValueError:
                pass
        if rec:
            try:
                os.remove(rec['path'])
            except OSError:
                pass
        self.group_push(gid)

    def search_users(self, cs, q):
        cs._send({'t': 'search_result', 'q': q, 'users': self.social.search(q)})

    # ---------- 中国象棋（服务端当裁判） ----------
    def _chess_send(self, nick, msg):
        target = self.session_of(nick)
        if target is not None:
            target._send(msg)
            return True
        return False

    def _chess_both(self, game, msg):
        self._chess_send(game.red, msg)
        self._chess_send(game.black, msg)

    def _chess_push(self, game, act='update', extra=None):
        payload = {'t': 'chess', 'act': act, 'game': game.snapshot()}
        if extra:
            payload.update(extra)
        self._chess_both(game, payload)

    def _chess_cleanup(self):
        """清掉过期的约战邀请和已经结束很久的棋局。"""
        now = time.time()
        for cid, c in list(self.challenges.items()):
            if now - c['time'] > CHALLENGE_TTL:
                self.challenges.pop(cid, None)
                self._chess_send(c['from'], {
                    't': 'chess', 'act': 'challenge_expired', 'cid': cid, 'to': c['to']})

    def active_games(self):
        return [g for g in self.games.values() if not g.over]

    def chess(self, cs, obj):
        """处理客户端发来的象棋消息。"""
        if not cs.authenticated:
            return
        act = str(obj.get('act') or '')
        self._chess_cleanup()
        if act == 'challenge':
            self._chess_challenge(cs, (obj.get('to') or '').strip())
        elif act == 'accept':
            self._chess_accept(cs, str(obj.get('cid') or ''), str(obj.get('color') or ''))
        elif act == 'reject':
            self._chess_reject(cs, str(obj.get('cid') or ''))
        elif act == 'cancel':
            self._chess_cancel(cs, str(obj.get('cid') or ''))
        else:
            game = self.games.get(str(obj.get('gid') or ''))
            if game is None:
                cs._send({'t': 'chess', 'act': 'error', 'text': '棋局不存在或已结束'})
                return
            if game.side_of(cs.nick) is None:
                cs._send({'t': 'chess', 'act': 'error', 'text': '你不在这一局里'})
                return
            if act == 'move':
                self._chess_move(cs, game, obj)
            elif act == 'resign':
                self._chess_resign(cs, game)
            elif act == 'draw':
                self._chess_offer_draw(cs, game)
            elif act == 'draw_answer':
                self._chess_answer(cs, game, 'draw', bool(obj.get('accept')))
            elif act == 'undo':
                self._chess_offer_undo(cs, game)
            elif act == 'undo_answer':
                self._chess_answer(cs, game, 'undo', bool(obj.get('accept')))
            elif act == 'state':
                cs._send({'t': 'chess', 'act': 'update', 'game': game.snapshot()})
            elif act == 'leave':
                self._chess_leave(cs, game)
            else:
                cs._send({'t': 'chess', 'act': 'error', 'text': '未知的象棋操作'})

    # ---- 约战 ----
    def _chess_challenge(self, cs, to):
        if not to:
            return
        target = self.session_of(to)
        if target is cs:
            cs._send({'t': 'chess', 'act': 'error', 'text': '不能约战自己'})
            return
        if target is None:
            cs._send({'t': 'chess', 'act': 'error', 'text': '对方不在线'})
            return
        if cs.game_id or target.game_id:
            cs._send({'t': 'chess', 'act': 'error', 'text': '对方或你正在对局中'})
            return
        if len(self.active_games()) >= MAX_GAMES:
            cs._send({'t': 'chess', 'act': 'error', 'text': '服务端对局数已达上限'})
            return
        low = target.key_lower
        for c in self.challenges.values():
            if c['from'] == cs.key_lower and c['to'] == low:
                cs._send({'t': 'chess', 'act': 'challenge_sent',
                          'cid': c['cid'], 'to': target.nick, 'again': True})
                return
            if c['to'] == low:
                cs._send({'t': 'chess', 'act': 'error', 'text': '已经有人在约战对方了'})
                return
        cid = secrets.token_hex(4)
        self.challenges[cid] = {'cid': cid, 'from': cs.key_lower, 'from_nick': cs.nick,
                                'to': low, 'time': time.time()}
        self._chess_send(target.nick, {
            't': 'chess', 'act': 'challenged', 'cid': cid, 'from': cs.nick,
            'region': cs.region})
        cs._send({'t': 'chess', 'act': 'challenge_sent', 'cid': cid, 'to': target.nick})
        self.log(f'◆ {cs.nick} 向 {target.nick} 发起象棋约战    （{self.counts()}）')

    def _chess_reject(self, cs, cid):
        c = self.challenges.pop(cid, None)
        if c is None or c['to'] != cs.key_lower:
            return
        self._chess_send(c['from_nick'], {
            't': 'chess', 'act': 'challenge_rejected', 'cid': cid, 'by': cs.nick})
        self.log(f'◆ {cs.nick} 拒绝了 {c["from_nick"]} 的象棋约战')

    def _chess_cancel(self, cs, cid):
        c = self.challenges.pop(cid, None)
        if c is None or c['from'] != cs.key_lower:
            return
        self._chess_send(c['to'], {'t': 'chess', 'act': 'challenge_cancelled', 'cid': cid})

    def _chess_accept(self, cs, cid, color):
        c = self.challenges.pop(cid, None)
        if c is None or c['to'] != cs.key_lower:
            cs._send({'t': 'chess', 'act': 'error', 'text': '这个约战已经失效了'})
            return
        if color not in ('r', 'b'):
            color = SIDE_RED
        other = self.session_of(c['from_nick'])
        if other is None or other.game_id or cs.game_id:
            cs._send({'t': 'chess', 'act': 'error', 'text': '对方已经不在线或已开局'})
            self._chess_send(c['from_nick'], {
                't': 'chess', 'act': 'challenge_cancelled', 'cid': cid})
            return
        # 被挑战方选颜色，另一方拿剩下的
        red = cs.nick if color == SIDE_RED else other.nick
        black = other.nick if color == SIDE_RED else cs.nick
        gid = secrets.token_hex(4)
        game = ChessGame(gid, red, black)
        game.created = time.time()
        self.games[gid] = game
        cs.game_id = gid
        other.game_id = gid
        self._chess_push(game, act='start')
        self.log(f'◆ 新棋局开始：红 {red} vs 黑 {black}'
                 f'（{cs.nick} 选了{"红" if color == SIDE_RED else "黑"}方）'
                 f'    （{self.counts()}）')

    # ---- 对局中 ----
    def _chess_move(self, cs, game, obj):
        if game.over:
            return
        fr = obj.get('from') or []
        to = obj.get('to') or []
        if len(fr) != 2 or len(to) != 2:
            cs._send({'t': 'chess', 'act': 'error', 'text': '走法格式不对'})
            return
        ok, err = game.do_move(cs.nick, fr[0], fr[1], to[0], to[1])
        if not ok:
            cs._send({'t': 'chess', 'act': 'error', 'text': err,
                      'game': game.snapshot()})
            return
        if game.over:
            self._chess_finish(game, game.reason)
        else:
            self._chess_push(game)
            if game.in_check_now():
                self._chess_both(game, {'t': 'chess', 'act': 'check',
                                        'gid': game.gid, 'turn': game.turn})

    def _chess_resign(self, cs, game):
        ok, err = game.resign(cs.nick)
        if not ok:
            cs._send({'t': 'chess', 'act': 'error', 'text': err})
            return
        self._chess_finish(game, 'resign')

    def _chess_offer_draw(self, cs, game):
        ok, err = game.offer_draw(cs.nick)
        if not ok:
            cs._send({'t': 'chess', 'act': 'error', 'text': err})
            return
        self._chess_push(game)
        other = game.opponent_of(cs.nick)
        self._chess_send(other, {'t': 'chess', 'act': 'notice',
                                 'gid': game.gid, 'text': f'{cs.nick} 提议和棋'})

    def _chess_offer_undo(self, cs, game):
        ok, err = game.request_undo(cs.nick)
        if not ok:
            cs._send({'t': 'chess', 'act': 'error', 'text': err})
            return
        self._chess_push(game)
        other = game.opponent_of(cs.nick)
        self._chess_send(other, {'t': 'chess', 'act': 'notice',
                                 'gid': game.gid, 'text': f'{cs.nick} 请求悔棋'})

    def _chess_answer(self, cs, game, kind, accept):
        if not game.pending or game.pending.get('kind') != kind:
            cs._send({'t': 'chess', 'act': 'error', 'text': '这个请求已经失效了'})
            return
        by = game.pending.get('by')
        if (by or '').lower() == cs.key_lower:
            cs._send({'t': 'chess', 'act': 'error', 'text': '不能自己同意自己的请求'})
            return
        if not accept:
            game.reject_pending(cs.nick)
            self._chess_push(game)
            self._chess_send(by, {'t': 'chess', 'act': 'notice', 'gid': game.gid,
                                  'text': f'{cs.nick} 拒绝了你的请求'})
            return
        if kind == 'draw':
            ok, err = game.agree_draw(cs.nick)
            if not ok:
                cs._send({'t': 'chess', 'act': 'error', 'text': err})
                return
            self._chess_finish(game, 'agreement')
            return
        # 悔棋：撤销发起方最近那一步
        n = game.apply_undo(by)
        self.log(f'◆ {game.red} vs {game.black} 悔棋 {n} 步')
        self._chess_push(game)
        self._chess_both(game, {'t': 'chess', 'act': 'notice', 'gid': game.gid,
                                'text': f'{cs.nick} 同意悔棋'})

    def _chess_leave(self, cs, game):
        """关掉棋盘窗口：棋局还在就先不动，双方都离开才回收。"""
        if game.over:
            cs.game_id = None
            if not self._game_in_use(game):
                self.games.pop(game.gid, None)
            cs._send({'t': 'chess', 'act': 'closed', 'gid': game.gid})
        else:
            cs._send({'t': 'chess', 'act': 'closed', 'gid': game.gid})

    def _game_in_use(self, game):
        for cs in self.sessions():
            if cs.game_id == game.gid:
                return True
        return False

    def _chess_finish(self, game, reason):
        game.finished = time.time()
        # 先释放双方的 game_id，再通知结束。
        # 反过来的话会有个微小的窗口：客户端收到 end 后立刻再约战，
        # 这次约战可能赶在 game_id 被清掉之前到达而被误判成「正在对局中」。
        for nick in (game.red, game.black):
            cs = self.session_of(nick)
            if cs is not None:
                cs.game_id = None
        self._chess_push(game, act='end', extra={'reason': reason})
        winner = {'red': game.red, 'black': game.black}.get(game.result, '')
        if game.result == 'draw':
            self.log(f'◆ 棋局结束：{game.red} 与 {game.black} 和棋'
                     f'（{self.reason_text(reason)}）    （{self.counts()}）')
        else:
            self.log(f'◆ 棋局结束：{winner} 胜（{self.reason_text(reason)}）'
                     f'    （{self.counts()}）')

    @staticmethod
    def reason_text(reason):
        return {'checkmate': '绝杀', 'stalemate': '困毙', 'resign': '认输',
                'agreement': '双方同意和棋', 'leave': '对方离线', 'abort': '中止'
                }.get(reason, reason or '')

    def chess_player_dropped(self, nick):
        """一方掉线：判断另一方直接获胜。"""
        for game in list(self.games.values()):
            if game.over:
                continue
            if game.side_of(nick) is None:
                continue
            other = game.opponent_of(nick)
            if game.win_by(other, 'leave'):
                self._chess_finish(game, 'leave')
                self._chess_send(other, {
                    't': 'chess', 'act': 'notice', 'gid': game.gid,
                    'text': f'{nick} 已离线，本局你获胜'})
            else:
                game.abort('abort')
                self._chess_push(game, act='end')

    # ---------- 文件（按会话） ----------
    def file_dir(self):
        d = os.path.join(tempfile.gettempdir(), 'qiaoni_server')
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = tempfile.gettempdir()
        return d

    def avatar_dir(self):
        try:
            os.makedirs(self.avatar_dir_path, exist_ok=True)
        except OSError:
            pass
        return self.avatar_dir_path

    def avatar_path(self, nick, ver=None):
        """头像文件路径：avatars/<昵称>.png（同一人只留一份，换头像直接覆盖）。"""
        k = conv_filename((nick or '').strip().lower())
        v = self.social.avatar_ver(nick)
        if ver is not None:
            try:
                v = int(ver)
            except (TypeError, ValueError):
                v = 0
        return os.path.join(self.avatar_dir(), f'{k}.{v}.png')

    def can_access_conv(self, cs, conv):
        if str(conv) == CONV_AVATAR:
            return True          # 头像上传/下载走伪会话，登录用户都能用
        kind = conv_kind(conv)
        if kind == 'room':
            return True
        if kind == 'group':
            return self.social.in_group(conv[2:], cs.nick)
        if kind == 'friend':
            if str(conv)[2:].strip().lower() == cs.key_lower:
                # 这个会话 id 就是「发给我的」（好友私聊里对方存的记录用的是
                # 收件人视角的会话号）：我当然是当事人，能取这份文件。
                return True
            return self.social.are_friends(cs.nick, conv[2:])
        return False

    def conv_targets(self, conv, exclude_sid=None):
        """该会话应该收到消息的连接。"""
        if conv_kind(conv) == 'room':
            return [cs for cs in self.sessions()
                    if cs.authenticated and cs.sid != exclude_sid]
        if conv_kind(conv) == 'group':
            members = set(self.social.group_members(conv[2:]))
            return [cs for cs in self.sessions()
                    if cs.authenticated and cs.key_lower in members and cs.sid != exclude_sid]
        return []

    def begin_upload(self, sender, obj):
        name = str(obj.get('name') or 'file').strip()[:120] or 'file'
        kind = obj.get('kind') if obj.get('kind') in ('image', 'video', 'file') else file_kind(name)
        conv = str(obj.get('conv') or CONV_ROOM)
        try:
            size = int(obj.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        if conv == CONV_AVATAR:
            if size <= 0 or size > AVATAR_MAX:
                sender.upload = None
                sender._notice(f'头像文件太大（上限 {human_size(AVATAR_MAX)}），请换一张小图')
                return
        elif size <= 0 or size > MAX_FILE_SIZE:
            sender.upload = None
            sender._notice('文件无效或超出可接受范围')
            return
        if not self.can_access_conv(sender, conv):
            sender.upload = None
            sender._notice('你没有该会话的权限')
            return
        try:
            fd, path = tempfile.mkstemp(prefix='recv_', dir=self.file_dir())
            fh = os.fdopen(fd, 'wb')
        except OSError as e:
            sender.upload = None
            sender._notice(f'服务器无法创建临时文件：{e}')
            return
        sender.upload = {'fid': str(obj.get('fid') or ''), 'name': name, 'kind': kind,
                         'size': size, 'path': path, 'fh': fh, 'written': 0, 'conv': conv}

    def abort_upload(self, sender):
        up = sender.upload
        sender.upload = None
        if not up:
            return
        try:
            up['fh'].close()
        except Exception:
            pass
        try:
            os.remove(up['path'])
        except OSError:
            pass

    def push_chunk(self, sender, obj):
        up = sender.upload
        if not up or str(obj.get('fid') or '') != up['fid']:
            return
        try:
            data = base64.b64decode(obj.get('data') or '')
        except Exception:
            return
        if up['written'] + len(data) > up['size']:
            self.abort_upload(sender)
            return
        try:
            up['fh'].write(data)
            up['written'] += len(data)
        except OSError:
            self.abort_upload(sender)

    def finish_upload(self, sender, obj):
        up = sender.upload
        sender.upload = None
        if not up:
            return
        try:
            up['fh'].close()
        except Exception:
            pass
        if str(obj.get('fid') or '') != up['fid'] or up['written'] != up['size']:
            try:
                os.remove(up['path'])
            except OSError:
                pass
            sender._notice('文件传输不完整，请重试')
            return
        if up['conv'] == CONV_AVATAR:
            self._finish_avatar(sender, up)
            return
        group_gid = up['conv'][2:] if conv_kind(up['conv']) == 'group' else ''
        stored_name = ''
        if group_gid:
            # 群文件是长期保存的：从临时目录挪到 data/group_files/<群号>/ 下
            safe = ''.join(c for c in up['name'] if c not in '\\/:*?"<>|') or 'file'
            stored_name = f'{up["fid"][:8]}_{safe}'
            dest = os.path.join(self.group_files_dir(group_gid), stored_name)
            try:
                os.replace(up['path'], dest)
                up['path'] = dest
            except OSError:
                pass
        with self.lock:
            self.files[up['fid']] = {'conv': up['conv'], 'from': sender.nick, 'name': up['name'],
                                     'kind': up['kind'], 'size': up['size'],
                                     'time': now_ts(), 'path': up['path'],
                                     'pin': bool(group_gid),
                                     'file': stored_name}
            self.file_order.append(up['fid'])
            self._evict_files()
        msg = {'t': 'file_msg', 'conv': up['conv'], 'fid': up['fid'], 'from': sender.nick,
               'region': sender.region, 'name': up['name'], 'kind': up['kind'],
               'size': up['size'], 'time': now_ts()}
        self.add_history(up['conv'], msg)
        # 群里的文件同时登记进「群文件」，之后随时能翻出来下载
        if group_gid:
            self.social.add_group_file(group_gid, dict(msg, by=sender.nick,
                                                       file=stored_name))
            self.group_push(group_gid)
        if conv_kind(up['conv']) == 'friend':
            self._deliver_file_pm(sender, up['conv'], msg)
        else:
            for cs in self.conv_targets(up['conv'], exclude_sid=sender.sid):
                cs._send(msg)
        sender._send(dict(msg, self=True))

    def _deliver_file_pm(self, sender, conv, msg):
        """好友私聊里的文件 / 图片：对方也必须收到。

        以前这里直接用 conv_targets() 找收件人，而 conv_targets() 只认识
        「大厅 / 群聊」，对好友会话返回空 —— 结果私聊发的图片和文件只回显给了
        发送者自己，对方永远收不到（用户报的「截图发出去对面看不到」就是这个）。
        和 friend_message() 一样：发给对方时要用**对方视角的会话号**，
        并且同时写进对方的历史，离线的话上线拉历史也看得到。
        """
        peer = str(conv)[2:]
        if not peer or not self.social.are_friends(sender.nick, peer):
            return
        conv_b = conv_user(sender.nick)          # 对方看到的会话 id
        to_peer = dict(msg, conv=conv_b)
        self.add_history(conv_b, to_peer)
        tgt = self.session_of(peer)
        if tgt is not None:
            tgt._send(to_peer)
        self.log(f'📎 「{sender.nick}」→「{self.social.display(peer)}」'
                 f'{"（对方离线，已存历史）" if tgt is None else ""}')

    # ---------- 头像 ----------
    def _finish_avatar(self, sender, up):
        """把刚上传的图片落到 avatars/ 下，版本号 +1，然后广播给所有人。"""
        ver = self.social.avatar_ver(sender.nick) + 1
        dest = self.avatar_path(sender.nick, ver)
        try:
            os.replace(up['path'], dest)
        except OSError:
            if not os.path.isfile(dest):
                sender._notice('服务器保存头像失败')
                try:
                    os.remove(up['path'])
                except OSError:
                    pass
                return
        self.social.set_avatar(sender.nick, ver)
        sender._notice('头像已更新')
        self.broadcast({'t': 'avatar', 'nick': sender.nick, 'ver': ver})
        sender._send({'t': 'avatar', 'nick': sender.nick, 'ver': ver})
        self.log(f'☺ {sender.nick} 更新了头像    （{self.counts()}）')

    def avatar_get(self, cs, nick, ver=None):
        """把某个人的头像发给请求者（走和文件一样的分块通道）。"""
        who = (nick or '').strip()
        cur = self.social.avatar_ver(who)
        if not who or cur <= 0:
            return
        try:
            want = int(ver) if ver is not None and str(ver) != '' else cur
        except (TypeError, ValueError):
            want = cur
        if want != cur:
            # 版本对不上：直接告诉客户端最新版本，让它重新请求
            cs._send({'t': 'avatar', 'nick': self.social.display(who), 'ver': cur})
            return
        path = self.avatar_path(who, cur)
        if not os.path.isfile(path):
            return
        rec = {'conv': CONV_AVATAR, 'from': self.social.display(who),
               'name': f'{self.social.display(who)}.png', 'kind': 'image',
               'size': os.path.getsize(path), 'time': now_ts(), 'path': path}
        fid = f'{AVATAR_FID_PREFIX}{who.lower()}:{cur}'
        threading.Thread(target=self._send_file_worker, args=(cs, fid, rec),
                         daemon=True).start()

    def _evict_files(self):
        """超限就淘汰最旧的临时文件；群文件（pin=True）长期保留，不参与淘汰。"""
        def over():
            return (len(self.file_order) > FILE_CACHE_COUNT
                    or self._file_bytes() > FILE_CACHE_BYTES)

        while self.file_order and over():
            victim = None
            for fid in list(self.file_order):
                rec = self.files.get(fid)
                if rec is not None and not rec.get('pin'):
                    victim = fid
                    break
            if victim is None:
                break        # 剩下的全是群文件：宁可占点空间也不删
            self.file_order.remove(victim)
            rec = self.files.pop(victim, None)
            if rec:
                try:
                    os.remove(rec['path'])
                except OSError:
                    pass

    def _file_bytes(self):
        return sum(r['size'] for r in self.files.values())

    def send_file(self, cs, fid):
        with self.lock:
            rec = self.files.get(fid)
            rec = dict(rec) if rec else None
        if rec is None:
            rec = self.group_file_record(cs, fid)   # 服务端重启后仍能从群文件记录里恢复
        if not rec or not os.path.isfile(rec['path']):
            cs._notice('该文件已过期或不存在，无法获取')
            return
        if not self.can_access_conv(cs, rec['conv']):
            cs._notice('你没有该文件的访问权限')
            return
        threading.Thread(target=self._send_file_worker, args=(cs, fid, rec), daemon=True).start()

    def group_files_dir(self, gid):
        d = os.path.join(self.data_dir, 'group_files', conv_filename(gid))
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def group_file_record(self, cs, fid):
        """在「我所在的群」的群文件里找这个 fid；找到就拼出可下载的记录。"""
        for g in self.social.groups_of(cs.nick):
            for f in (g.get('files') or []):
                if f.get('fid') != fid:
                    continue
                name = f.get('file') or f.get('name') or 'file'
                path = os.path.join(self.group_files_dir(g['gid']), name)
                if not os.path.isfile(path):
                    return None
                return {'conv': conv_group(g['gid']), 'from': f.get('from', ''),
                        'name': f.get('name', name), 'kind': f.get('kind', 'file'),
                        'size': int(f.get('size') or 0), 'time': f.get('time', 0),
                        'path': path, 'pin': True}
        return None

    def _send_file_worker(self, cs, fid, rec):
        size = rec['size']
        total = (size + FILE_CHUNK_RAW - 1) // FILE_CHUNK_RAW
        ch = cs.channel
        ch.send_json({'t': 'file_info', 'fid': fid, 'conv': rec['conv'], 'name': rec['name'],
                      'kind': rec['kind'], 'size': size, 'total': total,
                      'from': rec['from'], 'time': rec['time']})
        try:
            with open(rec['path'], 'rb') as f:
                i = 0
                while True:
                    chunk = f.read(FILE_CHUNK_RAW)
                    if not chunk:
                        break
                    while ch.pending() > 256 and not ch.dead and not cs.stop_flag.is_set():
                        time.sleep(0.01)
                    if ch.dead or cs.stop_flag.is_set():
                        return
                    ch.send_json({'t': 'file_chunk', 'fid': fid, 'i': i, 'total': total,
                                  'data': base64.b64encode(chunk).decode('ascii')})
                    i += 1
        except OSError:
            pass

    def cleanup_files(self):
        with self.lock:
            recs = [r for r in self.files.values() if not r.get('pin')]
            self.files.clear()
            self.file_order.clear()
        for r in recs:
            try:
                os.remove(r['path'])
            except OSError:
                pass

    # ---------- 断开 ----------
    def drop(self, sid, text=None):
        with self.lock:
            cs = self.clients.pop(sid, None)
            if cs is None:
                return
            ip = cs.addr[0]
            if cs.counted and self._ip_counts.get(ip, 0) > 0:
                self._ip_counts[ip] -= 1
        cs.stop_flag.set()
        cs.channel.close()
        self.abort_upload(cs)
        if cs.authenticated:
            self.chess_player_dropped(cs.nick)
            if text:
                full = f'{text}（{cs.region}）'
                self.add_history(CONV_ROOM, {'t': 'system', 'kind': 'leave', 'conv': CONV_ROOM,
                                             'text': full, 'time': now_ts()})
                self.broadcast({'t': 'system', 'kind': 'leave', 'conv': CONV_ROOM,
                                'text': full, 'time': now_ts()})
            self.push_users()
            self.notify_presence(cs.nick, False)
            self.log(f'○ {cs.nick} 下线    （{self.counts()}）')

    def kick(self, nick):
        target = self.session_of(nick)
        if target is None:
            print(f'用户「{nick}」不在线')
            return
        target._notice('你已被管理员移出')
        self.drop(target.sid, f'{nick} 被管理员移出')
        print(f'已踢出「{nick}」')

    def shutdown(self):
        self.stop.set()
        for cs in self.sessions():
            if cs.authenticated:
                cs._send({'t': 'system', 'kind': 'notice', 'conv': CONV_ROOM,
                          'text': '服务器已关闭', 'time': now_ts()})
        time.sleep(0.2)
        for cs in self.sessions():
            cs.channel.close()
            self.abort_upload(cs)
        self.cleanup_files()
        try:
            self.sock.close()
        except OSError:
            pass


# ---------- 控制台入口 ----------
def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith('127.'):
                ips.append(ip)
    except OSError:
        pass
    return ips or ['127.0.0.1']


DEFAULT_CONFIG = {'port': 26000, 'room': '公共大厅', 'geo_lookup': True,
                 'public_ip': '', 'super_admins': [],
                 'geo_api': '', 'geo_overrides': {}}


def config_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'server_config.json')


def load_config(path):
    try:
        # utf-8-sig：记事本存 UTF-8 会带 BOM，用普通 utf-8 读会直接解析失败
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        cfg = dict(DEFAULT_CONFIG)
        for k in DEFAULT_CONFIG:
            if k in data:
                cfg[k] = data[k]
        return cfg
    except Exception:
        return None


def save_config(path, cfg):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def main():
    try:
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=f'{APP_NAME} 服务端')
    ap.add_argument('--port', type=int, default=None, help='监听端口（覆盖配置文件）')
    ap.add_argument('--room', default=None, help='公共大厅名称')
    ap.add_argument('--host', default='0.0.0.0', help='监听地址（默认 0.0.0.0）')
    args = ap.parse_args()

    path = config_path()
    cfg = load_config(path)
    first_run = cfg is None
    if first_run:
        cfg = dict(DEFAULT_CONFIG)
    if args.port is not None:
        cfg['port'] = args.port
    if args.room is not None:
        cfg['room'] = args.room
    if first_run:
        save_config(path, cfg)

    base = os.path.dirname(os.path.abspath(path))
    data_path = os.path.join(base, 'social_data.json')

    # 可选：自定义属地接口（机房出网受限时用得上）
    if set_custom_api(cfg.get('geo_api') or ''):
        print(f'  属地接口：使用自定义接口 {cfg.get("geo_api")}')
    n_ov = set_overrides(cfg.get('geo_overrides') or {})
    if n_ov:
        print(f'  属地修正：手工指定了 {n_ov} 条（geo_overrides）')

    srv = Server(args.host, cfg['port'], cfg['room'], data_path,
                 geo_lookup=bool(cfg.get('geo_lookup', True)),
                 public_ip=cfg.get('public_ip', ''),
                 super_admins=cfg.get('super_admins') or [])
    srv.start()
    st = srv.social.stats()

    print('=' * 58)
    print(f'        {APP_NAME} 服务端已启动')
    print(f'  公共大厅：{cfg["room"]}')
    print(f'  端    口：{srv.port}')
    print('  局域网地址（客户端请填其中任意一个）：')
    for ip in lan_ips():
        print(f'      {ip}:{srv.port}')
    print('-' * 58)
    print(f'  配置文件：{path}')
    print(f'  账号数据：{data_path}')
    print(f'  启动时统计：账号 {st["accounts"]} 个    群组 {st["groups"]} 个')
    print(f'  IP 属地：强制展示（公网解析 {"开" if cfg.get("geo_lookup", True) else "关"}）')
    print('  本机对外 IP / 属地：启动后自动解析，并展示给所有客户端')
    supers = sorted(cfg.get('super_admins') or [])
    if supers:
        print('  超级管理员：' + '、'.join(str(x) for x in supers)
              + '（登录客户端后可打开「控制台」）')
    else:
        print('  超级管理员：未设置 —— 敲 admin add <昵称> 指定一个（或在 server_config.json 里写）')
    print('  控制台命令： users | stats | games | say <内容> | kick <昵称> | files | quit')
    print('  账号 / 群组 / 上下线 的变动会实时打印在下方 ↓')
    print('  按 Ctrl+C 或输入 quit 退出')
    print('=' * 58)

    def console():
        while not srv.stop.is_set():
            try:
                line = input()
            except EOFError:
                break
            except KeyboardInterrupt:
                srv.stop.set()
                break
            if line is None:
                continue
            cmd = line.strip()
            if not cmd:
                continue
            low = cmd.lower()
            if low in ('quit', 'exit'):
                srv.stop.set()
                break
            elif low in ('users', 'list'):
                users = srv.user_list()
                print(f'在线 {len(users)} 人：' + ('、'.join(u['nick'] for u in users) or '（无）'))
                print(f'  （{srv.counts()}）')
            elif low in ('stats', 'stat', '数据'):
                st2 = srv.social.stats()
                users = srv.user_list()
                print(f'账号 {st2["accounts"]} 个 · 群组 {st2["groups"]} 个 · 在线 {len(users)} 人'
                      f' · 头像 {len(srv.avatar_map())} 个'
                      f' · 离线留言 {srv.social.stats2()["online_offline"]} 条')
                print('  在线：' + ('、'.join(u['nick'] for u in users) or '（无）'))
                nicks = sorted(a['nick'] for a in srv.social.data['accounts'].values())
                show = '、'.join(nicks[:40]) + ('…' if len(nicks) > 40 else '')
                print('  账号：' + (show or '（无）'))
                for gid, g in srv.social.data['groups'].items():
                    members = '、'.join(srv.social.display(m) for m in g['members'])
                    extra = f' 群号 {group_no(gid)}'
                    if g.get('admins'):
                        extra += ' 管理员：' + '、'.join(srv.social.display(m)
                                                    for m in g['admins'])
                    if g.get('announce'):
                        extra += ' 有公告'
                    if g.get('files'):
                        extra += f' 群文件 {len(g["files"])} 个'
                    if g.get('joins'):
                        extra += f' 待审批 {len(g["joins"])} 人'
                    print(f'  群「{g["name"]}」（{len(g["members"])} 人）{extra}')
                    print(f'      {members}')
            elif low.startswith('say '):
                text = cmd[4:].strip()
                if text:
                    msg = {'t': 'system', 'kind': 'notice', 'conv': CONV_ROOM,
                           'text': f'[系统] {text}', 'time': now_ts()}
                    srv.add_history(CONV_ROOM, msg)
                    srv.broadcast(msg)
                    print('已广播')
            elif low.startswith('kick '):
                srv.kick(cmd[5:].strip())
            elif low == 'admin' or low.startswith('admin '):
                rest = cmd[5:].strip()
                sub = rest.split(None, 1)
                act = (sub[0].lower() if sub else 'list')
                arg = sub[1].strip() if len(sub) > 1 else ''
                if act in ('list', 'ls', '列表', ''):
                    names = sorted(srv.super_admins)
                    print('超级管理员 ' + str(len(names)) + ' 人：'
                          + ('、'.join(srv.social.display(n) for n in names) or '（无）'))
                    print('  加： admin add <昵称>    删： admin del <昵称>')
                    print('  也可以在 server_config.json 的 super_admins 里直接写')
                elif act in ('add', 'set', '添加'):
                    if not arg:
                        print('用法： admin add <昵称>')
                    else:
                        ok, n = srv.add_super(arg)
                        if ok:
                            cfg['super_admins'] = sorted(srv.super_admins)
                            save_config(path, cfg)
                            print(f'★ 已把「{n}」设为超级管理员（已写入配置文件，立刻生效）')
                            srv.log(f'★ {n} 被设为超级管理员')
                            srv.push_admin()
                        else:
                            print(n)
                elif act in ('del', 'remove', 'deladmin', '删除'):
                    ok, err = srv.del_super(arg)
                    if ok:
                        cfg['super_admins'] = sorted(srv.super_admins)
                        save_config(path, cfg)
                    print(f'已取消「{arg}」的超级管理员' if ok else err)
                else:
                    print('用法： admin [list | add <昵称> | del <昵称>]')
            elif low == 'bans' or low == '封禁列表':
                bans = srv.social.ban_list()
                if not bans:
                    print('当前没有被封禁的账号')
                for nick, b in bans.items():
                    if b['until']:
                        when = time.strftime('%Y-%m-%d %H:%M', time.localtime(b['until']))
                        left = max(1, int((b['until'] - now_ts()) // 60) + 1)
                        print(f'  {nick}：限时封禁至 {when}（约 {left} 分钟） 理由：{b["reason"]}')
                    else:
                        print(f'  {nick}：永久封禁 理由：{b["reason"]}')
            elif low.startswith('ban '):
                parts = cmd[4:].split(None, 2)
                if not parts:
                    print('用法： ban <昵称> [分钟数|0=永久] [理由]')
                else:
                    nick = parts[0]
                    try:
                        minutes = int(parts[1]) if len(parts) > 1 else 0
                    except ValueError:
                        minutes = 0
                    reason = parts[2] if len(parts) > 2 else ''
                    if srv.is_super(nick):
                        print('不能封禁超级管理员')
                    else:
                        ok, err = srv.social.set_ban(nick, minutes, reason, by='控制台')
                        if not ok:
                            print(err)
                        else:
                            tgt = srv.session_of(nick)
                            if tgt is not None:
                                text = srv.ban_text(nick)
                                tgt._send({'t': 'banned', 'nick': nick,
                                           'reason': reason, 'text': text})
                                tgt._notice(text)
                                threading.Timer(0.8, lambda s=tgt.sid: srv.drop(s, None)).start()
                            how = '永久封禁' if minutes == 0 else f'封禁 {minutes} 分钟'
                            print(f'已{how}「{srv.social.display(nick)}」'
                                  + (f'，理由：{reason}' if reason else ''))
                            srv.log(f'⚑ 控制台 {how} {nick}')
                            srv.push_admin()
            elif low.startswith('unban '):
                nick = cmd[6:].strip()
                ok, err = srv.social.set_ban(nick, -1)
                print(f'已解封「{nick}」' if ok else err)
                srv.push_admin()
            elif low.startswith('geoset'):
                # geoset <IP> <属地>   手工指定；属地填 - 表示删除
                rest = cmd[6:].strip()
                parts = rest.split(None, 1)
                if len(parts) < 2 or not parts[0]:
                    print('用法： geoset <IP> <属地>     例如 geoset 1.2.3.4 福建 厦门')
                    print('       geoset <IP> -          删掉这条修正')
                else:
                    ip, region = parts[0], parts[1].strip()
                    if region == '-':
                        set_override(ip, '')
                        clear_ip(ip)
                        print(f'已删除 {ip} 的属地修正')
                    else:
                        set_override(ip, region)
                        clear_ip(ip)
                        print(f'已把 {ip} 的属地固定为「{region}」'
                              f'（立刻生效；写进配置文件请用 geo save）')
                    # 该 IP 上的在线用户立刻刷新
                    changed = 0
                    for cs in srv.sessions():
                        if cs.authenticated and cs.addr[0] == ip:
                            cs.region = region if region != '-' else \
                                region_for(ip, srv.geo_lookup)
                            changed += 1
                    if changed:
                        srv.push_users()
                        srv.push_social_all()
                        print(f'  已刷新 {changed} 个在线用户的属地')
            elif low == 'geo save':
                cfg['geo_overrides'] = geo_overrides()
                save_config(path, cfg)
                print(f'已把 {len(cfg["geo_overrides"])} 条属地修正写进配置文件')
            elif low.startswith('geo'):
                arg = cmd[3:].strip()
                if not arg:
                    print('用法： geo <IP>          逐个数据源查这个 IP 的属地')
                    print('      geo self         查本机对外 IP 的属地')
                    print('      geoset <IP> <属地>  手工修正某个 IP 的属地（- 删除）')
                    print('      geo save         把修正写进 server_config.json')
                    ov = geo_overrides()
                    print(f'  当前设置：geo_lookup={"开" if srv.geo_lookup else "关"}'
                          f'   本机属地={srv.server_region or "（未解析出来）"}'
                          f'   手工修正 {len(ov)} 条')
                    for k, v in list(ov.items())[:8]:
                        print(f'    · {k} → {v}')
                else:
                    target = srv.server_ip if arg == 'self' else arg
                    if not target:
                        print('还没解析出本机对外 IP，稍后再试')
                    else:
                        clear_ip(target)
                        print(f'逐个数据源查询 {target}：')
                        for name, cost, info, err in geo_probe(target):
                            if info:
                                print(f'  ✓ {name:12} {cost:4.2f}s  '
                                      f'{format_region(info)}   {info.get("isp") or ""}')
                            else:
                                print(f'  ✗ {name:12} {cost:4.2f}s  {err}')
                        got = region_for(target, True, budget=8.0)
                        vt = geo_votes()
                        print(f'  → 最终采用：{got}' + (f'   （票数：{vt}）' if vt else ''))
            elif low == 'files':
                with srv.lock:
                    n = len(srv.files)
                    b = srv._file_bytes()
                pinned = sum(1 for r in srv.files.values() if r.get('pin'))
                print(f'文件缓存：{n} 个（其中群文件 {pinned} 个长期保留），共 {human_size(b)}')
                print(f'头像目录：{srv.avatar_dir_path}')
                print(f'历史目录：{srv.history_dir}')
            elif low in ('games', 'chess', '棋局'):
                act = srv.active_games()
                print(f'进行中的棋局 {len(act)} 局（服务端共记录 {len(srv.games)} 局）')
                for g in act:
                    pend = ''
                    if g.pending:
                        pend = f"  [待确认：{'和棋' if g.pending['kind'] == 'draw' else '悔棋'}]"
                    print(f'  {g.red}(红) vs {g.black}(黑)  已走 {len(g.moves)} 手  '
                          f'轮到{side_name(g.turn)}{pend}')
                if not act:
                    print('  （无）')
                if srv.challenges:
                    print('  待回应的约战：'
                          + '、'.join(f'{c["from_nick"]}→{c["to"]}'
                                      for c in srv.challenges.values()))
            elif low == 'help':
                print('users            查看在线列表')
                print('stats            查看账号 / 群组 / 在线的完整快照（含群号、管理员、群文件）')
                print('games            查看正在进行的象棋对局')
                print('say <内容>       在公共大厅以系统身份广播')
                print('kick <昵称>      踢出某用户')
                print('admin [list|add <昵称>|del <昵称>]   管理超级管理员')
                print('ban <昵称> [分钟|0=永久] [理由]      封号（0 或不填=永久）')
                print('unban <昵称>     解封')
                print('bans             查看当前封禁列表')
                print('geo [<IP>|self]  逐个数据源查属地（排查「为什么显示属地未知」）')
                print('geoset <IP> <属地>  手工修正某个 IP 的属地（属地填 - 删除）')
                print('geo save         把手工修正写进 server_config.json')
                print('files            查看文件缓存 / 群文件 / 头像 / 历史目录')
                print('quit             退出服务端')
            else:
                print('未知命令，输入 help 查看')

    threading.Thread(target=console, daemon=True).start()
    try:
        while not srv.stop.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        srv.stop.set()
    srv.shutdown()
    print('服务端已退出')


if __name__ == '__main__':
    main()
