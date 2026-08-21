# FN sync

[![CI](https://github.com/ripple0328/fn-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/ripple0328/fn-sync/actions/workflows/ci.yml)
[![Release](https://github.com/ripple0328/fn-sync/actions/workflows/release.yml/badge.svg)](https://github.com/ripple0328/fn-sync/actions/workflows/release.yml)

**FN sync brings safe, native fnOS file synchronization to Linux and Omarchy.**
It uses the documented fnOS WebDAV service, rclone's proven transfer engine,
and an Omarchy-native panel for connections, tasks, status and recovery.

一个为 Omarchy/Arch Linux 设计的 fnOS 文件同步客户端。它通过 fnOS 官方支持的 WebDAV 传输文件，不依赖 Windows/macOS 官方客户端的私有协议。

应用显示名为 **FN sync**；系统界面语言为中文时显示为 **飞牛**。包名、命令和内部路径仍使用 `fn-sync`，以保持安装与脚本兼容。

> 当前版本为 `0.8.0`。真实 fnOS 上的发现、授权、文件夹浏览和大型同步已验证；Omarchy 面板仅保留“任务 / 设置”两个主导航，NAS 连接作为设置子页显示紧凑的返回导航，任务列表也只在所属任务卡中显示一次同步状态。首次使用仍建议从一个新建的小目录开始。

## Interface

| Tasks and sync status | Settings and saved NAS connections |
| --- | --- |
| ![FN sync tasks](docs/screenshots/tasks.png) | ![FN sync settings](docs/screenshots/settings.png) |

## 架构

| 层 | 用途 | 是否依赖 Omarchy |
| --- | --- | --- |
| `fn-sync` 控制器 + rclone | WebDAV 传输、任务状态、冲突与删除保护 | 否 |
| systemd 用户服务 | 定时后台同步 | 否 |
| GTK 4/GJS 客户端 | 添加任务、首次同步引导、暂停与立即同步 | 否 |
| `community.fnos-sync` 插件 | Omarchy 原生任务管理面板与状态栏入口 | 是，可选 |

Omarchy 插件只是薄适配层。它不保存 WebDAV 密码，也不在长期运行的 `omarchy-shell` 进程内实现文件传输。

插件状态会在加载时、每次打开面板时、操作完成后以及后台定时自动刷新。默认间隔为 30 秒，可通过插件的 `refreshIntervalSec` 设置调整，因此面板不提供手动刷新按钮。

## 已实现

- NAS 连接和同步任务分离：每个 NAS 账号只授权一次，可复用于多个同步任务。
- 新建 NAS 连接时自动扫描当前私有局域网；确认 WebDAV 端口可用后自动填写地址，多台设备时提供选择。
- 新增 NAS 授权必须先成功测试登录并读取文件夹，任何字段变更都会要求重新测试，测试期间不保存凭据。
- 创建任务时通过文件夹选择器选择本地目录，并通过 NAS 文件夹浏览器选择远端目录，不能手工猜测路径。
- 双向同步、仅上传、仅下载。
- 双向任务首次通过一个两步引导完成：选择同名冲突要保留的副本，运行只读“检查首次同步”，然后使用唯一的“开始首次同步”主按钮。
- “检查首次同步”会显示已用时间和扫描进度，但不会修改文件。检查结果会记录对应冲突规则；更改规则后必须重新检查，避免检查与实际首次同步不一致。
- 首次同步成功后自动开启后台同步；开始前不再显示容易误解为失效控件的开关。
- 日常冲突保留双方，分别使用 `.Omarchy-conflictN` 和 `.NAS-conflictN` 后缀。
- 删除前备份到版本目录；单次超过 50% 的突发删除会中止。
- 双端 `FN_SYNC_ACCESS_TEST` 访问标记；每次双向同步前先进行快速验证，NAS 路径失效、标记缺失或内容不匹配时会在扫描文件前暂停任务。
- 安全暂停后可在任务面板确认两端路径，再使用“修复安全检查并恢复同步”；修复只重建并验证 fn-sync 标记，不修改其他文件。
- 任务日志超过 5 MiB 时自动轮换，仅保留一个上一份日志，避免只读检查和重复错误无限占用空间。
- 禁止使用 `/` 或整个用户主目录，并拒绝两个任务的本地/NAS 目录相互嵌套。
- 默认只允许 HTTPS；明文 HTTP 和跳过证书验证都需要显式选择。
- 密码优先保存在 Secret Service 桌面密钥环。同步时才生成权限为 `0600` 的临时 rclone 配置，使用后删除。
- Secret Service 不可用时回退到权限为 `0600` 的 rclone obscured 凭据；该形式只是可逆混淆，不是加密。
- 默认过滤常见临时文件和内部版本目录。

## 在 Omarchy 上安装（推荐）

发布到 AUR 后，下面一行会同时安装系统客户端、复制软件包内置的
Omarchy 插件、启动用户服务并把插件放到状态栏右侧：

```bash
omarchy pkg aur add fn-sync && fn-sync-omarchy-setup
```

pacman 以 root 身份安装系统文件，而 Omarchy 插件属于当前桌面用户；因此
PKGBUILD 不会冒充用户修改 `~/.config`。`fn-sync-omarchy-setup` 是这条一键命令
中的用户级阶段，不需要再手工复制、编辑或配置插件。

希望由 Omarchy 直接从 Git 更新插件时，使用另一种单行安装方式，不要同时安装
软件包内置副本：

```bash
omarchy pkg aur add fn-sync && omarchy plugin add https://github.com/ripple0328/omarchy-fn-sync.git --enable --yes
```

从源码构建 pacman 包、独立插件包和一键安装包：

```bash
git clone https://github.com/ripple0328/fn-sync.git
cd fn-sync
./scripts/build-packages.sh
```

然后以普通桌面用户运行一键安装器；安装器只在调用 pacman 时请求 `sudo`：

```bash
./scripts/install-omarchy-bundle.sh
```

构建产物位于 `dist/`：

- `fn-sync-0.8.0-1-any.pkg.tar.zst`：Arch/pacman 系统包；
- `fn-sync-omarchy-plugin-0.8.0.tar.gz`：独立 Omarchy 插件归档；
- `fn-sync-omarchy-bundle-0.8.0.tar.gz`：包含前两者和安装器的便携包。

安装后，状态栏右侧会显示飞牛同步官方双环标记，并打开跟随当前 Omarchy 主题的统一管理面板。标记的前景色、强调色和错误色均实时绑定系统主题。面板只有“Tasks / Settings”两个主入口；NAS 连接和授权位于 Settings 的子页，再由同步任务复用。密码仅在连接或重新授权时通过标准输入交给控制器，不保存在任务、QML 或插件设置中。

名称和图标素材来自[飞牛官方软件下载页](https://fnnas.com/download?key=fn-sync)与[飞牛同步官方帮助](https://help.fnnas.com/articles/v1/sync/how-to-use)。Omarchy 状态栏使用从官方客户端画面提取的原始双箭头轮廓作为透明蒙版，再由当前系统主题实时着色；飞牛及其图标商标归原权利人所有。

界面语言默认跟随桌面区域设置：`zh*` 使用简体中文，其余语言使用英文。Omarchy 面板的 Settings 页面也可覆盖为 System default、English 或简体中文；从面板打开完整客户端时会沿用该选择。

非 Omarchy Linux 仍可运行 `fn-sync ui` 使用 GTK 4 备用界面。

发布流水线会先通过 lint、Python/CLI/安装器测试、官方 Omarchy manifest
验证和干净的 Arch 打包，再创建 GitHub Release。配置 AUR 的专用 SSH 密钥后，
同一流水线会把 `PKGBUILD`、`.SRCINFO` 和安装提示推送到 AUR。插件子目录则由
独立流水线同步到 `ripple0328/omarchy-fn-sync`，保持 `manifest.json` 位于仓库根目录。

### 源码目录的用户级开发安装

不希望写入 pacman 数据库时，可以继续使用：

```bash
omarchy pkg add rclone python gjs gtk4 libsecret libnotify
./scripts/install.sh
./scripts/install-omarchy-plugin.sh
```

## fnOS 配置

1. 在 fnOS 的文件共享协议中启用 WebDAV。
2. 优先启用 HTTPS，并记下 fnOS 界面显示的完整 WebDAV 地址与端口。
3. 为 Linux 同步准备一个专用子目录。
4. 建议使用一个只对所需共享目录有读写权限的 fnOS 用户，不要使用管理员账号。
5. 在 Omarchy 面板的 Settings → NAS connections 子页（或 GTK 备用界面）完成一次授权，再创建一个或多个任务。
6. 选择冲突规则并完成“检查首次同步”，然后点击“开始首次同步”。

首次同步检查会遍历两端所有未被过滤的目录；源码树中的 `node_modules`、`deps`、`_build`、Xcode/Android build 等生成目录会显著增加时间和 WebDAV 请求量。该检查带有 `--dry-run`，不会修改文件，并可从进度卡停止。若根目录测试成功、但大型检查零散出现 `401 Unauthorized`，通常不是密码失效，而是 fnOS WebDAV 在密集深层请求中间歇拒绝授权；fn-sync 保留 HTTPS，但禁用该连接的 HTTP/2 多路复用，将 rclone `checkers/transfers` 降为 `2/2` 并增加重试间隔。目录修改时间不参与文件协调，因此也不会在文件比较完成后逐项写回目录时间。仍可逐目录检查账号权限，或在 fnOS 中关闭再开启 WebDAV 后重试。

参考：[fnOS WebDAV 官方帮助](https://help.fnnas.com/articles/v1/file-service/webdav)。不要把 NAS 密码发到 issue、聊天或日志中。

### 局域网自动发现

打开新的 NAS 连接表单时，Omarchy 插件会自动扫描当前直连的私有 IPv4 网段；也可以用“Scan local fnOS NAS”重新扫描。扫描严格限制为每个本地网段最多一个 `/24`，且只探测 fnOS 管理端口 `5667/5666/8001/8000` 与常见 WebDAV 端口 `5006/5005`。它只进行 TCP、HTTP(S) 和 WebDAV `OPTIONS` 读取，不登录、不修改 NAS。

官方飞牛同步的局域网发现填写的是客户端管理/授权地址（当前默认 HTTPS `5667`），而本项目通过 WebDAV 传输。因此仅发现 fnOS 管理端时，表单不会再猜测或填写 `5006`；它会提示在 fnOS“设置 > 文件共享协议”中启用或检查 WebDAV。只有 WebDAV 默认端口实际响应后才会自动填写，并且仍须通过“Test login & folders”后才能保存。自定义 WebDAV 端口、跨 VLAN、VPN 和 FN ID 不会被扫描。

## 常用 CLI

从 `0.3.0` 起主命令是 `fn-sync`；旧的 `fnsync` 命令仍作为兼容别名保留，原有 `~/.config/fnsync` 任务和密钥引用不会迁移或丢失。

```bash
fn-sync --version
fn-sync doctor
fn-sync connection add --name "Home NAS" --url https://nas.example/dav/ --username alice --password-stdin
fn-sync connection list
fn-sync connection test <connection-id>
fn-sync connection folders <connection-id> --json
fn-sync task add --name Docs --connection <connection-id> --local "$HOME/Sync/Docs" --remote-path Sync/Docs
fn-sync task repair-access <task-id> --resume
fn-sync task list
fn-sync status --json
fn-sync task test <task-id>
fn-sync task preview <task-id> --winner local
fn-sync task initialize <task-id> --winner local --apply
fn-sync task run <task-id> --dry-run
fn-sync sync-now
fn-sync logs <task-id>
```

## 与官方客户端的差异

| 功能 | 官方 Windows/macOS 客户端 | 本项目 |
| --- | --- | --- |
| IP/域名 | 支持 | WebDAV URL |
| 同局域网自动发现 | 支持 | 支持；发现主机后填写 WebDAV 地址并强制测试 |
| 一次授权、多任务复用 | 支持 | 支持；NAS 连接与任务分离 |
| FN ID/远程中继 | 支持 | 不支持；需直达 fnOS WebDAV |
| 双向、仅上传、仅下载 | 支持 | 支持 |
| 首次任务体验 | 创建后立即同步 | 先做一次只读安全检查，再开始同步 |
| 按需占位文件 | 仅 Windows | 不支持 |
| 冲突 | 保留本地冲突副本 | 双端均保留冲突副本 |
| 状态栏与管理 UI | 官方托盘 | Omarchy 原生插件；GTK 备用界面 |
| Linux 桌面 | 无官方客户端 | GTK 客户端 + systemd 服务 |

同一 NAS 目录可继续由 Mac/Windows 官方客户端使用，Linux 端则通过 WebDAV 访问它。不要让两个同步程序同时监视同一个 Linux 本地目录。

## 验证

- 57 个自动化测试通过，包括真实 WebDAV 双向/单向同步、完整的命令行连接/任务生命周期、安装器沙箱、打包与发布契约和独立插件测试；Python 分支覆盖率门槛为 65%。
- Omarchy 4.0 插件 manifest 与 QML 语法验证通过。
- pacman 系统包、独立插件归档和便携一键安装包完成结构校验。
- GTK/GJS 模块在无显示器环境下完成语法与导入检查。
- 用 rclone `serve webdav` 在 `/tmp` 内完成真实传输测试：双向初始合并、双向增量、冲突副本、删除版本备份、访问标记中止、仅上传不传播源删除、仅下载不传播源删除。

## 已知限制

- WebDAV 不能可靠保留修改时间，所以首次合并不提供“较新文件自动胜出”。
- 当前是周期性扫描，不是内核文件事件 + fnOS push 的准实时协议。
- 不支持 Windows 式按需占位文件、FN ID 中继、跨网段发现和 fnOS 官方客户端的 2FA 登录流程。
- fnOS 开放 API 目前不是外部桌面同步协议；详见 [调研记录](docs/research.md)。

## 测试

```bash
./scripts/ci.sh
./scripts/build-packages.sh
./scripts/verify-package.sh
```

覆盖范围和仍需真实 NAS 验证的边界见 [TESTING.md](TESTING.md)。
