# hadoop-lab-report

> 一个 **Claude Code / Claude Agent Skill**:把一篇 [heisun.xyz](https://heisun.xyz/docs/hadoop-e/) 的 Hadoop 实验教程网址丢进来,自动 **(运行前先 git 自更新)→ 读教程 → 在你的虚拟机上 SSH 真跑 → 终端截图(默认 FinalShell 壁纸)→ 按湛江科技学院模板排版成 Word 实验报告**,直到交付。
>
> 覆盖两套系列:**hadoop-e0\* 实操系列(P1–P7)**——部署 Hadoop、HDFS、MapReduce、Hive、HBase、Zookeeper、Flume/Sqoop;以及 **hadoop-training-v2 综合作业系列(Part 1–4)**——Hive 数据分析 + 写程序 + 可视化。换教程、换人都不抓瞎。

⚠️ **学习辅助工具**:用于把"自己真做过的实验"自动整理成规范报告并留存证据(真实命令 + 真实输出 + 真实截图),不是替你伪造实验。请遵守你所在课程的学术诚信规定。

---

## 这玩意儿能干嘛

给定一个教程网址(如 `https://heisun.xyz/docs/hadoop-e/hadoop-e04/` 或
`https://heisun.xyz/docs/hadoop-training-v2/hadoop-training03/`),它会:

0. **运行前先自更新**(`update_skill.py`):每次用 `git clone` 把本 skill 新克隆到最新版,**默认 GitHub、网络超时自动退让 Gitee**(匿名 clone,无需凭据),免得用了过期版本。
1. **解析教程** → 子任务、有序步骤、命令、HiveQL/SQL/XML、交互应答、常见问题(`parse_tutorial.py`);**两套系列通吃**——training-v2 的【任务名称】/【任务要求】/带样例代码的【任务提示】也能解析。
2. **生成执行计划**,区分「能 SSH 自动跑」(`auto`)/「要自己写命令」(`author`,如 Hive 的 7 条查询)/「要 GUI/人工」(`manual`,如 VirtualBox 克隆、网卡、NameNode `:9870` 网页)。
3. **SSH 真跑**(`ssh_runner.py`,paramiko 持久会话):**实时逐行回显**(`>> 命令` + 原样输出),完整写进 `run.log`;交互命令(`mysql_secure_installation`/`hive`/`ssh-keygen`…)按教程缺省值自动喂答案;改配置用 heredoc 不用 vi;断点续跑;**密码全程打码 `****`**。
4. **终端截图**(`render_shot.py`):把命令+输出渲染成 FinalShell 风终端 PNG,**默认叠上 FinalShell 壁纸**(`assets/FinalShellBackGround.png`);要黑底白字加 `--black-bg`(Windows 自带 Edge 无头,零额外安装)。
5. **排版**(`fill_report.py`,python-docx):往学校 Word 模板的单元格里填——表头、实验目的/内容、实验过程(步骤+截图+**淡金 `#FFF2CC` 代码块**)、结论、总结,**保持官方版式**。
6. **学号占位替换**:教程里 `emp你学号后3位`、`nodea+学号后3位` 等统一替换为你学号后 3 位(记 `NNN`,如 `empNNN`、`nodeaNNN`)。

---

## 给「新同学」的快速上手(冷启动)

### 0. 前提
- Windows + 装了 **Microsoft Word**(转模板用)、**Edge**(截图用,系统自带)。
- **Python 3.10+**。
- **[Claude Code](https://claude.com/claude-code)**(本 skill 在其中运行)。
- 你的实验 **虚拟机已就绪**、能从本机 SSH 连上(网卡、克隆这类 GUI 步骤本工具不自动做,会让你先弄好)。

### 1. 安装 skill
把本仓库放到 Claude 的 skills 目录(让 Claude 能发现它):
```
~/.claude/skills/hadoop-lab-report/        # macOS/Linux
C:\Users\<你>\.claude\skills\hadoop-lab-report\   # Windows
```
装 Python 依赖:
```bash
pip install -r requirements.txt
```

### 2. 准备模板与配置(放在你的「实验工作目录」)
- 把学校的空白报告模板(`.doc`/`.docx`)放进工作目录;首次会自动转成 `assets/template.docx`。
- 配置 `lab_config.json` 分两步,Claude 会自动驱动,你基本只需在弹窗里填身份:
  1. **教程缺省自动落盘**:`python <skill>/scripts/build_series_kb.py --tutorial <教程URL>`(按 URL 自动选系列、
     通读全系列产出 `./series_defaults.json`)+ `python <skill>/scripts/collect_config.py --autofill --tutorial <教程URL>`
     ——把教程已给的节点 IP/端口/缺省密码**直接写好、不问你**(做实验基本用默认)。
  2. **弹窗填身份**:`python <skill>/scripts/collect_config.py --popup` 会**直接弹出一个新控制台窗口**,让你本人填
     姓名/学号/学院/班级/教师/地点/时间(密码输入回显 `****`),填完自动校验、缺项再弹——你不用自己开终端敲命令。
  - **密码只存在 `lab_config.json` 这个本地文件**,绝不进日志/截图/报告,`.gitignore` 已排除它——**永远不要把它提交到 Git**。
  - `lab_config.json`(以及缺省知识库 `series_defaults.json`/`series-defaults.md`)只存在于你的工作目录,**绝不写进 skill 目录**;
    同一目录换教程(P1→P7)时身份/连接**零重填**。

### 3. 开跑
在 Claude Code 里,对话直接说(它会自动触发本 skill):
```
用 hadoop-lab-report 跑 https://heisun.xyz/docs/hadoop-e/hadoop-e04/,生成实验报告
```
Claude 会:读 `lab_config.json` → 抓教程 → 预检 SSH → 逐步执行(你能实时看到终端输出)→ 截图 → 排版出 `runs/<eNN>/report.docx`。
卡住时(典型:某节点 SSH 不通)它**不会退出**,会停下来说清楚、弹个 Windows 提醒,等你弄好回一句「继续」,再从断点接着跑。

> **想全程盯着看?** 不用手动开窗:`ssh_runner.py --run`/`--preflight` 启动时**自动弹出**一个实时
> 日志窗口(纯 Python 的 `scripts/live_tail.py`,新控制台跟随 `run.log`,低延迟刷新)——后台/子代理
> 跑也一样会弹。不想弹加 `--no-window`;也可手动 `python scripts/live_tail.py runs\e04\run.log`。

---

## 目录结构

```
hadoop-lab-report/
├── SKILL.md                      # 给 Claude 的编排说明(触发条件 + 7 阶段流程 + 硬规矩)
├── README.md                     # 你正在看的这份
├── requirements.txt
├── references/                   # 固定知识(Claude 按需读)
│   ├── tutorial-structure.md     #   教程页解析规则
│   ├── report-template.md        #   学校模板单元格映射 + 学号替换 + 自检清单
│   ├── docx-codeblock-recipe.md  #   #FFF2CC 代码块/截图 的 docx 配方
│   └── remote-help-mode.md       #   卡住时「远程帮修」暂停/续跑协议
│   # 注:P1–P7 缺省知识库(series-defaults.md/.json)含真实缺省值,由 build_series_kb.py
│   #     生成到「你的项目目录」,不在 skill 目录内(见硬规矩 5)。
├── assets/
│   ├── lab_config.schema.json    # 配置字段说明
│   ├── lab_config.example.json   # 配置示例(纯占位)
│   ├── template.docx             # 学校空白模板(由 .doc 转换 bundle)
│   └── FinalShellBackGround.png  # 截图默认 FinalShell 终端壁纸(深蓝墨色纹理)
└── scripts/
    ├── _common.py                # 共享:配置/打码/路径边界(ensure_outside_skill)/学号(URL→eNN/tNN)/UTF-8
    ├── update_skill.py           # 阶段 -1 自更新:每次 git clone 最新版(GitHub→Gitee 退让,匿名无凭据)
    ├── collect_config.py         # 教程缺省落盘(--autofill)/弹窗收身份(--popup)/校验(--validate)/脱敏回显
    ├── parse_tutorial.py         # 教程 URL → plan.json(e0* 与 training-v2 两套系列)
    ├── ssh_runner.py             # SSH 执行引擎(实时回显/交互喂答/断点续跑/打码)
    ├── render_shot.py            # run.log 终端流 → 终端 PNG(默认叠 FinalShell 壁纸;--black-bg 纯黑底)
    ├── convert_template.py       # .doc → .docx(Word COM / soffice)
    ├── fill_report.py            # 填进学校模板(从零 --template 或续写 --into)
    ├── build_series_kb.py        # 通读全系列 → 缺省值知识库(--tutorial 自动选系列;产出到项目目录,不进 skill)
    ├── popup.py                  # 纯 Python 提醒弹框(远程帮修抓注意力用)
    ├── live_tail.py              # 纯 Python 实时日志窗口(ssh_runner 自动拉起)
    ├── notify_popup.ps1          # (旧)PowerShell 弹框,保留备用
    └── live_tail.ps1             # (旧)PowerShell 日志窗口,保留备用
```

## 安全与隐私
- 密码/口令**只**存在你工作目录的 `lab_config.json`;脚本读后在所有输出里打码成 `****`。
- `.gitignore` 已排除 `lab_config.json`、`runs/`(含真实日志/截图)、安装包等——**别把它们 push 上去**。
- 截图与日志会包含你的真实命令与输出;公开分享前请自查是否有敏感信息。

## 致谢 / 许可
- 教程来源:heisun.xyz 的 hadoop-e 系列(版权归原作者)。
- 报告版式:湛江科技学院实验报告模板。
- 本工具许可见 `LICENSE`(Apache License 2.0)。
