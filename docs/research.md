# fnOS 客户端与 API 调研

调研日期：2026-08-17。

## 官方客户端

当前 fnOS 官方下载页提供“飞牛同步” Windows 和 macOS 客户端，未列出 Linux 版。官方帮助说明的主要能力包括：

官方下载资源使用 `fn-sync` 作为客户端包名。本项目从 `0.3.0` 起采用同一可见名称；`0.3.1` 起直接从官方客户端画面提取双箭头轮廓作为透明蒙版，不再使用近似手绘曲线。Omarchy 版本不写死官方蓝色，而是实时使用当前系统主题的前景色、强调色和警告色。

官方 `2025-08` 版帮助展示的连接与授权流程是：先通过 IP、域名、FN ID 或局域网发现选定 NAS，再进行一次账号授权；官方明确说明客户端不会保存账号密码，而连接方式和用户信息不变时无需再次授权。创建任务是后续独立流程，包含“同步设备 → 同步规则 → 同步路径”三个步骤，主页面允许在同一设备下管理多个任务。`0.4.0` 据此把本项目的数据模型和右侧面板改成“NAS 连接/授权”和“同步任务”两个层级。

- 通过 IP、域名或 FN ID 连接，并可在局域网内发现设备。
- 设备连接与任务分离；相同连接方式和用户信息可复用既有授权。
- 双向同步、仅下载、仅上传。两个单向模式均不把源端删除传播到目标端。
- 按大小和类型过滤，临时文件强制排除。
- 任务状态、进度、托盘入口和全局限速。
- 冲突时官方客户端在本地保留冲突副本，需用户手工合并。
- Windows 支持按需同步占位文件；macOS 官方帮助明确说明暂不支持。

来源：

- [fnOS 官方下载页](https://fnnas.com/download)
- [如何使用飞牛同步](https://help.fnnas.com/articles/v1/sync/how-to-use)
- [按需同步](https://help.fnnas.com/articles/v1/sync/on-demand-sync)
- [飞牛同步 FAQ](https://help.fnnas.com/articles/v1/sync/fnsync-faq)

## 局域网发现边界

官方飞牛同步帮助明确提供“发现局域网内设备”，当前同步客户端只使用 HTTPS，默认管理/授权端口为 `5667`。官方没有公开发现广播报文或桌面客户端远程文件协议。社区问题中的实际界面也显示：发现设备后官方客户端填写的是 `IP:5667`，说明发现结果是 fnOS 管理/授权端点，不是 WebDAV URL。

本项目不能把私有发现协议假装成稳定 API，所以 `0.6.0` 使用可审计的保守替代方案：只扫描当前直连私有 IPv4 网段（每个网段最多 `/24`）上的 `5667/5666/8001/8000` 管理端口和 `5006/5005` WebDAV 端口，并用只读 HTTP(S)/WebDAV 响应降低误报。扫描不发送账号密码、不登录、不改变 NAS。`0.6.1` 根据真实设备验证进一步收紧：只找到管理端口时不再把默认 `5006` 填成 WebDAV URL，而是提示先在 fnOS 设置中启用或检查 WebDAV；自定义 WebDAV 端口仍需用户从 fnOS 设置中填写。

来源：

- [飞牛同步功能介绍](https://help.fnnas.com/articles/v1/sync/how-to-use)
- [局域网发现后填写 5667 的案例](https://club.fnnas.com/forum.php?mod=viewthread&tid=39084)
- [WebDAV 5005/5006 端口案例](https://club.fnnas.com/forum.php?mod=viewthread&tid=61210)

## 开放 API 为什么不能直接做 Linux 客户端

fnOS 于 2026-07-31 公布的开放 API 要求 fnOS `1.2.0401+` 和 App `1.34.0+`。它的定位是“安装在 NAS 里的 fnOS 应用”，不是公网或局域网上的通用文件 API：

- 应用在 manifest 中声明 `api-scope`。
- 系统启动应用脚本时才把 `TRIM_API_TOKEN` 注入当前进程环境。
- 后端通过 NAS 内部 Unix Socket `/var/run/trim_open_gateway_apiscope.socket` 请求 `POST /api/v1/trimapp`。
- 目前公开的文件相关能力是授权目录管理、ACL 检查和内部路径转换；没有向外部桌面客户端提供列目录、上传、下载、变更日志或同步 token 的传输 API。

因此，不能把 NAS 内部 token 提取到 Linux 客户端，也不应试图持久化它。

来源：

- [fnOS 开发者文档索引](https://developer.fnnas.com/llms.txt)
- [开放 API 概览](https://developer.fnnas.com/api/overview)
- [开放 API 调用方式](https://developer.fnnas.com/api/calling)
- [授权与文件概览](https://developer.fnnas.com/api/authorization/overview)

## 第三方私有 API 实现

社区项目 [Timandes/fnos-cli](https://github.com/Timandes/fnos-cli) 和 [Timandes/pyfnos](https://github.com/Timandes/pyfnos) 说明 fnOS Web UI 的 WebSocket 接口可以被社区客户端调用，包括登录、2FA 和部分文件操作。但它们不是 fnOS 承诺稳定的公开 API，也没有为完整文件同步提供稳定的变更日志和传输契约。本项目不依赖它们。

## 选择 WebDAV + rclone

fnOS 官方提供 WebDAV；rclone 官方支持通用 WebDAV 后端和 `bisync`。因此这是当前唯一同时满足“官方支持的 NAS 传输层”和“可以在 Linux 端实现双向同步”的路线。

实现时根据 rclone 的安全建议启用了：

- 首轮 `--resync` 前 dry-run 预览。
- `--check-access` 双端标记。
- `--max-delete 50` 突发删除中止。
- `--resilient` / `--recover` 和独立 workdir。
- 双端版本备份目录。
- 无自动胜出方的冲突处理，保留双方副本。

来源：

- [fnOS WebDAV 官方帮助](https://help.fnnas.com/articles/v1/file-service/webdav)
- [rclone WebDAV](https://rclone.org/webdav/)
- [rclone global flags (`--checkers`, retries and stats)](https://rclone.org/docs/)
- [fnOS forum: intermittent WebDAV 401 report](https://club.fnnas.com/forum.php?mod=viewthread&tid=64657)
- [rclone bisync](https://rclone.org/bisync/)

## Omarchy 插件结论

Omarchy 4.0 的第三方插件位于 `~/.config/omarchy/plugins/<plugin-id>/`，并作为未沙箱化 QML/JS 代码加载进长期运行的 `omarchy-shell` Quickshell 进程。

结论是：

- 适合做状态栏、简短详情面板、“立即同步”和“打开客户端”的薄插件。
- 窄面板可保留官方的“同步任务 / NAS 连接 / 设置”信息架构，但使用 Omarchy 的主题组件和间距。
- 不适合把凭据、WebDAV 传输、长时间任务和通用 Linux 业务逻辑都放进插件。
- 最合理的发布形式是“通用 Linux 包 + 可选 Omarchy 插件”。
