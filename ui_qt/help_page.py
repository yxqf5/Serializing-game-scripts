# -*- coding: utf-8 -*-
"""帮助页:QTextBrowser 只读展示 HELP_TEXT 全文(移植 build_help:1770)。"""
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from ui_qt import theme

# 照抄 tkinter 版 游戏助手.pyw 的 HELP_TEXT(3222 起),不在运行时 import 旧模块。
HELP_TEXT = """欢迎使用「游戏串行一键长草助手」

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【免责声明】（使用前必读）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  本工具仅为本地「排队启动」第三方开源脚本，不是任何游戏官方产品。
  • 不读取/修改游戏内存，不分发第三方脚本 exe，需自行从官方渠道下载。
  • 第三方脚本可能违反游戏用户协议，存在封号等风险，由您自行承担。
  • 本工具按「现状」提供，作者不对账号损失等后果负责。
  • 完整声明见程序目录 DISCLAIMER.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

这是什么？
  把多个游戏的自动脚本「排队」运行：一次只跑一个，跑完并关闭后自动启动下一个。
  适合配置较低、内存有限的电脑挂机。

三步上手
  1) 在「主页」点每行左侧的 开/关，决定要不要跑。
  2) 拖动每行左侧「≡」，或用 ▲ ▼ 调整运行先后顺序。
  3) 点底部「▶ 开始运行」，剩下交给电脑。

运行日志
  • 拖动游戏队列与日志之间的分隔条，可自由调整日志高度。
  • 点「专注」让日志铺满右侧内容区；再次点击返回。
  • 每次运行结束自动保存到 logs\\YYYY-MM-DD.md（一天多次运行用分割线隔开），
    设置页可调整保留时长：最近一周 / 最近一个月 / 不清理。
  • 「导入」可打开保存的 md 日志或任意文本日志，在独立窗口查看；
    「目录」直接打开日志文件夹。
  • 向上滚动会暂停自动跟随，点「跟随最新」即可恢复。
  • 支持复制、清空和导出；界面最多保留最近 10000 行。

定时任务（每天到点自动开始）
  设置页 →「定时任务」：开启后设定每天几点开始、倒计时多少秒。
  到点时会弹出确认框并开始倒计时：
  • 点「立即运行」或等倒计时归零 → 自动开始执行当前勾选的串行队列；
  • 点「跳过本次」（或按 Esc）   → 本次不运行，明天同一时刻再询问。
  运行前检查发现的警告（如非管理员）会记入日志并自动通过，不会卡住挂机；
  到点时若已有任务在运行，或一个游戏都没勾选，则本次自动跳过。
  注意：需要助手保持开启（可以最小化），关掉助手就不会定时运行了。

添加游戏（推荐）
  点「＋ 添加游戏」→ 选游戏与脚本 → 路径自动探测 → 勾选脚本侧待办 → 保存。
  若列表为空，首次打开可「一键导入四套默认游戏」。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【已适配脚本 · 官方下载】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  以下链接均为各项目官方发布页，请自行辨别版本与安全：

  原神 · BetterGI（一条龙）
    https://github.com/babalae/better-genshin-impact/releases
    文档：https://www.bettergi.com/

  崩铁 · March7th Assistant
    https://github.com/moesnow/March7thAssistant/releases
    文档：https://m7a.top/

  绝区零 · OneDragon
    https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/releases
    文档：https://one-dragon.com/zzz/zh/home.html

  明日方舟 · MAA
    https://github.com/MaaAssistantArknights/MaaAssistantArknights/releases
    文档：https://docs.maa.plus/

  明日方舟：终末地 · MaaEnd（PC 端）
    https://github.com/MaaXYZ/MaaEnd/releases
    注意：MaaEnd 自身启动游戏有 bug，请在编辑页「高级选项 → 前置程序」
    填游戏本体 Endfield.exe，助手会先开游戏、等几十秒再启动 MaaEnd。

  鸣潮 · ok-ww（-t 1 -e 日常一条龙）
    https://github.com/ok-oldking/ok-wuthering-waves/releases
    请下载 setup.exe 安装包，勿下 Source code

  重返未来1999 · M9A（MaaPiCli -d）
    https://github.com/MAA1999/M9A/releases
    文档：https://1999.fan/zh_cn/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【暂未接入串行 · 有知名脚本但无法稳定「跑完退出」】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • 碧蓝航线 Alas — 7×24 调度 + Python 环境，无简单 one-shot CLI
    https://github.com/LmeSzinc/AzurLaneAutoScript
  • 阴阳师 OAS — GUI/Server 调度，无标准跑完退出命令
    https://github.com/runhey/OnmyojiAutoScript
  • 尘白禁区 SAA — 支持 --auto 但助手进程不会自动退出
    https://github.com/LaoZhuJackson/SnowbreakAutoAssistant

  若上述项目日后提供「任务完成自动退出」CLI，可在 catalog 中扩展。

脚本侧待办（卡片黄色提示）
  未完成可能影响脚本运行或无法自动切换下一个。开始运行后，日志会以黄色输出
  具体待办项与修改方法（编辑页按说明设置 → 勾选待办）。

运行前自检
  开始运行前会检查：是否勾选游戏、管理员权限、路径是否存在、进程是否已在运行。
  警告不会阻止保存，但建议按提示处理后再跑。

设置（左下角）
  可切换主题配色、修改字体与字号，设置会自动记忆。

小提示
  • 建议双击「一键长草助手.exe」以管理员身份打开（首次会 UAC 提示），部分脚本需要管理员权限。
  • 运行中可随时点「■ 停止」；切换页面不会中断运行。
  • 编辑页可展开「高级选项」手动改进程名与启动参数。
  • 长路径会自动省略，鼠标停在路径或游戏名上可查看完整内容。
  • 粘贴填充见「粘贴填充」弹窗内样例。
"""


class HelpPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        s = main.settings
        t = theme.THEMES.get(s.get("theme")) or theme.THEMES[theme.DEFAULT_THEME]

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(8)

        title = QLabel("使用帮助")
        title.setFont(theme.font(s, 20, True))
        root.addWidget(title)

        # 只读文本框:浅色排版,背景用日志底色
        box = QTextBrowser()
        box.setReadOnly(True)
        box.setOpenExternalLinks(False)
        box.setFont(theme.font(s, 11))
        box.setStyleSheet(
            "QTextBrowser { background: %s; color: %s; border: 1px solid %s; }"
            % (t.get("log_bg", t["panel"]), t.get("log_fg", t["fg"]), t["line"]))
        box.document().setDocumentMargin(16)
        box.setPlainText(HELP_TEXT)
        root.addWidget(box, 1)
