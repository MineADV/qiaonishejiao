"""悄匿社交 —— 公共常量、报文编解码与加密工具。"""
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import struct
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------- 协议常量 ----------
MAGIC = b'DCHT'
VERSION = 1
# 报文头：magic(4) ver(1) kind(1) flags(1) rsv(1) seq(4) ack(4) sid(16) plen(2)
HEADER_FMT = '>4sBBBBII16sH'
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 34 字节

# 报文类型
K_DATA = 1  # 数据（携带应用层负载）
K_ACK = 2   # 纯确认
K_PING = 3  # 心跳探测
K_PONG = 4  # 心跳应答

# 标志位
F_ENC = 0x01   # 负载已加密
F_RESET = 0x02  # 要求对端重置会话

# 可靠性参数
# 重传超时按实测 RTT 自适应（类似 TCP）：跨洋链路 RTT 常在 200~400ms，
# 如果写死 150ms，每个包都会在 ACK 回来之前被判超时，进而引发重传风暴。
RTO_MIN = 0.20           # 重传超时下限（秒）
RTO_MAX = 4.0            # 重传超时上限
RTO_INITIAL = 0.60       # 还没有 RTT 采样时的初值（宁可保守一点，别一上来就风暴）
RTO_BACKOFF_CAP = 2      # 单个包最多退避 2^2 = 4 倍。
# 为什么不是 2^6：聊天消息常常是「这一批的最后一个包」，一旦它丢了，
# 后面没有新包能触发快速重传，只能等退避计时器 —— 退避到 64 倍时
# 一次补发要等几十秒，用户看到的就是「消息卡住半天才发出去」。
TAIL_PROBE_MIN = 0.40    # 只差最后几个包时，最短补发间隔（秒）
TAIL_PROBE_MAX = 8       # 在途包不超过这个数才启用「尾包快速补发」
STARVE_GAP = 1.0         # 发送循环间隔超过这么久，说明本进程被饿住了（GC/杀软/CPU 抢占）
FAST_RESEND_DUPACK = 3   # 收到几个重复确认就立即重传缺口包
TICK = 0.005             # 发送循环间隔（有在途包/待发包时）
IDLE_TICK = 0.05         # 完全空闲时的循环间隔（省 CPU，心跳/重传都不受影响）
PACE_PER_TICK = 24       # 每个循环最多新发/补发多少包（削峰，避免一次性灌爆队列）
WINDOW = 128             # 滑动窗口：同时在途的数据包数（要够大才撑得起高延迟链路）
MAX_REORDER = 320        # 接收端乱序缓存上限（要大于窗口）
MAX_RETRIES = 0          # 0 = 永不放弃单个包，是否断开交给“无进展”判定
IDLE_PING = 3.0          # 空闲多久后发心跳（秒）
# 判死分两档：
#   SILENT_WARN  —— 只是「暂时收不到」，先在界面上提示「网络不稳，正在恢复」，
#                   不停连接、不锁输入框，照常重传，恢复后无缝继续；
#   DEAD_TIMEOUT —— 真的判死，才走重连/重新登录。
# 为什么要分开：跨洋链路、手机热点、NAT 抖动经常出现十几秒的黑洞。以前 20 秒
# 一到就直接判死重登，用户看到的就是「莫名其妙断开又重连」——明明再过几秒就通了。
SILENT_WARN = 8.0        # 多久没收到任何报文就先提示「网络不稳」（秒）
DEAD_TIMEOUT = 45.0      # 多久收不到任何报文才判死（秒）
NO_PROGRESS_TIMEOUT = 120.0   # 窗口长时间毫无确认进展才判死（秒）

MAX_PAYLOAD = 65000      # 单个 UDP 报文负载上限
MAX_TEXT = 2000          # 单条消息最大字符数
MAX_HISTORY = 100        # 公共大厅保留的历史消息数
MAX_CONV_HISTORY = 60    # 每个好友/群会话保留的历史消息数
GROUP_HISTORY_ON_JOIN = 30   # 新入群能看到的最近消息条数
HISTORY_KEEP = 200       # 落盘时每个会话最多留多少条（内存里只留 MAX_*_HISTORY）
MAX_CLIENTS = 200        # 服务端最大客户端数
MAX_PER_IP = 32          # 单个 IP 最多允许多少个「已登录」连接（NAT 后多设备共用公网 IP）
MAX_PENDING = 64         # 最多允许多少个「尚未登录」的连接（防止半开连接堆积）
AUTH_TIMEOUT = 20.0      # 未登录连接多久自动断开（秒）
MAX_GROUP_MEMBERS = 60   # 单个群人数上限
MAX_GROUPS_PER_USER = 30 # 每人最多加入多少个群
NICK_MIN, NICK_MAX = 2, 16
PASSWORD_MIN = 4         # 密码最短长度

# 头像（客户端会先缩到 256×256 再上传，这里再兜一道）
CONV_AVATAR = 'avatar'           # 头像上传/下载用的伪会话
AVATAR_MAX = 2 * 1024 * 1024     # 单张头像最大字节
AVATAR_SIDE = 256                # 头像统一缩放到这个边长
AVATAR_FID_PREFIX = 'av:'        # 头像下载用的伪文件 id

# 群管理
GROUP_ANNOUNCE_MAX = 500     # 群公告最大字符数
GROUP_JOIN_MSG_MAX = 100     # 加群申请留言最大字符数
GROUP_FILES_MAX = 100        # 每个群最多保留多少个「群文件」条目
MUTE_CHOICES = (('10 分钟', 10), ('1 小时', 60), ('1 天', 1440), ('永久', 0))
# 封号时长（分钟，0 = 永久）
BAN_CHOICES = (('10 分钟', 10), ('1 小时', 60), ('1 天', 1440), ('7 天', 10080),
               ('30 天', 43200), ('永久封禁', 0))
OFFLINE_MAX = 200            # 每人最多留存多少条离线留言
OFFLINE_TTL = 30 * 24 * 3600 # 离线留言保留 30 天

# 文件传输（磁盘流式，不占内存；不限制文件大小）
FILE_CHUNK_RAW = 1000                      # 每块原始字节（base64 后约 1.4 KB，单包不触发 IP 分片）
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024     # 4 GB（实际相当于不限制，仅防极端情况）
FILE_CACHE_COUNT = 50                      # 服务端最多保留多少个文件
FILE_INDEX_MAX = 400                       # 客户端本地文件索引最多记多少条
FILE_CACHE_BYTES = 4 * 1024 * 1024 * 1024  # 服务端文件缓存总量上限
FILE_INLINE_MAX = 24 * 1024 * 1024         # 超过此大小的图片不做内联缩略图

# ---------- 加密 / 认证 ----------
PBKDF2_ITER = 200_000


def derive_key_salted(password: str, salt: bytes) -> bytes:
    """账号密钥：PBKDF2-HMAC-SHA256(password, salt) → 32 字节。

    服务端只保存 salt 与派生结果；登录时密码不上网（用挑战-应答证明持有）。
    """
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITER, 32)


def auth_proof(key: bytes, nonce: bytes) -> str:
    """登录应答：HMAC(账号密钥, 'AUTH:' + 服务端随机数)。"""
    return hmac.new(key, b'AUTH:' + nonce, hashlib.sha256).hexdigest()


def tune_udp_socket(sock, bufsize: int = 4 * 1024 * 1024):
    """优化 UDP socket：放大收发缓冲；并在 Windows 上关闭 ICMP 引起的连接重置。

    对端刚关闭端口时，Windows 会把 ICMP 端口不可达回报成下一次 recvfrom 的
    WSAECONNRESET（OSError），若不处理会直接打断收包循环、导致服务端“假死”。
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, bufsize)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, bufsize)
    except OSError:
        pass
    try:
        sock.ioctl(socket.SIO_UDP_CONNRESET, False)
    except (AttributeError, OSError):
        pass


# ---------- 会话（conversation）标识 ----------
CONV_ROOM = 'room'

_CONV_FILE_RE = re.compile(r'[^0-9a-zA-Z_.-]+')


def conv_filename(conv) -> str:
    """把会话 / 昵称变成安全的文件名（room / u_xxx / g_12）。"""
    return _CONV_FILE_RE.sub('_', str(conv or 'x'))[:80] or 'x'


def conv_user(nick: str) -> str:
    """与某人的一对一会话 id（小写）。"""
    return 'u:' + (nick or '').lower()


def conv_group(gid) -> str:
    """群会话 id。"""
    return 'g:' + str(gid)


def conv_kind(conv) -> str:
    s = str(conv or '')
    if s == CONV_ROOM:
        return 'room'
    if s.startswith('g:'):
        return 'group'
    if s.startswith('u:'):
        return 'friend'
    return 'room'


def encrypt_payload(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_payload(key: bytes, data: bytes):
    """解密失败返回 None。"""
    try:
        nonce, ct = data[:12], data[12:]
        return AESGCM(key).decrypt(nonce, ct, None)
    except Exception:
        return None


# ---------- 报文编解码 ----------
def build_packet(kind: int, flags: int, seq: int, ack: int, sid: bytes, payload: bytes = b'') -> bytes:
    plen = len(payload)
    return struct.pack(HEADER_FMT, MAGIC, VERSION, kind, flags, 0, seq, ack, sid, plen) + payload


def parse_packet(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    magic, ver, kind, flags, _rsv, seq, ack, sid, plen = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    if magic != MAGIC or ver != VERSION:
        return None
    if plen > MAX_PAYLOAD or len(data) < HEADER_SIZE + plen:
        return None
    payload = data[HEADER_SIZE:HEADER_SIZE + plen]
    return {'kind': kind, 'flags': flags, 'seq': seq, 'ack': ack, 'sid': sid, 'payload': payload}


# ---------- JSON 负载 ----------
def encode_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def decode_json(data: bytes):
    return json.loads(data.decode('utf-8'))


# ---------- 校验 ----------
_NICK_RE = re.compile(r'^[\w\u4e00-\u9fff-]{%d,%d}$' % (NICK_MIN, NICK_MAX))
_RESERVED = {'系统', 'server', 'system', '所有人', 'all', 'admin', '管理员'}


def valid_nick(name: str) -> bool:
    n = (name or '').strip()
    if not _NICK_RE.match(n):
        return False
    if n.lower() in _RESERVED:
        return False
    return True


def nick_error(name: str) -> str:
    """返回昵称不合法的具体原因，合法时返回空串。"""
    n = (name or '').strip()
    if len(n) < NICK_MIN:
        return f'昵称至少 {NICK_MIN} 个字符'
    if len(n) > NICK_MAX:
        return f'昵称最多 {NICK_MAX} 个字符'
    if not _NICK_RE.match(n):
        return '昵称只能包含中文、字母、数字、下划线或短横线'
    if n.lower() in _RESERVED:
        return '该昵称是保留名，请换一个'
    return ''


def valid_text(text: str) -> bool:
    t = text.strip()
    return 0 < len(t) <= MAX_TEXT


# ---------- 服务器地址解析 ----------
_SCHEME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*://')


def normalize_host(text):
    """把用户填的地址收拾干净，返回 (主机, 端口或 None)。

    允许的写法（用户经常直接从浏览器复制）：
      `1.2.3.4` / `example.com` / `example.com:26000`
      `http://example.com:26000/` / `udp://example.com` / `[2001:db8::1]:26000`
    """
    s = (text or '').strip().strip('"\'')
    if not s:
        return '', None
    s = _SCHEME_RE.sub('', s)                 # 去掉 http:// 之类
    s = s.split('/')[0].split('?')[0].split('#')[0]   # 去掉路径/参数
    s = s.strip().rstrip('.')                 # 末尾的点（FQDN 写法）
    port = None
    if s.startswith('['):                     # [IPv6]:port
        host, _sep, rest = s[1:].partition(']')
        rest = rest.lstrip(':').strip()
        if rest.isdigit():
            port = int(rest)
        return host.strip(), port
    if s.count(':') == 1:                     # host:port（IPv6 会有多个冒号）
        host, _sep, rest = s.partition(':')
        if rest.isdigit():
            return host.strip(), int(rest)
    return s.strip(), None


def resolve_host(host, port):
    """解析服务器地址，返回候选列表 [(family, sockaddr), ...]。

    优先 IPv4：绝大多数玩家的网络和防火墙都是 IPv4，UDP 打洞也更省事。
    但**只有 AAAA 记录的域名**（纯 IPv6 的服务器很常见）也必须能用，
    所以拿 AF_INET 解析失败时要退回到 AF_UNSPEC 再试一次。
    """
    host = (host or '').strip()
    port = int(port)
    out = []
    seen = set()
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            infos = socket.getaddrinfo(host, port, family, socket.SOCK_DGRAM)
        except OSError:
            continue
        for info in infos:
            fam, sockaddr = info[0], info[4]
            key = (fam, sockaddr)
            if key in seen:
                continue
            seen.add(key)
            out.append((fam, sockaddr))
    if not out:
        # 再兜一次：某些系统只有 AF_UNSPEC 才肯给出答案
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_DGRAM)
        except OSError as e:
            raise socket.gaierror(
                f'域名「{host}」解析失败（本机 DNS 查不到它，或者只有 IPv6 记录）') from e
        for info in infos:
            fam, sockaddr = info[0], info[4]
            if (fam, sockaddr) not in seen:
                seen.add((fam, sockaddr))
                out.append((fam, sockaddr))
    if not out:
        raise socket.gaierror(f'域名「{host}」没有解析出任何可用地址')
    return out


# ---------- 时间 ----------
def now_ts() -> int:
    return int(time.time())


RECALL_WINDOW = 120        # 自己发的消息几分钟内可以撤回（群主/管理员撤成员不受限）


def new_mid() -> str:
    """给每条消息发一个唯一编号（撤回、去重都用它）。"""
    return '%x%s' % (int(time.time() * 1000) & 0xffffffffff,
                     secrets.token_hex(3))


def fmt_time(ts) -> str:
    return time.strftime('%H:%M:%S', time.localtime(ts))


# ---------- 文件 ----------
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tif', '.tiff'}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg'}


def file_kind(name: str) -> str:
    """按扩展名判断文件类型：image / video / file。"""
    ext = os.path.splitext(name or '')[1].lower()
    if ext in IMAGE_EXTS:
        return 'image'
    if ext in VIDEO_EXTS:
        return 'video'
    return 'file'


def human_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} GB'


# ---------- @提及 ----------
def parse_mentions(text: str, nicks) -> list:
    """在文本中找出被 @ 的昵称（优先匹配较长的昵称）。"""
    found = []
    for n in sorted({x for x in nicks if x}, key=len, reverse=True):
        if f'@{n}' in text and n not in found:
            found.append(n)
    return found
