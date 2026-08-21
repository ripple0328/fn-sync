pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
    id: root
    moduleName: "community.fnos-sync"
    ipcTarget: "community.fnos-sync"
    manageIpc: false

    property var anchorItem: null
    property var hostWidget: null
    property string controlPath: ""
    property string language: "en"
    property string languagePreference: "system"
    property bool installed: false
    property bool runtimeReady: false
    property string missingDependencies: ""
    property bool installingDependencies: false
    property var tasks: []
    property var connections: []
    property string statusError: ""
    property bool syncing: false

    property string page: "tasks"
    property string selectedTaskId: ""
    property string selectedConnectionId: ""
    property string actionStatus: ""
    property string actionError: ""
    property string actionOutput: ""
    property string actionLabel: ""
    property string actionKind: ""
    property string actionTaskId: ""
    property string actionWinner: ""
    property string actionProgressLine: ""
    property string processFirstError: ""
    property int actionElapsedSeconds: 0
    property int pendingActionExitCode: 0
    property bool actionCancelRequested: false
    property string removingConnectionId: ""
    property bool showFullOutput: false
    property string processStdout: ""
    property string processStderr: ""
    property string createStdout: ""
    property string createStderr: ""
    property string createKind: ""
    property bool createUsesPassword: false
    property string pendingPassword: ""

    property var pendingConfirmArgs: []
    property string pendingConfirmLabel: ""
    property string pendingConfirmMessage: ""
    property bool pendingConfirmBack: false

    property string addMode: "two-way"
    property string addConnectionId: ""
    property string firstSyncWinner: "local"
    property bool connectionAllowHttp: false
    property bool connectionInsecureTls: false
    property string editingConnectionId: ""
    property string verifiedConnectionFingerprint: ""
    property string pendingVerifyFingerprint: ""
    property string verifyStdout: ""
    property string verifyStderr: ""
    property var discoveredDevices: []
    property string discoveryStdout: ""
    property string discoveryStderr: ""
    property int discoveryGeneration: 0
    property int runningDiscoveryGeneration: 0
    property bool discoveryAutoFill: false
    property bool discoveryReplaceFields: false
    property string browseConnectionId: ""
    property string browsePath: ""
    property var browseFolders: []
    property string browseStdout: ""
    property string browseStderr: ""

    readonly property var barIdentity: hostWidget || root
    readonly property color foreground: bar ? bar.foreground : Color.foreground
    readonly property color accent: Color.accent
    readonly property color dimForeground: Qt.darker(foreground, 1.5)
    readonly property color urgent: bar ? bar.urgent : Color.urgent
    readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
    readonly property bool busy: actionProcess.running || createProcess.running || verifyProcess.running || folderProcess.running || syncing || installingDependencies
    readonly property bool connectionVerifying: verifyProcess.running
    readonly property bool connectionSaving: createProcess.running && createKind === "connection"
    readonly property bool connectionDiscovering: discoveryProcess.running
    readonly property bool connectionFormBusy: createProcess.running || verifyProcess.running
    readonly property bool connectionFieldsComplete: connectionNameField.text.trim() !== "" && connectionUrlField.text.trim() !== "" && connectionUserField.text.trim() !== "" && (editingConnectionId !== "" || connectionPasswordField.text !== "")
    readonly property bool connectionSaveReady: installed && runtimeReady && !connectionFormBusy && connectionFieldsComplete && (editingConnectionId !== "" || verifiedConnectionFingerprint === connectionFingerprint())
    readonly property int runningTaskCount: countTaskState("running")
    readonly property bool syncAllReady: installed && runtimeReady && enabledCount() > 0 && runningTaskCount === 0 && !busy
    readonly property bool createTaskReady: installed && runtimeReady && connections.length > 0 && !busy
    readonly property var selectedTask: taskById(selectedTaskId)
    readonly property bool previewRunning: actionProcess.running && actionKind === "preview"
    readonly property bool primaryPage: page === "tasks" || page === "nas" || page === "settings"
    readonly property bool editorFocused: taskNameField.activeFocus || taskRemoteField.activeFocus || taskLocalField.activeFocus || taskModeDropdown.popupOpen || taskConnectionDropdown.popupOpen || languageDropdown.popupOpen || connectionNameField.activeFocus || connectionUrlField.activeFocus || connectionUserField.activeFocus || connectionPasswordField.activeFocus

    function l10n(english, chinese) {
        return language === "zh" ? chinese : english;
    }

    function languageOptions() {
        return [
            {
                value: "system",
                label: l10n("System default", "跟随系统")
            },
            {
                value: "en",
                label: "English"
            },
            {
                value: "zh",
                label: "简体中文"
            }
        ];
    }

    function taskById(id) {
        for (var i = 0; i < tasks.length; i++) {
            if (tasks[i] && String(tasks[i].id || "") === String(id || ""))
                return tasks[i];
        }
        return null;
    }

    function connectionById(id) {
        for (var i = 0; i < connections.length; i++) {
            if (connections[i] && String(connections[i].id || "") === String(id || ""))
                return connections[i];
        }
        return null;
    }

    function connectionOptions() {
        var options = [];
        for (var i = 0; i < connections.length; i++) {
            var item = connections[i];
            options.push({
                value: String(item.id || ""),
                label: String(item.name || "fnOS NAS")
            });
        }
        return options;
    }

    function connectionUseCount(id) {
        var count = 0;
        for (var i = 0; i < tasks.length; i++) {
            if (String(tasks[i].connection_id || "") === String(id || ""))
                count++;
        }
        return count;
    }

    function enabledCount() {
        var count = 0;
        for (var i = 0; i < tasks.length; i++)
            if (tasks[i] && tasks[i].enabled === true)
                count++;
        return count;
    }

    function errorCount() {
        return countTaskState("error");
    }

    function countTaskState(state) {
        var count = 0;
        for (var i = 0; i < tasks.length; i++) {
            if (tasks[i] && tasks[i].status && String(tasks[i].status.state || "") === state)
                count++;
        }
        return count;
    }

    function taskListStatusFill(task) {
        var state = task && task.status ? String(task.status.state || "never") : "never";
        if (needsAccessRepair(task) || state === "error")
            return Util.alpha(urgent, 0.16);
        if (state === "running")
            return Util.alpha(accent, 0.18);
        return Util.alpha(foreground, 0.055);
    }

    function taskListStatusBorder(task) {
        var state = task && task.status ? String(task.status.state || "never") : "never";
        if (needsAccessRepair(task) || state === "error")
            return Border.flat(urgent, Style.focusBorderWidth);
        if (state === "running")
            return Border.flat(accent, Style.focusBorderWidth);
        return Border.controlSpec("normal", foreground, accent, urgent);
    }

    function taskListStatusDetail(task) {
        if (!task)
            return "";
        var state = task.status ? String(task.status.state || "never") : "never";
        if (state === "running" || state === "error" || needsAccessRepair(task))
            return stateSummary(task);
        return statusTimeText(task) + " · " + automationText(task);
    }

    function needsAccessRepair(task) {
        if (!task)
            return false;
        if (task.status && String(task.status.error_code || "") === "access-marker")
            return true;
        return task.safety_issue
            ? String(task.safety_issue.code || "") === "access-marker"
            : false;
    }

    function stateText(task) {
        var state = task && task.status ? String(task.status.state || "never") : "never";
        var action = task && task.status ? String(task.status.action || "") : "";
        if (needsAccessRepair(task))
            return l10n("Safety check paused", "安全检查已暂停");
        if (action === "initial-preview") {
            if (state === "ok" && String(task.status.conflict_winner || "") !== "")
                return l10n("Ready for first sync", "首次同步已就绪");
            if (state === "ok")
                return l10n("Check needed", "需要重新检查");
            if (state === "running")
                return l10n("Checking first sync…", "正在检查首次同步…");
            if (state === "cancelled")
                return l10n("First-sync check stopped", "首次同步检查已停止");
            if (state === "error")
                return l10n("First-sync check failed", "首次同步检查失败");
        }
        if (task && task.mode === "two-way" && !task.initialized && state !== "error" && firstSyncCheckWinner(task) !== "")
            return l10n("Ready for first sync", "首次同步已就绪");
        if (state === "ok")
            return l10n("Up to date", "已同步");
        if (state === "running")
            return l10n("Syncing…", "正在同步…");
        if (state === "error")
            return l10n("Needs attention", "需要处理");
        return l10n("Not run yet", "尚未运行");
    }

    function stateColor(task) {
        var state = task && task.status ? String(task.status.state || "never") : "never";
        if (needsAccessRepair(task) || state === "error")
            return urgent;
        return foreground;
    }

    function stateSurfaceFill(task) {
        var state = task && task.status ? String(task.status.state || "never") : "never";
        if (needsAccessRepair(task) || state === "error")
            return Style.selectedFillFor(urgent, urgent, urgent);
        if (state === "running" || state === "ok")
            return Style.selectedFillFor(accent, accent, urgent);
        return Style.normalFillFor(foreground, accent, urgent);
    }

    function stateSurfaceBorder(task) {
        var state = task && task.status ? String(task.status.state || "never") : "never";
        if (needsAccessRepair(task) || state === "error")
            return Border.controlSpec("selected", urgent, urgent, urgent);
        if (state === "running" || state === "ok")
            return Border.controlSpec("selected", accent, accent, urgent);
        return Border.controlSpec("normal", foreground, accent, urgent);
    }

    function stateSummary(task) {
        if (!task)
            return "";
        if (needsAccessRepair(task))
            return l10n("Automatic sync is paused until the folder safety check is repaired.", "文件夹安全检查修复前，自动同步保持暂停。");
        var status = task.status || {};
        var state = String(status.state || "never");
        var action = String(status.action || "");
        if (action === "initial-preview" && state === "running")
            return l10n("Scanning both folders without changing any files.", "正在扫描两端文件夹，不会更改任何文件。");
        if (action === "initial-preview" && state === "ok")
            return l10n("The safety check is complete. Review the conflict choice, then start the first sync.", "安全检查已完成。确认冲突处理方式后即可开始首次同步。");
        if (state === "running")
            return l10n("Comparing and transferring changes now.", "正在比较并传输更改。");
        if (state === "error") {
            var message = cleanLine(taskStatusMessage(task));
            return message !== "" ? message : l10n("The last sync failed. Open the technical log for details.", "上次同步失败。请打开技术日志查看详情。");
        }
        if (state === "cancelled")
            return l10n("The last operation was stopped before it finished.", "上次操作在完成前已停止。");
        if (state === "ok")
            return l10n("All included files match on this computer and the NAS.", "此电脑与 NAS 上的所有包含文件均已一致。");
        return l10n("This task is ready for its first run.", "此任务已准备好首次运行。");
    }

    function statusTimeText(task) {
        if (!task || !task.status)
            return l10n("Waiting for the first run", "等待首次运行");
        var status = task.status;
        var state = String(status.state || "never");
        var raw = state === "running" ? String(status.started_at || "") : String(status.finished_at || "");
        var date = new Date(raw);
        if (raw === "" || isNaN(date.getTime()))
            return l10n("Waiting for the first run", "等待首次运行");
        var now = new Date();
        var sameDay = date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
        var time = Qt.formatTime(date, "HH:mm");
        var when = sameDay
            ? l10n("today at ", "今天 ") + time
            : language === "zh"
                ? Qt.formatDate(date, "M月d日") + " " + time
                : Qt.formatDate(date, "MMM d") + " at " + time;
        if (state === "running")
            return l10n("Started ", "开始于") + when;
        if (String(status.action || "") === "initial-preview")
            return l10n("Checked ", "检查于") + when;
        return l10n("Last synced ", "上次同步于") + when;
    }

    function automationText(task) {
        if (!task || task.mode === "two-way" && !task.initialized)
            return l10n("Automatic sync unavailable", "自动同步不可用");
        return task.enabled
            ? l10n("Automatic sync on", "自动同步已开启")
            : l10n("Automatic sync paused", "自动同步已暂停");
    }

    function taskStatusMessage(task) {
        if (!task || !task.status)
            return "";
        if (needsAccessRepair(task))
            return l10n("Automatic sync is paused. Confirm both task folders, then repair the safety check.", "自动同步已暂停。请确认任务两端文件夹无误，然后修复安全检查。");
        var status = task.status;
        var action = String(status.action || "");
        var state = String(status.state || "never");
        if (action === "initial-preview" && state === "ok") {
            var started = Date.parse(String(status.started_at || ""));
            var finished = Date.parse(String(status.finished_at || ""));
            var duration = isNaN(started) || isNaN(finished) ? "" : elapsedText(Math.max(0, Math.round((finished - started) / 1000)));
            var planned = Number(status.planned_changes || 0);
            var plannedText = planned > 0 ? String(planned) : "";
            if (String(status.conflict_winner || "") === "")
                return l10n("Run Check first sync once more; the older result did not record the conflict rule.", "请再运行一次“检查首次同步”；旧版结果没有记录冲突规则。");
            return l10n("Safety check complete" + (duration !== "" ? " · " + duration : "") + (plannedText !== "" ? " · " + plannedText + " actions" : "") + " · no files changed.", "安全检查已完成" + (duration !== "" ? " · " + duration : "") + (plannedText !== "" ? " · " + plannedText + " 项操作" : "") + " · 未修改文件。");
        }
        if (task.mode === "two-way" && !task.initialized && firstSyncCheckWinner(task) !== "") {
            var storedPlanned = Number(task.first_sync_check.planned_changes || 0);
            return l10n("Safety check complete" + (storedPlanned > 0 ? " · " + storedPlanned + " actions" : "") + " · no files changed.", "安全检查已完成" + (storedPlanned > 0 ? " · " + storedPlanned + " 项操作" : "") + " · 未修改文件。");
        }
        return String(status.message || "");
    }

    function modeText(mode) {
        if (mode === "two-way")
            return l10n("Two-way sync", "双向同步");
        if (mode === "upload-only")
            return l10n("Upload only", "仅上传");
        if (mode === "download-only")
            return l10n("Download only", "仅下载");
        return String(mode || l10n("Unknown", "未知"));
    }

    function cleanLine(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function localPath(url) {
        var value = String(url || "");
        if (value.indexOf("file://") === 0)
            value = value.substring(7);
        try {
            return decodeURIComponent(value);
        } catch (error) {
            return value;
        }
    }

    function connectionFingerprint() {
        return JSON.stringify([connectionNameField.text.trim(), connectionUrlField.text.trim(), connectionUserField.text.trim(), connectionPasswordField.text, connectionAllowHttp, connectionInsecureTls]);
    }

    function invalidateConnectionTest() {
        if (editingConnectionId !== "")
            return;
        verifiedConnectionFingerprint = "";
        if (!verifyProcess.running) {
            actionStatus = l10n("Not tested yet. Test login and folder navigation before saving.", "尚未测试。保存前请测试登录和文件夹浏览。");
            actionError = "";
        }
    }

    function testConnectionForm() {
        if (connectionFormBusy || editingConnectionId !== "")
            return;
        var name = connectionNameField.text.trim();
        var url = connectionUrlField.text.trim();
        var username = connectionUserField.text.trim();
        var password = connectionPasswordField.text;
        if (name === "" || url === "" || username === "" || password === "") {
            actionError = l10n("Complete every connection field before testing.", "测试前请填写所有连接字段。");
            return;
        }
        var args = [controlPath, "cli", languagePreference, "connection", "verify", "--url", url, "--username", username, "--password-stdin", "--json"];
        if (connectionAllowHttp)
            args.push("--allow-http");
        if (connectionInsecureTls)
            args.push("--insecure-skip-verify");
        pendingVerifyFingerprint = connectionFingerprint();
        pendingPassword = password;
        verifyStdout = "";
        verifyStderr = "";
        actionStatus = l10n("Testing login and reading the NAS folder list…", "正在测试登录并读取 NAS 文件夹列表…");
        actionError = "";
        verifyProcess.command = args;
        verifyProcess.running = true;
    }

    function showRemoteFolderPicker() {
        if (addConnectionId === "") {
            actionError = l10n("Choose a NAS connection first.", "请先选择 NAS 连接。");
            return;
        }
        browseConnectionId = addConnectionId;
        browsePath = "";
        browseFolders = [];
        page = "remote-picker";
        clearMessages();
        loadRemoteFolders("");
    }

    function loadRemoteFolders(path) {
        if (folderProcess.running)
            return;
        browsePath = String(path || "");
        browseFolders = [];
        browseStdout = "";
        browseStderr = "";
        actionStatus = l10n("Loading NAS folders…", "正在加载 NAS 文件夹…");
        actionError = "";
        folderProcess.command = [controlPath, "cli", languagePreference, "connection", "folders", browseConnectionId, "--path", browsePath, "--json"];
        folderProcess.running = true;
    }

    function browseUp() {
        var parts = browsePath.split("/").filter(function (value) {
            return value !== "";
        });
        parts.pop();
        loadRemoteFolders(parts.join("/"));
    }

    function displayOutput(stdout, stderr, full) {
        var value = String(stderr || stdout || "").trim();
        if (value === "")
            return "";
        if (full)
            return value.length > 4000 ? value.substring(value.length - 4000) : value;
        var lines = value.split("\n");
        for (var i = lines.length - 1; i >= 0; i--) {
            var line = cleanLine(lines[i]);
            if (line !== "")
                return line.length > 280 ? line.substring(0, 277) + "…" : line;
        }
        return "";
    }

    function elapsedText(seconds) {
        var minutes = Math.floor(seconds / 60);
        var remainder = seconds % 60;
        return minutes + ":" + (remainder < 10 ? "0" : "") + remainder;
    }

    function previewProgressText() {
        if (actionWinner === "")
            return l10n("Checking changes (read-only) · ", "正在检查更改（只读） · ") + elapsedText(actionElapsedSeconds);
        var authority = actionWinner === "nas" ? l10n("keep NAS copy", "保留 NAS 副本") : l10n("keep this computer's copy", "保留此电脑副本");
        return l10n("Checking first sync · ", "正在检查首次同步 · ") + elapsedText(actionElapsedSeconds) + " · " + authority;
    }

    function firstSyncCheckReady(task) {
        return firstSyncCheckWinner(task) === firstSyncWinner;
    }

    function firstSyncCheckWinner(task) {
        if (!task || !task.first_sync_check)
            return "";
        return String(task.first_sync_check.conflict_winner || "");
    }

    function firstSyncRuleText() {
        return firstSyncWinner === "nas"
            ? l10n("If the same file differs, keep the NAS copy. Files found on only one side are still copied to the other.", "如果同一文件在两端不同，则保留 NAS 副本。只存在于一端的文件仍会复制到另一端。")
            : l10n("If the same file differs, keep this computer's copy. Files found on only one side are still copied to the other.", "如果同一文件在两端不同，则保留此电脑副本。只存在于一端的文件仍会复制到另一端。");
    }

    function firstSyncConfirmText() {
        var rule = firstSyncWinner === "nas"
            ? l10n("the NAS copy will be kept", "将保留 NAS 副本")
            : l10n("this computer's copy will be kept", "将保留此电脑副本");
        return l10n("Start the first sync? Files found on only one side will be copied to the other. If the same file differs, " + rule + ". Automatic sync will turn on after this run.", "开始首次同步吗？只存在于一端的文件将复制到另一端。如果同一文件在两端不同，" + rule + "。本次完成后将自动开启后台同步。");
    }

    function appendProcessLine(line, stderrLine) {
        var raw = String(line || "");
        if (raw === "")
            return;
        var key = stderrLine ? "processStderr" : "processStdout";
        var combined = String(root[key] || "") + raw + "\n";
        root[key] = combined.length > 12000 ? combined.substring(combined.length - 12000) : combined;
        var compact = cleanLine(raw);
        if (processFirstError === "" && (stderrLine || compact.indexOf("ERROR :") >= 0 || compact.indexOf("Unauthorized") >= 0))
            processFirstError = compact;
        if (!previewRunning)
            return;
        if ((compact.indexOf("NOTICE:") >= 0 && compact.indexOf(" / ") >= 0 && compact.indexOf("%") >= 0) || compact.indexOf("Transferred:") >= 0) {
            actionProgressLine = compact.replace(/^.*NOTICE:\s*/, "");
            actionOutput = actionProgressLine;
        }
    }

    function finishAction(exitCode) {
        var message = processFirstError !== "" ? processFirstError : displayOutput(processStdout, processStderr, showFullOutput);
        if (actionCancelRequested || exitCode === 130) {
            actionStatus = actionWinner !== ""
                ? l10n("First-sync check stopped. No files were changed.", "首次同步检查已停止。未修改任何文件。")
                : l10n("Read-only check stopped. No files were changed.", "只读检查已停止。未修改任何文件。")
            actionError = "";
            actionOutput = "";
        } else if (exitCode === 0) {
            actionStatus = actionKind === "preview" && actionWinner !== ""
                ? l10n("Safety check complete. You can now start the first sync.", "安全检查已完成。现在可以开始首次同步。")
                : actionKind === "preview"
                    ? l10n("Read-only check complete. No files were changed.", "只读检查已完成。未修改任何文件。")
                    : l10n(actionLabel + " complete", actionLabel + "已完成");
            actionError = "";
            actionOutput = displayOutput(processStdout, processStderr, showFullOutput);
            if (pendingConfirmBack)
                showPrimary("tasks");
        } else {
            actionStatus = "";
            if (message.indexOf("401 Unauthorized") >= 0) {
                actionError = l10n(
                    "fnOS intermittently rejected deep folder reads (401 Unauthorized). The saved login still works. FN sync now uses gentler WebDAV concurrency; retry this check.",
                    "fnOS 间歇性拒绝了深层文件夹读取请求（401 Unauthorized），已保存的登录仍然有效。飞牛现已降低 WebDAV 并发，请重试此检查。"
                );
            } else {
                actionError = message !== "" ? message : l10n(actionLabel + " failed", actionLabel + "失败");
            }
        }
        pendingConfirmBack = false;
        removingConnectionId = "";
        actionCancelRequested = false;
        refreshAfterAction();
    }

    function cancelPreview() {
        if (!previewRunning)
            return;
        actionCancelRequested = true;
        actionStatus = actionWinner !== "" ? l10n("Stopping first-sync check…", "正在停止首次同步检查…") : l10n("Stopping read-only check…", "正在停止只读检查…");
        actionProcess.running = false;
    }

    function clearMessages() {
        if (actionProcess.running)
            return;
        actionStatus = "";
        actionError = "";
        actionOutput = "";
    }

    function open() {
        controller.show();
        clearMessages();
        if (hostWidget)
            hostWidget.refreshStatus();
    }

    function close() {
        scrubPassword();
        controller.hide();
    }

    function toggle() {
        if (opened)
            close();
        else
            open();
    }
    function closeForPopoutSwitch() {
        close();
    }

    function showPrimary(target) {
        scrubPassword();
        page = target;
        selectedTaskId = "";
        editingConnectionId = "";
        clearMessages();
        if (hostWidget)
            hostWidget.refreshStatus();
        if (panelFlick)
            panelFlick.contentY = 0;
    }

    function showTask(task) {
        if (!task)
            return;
        selectedTaskId = String(task.id || "");
        firstSyncWinner = firstSyncCheckWinner(task) === "nas" ? "nas" : "local";
        page = "task";
        clearMessages();
        if (panelFlick)
            panelFlick.contentY = 0;
    }

    function showAddTask() {
        if (connections.length === 0) {
            page = "nas";
            actionError = l10n("Connect and authorize a NAS before creating sync tasks.", "请先连接并授权 NAS，再创建同步任务。");
            return;
        }
        resetTaskForm();
        addConnectionId = String(connections[0].id || "");
        taskConnectionDropdown.value = addConnectionId;
        page = "add-task";
        clearMessages();
        if (panelFlick)
            panelFlick.contentY = 0;
        Qt.callLater(function () {
            taskNameField.forceActiveFocus();
        });
    }

    function showConnectionForm(connection) {
        resetConnectionForm();
        if (connection) {
            editingConnectionId = String(connection.id || "");
            connectionNameField.text = String(connection.name || "");
            connectionUrlField.text = String(connection.url || "");
            connectionUserField.text = String(connection.username || "");
            connectionAllowHttp = connection.allow_http === true;
            connectionInsecureTls = connection.insecure_skip_verify === true;
        }
        page = "connection-form";
        clearMessages();
        if (!connection)
            actionStatus = l10n("Not tested yet. Test login and folder navigation before saving.", "尚未测试。保存前请测试登录和文件夹浏览。");
        if (panelFlick)
            panelFlick.contentY = 0;
        Qt.callLater(function () {
            connectionNameField.forceActiveFocus();
            if (!connection)
                root.discoverNas(true, false);
        });
    }

    function applyDiscoveredDevice(device) {
        if (!device)
            return;
        var webdavUrl = String(device.url || "");
        connectionNameField.text = String(device.name || "fnOS NAS");
        connectionUrlField.text = webdavUrl;
        connectionAllowHttp = webdavUrl !== "" && device.allow_http === true;
        connectionInsecureTls = webdavUrl !== "" && device.insecure_skip_verify === true;
        invalidateConnectionTest();
        if (webdavUrl === "")
            actionStatus = l10n("fnOS found, but WebDAV is off or uses a custom port. Enable it in fnOS Settings → File Sharing Protocols, then scan again.", "已发现 fnOS，但 WebDAV 未开启或使用了自定义端口。请在 fnOS 设置 → 文件共享协议中启用，然后重新扫描。");
        else if (device.webdav_verified === true)
            actionStatus = l10n("fnOS WebDAV found. Enter your account, then test the connection.", "已发现 fnOS WebDAV。请输入账号，然后测试连接。");
        else
            actionStatus = l10n("A WebDAV port is open. Enter your account, then test the connection.", "已发现开放的 WebDAV 端口。请输入账号，然后测试连接。");
        actionError = "";
    }

    function discoveredDeviceLabel(device) {
        var name = String(device && device.name || "fnOS NAS");
        var url = String(device && device.url || "");
        return url !== ""
            ? name + "  ·  " + url
            : name + "  ·  " + l10n("WebDAV not detected", "未检测到 WebDAV");
    }

    function openDiscoveredNas(device) {
        applyDiscoveredDevice(device);
        var managementUrl = String(device && device.management_url || "");
        if (managementUrl !== "")
            Quickshell.execDetached(["xdg-open", managementUrl]);
    }

    function discoverNas(autoFill, replaceFields) {
        if (discoveryProcess.running || connectionFormBusy)
            return;
        discoveryGeneration += 1;
        runningDiscoveryGeneration = discoveryGeneration;
        discoveryAutoFill = autoFill === true;
        discoveryReplaceFields = replaceFields === true;
        discoveredDevices = [];
        discoveryStdout = "";
        discoveryStderr = "";
        actionStatus = l10n("Scanning this LAN for fnOS…", "正在当前局域网中扫描 fnOS…");
        actionError = "";
        actionOutput = "";
        discoveryProcess.command = [controlPath, "discover"];
        discoveryProcess.running = true;
    }

    function scrubPassword() {
        pendingPassword = "";
        connectionPasswordField.text = "";
    }

    function refreshAfterAction() {
        if (hostWidget)
            hostWidget.refreshStatus();
        settleRefresh.restart();
    }

    function runAction(args, label, fullOutput, backAfter) {
        if (busy || !installed)
            return;
        actionLabel = label;
        actionKind = args.length > 1 && args[0] === "task" ? String(args[1]) : "";
        actionTaskId = args.length > 2 && args[0] === "task" ? String(args[2]) : "";
        actionWinner = "";
        for (var i = 0; i < args.length - 1; i++) {
            if (args[i] === "--winner")
                actionWinner = String(args[i + 1]);
        }
        actionElapsedSeconds = 0;
        actionCancelRequested = false;
        actionProgressLine = "";
        processFirstError = "";
        removingConnectionId = args.length > 2 && args[0] === "connection" && args[1] === "remove" ? String(args[2]) : "";
        showFullOutput = fullOutput === true;
        pendingConfirmBack = backAfter === true;
        actionStatus = actionKind === "preview" ? previewProgressText() : label + "…";
        actionError = "";
        actionOutput = "";
        processStdout = "";
        processStderr = "";
        actionProcess.command = [controlPath, "cli", languagePreference].concat(args);
        actionProcess.running = true;
    }

    function requestConfirm(message, args, label, backAfter) {
        pendingConfirmMessage = message;
        pendingConfirmArgs = args;
        pendingConfirmLabel = label;
        pendingConfirmBack = backAfter === true;
        confirmDialog.opened = true;
        confirmDialog.selectedIndex = 0;
    }

    function submitTask() {
        if (busy)
            return;
        var name = taskNameField.text.trim();
        var remote = taskRemoteField.text.trim();
        var local = taskLocalField.text.trim();
        if (name === "" || addConnectionId === "" || remote === "" || local === "") {
            actionError = l10n("Choose a NAS connection and complete every task field.", "请选择 NAS 连接并填写所有任务字段。");
            return;
        }
        createKind = "task";
        createUsesPassword = false;
        createStdout = "";
        createStderr = "";
        createProcess.command = [controlPath, "cli", languagePreference, "task", "add", "--name", name, "--connection", addConnectionId, "--remote-path", remote, "--local", local, "--mode", addMode];
        actionStatus = l10n("Creating sync task…", "正在创建同步任务…");
        actionError = "";
        actionOutput = "";
        createProcess.running = true;
    }

    function submitConnection() {
        if (connectionFormBusy)
            return;
        var name = connectionNameField.text.trim();
        var url = connectionUrlField.text.trim();
        var username = connectionUserField.text.trim();
        var password = connectionPasswordField.text;
        if (name === "" || url === "" || username === "" || (editingConnectionId === "" && password === "")) {
            actionError = editingConnectionId === "" ? l10n("Complete every connection field before authorizing.", "授权前请填写所有连接字段。") : l10n("Name, URL, and username are required. Leave password blank to keep it unchanged.", "名称、URL 和用户名为必填项；密码留空可保持不变。");
            return;
        }
        if (editingConnectionId === "" && verifiedConnectionFingerprint !== connectionFingerprint()) {
            actionError = l10n("Test login and folder navigation before saving this authorization.", "保存此授权前，请先测试登录和文件夹浏览。");
            return;
        }
        var args = [controlPath, "cli", languagePreference, "connection", editingConnectionId === "" ? "add" : "update"];
        if (editingConnectionId !== "")
            args.push(editingConnectionId);
        args.push("--name", name, "--url", url, "--username", username);
        if (connectionAllowHttp)
            args.push("--allow-http");
        else if (editingConnectionId !== "")
            args.push("--require-https");
        if (connectionInsecureTls)
            args.push("--insecure-skip-verify");
        else if (editingConnectionId !== "")
            args.push("--verify-tls");
        createUsesPassword = password !== "";
        if (createUsesPassword)
            args.push("--password-stdin");
        pendingPassword = password;
        connectionPasswordField.text = "";
        createKind = "connection";
        createStdout = "";
        createStderr = "";
        createProcess.command = args;
        actionStatus = editingConnectionId === "" ? l10n("Authorizing NAS…", "正在授权 NAS…") : l10n("Updating NAS authorization…", "正在更新 NAS 授权…");
        actionError = "";
        actionOutput = "";
        createProcess.running = true;
    }

    function resetTaskForm() {
        taskNameField.text = "";
        taskRemoteField.text = "";
        taskLocalField.text = "";
        addMode = "two-way";
        taskModeDropdown.value = "two-way";
    }

    function resetConnectionForm() {
        discoveryGeneration += 1;
        discoveredDevices = [];
        editingConnectionId = "";
        connectionNameField.text = "";
        connectionUrlField.text = "";
        connectionUserField.text = "";
        connectionPasswordField.text = "";
        connectionAllowHttp = false;
        connectionInsecureTls = false;
        verifiedConnectionFingerprint = "";
        pendingVerifyFingerprint = "";
    }

    Process {
        id: actionProcess
        running: false
        command: []
        stdout: SplitParser {
            onRead: function (line) {
                root.appendProcessLine(line, false);
            }
        }
        stderr: SplitParser {
            onRead: function (line) {
                root.appendProcessLine(line, true);
            }
        }
        onExited: function (exitCode) {
            root.pendingActionExitCode = exitCode;
            actionFinishTimer.restart();
        }
    }

    Timer {
        id: actionElapsedTimer
        interval: 1000
        repeat: true
        running: root.previewRunning
        onTriggered: {
            root.actionElapsedSeconds += 1;
            root.actionStatus = root.previewProgressText();
        }
    }

    Timer {
        id: actionFinishTimer
        interval: 100
        repeat: false
        onTriggered: root.finishAction(root.pendingActionExitCode)
    }

    Process {
        id: createProcess
        running: false
        command: []
        stdinEnabled: true
        onStarted: {
            if (root.createUsesPassword)
                write(root.pendingPassword + "\n");
            root.pendingPassword = "";
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.createStdout = text
        }
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.createStderr = text
        }
        onExited: function (exitCode) {
            stdinEnabled = true;
            var message = root.displayOutput(root.createStdout, root.createStderr, false);
            if (exitCode === 0) {
                root.actionError = "";
                if (root.createKind === "task") {
                    root.actionStatus = root.l10n("Task created. Open it to complete the guided first sync.", "任务已创建。请打开任务完成首次同步引导。");
                    root.resetTaskForm();
                    root.page = "tasks";
                } else {
                    root.actionStatus = root.l10n("NAS authorized. You can now reuse it for multiple tasks.", "NAS 已授权，现在可供多个任务复用。");
                    root.resetConnectionForm();
                    root.page = "nas";
                }
            } else {
                root.actionStatus = "";
                root.actionError = message !== "" ? message : root.l10n("Could not save changes", "无法保存更改");
            }
            root.createUsesPassword = false;
            root.refreshAfterAction();
        }
    }

    Process {
        id: verifyProcess
        running: false
        command: []
        stdinEnabled: true
        onStarted: {
            write(root.pendingPassword + "\n");
            root.pendingPassword = "";
            stdinEnabled = false;
        }
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.verifyStdout = text
        }
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.verifyStderr = text
        }
        onExited: function (exitCode) {
            stdinEnabled = true;
            if (exitCode === 0) {
                var payload = {};
                try {
                    payload = JSON.parse(root.verifyStdout || "{}");
                } catch (error) {
                    payload = {};
                }
                var folders = payload.folders instanceof Array ? payload.folders.length : 0;
                root.verifiedConnectionFingerprint = root.pendingVerifyFingerprint;
                root.actionStatus = root.l10n("Connection works; folder navigation returned " + folders + " root folder(s). You can now save.", "连接正常；文件夹浏览返回 " + folders + " 个根目录文件夹。现在可以保存。");
                root.actionError = "";
            } else {
                root.verifiedConnectionFingerprint = "";
                root.actionStatus = "";
                root.actionError = root.displayOutput(root.verifyStdout, root.verifyStderr, false) || root.l10n("Connection test failed", "连接测试失败");
            }
            root.pendingVerifyFingerprint = "";
        }
    }

    Process {
        id: discoveryProcess
        running: false
        command: []
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.discoveryStdout = text
        }
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.discoveryStderr = text
        }
        onExited: function (exitCode) {
            if (root.runningDiscoveryGeneration !== root.discoveryGeneration || root.page !== "connection-form")
                return;
            var payload = {};
            try {
                payload = JSON.parse(root.discoveryStdout || "{}");
            } catch (error) {
                payload = {};
            }
            if (exitCode !== 0 || payload.error) {
                root.discoveredDevices = [];
                root.actionStatus = "";
                root.actionError = String(payload.error || root.discoveryStderr || root.l10n("LAN scan failed", "局域网扫描失败")).trim();
                return;
            }
            root.discoveredDevices = payload.devices instanceof Array ? payload.devices : [];
            var networks = payload.networks instanceof Array ? payload.networks.join(", ") : "";
            if (root.discoveredDevices.length === 0) {
                root.actionStatus = networks !== ""
                    ? root.l10n("No fnOS NAS found on " + networks + ". You can still enter the WebDAV address.", "在 " + networks + " 未发现 fnOS NAS。仍可手动输入 WebDAV 地址。")
                    : root.l10n("No private LAN is available to scan. Enter the WebDAV address manually.", "没有可扫描的专用局域网。请手动输入 WebDAV 地址。");
                root.actionError = "";
                return;
            }
            var formIsEmpty = connectionNameField.text.trim() === "" && connectionUrlField.text.trim() === "";
            if (root.discoveredDevices.length === 1 && root.discoveryAutoFill && (root.discoveryReplaceFields || formIsEmpty)) {
                root.applyDiscoveredDevice(root.discoveredDevices[0]);
            } else if (root.discoveredDevices.length === 1) {
                root.actionStatus = root.l10n("Found one fnOS NAS. Select it below to use its address.", "发现一台 fnOS NAS。请在下方选择以使用其地址。");
                root.actionError = "";
            } else {
                root.actionStatus = root.l10n("Found " + root.discoveredDevices.length + " possible fnOS devices. Choose one below.", "发现 " + root.discoveredDevices.length + " 台可能的 fnOS 设备。请在下方选择。");
                root.actionError = "";
            }
        }
    }

    Process {
        id: folderProcess
        running: false
        command: []
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.browseStdout = text
        }
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.browseStderr = text
        }
        onExited: function (exitCode) {
            if (exitCode === 0) {
                try {
                    var payload = JSON.parse(root.browseStdout || "{}");
                    root.browseFolders = payload.folders instanceof Array ? payload.folders : [];
                    root.actionStatus = root.browseFolders.length > 0 ? root.l10n("Choose a folder or open it to browse deeper.", "请选择文件夹，或打开它继续浏览。") : root.l10n("No subfolders here. You can use this folder.", "这里没有子文件夹，可以使用当前文件夹。");
                    root.actionError = "";
                } catch (error) {
                    root.browseFolders = [];
                    root.actionStatus = "";
                    root.actionError = root.l10n("The NAS returned an invalid folder list", "NAS 返回了无效的文件夹列表");
                }
            } else {
                root.browseFolders = [];
                root.actionStatus = "";
                root.actionError = root.displayOutput(root.browseStdout, root.browseStderr, false) || root.l10n("Could not browse this NAS", "无法浏览此 NAS");
            }
        }
    }

    FolderDialog {
        id: localFolderDialog
        title: root.l10n("Choose a local sync folder", "选择本地同步文件夹")
        currentFolder: "file://" + Quickshell.env("HOME")
        onAccepted: taskLocalField.text = root.localPath(selectedFolder)
    }

    Timer {
        id: settleRefresh
        interval: 800
        repeat: false
        onTriggered: if (root.hostWidget)
            root.hostWidget.refreshStatus()
    }

    KeyboardPanel {
        id: panel
        anchorItem: root.anchorItem
        owner: root.barIdentity
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        contentWidth: panel.fittedContentWidth(Style.space(520))
        contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(720))

        PanelKeyCatcher {
            id: keyCatcher
            anchors.fill: parent
            blocked: root.editorFocused || confirmDialog.opened
            onCloseRequested: {
                if (root.page === "nas")
                    root.showPrimary("settings");
                else if (root.primaryPage)
                    root.close();
                else if (root.page === "remote-picker")
                    root.page = "add-task";
                else if (root.page === "task" || root.page === "add-task")
                    root.showPrimary("tasks");
                else
                    root.showPrimary("nas");
            }
            onTextKey: function (text) {
                if (root.page === "tasks" && (text === "a" || text === "A"))
                    root.showAddTask();
                else if (root.primaryPage && (text === "r" || text === "R") && root.hostWidget)
                    root.hostWidget.refreshStatus();
                else if (root.page === "tasks" && (text === "s" || text === "S") && root.hostWidget)
                    root.hostWidget.syncNow();
            }

            Flickable {
                id: panelFlick
                anchors.fill: parent
                contentWidth: width
                contentHeight: content.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.VerticalFlick
                interactive: contentHeight > height

                Column {
                    id: content
                    width: panelFlick.width
                    spacing: Style.spacing.lg

                    PanelHero {
                        visible: root.primaryPage
                        width: parent.width
                        title: root.l10n("FN sync", "飞牛")
                        meta: !root.installed
                            ? root.l10n("Plugin runtime missing", "插件运行组件缺失")
                            : !root.runtimeReady
                                ? root.l10n("One-time setup required", "需要完成一次设置")
                                : root.l10n(root.tasks.length + " tasks · " + root.connections.length + " NAS connections", root.tasks.length + " 个任务 · " + root.connections.length + " 个 NAS 连接")
                        foreground: root.foreground
                        fontFamily: root.fontFamily
                        iconComponent: Component {
                            FnSyncIcon {
                                iconSize: Style.font.title * 1.7
                                color: root.errorCount() > 0 ? root.urgent : root.accent
                            }
                        }
                    }

                    Row {
                        visible: root.primaryPage
                        width: parent.width
                        spacing: Style.spacing.sm
                        Button {
                            width: (parent.width - parent.spacing) / 2
                            text: root.l10n("Tasks", "任务")
                            bordered: true
                            focusable: true
                            selected: root.page === "tasks"
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.showPrimary("tasks")
                        }
                        Button {
                            width: (parent.width - parent.spacing) / 2
                            text: root.l10n("Settings", "设置")
                            bordered: true
                            focusable: true
                            selected: root.page === "settings" || root.page === "nas"
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.showPrimary("settings")
                        }
                    }

                    BorderSurface {
                        visible: root.primaryPage && (!root.installed || !root.runtimeReady)
                        width: parent.width
                        implicitHeight: setupContent.implicitHeight + Style.spacing.xl * 2
                        color: Util.alpha(root.accent, 0.13)
                        borderSpec: Border.flat(root.accent, Style.focusBorderWidth)
                        radius: Style.cornerRadius

                        Column {
                            id: setupContent
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: Style.spacing.rowPaddingX
                            anchors.rightMargin: Style.spacing.rowPaddingX
                            spacing: Style.spacing.md

                            Text {
                                width: parent.width
                                text: root.installed ? root.l10n("Finish FN Sync setup", "完成飞牛设置") : root.l10n("FN Sync needs to be reinstalled", "需要重新安装飞牛")
                                color: root.foreground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.subtitle
                                font.bold: true
                            }

                            Text {
                                width: parent.width
                                text: root.installed
                                    ? root.l10n("The client is already included in this plugin. Authorize the required Arch components once to enable file transfer and the desktop client.", "客户端已包含在插件中。只需授权安装所需的 Arch 组件，即可启用文件传输和桌面客户端。")
                                    : root.l10n("The plugin checkout does not contain its bundled client. Update or reinstall the plugin.", "插件目录中没有内置客户端，请更新或重新安装插件。")
                                color: root.dimForeground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.body
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                visible: root.statusError !== ""
                                width: parent.width
                                text: root.statusError
                                color: root.urgent
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                                wrapMode: Text.WordWrap
                            }

                            Button {
                                visible: root.installed
                                width: parent.width
                                text: root.installingDependencies ? root.l10n("Installing required components…", "正在安装所需组件…") : root.l10n("Install required components", "安装所需组件")
                                bordered: true
                                focusable: true
                                enabled: !root.installingDependencies
                                opacity: enabled ? 1.0 : 0.55
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: if (root.hostWidget)
                                    root.hostWidget.installDependencies()
                            }
                        }
                    }

                    Column {
                        visible: root.page === "tasks" && root.runtimeReady
                        width: parent.width
                        spacing: Style.spacing.lg

                        PanelSectionHeader {
                            text: root.l10n("TASK ACTIONS", "任务操作")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Row {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Sync all now", "立即同步全部")
                                bordered: true
                                focusable: true
                                enabled: root.syncAllReady
                                opacity: enabled ? 1.0 : 0.42
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: if (root.hostWidget)
                                    root.hostWidget.syncNow()
                            }
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Create task", "创建任务")
                                bordered: true
                                focusable: true
                                enabled: root.createTaskReady
                                opacity: enabled ? 1.0 : 0.42
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.showAddTask()
                            }
                        }

                        PanelSectionHeader {
                            text: root.l10n("SYNC TASKS", "同步任务")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Text {
                            visible: root.tasks.length === 0
                            width: parent.width
                            text: root.connections.length === 0 ? root.l10n("Open Settings and connect a NAS once, then create as many tasks as you need.", "请在设置中连接一次 NAS，然后按需创建多个任务。") : root.l10n("No tasks yet. Create the first task with a saved NAS connection.", "尚无任务。请使用已保存的 NAS 连接创建第一个任务。")
                            color: root.dimForeground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.body
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            topPadding: Style.spacing.xl
                            bottomPadding: Style.spacing.xl
                        }

                        Repeater {
                            model: root.tasks
                            BorderSurface {
                                required property var modelData
                                width: content.width
                                implicitHeight: taskCard.implicitHeight + Style.spacing.xl * 2
                                color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                                borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
                                radius: Style.cornerRadius
                                Column {
                                    id: taskCard
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.leftMargin: Style.spacing.rowPaddingX
                                    anchors.rightMargin: Style.spacing.rowPaddingX
                                    spacing: Style.spacing.sm
                                    Row {
                                        width: parent.width
                                        spacing: Style.spacing.sm
                                        Column {
                                            width: parent.width - taskManage.implicitWidth - parent.spacing
                                            spacing: Style.spacing.xs
                                            Text {
                                                width: parent.width
                                                text: String(modelData.name || modelData.id || root.l10n("Sync task", "同步任务"))
                                                color: root.foreground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.subtitle
                                                font.bold: true
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                width: parent.width
                                                text: String(modelData.connection_name || "fnOS NAS") + " · " + root.modeText(modelData.mode)
                                                color: root.dimForeground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                elide: Text.ElideRight
                                            }
                                        }
                                        Button {
                                            id: taskManage
                                            text: root.l10n("Manage", "管理")
                                            bordered: true
                                            focusable: true
                                            enabled: !root.busy
                                            foreground: root.foreground
                                            fontFamily: root.fontFamily
                                            onClicked: root.showTask(modelData)
                                        }
                                    }
                                    BorderSurface {
                                        width: parent.width
                                        implicitHeight: taskCardStatus.implicitHeight + Style.spacing.lg * 2
                                        color: root.taskListStatusFill(modelData)
                                        borderSpec: root.taskListStatusBorder(modelData)
                                        radius: Style.cornerRadius

                                        Column {
                                            id: taskCardStatus
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            anchors.leftMargin: Style.spacing.rowPaddingX
                                            anchors.rightMargin: Style.spacing.rowPaddingX
                                            spacing: Style.spacing.xs

                                            Text {
                                                width: parent.width
                                                text: root.stateText(modelData)
                                                color: root.stateColor(modelData)
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.subtitle
                                                font.bold: true
                                            }

                                            Text {
                                                width: parent.width
                                                text: root.taskListStatusDetail(modelData)
                                                color: root.needsAccessRepair(modelData) || modelData.status && modelData.status.state === "error" ? root.urgent : root.foreground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                wrapMode: Text.WordWrap
                                            }
                                        }
                                    }

                                    Row {
                                        width: parent.width
                                        spacing: Style.spacing.lg

                                        Column {
                                            width: (parent.width - parent.spacing) / 2
                                            spacing: Style.spacing.xs

                                            Text {
                                                width: parent.width
                                                text: root.l10n("THIS COMPUTER", "此电脑")
                                                color: root.dimForeground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                font.bold: true
                                            }

                                            Text {
                                                width: parent.width
                                                text: String(modelData.local_path || "")
                                                color: root.foreground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                elide: Text.ElideMiddle
                                            }
                                        }

                                        Column {
                                            width: (parent.width - parent.spacing) / 2
                                            spacing: Style.spacing.xs

                                            Text {
                                                width: parent.width
                                                text: root.l10n("NAS FOLDER", "NAS 文件夹")
                                                color: root.dimForeground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                font.bold: true
                                            }

                                            Text {
                                                width: parent.width
                                                text: "NAS:/" + String(modelData.remote_path || "")
                                                color: root.foreground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                elide: Text.ElideMiddle
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Column {
                        visible: root.page === "nas" && root.runtimeReady
                        width: parent.width
                        spacing: Style.spacing.lg

                        PanelPageHeader {
                            width: parent.width
                            parentTitle: root.l10n("Settings", "设置")
                            backAccessibleText: root.l10n("Back to Settings", "返回设置")
                            title: root.l10n("NAS connections", "NAS 连接")
                            foreground: root.foreground
                            dimForeground: root.dimForeground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onBackRequested: root.showPrimary("settings")
                        }

                        PanelSectionHeader {
                            text: root.l10n("CONNECTION ACTIONS", "连接操作")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Button {
                            width: parent.width
                            text: root.connections.length > 0 ? root.l10n("Add NAS connection", "添加 NAS 连接") : root.l10n("Connect NAS", "连接 NAS")
                            bordered: true
                            focusable: true
                            enabled: root.installed && !root.busy
                            opacity: enabled ? 1.0 : 0.42
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.showConnectionForm(null)
                        }

                        PanelSectionHeader {
                            text: root.l10n("SAVED CONNECTIONS", "已保存的连接")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Text {
                            visible: root.connections.length === 0
                            width: parent.width
                            text: root.l10n("No NAS connections yet. Connect using the official fnOS WebDAV service.", "尚无 NAS 连接。请使用 fnOS 官方 WebDAV 服务连接。")
                            color: root.dimForeground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.body
                            wrapMode: Text.WordWrap
                            horizontalAlignment: Text.AlignHCenter
                            topPadding: Style.spacing.xl
                            bottomPadding: Style.spacing.xl
                        }

                        Repeater {
                            model: root.connections
                            BorderSurface {
                                required property var modelData
                                width: content.width
                                implicitHeight: nasCard.implicitHeight + Style.spacing.xl * 2
                                color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                                borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
                                radius: Style.cornerRadius
                                Column {
                                    id: nasCard
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.leftMargin: Style.spacing.rowPaddingX
                                    anchors.rightMargin: Style.spacing.rowPaddingX
                                    spacing: Style.spacing.sm

                                    Row {
                                        width: parent.width
                                        spacing: Style.spacing.sm

                                        Text {
                                            width: parent.width - nasUsageBadge.width - parent.spacing
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: String(modelData.name || "fnOS NAS")
                                            color: root.foreground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.subtitle
                                            font.bold: true
                                            elide: Text.ElideRight
                                        }

                                        BorderSurface {
                                            id: nasUsageBadge
                                            anchors.verticalCenter: parent.verticalCenter
                                            implicitWidth: nasUsageBadgeText.implicitWidth + Style.spacing.lg * 2
                                            implicitHeight: nasUsageBadgeText.implicitHeight + Style.spacing.sm * 2
                                            width: implicitWidth
                                            height: implicitHeight
                                            color: Util.alpha(root.foreground, 0.055)
                                            borderSpec: Border.controlSpec("normal", root.foreground, root.accent, root.urgent)
                                            radius: height / 2

                                            Text {
                                                id: nasUsageBadgeText
                                                anchors.centerIn: parent
                                                text: root.connectionUseCount(modelData.id) === 1
                                                    ? root.l10n("1 TASK", "1 个任务")
                                                    : root.l10n(root.connectionUseCount(modelData.id) + " TASKS", root.connectionUseCount(modelData.id) + " 个任务")
                                                color: root.foreground
                                                font.family: root.fontFamily
                                                font.pixelSize: Style.font.caption
                                                font.bold: true
                                            }
                                        }
                                    }

                                    Text {
                                        width: parent.width
                                        text: String(modelData.username || "") + " · " + String(modelData.url || "")
                                        color: root.dimForeground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                        elide: Text.ElideMiddle
                                    }

                                    Text {
                                        width: parent.width
                                        text: root.l10n("CONNECTION ACTIONS", "连接操作")
                                        color: root.dimForeground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                        font.bold: true
                                    }

                                    Row {
                                        width: parent.width
                                        spacing: Style.spacing.sm
                                        Button {
                                            width: (parent.width - Style.spacing.sm * 2) / 3
                                            text: root.l10n("Test connection", "测试连接")
                                            bordered: true
                                            focusable: true
                                            enabled: !root.busy
                                            foreground: root.foreground
                                            fontFamily: root.fontFamily
                                            onClicked: root.runAction(["connection", "test", String(modelData.id)], root.l10n("Connection test", "连接测试"), false, false)
                                        }
                                        Button {
                                            width: (parent.width - Style.spacing.sm * 2) / 3
                                            text: root.l10n("Edit connection", "编辑连接")
                                            bordered: true
                                            focusable: true
                                            enabled: !root.busy
                                            foreground: root.foreground
                                            fontFamily: root.fontFamily
                                            onClicked: root.showConnectionForm(modelData)
                                        }
                                        Button {
                                            width: (parent.width - Style.spacing.sm * 2) / 3
                                            text: root.removingConnectionId === String(modelData.id) ? root.l10n("Removing…", "正在移除…") : root.l10n("Remove", "移除")
                                            bordered: true
                                            focusable: true
                                            enabled: !root.busy && root.connectionUseCount(modelData.id) === 0
                                            foreground: root.connectionUseCount(modelData.id) === 0 ? root.urgent : root.dimForeground
                                            fontFamily: root.fontFamily
                                            onClicked: root.requestConfirm(root.l10n("Remove this saved NAS authorization? No files will be deleted.", "移除此 NAS 授权？不会删除任何文件。"), ["connection", "remove", String(modelData.id)], root.l10n("Remove NAS connection", "移除 NAS 连接"), false)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Column {
                        visible: root.page === "settings" && root.runtimeReady
                        width: parent.width
                        spacing: Style.spacing.lg

                        PanelSectionHeader {
                            text: root.l10n("NAS CONNECTIONS", "NAS 连接")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        BorderSurface {
                            width: parent.width
                            implicitHeight: settingsNasRow.implicitHeight + Style.spacing.xl * 2
                            color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                            borderSpec: Border.controlSpec("normal", root.foreground, root.accent, root.urgent)
                            radius: Style.cornerRadius

                            Row {
                                id: settingsNasRow
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: Style.spacing.rowPaddingX
                                anchors.rightMargin: Style.spacing.rowPaddingX
                                spacing: Style.spacing.sm

                                Column {
                                    width: parent.width - manageNasConnections.implicitWidth - parent.spacing
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: Style.spacing.xs

                                    Text {
                                        width: parent.width
                                        text: root.l10n("Saved NAS authorizations", "已保存的 NAS 授权")
                                        color: root.foreground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.subtitle
                                        font.bold: true
                                    }

                                    Text {
                                        width: parent.width
                                        text: root.connections.length > 0
                                            ? root.l10n(root.connections.length + " connection(s) available to every sync task", root.connections.length + " 个连接可供所有同步任务使用")
                                            : root.l10n("Connect a NAS before creating a sync task", "创建同步任务前请先连接 NAS")
                                        color: root.dimForeground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.caption
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                Button {
                                    id: manageNasConnections
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: root.connections.length > 0 ? root.l10n("Open", "打开") : root.l10n("Connect", "连接")
                                    bordered: true
                                    focusable: true
                                    enabled: root.installed && !root.busy
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                    onClicked: root.showPrimary("nas")
                                }
                            }
                        }

                        PanelSectionHeader {
                            text: root.l10n("CLIENT SETTINGS", "客户端设置")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        BorderSurface {
                            width: parent.width
                            implicitHeight: languageSettings.implicitHeight + Style.spacing.xl * 2
                            color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                            borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
                            radius: Style.cornerRadius
                            Column {
                                id: languageSettings
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: Style.spacing.rowPaddingX
                                anchors.rightMargin: Style.spacing.rowPaddingX
                                spacing: Style.spacing.sm
                                Text {
                                    text: root.l10n("Language", "语言")
                                    color: root.foreground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.subtitle
                                    font.bold: true
                                }
                                Text {
                                    width: parent.width
                                    text: root.l10n("System default follows the desktop locale. You can override it here.", "“跟随系统”会使用桌面区域设置，也可以在此手动覆盖。")
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.bodySmall
                                    wrapMode: Text.WordWrap
                                }
                                Dropdown {
                                    id: languageDropdown
                                    width: parent.width
                                    label: root.l10n("DISPLAY LANGUAGE", "显示语言")
                                    value: root.languagePreference
                                    options: root.languageOptions()
                                    foreground: root.foreground
                                    accent: root.accent
                                    fontFamily: root.fontFamily
                                    onChanged: function (value) {
                                        if (root.hostWidget)
                                            root.hostWidget.saveLanguage(value);
                                    }
                                }
                            }
                        }

                        Button {
                            width: parent.width
                            text: root.l10n("Open full client", "打开完整客户端")
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: root.installed && !root.busy
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: if (root.hostWidget)
                                root.hostWidget.openClient()
                        }
                    }

                    Column {
                        visible: root.page === "task"
                        width: parent.width
                        spacing: Style.spacing.lg

                        PanelPageHeader {
                            width: parent.width
                            parentTitle: root.l10n("Tasks", "任务")
                            backAccessibleText: root.l10n("Back to Tasks", "返回任务")
                            title: root.selectedTask ? String(root.selectedTask.name || root.l10n("Sync task", "同步任务")) : root.l10n("Sync task", "同步任务")
                            foreground: root.foreground
                            dimForeground: root.dimForeground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onBackRequested: root.showPrimary("tasks")
                        }

                        PanelSectionHeader {
                            visible: root.selectedTask !== null
                            text: root.l10n("STATUS", "状态")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        BorderSurface {
                            visible: root.selectedTask !== null
                            width: parent.width
                            implicitHeight: taskStatusColumn.implicitHeight + Style.spacing.xl * 2
                            color: root.stateSurfaceFill(root.selectedTask)
                            borderSpec: root.stateSurfaceBorder(root.selectedTask)
                            radius: Style.cornerRadius

                            Column {
                                id: taskStatusColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: Style.spacing.rowPaddingX
                                anchors.rightMargin: Style.spacing.rowPaddingX
                                spacing: Style.spacing.sm

                                Row {
                                    width: parent.width
                                    spacing: Style.spacing.sm

                                    Text {
                                        width: parent.width - taskModeBadge.width - parent.spacing
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: root.selectedTask ? root.stateText(root.selectedTask) : ""
                                        color: root.selectedTask ? root.stateColor(root.selectedTask) : root.foreground
                                        font.family: root.fontFamily
                                        font.pixelSize: Style.font.heading
                                        font.bold: true
                                        wrapMode: Text.WordWrap
                                    }

                                    BorderSurface {
                                        id: taskModeBadge
                                        anchors.verticalCenter: parent.verticalCenter
                                        implicitWidth: taskModeBadgeText.implicitWidth + Style.spacing.lg * 2
                                        implicitHeight: taskModeBadgeText.implicitHeight + Style.spacing.sm * 2
                                        width: implicitWidth
                                        height: implicitHeight
                                        color: "transparent"
                                        borderSpec: Border.controlSpec("normal", root.foreground, root.accent, root.urgent)
                                        radius: height / 2

                                        Text {
                                            id: taskModeBadgeText
                                            anchors.centerIn: parent
                                            text: root.selectedTask ? root.modeText(root.selectedTask.mode).toUpperCase() : ""
                                            color: root.foreground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.caption
                                            font.bold: true
                                        }
                                    }
                                }

                                Text {
                                    width: parent.width
                                    text: root.stateSummary(root.selectedTask)
                                    color: root.foreground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.body
                                    wrapMode: Text.WordWrap
                                }

                                Text {
                                    width: parent.width
                                    text: root.statusTimeText(root.selectedTask) + " · " + root.automationText(root.selectedTask)
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    font.bold: true
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }

                        PanelSectionHeader {
                            visible: root.selectedTask !== null
                            text: root.l10n("SYNC INFORMATION", "同步信息")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        BorderSurface {
                            visible: root.selectedTask !== null
                            width: parent.width
                            implicitHeight: taskInformationColumn.implicitHeight + Style.spacing.xl * 2
                            color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                            borderSpec: Border.controlSpec("normal", root.foreground, root.accent, root.urgent)
                            radius: Style.cornerRadius

                            Column {
                                id: taskInformationColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: Style.spacing.rowPaddingX
                                anchors.rightMargin: Style.spacing.rowPaddingX
                                spacing: Style.spacing.md

                                Repeater {
                                    model: root.selectedTask ? [
                                        {
                                            label: root.l10n("NAS CONNECTION", "NAS 连接"),
                                            value: String(root.selectedTask.connection_name || "") + " · " + String(root.selectedTask.remote_url || "")
                                        },
                                        {
                                            label: root.l10n("THIS COMPUTER", "此电脑"),
                                            value: String(root.selectedTask.local_path || "")
                                        },
                                        {
                                            label: root.l10n("NAS FOLDER", "NAS 文件夹"),
                                            value: "NAS:/" + String(root.selectedTask.remote_path || "")
                                        }
                                    ] : []

                                    delegate: Column {
                                        required property var modelData
                                        width: taskInformationColumn.width
                                        spacing: Style.spacing.xs

                                        Text {
                                            width: parent.width
                                            text: modelData.label
                                            color: root.dimForeground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.caption
                                            font.bold: true
                                        }

                                        Text {
                                            width: parent.width
                                            text: modelData.value
                                            color: root.foreground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.bodySmall
                                            wrapMode: Text.WrapAnywhere
                                        }
                                    }
                                }
                            }
                        }

                        PanelSectionHeader {
                            visible: root.selectedTask !== null && root.selectedTask.mode === "two-way" && !root.selectedTask.initialized
                            text: root.l10n("FIRST SYNC", "首次同步")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        BorderSurface {
                            visible: root.selectedTask !== null && root.selectedTask.mode === "two-way" && !root.selectedTask.initialized
                            width: parent.width
                            implicitHeight: firstSyncColumn.implicitHeight + Style.spacing.xl * 2
                            color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                            borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
                            radius: Style.cornerRadius
                            Column {
                                id: firstSyncColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: Style.spacing.rowPaddingX
                                anchors.rightMargin: Style.spacing.rowPaddingX
                                spacing: Style.spacing.sm
                                Text {
                                    width: parent.width
                                    text: root.previewRunning && root.actionTaskId === String(root.selectedTask.id)
                                        ? root.l10n("Checking both folders", "正在检查两端文件夹")
                                        : root.firstSyncCheckReady(root.selectedTask)
                                            ? root.l10n("Ready to start", "可以开始了")
                                            : root.l10n("Choose the copy to keep for conflicts", "选择冲突时要保留的副本")
                                    color: root.firstSyncCheckReady(root.selectedTask) ? root.accent : root.foreground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.subtitle
                                    font.bold: true
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    width: parent.width
                                    text: root.l10n("This choice matters only when the same file exists on both sides with different contents.", "此选择只在同一文件同时存在于两端且内容不同时生效。")
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    wrapMode: Text.WordWrap
                                }
                                Row {
                                    width: parent.width
                                    spacing: Style.spacing.sm
                                    Button {
                                        width: (parent.width - parent.spacing) / 2
                                        text: root.l10n("Keep this computer's copy", "保留此电脑副本")
                                        bordered: true
                                        focusable: true
                                        selected: root.firstSyncWinner === "local"
                                        enabled: !root.busy
                                        opacity: enabled ? 1.0 : 0.42
                                        foreground: root.foreground
                                        fontFamily: root.fontFamily
                                        onClicked: root.firstSyncWinner = "local"
                                    }
                                    Button {
                                        width: (parent.width - parent.spacing) / 2
                                        text: root.l10n("Keep the NAS copy", "保留 NAS 副本")
                                        bordered: true
                                        focusable: true
                                        selected: root.firstSyncWinner === "nas"
                                        enabled: !root.busy
                                        opacity: enabled ? 1.0 : 0.42
                                        foreground: root.foreground
                                        fontFamily: root.fontFamily
                                        onClicked: root.firstSyncWinner = "nas"
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: root.firstSyncRuleText()
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    wrapMode: Text.WordWrap
                                }
                                BorderSurface {
                                    visible: root.previewRunning && root.actionTaskId === String(root.selectedTask.id)
                                    width: parent.width
                                    implicitHeight: firstSyncProgressColumn.implicitHeight + Style.spacing.lg * 2
                                    color: Util.alpha(root.accent, 0.10)
                                    borderSpec: Border.flat(root.accent, Style.normalBorderWidth)
                                    radius: Style.cornerRadius
                                    Column {
                                        id: firstSyncProgressColumn
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.leftMargin: Style.spacing.rowPaddingX
                                        anchors.rightMargin: Style.spacing.rowPaddingX
                                        spacing: Style.spacing.xs
                                        Text {
                                            width: parent.width
                                            text: root.previewProgressText()
                                            color: root.foreground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.bodySmall
                                            font.bold: true
                                            wrapMode: Text.WordWrap
                                        }
                                        Text {
                                            width: parent.width
                                            text: root.l10n("This read-only check scans both folders and can take several minutes. No files are being changed.", "此只读检查会扫描两端文件夹，可能需要几分钟。不会修改任何文件。")
                                            color: root.dimForeground
                                            font.family: root.fontFamily
                                            font.pixelSize: Style.font.caption
                                            wrapMode: Text.WordWrap
                                        }
                                        Text {
                                            visible: root.actionProgressLine !== ""
                                            width: parent.width
                                            text: root.actionProgressLine
                                            color: root.dimForeground
                                            font.family: "monospace"
                                            font.pixelSize: Style.font.caption
                                            wrapMode: Text.WrapAnywhere
                                        }
                                        Button {
                                            width: parent.width
                                            text: root.l10n("Stop check", "停止检查")
                                            leftAlign: true
                                            bordered: true
                                            focusable: true
                                            foreground: root.urgent
                                            fontFamily: root.fontFamily
                                            onClicked: root.cancelPreview()
                                        }
                                    }
                                }
                                Button {
                                    width: parent.width
                                    text: root.previewRunning && root.actionTaskId === String(root.selectedTask.id)
                                        ? root.l10n("Checking first sync…", "正在检查首次同步…")
                                        : root.firstSyncCheckReady(root.selectedTask)
                                            ? root.l10n("Start first sync", "开始首次同步")
                                            : root.l10n("Check first sync", "检查首次同步")
                                    bordered: true
                                    focusable: true
                                    selected: enabled
                                    enabled: !root.busy
                                    opacity: enabled ? 1.0 : 0.42
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                    onClicked: {
                                        if (root.firstSyncCheckReady(root.selectedTask)) {
                                            root.requestConfirm(root.firstSyncConfirmText(), ["task", "initialize", String(root.selectedTask.id), "--winner", root.firstSyncWinner, "--apply"], root.l10n("Start first sync", "开始首次同步"), false);
                                        } else {
                                            root.runAction(["task", "preview", String(root.selectedTask.id), "--winner", root.firstSyncWinner], root.l10n("Check first sync", "检查首次同步"), false, false);
                                        }
                                    }
                                }
                                Button {
                                    visible: root.firstSyncCheckReady(root.selectedTask) && !root.previewRunning
                                    width: parent.width
                                    text: root.l10n("Check again", "重新检查")
                                    leftAlign: true
                                    bordered: true
                                    focusable: true
                                    enabled: !root.busy
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                    onClicked: root.runAction(["task", "preview", String(root.selectedTask.id), "--winner", root.firstSyncWinner], root.l10n("Check first sync", "检查首次同步"), false, false)
                                }
                                Text {
                                    width: parent.width
                                    text: root.firstSyncCheckReady(root.selectedTask)
                                        ? root.l10n("Starting the first sync will also turn on automatic background sync.", "开始首次同步后，也会自动开启后台同步。")
                                        : root.l10n("Read-only · no files will change · large folders can take several minutes.", "只读 · 不会修改文件 · 大型文件夹可能需要几分钟。")
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }

                        PanelSectionHeader {
                            visible: root.selectedTask !== null && !(root.selectedTask.mode === "two-way" && !root.selectedTask.initialized)
                            text: root.l10n("SYNC CONTROL", "同步控制")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Toggle {
                            visible: root.selectedTask !== null && !(root.selectedTask.mode === "two-way" && !root.selectedTask.initialized)
                            width: parent.width
                            label: root.l10n("Automatic background sync", "自动后台同步")
                            description: root.needsAccessRepair(root.selectedTask)
                                ? root.l10n("Paused by the safety check · repair before resuming", "已由安全检查暂停 · 修复后才能恢复")
                                : root.selectedTask && root.selectedTask.enabled
                                    ? root.l10n("On · use this switch to pause periodic sync", "已开启 · 可用此开关暂停定时同步")
                                    : root.l10n("Off · use this switch to enable periodic sync", "已关闭 · 可用此开关启用定时同步")
                            checked: root.selectedTask ? root.selectedTask.enabled === true : false
                            enabled: root.selectedTask !== null && !root.busy && !root.needsAccessRepair(root.selectedTask)
                            foreground: root.foreground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onClicked: if (root.selectedTask)
                                root.runAction(["task", root.selectedTask.enabled ? "disable" : "enable", String(root.selectedTask.id)], root.selectedTask.enabled ? root.l10n("Pause task", "暂停任务") : root.l10n("Enable task", "启用任务"), false, false)
                        }

                        PanelSectionHeader {
                            visible: root.needsAccessRepair(root.selectedTask)
                            text: root.l10n("SAFETY CHECK", "安全检查")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        BorderSurface {
                            visible: root.needsAccessRepair(root.selectedTask)
                            width: parent.width
                            implicitHeight: repairAccessColumn.implicitHeight + Style.spacing.xl * 2
                            color: Style.normalFillFor(root.foreground, root.accent, root.urgent)
                            borderSpec: Border.controlSpec("normal", root.foreground, root.accent)
                            radius: Style.cornerRadius
                            Column {
                                id: repairAccessColumn
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: Style.spacing.rowPaddingX
                                anchors.rightMargin: Style.spacing.rowPaddingX
                                spacing: Style.spacing.md
                                Text {
                                    width: parent.width
                                    text: root.l10n("Confirm the local and NAS folders above are correct. Repair recreates only FN sync's marker, verifies it, then resumes automatic sync.", "请确认上方本地和 NAS 文件夹无误。修复操作只会重新创建飞牛同步标记，验证后恢复自动同步。")
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    wrapMode: Text.WordWrap
                                }
                                Button {
                                    width: parent.width
                                    text: root.l10n("Repair safety check and resume", "修复安全检查并恢复同步")
                                    leftAlign: true
                                    bordered: true
                                    focusable: true
                                    selected: enabled
                                    enabled: root.selectedTask !== null && !root.busy
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                    onClicked: root.requestConfirm(
                                        root.l10n("Continue only if both task folders shown above are correct. FN sync will recreate and verify its marker, then resume automatic sync. No other files are changed by this repair.", "仅当上方显示的任务两端文件夹正确时继续。飞牛将重新创建并验证同步标记，然后恢复自动同步。修复操作不会更改其他文件。"),
                                        ["task", "repair-access", String(root.selectedTask.id), "--resume"],
                                        root.l10n("Repair and resume", "修复并恢复"),
                                        false
                                    )
                                }
                            }
                        }

                        PanelSectionHeader {
                            visible: root.selectedTask !== null && !(root.selectedTask.mode === "two-way" && !root.selectedTask.initialized)
                            text: root.l10n("RUN SYNC", "运行同步")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Row {
                            visible: root.selectedTask !== null && !(root.selectedTask.mode === "two-way" && !root.selectedTask.initialized)
                            width: parent.width
                            spacing: Style.spacing.sm
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Check changes (read-only)", "检查更改（只读）")
                                bordered: true
                                focusable: true
                                enabled: !root.busy && !root.needsAccessRepair(root.selectedTask)
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.runAction(["task", "preview", String(root.selectedTask.id)], root.l10n("Check changes", "检查更改"), true, false)
                            }
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Sync now", "立即同步")
                                bordered: true
                                focusable: true
                                enabled: !root.busy && !root.needsAccessRepair(root.selectedTask)
                                selected: enabled
                                opacity: enabled ? 1.0 : 0.42
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.runAction(["task", "run", String(root.selectedTask.id)], root.l10n("Sync", "同步"), false, false)
                            }
                        }

                        PanelSectionHeader {
                            text: root.l10n("TROUBLESHOOTING", "故障排查")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Button {
                            width: parent.width
                            text: root.l10n("Test NAS connection", "测试 NAS 连接")
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: root.selectedTask !== null && !root.busy
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.runAction(["task", "test", String(root.selectedTask.id)], root.l10n("Connection test", "连接测试"), false, false)
                        }

                        Button {
                            width: parent.width
                            text: root.l10n("View technical log", "查看技术日志")
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: root.selectedTask !== null && !root.busy
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.runAction(["logs", String(root.selectedTask.id), "--lines", "50"], root.l10n("Load log", "加载日志"), true, false)
                        }

                        PanelSectionHeader {
                            text: root.l10n("TASK SETTINGS", "任务设置")
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                        }

                        Button {
                            width: parent.width
                            text: root.l10n("Remove task configuration", "移除任务配置")
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: root.selectedTask !== null && !root.busy
                            foreground: root.urgent
                            fontFamily: root.fontFamily
                            onClicked: root.requestConfirm(root.l10n("Remove this sync task? Local and NAS files will be kept.", "移除此同步任务？本地和 NAS 文件都会保留。"), ["task", "remove", String(root.selectedTask.id)], root.l10n("Remove task", "移除任务"), true)
                        }
                    }

                    Column {
                        visible: root.page === "add-task"
                        width: parent.width
                        spacing: Style.spacing.lg
                        PanelPageHeader {
                            width: parent.width
                            parentTitle: root.l10n("Tasks", "任务")
                            backAccessibleText: root.l10n("Back to Tasks", "返回任务")
                            title: root.l10n("Create sync task", "创建同步任务")
                            foreground: root.foreground
                            dimForeground: root.dimForeground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onBackRequested: root.showPrimary("tasks")
                        }
                        Text {
                            width: parent.width
                            text: root.l10n("The NAS authorization is reused. This task only defines the sync rule and two folders.", "此任务复用已有 NAS 授权，只定义同步规则和两端文件夹。")
                            color: root.dimForeground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                            wrapMode: Text.WordWrap
                        }
                        Dropdown {
                            id: taskConnectionDropdown
                            width: parent.width
                            label: root.l10n("NAS CONNECTION", "NAS 连接")
                            value: root.addConnectionId
                            options: root.connectionOptions()
                            foreground: root.foreground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onChanged: function (value) {
                                root.addConnectionId = value;
                                taskRemoteField.text = "";
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Text {
                                text: root.l10n("TASK NAME", "任务名称")
                                color: root.dimForeground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                                font.bold: true
                            }
                            TextField {
                                id: taskNameField
                                width: parent.width
                                placeholderText: root.l10n("Work documents", "工作文档")
                                foreground: root.foreground
                                accent: root.accent
                                enabled: !root.busy
                                onAccepted: taskRemoteField.forceActiveFocus()
                            }
                        }
                        Dropdown {
                            id: taskModeDropdown
                            width: parent.width
                            label: root.l10n("SYNC MODE", "同步模式")
                            value: root.addMode
                            options: [
                                {
                                    value: "two-way",
                                    label: root.l10n("Two-way sync", "双向同步")
                                },
                                {
                                    value: "download-only",
                                    label: root.l10n("Download only · source deletes are kept", "仅下载 · 保留源端删除项")
                                },
                                {
                                    value: "upload-only",
                                    label: root.l10n("Upload only · source deletes are kept", "仅上传 · 保留源端删除项")
                                }
                            ]
                            foreground: root.foreground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onChanged: function (value) {
                                root.addMode = value;
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Text {
                                text: root.l10n("NAS FOLDER", "NAS 文件夹")
                                color: root.dimForeground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                                font.bold: true
                            }
                            Row {
                                width: parent.width
                                spacing: Style.spacing.sm
                                TextField {
                                    id: taskRemoteField
                                    width: parent.width - browseNasButton.implicitWidth - parent.spacing
                                    placeholderText: root.l10n("Choose a folder on the NAS", "选择 NAS 上的文件夹")
                                    readOnly: true
                                    foreground: root.foreground
                                    accent: root.accent
                                    enabled: !root.busy
                                }
                                Button {
                                    id: browseNasButton
                                    text: root.l10n("Browse NAS…", "浏览 NAS…")
                                    bordered: true
                                    focusable: true
                                    enabled: !root.busy
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                    onClicked: root.showRemoteFolderPicker()
                                }
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Text {
                                text: root.l10n("LOCAL FOLDER", "本地文件夹")
                                color: root.dimForeground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                                font.bold: true
                            }
                            Row {
                                width: parent.width
                                spacing: Style.spacing.sm
                                TextField {
                                    id: taskLocalField
                                    width: parent.width - chooseLocalButton.implicitWidth - parent.spacing
                                    placeholderText: root.l10n("Choose an existing local folder", "选择已有的本地文件夹")
                                    readOnly: true
                                    foreground: root.foreground
                                    accent: root.accent
                                    enabled: !root.busy
                                }
                                Button {
                                    id: chooseLocalButton
                                    text: root.l10n("Choose folder…", "选择文件夹…")
                                    bordered: true
                                    focusable: true
                                    enabled: !root.busy
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                    onClicked: localFolderDialog.open()
                                }
                            }
                        }
                        Row {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Cancel", "取消")
                                bordered: true
                                focusable: true
                                enabled: !root.busy
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.showPrimary("tasks")
                            }
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.busy ? root.l10n("Creating…", "正在创建…") : root.l10n("Create task", "创建任务")
                                bordered: true
                                focusable: true
                                enabled: !root.busy
                                selected: enabled
                                opacity: enabled ? 1.0 : 0.42
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.submitTask()
                            }
                        }
                    }

                    Column {
                        visible: root.page === "remote-picker"
                        width: parent.width
                        spacing: Style.spacing.lg
                        PanelPageHeader {
                            width: parent.width
                            parentTitle: root.l10n("Task setup", "任务设置")
                            backAccessibleText: root.l10n("Back to task setup", "返回任务设置")
                            title: root.l10n("Choose NAS folder", "选择 NAS 文件夹")
                            foreground: root.foreground
                            dimForeground: root.dimForeground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onBackRequested: root.page = "add-task"
                        }
                        Text {
                            width: parent.width
                            text: root.browsePath === "" ? "NAS:/" : "NAS:/" + root.browsePath
                            color: root.accent
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.subtitle
                            font.bold: true
                            elide: Text.ElideMiddle
                        }
                        Text {
                            width: parent.width
                            text: root.l10n("Open folders to navigate. The NAS root itself cannot be selected.", "打开文件夹进行浏览。NAS 根目录不能直接选择。")
                            color: root.dimForeground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                            wrapMode: Text.WordWrap
                        }
                        Button {
                            visible: root.browsePath !== ""
                            width: parent.width
                            text: root.l10n("Up one folder", "返回上一级")
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: !root.busy
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.browseUp()
                        }
                        Repeater {
                            model: root.browseFolders
                            Button {
                                required property var modelData
                                width: content.width
                                text: String(modelData.name || "") + "  ›"
                                leftAlign: true
                                bordered: true
                                focusable: true
                                enabled: !root.busy
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.loadRemoteFolders(String(modelData.path || ""))
                            }
                        }
                        Row {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Cancel", "取消")
                                bordered: true
                                focusable: true
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.page = "add-task"
                            }
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Use this folder", "使用此文件夹")
                                bordered: true
                                focusable: true
                                enabled: root.browsePath !== "" && !root.busy
                                selected: enabled
                                opacity: enabled ? 1.0 : 0.42
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: {
                                    taskRemoteField.text = root.browsePath;
                                    root.page = "add-task";
                                    root.clearMessages();
                                }
                            }
                        }
                    }

                    Column {
                        visible: root.page === "connection-form"
                        width: parent.width
                        spacing: Style.spacing.lg
                        PanelPageHeader {
                            width: parent.width
                            parentTitle: root.l10n("NAS connections", "NAS 连接")
                            backAccessibleText: root.l10n("Back to NAS connections", "返回 NAS 连接")
                            title: root.editingConnectionId === "" ? root.l10n("Connect NAS", "连接 NAS") : root.l10n("Edit NAS authorization", "编辑 NAS 授权")
                            foreground: root.foreground
                            dimForeground: root.dimForeground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onBackRequested: root.showPrimary("nas")
                        }
                        Text {
                            width: parent.width
                            text: root.editingConnectionId === "" ? root.l10n("Nothing is saved until Test login & folders can sign in and read the NAS folder list. Tasks reuse this authorization later.", "只有“测试登录与文件夹”成功登录并读取 NAS 文件夹列表后才会保存；之后任务会复用此授权。") : root.l10n("Update the connection for every task at once. Leave password blank to keep the current authorization.", "一次更新所有任务使用的连接；密码留空可保持当前授权。")
                            color: root.dimForeground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                            wrapMode: Text.WordWrap
                        }
                        Button {
                            width: parent.width
                            text: root.connectionDiscovering ? root.l10n("Scanning local network…", "正在扫描局域网…") : root.l10n("Scan local fnOS NAS", "扫描本地 fnOS NAS")
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: !root.connectionDiscovering && !root.connectionFormBusy
                            selected: root.connectionDiscovering
                            opacity: enabled ? 1.0 : 0.55
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.discoverNas(true, true)
                        }
                        Column {
                            visible: root.discoveredDevices.length > 0
                            width: parent.width
                            spacing: Style.spacing.sm
                            Repeater {
                                model: root.discoveredDevices
                                Button {
                                    required property var modelData
                                    width: parent.width
                                    text: root.discoveredDeviceLabel(modelData)
                                    leftAlign: true
                                    bordered: true
                                    focusable: true
                                    selected: String(modelData.url || "") !== "" && connectionUrlField.text.trim() === String(modelData.url || "")
                                    foreground: String(modelData.url || "") !== "" ? root.foreground : root.urgent
                                    fontFamily: root.fontFamily
                                    onClicked: {
                                        if (String(modelData.url || "") !== "")
                                            root.applyDiscoveredDevice(modelData);
                                        else
                                            root.openDiscoveredNas(modelData);
                                    }
                                }
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Text {
                                text: root.l10n("CONNECTION NAME", "连接名称")
                                color: root.dimForeground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                                font.bold: true
                            }
                            TextField {
                                id: connectionNameField
                                width: parent.width
                                placeholderText: root.l10n("Home NAS", "家庭 NAS")
                                foreground: root.foreground
                                accent: root.accent
                                enabled: !root.connectionFormBusy
                                onTextChanged: root.invalidateConnectionTest()
                                onAccepted: connectionUrlField.forceActiveFocus()
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Text {
                                text: "WEBDAV URL"
                                color: root.dimForeground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.caption
                                font.bold: true
                            }
                            TextField {
                                id: connectionUrlField
                                width: parent.width
                                placeholderText: "https://nas.local:5006/"
                                foreground: root.foreground
                                accent: root.accent
                                enabled: !root.connectionFormBusy
                                onTextChanged: root.invalidateConnectionTest()
                                onAccepted: connectionUserField.forceActiveFocus()
                            }
                        }
                        Row {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Column {
                                width: (parent.width - parent.spacing) / 2
                                spacing: Style.spacing.sm
                                Text {
                                    text: root.l10n("USERNAME", "用户名")
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    font.bold: true
                                }
                                TextField {
                                    id: connectionUserField
                                    width: parent.width
                                    placeholderText: root.l10n("fnOS user", "fnOS 用户")
                                    foreground: root.foreground
                                    accent: root.accent
                                    enabled: !root.connectionFormBusy
                                    onTextChanged: root.invalidateConnectionTest()
                                    onAccepted: connectionPasswordField.forceActiveFocus()
                                }
                            }
                            Column {
                                width: (parent.width - parent.spacing) / 2
                                spacing: Style.spacing.sm
                                Text {
                                    text: root.editingConnectionId === "" ? root.l10n("PASSWORD", "密码") : root.l10n("NEW PASSWORD", "新密码")
                                    color: root.dimForeground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                    font.bold: true
                                }
                                TextField {
                                    id: connectionPasswordField
                                    width: parent.width
                                    password: true
                                    placeholderText: root.editingConnectionId === "" ? root.l10n("Stored securely", "安全保存") : root.l10n("Leave unchanged", "留空保持不变")
                                    foreground: root.foreground
                                    accent: root.accent
                                    enabled: !root.connectionFormBusy
                                    onTextChanged: root.invalidateConnectionTest()
                                    onAccepted: if (root.editingConnectionId === "")
                                        root.testConnectionForm()
                                    else
                                        root.submitConnection()
                                }
                            }
                        }
                        Toggle {
                            width: parent.width
                            label: root.l10n("Allow plain HTTP", "允许明文 HTTP")
                            description: root.l10n("Only use on a trusted LAN. HTTPS is recommended.", "仅限受信任局域网使用，建议使用 HTTPS。")
                            checked: root.connectionAllowHttp
                            enabled: !root.connectionFormBusy
                            foreground: root.foreground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onClicked: {
                                root.connectionAllowHttp = !root.connectionAllowHttp;
                                root.invalidateConnectionTest();
                            }
                        }
                        Toggle {
                            width: parent.width
                            label: root.l10n("Trust a self-signed certificate", "信任自签名证书")
                            description: root.l10n("Disables TLS certificate validation for this NAS.", "为此 NAS 禁用 TLS 证书验证。")
                            checked: root.connectionInsecureTls
                            enabled: !root.connectionFormBusy
                            foreground: root.foreground
                            accent: root.accent
                            fontFamily: root.fontFamily
                            onClicked: {
                                root.connectionInsecureTls = !root.connectionInsecureTls;
                                root.invalidateConnectionTest();
                            }
                        }
                        Button {
                            visible: root.editingConnectionId === ""
                            width: parent.width
                            text: root.connectionVerifying ? root.l10n("Testing login and folders…", "正在测试登录与文件夹…") : (root.verifiedConnectionFingerprint === root.connectionFingerprint() ? root.l10n("Test passed", "测试已通过") : root.l10n("Test login & folders", "测试登录与文件夹"))
                            leftAlign: true
                            bordered: true
                            focusable: true
                            enabled: !root.connectionFormBusy && root.connectionFieldsComplete && root.verifiedConnectionFingerprint !== root.connectionFingerprint()
                            foreground: root.verifiedConnectionFingerprint === root.connectionFingerprint() ? root.accent : root.foreground
                            fontFamily: root.fontFamily
                            onClicked: root.testConnectionForm()
                        }
                        Row {
                            width: parent.width
                            spacing: Style.spacing.sm
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.l10n("Cancel", "取消")
                                bordered: true
                                focusable: true
                                enabled: !root.connectionFormBusy
                                foreground: root.foreground
                                fontFamily: root.fontFamily
                                onClicked: root.showPrimary("nas")
                            }
                            Button {
                                width: (parent.width - parent.spacing) / 2
                                text: root.connectionSaving ? root.l10n("Saving…", "正在保存…") : (root.editingConnectionId === "" ? root.l10n("Save authorization", "保存授权") : root.l10n("Save connection", "保存连接"))
                                bordered: true
                                focusable: true
                                enabled: root.connectionSaveReady
                                selected: root.connectionSaveReady
                                foreground: root.connectionSaveReady ? root.foreground : root.dimForeground
                                fontFamily: root.fontFamily
                                onClicked: root.submitConnection()
                            }
                        }
                    }

                    BorderSurface {
                        visible: root.actionStatus !== "" || root.actionError !== "" || root.actionOutput !== "" || root.statusError !== ""
                        width: parent.width
                        implicitHeight: messageColumn.implicitHeight + Style.spacing.xl * 2
                        color: root.actionError !== "" || root.statusError !== "" ? Util.alpha(root.urgent, 0.10) : Style.normalFillFor(root.foreground, root.accent, root.urgent)
                        borderSpec: Border.flat(root.actionError !== "" || root.statusError !== "" ? root.urgent : root.accent, Style.normalBorderWidth)
                        radius: Style.cornerRadius
                        Column {
                            id: messageColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: Style.spacing.rowPaddingX
                            anchors.rightMargin: Style.spacing.rowPaddingX
                            spacing: Style.spacing.sm
                            Text {
                                visible: root.actionStatus !== ""
                                width: parent.width
                                text: root.actionStatus
                                color: root.foreground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.bodySmall
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                visible: root.actionError !== "" || root.statusError !== ""
                                width: parent.width
                                text: root.actionError !== "" ? root.actionError : root.statusError
                                color: root.urgent
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.bodySmall
                                wrapMode: Text.WordWrap
                            }
                            Text {
                                visible: root.actionOutput !== ""
                                width: parent.width
                                text: root.actionOutput
                                color: root.dimForeground
                                font.family: "monospace"
                                font.pixelSize: Style.font.caption
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }
            }

            ConfirmDialog {
                id: confirmDialog
                anchors.fill: parent
                z: 20
                message: root.pendingConfirmMessage
                cancelText: root.l10n("Cancel", "取消")
                confirmText: root.pendingConfirmArgs.length > 1 && root.pendingConfirmArgs[1] === "remove"
                    ? root.l10n("Remove", "移除")
                    : root.pendingConfirmArgs.length > 1 && root.pendingConfirmArgs[1] === "initialize"
                        ? root.l10n("Start", "开始")
                        : root.l10n("Confirm", "确认")
                background: Color.popups.background
                foreground: root.foreground
                selectedText: root.accent
                fontFamily: root.fontFamily
                cornerRadius: Style.cornerRadius
                Keys.onPressed: function (event) {
                    if (confirmDialog.handleKey(event))
                        event.accepted = true;
                }
                focus: opened
                onOpenedChanged: if (opened)
                    forceActiveFocus()
                onCanceled: {
                    confirmDialog.opened = false;
                    root.pendingConfirmArgs = [];
                    root.pendingConfirmLabel = "";
                    root.pendingConfirmMessage = "";
                    keyCatcher.forceActiveFocus();
                }
                onConfirmed: {
                    confirmDialog.opened = false;
                    root.runAction(root.pendingConfirmArgs, root.pendingConfirmLabel, false, root.pendingConfirmBack);
                    root.pendingConfirmArgs = [];
                    root.pendingConfirmLabel = "";
                    root.pendingConfirmMessage = "";
                    keyCatcher.forceActiveFocus();
                }
            }
        }
    }
}
