# CHANGELOG · 修改记录

> 面向后续接手的 AI / 开发者。每次改动后追加一节,便于快速定位"这个功能是为什么加的、怎么改的"。
> 涉及原理与结构速览见 `AI_HANDOFF.md`。

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
