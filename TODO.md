# 游戏串行一键长草 · 助手 — 说明与待办

> 本文档介绍当前助手的功能与架构，列出易用性改进建议，并详细规划「主流游戏/脚本预设下拉」功能，目标：**让不会操作电脑的新手也能完成配置并正常使用**。

---

## 一、当前助手是什么？

### 1.1 解决什么问题？

在 **3060 + 16G 内存** 这类配置下，**无法同时运行多个 3A/二次元客户端**。本助手把多个游戏的自动脚本 **排队串行执行**：

1. 启动第一个游戏的辅助工具 → 自动跑日常 → 游戏关闭  
2. 自动启动第二个 → …  
3. 全部完成后结束  

用户只需 **勾选要跑的游戏 + 点「开始运行」**，不必手动关游戏、开下一个脚本。

### 1.2 目录结构

```
E:\Games\py\
├── 启动助手.vbs          ← 推荐入口：无黑终端、pythonw 静默启动、UAC 提权
├── 启动助手.bat          ← 旧入口（会闪 cmd，可弃用）
├── 一键长草.bat          ← 命令行版（四游戏串行，无 GUI）
└── 游戏助手\
    ├── 游戏助手.pyw      ← 图形界面主程序（tkinter）
    ├── runner_core.py    ← 串行执行引擎（与 UI 解耦）
    ├── settings.json     ← 用户偏好：主题、字体、字号
    ├── TODO.md           ← 本文件
    └── plugins\          ← 每个游戏一个 JSON「插件」
        ├── 1_绝区零.json
        ├── 2_原神.json
        ├── 3_崩坏星穹铁道.json
        └── 4_明日方舟.json
```

### 1.3 核心概念：插件（Plugin）

每个 `plugins/*.json` 描述 **一个游戏 + 一套脚本** 如何被串行调度，字段含义：

| 字段 | 含义 | 示例 |
|------|------|------|
| `id` | 内部标识 | `genshin` |
| `name` | 界面显示名 | `原神 · BetterGI` |
| `launcher` | 脚本/启动器 `.exe` 完整路径 | `E:\Games\py\BetterGI\BetterGI.exe` |
| `args` | 命令行参数 | `["startOneDragon"]` |
| `wait_mode` | 完成判定方式 | `game` 或 `helper` |
| `game_processes` | 游戏进程名列表 | `["YuanShen.exe", "GenshinImpact.exe"]` |
| `helper_processes` | 助手进程名（跑完后可强制结束） | `["BetterGI.exe"]` |
| `start_timeout_min` | 等待游戏启动的最长时间（分钟） | `15` |
| `enabled` | 是否参与本次串行 | `true` |
| `order` | 执行顺序（1 最先） | `2` |
| `notes` | 备注（需用户在脚本里额外设置的项） | 见各插件 |

**等待模式说明：**

- **`game`**：先等 `game_processes` 里任一进程出现 → 再等全部消失（认为脚本已关游戏）→ 再 `taskkill` 助手进程。适用于绝区零、原神、崩铁。
- **`helper`**：只等 `helper_processes` 自己退出。适用于 MAA（游戏在 MuMu 模拟器内，MAA 已配置跑完自关）。

### 1.4 执行引擎（runner_core.py）

- 按 `order` 排序，只跑 `enabled=true` 的插件。  
- 启动：`subprocess.Popen([launcher] + args)`。  
- 进程检测：`tasklist`（已隐藏黑窗口，不干扰游戏脚本）。  
- 支持 `stop_event` 中止、带时间戳的日志回调。  
- 与 UI 完全解耦，便于以后做 CLI / 托盘版。

### 1.5 图形界面（游戏助手.pyw）

| 能力 | 说明 |
|------|------|
| 主页 | 游戏卡片列表：开/关、排序、编辑、删除；实时日志；开始/停止 |
| 编辑 | 单页表单，字段较多（见下文「痛点」） |
| 设置 | 主题（橙黑/绝区零/英伦/极简）、字体、字号；DWM 染色系统标题栏 |
| 帮助 | 内置图文说明 |
| 持久化 | 勾选与顺序写在插件 JSON；主题写在 `settings.json` |

**启动方式：** 双击 `启动助手.vbs` → `pythonw` 无终端 → UAC 管理员（部分脚本需要）。

### 1.6 当前已内置的四个插件

| 游戏 | 脚本 | 启动方式 | 关游戏 |
|------|------|----------|--------|
| 绝区零 | OneDragon | `-o --close-game` | 参数自带 |
| 原神 | BetterGI | `startOneDragon` | 需在 BetterGI 设「一条龙结束后关闭游戏」 |
| 崩铁 | March7th | `main -e` | `config.yaml` 中 `after_finish: Exit` |
| 明日方舟 | MAA | 无参启动 | MAA 内「完成后退出模拟器+MAA」等 |

---

## 二、当前痛点（为什么新手难用）

1. **添加/编辑字段太多**  
   显示名称、启动器路径、启动参数、完成判定方式、游戏进程名、助手进程名、超时、备注——共 8 项，小白不知道 `YuanShen.exe` 是什么、更不知道 `wait_mode` 选哪个。

2. **路径需手动浏览**  
   虽然有点「浏览…」，但不知道选哪个 exe（是 `BetterGI.exe` 还是游戏本体）。

3. **脚本侧还要额外配置**  
   助手只负责「排队启动」；关游戏、日常任务内容仍在各脚本 GUI/配置文件里，帮助文档分散。

4. **无「首次使用向导」**  
   没有一步步检测：Python、管理员、路径是否存在、脚本是否已设「完成后关游戏」。

5. **无运行前自检**  
   点运行才发现路径无效或游戏已在跑。

6. **预设与扩展**  
   新增第五个游戏要从零填 JSON 字段，没有「选原神就自动填好」的模板。

---

## 三、改进建议（优先级）

### P0 — 必须做（新手能否上手）

| 编号 | 建议 | 说明 |
|------|------|------|
| P0-1 | **游戏/脚本预设下拉（见第四节）** | 选「原神 · BetterGI」自动填进程名、参数、等待模式 |
| P0-2 | **添加向导：简单模式 / 高级模式** | 简单模式只显示：选预设 → 选路径 → 完成；高级模式才展开全部字段 |
| P0-3 | **运行前自检面板** | 开始运行前弹层或主页顶部：路径 ✓/✗、是否管理员、是否有游戏进程占用 |
| P0-4 | **首次启动向导（3 步）** | ① 欢迎 ② 检测管理员 ③ 确认四个预设是否已安装 |

### P1 — 强烈建议

| 编号 | 建议 | 说明 |
|------|------|------|
| P1-1 | **常见安装路径自动探测** | 选预设后扫描 `E:\Games\`、`D:\`、`miHoYo Launcher\` 等，路径下拉「已找到 / 未找到请浏览」 |
| P1-2 | **脚本配置检查清单** | 每个预设卡片显示「还需在脚本里完成：…」+ 一键打开配置文件或脚本目录 |
| P1-3 | **运行结束通知** | 可选：全部完成播放提示音 / 托盘气泡 / 关显示器（不默认关机） |
| P1-4 | **桌面快捷方式生成器** | 一键在桌面创建「启动助手.vbs」快捷方式 |

### P2 — 体验增强

| 编号 | 建议 | 说明 |
|------|------|------|
| P2-1 | 定时启动（Windows 任务计划程序向导） | 每天 4:00 自动跑 |
| P2-2 | 上次运行摘要 | 主页显示「上次：绝区零 52 分钟，原神跳过（路径无效）」 |
| P2-3 | 插件市场 / 导入导出 | 分享 `plugins/xxx.json` 或从 URL 导入社区模板 |
| P2-4 | 日志导出 | 运行日志保存为 `logs/YYYY-MM-DD.txt` |

---

## 四、重点功能设计：主流游戏 / 脚本预设下拉

> **目标：** 添加任务时，新手只需 **选游戏 → 选脚本 → 确认路径**，其余字段由预设自动填充；高级用户仍可改「高级选项」。

### 4.1 交互流程（简单模式）

```
[＋ 添加游戏]
      │
      ▼
┌─────────────────────────────────────┐
│  选择游戏                            │
│  ┌───────────────────────────────┐  │
│  │ 原神                      ▼   │  │  ← 一级下拉：游戏
│  └───────────────────────────────┘  │
│  ┌───────────────────────────────┐  │
│  │ BetterGI（一条龙）          ▼   │  │  ← 二级下拉：该游戏常用脚本
│  └───────────────────────────────┘  │
│                                     │
│  脚本位置：                          │
│  ○ 已自动找到：E:\Games\py\BetterGI\BetterGI.exe  │
│  ○ 未找到，[浏览…] 选择 BetterGI.exe                │
│                                     │
│  [ ] 我已在 BetterGI 里设好「完成后关闭游戏」       │  ← 勾选才能保存（或仅警告）
│                                     │
│  [ 取消 ]              [ 添加并返回主页 ]          │
└─────────────────────────────────────┘
```

**高级模式**（折叠区「展开高级选项」）：与当前编辑页相同，可改进程名、参数、`wait_mode` 等。

### 4.2 预设数据文件：`presets/catalog.json`

建议新建 `游戏助手/presets/catalog.json`，与 `plugins/` 分离：**预设是模板，plugins 是用户实例**。

```json
{
  "version": 1,
  "games": [
    {
      "id": "genshin",
      "name": "原神",
      "icon": "genshin",
      "game_processes": ["YuanShen.exe", "GenshinImpact.exe"],
      "scripts": [
        {
          "id": "bettergi_onedragon",
          "name": "BetterGI · 一条龙",
          "launcher_globs": [
            "**/BetterGI/BetterGI.exe",
            "**/BetterGI.exe"
          ],
          "launcher_hints": [
            "E:\\Games\\py\\BetterGI\\BetterGI.exe",
            "C:\\BetterGI\\BetterGI.exe"
          ],
          "args": ["startOneDragon"],
          "wait_mode": "game",
          "helper_processes": ["BetterGI.exe"],
          "start_timeout_min": 15,
          "setup_checklist": [
            "在 BetterGI：设置 → 一条龙 → 结束后操作 → 关闭游戏",
            "在 BetterGI：一条龙任务勾选你需要的日常（合成树脂、秘境等）"
          ],
          "notes": "命令行 startOneDragon；需脚本内开启完成后关游戏。"
        }
      ]
    },
    {
      "id": "hsr",
      "name": "崩坏：星穹铁道",
      "game_processes": ["StarRail.exe"],
      "scripts": [
        {
          "id": "m7a_main",
          "name": "March7th · 完整运行",
          "launcher_globs": ["**/March7th Launcher.exe", "**/March7thAssistant*/March7th Launcher.exe"],
          "args": ["main", "-e"],
          "wait_mode": "game",
          "helper_processes": ["March7th Launcher.exe", "March7th Assistant.exe"],
          "setup_checklist": [
            "config.yaml：after_finish: Exit",
            "config.yaml：pause_after_success: false"
          ]
        }
      ]
    },
    {
      "id": "zzz",
      "name": "绝区零",
      "game_processes": ["ZenlessZoneZero.exe"],
      "scripts": [
        {
          "id": "onedragon",
          "name": "OneDragon · 一条龙",
          "launcher_globs": ["**/OneDragon-Launcher.exe", "**/zzz/OneDragon-Launcher.exe"],
          "args": ["-o", "--close-game"],
          "wait_mode": "game",
          "helper_processes": ["OneDragon-Launcher.exe"],
          "setup_checklist": ["在 OneDragon 界面勾选需要的一条龙应用"]
        }
      ]
    },
    {
      "id": "arknights",
      "name": "明日方舟",
      "game_processes": [],
      "scripts": [
        {
          "id": "maa_gui",
          "name": "MAA · 一键长草（MuMu/ADB）",
          "launcher_globs": ["**/MAA.exe", "**/MAA-v*/MAA.exe"],
          "args": [],
          "wait_mode": "helper",
          "helper_processes": ["MAA.exe"],
          "setup_checklist": [
            "MAA：启动后自动开始任务",
            "MAA：启动后自动开模拟器",
            "MAA：完成后退出模拟器 + 退出 MAA"
          ],
          "notes": "游戏在模拟器内，不监控 StarRail/Arknights 进程。"
        }
      ]
    },
    {
      "id": "wuwa",
      "name": "鸣潮",
      "game_processes": ["Wuthering Waves.exe", "Client-Win64-Shipping.exe"],
      "scripts": [
        {
          "id": "placeholder",
          "name": "（预留）社区脚本",
          "launcher_globs": [],
          "args": [],
          "wait_mode": "game",
          "helper_processes": [],
          "setup_checklist": ["待补充常用鸣潮助手预设"]
        }
      ]
    },
    {
      "id": "custom",
      "name": "其他 / 自定义",
      "game_processes": [],
      "scripts": [
        {
          "id": "manual",
          "name": "手动填写全部项",
          "launcher_globs": [],
          "args": [],
          "wait_mode": "game",
          "helper_processes": [],
          "setup_checklist": ["适合非列表内游戏，进入高级模式填写"]
        }
      ]
    }
  ]
}
```

**下拉展示文案示例（UI 层拼接，不必写进 JSON）：**

| 下拉层级 | 展示文本 |
|----------|----------|
| 游戏 | `原神` |
| 脚本 | `BetterGI · 一条龙` |
| 进程（只读预览，给进阶用户） | `YuanShen.exe（国服）/ GenshinImpact.exe（国际服）` |

若需要「进程也下拉」，可做第三级 **可选** 下拉：仅当该游戏存在多服/多进程时显示，例如原神选「国服 YuanShen.exe」或「国际服 GenshinImpact.exe」，写入 `game_processes` 为单元素数组。

### 4.3 路径自动探测逻辑

新增 `preset_resolver.py`（建议）：

1. 读取 `catalog.json` 中当前脚本的 `launcher_hints`（固定常见路径，优先匹配用户机器上的 `E:\Games\py\...`）。  
2. 对 `launcher_globs` 在用户选定的盘符（默认 `E:\`、`D:\`、脚本所在盘）做有限深度 glob（最多 4 层，避免全盘扫描卡死）。  
3. 命中多个时：弹小列表让用户选；命中 0 个：只显示「浏览…」。  
4. 结果缓存到 `settings.json` 的 `path_cache`：`{"bettergi_onedragon": "E:\\..."}`，下次秒开。

### 4.4 与现有插件 JSON 的映射

用户点「添加并返回」时，由预设生成标准 plugin 文件：

```python
plugin = {
    "id": preset_game_id + "_" + preset_script_id,  # 或 uuid 短码
    "name": f"{game_name} · {script_name}",
    "launcher": resolved_path,
    "args": preset["args"],
    "wait_mode": preset["wait_mode"],
    "game_processes": preset.get("game_processes") or game["game_processes"],
    "helper_processes": preset["helper_processes"],
    "start_timeout_min": preset.get("start_timeout_min", 15),
    "enabled": True,
    "order": next_order,
    "notes": preset.get("notes", ""),
    # 新增可选字段，便于 UI 展示 checklist
    "preset_id": "bettergi_onedragon",
    "setup_checklist": preset.get("setup_checklist", []),
}
```

保存路径：`plugins/{order}_{slug}.json`（与现有一致）。

### 4.5 编辑页改造

- 顶部增加 **「预设：原神 · BetterGI」** 只读标签；点「更换预设」回到简单向导。  
- **默认折叠**：启动参数、进程名、`wait_mode`、超时 → 放进「高级选项」。  
- 主页卡片增加 **「待办：1 项脚本设置未完成」**（根据 checklist 是否勾选「我已完成」或自动检测配置文件关键字——后者可做 P1）。

### 4.6 主流游戏 / 脚本扩展路线图

| 阶段 | 内容 |
|------|------|
| **v1** | 原神 BetterGI、崩铁 March7th、绝区零 OneDragon、明日方舟 MAA（与现网四个插件对齐） |
| **v1.1** | 原神国际服进程、B 服路径差异说明；MAA 官服/B 服 client 备注 |
| **v2** | 鸣潮、碧蓝航线、公主连结等（需社区贡献 preset 条目） |
| **v2** | `presets/community/` 目录，用户丢 json 即出现在下拉里 |

**新增预设的最低信息（给贡献者）：**

- 游戏中文名 + 默认 `game_processes`  
- 脚本显示名 + `launcher` 文件名 + 推荐 `args`  
- `wait_mode` + `helper_processes`  
- 3 条以内 `setup_checklist`  

### 4.7 实现任务拆分（开发 TODO）

- [ ] **T1** 新建 `presets/catalog.json`，录入现有 4 款 + custom  
- [ ] **T2** 实现 `preset_resolver.py`（hints + 有限 glob + cache）  
- [ ] **T3** UI：`AddGameWizard` 简单模式（双下拉 + 路径 + checklist 勾选）  
- [ ] **T4** 编辑页：高级选项折叠 + 显示 preset 标签  
- [ ] **T5** 运行前自检：遍历 enabled 插件，汇总路径与占用进程  
- [ ] **T6** 首次启动：`settings.json` 中 `first_run_done`，未完成则弹 3 步向导  
- [ ] **T7** 文档：帮助页链到各脚本官方教程 URL  

### 4.8 验收标准（新手场景）

1. 从未用过的人，双击 `启动助手.vbs`，3 分钟内能在主页看到 4 个游戏且路径有效。  
2. 添加「原神 · BetterGI」：**零手填进程名/参数**，仅浏览一次 exe（若自动探测失败）。  
3. 帮助/卡片上能看懂「还要去 BetterGI 里勾什么」，而不是只看 `YuanShen.exe`。  
4. 误点「开始运行」时，路径无效的游戏被明确跳过并写在日志里，不 silent fail。

---

## 五、其他技术债（顺手记录）

| 项 | 状态 | 说明 |
|----|------|------|
| tasklist 黑窗 | ✅ 已修 | `CREATE_NO_WINDOW` |
| 列表开关整页刷新 | ✅ 已修 | 就地更新卡片 |
| 编辑保存 | ✅ 已修 | 路径 normpath + 写盘校验 |
| 滚动条样式 | ✅ 已修 | `Vert.TScrollbar` 主题色 |
| 任务栏/最小化 | ✅ 已改 | 原生窗口 + DWM 标题栏染色 |
| 启动闪终端 | ✅ 已改 | 改用 `启动助手.vbs` + pythonw |
| UAC 每次弹出 | 可选优化 | VBS 中 `runas` 改 `open` 可免管理员（部分脚本可能失败） |

---

## 六、推荐阅读顺序（给接手开发的人）

1. 读 `runner_core.py` 理解串行与两种 `wait_mode`  
2. 读 `plugins/*.json` 看真实数据长什么样  
3. 读 `游戏助手.pyw` 中 `build_edit` / `toggle` / `go`  
4. 按 **第四节 T1→T4** 做预设下拉与添加向导  
5. 再做 P0-3 运行前自检  

---

## 七、版本愿景（一句话）

**从「会写 JSON 的极客工具」变成「选游戏、点运行」的挂机助手**——预设下拉是其中最关键的一步。

---

*文档版本：2026-06-18 · 与当前代码库（游戏助手 + 四插件 + VBS 启动）同步*
