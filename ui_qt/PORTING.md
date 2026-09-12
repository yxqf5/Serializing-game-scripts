# ui_qt 移植契约(tkinter 游戏助手.pyw → PySide6)

> 本文档是 3 个并行 Agent 的仲裁依据。签名冲突时以本文档为准。
> 参考实现:游戏助手.pyw(tkinter 版,保留不动,可对照移植)。逻辑层模块零改动、直接 import。

## 铁律
1. 只创建/修改自己名下的文件;**禁止**改 游戏助手.pyw、逻辑层模块、tests/、build 脚本;**禁止 git commit**;禁止安装包。
2. 保留桩文件里已有的公开签名(类名、方法名、参数);可以新增私有方法/信号。
3. 界面文案、中文提示一律照抄旧版(保持一致);代码风格:文件头 `# -*- coding: utf-8 -*-`、中文注释、简洁。
4. 跨线程:工作线程内**只能发 Qt 信号**,不得直接摸任何 QWidget。
5. 每完成一个文件:`python -m py_compile <file>`;最后跑冒烟(见文末)。

## 运行环境
- Python: miniconda `python`(3.x),PySide6 已安装。
- 离屏冒烟:`QT_QPA_PLATFORM=offscreen python -c "..."`(Windows Git Bash 下同样有效)。
- 逻辑层公开 API 清单见附录 A;queue 消息协议见附录 B;settings 键见附录 C;插件字段见附录 D。

## 模块与签名契约

### core_glue.py(Agent A)
从 游戏助手.pyw 模块级平移(逻辑不变):`SETTINGS_FILE/PLUGIN_DIR/LOG_DIR/DAILY_STATE_FILE/BASE_DIR`、
`load_settings() -> dict`、`save_settings(d)`、`load_plugins() -> list[dict]`、`save_plugin(p)`、
`WAIT_MODE_LABELS`、`log_tag_for(msg, level=None) -> str|None`(移植 App._log_tag_for:2902 的关键词逻辑,去掉 self)。
另含 `LOG_VIEW_LINES = 600`。

### theme.py(Agent A)
- `THEMES: dict[str, dict]`(照抄旧版 4 套:橙黑/绝区零/英伦/极简,键名 bg/panel/line/fg/sub/accent/on_accent/log_bg/log_fg/ok/warn/err/log_gold/log_blue)、`DEFAULT_THEME`。
- `FONT_SCALES = {"小":0.9, "中":1.0, "大":1.15, "特大":1.3}`。
- `base_pt(size, settings) -> int`:tkinter F(size) ≈ Qt point(size-1,最小8)× FONT_SCALES 档位。
- `font(settings, size, bold=False) -> QFont`。
- `qss(theme_name, settings) -> str`:全局 QSS,覆盖 QWidget 底色、QLineEdit/QTextEdit/QComboBox/QCheckBox、QPushButton(普通/accent 变体,用动态属性 `class="accent"`)、QScrollBar(窄、深色)、QSplitter::handle、QToolTip、侧栏选中态(动态属性 `navActive=true`)。色值从 THEMES 取。

### run_controller.py(Agent A)
```python
class RunController(QObject):
    log_lines = Signal(list)                 # list[(text, level|None)] 批量
    run_event = Signal(dict)                 # 与旧 ui_queue "run_event" 的 event 字典一致
    preflight_done = Signal(int, list, list) # token, active_plugins, issues(见 preflight.check_plugins)
    state_changed = Signal(dict)             # run_state 快照:state/index/total/name/message/result/parallel_names
    finished = Signal()                      # Runner 结束(__DONE__)
    def __init__(self, settings: dict)
    def start(self, plugins: list[dict]) -> None   # 起 preflight 线程,完成后发 preflight_done
    def begin_run(self, active: list[dict]) -> None # 用户确认后真正开跑(镜像旧 _finish_preflight 后半段)
    def cancel_preflight(self) -> None
    def stop(self) -> None
    running: bool
    def save_run_log(self) -> None  # 移植 _save_run_log:md 记录用 _run_log_buffer(5万行) + log_saver.append_run_markdown 语义
```
内部:`log_queue`/`ui_queue` 协议不变(附录 B);`QTimer(33ms)` 排水(上限 1000 行/次、12ms 时间片,照抄 _drain_log 节奏);`Runner(self._enqueue_log, self.stop_event, self._enqueue_run_event, daily_state_file=...)`;结束时 `log_queue.put(("__DONE__", None, None))`;`_run_log_buffer` 上限 50000 行、`_run_log_dropped` 统计。工作线程只 put 队列。

### app.py(Agent A)
```python
def main() -> int
class MainWindow(QMainWindow):
    settings: dict
    controller: RunController
    plugins: list[dict]
    home_page: HomePage            # 自己构造(B 实现),含 .log_panel
    def save_settings_soon(self)   # 350ms 防抖
    def reload_plugins(self) -> None          # 重读插件并让主页刷新
    def reload_and_render(self) -> None
    def go(self, name: str, plugin: dict | None = None) -> None
        # name ∈ home/add/edit/first_run/help/settings;add/edit 需要 plugin/预设上下文
    def open_edit(self, plugin: dict) -> None
    def add_plugin(self) -> None
    def delete_plugin(self, p) -> None
    def toggle(self, p) -> None                # 启用开关(照抄旧版)
    def toggle_parallel(self, p) -> None
    def move_plugin(self, p, delta: int) -> None     # 上/下移(order 交换+save)
    def reorder_plugin(self, p, new_index: int) -> None  # 拖拽落点(order 重排)
    def start_run(self) -> None                # 全局运行条「开始」:enabled 插件 → controller.start
    def stop_run(self) -> None
    def refresh_run_buttons(self) -> None
    def apply_theme_and_rebuild(self) -> None  # 设置页切换主题/字体后调用
```
外壳:左**侧栏**(固定宽,logo app.png、导航项 主页/部署向导 + 底部 使用帮助/设置 + 「● 管理员模式/非管理员」)、中 QStackedWidget(六个页面,add/edit 动态创建后入栈)、底部**全局运行条**(状态圆点、运行标题、进度 x/y、开始/停止按钮、用时)——移植 `_build_global_run_bar`/`_update_global_run_bar`/`_refresh_run_buttons` 语义。
窗口:标题「一键长草 · 游戏串行助手」、图标 assets/icons/app.png(窗口+任务栏 AppUserModelID "Games.Py.SerialRunner.GameAssistant.1")、minsize 940×660、geometry/maximized 持久化(500ms 防抖,`clamp_window_bounds` 校正)、关闭时 flush 设置。DPI:Qt6 自动,无需 hack;深色标题栏可不做(可选项,加分项:QWidget.winId + DwmSetWindowAttribute)。
接线:controller.log_lines → home_page.log_panel.append_lines;controller.run_event → 内部 run_state 更新(_apply_run_event:2843 的 kind 全集)→ state_changed → 运行条+卡片控制态;preflight_done → 弹窗确认逻辑(照旧:error 阻断、warn askyesno)→ begin_run/取消;finished → save_run_log + 刷新。

### home_page.py(Agent B)
```python
class HomePage(QWidget):
    def __init__(self, main: MainWindow)
    log_panel: LogPanel
    def refresh_cards(self) -> None            # = _render_cards
    def refresh_status(self) -> None           # = _refresh_home_status(顶部自检汇总条)
    def set_log_focus(self, on: bool) -> None  # 专注模式 = 隐藏/恢复队列面板
```
QSplitter(垂直):上=队列区(标题行「游戏队列」+「＋ 添加游戏」「↻ 刷新」、状态汇总条、卡片滚动区),下=LogPanel。`home_log_ratio` 读写(0.25~0.72 钳制,splitterMoved 保存)。
卡片(移植 _card:938):序号、游戏名(elide_end)、路径(elide_middle)、状态行(_card_status:_path_exists TTL 3s 探测 + 就绪/缺失着色)、启用开关(toggle)、并行标记(toggle_parallel,仅按钮)、↑/↓(move_plugin)、编辑、删除;整卡可拖拽排序(拖到目标位高亮,落下 reorder_plugin,落盘 _save_orders 语义);tooltip 完整名/路径。空列表显示占位提示。刷新时不清滚动位置(照旧版语义)。

### log_panel.py(Agent B)
```python
class LogPanel(QWidget):
    focus_requested = Signal(bool)
    def __init__(self, main: MainWindow, log_store: LogStore)
    def append_lines(self, lines: list) -> None   # 批量插入;group_tagged_lines 复用;maximumBlockCount(600)
    def render_store(self) -> None                # 主题切换后全量重插(尾部600)
    def refresh_toolbar(self) -> None             # 跟随按钮文案/颜色 + 「N 行 · 已丢弃较早 M 行」
```
工具栏按钮(照旧顺序):● 跟随最新/○ 已暂停、复制、清空(确认)、导出、目录、导入、□ 专注/▣ 退出专注。滚动到底自动跟随、上滚暂停(QScrollBar rangeChanged+valueChanged 实现旧 _on_log_scroll 语义)。着色:log_tag_for(core_glue)→ QTextCharFormat。导入:文件对话框(utf-8-sig→gbk 容错,>20000 行截断提示)→「日志查看」只读对话框(可放本文件)。

### add_page.py(Agent C)
```python
class AddPage(QWidget):
    def __init__(self, main: MainWindow)
    def open_for(self, preset_id: str | None = None) -> None
```
移植 build_add:1911(游戏下拉→脚本下拉→「扫描启动器」→候选列表→自定义模式框→保存)。扫描在**工作线程**(preset_resolver.resolve_all_candidates/resolve_launcher,10s 超时)→ 信号回填;保存走 preset_catalog.resolve_and_build/build_plugin + save_plugin_file → main.reload_and_render + go home。

### edit_page.py(Agent C)
```python
class EditPage(QWidget):
    def open_for(self, plugin: dict) -> None   # 填表
```
移植 build_edit:1141 全部字段(name/launcher/args/wait_mode/game_processes/helper_processes/log_file/log_encoding/daily_done_patterns/daily_pending_patterns/stamina_patterns/start_timeout_min/parallel/pre_launcher/pre_args/pre_delay_sec/notes/doc_url/setup_checklist 摘要)+「高级选项」折叠 + 浏览按钮(QFileDialog)+ 粘贴填充入口 + 保存(save_plugin → main.reload_and_render + go home)。工作目录参照 _save_edit:1370。

### wizard_page.py(Agent C)
```python
class WizardPage(QWidget):
    def refresh(self) -> None
```
移植 build_first_run:2320 全套:管理员检测说明、每游戏卡片(_wizard_game_card:2441:状态、下载按钮 _wizard_dl_buttons、一键配置 _wizard_apply_setup→assistant_setup.apply_for_plugin、导入 _wizard_import_game、扫描 _wizard_rescan/_wizard_apply_scan→线程+信号、恢复 _wizard_restore→backup/restore_backup、安装检查 verify_for_plugin)、底部「完成」(_first_run_finish:写 first_run_done → go home)。扫描/配置等耗时操作必须在工作线程。

### settings_page.py(Agent C)
```python
class SettingsPage(QWidget):
    def refresh(self) -> None
```
移植 build_settings:1636:主题卡片(4 套,点击即 main.apply_theme_and_rebuild)、字体族下拉(微软雅黑/Microsoft YaHei UI/黑体/等线/宋体/Arial)+字号档(小中大特大,改后重建)、助手根目录(选择+清缓存)、日志保留(week/month/forever,改后 log_saver.cleanup_old_logs)。

### help_page.py(Agent C)
```python
class HelpPage(QWidget):
```
移植 build_help:1770 + HELP_TEXT(游戏助手.pyw:3222)全文,用 QTextBrowser 只读展示。

### dialogs.py(Agent C)
```python
class QuickFillDialog(QDialog):
    def __init__(self, parent, mode: str, plugin: dict | None)  # mode: "add"|"edit"
    applied = Signal(dict)   # 解析出的 fields
```
移植 _open_quick_fill_dialog:1416:左侧粘贴文本(QTextEdit,预填 export_plugin_to_text/SAMPLE_QUICK_FILL)、右侧说明;「确认并保存」→ qf.parse_quick_fill → 出错提示 / 成功发 applied(由页面把 fields 填进表单,照 _apply_parsed_to_edit:1540/_apply_parsed_to_add:1595)。
另提供 `askyesno(parent, title, text) -> bool`、`showinfo/showerror` 封装。

## 附录 A:逻辑层公开 API(节选,全部可直接 import)
- runner_core:`Runner(log_func, stop_event, event_func, settle_sec=1.0, daily_state_file=None)`、`run_all(plugins)`、`split_queue(plugins)`、`is_admin()`、`snapshot_running_processes()`、`DailyDoneState(path)`
- ui_helpers:`LogStore(max_lines=10000)`、`group_tagged_lines(lines, tag_func)`、`elide_middle/elide_end`、`clamp_window_bounds`
- preflight:`check_plugins(plugins, running_names=None) -> issues`、`has_blocking_errors(issues)`
- quick_fill:`parse_quick_fill(text)`、`export_plugin_to_text(plugin)`、`SAMPLE_QUICK_FILL`
- preset_catalog:`load_catalog/list_games/get_game/get_script/find_script_by_preset_id/next_plugin_order/build_plugin/save_plugin_file/resolve_and_build/import_default_plugins/pending_checklist_count`
- preset_resolver:`resolve_launcher/resolve_all_candidates/update_path_cache/get_assistants_root/fixed_drives/narrow_search_roots/default_search_roots`(耗时操作一律进线程)
- log_saver:`retention_days/today_record_count/append_run_record/build_run_markdown/cleanup_old_logs`
- log_watcher:`ScriptLogWatcher(...).start/poll/finish`(Runner 内部已用,UI 不直接碰)
- assistant_setup:`apply_for_plugin/verify_for_plugin/backup_files/list_backups/restore_backup/backup_time_label`

## 附录 B:队列消息协议(RunController 内部沿用)
- log_queue:`("line", msg, level|None)`、`("__DONE__", None, None)`;level ∈ info/warn/error/ok/gold/blue
- ui_queue:`("preflight", token, active, issues)`、`("run_event", event)`;
  event kind:`queue_started{total,parallel_total}`、`task_started{index,total,name[,parallel]}`、`stage_changed{stage,message,index,total,name[,parallel]}`、`task_finished{index,total,name,result,task_status[,parallel]}`、`queue_finished{result}`(result ∈ completed/skipped/failed/stopped)

## 附录 C:settings.json 键
theme(橙黑/绝区零/英伦/极简)、font_family、font_size(小/中/大/特大)、first_run_done、path_cache、window_maximized、window_bounds{x,y,width,height}、home_log_ratio(0.25~0.72)、log_retention(week/month/forever)、assistants_root

## 附录 D:插件 dict 字段
id,name,launcher,args,wait_mode("game"/"helper"),game_processes,helper_processes,log_file,log_encoding,daily_done_patterns,daily_pending_patterns,stamina_patterns,start_timeout_min,enabled,order,parallel,notes,preset_id,preset_game_id,setup_checklist,checklist_done,doc_url[,pre_launcher,pre_args,pre_delay_sec],_file(运行时)

## 冒烟自验(每人做完后)
```bash
python -m py_compile ui_qt/<你的文件>
QT_QPA_PLATFORM=offscreen python -c "import ui_qt.<你的模块>"
```
集成冒烟(主 Agent):`QT_QPA_PLATFORM=offscreen python 游戏助手Qt.pyw --smoke`(app.main 支持 --smoke:建窗→切 6 页→灌 3 条日志→退出,不进事件循环)。
