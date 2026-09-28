"""悄匿社交 —— 终端命令行客户端（便于脚本化与测试）。

用法：
    py chat_cli.py --host 127.0.0.1 --port 26000 --nick 小明 --password 123456
    py chat_cli.py ... --register         # 先注册再登录

进入后直接输入内容回车发送到「公共大厅」；可用命令：
    /to <昵称> <内容>   给好友发私聊（需先加好友）
    /g <群号> <内容>    在群里发言
    /open <会话>        切换会话（room / u:昵称 / g:群号）
    /add <昵称>         发送好友申请
    /accept <昵称>      同意好友申请
    /group <群名> a,b   建群并拉 a、b 进来
    /friends            显示好友/群组
    /quit               退出
"""
import argparse
import queue
import sys
import threading
import time

from chat_common import fmt_time
from chat_client_core import ChatClient


def print_msg(m):
    ts = fmt_time(m.get('time', 0))
    t = m.get('t')
    conv = m.get('conv', 'room')
    if t == 'chat':
        tag = '私聊' if m.get('kind') == 'pm' else ('群' if m.get('kind') == 'group' else '大厅')
        print(f'[{tag}] {ts}  {m.get("from", "")}：{m.get("text", "")}')
    elif t == 'me':
        print(f'[大厅] {ts}  * {m.get("from", "")} {m.get("text", "")}')
    elif t == 'system':
        print(f'[系统] {ts}  {m.get("text", "")}')
    elif t == 'file_msg':
        print(f'[{conv}] {ts}  {m.get("from", "")} 发送了文件 {m.get("name", "")}')


def wait(c, etype, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            ev = c.events.get(timeout=0.2)
        except queue.Empty:
            continue
        if ev[0] == etype:
            return ev
    return None


def main():
    ap = argparse.ArgumentParser(description='悄匿社交 命令行客户端')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=26000)
    ap.add_argument('--nick', required=True)
    ap.add_argument('--password', required=True)
    ap.add_argument('--register', action='store_true', help='先注册账号再登录')
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass

    client = ChatClient(args.host, args.port)
    if args.register:
        client.register(args.nick, args.password)
        ev = wait(client, 'register_ok', 10) or wait(client, 'register_err', 3)
        if ev and ev[0] == 'register_err':
            print('注册失败：', ev[1])
            return
        print('注册成功')
    else:
        client.login(args.nick, args.password)

    ev = wait(client, 'welcome', 12)
    if ev is None:
        print('登录失败：', client.denied or '超时（请检查 IP/端口/密码）')
        client.disconnect()
        return
    print(f'已登录 悄匿社交 ｜ 大厅「{ev[1].get("room", "")}」，你是 {ev[1].get("you", "")}')

    conv = {'cur': 'room'}
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                e = client.events.get(timeout=0.2)
            except queue.Empty:
                continue
            kind, data = e
            if kind == 'chat' or kind == 'me' or kind == 'system':
                print_msg(data)
            elif kind == 'social':
                print('好友：' + ('、'.join(data.get('friends') or []) or '（无）'))
                print('群组：' + ('、'.join(f"{g['name']}(g:{g['gid']})"
                                           for g in (data.get('groups') or [])) or '（无）'))
                if data.get('requests'):
                    print('待处理好友申请：' + '、'.join(r['from'] for r in data['requests']))
            elif kind == 'disconnected':
                print('与服务器断开连接')
                stop.set()
                break
    threading.Thread(target=reader, daemon=True).start()

    print('输入内容回车发送；/quit 退出（/help 见文件头注释）')
    try:
        while not stop.is_set():
            line = input()
            if line is None:
                break
            cmd = line.strip()
            if not cmd:
                continue
            low = cmd.lower()
            if low in ('/quit', '/exit'):
                break
            elif low == '/friends':
                print('好友：' + ('、'.join(client.friends) or '（无）'))
                print('群组：' + ('、'.join(f"{g['name']}(g:{g['gid']})"
                                           for g in client.groups) or '（无）'))
            elif low.startswith('/add '):
                client.add_friend(cmd[5:].strip())
            elif low.startswith('/accept '):
                client.accept_friend(cmd[8:].strip())
            elif low.startswith('/open '):
                conv['cur'] = cmd[6:].strip() or 'room'
                client.open_conv(conv['cur'])
                print('已切换到', conv['cur'])
            elif low.startswith('/to '):
                parts = cmd.split(maxsplit=2)
                if len(parts) == 3:
                    client.send_text('u:' + parts[1].lstrip('@').lower(), parts[2])
            elif low.startswith('/g '):
                parts = cmd.split(maxsplit=2)
                if len(parts) == 3:
                    client.send_text('g:' + parts[1], parts[2])
            elif low.startswith('/group '):
                parts = cmd.split(maxsplit=2)
                members = [m.strip() for m in parts[2].split(',')] if len(parts) > 2 else []
                if len(parts) >= 2:
                    client.create_group(parts[1], members)
            else:
                client.send_text(conv['cur'], cmd)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        stop.set()
        client.disconnect()
        time.sleep(0.1)


if __name__ == '__main__':
    main()
