# CHANGELOG · 修改记录

> 面向后续接手的 AI / 开发者。每次改动后追加一节,便于快速定位"这个功能是为什么加的、怎么改的"。
> 涉及原理与结构速览见 `AI_HANDOFF.md`。

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
