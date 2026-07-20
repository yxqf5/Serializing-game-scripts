# AI 交接文档 · 游戏串行一键长草助手

> 本文件的读者:**下一个接手这个项目的 AI 助理**。
> 目标:5 分钟内理解全貌,10 分钟内能安全地加一个新的第三方脚本预设,不破坏已有功能。
>
> 用户是「电脑水平一般 + 想挂机日常」的玩家,不是开发者。**所有 UI 文案都要照顾新手。**

---

## 1. 项目一句话

一个 tkinter 桌面 GUI(单窗口,自绘部分标题栏),把多个游戏的**第三方自动化脚本**排队串行运行:一次只跑一个,跑完关闭后自动启动下一个。**本工具只是调度器,不含脚本本体**——用户要自己去官方页下载脚本。

已适配:BetterGI(原神)、March7th(崩铁)、OneDragon(绝区零)、MAA(明日方舟)、MaaEnd(终末地)、ok-ww(鸣潮)、M9A(重返未来 1999)。

---

## 2. 目录速览(工作目录 `E:\Games\py\游戏助手\`)

```
游戏助手.pyw          单窗口 GUI 主程序(tkinter) —— 唯一入口
runner_core.py        串行执行引擎(subprocess + tasklist 轮询) —— 与 UI 解耦
preset_catalog.py     预设 catalog 加载 / plugin 构造 / 一键导入
preset_resolver.py    启动器路径探测:hints → glob → 缓存
preflight.py          运行前自检:路径 / 管理员 / 进程占用
quick_fill.py         "粘贴 键:值" 快速填充解析
app_paths.py          资源路径 & 数据目录(EXE 打包时区分)
build_exe.bat         PyInstaller 打包脚本
一键长草助手.spec     PyInstaller 规格

presets/
  catalog.json        游戏 & 脚本预设目录(核心数据文件,加新脚本改这里)

plugins/              用户实例 —— 每个游戏一个 JSON,由 catalog + UI 生成
  1_zzz_onedragon.json 等

assets/               图标资源(app.png / app.ico)
tests/                unittest 测试,`python run_tests.py` 跑
settings.json         用户偏好:主题、字体、path_cache、first_run_done
TODO.md               作者原始改进规划(P0/P1/P2 & 预设下拉方案)
使用说明.txt         终端用户 README
DISCLAIMER.md         免责声明
AI_HANDOFF.md         本文件
```

---

## 3. 核心概念

### 3.1 预设(preset)vs 插件(plugin)

| 概念 | 位置 | 是什么 |
|---|---|---|
| 预设 | `presets/catalog.json` | 模板:一个游戏可以配几种脚本,每种脚本的默认参数 |
| 插件 | `plugins/*.json` | 用户实例:某个具体的游戏配置,含实际启动器路径、启用状态、执行顺序 |

**用户看到的卡片 = 插件**。预设不直接展示,只在"添加游戏"向导中作为候选出现。

### 3.2 catalog.json 结构

```json
{
  "version": 1,
  "games": [
    {
      "id": "genshin",
      "name": "原神",
      "game_processes": ["YuanShen.exe", "GenshinImpact.exe"],
      "doc_url": "https://www.bettergi.com/",
      "download_url": "https://github.com/babalae/better-genshin-impact/releases",
      "scripts": [
        {
          "id": "bettergi_onedragon",
          "name": "BetterGI · 一条龙",
          "launcher_filename": "BetterGI.exe",
          "launcher_globs": ["**/BetterGI/BetterGI.exe", "**/BetterGI.exe"],
          "launcher_hints": ["E:\\Games\\py\\BetterGI\\BetterGI.exe"],
          "args": ["startOneDragon"],
          "wait_mode": "game",
          "helper_processes": ["BetterGI.exe"],
          "start_timeout_min": 15,
          "setup_checklist": ["在 BetterGI:设置 → 一条龙 → 结束后操作 → 关闭游戏"],
          "notes": "命令行 startOneDragon"
        }
      ]
    }
  ]
}
```

**特殊 game id `"custom"`** 保留给"其他/自定义"分支,里面只有一个 `manual` script 作为兜底空模板。

### 3.3 wait_mode(完成判定方式)

新手最搞不清的字段,加脚本时**必须想清楚**:

- **`"game"`**:等 `game_processes` 里任一进程出现 → 再等全部消失(认为脚本已关游戏) → 然后 `taskkill` 助手进程。适合原神/崩铁/绝区零/鸣潮这类"脚本会关游戏"的场景。
- **`"helper"`**:只等 `helper_processes` 自己退出。适合 MAA/MaaEnd/M9A 这类"游戏在模拟器里"或"脚本自己会退出"的场景。

判断:**脚本运行时会出现独立的游戏客户端进程吗?**
- 是 → `game`(还要在脚本里勾"完成后关游戏"作为退出信号)
- 否(游戏在模拟器里,或者脚本本身就是任务队列跑完就退)→ `helper`

### 3.4 plugin 生成流程

```
用户点"+ 添加游戏"
  → build_add UI(游戏下拉 + 脚本下拉 + 路径探测)
  → 保存时调用 pc.build_plugin(game, script, launcher_path)
  → 得到 dict,写入 plugins/{order}_{slug}.json
  → save_plugin_file 落盘
  → self.reload() 重新加载卡片
```

`build_plugin` 会把 `preset_id`、`preset_game_id`、`setup_checklist`、`doc_url` 都一并写进 plugin,便于卡片和编辑页展示。

### 3.5 路径探测三层策略(preset_resolver.py)

```
1. cache      settings.json["path_cache"][script_id]
2. hint       catalog 的 launcher_hints 列表(逐个 os.path.isfile)
3. glob       在 default_search_roots(E:\、D:\、BASE_DIR、E:\Games、D:\Games)
              做有限深度 fnmatch(盘符根深度 2,子目录深度 5,10 秒超时)
```

UI 层新版(2026-07):**添加页深度探测调用 `resolve_all_candidates`**,最多返回 8 个候选,≥2 个时在路径输入框下方显示可点击列表。

---

## 4. 主要模块速览

### runner_core.py
串行执行引擎。`Runner(log_callback, stop_event).run_all(plugins)`。
- 用 `subprocess.Popen([launcher] + args)` 启动脚本
- 用 `tasklist /FI "IMAGENAME eq X.exe"` 轮询进程状态(`CREATE_NO_WINDOW`,不弹黑窗)
- 支持 `pre_launcher`(前置程序,如 MaaEnd 需要先启动 Endfield.exe)
- 支持 `stop_event` 中止

### preflight.py
`check_plugins(plugins)` 返回 issue 列表(level: error|warn|info)。
自检项:是否有勾选、是否管理员、路径是否存在、进程是否已在运行。

### quick_fill.py
新手用不上,但对熟练用户是快速填写捷径。解析"键:值"文本,识别中英文别名(比如"启动器"、"launcher"、"路径"都映射到 `launcher` 字段)。

### 游戏助手.pyw
1780+ 行的单文件 App 类。核心方法:
- `build_home` / `build_add` / `build_edit` / `build_first_run` / `build_settings` / `build_help`  各页面构造
- `_render_cards` / `_card`  主页卡片
- `_refresh_home_status`  **主页顶部状态条**(新增,汇总🟢就绪 🟡待办 🔴无效)
- `_add_rescan` / `_add_apply_scan_result` / `_add_pick_candidate`  **路径多候选**(新增)
- `_add_apply_custom_mode` / `_build_add_custom_frame` / `_add_custom_use_reference` / `_add_custom_use_blank`  **自定义分支两选项**(新增)
- `_first_run_render_check` / `_first_run_import`  **首次向导第 3 步的路径检测清单**(新增)
- `_open_url`  用 `webbrowser.open` 打开链接
- `start_run` / `_finish_preflight` / `stop_run`  运行控制
- `_drain_log`  100ms 轮询 log_queue 和 ui_queue

**导航:** `self.go(name)` 切换页面,name ∈ {home, edit, add, first_run, settings, help}。

**主题:** THEMES 字典,`self.t` 是当前主题色。四款:橙黑/绝区零/英伦/极简。

**风格约定:**
- 中文标点全用**全角**(`,` `:` `;` `(` `)` `「」`)—— 匹配 old_string 时特别注意
- `_chip` 是次要按钮,`_pill` 是主要按钮(primary=True 用主题色)
- 所有 UI 要用 `F(size, bold)` 生成字体,而不是硬编码

---

## 5. 已经做过的易用性改造(2026-07)

见 git 未提交状态。四项改动都集中在 `游戏助手.pyw` + `catalog.json`:

1. **首次向导重做** —— 3 步卡片:管理员权限 / 下载脚本(每款脚本一个"↗ 官方下载"按钮直达 GitHub releases) / 导入并检测(路径缺失时同页显示"手动指定"+"下载"链接)
2. **路径探测多候选** —— `resolve_all_candidates` 替代单值 `resolve_launcher`,UI 显示可点击候选列表
3. **"其他/自定义"两分支** —— ①基于现有预设修改(复制 wait_mode/进程模式作起点) ②完全手填
4. **主页顶部常驻状态条** —— 🟢N 就绪 / 🟡N 待办 / 🔴N 路径无效 + 非管理员警告

catalog.json 中每个 game 加了 `download_url` 字段(优先于 `doc_url` 作为下载入口)。

---

## 6. 打包 & 分发

```bash
cd 游戏助手
build_exe.bat   # 调用 PyInstaller 用 一键长草助手.spec
```

产出 `dist/一键长草助手.exe`(约 26 MB,含 tkinter/PIL runtime)。
分发时:**只发 exe + 使用说明.txt**,不发 plugins/ 和 settings.json(里面是本机路径)。

---

## 7. 测试

```bash
cd 游戏助手
python run_tests.py
```

36 个 unittest,覆盖 preset_catalog / preset_resolver / preflight / runner_core / quick_fill。**没有 UI 测试**——GUI 改动必须实际启动跑一遍验证。

改代码后自检最低要求:
```powershell
python -m py_compile 游戏助手.pyw
python run_tests.py
```

---

## 8. 常见陷阱

1. **文件里全是全角标点**。Edit 工具匹配 old_string 时不要用半角 `:` 替换 `：`,会 not found。
2. **catalog.json 的 doc_url 那行有奇怪的缩进**(zzz 那块比其它多 4 空格),不是错误,别顺手"整理"。
3. **plugins 目录不进 git**(见 `.gitignore`),它是运行时用户数据。
4. **首次向导判定**在 `App.__init__` 里读 `settings["first_run_done"]`,导入完 plugins 用户按"进入主页"才会置 True。
5. **path_cache** 存在 settings.json,加了新脚本 hint 后如果用户 cache 里指向了错误路径,新 hint 也不会被用——**先删 cache 或让 resolve_launcher 检测到 cache 失效才 fallback**。
6. **wait_mode = "helper" 时 game_processes 通常留空**,填了也是无害的(runner 只用 helper_processes)。反过来 `game` 模式必须两者都填。

---

# SOP:添加一款新的第三方脚本预设

> 场景:用户说"我装了个 XX 游戏的 YY 脚本,能加进去吗?"
>
> 目标:让下一个 AI 在**不启动 GUI 也不问用户太多问题的前提下**,通过修改 `presets/catalog.json` 一键加好一款新脚本,并让用户下次打开时看到它出现在"添加游戏"的下拉里。

## Step 0:先向用户确认这些信息(缺一不可)

如果用户没说,**用 AskUserQuestion 一次问齐**(不要来回追问):

| 需要知道的 | 例子 | 拿不到怎么办 |
|---|---|---|
| 游戏中文名 | "重返未来:1999" | 从项目 README 找 |
| 脚本项目 GitHub 地址 | `https://github.com/xxx/yyy` | 必须要,没这个别开始 |
| 启动器 exe 文件名 | `MaaPiCli.exe` | 看项目 README 或 releases |
| 脚本官方文档 URL | `https://xxx.doc/` | 用 GitHub URL 兜底 |
| 用户本机安装路径 | `E:\Games\py\M9A\MaaPiCli.exe` | 只用来加 `launcher_hints` |
| 命令行参数 | `-d` / `startOneDragon` / `-t 1 -e` | 看 README;不确定就留 `[]` |
| 脚本会自己关游戏吗? | 是/否 | 决定 wait_mode(见 §3.3) |
| 游戏进程名(如果 wait_mode=game) | `Endfield.exe` | 用户任务管理器截图 |
| 完成脚本要额外配置什么? | "MAA 里勾完成后退出模拟器" | 至少 1 条 checklist |

## Step 1:决定 wait_mode

- 脚本运行时会出现独立游戏客户端窗口,且脚本会自己关游戏 → `"game"` + 填 `game_processes` + 填 `helper_processes`
- 脚本本身就是任务队列(比如 MAA/M9A 类),跑完自己退出 → `"helper"` + 只填 `helper_processes`,`game_processes` 留 `[]`
- **不确定**就默认 `"helper"`,更安全(不会因为等不到游戏进程而超时)

## Step 2:在 catalog.json 里加游戏节点

在 `presets/catalog.json` 的 `games` 数组里,**紧挨着 `"custom"` 之前**插入新条目。保持缩进和其它条目一致(2 空格)。

模板:
```json
{
  "id": "shortname",
  "name": "游戏中文名",
  "game_processes": ["GameExe.exe"],
  "doc_url": "https://doc.example.com/",
  "download_url": "https://github.com/user/repo/releases",
  "scripts": [
    {
      "id": "shortname_variant",
      "name": "脚本显示名 · 变体",
      "launcher_filename": "Launcher.exe",
      "launcher_globs": ["**/Launcher.exe", "**/RepoName*/Launcher.exe"],
      "launcher_hints": [
        "E:\\Games\\py\\RepoName\\Launcher.exe"
      ],
      "args": ["-flag"],
      "wait_mode": "helper",
      "helper_processes": ["Launcher.exe"],
      "start_timeout_min": 15,
      "setup_checklist": [
        "在脚本内完成 XX 设置",
        "确保命令行参数一致"
      ],
      "notes": "一句话说明脚本用法。"
    }
  ]
}
```

**id 命名规则:** 全小写英文/数字,和其它 id 不冲突。game id 是短游戏名(`hsr`/`zzz`/`wuwa`),script id 是 `游戏id_变体`(`m7a_main`、`okww_daily`)。

**launcher_globs 写法:**
- `**/Launcher.exe` — 通配任意深度,常见形式,几乎必备
- `**/RepoName*/Launcher.exe` — 加一层版本号目录限定(比如 `M9A-v5.16.8/MaaPiCli.exe`)

**launcher_hints 写法:**
- 只加**用户本机确定存在**或**社区常见约定**的完整路径
- 用双反斜杠 `\\`(JSON 转义)
- 越具体的路径放越前面

**game_processes / helper_processes:**
- 大小写不敏感(runner 会 lower),但按约定用 PascalCase.exe
- 多个进程用逗号分隔的字符串数组

**start_timeout_min:** 默认 15。MAA/M9A 这种要等模拟器起来的可以设 20。

## Step 3:验证 catalog.json 语法

**必须做**——JSON 语法错了首次向导会崩:

```powershell
python -c "import json; json.load(open('presets/catalog.json', encoding='utf-8')); print('OK')"
```

## Step 4:跑测试(1 秒)

```powershell
python run_tests.py
```

`test_preset_catalog.py::test_catalog_loads` 会自动读 catalog.json 检查结构。全绿再往下。

## Step 5:(可选)加进"内置四款默认导入"

只有在这脚本是**主流刚需**、值得让所有新用户默认拥有时,才改 `preset_catalog.py`:

```python
DEFAULT_PRESET_IDS = [
    ("zzz", "onedragon"),
    ("genshin", "bettergi_onedragon"),
    ("hsr", "m7a_main"),
    ("arknights", "maa_gui"),
    ("new_game_id", "new_script_id"),   # ← 加这行
]
```

**默认情况下不要动**——用户可以在"+ 添加游戏"里选。

## Step 6:告诉用户下一步

回答用户时告诉他:
1. 已加到 `presets/catalog.json`,重启程序后会出现在"+ 添加游戏"下拉里
2. 首次向导会自动列出"↗ 官方下载"按钮(如果填了 download_url)
3. 路径探测会自动扫 E:\、D:\、E:\Games、D:\Games —— 用户装到别处时点"浏览…"手动指定
4. **提醒用户在脚本里完成 checklist 里的设置**(这是最容易漏的)

## Step 7:不要做的事

- ❌ 不要碰 `plugins/` 目录 —— 那是用户实例数据,不是模板
- ❌ 不要在没确认 wait_mode 的情况下拍脑袋写 `"game"` —— 猜错了跑起来会超时卡 15 分钟
- ❌ 不要给 `launcher_hints` 塞不存在的路径当"占位"—— hint 命中 = 直接返回,会误导
- ❌ 不要在 `notes` 里写长篇教程 —— 那是 setup_checklist 的活;notes 只放一句话备注
- ❌ 不要动 `custom` 那一节 —— 它是"其他/自定义"分支的兜底
- ❌ 不要用 Bash 打开 `游戏助手.pyw` 验证 GUI —— 在 headless 环境跑不起来,让用户自己启动

---

# 快速判断:用户想要什么?

| 用户说 | 该做什么 |
|---|---|
| "加一个 XX 游戏 / XX 脚本" | 走本文档 SOP |
| "路径找不到" | 检查 `launcher_hints` 是否覆盖用户的实际安装位置;必要时加 hint |
| "跑起来后跳过了 XX" | 让用户看运行日志 [跳过] 行,通常是路径无效或 checklist 未确认 |
| "wait_mode 该选哪个" | 见 §3.3 |
| "怎么改主题/字体" | `settings.json` 的 `theme` / `font_family` / `font_size` 字段,或程序内"设置" |
| "怎么打包发朋友" | 见 §6,只发 exe + 使用说明.txt |
| "怎么运行测试" | `python run_tests.py`(在 `游戏助手/` 目录下) |

---

*本文档创建于 2026-07-19,基于当时的代码状态。若代码有大改,请更新本文件。*
