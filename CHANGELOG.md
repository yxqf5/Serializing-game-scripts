# CHANGELOG · 修改记录

> 面向后续接手的 AI / 开发者。每次改动后追加一节,便于快速定位"这个功能是为什么加的、怎么改的"。
> 涉及原理与结构速览见 `AI_HANDOFF.md`。

---

## 2026-09-12 · Qt 版完整入库:旧版 UI 的最后版本(标签 v1.2.0-qt-oldui)

背景:Qt 版此前一直在工作区未入库。在启动主页/设置页 UI 重设计之前,把当前旧版 UI 的完整 Qt 实现提交并打标签,作为重设计前的基线;此标签之后的改动即新 UI 迭代。

### 入库内容

- `ui_qt/` 页面包全部入库(app/home/settings/add/edit/wizard/help/log_panel/run_controller/theme/core_glue/dialogs)
- `schedule_core.py`(每日定时,Qt 版专用)+ `display_ctrl.py`(运行时分辨率切换)+ 对应三份新测试
- `游戏助手Qt.pyw` 入口、`一键长草助手Qt.spec` 打包规格、`build_exe_qt.bat` 打包脚本
- `.gitignore` 补 `一键长草助手Qt.exe`(与 tkinter 版 exe 同例,打包产物不入库)
- AI_HANDOFF / 使用说明 / CHANGELOG 同步(含ffi.dll 打包修复、分辨率切换两节)

### 验证

- `run_tests.py` 184 项全过

---

## 2026-09-12 · 修复打包 exe 启动崩溃:conda 打包缺 ffi.dll 导致 _ctypes 加载失败

背景:exe 启动即崩「ImportError: DLL load failed while importing _ctypes: 找不到指定的模块」。根因:miniconda 的 `_ctypes.pyd` 动态链接 `%PREFIX%\Library\bin\ffi.dll`,PyInstaller 分析不到这层依赖、没打进包。此前一直未暴露,是因为 runner_core 等处的 `import ctypes` 全部 try/except 静默降级(exe 里管理员检测/快速进程快照其实一直在走降级路径);display_ctrl.py 新增后顶层硬 `import ctypes`,才把整个启动炸了。旧 tkinter 版 spec 早已手动收过 `ffi.dll`(conda_dlls 列表里就有),Qt 版 spec 漏了同样的处理。

### 修复

- `一键长草助手Qt.spec`:glob `sys.prefix\Library\bin\ffi*.dll` 显式加入 binaries;换非 conda 环境打包时 glob 为空、无副作用
- `display_ctrl.py` 加固:`import ctypes` 改 try/except 降级(ctypes 不可用时 `_DevModeW`/`_user32` 不定义,`set_resolution` 等返回安全失败值)——坏环境只损失分辨率切换功能,不再拖垮整个程序启动;正常环境行为完全不变
- tkinter 版 spec 原本已含 `ffi.dll`,无需改动

### 验证

- 源环境(miniconda3)`import ctypes` 正常;display_ctrl 正常路径 `current_resolution()` 读到真实分辨率,模拟 ctypes 不可用的降级路径(supported_modes=[]、set_resolution 返回失败元组)全部安全
- `run_tests.py` 184 项全过;重新打包后 `archive_viewer -l` 确认 `_ctypes.pyd` 与 `ffi.dll` 均在 onefile exe 内,根因消除
- 注:exe 清单要求管理员(UAC),宿主 shell 非管理员无法命令行拉起自检,最终请双击 exe 确认能正常进主界面

---

## 2026-09-12 · 新功能：运行时自动切换分辨率（适配仅支持 16:9 的开源脚本）

背景：用户屏幕 2560×1600（16:10），MAA/BetterGI/三月七助手/一条龙等开源脚本普遍只适配 16:9（1080P/2K），在此分辨率下脚本运行失败。实测该机屏幕同时支持 1920×1080 与 2560×1440（均 165Hz）。

### 方案

- 新增逻辑模块 `display_ctrl.py`（无 UI 依赖）：`current_resolution()`（**双偏移容错解析**：本机 GameViewer 间接显示驱动经 CDD 路径返回的 DEVMODE 缓冲自 dmLogPixels 起整体 +8 字节（dmSize=188，标准 212），宽/高真实位于 172/176 而非标准 164/168，故标准偏移优先、+8 兜底、再回退 GetSystemMetrics）、`set_resolution()`（**优先用驱动返回的原样缓冲改宽高**——找到当前分辨率所在偏移组，只改那一组 + dmFields，其余字节不动；实测标准输入会被拒 BADMODE=-2，此法可行。切换后复核 current_resolution 确认生效）、`apply_for_run()`/`restore_if_needed()`（原始分辨率落盘 `display_state.json`，崩溃后下次启动自动恢复；恢复失败保留文件重试）
- Qt 接线：`run_controller.py` 开跑前按 `settings["run_resolution"]` 切换、finally 恢复（含停止/异常）；`app.py` 启动崩溃恢复、运行中关窗兜底恢复、未开启自动切换且当前非 16:9 时开始前弹提示（定时触发走日志不弹窗）；`settings_page.py` 新增「运行时分辨率」（不切换/1920×1080/2560×1440，默认不切换）
- tkinter 版最小接线（同一 settings 键，行为对齐）：`_finish_preflight` worker 切换/finally 恢复、`App.__init__` 启动恢复、`start_run` 预警；无 UI 设置项

### 验证

- `tests/test_display_ctrl.py` 14 项（假 user32：标准/偏移解析、偏移定位、状态文件往返、已是目标 no-op、不支持不落盘、恢复失败保留重试、先恢复再切换）
- 真机端到端：2560×1600 → apply 1920×1080（实测生效）→ restore → 2560×1600，状态文件清除
- 全量回归 184 项测试通过；`--smoke` 通过；tkinter 版编译通过

---

## 2026-09-12 · 定时任务:每天到点弹倒计时确认框,确认/归零开跑、跳过则放弃本次(Qt 版)

背景:用户希望每天固定时间自动跑串行队列,但怕挂机时突然开跑抢鼠标——到点先弹**倒计时确认框**:点「立即运行」或等倒计时归零 → 开跑;点「跳过」(或 Esc) → 本次不运行,明天同一时刻再问。对应 TODO P2-1,采用**应用内每日定时**(非 Windows 任务计划程序),前提是助手保持开启(可最小化)。

### 新增/改动

- **新模块 `schedule_core.py`(纯逻辑,与 UI 解耦)**:`parse_hhmm` 时刻解析、`next_daily_occurrence(t, now)` 下次触发时刻(今天的时刻已过→明天;恰好等于 now 视为已过,避免保存设置瞬间秒级重合立刻弹窗)、`countdown_bounds` 秒数夹取(10~600)、`schedule_config` 读取归一化配置。设置键:`schedule_enabled` / `schedule_time`("HH:MM",默认 04:00)/ `schedule_countdown_sec`(默认 60)
- **`ui_qt/dialogs.py` 新增 `ScheduleCountdownDialog`**:模态确认框,显示定时时刻 + 将运行的游戏列表 + 大字倒计时;内部 1s QTimer 归零自动 accept;「跳过本次」/Esc → reject
- **`ui_qt/app.py` 主窗口接入**:`MainWindow.__init__` 起 1s `_sched_timer` 轮询 `_sched_tick`;到点先推进 `_sched_next` 到明天(确认框打开期间不重复触发)再 `_fire_scheduled`;弹框前若最小化则 `showNormal`+`activateWindow`;**忙碌/无勾选任务/确认框异常 → 本次自动跳过并写日志**。运行条空闲态显示「下次定时 MM-DD HH:MM」
- **定时触发的前检查语义**:`start_run(scheduled=False)` 新增形参;`_on_preflight_done` 中定时触发的 warn 级警告(非管理员/进程占用等)**不弹窗询问,写日志自动通过**(否则挂机人不在会被 QMessageBox 卡死);error 级仍然阻断弹窗。开始按钮 connect 改 lambda,避免 `clicked(bool)` 的 checked 落进 `scheduled` 形参
- **`ui_qt/settings_page.py` 设置页新增「定时任务」区**:启用开关 + QTimeEdit(HH:mm) + 倒计时秒数 QSpinBox,任一变化写回 settings 并 `main.schedule_resync()` 重算
- 帮助页补「定时任务」说明段

### 验证

- 全量 `run_tests.py` 170 项通过(新增 `tests/test_schedule_core.py` 13 项纯逻辑 + `test_ui_qt.py` 9 项离屏:resync/tick 推进/到点三分支/确认框归零 accept 与 reject;测试注入假插件列表、关窗前还原内存 settings 不写回真实 settings.json)
- 离屏端到端 ×2(临时脚本,已删):真实 1s 调度器 → 真实倒计时框 ①归零自动 accept → `start_run(scheduled=True)` ②模拟点「跳过」→ 不开跑、`_sched_next` 推进到明天
- `--smoke` 冒烟通过;tkinter 版(游戏助手.pyw)未加此功能,仅 Qt 版提供

---

## 2026-09-12 · 界面移植 PySide6:新增 ui_qt/ 包与 Qt 版入口(tkinter 版保留)

背景:tkinter 版在 150% DPI 下窗口缩放仅 3.6fps(Tk 软件布局+GDI 渲染的结构性上限,见上一节),决定按社区主流路线迁移 Qt。**逻辑层(runner_core/ui_helpers/log_watcher/log_saver/preset_*/quick_fill/preflight/assistant_setup)零改动**,新旧版本共用 settings.json、plugins/*.json、logs/,tkinter 版完整保留可回退。

### 新增文件

- `ui_qt/` 包:`app.py`(MainWindow 外壳:侧栏导航/全局运行条/页面栈/窗口几何持久化/管理员状态/深色标题栏/AppUserModelID)、`run_controller.py`(Runner+preflight 守护线程,队列→Qt 信号,QTimer 33ms 排水,md 自动保存含 5 万行缓冲与 partial 语义)、`theme.py`(4 套主题→QSS、字号档)、`core_glue.py`(设置/插件读写、log_tag_for)、`home_page.py`(卡片列表:拖拽排序/启用/并行/▲▼/状态条/专注模式)、`log_panel.py`(QPlainTextEdit **maximumBlockCount(600)** 内置行数上限、级别着色、跟随、导入查看器)、`add_page.py`、`edit_page.py`、`wizard_page.py`、`settings_page.py`、`help_page.py`、`dialogs.py`(粘贴填充)、`PORTING.md`(契约)、`PARITY.md`(对等性清单)
- 入口 `游戏助手Qt.pyw`;打包 `一键长草助手Qt.spec` + `build_exe_qt.bat`(排除 tkinter/PIL);测试 `tests/test_ui_qt.py`(离屏冒烟:主窗口构建/六页切换/日志 600 行上限)

### 执行方式与验证

- 3 个并行 Agent 按文件分工实现(A:外壳+运行链路,B:主页+日志,C:页面+对话框),主 Agent 出契约文档与桩骨架统一签名;Agent 间零交叉编辑,逻辑层与旧版零接触
- 集成验证:全量 py_compile;`--smoke` 离屏冒烟;`run_tests.py` 148 项逻辑测试全过;tests/test_ui_qt 4 项全过;A 的 11 项运行链路自测(preflight 确认流/停止语义/并行事件/md 自动保存/partial/几何持久化)、B 的拖拽排序与跟随自测、C 的页面与线程信号自测全过
- **性能实测(与 tkinter 相同方法学:1 万行日志、全速连续缩放)**:tkinter 修复前 2.0fps → 修复后 3.6fps → **Qt 版 19.0fps(52.7ms/次),提升 5.3 倍**;真实拖拽中 Qt 还会合并中间状态,观感更顺
- 页面写运行日志统一走 `MainWindow.append_log()`(先入 LogStore 再上屏,导出/复制同源)

### 有意差异(相对 tkinter 版)

- 全局字体经 `app.setFont` 而非 QSS(Qt 中 QSS 字体会覆盖各处 setFont)
- 主题/字号切换不重建窗口(重刷 QSS+字体+日志重着色);add/edit 为复用页(open_for 重填)
- 运行条新增用时显示与运行中关闭确认;拖拽排序放宽为整卡可拖(按钮区除外)

---

## 2026-09-12 · 窗口缩放卡顿根治：日志字体回退链 + 界面日志截断 + 画布同步节流

背景：用户反馈拉伸窗口时 UI 明显卡顿。经端到端基准（加载真实程序模拟逐像素缩放、cProfile、组件二分、同轮交错对照）定位，**不是**此前怀疑的 Text 全量重折行（行数 600 与 1 万同耗），而是三个因素叠加。

### 根因（按贡献排序）

1. **日志 Text 用 Consolas 字体（无中文字形）**：每个中文字符走 GDI font-linking 回退链测量/渲染，实测同样 1 万行中文日志，Consolas 体系 ~450ms/步 vs 原生中文字体 ~110ms/步（150% DPI）。只要日志区有中文内容就有此项开销，与行数基本无关。
2. **高 DPI（tk scaling=2.0）下 CJK 文本渲染偏慢**：卡片、状态条等全部控件的逐帧重排是固定大项，无法从回调层优化。
3. **主页/编辑页/首次运行页的 Canvas 内嵌宽度逐像素同步**：每个 Configure 事件 `itemconfig` 强制全部卡片/表单控件重排（实测 ~50ms/步）。

### 修复（游戏助手.pyw）

- **日志 Text 字体 Consolas → `_FAMILY`（原生中文字体）**，同类的粘贴填充编辑器、导入日志查看窗口一并修改（`_show_log_viewer`）。注释注明原因防回归。**这是主要收益**
- 新增 `LOG_VIEW_LINES=600`：界面 Text 只保留最近 600 行（`_render_log_store` 只插尾部、`_insert_log_batch` 插入后裁头），完整 1 万行仍在 LogStore，导出/复制/自动保存（5 万行 `_run_log_buffer`）不受影响。**注意：裁剪必须在 `state="normal"` 下做，disabled 的 `delete()` 静默无效**（调试时踩过）
- 新增 `_throttle(attr, ms, func)` 通用节流（至多每 80ms 执行一次、停止后补一次）：主页 `_on_list_canvas_configure` 合并为 `_apply_card_layout`（内嵌宽度 + 卡片省略号一次做）；编辑页/首次运行页内嵌宽度同步走 `_sync_canvas_inner`。拖拽中内容仍以 ~12 次/秒跟随
- 移除 `_sync_card_wraplength` 的 after_idle 自调度（`_wrap_sync_job`），统一走 `_throttle`

### 验证

- 同步基准（每步 geometry+update，40 步×2 轮，同轮交错）：等效改前 ~451-509ms/步 → 修复后 ~293-303ms/步（**1.55-1.65x**）；真实拖拽为 60-120Hz 事件流，节流将卡片重排从每秒 60-120 次压到至多 12 次，实际体感增益更大
- 界面日志自检：LogStore=10000 行时界面 Text 恰为 600 行、跟随底部正常
- `python -m py_compile` 通过；`run_tests.py` 144 项全过

---

## 2026-09-12 · 日志模块加固：保存缓冲 / 轮转守卫 / 读取上限 / 尾部解码

背景：日志模块全面审查（log_watcher / log_saver / runner_core 日志链路 / 界面日志区）后修复 4 个问题。核心链路（线程队列、增量读取、编码兜底、原子落盘、并行线程安全）审查确认健壮，本次均为防御性加固。

### 1. 自动保存的 md 不再静默截断（游戏助手.pyw）

- 旧行为：`_save_run_log`/`_export_log` 直接取界面 LogStore（1 万行上限，超出丢最旧），md 无任何标注；脚本刷屏时最早的游戏失败证据恰会缺失；运行中点「清空日志」还会把前半段从 md 里抹掉
- 新增**保存专用缓冲** `_run_log_buffer`（上限 `RUN_LOG_BUFFER_MAX=50000` 行），与界面显示分离：md 取自缓冲，运行中清空只清界面不清缓冲；超限时 md 头部注入「⚠ 本次运行日志共约 N 行，较早的 M 行已省略」
- md 标题修正：有任务未完成的一轮不再标「全部完成」，改用新增的 `partial → 部分未完成` 标签（log_saver `_RESULT_LABELS`）

### 2. 日志轮转跟随守卫（log_watcher.py）

- 旧风险：`poll()` 按 mtime 取 glob 里最新文件并从头读——运行中若有**旧**日志被外部触碰（其他实例/编辑器/同步盘），watcher 会切过去把整份旧日志当成本次新增行，旧关键词混入证据造成误判
- 新增 `_should_follow()`：只跟随创建时间（getctime）晚于本次 `start()` 时刻（容差 2 秒）的文件；当前文件已不存在时强制跟随避免监控中断

### 3. 单次 poll 读取上限（log_watcher.py）

- `f.read()` 加 `MAX_POLL_READ=8MB` 上限、`_offset` 按实际读入量推进：脚本异常倾泻超大日志时分批消化，不再有内存峰值

### 4. 尾部残留字节按配置编码容错解码（log_watcher.py）

- `_flush_tail` 原硬编码 utf-8 replace；新增 `_decode_lossy()` 按 `_encodings()` 顺序解码。实际影响极小（流末残留必是不完整多字节序列），属正确性修正

### 5. 监控提示语与跟随可见性（runner_core.py）

- glob 监控的初始提示加「（脚本新建日志时会自动跟随）」注（启动前探测到的多半是前一天的文件，纯显示问题但易误解）
- 游戏模式确认游戏已启动后，若监控已切换文件则输出「[日志] 已跟随到脚本日志：路径」；导入日志查看器对超大文件只展示最后 2 万行并标注

### 测试

- `tests/test_log_watcher.py` 新增 5 项：跟随守卫（旧 ctime 拒绝/新 ctime 跟随/当前文件消失强制跟随）、旧文件被触碰不误读、新会话文件正常跟随、读取上限分批消化、`_decode_lossy`；全套 **144 项通过**

---

## 2026-09-12 · 修复：明日方舟检测项误报（MAA v6 新格式 gui.new.json）

背景：用户反馈向导里明日方舟一键配置出现「已配置模拟器连接（ADB 路径）」报警。排查结论：**误报**。本机 MAA 已从 v5 原地自更新到 v6.17.5（目录名仍是 MAA-v5.16.8），v6 把配置从 `gui.json`（点号键扁平、值为字符串）整体迁移到 `gui.new.json`（`Configurations.<名>.Gui` 嵌套：`StartUpSettings.RunDirectly/StartEmulator` 布尔、`PostActions` 为 `"ExitEmulator, ExitSelf"` 字符串、连接在 `ConnectSettings.AdbPath`），而 handler 只读旧文件。此前「MAA 配置被重置、串行已断」的判断**有误**——设置是迁移而非丢失，本机新格式里连接/启动/收尾全齐。

方案：`_setup_maa` 拆为双格式——`gui.new.json` 存在且可解析时走 `_maa_setup_new`（写 `RunDirectly=True`、`StartEmulator=True` 布尔，`PostActions` 补成含 `ExitEmulator`+`ExitSelf` 的字符串，ADB 自检读 `ConnectSettings.AdbPath`）；解析失败或文件不存在回退 `_maa_setup_old`（原 gui.json 逻辑不动）。备份/还原、dry-run 语义不变。

- `tests/test_assistant_setup.py` 新增 `TestMaaNewFormat` 6 项（新格式写入/幂等/dry-run 不落盘/新文件优先且不动旧文件/坏新文件回退旧格式/ADB 缺失报警），全套 139 项通过
- 注：本次修复前误写入旧 gui.json 的三个点号键无害保留（旧版回滚场景仍有效）；本机 MAA 无需任何人工操作

---

## 2026-09-12 · 新功能：部署向导 2.0 + 助手配置一键写入（面向零基础分发）

背景：exe 虽已可直接双击，但用户拿到的 90% 门槛在「安装并配置 4-5 个第三方助手」——March7th 要改 config.yaml、MAA 要勾三个开关、MaaEnd 要在任务队列末尾加收尾任务、BetterGI 要设一条龙结束操作。小白无法独立完成。目标：exe 发给零基础用户后，不碰任何配置文件、不敲任何命令即可用起来。用户决策：只发 exe+说明（不做整合包）；允许自动写入第三方配置（备份可还原）；先支持当前 5 款。

### 1. 新模块 assistant_setup.py

- 每个 preset_id 一个 handler（`HANDLERS`），统一接口 `handler(plugin, dry_run)`：
  - `m7a_main`：行级替换 `config.yaml` 顶层键 `after_finish: Exit`、`pause_after_success: false`（`_patch_flat_yaml` 保留行内注释、缺键追加、UTF-8/GBK 自适应、保留换行符风格）
  - `bettergi_onedragon`：`User\OneDragon\*.json`（取 mtime 最新）写 `CompletionAction="关闭游戏和软件"`
  - `maa_gui`：`config\gui.json` 在 `Configurations.<Current>` 下写 `Start.RunDirectly="True"`、`Start.OpenEmulatorAfterLaunch="True"`、`MainFunction.PostActions="12"`（键名经本机 `gui.json.old` 全量历史键验证；发现本机 gui.json 曾被重置丢失三键，本次已实际写回并留有备份）
  - `maaend_gui`：`config\mxu-MaaEnd.json` 选取 `savedDevice.connectedProgramPath` 含 Endfield.exe 的实例，任务队列末尾缺则补两个 `__MXU_KILLPROC__`（杀 Endfield.exe；SELF=true 退出 MaaEnd，保持收尾在最后）
  - `onedragon`：`config\one_dragon.yml` 顶层键 `after_done: 关闭游戏`
- 通用机制：写入前备份到 `<数据目录>\backup\config\<preset_id>\<时间戳>\`（manifest.json 记录原路径，`restore_backup` 整体还原）；文件缺失/解析失败**绝不盲写**，返回 `_manual_result`（ok=False + 人工指引）
- 对外入口仅 `apply_for_plugin`（写盘）/ `verify_for_plugin`（恒 dry-run，并把「无法自动配置」转成未完成检查项）/ `list_backups` / `restore_backup` / `SUPPORTED_PRESET_IDS`；未知预设回退用插件 `setup_checklist` 渲染
- 检查项语义：dry-run 只报「本来就是对的」；apply 写入成功后可写项恒 ✓（写失败已提前中止）

### 2. 游戏助手.pyw —— 部署向导 2.0

- `build_first_run` 整体重做：就绪进度总览（已导入 n 款中 ✓m 款就绪）→「助手安装根目录」可选设置 → **每款 catalog 游戏一张卡片**（状态徽标 ✓就绪/待配置/待设置路径/未导入；检查项逐条绿勾黄标；动作按钮：导入此游戏并检测路径 / 一键配置 / 重新检测 / 浏览 / 编辑 / 还原备份 / 官方下载）；一键配置结果就地回显（已自动写入 / 还需人工 / 错误）
- 侧栏新增「★ 部署向导」常驻导航项（老用户随时可进，不再只限首次启动）
- 新增 `_wizard_*` 方法族：卡片渲染、`_wizard_import_game`（单游戏导入+探测失败转手动浏览）、`_wizard_apply_setup`、`_wizard_rescan`（后台线程走 `ui_queue` 新事件 `wizard_scan` → `_wizard_apply_scan`）、`_wizard_browse`、`_wizard_restore`、根目录选择（向导版跳 first_run、设置页版 `_settings_pick_root` 留在设置页）
- 设置页新增「助手安装根目录」区块（只读展示 + 修改/清除）
- `_first_run_render_check` / `_first_run_step_box` 删除（被向导 2.0 取代）；`_first_run_import`（一键导入常用四套）保留在向导底栏

### 3. preset_resolver.py —— 助手根目录 + 全固定盘符

- 新增 `get_assistants_root(settings)`、`fixed_drives()`（`GetLogicalDrives + GetDriveTypeW==DRIVE_FIXED` 枚举，异常回退 C/D/E 探测）
- `narrow_search_roots(base_dir, settings=None)` / `default_search_roots(base_dir, settings=None)`：assistants_root 排首位、base_dir 可为 None；`_max_depth_for_root` 用正则判定任意盘符根（深度 2），自定义根目录深扫（5）
- `resolve_launcher` / `resolve_all_candidates` 的默认搜索根改为按 settings 构建（不再硬编码 `E:\ D:\`）；调用方（preset_catalog、pyw 添加页/向导）全部传入 settings

### 4. 文档与打包

- 使用说明.txt 零基础重写：开头「三步上手」、一键配置说明、终末地下载链接、备份还原与杀软 FAQ；同步 dist
- `build_exe.bat`：Python 探测改为 `%USERPROFILE%\miniconda3` → `where python`（去掉用户名硬编码）；py_compile 清单补新模块
- 新增 `tests/test_assistant_setup.py`（22 项：五款 handler 写入/幂等/dry-run 不落盘/坏 JSON 中止/备份还原/未知预设回退）；`test_preset_resolver.py` 补助手根目录 5 项；全套 **133 项通过**；GUI 冒烟（5 页面构建）通过；exe 已重新打包并同步根目录

---

## 2026-09-12 · 新功能：并行运行（模拟器类任务不再排队）

背景：明日方舟（MAA）跑在安卓模拟器里，操作走 ADB、**不占用真实鼠标**；而原神／绝区零／崩铁等脚本会模拟真实键鼠。串行队列把 MAA 也排在队尾依次跑，浪费了"能同时跑"的机会。用户希望：勾选了「并行」的任务（如 MAA）在点开始时立即与串行任务同时跑，其余任务照旧排队。

方案：插件新增 `parallel` 布尔字段（编辑页复选框「⇉ 并行运行」）；`Runner.run_all` 把队列分成并行组 + 串行组——并行组在队列开始时用独立线程同时启动（组内错峰 `PARALLEL_STAGGER_SEC=3` 秒），主线程照旧串行跑串行组，**两者全部结束后**才输出每日汇总并结束本轮。

### 1. runner_core.py

- 新增常量 `PARALLEL_STAGGER_SEC = 3.0` 与 `split_queue(plugins) -> (parallel_list, serial_list)`
- `run_all` 重构：并行任务各起一个 daemon 线程跑 `_run_one(..., parallel=True)`；串行循环结束后 `join` 全部并行线程再汇总；停止时并行线程靠现有 `_stopped()` 检查自行退出并 taskkill 收尾
- `_run_one` 拆出 `_run_one_body`；并行任务日志头为 `⇉ [并行] 名字`，该任务所有日志行带 `[名字]` 前缀（`threading.local` 存前缀，多任务日志交错可分辨），事件带 `parallel=True`（index=0，不占进度位）
- `task_status` 改由 `_log_task_final` 写入线程本地 `final_status` 经 `out` 参数回传，不再读共享的 `_last_task_status`（并行下有竞态）；属性仍保留写入以兼容旧调用
- `DailyDoneState` 加 `threading.Lock`（并行线程并发 mark_done 时保护 tmp+replace 写盘）

### 2. 游戏助手.pyw

- `load_plugins` 一次性迁移：`preset_id == "maa_gui"` 且无 `parallel` 字段的老插件自动补 `parallel: true` 写回（幂等）
- 编辑页：显示名称下方新增复选框「⇉ 并行运行（与其它任务同时启动）」+ 灰字说明；`_save_edit` 存 `p["parallel"]`
- **主页卡片「⇉」快捷开关**：每行右侧 ▲▼ 前新增「⇉」按钮，点一下直接切换该任务的并行并保存（`toggle_parallel` 仿照 `toggle` 就地刷新按钮配色与状态行，不重建列表；运行期间随其它控件一起禁用）；状态行文字抽成 `_card_status` 供卡片与开关复用
- 主页卡片状态行追加「· ⇉ 并行」标记
- `_apply_run_event`：并行 task_started／task_finished 维护 `run_state["parallel_names"]`（不推进进度条），并行结果同样写入 `_run_tasks`（md 日志摘要）；`queue_finished` 时进度条走满
- `_update_global_run_bar`：运行中 detail 追加「· ⇉ 并行：任务名」；文案「串行任务未运行」等微调为「任务未运行」

### 3. preset_catalog.py / presets/catalog.json / preflight.py

- `build_plugin` 新增 `"parallel": bool(script.get("parallel_default", False))`；catalog 中仅 `maa_gui` 加 `"parallel_default": true`
- `check_plugins`：勾了并行的任务 ≥2 个时输出一条 warn（确认互不抢鼠标、不共用同一个模拟器）；仅 1 个时不提醒

### 4. 测试与文档

- 新增 `tests/test_runner_parallel.py`（13 项）：分区顺序、并行+串行都执行且汇总含两者、并行日志带名字前缀、坏路径跳过、预先停止不启动任何进程、纯并行队列、全串行回归、DailyDoneState 8 线程并发写盘
- `test_preset_catalog.py` 补 parallel 字段用例；`test_preflight.py` 补并行提醒用例；全套 111 项通过
- AI_HANDOFF.md、使用说明.txt 补「并行运行」说明

---

## 2026-09-12 · 同服务器日重复运行不再误报「每日未完成」

背景：所有适配游戏的每日奖励都在**凌晨 4 点**重置。同一天里白天跑成功一次、晚上再跑第二次时，脚本检测不到可领取内容会输出「未领取/未检测到」，助手按关键词判定把第二次运行判成 **❌ 未完成** 并红色报警——实际每日早已完成，属于系统性误报（日志分析中 09-05 凌晨连续 3 次重跑失败同属 4 点重置前运行导致）。

方案：引入「服务器日」概念（`runner_core.server_day`，以 04:00 为界），持久化每个游戏最近一次判定「已完成」的时间。

### 1. runner_core.py

- 新增常量 `DAILY_RESET_HOUR = 4`、纯函数 `server_day(dt)`（4 点前属上一个服务器日）与 `resolve_daily_repeat(status, last_done, now)`（同服务器日内已完成过 → `incomplete` 降级为 `completed`）
- 新增 `DailyDoneState`：JSON 持久化（跨重启），原子写（tmp + os.replace），损坏文件回退为空；`Runner.__init__` 新增 `daily_state_file` 参数，不传则仅内存（测试用）
- `_report_task_result` 判定后调用 `_apply_daily_repeat`：
  - 判定「已完成」→ 记录完成时间到状态文件
  - 判定「未完成」但本服务器日已完成过 → 降级为「已完成」，红色 `❌ [每日未完成]` 区块改用 `ℹ️ [当日已完成] 今天 04:00 重置后已成功完成过每日…不计为未完成` 说明（证据行保留，仅换措辞与颜色）
  - 其他游戏/新服务器日不受影响，照常报警

### 2. 游戏助手.pyw / log_saver.py —— 修正 md 日志摘要的标记来源

- 修复现存问题：md 摘要的 ✅/❌ 此前取自 `result`（脚本是否跑完），导致「脚本正常跑完但每日未完成」的日子（如 09-06，实际 2 个未完成）摘要里显示全部 ✅、完成数虚高。现改为脚本正常结束时取 `task_status`（关键词判定），跳过/失败/停止仍按原 `result` 显示
- `_TASK_MARKS` 补充 `incomplete → ❌`、`unknown → ⚠️`
- 新增运行时状态文件 `daily_state.json`（exe 同目录，与 settings.json 同级），已加入 .gitignore

### 3. 测试

- 新增 `tests/test_daily_repeat.py`（服务器日边界 03:59/04:00、跨零点仍同日、次日 04:01 恢复报警、无记录不降级、状态文件往返/损坏回退）
- `tests/test_runner_skip.py` 新增同日降级与其他游戏不降级两个用例；原状态透传用例改用独立 Runner 隔离内存状态
- 全套 98 项测试通过

---

## 2026-09-12 · 界面修复：侧栏文字裁剪 + 流畅度优化

背景：用户反馈两问题——① 高分屏（125%/150% 缩放）或调大应用字号后，左侧导航栏文字（「一键长草」「使用帮助」等）右侧被截断；② 运行刷日志、拖动卡片排序、拉伸窗口时界面卡顿不丝滑。

根因：侧栏 `width=212` 固定像素 + `pack_propagate(False)`，而字体随 DPI（tk scaling）和字号档位（0.9~1.3）放大，像素容器不跟着涨，超出即被像素级裁剪。

### 1. 文字裁剪修复（游戏助手.pyw）

- 新增 `_sidebar_width()`：按当前字体实测侧栏最宽内容（导航项加粗态 / logo「一键长草」/「● 管理员模式」）+ 内边距，`max(212, 实测)` 作为侧栏宽度；字号/主题切换走 `_rebuild_all` 重建时自动重算
- "SERIAL RUNNER" 副标题写死的 `("Consolas", 8)` 改为随字号档位缩放
- 新增 `_px(v)`：按 96 DPI 设计的固定像素 × 字号档位 × DPI/96 换算；应用于全局运行条高度 72、开始/结束按钮槽 148×50、进度条 pady、`minsize(940,660)`

### 2. 流畅度优化（游戏助手.pyw）

- 日志刷屏（运行时卡顿主因）：`_drain_log` 积压时轮询间隔 16ms → 33ms（约 30 次/秒），单次行数上限 500 → 1000 补偿吞吐；行数标签至多每 200ms 刷新一次（新增 `_flush_log_count`）；「跟随最新」按钮仅在文字变化时 config
- 拖动排序：`_move_card_drag` 只在目标位变化时更新两张卡的高亮（原先每像素移动全量刷所有卡片边框）；`_finish_card_drag` 只保存 order 实际变化的插件 JSON
- 拉伸窗口：`_on_list_canvas_configure` 合并同帧多次触发（after_idle 去抖），`_do_sync_card_wraplength` 宽度变化 <8px 跳过；`_render_cards` 重建时重置宽度标记保证首轮省略号同步执行
- 新增 `_path_exists()`：3 秒 TTL 缓存的存在性探测，替代 `_card` / `_refresh_home_status` 里每次勾选/刷新都读盘的 `os.path.exists/isfile`

验证：`python -m py_compile` 通过；`run_tests.py` 86 项测试全过。

---

## 2026-08-13 · 任务完成状态明确化（已完成 / 未完成）

背景：串行运行每个游戏时，旧逻辑只逐条打印「每日完成 / 每日未完成 / 体力」的匹配行；没匹配到就打印「未捕捉到相关记录」。这会导致脚本明明已完成，仍同时出现红色未完成噪音，用户无法一眼判断这个游戏到底跑完没有。

备份：改动前原始文件已复制到 `backup\backup-2026-08-13-before-task-status\`。

### 1. log_watcher.py —— 输出明确任务结论

- 新增常量 `TASK_COMPLETED / TASK_INCOMPLETE / TASK_UNKNOWN`
- 新增纯函数 `resolve_task_status(done_lines, pending_lines, done_configured, pending_configured)`：
  - 完成关键词命中 → **已完成**（即使同时命中失败关键词；崩铁完成后会补打「未检测到奖励」，属正常）
  - 配了完成关键词但没命中 → **未完成**
  - 只配了失败关键词（MaaEnd / OneDragon）且命中失败行 → **未完成**；没有失败行 → **已完成**
  - 两类关键词都没配 → unknown
- `finish()` 返回新增 `task_status` 字段

### 2. runner_core.py —— 每局结束输出一句明确结论

- `_report_task_result` 重写：
  - 只输出**实际匹配到**的证据行，不再给未命中分类打印「未捕捉到相关记录」
  - 返回任务状态；未配置完成/失败关键词时返回 unknown
- 新增 `_log_task_final`，每个游戏跑完后输出：
  - `[任务完成] 游戏名 · 已完成`（绿色）
  - `[任务未完成] 游戏名 · 未完成`（红色）
  - 无法判断时输出黄色提示，绝不假装完成
- `game` 模式下若超时未检测到游戏进程，且日志也无法给出结论，直接记**未完成**
  - 队列跑完后，如果有任务未完成，总结行会显示「串行队列执行完毕：有 N 个游戏任务未完成」
  - 修复打包问题：`_report_task_result_legacy` 尾部缩进错误会让 PyInstaller 把 `runner_core` 标记为 invalid module，导致 exe 运行时 `ModuleNotFoundError: runner_core`；已恢复为原始缩进
  - `build_exe.bat` 增加打包前 `py_compile` 语法检查，避免以后再出现「PyInstaller 静默跳过坏模块、exe 启动才报 ModuleNotFoundError」
  - 修复 `_log_task_final` 输出 `%s` 未格式化的 bug（运行日志里出现字面量 `%s`）
  - `plugins/1_绝区零.json`：OneDragon 实际日志为 `.log\log.txt`（旧配置 `*.log` 永远匹配不到），已修正并新增完成关键词「日常奖励领取成功 / 全部结束」
  - `plugins/5_明日方舟终末地.json`：新增完成关键词「收尾任务已提交」，编码改为 auto；任务正常收尾时能显示证据而不再空结果
  - 崩铁「完成后复查出未检测到奖励」不再用红色 `❌ [每日未完成]` 显示，改为黄色 `ℹ️ [复查记录]`，避免出现“既完成又未完成”的视觉矛盾
  - 队列结束前新增蓝色星形分割线「每日奖励完成情况汇总」：每行显示 ✅ 已完成 / ❌ 未完成 / ⚠ 未能确认，并统计「完成 N 个，未完成 N 个」
    - 修正 `task_finished` 事件中的 `task_status`：跳过/失败等没有 `_last_task_status` 的情况也正确上报 `incomplete`
    - 重新打包 `dist\一键长草助手.exe` 并覆盖根目录 `一键长草助手.exe`，确保这些修复在实际双击运行时生效






  - 旧的 `_report_task_result_legacy` 保留在文件中仅供对照，不再被运行路径调用

### 3. 测试

- `tests/test_log_watcher.py` 新增 6 个 `resolve_task_status` 用例，并断言崩铁「同时命中金+红」判已完成
- `tests/test_runner_skip.py` 新增任务状态返回、空分类噪音移除、最终结论日志 3 个用例


## 2026-08-13 · 日志自动保存（md）+ 导入查看

背景：用户希望运行日志自动保存为 markdown，可设置保留时长（一周/一个月/不清理），并能在软件里导入查看。四个设计点均按用户确认的推荐项实施。

### 1. 新模块 log_saver.py（与界面解耦的纯逻辑）

- **每天一个 md**：`logs\YYYY-MM-DD.md`，文件头 `# 运行日志 · 日期`
- **多次运行隔离**：每条记录以 `## 运行记录 · 第 N 次 · HH:MM:SS → HH:MM:SS · 结果` 开头，记录之间用 `---` 分割线隔开
- **记录内容**：`### 摘要`（共 N 个游戏/完成数 + ✅⏭❌⏹ 逐游戏结果）+ `### 日志`（```text 代码块，保留界面显示顺序）
- **保留策略**：`week/month/forever` → 7 天/30 天/不清理；`cleanup_old_logs` 只删除 `YYYY-MM-DD.md` 命名文件（按文件名日期判断），用户手动放的文件一律不碰

### 2. 界面（游戏助手.pyw）

- 每次运行结束（含手动停止）自动保存：`_save_run_log` 汇总摘要 + 全文追加到今天的 md，保存后日志面板提示「日志已自动保存：…（今天第 N 次运行）」
- 启动时与每次保存后按设置清理过期文件
- **设置页**新增「日志自动保存」区：保留最近一周 / 最近一个月 / 不清理 单选（立即生效），+「打开日志目录」按钮
- **日志面板**新增「导入」按钮：选择 md/txt/log，在**独立只读窗口**查看（保留按级别着色，utf-8/gbk 自适应解码），可复制全部；另新增「目录」按钮直达日志文件夹
- `_log_tag_for` 增加 md 标题着色（`#`/`##`/`###` 与 ``` 围栏 → 主题绿），导入查看更易读
- HELP_TEXT 补充说明；`.gitignore` 增加 `logs/`（运行时数据不入库）

### 3. 测试

- 新增 `tests/test_log_saver.py` 6 个：保留策略映射、md 结构（标题/摘要/代码块/结束符）、追加建文件+分割线+编号、清理只删过期日期文件且不碰用户文件、forever 不清理、目录不存在安全返回
- 全量 75 个通过（原 69 + 新 6）

### 附加修复（随本提交）

- `log_watcher.py` 轮转检测从「创建时间戳」改为 **Windows 文件身份**（`GetFileInformationByHandle` 卷序列号+文件索引）：替换日志时身份必然变化，不再受 NTFS 时间戳精度影响（旧实现同一时间片内快速轮转会漏判，测试间歇性失败）

### 遗留/注意

- 清理按**文件名日期**判断（不是修改时间），所以别手动把非 `YYYY-MM-DD.md` 命名的文件放进 logs 目录
- 保存失败不影响运行：`_save_run_log` 捕获异常并输出一条 error 日志

---

## 2026-08-13 · 日志子系统改进（结构化级别 + 增量读取健壮性）

背景：用户对日志部分不满意，审查后发现增量读取存在跨 poll 截断/漏读等正确性问题，且界面着色依赖日志文字里的魔法标记。备份标签 `backup-2026-08-13-before-log-improvements`。

### 1. log_watcher.py —— 增量读取健壮性

- **跨 poll 截断修复**：新增 `_decode_incremental` 字节级增量解码——多字节字符（GBK/UTF-8）恰好被 chunk 边界截断时不再出乱码，截断的尾部字节留到下次拼接
- **半行缓存**：无换行结尾的未写完行缓存到 `_partial`，与下一块拼成完整行再分类 → 一行分多次写入（如「每日实训」+「已完成」）不再漏报/误报
- **流结束冲刷**：`finish()` 处理残留（未完成多字节尾部 + 未换行的最后一行），最后一截日志不丢
- **轮转检测增强**：记录 Windows 文件创建时间（`st_ctime_ns`），日志被替换成「更大的新文件」也能从头重读（旧逻辑只认 size<offset，会漏掉新文件开头）
- **结果上限**：每类最多保留最新 `max_per_category=20` 条，`finish()` 返回 `truncated` 标记是否截断

### 2. runner_core.py —— 结构化日志级别

- 新增级别常量 `LEVEL_INFO/WARN/ERROR/OK/GOLD/BLUE`；`_tlog`/`_log` 携带 level，通过 `inspect.signature` 探测兼容只接受 msg 的旧回调（如测试里的 `list.append`）
- `_report_task_result`：
  - 只输出**配置了提取关键词**的分类（原神只配了「每日完成」就不再打两行「未捕捉到」噪音）；完全没配关键词时不输出结果区
  - 输出前等待 `settle_sec=1s`（可被停止打断，`Runner(settle_sec=…)` 可调）并**强制 poll 一次**，避免最后一截日志漏读
  - 截断时输出「（匹配行过多，仅显示最新 N 条）」
- 等待循环（`_wait_until_any_appear`/`_wait_until_all_gone`）即使进程列表为空也至少 tick 一次 → 修复某些插件配置下日志从未被读取的问题

### 3. 界面（游戏助手.pyw / ui_helpers.py）

- 日志队列条目携带结构化 level；`_log_tag_for` 优先按 level 着色，旧的关键字匹配保留为兜底（对外层无 level 的日志不失效）
- `LogStore` 改存 `(text, level)` 元组（`append_many` 兼容纯字符串）；`group_tagged_lines` 支持带 level 的行
- 金/蓝两色随主题：`THEMES` 新增 `log_gold`/`log_blue`（「极简」浅色主题用深金 `#8a6d00`/深蓝 `#0066cc`，不再刺眼）

### 4. 测试

- 新增 12 个：半行截断、UTF-8/GBK 多字节截断、轮转为更大新文件、每类上限+truncated、只输出已配置分类、无关键词不输出、最终 poll、level 传递、旧回调兼容、LogStore 元组/分组带 level
- 全量 69 个通过（原 57 + 新 12）

### 遗留/注意

- `finish()` 是流结束时的最终调用：中途调用会冲刷半行缓存，测试中两次 poll 之间不要调它
- 展示文本（`🎁 [每日完成]` 等）保持不变，只是颜色来源从「文字匹配」改为「结构化级别」

---

## 2026-08-03 · MaaEnd 接入 + 任务结果日志提取（本次会话）

背景：用户新增「明日方舟：终末地 · MaaEnd」，MaaEnd 自身启动游戏有 bug，且用户需要从脚本日志中快速判断每日奖励是否领取、体力剩余多少。

### 1. 前置程序功能（pre_launcher）

- **字段**（插件 JSON / catalog script 均可）：`pre_launcher`、`pre_args`、`pre_delay_sec`（秒）、`pre_launch_method`（`explorer` 默认 / `direct`）
- **行为**（`runner_core.py`）：启动主脚本前先启动前置程序 → 等 `pre_delay_sec` 秒让游戏就绪 → 再启动主脚本；`_sleep_interruptible` 支持停止按钮打断
- **helper 模式兜底**：`wait_mode="helper"` 等助手退出后，若 `game_processes` 仍在运行则自动 taskkill 关闭（脚本没关游戏时兜底）
- UI：编辑页「高级选项」新增前置程序三字段（含浏览按钮）；quick_fill 支持 `前置程序/前置参数/前置等待`
- 插件 `5_明日方舟终末地.json`：pre_launcher 指向 `E:\open\Hypergryph Launcher\games\Arknights Endfield\Endfield.exe`，pre_delay_sec=30
- catalog.json 新增 `endfield` 游戏 + `maaend_gui` 预设（`build_plugin` 会透传 pre_* 字段）

### 2. explorer 代理启动（绕过 ACE 反作弊）

- **原因**：通过助手 Popen 直接启动 Endfield.exe 时，ACE 反作弊（游戏目录 `AntiCheatExpert/ACE-BASE.sys` 等内核驱动）报 `警告(3,1051,150005) 检测到系统环境存在异常`；手动双击正常
- **方案**：`build_pre_cmd`（runner_core.py）—— 无参数时默认 `explorer.exe <目标exe>` 代理启动：普通权限、父进程为 explorer，与手动双击完全一致
- **注意**：explorer 无法转发参数，带 `pre_args` 或 `pre_launch_method="direct"` 时回退直接 Popen
- 日志输出「已通过 explorer 代理启动（普通权限，同手动双击）」

### 3. 脚本日志监控模块（新独立文件 `log_watcher.py`）

- **定位**：与执行引擎解耦的独立模块，含 `ScriptLogWatcher` 类 + `resolve_log_file`（支持 glob 通配取最新）
- **增量读取**：`start()` 记录文件 offset → 等待期间 `poll()` 只读新增字节（GBK/UTF-8 自动解码，utf-8 优先）→ `finish()` 返回提取结果
- **日志轮转**：文件被替换/清空（size < offset 或换文件）自动从头重读（覆盖 MAA asst.log、MaaEnd 按天滚动、OneDragon log.txt 轮转）
- **三类语义提取**（取代旧的通用 done/fail + tail 原文方案，不再输出原始日志）：
  - `daily_done_patterns` → 每日奖励已完成（金色 `#ffd700`）
  - `daily_pending_patterns` → 未完成/未领取（红色，复用 `log_err`）
  - `stamina_patterns` → 体力/理智，**只保留最新一条**（蓝色 `#4da6ff`）
- 优先级：体力 > 未完成 > 完成（同行进多类时按此归类）
- 无效正则自动降级为字面量匹配

### 4. runner_core.py 集成点

- `_start_log_watcher(p)`：配了 `log_file` 才启用（未配置行为与旧版完全一致，向后兼容）
- `_report_task_result(p, watcher)`：脚本退出后输出
  ```
  ──────── 任务结果 · <名称> ────────
    🎁 [每日完成] 每日奖励 · 已完成：    ← 金色
    ❌ [每日未完成] 每日奖励 · 未完成/未领取： ← 红色
    ⚡ [体力] 剩余体力/理智：           ← 蓝色
  ```
- `_wait_until_any_appear` / `_wait_until_all_gone` 增加 `on_tick` 回调参数（等待循环内周期 poll）

### 5. 各插件日志配置（plugins/*.json 实测关键词）

| 插件 | log_file | 每日完成(金) | 每日未完成(红) | 体力(蓝) |
|---|---|---|---|---|
| 原神 BetterGI | `log\better-genshin-impact*.log` | `今日奖励已领取` | `未领取, 手动检查` | （无日志，显示未捕捉到） |
| 崩铁 March7th | `logs\*.log` | `每日实训已完成` | `未检测到每日实训奖励` | `开拓力` |
| 方舟 MAA | `debug\asst.log`（36MB，增量读） | `TaskChainCompleted.*"taskchain":"Award"` | `SubTaskError.*"taskchain":"Award"` | `Current Sanity: \d+` |
| 终末地 MaaEnd | `debug\20*.log` | （无） | `任务启动异常` | （无） |
| 绝区零 OneDragon | `.log\*.log` | （无） | `执行失败` | （无） |

> MaaEnd / OneDragon 的日志本身不写奖励/体力信息 → 显示「未捕捉到相关记录」，属脚本限制。
> 崩铁可能同时命中金+红：脚本行为是完成后再次检测奖励显示「未检测到」，非误报。

### 6. UI / quick_fill / 测试

- 编辑页高级选项：日志文件（浏览）、编码（auto/gbk/utf-8）、每日完成/每日未完成/体力三类关键词输入框
- quick_fill 键：`日志文件 / 日志编码 / 每日完成 / 每日未完成 / 体力关键词`
- 日志着色：`_log_tag_for` 识别 `[每日完成]`→gold、`[每日未完成]`→err、`[体力]`→blue（tag 硬编码色，不随主题）
- 测试：`tests/test_log_watcher.py`（增量/轮转/GBK/UTF-8/正则兜底/JSON 正则/体力只留最新），全量 57 个通过
- 打包：`python -m PyInstaller --noconfirm --clean 一键长草助手.spec` → 复制到 `一键长草助手.exe`（打包前须关闭运行中的 exe，否则复制失败）

### 遗留/注意

- 编辑页保存会自动移除旧字段 `done_patterns`/`fail_patterns`/`tail_lines`（已被三类语义字段取代）
- MaaEnd「任务启动异常」配置在 daily_pending；MAA 的 SubTaskError 噪音多，只匹配 Award 任务链
