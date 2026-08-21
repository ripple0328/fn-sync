import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
    id: root
    moduleName: "community.fnos-sync"

    property bool installed: false
    property var tasks: []
    property var connections: []
    property string statusError: ""
    property bool syncing: false

    readonly property string controlPath: root.localPath(Qt.resolvedUrl("scripts/fn-syncctl"))
    readonly property int refreshIntervalSec: Math.max(10, Number(settings && settings.refreshIntervalSec || 30))
    readonly property string languagePreference: String(settings && settings.language || "system")
    readonly property string systemLocale: String(Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANGUAGE") || Quickshell.env("LANG") || "en")
    readonly property string language: languagePreference === "en" || languagePreference === "zh" ? languagePreference : (/^zh([_.-]|$)/i.test(systemLocale) ? "zh" : "en")
    readonly property int errorCount: countState("error")
    readonly property int runningCount: countState("running")
    readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
    readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

    function l10n(english, chinese) {
        return language === "zh" ? chinese : english;
    }

    function saveLanguage(value) {
        var next = {};
        for (var key in settings)
            next[key] = settings[key];
        next.language = value === "en" || value === "zh" ? value : "system";
        root.settings = next;
        if (bar && bar.shell && typeof bar.shell.updateEntryInline === "function")
            bar.shell.updateEntryInline(root.moduleName, next);
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

    function countState(state) {
        var count = 0;
        for (var i = 0; i < tasks.length; i++) {
            if (tasks[i] && tasks[i].status && tasks[i].status.state === state)
                count++;
        }
        return count;
    }

    function injectPanel() {
        var target = panelLoader.item;
        if (!target)
            return;
        if ("bar" in target)
            target.bar = root.bar;
        if ("settings" in target)
            target.settings = root.settings;
        if ("anchorItem" in target)
            target.anchorItem = widgetButton;
        if ("hostWidget" in target)
            target.hostWidget = root;
        if ("controlPath" in target)
            target.controlPath = root.controlPath;
        if ("language" in target)
            target.language = root.language;
        if ("languagePreference" in target)
            target.languagePreference = root.languagePreference;
        target.installed = root.installed;
        target.tasks = root.tasks;
        target.connections = root.connections;
        target.statusError = root.statusError;
        target.syncing = root.syncing;
    }

    function applyStatus(raw) {
        try {
            var payload = JSON.parse(String(raw || "{}"));
            installed = payload.installed === true;
            tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
            connections = Array.isArray(payload.connections) ? payload.connections : [];
            statusError = String(payload.error || "");
        } catch (error) {
            installed = false;
            tasks = [];
            connections = [];
            statusError = l10n("Could not read FN sync status", "无法读取飞牛状态");
        }
        injectPanel();
    }

    function refreshStatus() {
        if (!statusProcess.running)
            statusProcess.running = true;
    }

    function syncNow() {
        if (!installed || syncProcess.running)
            return;
        syncing = true;
        injectPanel();
        syncProcess.running = true;
    }

    function openClient() {
        Quickshell.execDetached([controlPath, "open", languagePreference]);
    }

    function open() {
        if (panelLoader.item)
            panelLoader.item.open();
    }
    function close() {
        if (panelLoader.item)
            panelLoader.item.close();
    }
    function togglePanel() {
        if (panelLoader.item)
            panelLoader.item.toggle();
    }
    function closeForPopoutSwitch() {
        if (panelLoader.item)
            panelLoader.item.closeForPopoutSwitch();
    }

    function showPage(page) {
        if (!panelLoader.item)
            return;
        panelLoader.item.showPrimary(page);
        panelLoader.item.open();
    }

    function showConnectNas() {
        if (!panelLoader.item)
            return;
        panelLoader.item.showConnectionForm(null);
        panelLoader.item.open();
    }

    implicitWidth: widgetButton.implicitWidth
    implicitHeight: widgetButton.implicitHeight
    onBarChanged: injectPanel()
    onSettingsChanged: injectPanel()

    Loader {
        id: panelLoader
        active: true
        source: Qt.resolvedUrl("Panel.qml")
        visible: false
        onLoaded: {
            root.injectPanel();
            Qt.callLater(root.injectPanel);
        }
    }

    Process {
        id: statusProcess
        command: [root.controlPath, "status", root.languagePreference]
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: root.applyStatus(text)
        }
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: {
                var value = String(text || "").trim();
                if (value !== "")
                    root.statusError = value;
            }
        }
        onExited: function (exitCode) {
            if (exitCode !== 0 && root.statusError === "")
                root.statusError = root.l10n("FN sync is unavailable", "飞牛不可用");
            root.injectPanel();
        }
    }

    Process {
        id: syncProcess
        command: [root.controlPath, "sync", root.languagePreference]
        stderr: StdioCollector {
            waitForEnd: true
            onStreamFinished: {
                var value = String(text || "").trim();
                if (value !== "")
                    root.statusError = value;
            }
        }
        onExited: function (exitCode) {
            root.syncing = false;
            if (exitCode === 0)
                root.statusError = "";
            root.refreshStatus();
            root.injectPanel();
        }
    }

    Timer {
        interval: root.refreshIntervalSec * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refreshStatus()
    }

    IpcHandler {
        target: "community.fnos-sync"
        function refresh(): void {
            root.broadcast("refreshStatus");
        }
        function sync(): void {
            root.syncNow();
        }
        function open(): void {
            root.open();
        }
        function close(): void {
            root.close();
        }
        function show(): void {
            root.open();
        }
        function hide(): void {
            root.close();
        }
        function tasks(): void {
            root.showPage("tasks");
        }
        function task(taskId: string): void {
            root.open();
            Qt.callLater(function () {
                if (panelLoader.item)
                    panelLoader.item.showTask(panelLoader.item.taskById(taskId));
            });
        }
        function nas(): void {
            root.showPage("nas");
        }
        function settings(): void {
            root.showPage("settings");
        }
        function connectNas(): void {
            root.showConnectNas();
        }
    }

    WidgetButton {
        id: widgetButton
        anchors.fill: parent
        bar: root.bar
        text: ""
        labelVisible: false
        hasVisualContent: true
        fixedWidth: vertical ? -1 : Style.bar.iconSlot
        useActiveColor: false
        tooltipText: !root.installed
            ? root.l10n("FN sync is not installed", "尚未安装飞牛")
            : root.errorCount > 0
                ? root.l10n(root.errorCount + " sync task(s) need attention", root.errorCount + " 个同步任务需要处理")
                : root.syncing || root.runningCount > 0
                    ? root.l10n("FN sync is syncing\nLeft click for details", "飞牛正在同步\n左键查看详情")
                    : root.l10n(root.tasks.length + " FN sync task(s)\nLeft click for details · Right click to sync", "飞牛 · " + root.tasks.length + " 个同步任务\n左键查看详情 · 右键立即同步")
        onPressed: function (buttonCode) {
            if (buttonCode === Qt.RightButton)
                root.syncNow();
            else if (buttonCode === Qt.MiddleButton)
                root.openClient();
            else
                root.togglePanel();
        }

        BorderSurface {
            anchors.centerIn: parent
            width: Style.bar.statusSlot
            height: Style.bar.statusSlot
            radius: Style.cornerRadius
            color: root.errorCount > 0
                ? Util.alpha(root.bar ? root.bar.urgent : Color.urgent, 0.18)
                : root.syncing || root.runningCount > 0
                    ? Util.alpha(Color.accent, 0.22)
                    : "transparent"
            borderSpec: root.errorCount > 0
                ? Border.flat(root.bar ? root.bar.urgent : Color.urgent, Style.normalBorderWidth)
                : root.syncing || root.runningCount > 0
                    ? Border.flat(Color.accent, Style.focusBorderWidth)
                    : Border.none()

            FnSyncIcon {
                anchors.centerIn: parent
                iconSize: Style.bar.iconFont
                color: root.errorCount > 0
                    ? (root.bar ? root.bar.urgent : Color.urgent)
                    : widgetButton.foreground
            }
        }
    }
}
