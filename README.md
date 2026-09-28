# 悄匿社交 · 服务端 + 客户端 总说明（README）

一个**自研可靠 UDP 传输**的局域网 / 公网聊天程序：**一个服务端（控制台）+ 一个图形客户端**，
两部分都能打包成免安装 exe。

> 所有窗口标题统一带演示后缀「（信息学院 张伊博 项目演示用）」。
> 想改或去掉，改 `chat_gui.py` 顶部的 `APP_SUFFIX` 即可。

想直接上手：跳到 [2. 快速开始](#2-快速开始)。
想看某个功能的细节：看 [12. 文档索引](#12-文档索引) 指向的两份分册说明。

---

## 1. 两部分分别是什么

| 部分 | 入口源码 | 打包产物 | 负责什么 |
| --- | --- | --- | --- |
| **服务端** | `chat_server.py` | `dist\server\悄匿社交-服务端.exe` | 账号与登录、好友、群组与群管理、消息路由与历史、文件与头像分发、中国象棋裁判、IP 属地判定、超级管理员控制台 |
| **客户端** | `chat_gui.py` | `dist\client\悄匿社交.exe` | 登录界面、侧栏会话、消息渲染与分帧重绘、文件/头像发送与预览、象棋棋盘窗口、7 套主题、诊断日志 |

两者共用这些模块：

| 文件 | 作用 |
| --- | --- |
| `chat_common.py` | 协议常量、报文编解码、PBKDF2 / AES-GCM、会话号与校验 |
| `chat_net.py` | 可靠 UDP 信道（滑动窗口 / 累积确认 / 快速重传 / 乱序缓存 / 心跳） |
| `chat_social.py` | 服务端账号、好友、黑名单、群组（JSON 持久化） |
| `chat_client_core.py` | 客户端网络核心（无界面，可被 GUI / CLI 复用） |
| `chat_geo.py` | IP 属地：9 个公开数据源 + 投票 + 缓存 + 人工修正 |
| `chat_chess.py` / `chat_chess_ui.py` | 中国象棋规则引擎 / 棋盘窗口（PIL 绘制） |
| `chat_sound.py` / `chat_notify.py` | 提示音（内存合成）/ 右下角通知 |
| `chat_secret.py` | 本机密码保管（Windows DPAPI 加密） |

> 目录里还留着更早的「PHP 聊天室」文件（`index.php`、`config.php`、`lib/`、`api/`、`assets/`、`router.php`），
> 与现在这套 Python 程序无关，说明见 `PHP聊天室_README.md`。

---

## 2. 快速开始

### 2.1 启动服务端

**方式一：双击 exe（演示推荐）**

```
dist\server\悄匿社交-服务端.exe
```

首次运行会在**同目录**生成 `server_config.json`，然后监听 **UDP 26000**，并打印局域网地址：

```
  公共大厅：公共大厅
  端    口：26000
  局域网地址（客户端请填其中任意一个）：
      192.168.1.5:26000
```

**方式二：跑源码**（改代码 / 调试时用；本机依赖装在 `D:\dsh\site-packages`）

```powershell
$env:PYTHONPATH='D:\dsh;D:\dsh\site-packages'
py chat_server.py                    # 用 server_config.json 里的端口
py chat_server.py --port 27000       # 临时换端口
py chat_server.py --room 演示大厅     # 临时换大厅名
py chat_server.py --host 127.0.0.1   # 只监听本机（本机自测最安全）
```

> 一个 UDP 端口只能被一个服务端占用；同机开第二个必须换端口。

### 2.2 启动客户端

**方式一：双击 exe**：`dist\client\悄匿社交.exe`（`_internal` 必须与 exe 同目录，不能删）

**方式二：跑源码**：`py chat_gui.py`

登录界面填四项：**服务器地址 / 端口 / 昵称 / 密码** → 首次点「注册」，之后点「登录」。
四个输入框任意一个按回车都能提交；打开界面会自动聚焦到还没填的那一栏。

关于记忆：地址 / 端口 / 昵称**登录成功后自动记住**；密码**默认不保存**，
勾选「记住密码」后用 Windows DPAPI 加密存在本机，并且**下次自动登录**
（换机器、换 Windows 账号都解不开；关掉开关会立刻删除本机密文）。

### 2.3 第一次用（三步）

1. **公共大厅**：所有人在同一个公共聊天室，支持 `@昵称` 提及；
2. **加好友**：点侧栏「好友」右侧的 **＋ 加好友** → 输入昵称搜索 → 发送申请（可附一句留言）→
   对方在「好友申请」里点「同意」；
3. **建群**：点「群组」右侧的 **＋ 建群**（勾选好友）或 **＋ 加群**（用 6 位群号申请）。

### 2.4 连不上先查这几处

客户端登录一直转圈 = 包没到服务端。依次检查：
**云安全组放行 UDP 26000（注意是 UDP 不是 TCP）→ Windows 防火墙入站规则 → 端口是否被占用 →
服务端窗口有没有打印启动成功**。服务端窗口里 `geo self` 能看到自己对外解析出的地址。

---

## 3. 功能一览

### 3.1 客户端（用户看得到的）

| 模块 | 说明 |
| --- | --- |
| 会话侧栏 | 「公共大厅 / 好友 / 群组」分区分组，群和好友各归各的段；有新消息会标记 |
| 会话切换 | 每个会话各留一份**已经画好的界面**（最多 20 个），切过去只是换显示（实测 7~70 ms）；空闲时后台把侧栏里所有会话都预热好 |
| 消息渲染 | 一个会话最多画最近 20 条，更早的给一行「（更早的 N 条没有显示，点这里显示）」；分帧绘制，单帧不超过 12 ms |
| 发送即显示 | 自己发的消息先在本机显示，服务端回显按内容指纹 + 本机等待时长去重（**不会变成两个气泡**） |
| 文件与图片 | 按会话发送；图片内联缩略图 + 点击放大（滚轮 / ＋－ 缩放）；视频/文件点击打开；拖拽文件到窗口即发送；`Ctrl+V` 直接发剪贴板截图 |
| 头像 | 侧栏左下角点一下即可选图，自动裁成 256×256 上传到服务端，别人按版本号按需拉取 |
| 成员列表 | 大厅 / 群聊右侧列出成员（含属地、在线圆点、群主 👑 / 管理员 ★ / 禁言 🔇），**右键**可 @ / 加好友 / 设管理员 / 禁言 / 移出群 / 发起私聊 |
| 群管理 | 群公告（顶部横幅）、群文件、群号复制、审批加群与拉人、禁言 / 移出成员 |
| 撤回 | 右键自己的消息 2 分钟内可撤回；群主 / 管理员可撤回普通成员的消息（不限时间） |
| 中国象棋 | 输入框左边 ♟ 约战，被挑战方选红黑；绝杀 / 困毙由服务端判定；可认输、求和、悔棋（需对方同意）；退出前会确认「视为认输」 |
| 提示音 / 通知 | 7 种内存合成音效；好友 / 群消息与 @ 提及会在右下角弹系统通知（正看着那个会话时只出声） |
| 7 套主题 | 午夜蓝（默认）/ 森林绿 / 霓虹紫 / 深海青 / 清透白 / 暖阳橙 / 羊皮纸；登录页和聊天界面都能换，选择会记住 |
| 诊断日志 | exe 同目录 `client_diag.log`（最多 400KB 自动滚动）：构建号、窗口最小化 / 恢复、每次整块重绘及原因、每次发送结果、每 10 秒一行状态 |
| 省电模式 | `client_config.json` 里写 `"calm": true`：关掉后台预热与动画，一个会话只画最近 8 条，适合老机器 / 远程桌面 |

### 3.2 服务端（后台负责的）

| 模块 | 说明 |
| --- | --- |
| 账号 | 昵称全服唯一（不区分大小写）；口令存 `PBKDF2-HMAC-SHA256(密码, 每账号随机盐)`，迭代 20 万次，**不存明文** |
| 好友 / 黑名单 | 申请、同意、拒绝、删除、拉黑；拉黑后对方发不出消息也再申请不了 |
| 群组 | 建群、6 位群号、按群号申请加入（群主 / 管理员审批）、好友拉人（管理员 + 本人双方同意）、退群 / 移出、管理员、禁言（10 分钟 / 1 小时 / 1 天 / 永久）、群公告、群文件 |
| 消息 | 大厅广播、私聊投递、群发；每个会话落盘历史；**离线留言**（好友不在线时留服务端，对方上线一次性送达） |
| 文件 / 头像 | 分块接收与转发，头像 256×256 PNG 存服务端；私聊文件按「对方视角的会话号」投递 |
| 象棋裁判 | 棋盘状态、轮次、走法合法性、将军 / 绝杀 / 困毙、认输 / 和棋 / 悔棋全在服务端判定 |
| IP 属地 | **只按 UDP 报文来源地址**判定，不采信客户端上报，所以客户端改不了 |
| 超级管理员 | 客户端多一个「🛡 控制台」：所有用户（属地 / 在线 / 注册时间 / 群聊）、所有群聊、封号（限时 / 永久，必须填理由） |

---

## 4. 账号、认证与安全

- **昵称**：2–16 个字符，支持中文 / 字母 / 数字 / 下划线 / 短横线，全服唯一（不区分大小写）
- **密码**：至少 4 位
- **登录**：客户端发昵称 → 服务端回盐 + 一次性随机数 → 客户端用 `HMAC(密钥, 随机数)` 应答 → 服务端比对。
  **密码与密钥都不上网**
- **加密**：认证成功后，除 `HELLO` / `DENY` 外所有报文用 **AES-256-GCM** 加密；报文带 16 字节随机会话号
- **重复登录**：同一账号新连接生效，旧连接被提示并断开
- ⚠️ **已知限制**：注册那一次的密码是**明文**发的（首个报文还没协商密钥）；且这是**链路加密、不是端到端加密** ——
  服务端持有密钥，能看到消息与文件明文。面向局域网 / 内网演示，公网部署建议自行加隧道

---

## 5. IP 属地

- **只看 UDP 报文的来源地址**，客户端既不能伪造也不能隐藏
- 展示位置：大厅 / 群聊 / 私聊每条消息的发送者旁、好友列表（在线时）、成员列表、大厅进出提示
- 判定结果：本机回环 → `本机`；私网地址 → `局域网 192.168.x.x`；公网解析成功 → `福建 厦门`；
  解析失败 → `属地未知`；关掉联网解析 → `公网`
- **9 个公开数据源并行查询 + 投票**（`pconline / vore / useragentinfo / ip-api / ipwho / ipwhois.app / ipapi.co / ip.sb / ipinfo`）：
  同一家库的多个域名只算一票；熟悉的库按准确度加权（pconline / ip.sb / ipinfo = 3，vore / useragentinfo = 2，其余 = 1）；
  先比省份多数派（≥2 家一致），再比省内城市，最后才比数据源顺序；**只要有国内库回过话就不提前收工**
  （境外库把移动 / 家宽出口认成「北京」是老毛病）
- 成功缓存 24 小时、失败 5 分钟，避免刷接口
- 想排查 / 手改：

  ```text
  geo 1.2.3.4                  逐个数据源列出结果和票数
  geo self                     查服务器自己的对外地址与属地
  geoset 1.2.3.4 福建 厦门      手工固定这个 IP（立刻生效）
  geoset 1.2.3.4 -             删掉这条修正
  geo save                     写进 server_config.json（重启也保留）
  ```

  想在本机复现解析过程，跑 `py _geo_live.py 1.2.3.4`（逐源列出结果和耗时，末尾附本机公网 IP）；
  `py geo_probe.py` 是打包后的自检，会把 9 个源的结果写进同目录 `geo_report.txt`
- 服务端改过属地算法后**必须重启服务端**，否则内存里还是旧结论

---

## 6. 配置文件

### 6.1 服务端 `server_config.json`（服务端目录）

```json
{
  "port": 26000,
  "room": "公共大厅",
  "geo_lookup": true,
  "public_ip": "",
  "super_admins": [],
  "geo_api": "",
  "geo_overrides": {},
  "geo_sources": ""
}
```

| 字段 | 含义 |
| --- | --- |
| `port` | 监听端口（UDP），客户端要填一样的数字 |
| `room` | 公共大厅的显示名字 |
| `geo_lookup` | 是否联网判定属地；内网 / 不想联网就设 `false` |
| `public_ip` | 手写服务端自己的公网 IP（探测不准时手动填） |
| `super_admins` | 超级管理员昵称列表（这些人登录后出现「🛡 控制台」） |
| `geo_api` | 自建属地接口（URL 里用 `{ip}` 占位），留空用内置数据源 |
| `geo_overrides` | 手工指定的 IP → 属地（由 `geoset` + `geo save` 写入） |
| `geo_sources` | 只用指定的源，例 `"pconline,ip.sb"`；留空 = 全部 9 个 |

> 用 UTF-8 保存（带 BOM 也能读）。

### 6.2 客户端 `client_config.json`（exe / `chat_gui.py` 同目录）

```json
{
  "host": "a.mineadv.top",
  "port": "26000",
  "nick": "mineadv",
  "theme": "midnight",
  "calm": false,
  "debug": false,
  "save_password": true,
  "password": "dpapi1:……"
}
```

| 字段 | 含义 |
| --- | --- |
| `host` / `port` | 上次登录的服务器地址与端口（登录成功后自动记住） |
| `nick` | 上次登录的昵称 |
| `theme` | 外观主题键：`midnight` 午夜蓝 / `forest` 森林绿 / `violet` 霓虹紫 / `ocean` 深海青 / `light` 清透白 / `sunset` 暖阳橙 / `paper` 羊皮纸 |
| `calm` | `true` = 省电模式（关预热 / 动画，只画最近 8 条） |
| `debug` | `true` = 额外写 `client_trace.log` 详细流水（与设 `QIAONI_DEBUG=1` 等效） |
| `save_password` / `password` | 勾选「记住密码」后写入：前者是开关，后者是 `dpapi1:` 开头的 DPAPI 密文，只在**当前 Windows 账号**下可解 |

---

## 7. 服务端控制台命令

| 命令 | 作用 |
| --- | --- |
| `help` | 打印命令表 |
| `users` / `list` | 当前在线的人 + 在线人数 / 群数 |
| `stats` | 账号数、群数、在线数、头像数、离线留言数；逐群列出成员 / 管理员 / 公告 / 群文件 / 待审批 |
| `games` | 正在进行的象棋对局 |
| `say <内容>` | 以系统身份在大厅广播 |
| `kick <昵称>` | 踢下线 |
| `admin list \| admin add <昵称> \| admin del <昵称>` | 超级管理员名单（即时生效并写回配置） |
| `ban <昵称> [分钟\|0] [理由]` | 封号（`0` 或省略 = 永久），理由会显示给被封的人 |
| `unban <昵称>` / `bans` | 解封 / 查看封禁名单 |
| `geo <IP>` / `geo self` | 查属地并说明「为什么显示属地未知」 |
| `geoset <IP> <属地>` / `geo save` | 手工修正属地 / 写盘 |
| `files` | 文件缓存、群文件、头像、历史目录的位置与数量 |
| `quit` / `exit` | 关服（会给在线客户端发「服务器已关闭」） |

---

## 8. 客户端内置命令与快捷键

输入框里以 `/` 开头：

| 命令 | 说明 |
| --- | --- |
| `/help` | 帮助 |
| `/me <动作>` | 动作消息（仅公共大厅） |
| `/users` | 刷新在线列表 |
| `/ping` | 查看网络延迟 |
| `/clear` | 清空当前会话显示 |
| `/quit` | 断开连接 |

输入框：`Enter` 发送、`Shift+Enter` 换行，行数自动增高。
底部按钮：😊 表情面板 / 📎 发文件 / @ 提及 / ♟ 约战象棋 / 👥 成员列表开关。

---

## 9. 数据、目录与限额

**服务端目录**（exe / `chat_server.py` 同目录）：

| 路径 | 内容 |
| --- | --- |
| `server_config.json` | 上面第 6.1 节的参数 |
| `social_data.json` | 账号（盐 + 口令散列）、好友、黑名单、群组（成员 / 管理员 / 禁言 / 公告 / 群文件 / 待审批）、离线留言、封禁记录 |
| `avatars/` | 所有人上传的头像（`<昵称>.<版本>.png`） |
| `group_files/<群号>/` | 群文件（长期保留，不参与临时缓存淘汰） |
| `history/*.jsonl` | 每个会话的历史消息（每行一条 JSON） |

换服务器时把这几个一起拷走 = 账号、好友、群、历史、头像全部保留。
服务端临时文件缓存在 `%TEMP%\qiaoni_server\`（上限 50 个 / 4GB，正常退出清空）。

**客户端目录**：`client_config.json`、`client_diag.log`、`client_error.log`（还有开了 debug 才有的 `client_trace.log`）。
收到的文件在 `%TEMP%\qiaoni_recv\`，并维护一份索引 `index.json`（最多 400 条），
所以切会话、甚至重启客户端都能直接用本机那份。

**限额速查**：

| 项目 | 取值 |
| --- | --- |
| 单条消息 | 最长 2000 字 |
| 昵称 / 密码 | 2–16 字符 / 至少 4 位 |
| 群成员上限 | 60 人 |
| 群号 | 6 位数字 |
| 每个会话落盘历史 | 最多 200 条（`HISTORY_KEEP`） |
| 新入群补历史 | 最近 30 条 + 一份群资料 |
| 离线留言 | 每人最多 200 条，保留 30 天 |
| 撤回 | 自己的消息 2 分钟内；群主 / 管理员撤普通成员不限时间 |
| 文件 | 分块 1000 字节；单文件上限 4 GB（等于不限） |
| 传输 | 报文头 34 字节；滑动窗口 128 包；单包负载上限 65000 字节 |
| 判死（两端一致） | 8 秒收不到包只提示「网络不稳」；45 秒才判离线；窗口 120 秒无确认进展也判离线 |
| 自动重连 | 断开后按 2/4/8/15/25 秒重试，共 5 次，**不需要手动重登** |

---

## 10. 打包成 exe

一键脚本（服务端 + 客户端，产物改名并放到 `dist\`）：

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

手工命令（和脚本等价，按需单跑）：

```powershell
$env:PYTHONPATH='D:\dsh;D:\dsh\site-packages'
$env:TEMP='D:\dsh\.tmp2'; $env:TMP='D:\dsh\.tmp2'

py -m PyInstaller --noconfirm --onedir --console --name server --distpath D:\dsh\dist `
  --workpath D:\dsh\.tmp2\bld_s --specpath D:\dsh\.tmp2 D:\dsh\chat_server.py

py -m PyInstaller --noconfirm --onedir --windowed --name client --distpath D:\dsh\dist `
  --workpath D:\dsh\.tmp2\bld_c --specpath D:\dsh\.tmp2 `
  --collect-all customtkinter --collect-all PIL --collect-all tkinterdnd2 D:\dsh\chat_gui.py
```

产物：

```
dist\
├── client\悄匿社交.exe         + client\_internal\
├── server\悄匿社交-服务端.exe  + server\_internal\
├── client.zip                 （发用户，不含 client_config.json）
└── server.zip                 （含 server_config.json）
```

**打包后必须做的收尾**（`--noconfirm` 会把 `dist\client` / `dist\server` 整个删掉重建）：

1. 先关掉正在运行的客户端 / 服务端，否则删文件会报 `WinError 5`（拒绝访问）；
2. `client.exe` → `悄匿社交.exe`，`server.exe` → `悄匿社交-服务端.exe`；
3. 把 `客户端说明.md` / `服务端说明.md` 拷进对应目录；
4. **`dist\client\client_config.json` 是用户的登录信息，打包前备份、打包后放回**；
5. 清掉 `client_diag.log` / `client_error.log` / `probe_report.txt` / `history\` / `social_data.json`；
6. 重新打 zip：客户端 zip **排除** `client_config.json`；服务端 zip 含 `server_config.json`。

> 如果客户端正开着，可以先把新版打到 `dist\client_new`，冒烟通过后再改名顶上 `dist\client`
> （正在运行的进程只锁旧目录里的文件，不影响新目录打包）。

`_internal` 文件夹必须与 exe 同目录，不可删除。

---

## 11. 测试

每个测试脚本结尾都会打印 `结果：N 通过，M 失败`，**M 必须为 0**。

```powershell
$env:PYTHONPATH='D:\dsh;D:\dsh\site-packages'
py test_protocol.py                          # 直接跑
py _runtest.py test_msg_echo.py out.txt      # 输出强制写成 UTF-8 文件（受限环境 / 中文乱码时用）
```

| 类别 | 脚本 |
| --- | --- |
| 协议 / 配置 / 账号 | `test_protocol`、`test_config`、`test_social`、`test_server_log` |
| 文件与链路 | `test_features`、`test_loss`、`test_latency`、`test_latency_msg` |
| 好友 / 群 / 管理 | `test_friend_ops`、`test_group_admin`、`test_group_ui`、`test_members`、`test_recall_social`、`test_super_admin` |
| 界面与渲染 | `test_new_ui`、`test_theme`、`test_title`、`test_smooth_ui`、`test_render_order`、`test_scroll`、`test_preload`、`test_preload_race`、`test_veil`、`test_emoji_cache`、`test_sidebar_grouping`、`test_send_visible`、`test_echo_clock`、`test_display_heal` |
| 登录 / 连接 | `test_login_save`、`test_reconnect_ui`、`test_domain_reconnect`、`test_outage`、`test_soak` |
| 象棋 / 声音 | `test_chess`、`test_chess_net`、`test_chess_gui`、`test_sound` |
| 属地 | `test_geo`（需要联网，可能因外部接口慢而变慢） |
| 辅助 | `gui_smoke.py`（`GUI_SMOKE_OK`）、`theme_audit.py`（`COLOR_AUDIT_OK`）、`frozen_probe.py`、`smoke_exe_test.py <端口>` |

注意事项：

- `test_game_center.py` **已过期**（游戏中心整体回滚，`chat_gomoku.py` / `chat_idiom.py` / `chat_games.py` / `chat_game_ui.py`
  还在磁盘上但**没有接线**，不要重新引入）；
- `test_title` / `test_theme` / `test_login_save` 需要在**项目目录里可写**（它们会写 `client_config.json` / 截图），
  受限环境下会因为权限失败，属于环境问题而不是代码问题；
- GUI 测试要把输出重定向到文件再读，侧栏真实顺序要用 `pack_slaves()`（`winfo_children()` 是创建顺序）；
- 这台机器上 GUI 测试有环境抖动（窗口拿不到可见状态时 `test_preload` / `test_scroll` 会失败），单独重跑即可。

---

## 12. 文档索引

| 文档 | 讲什么 |
| --- | --- |
| **本文件 `README.md`** | 总览：组成部分、快速开始、功能、配置、命令、限额、打包、测试 |
| `客户端说明.md` | 客户端的使用细节与界面行为（给用户 / 演示） |
| `服务端说明.md` | 服务端部署、控制台、协议与安全、属地（给运维 / 演示） |
| `交接说明.md` | **给下一个接手的人**：项目背景、关键设计、踩过的坑、每一轮修了什么、怎么复现 |
| `README_旧版备份.md` | 上一版 README（内容已并入本文件与两份分册，留作参考） |
| `PHP聊天室_README.md` | 目录里遗留的 PHP 聊天室（与当前程序无关） |

---

## 13. 已知限制（如实说明）

- **没有端到端加密**：服务端能看到消息与文件明文；**注册时密码明文传输一次**（历史遗留，未修）
- **属地依赖第三方公开接口**：会失败、会给错；单源配置（如只用 `pconline`）会变成单点
- **成员列表里别人的属地只有服务端能判**：服务端不升级，你看到的别人仍可能是旧结论
- `%TEMP%\qiaoni_recv\` 收到的文件**不会自动清理**（索引上限 400 条）
- 象棋 / 通知 / DPAPI 密码保管 / 提示音都是 **Windows 专属**，其他系统上会退化成不可用或无声
- 离线留言保留 30 天、每人 200 条，过期自动清理

---

## 14. 常见问题速查

| 现象 | 先做什么 |
| --- | --- |
| 一直连不上 | 安全组 / 防火墙放行 **UDP** 端口；确认没填错 IP / 端口；服务端窗口有没有启动成功 |
| 提示「该昵称尚未注册」/「密码错误」 | 先在「注册」页签建号；密码区分大小写，忘了只能让管理员删号重建 |
| 界面卡 / 白 / 消息不显示 | 看客户端目录 `client_diag.log` 最后 30 行（重绘原因 / 待画 / 遮罩 / 锁输入），有 `显示自检` 行说明界面正在自救 |
| 客户端起不来 | 看 `client_error.log`；确认 `_internal` 完整；确认没杀过残留进程导致文件锁 |
| 打包失败 / WinError 5 | 先关掉正在运行的客户端 / 服务端，等 2 秒重试 |
| 属地不对 | 服务端控制台 `geo <IP>` 看票数；`geoset` 手工固定；确认服务端已重启 |
| 消息发出去了对方没收到 | 双方是否好友 / 是否被拉黑；对方不在线时私聊走离线留言（30 天内上线即可收到） |
| 想清空所有数据重来 | 关服务端，删 `social_data.json`、`history/`、`avatars/`，再启动 |
| 界面配色不喜欢 / 想恢复默认 | 登录页底部或聊天界面右上角的主题下拉；恢复默认选「午夜蓝」 |
| 想要绝对流畅（老机器 / 远程桌面） | `client_config.json` 里加 `"calm": true` |
