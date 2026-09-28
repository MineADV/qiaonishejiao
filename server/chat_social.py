"""悄匿社交 —— 服务端账号 / 好友 / 群组数据（JSON 持久化）。

- 账号：昵称全服唯一（不区分大小写），只保存 salt 与 PBKDF2 派生结果，不保存明文密码
- 头像：只存「版本号」，图片本体放在服务端 avatars/ 目录（见 chat_server）
- 好友：双向好友表 + 待处理申请 + **离线留言**（好友不在线时先存服务端，登录后送达）
- 群组：群名、群号（= gid）、群主、成员、管理员、禁言表、群公告、群文件、加群申请
"""
import base64
import json
import os
import secrets
import threading

from chat_common import (
    derive_key_salted, nick_error, now_ts,
    PASSWORD_MIN, MAX_GROUP_MEMBERS, MAX_GROUPS_PER_USER,
    GROUP_ANNOUNCE_MAX, GROUP_JOIN_MSG_MAX, GROUP_FILES_MAX,
    OFFLINE_MAX, OFFLINE_TTL,
)


def _low(nick):
    return (nick or '').strip().lower()


def group_no(gid):
    """群号的展示形式：6 位数字（真正的 id 还是 gid 字符串）。"""
    try:
        return '%06d' % int(gid)
    except (TypeError, ValueError):
        return str(gid or '')


def parse_group_no(text):
    """把用户输入的群号转成内部 gid；非法返回 ''。"""
    s = str(text or '').strip()
    if not s.isdigit():
        return ''
    try:
        return str(int(s))
    except ValueError:
        return ''


class Social:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = self._empty()
        self.load()
        self._migrate()

    @staticmethod
    def _empty():
        return {'accounts': {}, 'friends': {}, 'requests': {}, 'groups': {},
                'next_gid': 1, 'offline': {}, 'bans': {}, 'blocks': {}}

    # ---------- 持久化 ----------
    def load(self):
        try:
            # utf-8-sig：兼容带 BOM 的文件（手改过 social_data.json 时很常见）
            with open(self.path, 'r', encoding='utf-8-sig') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                d = self._empty()
                for k in d:
                    if k in raw:
                        d[k] = raw[k]
                self.data = d
        except Exception:
            pass

    def _migrate(self):
        """老数据补字段：账号头像版本、群的公告/管理员/禁言/群文件/申请。"""
        changed = False
        for a in self.data['accounts'].values():
            for k, v in (('avatar', 0),):
                if k not in a:
                    a[k] = v
                    changed = True
        for gv in self.data['groups'].values():
            for k, v in (('announce', None), ('admins', []), ('mutes', {}),
                         ('files', []), ('joins', []), ('invites', [])):
                if k not in gv:
                    gv[k] = v
                    changed = True
        if 'offline' not in self.data:
            self.data['offline'] = {}
            changed = True
        if 'bans' not in self.data:
            self.data['bans'] = {}
            changed = True
        if 'blocks' not in self.data:      # 黑名单
            self.data['blocks'] = {}
            changed = True
        if changed:
            self.save()

    def save(self):
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    # ---------- 账号 ----------
    def get(self, nick):
        return self.data['accounts'].get(_low(nick))

    def exists(self, nick):
        return _low(nick) in self.data['accounts']

    def display(self, nick):
        acct = self.get(nick)
        return acct['nick'] if acct else (nick or '').strip()

    def account_key(self, nick):
        acct = self.get(nick)
        if not acct:
            return None
        try:
            return base64.b64decode(acct['key'])
        except Exception:
            return None

    def register(self, nick, password):
        """注册：昵称全服查重。返回 (ok, err)。"""
        nick = (nick or '').strip()
        err = nick_error(nick)
        if err:
            return False, err
        if len(password or '') < PASSWORD_MIN:
            return False, f'密码至少 {PASSWORD_MIN} 位'
        with self.lock:
            k = _low(nick)
            if k in self.data['accounts']:
                return False, '该昵称已被注册，请换一个'
            salt = secrets.token_bytes(16)
            key = derive_key_salted(password, salt)
            self.data['accounts'][k] = {
                'nick': nick,
                'salt': base64.b64encode(salt).decode(),
                'key': base64.b64encode(key).decode(),
                'created': now_ts(),
                'last_seen': 0,
                'avatar': 0,
            }
            self.data['friends'].setdefault(k, [])
            self.save()
        return True, ''

    def touch(self, nick):
        """记一下这个账号最近一次在线时间（超管面板要看）。"""
        a = self.get(nick)
        if not a:
            return
        with self.lock:
            a['last_seen'] = now_ts()
            self.save()

    # ---------- 封号 ----------
    def ban_info(self, nick):
        """返回 (是否封禁中, 到期时间戳(0=永久), 理由)。到期的封禁会自动清掉。"""
        k = _low(nick)
        rec = self.data['bans'].get(k)
        if not rec:
            return False, 0, ''
        try:
            until = float(rec.get('until') or 0)
        except (TypeError, ValueError):
            until = 0
        if until and now_ts() >= until:
            with self.lock:
                self.data['bans'].pop(k, None)
                self.save()
            return False, 0, ''
        return True, int(until), str(rec.get('reason') or '')

    def is_banned(self, nick):
        return self.ban_info(nick)[0]

    def set_ban(self, nick, minutes, reason='', by=''):
        """minutes > 0 限时封号；0 = 永久；< 0 = 解封。返回 (ok, err)。"""
        k = _low(nick)
        if k not in self.data['accounts']:
            return False, '该用户不存在'
        with self.lock:
            if minutes is None or int(minutes) < 0:
                self.data['bans'].pop(k, None)
            else:
                m = int(minutes)
                self.data['bans'][k] = {
                    'until': 0 if m == 0 else now_ts() + m * 60,
                    'reason': (reason or '').strip()[:200],
                    'by': by or '',
                    'time': now_ts(),
                }
            self.save()
        return True, ''

    def ban_list(self):
        out = {}
        for k in list(self.data['bans']):
            on, until, reason = self.ban_info(k)
            if on:
                out[self.display(k)] = {'until': until, 'reason': reason}
        return out

    # ---------- 给超级管理员看的全量快照 ----------
    def all_users(self, region_of=None):
        """所有注册用户的信息（属地 / 群聊 / 封禁状态 等）。"""
        online = set(region_of.keys()) if region_of else set()
        out = []
        for k, a in self.data['accounts'].items():
            nick = a.get('nick') or k
            on, until, reason = self.ban_info(k)
            out.append({
                'nick': nick,
                'created': int(a.get('created') or 0),
                'last_seen': int(a.get('last_seen') or 0),
                'avatar': int(a.get('avatar') or 0),
                'online': nick in online,
                'region': (region_of or {}).get(nick, ''),
                'friends': [self.display(x) for x in self.data['friends'].get(k, [])],
                'groups': [{'gid': gid, 'no': group_no(gid),
                            'name': (self.data['groups'].get(gid) or {}).get('name', '')}
                           for gid, gv in self.data['groups'].items() if k in gv['members']],
                'banned': on,
                'ban_until': until,
                'ban_reason': reason,
            })
        out.sort(key=lambda u: (not u['online'], u['nick'].lower()))
        return out

    def all_groups(self):
        """所有已建立的群聊。"""
        out = []
        for gid, gv in self.data['groups'].items():
            members = [self.display(m) for m in gv['members']]
            out.append({
                'gid': gid,
                'no': group_no(gid),
                'name': gv.get('name', ''),
                'owner': self.display(gv.get('owner', '')),
                'created': int(gv.get('created') or 0),
                'members': members,
                'admins': [self.display(m) for m in (gv.get('admins') or [])],
                'mutes': {self.display(m): self.is_muted(gid, m)
                          for m in (gv.get('mutes') or {})},
                'files': len(gv.get('files') or []),
                'joins': len(gv.get('joins') or []),
                'announce': ((gv.get('announce') or {}).get('text') or ''),
            })
        out.sort(key=lambda g: g['no'])
        return out

    def stats(self):
        return {'accounts': len(self.data['accounts']), 'groups': len(self.data['groups'])}

    def search(self, prefix, limit=20):
        p = _low(prefix)
        out = []
        for k, a in self.data['accounts'].items():
            if p and p in k:
                out.append(a['nick'])
                if len(out) >= limit:
                    break
        return out

    # ---------- 头像 ----------
    def avatar_ver(self, nick):
        a = self.get(nick)
        try:
            return int(a.get('avatar') or 0) if a else 0
        except (TypeError, ValueError):
            return 0

    def avatar_map(self):
        """昵称 → 头像版本号（只包含有头像的人）。"""
        out = {}
        for a in self.data['accounts'].values():
            try:
                v = int(a.get('avatar') or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                out[a['nick']] = v
        return out

    def set_avatar(self, nick, ver):
        k = _low(nick)
        a = self.data['accounts'].get(k)
        if not a:
            return False
        with self.lock:
            a['avatar'] = int(ver)
            self.save()
        return True

    # ---------- 好友 ----------
    def friends(self, nick):
        return list(self.data['friends'].get(_low(nick), []))

    def friend_nicks(self, nick):
        return [self.display(k) for k in self.friends(nick)]

    def are_friends(self, a, b):
        return _low(b) in self.data['friends'].get(_low(a), [])

    def requests(self, nick):
        out = []
        for r in self.data['requests'].get(_low(nick), []):
            out.append({'from': self.display(r.get('from')), 'time': r.get('time', 0),
                        'msg': r.get('msg', '')})
        return out

    def add_friend_request(self, frm, to, msg=''):
        f, t = _low(frm), _low(to)
        if not t:
            return False, '请填写对方昵称'
        if f == t:
            return False, '不能加自己为好友'
        if t not in self.data['accounts']:
            return False, '该昵称不存在'
        if self.are_friends(f, t):
            return False, '你们已经是好友了'
        if self.blocked_between(f, t):
            return False, '对方已把你拉黑，无法发送好友申请'
        msg = (msg or '').strip()[:100]
        with self.lock:
            reqs = self.data['requests'].setdefault(t, [])
            if any(r.get('from') == f for r in reqs):
                return False, '已发送过申请，等待对方同意'
            reqs.append({'from': f, 'time': now_ts(), 'msg': msg})
            self.save()
        return True, ''

    def accept_friend(self, me, other):
        a, b = _low(me), _low(other)
        if b not in self.data['accounts']:
            return False, '该昵称不存在'
        with self.lock:
            reqs = self.data['requests'].get(a, [])
            if not any(r.get('from') == b for r in reqs):
                return False, '没有来自该用户的申请'
            self.data['requests'][a] = [r for r in reqs if r.get('from') != b]
            fa = self.data['friends'].setdefault(a, [])
            fb = self.data['friends'].setdefault(b, [])
            if b not in fa:
                fa.append(b)
            if a not in fb:
                fb.append(a)
            self.save()
        return True, ''

    def reject_friend(self, me, other):
        a, b = _low(me), _low(other)
        with self.lock:
            self.data['requests'][a] = [r for r in self.data['requests'].get(a, [])
                                        if r.get('from') != b]
            self.save()
        return True, ''

    def remove_friend(self, me, other):
        a, b = _low(me), _low(other)
        if not self.are_friends(a, b):
            return False, '你们还不是好友'
        with self.lock:
            for x, y in ((a, b), (b, a)):
                lst = self.data['friends'].get(x, [])
                if y in lst:
                    lst.remove(y)
            self.data['requests'][a] = [r for r in self.data['requests'].get(a, [])
                                        if r.get('from') != b]
            self.save()
        return True, ''

    # ---------- 黑名单 ----------
    def block_list(self, nick):
        """我拉黑的人（显示名）。"""
        return [self.display(k) for k in self.data.get('blocks', {}).get(_low(nick), [])]

    def blocked(self, me, other):
        """我有没有拉黑对方。"""
        return _low(other) in self.data.get('blocks', {}).get(_low(me), [])

    def blocked_between(self, a, b):
        """任一方被另一方拉黑 —— 这种关系下不许私聊。"""
        return self.blocked(a, b) or self.blocked(b, a)

    def set_block(self, me, other, on=True):
        a, b = _low(me), _low(other)
        if not b or b not in self.data['accounts']:
            return False, '该昵称不存在'
        if a == b:
            return False, '不能拉黑自己'
        with self.lock:
            lst = self.data.setdefault('blocks', {}).setdefault(a, [])
            if on:
                if b not in lst:
                    lst.append(b)
                # 拉黑的同时把双方待处理的申请清掉
                self.data['requests'][a] = [r for r in self.data['requests'].get(a, [])
                                            if r.get('from') != b]
                self.data['requests'][b] = [r for r in self.data['requests'].get(b, [])
                                            if r.get('from') != a]
            elif b in lst:
                lst.remove(b)
            self.save()
        return True, ''

    # ---------- 离线留言（好友不在线时先存服务端） ----------
    def add_offline(self, to, msg):
        """给不在线的用户留一条消息。返回 (ok, 当前积压条数)。"""
        t = _low(to)
        if t not in self.data['accounts']:
            return False, 0
        now = now_ts()
        with self.lock:
            box = self.data['offline'].setdefault(t, [])
            box = [m for m in box if now - float(m.get('time') or 0) < OFFLINE_TTL]
            box.append(msg)
            if len(box) > OFFLINE_MAX:
                box = box[-OFFLINE_MAX:]
            self.data['offline'][t] = box
            self.save()
            return True, len(box)

    def take_offline(self, nick):
        """取出并清空某人的离线留言（登录时调用）。"""
        k = _low(nick)
        with self.lock:
            box = self.data['offline'].pop(k, [])
            if box:
                self.save()
        now = now_ts()
        return [m for m in box if now - float(m.get('time') or 0) < OFFLINE_TTL]

    def offline_count(self, nick):
        k = _low(nick)
        now = now_ts()
        return len([m for m in self.data['offline'].get(k, [])
                    if now - float(m.get('time') or 0) < OFFLINE_TTL])

    def stats2(self):
        """给控制台 stats 用的更完整快照。"""
        st = self.stats()
        st['online_offline'] = sum(len(v) for v in self.data['offline'].values())
        st['avatars'] = len(self.avatar_map())
        return st

    # ---------- 群组 ----------
    def group(self, gid):
        return self.data['groups'].get(str(gid))

    def group_members(self, gid):
        gv = self.group(gid)
        return list(gv['members']) if gv else []

    def in_group(self, gid, nick):
        gv = self.group(gid)
        return bool(gv) and _low(nick) in gv['members']

    def group_no(self, gid):
        return group_no(gid)

    def find_by_no(self, no):
        """按群号找群；支持 000123 / 123 两种写法。"""
        gid = parse_group_no(no)
        if not gid:
            return None, ''
        gv = self.group(gid)
        return (gv, gid) if gv else (None, '')

    def role(self, gid, nick):
        """群内角色：owner / admin / member / ''（不在群里）。"""
        gv = self.group(gid)
        k = _low(nick)
        if not gv or k not in gv['members']:
            return ''
        if gv.get('owner') == k:
            return 'owner'
        return 'admin' if k in (gv.get('admins') or []) else 'member'

    def can_manage(self, gid, actor):
        """能发布公告 / 审批加群 / 管成员的角色。"""
        return self.role(gid, actor) in ('owner', 'admin')

    def is_muted(self, gid, nick):
        """返回禁言剩余秒数；0 表示没被禁言，-1 表示永久禁言。"""
        gv = self.group(gid)
        if not gv:
            return 0
        rec = (gv.get('mutes') or {}).get(_low(nick))
        if not rec:
            return 0
        try:
            until = float(rec)
        except (TypeError, ValueError):
            return 0
        if until <= 0:
            return -1
        left = int(until - now_ts())
        if left <= 0:
            with self.lock:
                gv.get('mutes', {}).pop(_low(nick), None)
                self.save()
            return 0
        return left

    def groups_of(self, nick):
        k = _low(nick)
        out = []
        for gid, gv in self.data['groups'].items():
            if k in gv['members']:
                mine = self.role(gid, k)
                g = {'gid': gid, 'no': group_no(gid), 'name': gv['name'],
                     'owner': gv.get('owner') == k,
                     'admin': k in (gv.get('admins') or []),
                     'announce': gv.get('announce'),
                     'files': list(gv.get('files') or []),
                     'members': [self.display(m) for m in gv['members']]}
                # 加群申请只给有审批权的人看（主页要和好友申请一样能直接处理）
                joins = gv.get('joins') or []
                if mine in ('owner', 'admin') and joins:
                    g['joins'] = [{'from': self.display(r.get('from')),
                                   'msg': r.get('msg', ''),
                                   'time': r.get('time', 0)}
                                  for r in joins[:20]]
                # 拉人入群：管理员（含群主）要在这里看到「待批准」的
                inv = gv.get('invites') or []
                if mine in ('owner', 'admin') and inv:
                    g['invites'] = [self._invite_view(r, gid) for r in inv[:20]]
                out.append(g)
        return out

    def my_invites(self, nick):
        """别人拉我进群、还没经过我同意的邀请（客户端弹窗用）。"""
        k = _low(nick)
        out = []
        for gid, gv in self.data['groups'].items():
            for r in (gv.get('invites') or []):
                if r.get('nick') == k:
                    out.append(self._invite_view(r, gid))
        return out

    def _invite_view(self, r, gid):
        gv = self.group(gid) or {}
        return {'gid': str(gid), 'group': gv.get('name') or '群聊',
                'no': group_no(gid), 'nick': self.display(r.get('nick')),
                'by': self.display(r.get('by')), 'time': r.get('time', 0),
                'admin_ok': bool(r.get('admin_ok')), 'nick_ok': bool(r.get('nick_ok'))}

    def invite_to_group(self, gid, by, nick):
        """任何群成员都可以拉自己的好友入群（要管理员和被拉人双方同意）。"""
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        b, k = _low(by), _low(nick)
        if b not in gv['members']:
            return False, '你不在该群里'
        if not k or k not in self.data['accounts']:
            return False, '该昵称不存在'
        if k in gv['members']:
            return False, '对方已经在群里了'
        if len(gv['members']) >= MAX_GROUP_MEMBERS:
            return False, f'群人数已达上限 {MAX_GROUP_MEMBERS}'
        if b == k:
            return False, '不用拉自己'
        if not self.are_friends(b, k):
            return False, '只能拉自己的好友进群'
        with self.lock:
            inv = gv.setdefault('invites', [])
            if any(r.get('nick') == k for r in inv):
                return False, '已经邀请过对方了，等对方和管理员确认'
            inv.append({'nick': k, 'by': b, 'time': now_ts(),
                        'admin_ok': False, 'nick_ok': False,
                        # 拉人的人自己如果是管理员，就直接算管理员这一票
                        })
            self.save()
        # 拉人者自己就是群主/管理员时，管理员那一边无需再等
        if self.role(gid, b) in ('owner', 'admin'):
            with self.lock:
                for r in gv.get('invites') or []:
                    if r.get('nick') == k:
                        r['admin_ok'] = True
                self.save()
        return True, ''

    def answer_invite(self, gid, nick, who, accept, actor=''):
        """表态：who = 'admin'（群主/管理员）或 'nick'（被拉的人本人）。

        返回 (ok, err, done)；done=True 表示两边都同意、人已经进群了。
        任意一方拒绝 → 这条邀请直接作废。
        """
        gv = self.group(gid)
        if not gv:
            return False, '群不存在', False
        k = _low(nick)
        rec = None
        for r in (gv.get('invites') or []):
            if r.get('nick') == k:
                rec = r
                break
        if rec is None:
            return False, '这条邀请已经处理过了', False
        if who == 'admin':
            a = _low(actor)
            if a not in gv['members']:
                return False, '你不在该群里', False
        else:
            if _low(actor) != k:
                return False, '只有被邀请的人本人能同意', False
        with self.lock:
            if not accept:
                gv['invites'] = [r for r in (gv.get('invites') or [])
                                 if r.get('nick') != k]
                self.save()
                return True, '', False
            rec['admin_ok' if who == 'admin' else 'nick_ok'] = True
            both = bool(rec.get('admin_ok')) and bool(rec.get('nick_ok'))
            if both:
                gv['invites'] = [r for r in (gv.get('invites') or [])
                                 if r.get('nick') != k]
                if k not in gv['members'] and len(gv['members']) < MAX_GROUP_MEMBERS:
                    gv['members'].append(k)
            self.save()
        return True, '', both

    def add_member(self, gid, nick):
        """把（已经双方同意的）人真正加进群。"""
        gv = self.group(gid)
        k = _low(nick)
        if not gv or k in gv['members']:
            return False
        with self.lock:
            gv['members'].append(k)
            gv['joins'] = [r for r in (gv.get('joins') or []) if r.get('from') != k]
            self.save()
        return True

    def create_group(self, owner, name, members):
        o = _low(owner)
        name = (name or '').strip()[:24]
        if not name:
            return False, '群名称不能为空', None
        with self.lock:
            if len(self.groups_of(owner)) >= MAX_GROUPS_PER_USER:
                return False, f'最多加入 {MAX_GROUPS_PER_USER} 个群', None
            gid = str(self.data.get('next_gid', 1))
            self.data['next_gid'] = int(gid) + 1
            mem = [o]
            for m in members:
                mk = _low(m)
                if mk in self.data['accounts'] and mk not in mem:
                    mem.append(mk)
                if len(mem) >= MAX_GROUP_MEMBERS:
                    break
            self.data['groups'][gid] = {'name': name, 'owner': o,
                                        'members': mem, 'created': now_ts(),
                                        'announce': None, 'admins': [], 'mutes': {},
                                        'files': [], 'joins': []}
            self.save()
        return True, '', gid

    def add_to_group(self, gid, nick):
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        k = _low(nick)
        if k not in self.data['accounts']:
            return False, '该昵称不存在'
        if k in gv['members']:
            return False, '对方已在群里'
        if len(gv['members']) >= MAX_GROUP_MEMBERS:
            return False, f'群人数已达上限 {MAX_GROUP_MEMBERS}'
        with self.lock:
            gv['members'].append(k)
            gv['joins'] = [r for r in (gv.get('joins') or []) if r.get('from') != k]
            self.save()
        return True, ''

    # ---------- 群管理 ----------
    def member_list(self, gid):
        """带角色/禁言状态的成员列表（界面用）。"""
        gv = self.group(gid)
        if not gv:
            return []
        out = []
        for m in gv['members']:
            out.append({'nick': self.display(m),
                        'role': self.role(gid, m),
                        'mute': self.is_muted(gid, m)})
        return out

    def set_announce(self, gid, actor, text):
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        if not self.can_manage(gid, actor):
            return False, '只有群主或管理员可以发布公告'
        text = (text or '').strip()
        if len(text) > GROUP_ANNOUNCE_MAX:
            return False, f'公告最多 {GROUP_ANNOUNCE_MAX} 字'
        with self.lock:
            if text:
                gv['announce'] = {'text': text, 'by': self.display(actor),
                                  'time': now_ts()}
            else:
                gv['announce'] = None      # 空内容 = 清除公告
            self.save()
        return True, ''

    def set_admin(self, gid, actor, nick, on=True):
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        if gv.get('owner') != _low(actor):
            return False, '只有群主可以设置管理员'
        k = _low(nick)
        if k not in gv['members']:
            return False, '对方不在群里'
        if k == gv.get('owner'):
            return False, '群主不需要设为管理员'
        with self.lock:
            admins = gv.setdefault('admins', [])
            if on and k not in admins:
                admins.append(k)
            elif not on and k in admins:
                admins.remove(k)
            self.save()
        return True, ''

    def set_mute(self, gid, actor, nick, minutes):
        """minutes: >0 分钟数；0 永久；<0 解除禁言。"""
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        if not self.can_manage(gid, actor):
            return False, '只有群主或管理员可以禁言'
        k = _low(nick)
        if k not in gv['members']:
            return False, '对方不在群里'
        if k == gv.get('owner'):
            return False, '不能禁言群主'
        if self.role(gid, k) == 'admin' and gv.get('owner') != _low(actor):
            return False, '管理员不能禁言其他管理员'
        with self.lock:
            mutes = gv.setdefault('mutes', {})
            if minutes is None or int(minutes) < 0:
                mutes.pop(k, None)
            else:
                mutes[k] = 0 if int(minutes) == 0 else now_ts() + int(minutes) * 60
            self.save()
        return True, ''

    def kick(self, gid, actor, nick):
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        if not self.can_manage(gid, actor):
            return False, '只有群主或管理员可以移出成员'
        k = _low(nick)
        if k not in gv['members']:
            return False, '对方不在群里'
        if k == gv.get('owner'):
            return False, '不能移出群主'
        if self.role(gid, k) == 'admin' and gv.get('owner') != _low(actor):
            return False, '管理员不能移出其他管理员'
        with self.lock:
            gv['members'].remove(k)
            if k in (gv.get('admins') or []):
                gv['admins'].remove(k)
            (gv.get('mutes') or {}).pop(k, None)
            self.save()
        return True, ''

    # ---------- 加群申请 ----------
    def join_request(self, gid, nick, msg=''):
        gv = self.group(gid)
        if not gv:
            return False, '群号不存在，请检查后重试'
        k = _low(nick)
        if k in gv['members']:
            return False, '你已经在这个群里了'
        if len(gv['members']) >= MAX_GROUP_MEMBERS:
            return False, f'群人数已达上限 {MAX_GROUP_MEMBERS}'
        msg = (msg or '').strip()[:GROUP_JOIN_MSG_MAX]
        with self.lock:
            joins = gv.setdefault('joins', [])
            if any(r.get('from') == k for r in joins):
                return False, '已提交过申请，等待群主/管理员同意'
            joins.append({'from': k, 'msg': msg, 'time': now_ts()})
            self.save()
        return True, ''

    def join_requests(self, gid):
        gv = self.group(gid)
        if not gv:
            return []
        return [{'from': self.display(r.get('from')), 'key': r.get('from'),
                 'msg': r.get('msg', ''), 'time': r.get('time', 0)}
                for r in (gv.get('joins') or [])]

    def answer_join(self, gid, actor, nick, accept=True):
        gv = self.group(gid)
        if not gv:
            return False, '群不存在'
        if not self.can_manage(gid, actor):
            return False, '只有群主或管理员可以审批加群申请'
        k = _low(nick)
        joins = gv.get('joins') or []
        if not any(r.get('from') == k for r in joins):
            return False, '没有该申请'
        with self.lock:
            gv['joins'] = [r for r in joins if r.get('from') != k]
            if accept:
                if k not in gv['members'] and len(gv['members']) < MAX_GROUP_MEMBERS:
                    gv['members'].append(k)
            self.save()
        return True, ''

    # ---------- 群文件 ----------
    def add_group_file(self, gid, rec):
        gv = self.group(gid)
        if not gv:
            return False
        with self.lock:
            files = gv.setdefault('files', [])
            files[:] = [f for f in files if f.get('fid') != rec.get('fid')]
            files.insert(0, rec)
            del files[GROUP_FILES_MAX:]
            self.save()
        return True

    def remove_group_file(self, gid, fid):
        gv = self.group(gid)
        if not gv:
            return False
        with self.lock:
            gv['files'] = [f for f in (gv.get('files') or []) if f.get('fid') != fid]
            self.save()
        return True

    def group_file(self, gid, fid):
        for f in (self.group(gid) or {}).get('files') or []:
            if f.get('fid') == fid:
                return f
        return None

    def leave_group(self, gid, nick):
        gv = self.group(gid)
        k = _low(nick)
        if not gv or k not in gv['members']:
            return False, '你不在该群'
        with self.lock:
            gv['members'].remove(k)
            if k in (gv.get('admins') or []):
                gv['admins'].remove(k)
            (gv.get('mutes') or {}).pop(k, None)
            if not gv['members']:
                self.data['groups'].pop(str(gid), None)
            elif gv.get('owner') == k:
                gv['owner'] = gv['members'][0]
            self.save()
        return True, ''
