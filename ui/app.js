#!/usr/bin/gjs -m

import Gio from "gi://Gio";
import Gdk from "gi://Gdk?version=4.0";
import GLib from "gi://GLib";
import Gtk from "gi://Gtk?version=4.0";

const APP_ID = "dev.fnnas.FnSync";
const controller = GLib.getenv("FNSYNC_CONTROLLER");
const commandPrefix = controller ? ["python3", controller] : ["fn-sync"];

function resolveLanguage() {
  const override = String(GLib.getenv("FNSYNC_LANGUAGE") || "system").toLowerCase();
  if (override === "en" || override === "zh") return override;
  const locales = GLib.get_language_names().map(value => String(value).toLowerCase());
  return locales.some(value => value === "zh" || value.startsWith("zh_") || value.startsWith("zh-")) ? "zh" : "en";
}

const language = resolveLanguage();
const t = (english, chinese) => language === "zh" ? chinese : english;

function runController(args, input, callback) {
  const flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE | Gio.SubprocessFlags.STDIN_PIPE;
  let process;
  try {
    process = Gio.Subprocess.new(commandPrefix.concat(args), flags);
  } catch (error) {
    callback(127, "", String(error));
    return;
  }
  process.communicate_utf8_async(input || null, null, (source, result) => {
    try {
      const [, stdout, stderr] = source.communicate_utf8_finish(result);
      callback(source.get_exit_status(), stdout || "", stderr || "");
    } catch (error) {
      callback(1, "", String(error));
    }
  });
}

function label(text, cssClass) {
  const widget = new Gtk.Label({label: text, xalign: 0, wrap: true});
  if (cssClass) widget.add_css_class(cssClass);
  return widget;
}

function button(text, callback, suggested = false) {
  const widget = new Gtk.Button({label: text});
  if (suggested) widget.add_css_class("suggested-action");
  widget.connect("clicked", callback);
  return widget;
}

class FnSyncWindow {
  constructor(app) {
    this.app = app;
    this.window = new Gtk.ApplicationWindow({
      application: app,
      title: t("FN sync", "飞牛"),
      default_width: 920,
      default_height: 650,
    });

    const header = new Gtk.HeaderBar();
    const titleBox = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL});
    titleBox.append(label(t("FN sync", "飞牛"), "title"));
    titleBox.append(label("fnOS · Omarchy", "dim-label"));
    header.set_title_widget(titleBox);
    header.pack_start(button(t("Refresh", "刷新"), () => this.refresh()));
    this.connectionButton = button(t("Connect NAS", "连接 NAS"), () => this.openConnectionManager());
    this.addTaskButton = button(t("Add sync task", "添加同步任务"), () => this.openAddDialog(), true);
    header.pack_end(this.connectionButton);
    header.pack_end(this.addTaskButton);
    this.window.set_titlebar(header);

    this.root = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 14});
    this.root.set_margin_top(18);
    this.root.set_margin_bottom(18);
    this.root.set_margin_start(22);
    this.root.set_margin_end(22);

    const intro = label(
      t(
        "Connect and authorize an fnOS NAS once, then reuse it for multiple sync tasks. A read-only safety check guides the first two-way sync.",
        "先连接并授权 fnOS NAS，再复用同一授权创建多个同步任务。双向任务首次同步前会进行只读安全检查。",
      ),
      "dim-label",
    );
    this.root.append(intro);

    this.banner = label("");
    this.banner.set_visible(false);
    this.banner.add_css_class("banner");
    this.root.append(this.banner);

    const scroll = new Gtk.ScrolledWindow({hexpand: true, vexpand: true});
    this.list = new Gtk.ListBox({selection_mode: Gtk.SelectionMode.NONE});
    this.list.add_css_class("boxed-list");
    scroll.set_child(this.list);
    this.root.append(scroll);
    this.window.set_child(this.root);
    this.refresh();
  }

  showMessage(message, error = false) {
    this.banner.set_label(message);
    this.banner.set_visible(message !== "");
    if (error) this.banner.add_css_class("error");
    else this.banner.remove_css_class("error");
  }

  clearList() {
    let child = this.list.get_first_child();
    while (child) {
      const next = child.get_next_sibling();
      this.list.remove(child);
      child = next;
    }
  }

  refresh() {
    this.showMessage("");
    runController(["connection", "list", "--json"], null, (connectionCode, connectionOut, connectionErr) => {
      if (connectionCode !== 0) {
        this.showMessage((connectionErr || connectionOut || t("Could not read NAS connections", "无法读取 NAS 连接")).trim(), true);
        return;
      }
      try {
        this.connections = JSON.parse(connectionOut || "[]");
        const count = this.connections.length;
        this.connectionButton.set_label(count ? t(`NAS connections (${count})`, `NAS 连接（${count}）`) : t("Connect NAS", "连接 NAS"));
        this.addTaskButton.set_sensitive(count > 0);
      } catch (error) {
        this.showMessage(t("The NAS connection status is invalid", "NAS 连接状态格式无效"), true);
        return;
      }
      runController(["status", "--json"], null, (code, stdout, stderr) => {
      if (code !== 0) {
        this.showMessage((stderr || stdout || t("Could not read sync status", "无法读取同步状态")).trim(), true);
        return;
      }
      let tasks;
      try {
        tasks = JSON.parse(stdout || "[]");
      } catch (error) {
        this.showMessage(t("The sync status is invalid", "同步状态格式无效"), true);
        return;
      }
      this.renderTasks(tasks);
      });
    });
  }

  renderTasks(tasks) {
    this.clearList();
    if (!tasks.length) {
      const empty = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 10, valign: Gtk.Align.CENTER});
      empty.set_margin_top(80);
      empty.append(label(t("No sync tasks yet", "还没有同步任务"), "title"));
      empty.append(label(this.connections?.length ? t("Your NAS authorization is ready. Choose Add sync task and select both folders.", "NAS 授权已就绪。请选择“添加同步任务”，然后选择两端文件夹。") : t("Enable WebDAV in fnOS, then connect and authorize your NAS.", "请先在 fnOS 启用 WebDAV，然后连接并授权 NAS。"), "dim-label"));
      this.list.append(empty);
      return;
    }
    for (const task of tasks) this.list.append(this.taskRow(task));
  }

  taskRow(task) {
    const row = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 9});
    row.set_margin_top(14);
    row.set_margin_bottom(14);
    row.set_margin_start(16);
    row.set_margin_end(16);

    const top = new Gtk.Box({spacing: 10});
    const title = label(task.name || task.id, "title");
    title.set_hexpand(true);
    top.append(title);
    const state = task.status?.state || "never";
    const needsAccessRepair = task.status?.error_code === "access-marker" || task.safety_issue?.code === "access-marker";
    const recordedCheckWinner = String(task.first_sync_check?.conflict_winner || "");
    const uninitializedTwoWay = task.mode === "two-way" && !task.initialized;
    const firstSyncState = uninitializedTwoWay && task.status?.action === "initial-preview";
    const stateText = needsAccessRepair
      ? t("Safety check paused", "安全检查已暂停")
      : uninitializedTwoWay && recordedCheckWinner && state !== "error"
      ? t("Ready for first sync", "首次同步已就绪")
      : firstSyncState
      ? {
        ok: recordedCheckWinner ? t("Ready for first sync", "首次同步已就绪") : t("Check needed", "需要重新检查"),
        running: t("Checking first sync", "正在检查首次同步"),
        error: t("First-sync check failed", "首次同步检查失败"),
        cancelled: t("First-sync check stopped", "首次同步检查已停止"),
      }[state] || state
      : {
        ok: t("Up to date", "正常"),
        running: t("Syncing", "同步中"),
        error: t("Error", "错误"),
        never: t("Not run yet", "未运行"),
      }[state] || state;
    const badge = label(stateText, "badge");
    if (state === "error") badge.add_css_class("error");
    top.append(badge);
    row.append(top);

    const modeText = {
      "two-way": t("Two-way sync", "双向同步"),
      "upload-only": t("Upload only", "仅上传"),
      "download-only": t("Download only", "仅下载"),
    }[task.mode] || task.mode;
    row.append(label(`${task.connection_name || "fnOS NAS"}  ·  ${modeText}\n${task.local_path}  ↔  NAS:/${task.remote_path}`, "dim-label"));
    const message = needsAccessRepair
      ? t("Automatic sync is paused. Confirm both task folders, then repair the safety check.", "自动同步已暂停。请确认任务两端文件夹无误，然后修复安全检查。")
      : uninitializedTwoWay && recordedCheckWinner && state !== "error" || firstSyncState && state === "ok" ? "" : String(task.status?.message || "").trim();
    if (message) row.append(label(message, needsAccessRepair || state === "error" ? "error-text" : "dim-label"));

    if (task.mode === "two-way" && !task.initialized) {
      const firstSync = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 8});
      firstSync.append(label(t("First sync", "首次同步"), "title"));
      firstSync.append(label(
        t(
          "Choose what to keep only when the same file differs on both sides. Files found on only one side are copied to the other.",
          "请选择同一文件在两端不同时要保留哪一份。只存在于一端的文件会复制到另一端。",
        ),
        "dim-label",
      ));
      const choices = new Gtk.Box({spacing: 8});
      const localChoice = new Gtk.CheckButton({label: t("Keep this computer's copy", "保留此电脑副本")});
      const nasChoice = new Gtk.CheckButton({label: t("Keep the NAS copy", "保留 NAS 副本"), group: localChoice});
      const recordedWinner = recordedCheckWinner;
      if (recordedWinner === "nas") nasChoice.set_active(true);
      else localChoice.set_active(true);
      choices.append(localChoice);
      choices.append(nasChoice);
      firstSync.append(choices);
      const selectedWinner = () => nasChoice.get_active() ? "nas" : "local";
      const checkReady = () => recordedWinner !== "" && recordedWinner === selectedWinner();
      const plannedChanges = Number(task.first_sync_check?.planned_changes || task.status?.planned_changes || 0);
      const summary = recordedWinner
        ? t(`${plannedChanges} actions found. No files changed.`, `发现 ${plannedChanges} 项操作。未修改任何文件。`)
        : task.status?.action === "initial-preview" && task.status?.state === "ok"
          ? t("Run the safety check once more so FN sync can record the conflict rule.", "请再运行一次安全检查，让飞牛记录冲突规则。")
          : t("The safety check is read-only and can take several minutes for large folders.", "安全检查为只读操作；大型文件夹可能需要几分钟。");
      firstSync.append(label(summary, "dim-label"));
      const primary = button("", () => {
        const winner = selectedWinner();
        if (checkReady()) this.confirmInitialize(task, winner);
        else this.runTaskAction(task, "preview", true, ["--winner", winner]);
      }, true);
      const updatePrimary = () => primary.set_label(checkReady() ? t("Start first sync", "开始首次同步") : t("Check first sync", "检查首次同步"));
      localChoice.connect("toggled", updatePrimary);
      nasChoice.connect("toggled", updatePrimary);
      updatePrimary();
      firstSync.append(primary);
      firstSync.append(label(t("Starting the first sync also turns on automatic background sync.", "开始首次同步后，也会自动开启后台同步。"), "dim-label"));
      row.append(firstSync);
      const troubleshooting = new Gtk.Box({spacing: 8});
      troubleshooting.append(button(t("Test NAS connection", "测试 NAS 连接"), () => this.runTaskAction(task, "test")));
      row.append(troubleshooting);
    } else {
      if (needsAccessRepair) {
        const repair = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 8});
        repair.append(label(t("Safety check paused this task", "安全检查已暂停此任务"), "title"));
        repair.append(label(
          t(
            "Confirm the local and NAS folders above are correct. Repair recreates only FN sync's marker, verifies it, then resumes automatic sync.",
            "请确认上方本地和 NAS 文件夹无误。修复操作只会重新创建飞牛同步标记，验证后恢复自动同步。",
          ),
          "dim-label",
        ));
        repair.append(button(
          t("Repair safety check and resume", "修复安全检查并恢复同步"),
          () => this.confirmRepair(task),
          true,
        ));
        row.append(repair);
      }
      const actions = new Gtk.Box({spacing: 8});
      actions.append(button(t("Test connection", "测试连接"), () => this.runTaskAction(task, "test")));
      const preview = button(t("Check changes (read-only)", "检查更改（只读）"), () => this.runTaskAction(task, "preview"));
      preview.set_sensitive(!needsAccessRepair);
      actions.append(preview);
      const syncNow = button(t("Sync now", "立即同步"), () => this.runTaskAction(task, "run"), true);
      syncNow.set_sensitive(!needsAccessRepair);
      actions.append(syncNow);
      const toggle = new Gtk.Switch({active: task.enabled === true, valign: Gtk.Align.CENTER});
      toggle.set_sensitive(!needsAccessRepair);
      toggle.set_tooltip_text(needsAccessRepair
        ? t("Repair the safety check before resuming", "请先修复安全检查再恢复同步")
        : task.enabled ? t("Pause background sync", "暂停后台同步") : t("Enable background sync", "启用后台同步"));
      toggle.connect("state-set", (_widget, enabled) => {
        this.runTaskAction(task, enabled ? "enable" : "disable", false);
        return false;
      });
      actions.append(toggle);
      row.append(actions);
    }
    return row;
  }

  runTaskAction(task, action, refreshAfter = true, extra = []) {
    this.showMessage(t(`${task.name}: working…`, `${task.name}：正在执行…`));
    runController(["task", action, task.id].concat(extra), null, (code, stdout, stderr) => {
      const output = (stderr || stdout || "").trim();
      this.showMessage(code === 0 ? t(`${task.name}: complete`, `${task.name}：完成`) : t(`${task.name}: ${output || "Operation failed"}`, `${task.name}：${output || "操作失败"}`), code !== 0);
      if (refreshAfter || action === "enable" || action === "disable") GLib.timeout_add(GLib.PRIORITY_DEFAULT, 400, () => {
        this.refresh();
        return GLib.SOURCE_REMOVE;
      });
    });
  }

  confirmInitialize(task, winner) {
    const dialog = new Gtk.MessageDialog({
      transient_for: this.window,
      modal: true,
      message_type: Gtk.MessageType.WARNING,
      text: t("Start the first sync?", "开始首次同步吗？"),
      secondary_text: t(
        winner === "nas"
          ? "Files found on only one side will be copied to the other. If the same file differs, the NAS copy will be kept. Automatic sync will turn on afterward."
          : "Files found on only one side will be copied to the other. If the same file differs, this computer's copy will be kept. Automatic sync will turn on afterward.",
        winner === "nas"
          ? "只存在于一端的文件会复制到另一端。如果同一文件在两端不同，将保留 NAS 副本。之后会自动开启后台同步。"
          : "只存在于一端的文件会复制到另一端。如果同一文件在两端不同，将保留此电脑副本。之后会自动开启后台同步。",
      ),
    });
    dialog.add_button(t("Cancel", "取消"), Gtk.ResponseType.CANCEL);
    dialog.add_button(t("Start first sync", "开始首次同步"), Gtk.ResponseType.OK);
    dialog.connect("response", (_source, response) => {
      dialog.destroy();
      if (response === Gtk.ResponseType.OK)
        this.runTaskAction(task, "initialize", true, ["--winner", winner, "--apply"]);
    });
    dialog.present();
  }

  confirmRepair(task) {
    const dialog = new Gtk.MessageDialog({
      transient_for: this.window,
      modal: true,
      message_type: Gtk.MessageType.WARNING,
      text: t("Repair this task's safety check?", "修复此任务的安全检查吗？"),
      secondary_text: t(
        "Continue only if the local and NAS folders shown for this task are correct. FN sync will recreate its marker, verify both sides, and resume automatic sync. No other files are changed by the repair.",
        "仅当此任务显示的本地和 NAS 文件夹正确时继续。飞牛将重新创建同步标记、验证两端并恢复自动同步。修复操作不会更改其他文件。",
      ),
    });
    dialog.add_button(t("Cancel", "取消"), Gtk.ResponseType.CANCEL);
    dialog.add_button(t("Repair and resume", "修复并恢复"), Gtk.ResponseType.OK);
    dialog.connect("response", (_source, response) => {
      dialog.destroy();
      if (response === Gtk.ResponseType.OK)
        this.runTaskAction(task, "repair-access", true, ["--resume"]);
    });
    dialog.present();
  }

  openLocalFolderChooser(parent, callback) {
    const chooser = new Gtk.FileChooserNative({
      title: t("Choose a local sync folder", "选择本地同步文件夹"),
      transient_for: parent,
      modal: true,
      action: Gtk.FileChooserAction.SELECT_FOLDER,
      accept_label: t("Use this folder", "使用此文件夹"),
      cancel_label: t("Cancel", "取消"),
    });
    chooser.connect("response", (_source, response) => {
      if (response === Gtk.ResponseType.ACCEPT) {
        const path = chooser.get_file()?.get_path();
        if (path) callback(path);
      }
      chooser.destroy();
    });
    chooser.show();
  }

  openRemoteFolderChooser(connection, parent, callback) {
    const dialog = new Gtk.Window({
      title: t(`Choose a folder on ${connection.name}`, `选择 ${connection.name} 上的文件夹`),
      transient_for: parent,
      modal: true,
      default_width: 560,
      default_height: 520,
    });
    const box = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 10});
    box.set_margin_top(18); box.set_margin_bottom(18); box.set_margin_start(20); box.set_margin_end(20);
    const pathLabel = label("NAS:/", "title");
    box.append(pathLabel);
    box.append(label(t("Open folders to navigate. The NAS root itself cannot be used as a sync task.", "打开文件夹进行浏览。NAS 根目录不能直接用作同步任务。"), "dim-label"));
    const message = label("");
    box.append(message);
    const scroll = new Gtk.ScrolledWindow({hexpand: true, vexpand: true});
    const folderList = new Gtk.ListBox({selection_mode: Gtk.SelectionMode.NONE});
    folderList.add_css_class("boxed-list");
    scroll.set_child(folderList);
    box.append(scroll);
    const actions = new Gtk.Box({spacing: 8, halign: Gtk.Align.END});
    const up = button(t("Up", "上一级"), () => {
      const parts = currentPath.split("/").filter(Boolean);
      parts.pop();
      load(parts.join("/"));
    });
    const cancel = button(t("Cancel", "取消"), () => dialog.destroy());
    const choose = button(t("Use this folder", "使用此文件夹"), () => {
      callback(currentPath);
      dialog.destroy();
    }, true);
    choose.set_sensitive(false);
    actions.append(up);
    actions.append(cancel);
    actions.append(choose);
    box.append(actions);
    dialog.set_child(box);

    let currentPath = "";
    const clearFolders = () => {
      let child = folderList.get_first_child();
      while (child) {
        const next = child.get_next_sibling();
        folderList.remove(child);
        child = next;
      }
    };
    const load = path => {
      currentPath = path;
      pathLabel.set_label(path ? `NAS:/${path}` : "NAS:/");
      up.set_sensitive(path !== "");
      choose.set_sensitive(path !== "");
      message.set_label(t("Loading folders…", "正在加载文件夹…"));
      clearFolders();
      runController(["connection", "folders", connection.id, "--path", path, "--json"], null, (code, stdout, stderr) => {
        if (code !== 0) {
          message.set_label((stderr || stdout || t("Could not browse this NAS", "无法浏览此 NAS")).trim());
          message.add_css_class("error-text");
          return;
        }
        let payload;
        try {
          payload = JSON.parse(stdout || "{}");
        } catch (error) {
          message.set_label(t("The NAS returned an invalid folder list", "NAS 返回了无效的文件夹列表"));
          message.add_css_class("error-text");
          return;
        }
        message.remove_css_class("error-text");
        const folders = Array.isArray(payload.folders) ? payload.folders : [];
        message.set_label(folders.length ? t("Choose a folder or open it to browse deeper.", "请选择文件夹，或打开它继续浏览。") : t("No subfolders here. You can use this folder.", "这里没有子文件夹，可以使用当前文件夹。"));
        for (const item of folders) {
          const open = button(`${item.name}  ›`, () => load(String(item.path || "")));
          open.set_hexpand(true);
          folderList.append(open);
        }
      });
    };
    dialog.present();
    load("");
  }

  openAddDialog() {
    if (!this.connections?.length) {
      this.showMessage(t("Connect and authorize a NAS first.", "请先连接并授权一台 NAS。"), true);
      this.openConnectionDialog();
      return;
    }
    const dialog = new Gtk.Window({title: t("Add sync task", "添加同步任务"), transient_for: this.window, modal: true, default_width: 640});
    const box = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 10});
    box.set_margin_top(18); box.set_margin_bottom(18); box.set_margin_start(20); box.set_margin_end(20);

    box.append(label(t("Task name", "任务名称")));
    const name = new Gtk.Entry({placeholder_text: t("For example: Work documents", "例如：工作文档"), hexpand: true});
    box.append(name);
    box.append(label(t("NAS connection (authorization is reused)", "NAS 连接（复用已有授权）")));
    const connection = Gtk.DropDown.new_from_strings(this.connections.map(item => `${item.name} · ${item.username}`));
    box.append(connection);
    box.append(label(t("Sync mode", "同步模式")));
    const mode = Gtk.DropDown.new_from_strings([t("Two-way sync", "双向同步"), t("Upload only", "仅上传"), t("Download only", "仅下载")]);
    box.append(mode);

    const selectionRow = (title, placeholder, chooseText, callback) => {
      box.append(label(title));
      const row = new Gtk.Box({spacing: 8});
      const entry = new Gtk.Entry({placeholder_text: placeholder, editable: false, hexpand: true});
      row.append(entry);
      row.append(button(chooseText, () => callback(entry)));
      box.append(row);
      return entry;
    };
    const remote = selectionRow(
      t("NAS folder", "NAS 文件夹"),
      t("Choose a folder on the NAS", "选择 NAS 上的文件夹"),
      t("Browse NAS…", "浏览 NAS…"),
      entry => this.openRemoteFolderChooser(this.connections[connection.get_selected()], dialog, path => entry.set_text(path)),
    );
    const local = selectionRow(
      t("Local folder", "本地文件夹"),
      t("Choose an existing local folder", "选择已有的本地文件夹"),
      t("Choose folder…", "选择文件夹…"),
      entry => this.openLocalFolderChooser(dialog, path => entry.set_text(path)),
    );
    connection.connect("notify::selected", () => remote.set_text(""));

    const dialogMessage = label(t("Both folders must be selected; paths cannot be typed manually.", "必须选择两端文件夹，路径不能手动输入。"), "dim-label");
    box.append(dialogMessage);
    const actions = new Gtk.Box({spacing: 8, halign: Gtk.Align.END});
    actions.append(button(t("Cancel", "取消"), () => dialog.destroy()));
    const save = button(t("Save task", "保存任务"), () => {
      const values = {name: name.get_text().trim(), remote: remote.get_text().trim(), local: local.get_text().trim()};
      if (Object.values(values).some(value => !value)) {
        dialogMessage.set_label(t("Name the task and select both folders.", "请填写任务名称并选择两端文件夹。"));
        dialogMessage.add_css_class("error-text");
        return;
      }
      const modes = ["two-way", "upload-only", "download-only"];
      const chosen = this.connections[connection.get_selected()];
      const args = ["task", "add", "--name", values.name, "--connection", chosen.id,
        "--remote-path", values.remote, "--local", values.local, "--mode", modes[mode.get_selected()]];
      save.set_sensitive(false);
      runController(args, null, (code, stdout, stderr) => {
        if (code !== 0) {
          dialogMessage.set_label((stderr || stdout || t("Could not save the task", "无法保存任务")).trim());
          dialogMessage.add_css_class("error-text");
          save.set_sensitive(true);
          return;
        }
        dialog.destroy();
        this.showMessage(t("Task added. Choose the conflict rule, then run Check first sync.", "任务已添加。请选择冲突规则，然后运行“检查首次同步”。"));
        this.refresh();
      });
    }, true);
    actions.append(save);
    box.append(actions);
    dialog.set_child(box);
    dialog.present();
  }

  openConnectionManager() {
    if (!this.connections?.length) {
      this.openConnectionDialog();
      return;
    }
    const dialog = new Gtk.Window({title: t("NAS connections", "NAS 连接"), transient_for: this.window, modal: true, default_width: 680, default_height: 440});
    const box = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 12});
    box.set_margin_top(18); box.set_margin_bottom(18); box.set_margin_start(20); box.set_margin_end(20);
    box.append(label(t("Saved authorizations", "已保存的授权"), "title"));
    box.append(label(t("Tasks reuse these authorizations. Choose Add another NAS only when you really need a separate server or account.", "同步任务会复用这些授权。只有确实需要其他服务器或账号时，才添加另一台 NAS。"), "dim-label"));
    const managerMessage = label("");
    box.append(managerMessage);
    const scroll = new Gtk.ScrolledWindow({hexpand: true, vexpand: true});
    const list = new Gtk.ListBox({selection_mode: Gtk.SelectionMode.NONE});
    list.add_css_class("boxed-list");
    for (const item of this.connections) {
      const row = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 8});
      row.set_margin_top(12); row.set_margin_bottom(12); row.set_margin_start(14); row.set_margin_end(14);
      row.append(label(item.name, "title"));
      row.append(label(`${item.username} · ${item.url}`, "dim-label"));
      const actions = new Gtk.Box({spacing: 8});
      actions.append(button(t("Test & browse", "测试并浏览"), () => {
        managerMessage.set_label(t(`Testing ${item.name}…`, `正在测试 ${item.name}…`));
        runController(["connection", "folders", item.id, "--json"], null, (code, stdout, stderr) => {
          if (code !== 0) {
            managerMessage.set_label((stderr || stdout || t("Connection test failed", "连接测试失败")).trim());
            managerMessage.add_css_class("error-text");
            return;
          }
          managerMessage.remove_css_class("error-text");
          managerMessage.set_label(t(`${item.name} is working.`, `${item.name} 工作正常。`));
          this.openRemoteFolderChooser(item, dialog, () => {});
        });
      }));
      actions.append(button(t("Remove", "移除"), () => {
        runController(["connection", "remove", item.id], null, (code, stdout, stderr) => {
          if (code !== 0) {
            managerMessage.set_label((stderr || stdout || t("Could not remove this connection", "无法移除此连接")).trim());
            managerMessage.add_css_class("error-text");
            return;
          }
          dialog.destroy();
          this.refresh();
        });
      }));
      row.append(actions);
      list.append(row);
    }
    scroll.set_child(list);
    box.append(scroll);
    const actions = new Gtk.Box({spacing: 8, halign: Gtk.Align.END});
    actions.append(button(t("Close", "关闭"), () => dialog.destroy()));
    actions.append(button(t("Add another NAS", "添加另一台 NAS"), () => {
      dialog.destroy();
      this.openConnectionDialog();
    }, true));
    box.append(actions);
    dialog.set_child(box);
    dialog.present();
  }

  openConnectionDialog() {
    const dialog = new Gtk.Window({title: t("Add NAS authorization", "添加 NAS 授权"), transient_for: this.window, modal: true, default_width: 640});
    const box = new Gtk.Box({orientation: Gtk.Orientation.VERTICAL, spacing: 10});
    box.set_margin_top(18); box.set_margin_bottom(18); box.set_margin_start(20); box.set_margin_end(20);
    box.append(label(t("Test login and folder navigation before saving. No credential is stored during the test.", "保存前必须测试登录和文件夹浏览；测试期间不会保存凭据。"), "dim-label"));

    const fields = {};
    const addField = (key, title, placeholder = "", secret = false) => {
      box.append(label(title));
      const entry = new Gtk.Entry({placeholder_text: placeholder, visibility: !secret, hexpand: true});
      fields[key] = entry;
      box.append(entry);
    };
    addField("name", t("Connection name", "连接名称"), t("For example: Home NAS", "例如：家里的 NAS"));
    addField("url", t("fnOS WebDAV address", "fnOS WebDAV 地址"), "https://192.168.1.20:5006/");
    addField("username", t("fnOS username", "fnOS 用户名"));
    addField("password", t("WebDAV password", "WebDAV 密码"), "", true);
    const insecure = new Gtk.CheckButton({label: t("Trust an fnOS self-signed certificate (skip TLS verification)", "信任 fnOS 自签名证书（跳过 TLS 验证）")});
    const allowHttp = new Gtk.CheckButton({label: t("Allow plain HTTP (trusted LAN only)", "允许明文 HTTP（仅可用于受信任局域网）")});
    box.append(insecure);
    box.append(allowHttp);
    const dialogMessage = label(t("Not tested yet", "尚未测试"), "dim-label");
    box.append(dialogMessage);

    let verifiedFingerprint = "";
    const values = () => Object.fromEntries(Object.entries(fields).map(([key, entry]) => [key, entry.get_text().trim()]));
    const fingerprint = current => JSON.stringify([current.name, current.url, current.username, current.password, insecure.get_active(), allowHttp.get_active()]);
    const connectionArgs = (command, current) => {
      const args = ["connection", command, "--url", current.url, "--username", current.username, "--password-stdin"];
      if (command === "add") args.push("--name", current.name);
      if (insecure.get_active()) args.push("--insecure-skip-verify");
      if (allowHttp.get_active()) args.push("--allow-http");
      if (command === "verify") args.push("--json");
      return args;
    };

    const actions = new Gtk.Box({spacing: 8, halign: Gtk.Align.END});
    actions.append(button(t("Cancel", "取消"), () => dialog.destroy()));
    let save;
    const test = button(t("Test & browse", "测试并浏览"), () => {
      const current = values();
      if (Object.values(current).some(value => !value)) {
        dialogMessage.set_label(t("Complete every field before testing.", "测试前请填写所有字段。"));
        dialogMessage.add_css_class("error-text");
        return;
      }
      test.set_sensitive(false);
      save.set_sensitive(false);
      dialogMessage.remove_css_class("error-text");
      dialogMessage.set_label(t("Testing login and reading the NAS folder list…", "正在测试登录并读取 NAS 文件夹列表…"));
      runController(connectionArgs("verify", current), current.password + "\n", (code, stdout, stderr) => {
        test.set_sensitive(true);
        if (code !== 0) {
          verifiedFingerprint = "";
          dialogMessage.set_label((stderr || stdout || t("Connection test failed", "连接测试失败")).trim());
          dialogMessage.add_css_class("error-text");
          return;
        }
        let payload = {};
        try { payload = JSON.parse(stdout || "{}"); } catch (error) { payload = {}; }
        verifiedFingerprint = fingerprint(current);
        save.set_sensitive(true);
        dialogMessage.remove_css_class("error-text");
        const count = Array.isArray(payload.folders) ? payload.folders.length : 0;
        dialogMessage.set_label(t(`Connection works; folder navigation returned ${count} root folder(s). You can now save.`, `连接正常；文件夹浏览返回 ${count} 个根目录文件夹。现在可以保存。`));
      });
    });
    actions.append(test);
    save = button(t("Save authorization", "保存授权"), () => {
      const current = values();
      if (!verifiedFingerprint || verifiedFingerprint !== fingerprint(current)) {
        save.set_sensitive(false);
        dialogMessage.set_label(t("Connection details changed. Test again before saving.", "连接信息已更改，请重新测试后再保存。"));
        dialogMessage.add_css_class("error-text");
        return;
      }
      test.set_sensitive(false);
      save.set_sensitive(false);
      dialogMessage.remove_css_class("error-text");
      dialogMessage.set_label(t("Rechecking and saving authorization…", "正在复查并保存授权…"));
      runController(connectionArgs("add", current), current.password + "\n", (code, stdout, stderr) => {
        if (code !== 0) {
          test.set_sensitive(true);
          dialogMessage.set_label((stderr || stdout || t("Could not save NAS authorization", "无法保存 NAS 授权")).trim());
          dialogMessage.add_css_class("error-text");
          return;
        }
        dialog.destroy();
        this.showMessage(t("NAS authorized and verified. It is ready for sync tasks.", "NAS 已验证并授权，可以用于同步任务。"));
        this.refresh();
      });
    }, true);
    save.set_sensitive(false);
    actions.append(save);
    const invalidate = () => {
      verifiedFingerprint = "";
      if (save) save.set_sensitive(false);
      dialogMessage.remove_css_class("error-text");
      dialogMessage.set_label(t("Connection details changed; test before saving.", "连接信息已更改，请测试后再保存。"));
    };
    for (const entry of Object.values(fields)) entry.connect("changed", invalidate);
    insecure.connect("toggled", invalidate);
    allowHttp.connect("toggled", invalidate);
    box.append(actions);
    dialog.set_child(box);
    dialog.present();
  }
}

function installStyles() {
  const display = Gdk.Display.get_default();
  if (!display) return;
  const css = new Gtk.CssProvider();
  css.load_from_string(`
    .title { font-size: 17px; font-weight: 700; }
    .dim-label { opacity: 0.68; }
    .banner { padding: 10px 12px; border-radius: 8px; background: alpha(@accent_bg_color, 0.16); }
    .banner.error { background: alpha(@error_bg_color, 0.18); color: @error_color; }
    .badge { padding: 3px 9px; border-radius: 999px; background: alpha(@accent_bg_color, 0.20); }
    .badge.error, .error-text { color: @error_color; }
  `);
  Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION);
}

const app = new Gtk.Application({application_id: APP_ID, flags: Gio.ApplicationFlags.DEFAULT_FLAGS});
app.connect("activate", application => {
  installStyles();
  const win = new FnSyncWindow(application);
  win.window.present();
});
app.run([]);
