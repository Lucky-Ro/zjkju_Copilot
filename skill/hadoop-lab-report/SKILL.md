---
name: hadoop-lab-report
description: >
  端到端跑湛江科技学院「Hadoop 集群部署与开发」实验并生成 Word 实验报告。当用户给出一个
  heisun.xyz 的实验教程网址(形如 https://heisun.xyz/docs/hadoop-e/hadoop-eNN/,即 e01–e07
  / P1–P7 系列),或说「帮我跑这篇 Hadoop 实验、生成实验报告」「按学校模板排版实验报告」「在虚拟机上
  SSH 跑完这篇教程并截图」「湛江科技学院实验报告」「把这个 hadoop-e 教程做成 docx」时,务必使用本
  skill。它会:读取/索要配置 → 解析教程 → 通过 SSH 在用户虚拟机上逐步执行并捕获真实输入输出 →
  渲染终端截图 → 用内置 docx skill 把内容填进学校实验报告模板。**典型一句话用法**:「用本 skill 帮我
  完成 XX 教程的第 N 趴(附教程地址)」「帮我做 hadoop-e04 的 4.2」「完成这篇实验的第 4 部分并出报告」。
  即使用户没明说「用 skill」,只要任务涉及 heisun.xyz 的 hadoop 实验教程或湛江科技学院实验报告,也应触发
  本 skill。不要用于与该课程实验报告无关的通用 SSH/Word 任务。
license: Proprietary
---

# Hadoop 实验报告 Copilot（湛江科技学院 / heisun.xyz e0* 系列）

## 这个 skill 干什么

把一篇 heisun.xyz 实验教程网址变成一份符合学校模板的 Word 实验报告:**读教程 → 在用户虚拟机上
SSH 真跑 → 截图 → 按模板排版**,直到交付。设计目标是**泛化**——换教程(P1–P7)、换同学,靠
`lab_config.json` 与教程页本身驱动,不依赖对话上下文,可断点续跑。

**唯一真相是磁盘,不是对话。** 配置、执行计划、进度、运行日志、截图都落盘;任何一步都能从磁盘恢复。
上下文被压缩或会话中断后,读这些文件即可无缝接着跑。

**一步到位 + 一切以教程为准。** 用户只需准备好工作目录、拷好文件、说一句「用本 skill 帮我完成 XX 教程的
第 N 趴」。你要**自己看完整篇教程、按教程把环境/缺省密码/所需文件都查清楚并预检**;**缺什么就弹窗让用户
先备齐,齐了再开跑**,尽量一次跑到底。遇到拿不准的路径、缺省密码、环境变量、报错,**先查本趴教程,再查
全系列**(项目目录的 `series-defaults.md` 知识库,由 `build_series_kb.py` 通读全系列产出 + 必要时用
`parse_tutorial.py` 抓相邻教程页)——像人一样在教程里找答案,而不是猜。**一切以教程为准。**

## 五条不可违背的硬规矩

1. **密码只存 `lab_config.json` 这一个本地文件。** 绝不写进 SKILL.md、参考资料、`plan.json`、
   `state.json`、`run.log`,也绝不打印到终端输出或截图里。脚本读密码后,日志中相关命令一律用
   `***` 脱敏(见 `scripts/ssh_runner.py` 的脱敏逻辑)。
2. **改远程配置文件用 heredoc / `cat > file <<'EOF'`,绝不用 `vi`/`vim`/`nano`。** 交互式编辑器在
   非 TTY 的 SSH 管道里会乱码、卡死、把文件写坏。
3. **学号占位一律替换。** 教程里「你的学号后3位 / 替换为你学号后3位 / nodea+你学号后3位」等占位,
   统一换成 `lab_config.json` 里完整学号的**后 3 位**(`<完整学号>` → 后3位 `NNN`);表名、主机名、
   配置值、HiveQL 里出现的占位都要换。替换规则细节见 `references/report-template.md`。
4. **身份(姓名/学号/学院/班级/教师/地点/时间)必须由本人在交互窗中填写,不从示例或任何现成值套用。**
   教程给不了这些,所以一律**弹窗交互索取**:运行 **`python scripts/collect_config.py --popup`**——它会
   直接弹出新控制台让用户本人填,填完主流程才继续。**严禁**只打印一条命令/路径让用户自己开终端。
   `--validate` 只查缺项/占位/格式(不再有身份门禁);身份留空/占位时不得带病继续,重新弹窗索取。
5. **含真实信息的配置/缺省值文件只能落在用户项目目录(cwd),绝不写进 skill 目录。** 指 `lab_config.json`、
   `series_defaults.json`、`series-defaults.md` 等;skill 目录内只保留 `assets/lab_config.schema.json` 与纯
   占位 `assets/lab_config.example.json`。脚本由 `_common.ensure_outside_skill()` 强制兜底:输出路径落在
   skill 安装目录内一律报错非零退出、拒绝写盘。所有**写**配置/缺省值的脚本在写盘前都过这道边界。

## 文件布局(工作目录 = 用户实验目录,默认当前目录)

```
<工作目录>/
├── lab_config.json              # 身份 + 虚拟机 + 固定值 + 安装包来源(密码只在这里)。跨实验复用
├── runs/<eNN>/
│   ├── plan.json                # 解析教程得到的有序步骤(含命令/语言/交互应答/常见问题)
│   ├── state.json               # 进度游标:每步 pending/done/failed/skipped + 证据指针
│   ├── run.log                  # 逐条命令的完整 stdin/stdout/stderr(脱敏后),唯一真相
│   ├── live.md                  # 高层进度清单(配合 run.log 给「做到哪了」的清爽视图)
│   ├── shots/step-*.png         # 终端风格截图(命令+输出)
│   ├── manual/*.png             # 必须真实截屏的 GUI/网页步骤(用户提供或本机截屏)
│   └── report.docx              # 最终交付
```
`<eNN>` 取自教程网址(如 `hadoop-e04` → `e04`)。`lab_config.json` 共享;每篇实验的产物各自放 `runs/<eNN>/`。

## 工作流程(skill 核心,按顺序推进,每步落盘)

### 阶段 0 — 先通读教程、缺省自动落盘、弹窗收身份(务必先做,全在项目目录)
**接任务第一件事:把固定知识落盘,别只靠对话。所有产物只落项目目录(cwd),绝不进 skill 目录(硬规矩 5)。**
1. **通读全系列、产出缺省知识库**:在项目目录跑 `python <skill>/scripts/build_series_kb.py`,
   它遍历 `hadoop-eNN`(e01…e07)读遍所有教程,把缺省密码(如 P4 Hive、P7 Sqoop 的元数据库口令)、
   IP、主机名约定、Web 端口、安装包抽取到**项目目录**的 `./series_defaults.json`(机读)+ `./series-defaults.md`(人读)。
   先读 `./series-defaults.md` 心里有数。
2. **缺省自动落盘、不问用户**(需求 2.2):`python <skill>/scripts/collect_config.py --autofill --tutorial <本次教程URL>`——
   把教程已给的连接段/固定值段(账号/密码/IP/主机名/端口)**直接写进** `./lab_config.json`,**不打扰用户**(做实验基本用默认);
   **已有值一律不覆盖**(同项目换教程 P1→P7 时连接/固定值零重填)。身份段写占位,待下一步本人填。
3. **弹窗收身份**(需求 2.1,教程给不了的才问):`python <skill>/scripts/collect_config.py --popup`——
   它会**直接弹出新控制台窗口**跑 `--interactive`,让用户**本人逐项**填姓名/学号/学院/班级/教师/地点/时间
   (密码类回显 `****`);窗口结束后自动 `--validate`,仍有缺项就**再弹**(硬规矩 4,**严禁**只打印命令让用户自己开终端)。
   `student_id_last3` 由完整学号自动派生,不必让用户填。
   **注**:`--popup` 会阻塞到用户在弹窗里填完,所以用后台/给足超时的方式跑(如 Bash 工具 `run_in_background`),别让它把对话卡住。
   - 若 `lab_config.json` 已存在且 `--validate` 通过 → 直接 `--show` 脱敏回显给用户确认即可,身份/连接零重填。
   - 字段含义与示例见 `assets/lab_config.schema.json` 与 `assets/lab_config.example.json`(纯占位)。

### 阶段 1 — 解析教程
`python scripts/parse_tutorial.py <tutorial_url> -o runs/<eNN>/plan.json`
抓取教程 HTML,提取:子任务(`任务N.M`)、每个子任务的【任务目的/环境/资源/说明或内容/步骤/常见问题】、
每步的命令/代码块(含 `sql`/`xml` 语言标签或「无标签=交互/shell」)、教程已给出的交互应答值、常见问题
的「报错→解决办法」。教程页结构与解析规则见 `references/tutorial-structure.md`。

### 阶段 2 — 生成执行计划 + 标注前置条件
对 `plan.json` 的每一步打标:`auto`(能在 SSH 终端自动跑) vs `manual`(需 GUI/人工/浏览器,如 P1 的
VirtualBox 克隆、网卡配置、NameNode `:9870` 网页)。把 `manual` 步骤汇总成**「前置条件清单」**给用户确认,
并**探测前置状态**:能否 SSH 上各节点、节点间是否连通、安装包是否就位。判定哪类步骤不可自动化的依据见
`references/tutorial-structure.md`。

### 阶段 3 — 预检(缺什么先备齐,再开跑)
`python scripts/ssh_runner.py --preflight runs/<eNN>/plan.json`
用 `lab_config.json` 连接每个节点:确认可登录、`sudo`/`root` 可用、节点间连通、所需安装包在目标机就位或
可从本机(Windows)上传(`scp`/`sftp`)。结果写 `runs/<eNN>/preflight.json`,含 `missing[]` 与 `ready`。
- `ready=true` → 进入阶段 4 开跑。
- `ready=false`(有缺口)→ **不要硬跑**:把 `missing[]` 用一句话弹窗告诉用户去准备,并**停下等**:
  `python scripts/popup.py "预检发现还差:<逐条>。准备好后回我『继续』,我就重新预检并开跑"`,
  然后按「卡住怎么办」停在原地。用户回「继续」→ 重跑 `--preflight`,`ready` 了再开跑。不要 abort。

### 阶段 4 — 执行(逐步真跑,完整捕获)
`python scripts/ssh_runner.py --run runs/<eNN>/plan.json`,要点:
- **实时逐行回显到屏幕(硬要求)**:发出去的每条命令、虚拟机返回的每行输出都**即时、逐行**打印,让用户像看真终端一样跟着看。
  PTY 开了回显,命令以「**真实提示符 + 命令**」形式进流(`[hadoop@<真实hostname> ~]$ cmd`),进 hive/mysql 还会出现真实的
  `hive>`/`mysql>`/续行 `>`;OSC 窗口标题等控制序列已清洗掉(不伪造、不残留)。**同一份内容同步 `tee` 进 `run.log`,并作为截图来源**(三处一致)。
  `--run`/`--preflight` **启动即自动弹出实时日志窗口**(纯 Python 的 `live_tail.py`,在新控制台跟随 `run.log`,
  立即显示已有内容、低延迟刷新;不想弹加 `--no-window`)。**无需也不要**再手动用
  `Start-Process powershell -ExecutionPolicy Bypass` 去开窗口——那会被安全分类器拦(上次「终端没弹出」的原因)。
- **完整捕获** 每步的 stdin/stdout/stderr 写入 `run.log`。`run.log` 是后续排版与截图的唯一来源。
- **敏感信息打码**:凡密码等 [敏感] 值,**屏幕回显与日志都打码成 `****`**,绝不出现明文(仅在喂入 SSH 通道的瞬间用真值且不写出)。
- **交互命令**(`sudo`、`mysql_secure_installation`、`mysql -p`、`ssh-keygen`、`ssh-copy-id`、`hive` 等)用教程
  给出的 / `lab_config.json` 里的应答**自动喂入**(paramiko 交互通道,按提示匹配喂答案,不是盲发)。
- **`sudo` 直接在 PTY 里跑**:`ssh_runner` 已把「哨兵 printf」从命令上拆开、对交互命令**延后发送**,sudo 读密码时
  缓冲区里不再有排队的 printf 行(根除 type-ahead 抢答「Sorry, try again」),密码由 sudo 兜底应答自动喂入(取
  `sudo_password` 或 `hadoop_password`)。**不要**再手写 `echo 密码 | sudo -S` 带外脚本或临时授 NOPASSWD 绕过。
- **改配置文件用 heredoc/`cat`**,不用 vi(硬规矩 2)。
- **需要「自己写」的部分**(如 P4 要写 7 条 HiveQL):由你**生成** HiveQL 并**实际执行**,把「你的 HiveQL
  + 真实输出」都记进 `run.log`,并对照教程的期望结果**校验**(对得上才算过)。
- **幂等 / 断点续跑**:每步先**探测状态**——已完成的跳过,但仍抓证据(截图/输出);把「进行到第几步」写进
  `state.json`。重跑时从 `state.json` 续。
- **自我处理小问题(一切以教程为准)**:命中教程【常见问题】里的报错,按其解决办法自动修。遇到教程没直说的
  路径 / 缺省密码 / 环境变量 / 报错,**先查本趴教程,再查全系列**(项目目录的 `series-defaults.md` + 必要时
  `parse_tutorial.py` 抓相邻 eNN 页)——这些教程同一套约定,像人一样翻教程找答案,别猜。把「问题 + 解决方法」
  留存到 `state.json`,供阶段 6 的「实验总结」使用。
- **长命令放远程 `tmux`**:在节点上用持久会话跑耗时命令,SSH 断了也不丢(见 `references/remote-help-mode.md`)。

### 阶段 5 — 截图(FinalShell 风,忠实重放真实终端流)
`python scripts/render_shot.py --from-log runs/<eNN>/run.log --out runs/<eNN>/shots/`
**这是唯一权威截图路径**——`--from-log` 把每段(`### <subtask>#<idx>`)的「命令 + 完整输出」一起渲染成
**FinalShell 默认风格 PNG**:纯黑底、白等宽字、右侧淡滚动条;**不要**画 macOS 窗框/红绿灯/语法高亮(那样很「疏离」)。
**提示符不伪造**——它已在 `run.log` 的真实流里(shell 的 `[hadoop@<真实hostname> ~]$`、hive 的 `hive>`、mysql 的
`mysql>`/续行 `>`),render 逐行重放、只对识别到的提示符着色。脚本**自带成品级处理,无需你再加工**:
- **命令清洗**:截图里自动剥掉注入的管道噪声(开头的 `sleep N;` / `source /etc/profile…;`,以及 `>/dev/null 2>&1`
  / `2>/dev/null`),让命令看起来就是学生手敲的那条;**run.log 仍存真实命令,不受影响**。
- **REPL 美化**:`hbase shell <<'EOF' … EOF` 这类 heredoc 段自动折叠成干净的 `hbase(main):NNN:0> 命令` + 输出
  (hive/mysql 同理),跨段连号、banner 只出现一次。
- **缺输出守卫**:某段只有命令、没有输出时在 stderr 告警,提示捕获缺失。

**严禁**手写一次性渲染脚本(如 `render_5x.py`),也**严禁**只渲染命令、不带输出(那正是上次「截图只有输入没有输出」的成因)。
`--cmd/--output-text` 即时路径只留给无真实流的兜底。**必须真实截屏的 GUI/网页步骤**(如 NameNode `:9870` 页面)不要伪造:
改为真实截图或**提示用户手动提供**,放 `runs/<eNN>/manual/`。

### 阶段 6 — 排版(用内置 docx skill,编辑现有模板)
用 `scripts/fill_report.py` 往**学校模板的单元格**里填,保持官方版式不变(python-docx 编辑现有文档,
不破版式;代码块/截图/表头样式见下两份参考)。**若用户已有半成品报告**(如表头+4.1 已填,要从 4.2 续写),
用 `--into 现有报告.docx`:表头不动、「实验过程」在已有内容后**追加**、结论/总结替换,只渲染你这次给的栏目。
从零则用 `--template assets/template.docx`。模板与填充细节见 `references/report-template.md`;代码块表格样式见
`references/docx-codeblock-recipe.md`。
**最终报告输出到工作目录根**(不要留在 `runs/` 里):`-o "<工作目录>/Hadoop集群部署与开发-实验报告-P<N>-完成.docx"`;
`runs/<eNN>/` 只放过程产物(plan/state/run.log/shots)。要填的内容:
- **表头**(姓名/学号/班级/地点/时间…)从 `lab_config.json` 取。
- **实验目的** ← 各子任务【任务目的】;**实验内容及实验器材** ← 【任务环境】/【任务资源】。
- **实验过程** ← 步骤说明 + 穿插截图 + 命令/代码用 **#FFF2CC 淡金色表格**;**文风放轻松、像学生记笔记**
  (短句、看图说话「可以看到…」、少用「我」、别写作文腔),详见 `references/report-template.md` 的「内容改写口径」。
- **实验结论** ← 最终结果截图 + 关键代码/HiveQL。
- **实验总结** ← 真实遇到的问题与解决方法(取自 `state.json`) + 一句心得体会。

### 阶段 7 — 自检 + 交付
对照检查表逐项核对(子任务全覆盖、每条要求的查询都有「命令/HiveQL + 截图 + 说明」、学号替换到位、代码块
样式正确、密码未泄漏)。检查表见 `references/report-template.md` 末尾。最后给用户两个文件路径:
`<工作目录>/Hadoop集群部署与开发-实验报告-P<N>-完成.docx`(最终报告,在工作目录根)与 `runs/<eNN>/run.log`。

## 卡住怎么办 —— 「远程帮修电脑」模式(不要断开)

遇到搞不定、需要用户配合的情况(典型:网卡没配好导致 SSH 不通),**像朋友远程帮修电脑那样**:停在原地、
说清楚情况,但**不结束、不丢进度、不断会话**。完整协议见 `references/remote-help-mode.md`,要点:
1. **不要 abort。** 进度/日志/配置都已在磁盘;远程长任务在 `tmux` 里,可重连续跑。
2. **暂停时**:① 在对话里讲清「卡在哪、报什么错、需要你手动做什么、做完回复什么继续」;
   ② 弹一个 Windows 提醒抓注意力 —— **`python scripts/popup.py "<一句话,可中文>"`**(已封装:写 UTF-8 临时文件、
   隐藏控制台只弹对话框、detached 不阻塞;别再用裸 `powershell -File`,那样会留一个空白 PS 窗口)。
3. **收到「继续/好了」后**:先**重新核对那个条件**(如重测 SSH 是否通),通过就从 `state.json` 的游标接着跑,
   不通就再说明一次。

## 两种运行方式
- **(A) 交互式真跑(推荐,默认)**:在当前会话里逐阶段跑,**实时逐行回显**给用户看;碰到搞不定的进入
  「远程帮修模式」停下等用户。最稳妥,适合第一次跑、要交的报告、可能需要人工配合的实验。
- **(B) 后台/子代理冷启动(模拟陌生同学)**:开一个干净会话/子代理,只给它 `lab_config.json` + 教程网址,
  让它自驱跑通——用来验证 skill 的「可复用性」。**子代理是闷头跑、跑完才回报**,但 `ssh_runner.py --run`/
  `--preflight` **默认自动弹出实时日志窗口**(`live_tail.py`,新控制台跟随 `run.log`,低延迟刷新),
  用户照样能实时看见在干啥,无需手动开窗。**子代理启动 `--run` 后必须确认窗口已弹出**:stderr 出现
  `[live] 已打开实时日志窗口`即为成功;只有用户明确说不要弹窗时才加 `--no-window`。
  `run.log`(全量)与 `live.md`(高层进度)都在实时落盘。
  注意:子代理无法做交互式「远程帮修」,故 (B) 仅适合环境已完全就绪、能一次性跑完的情况;否则用 (A)。

> ⚠️ 永远不要把 `powershell -ExecutionPolicy Bypass ...` 当**直接工具命令**执行——会被安全分类器拒。
> 开窗口/弹窗都已封装成纯 Python(`live_tail.py` 自动拉起、`popup.py` 弹框),用它们即可。

## 参考资料(按需读取,不要一次性全读进上下文)
- `series-defaults.md`(**项目目录,非 skill 目录**)—— **接任务先用 `build_series_kb.py` 生成再读**:
  P1–P7 全系列缺省密码/IP/主机名/端口/包知识库(含真实缺省值,故只落项目目录,见硬规矩 5)。
- `references/tutorial-structure.md` —— heisun.xyz e0* 教程页结构、解析规则、auto/author/manual/note 判定。
- `references/report-template.md` —— 学校模板的表头/栏目单元格映射、学号替换规则、自检清单。
- `references/docx-codeblock-recipe.md` —— #FFF2CC 代码块表格配方(ShadingType.CLEAR、细黑边框 sz4、
  宽度 auto、Consolas 五号)、截图插入(左对齐满栏、无图注)、来自内置 docx skill 的注意事项。
- `references/remote-help-mode.md` —— 暂停/续跑协议、tmux 持久会话、Windows 弹框检测。

## 脚本(`scripts/`,确定性重活交给脚本;接口详见 `scripts/README.md`)
- `collect_config.py` —— `--autofill` 教程缺省直接落盘(不问用户、已有不覆盖);`--popup` 弹新控制台跑
  `--interactive` 收身份(本人必填、密码回显 `****`)完后自动校验、缺项再弹;`--validate` 完整性校验
  (缺项/占位/格式,**无身份门禁**);`--show` 脱敏回显;派生 `student_id_last3`。**写盘前过 `ensure_outside_skill` 边界。**
- `parse_tutorial.py` —— 教程 URL → `plan.json`。
- `build_series_kb.py` —— 抓 P1–P7 → 缺省值知识库,**产出到项目目录** `./series_defaults.json` + `./series-defaults.md`(过边界,不进 skill)。
- `ssh_runner.py` —— paramiko 执行引擎:实时回显、**自动弹 `live_tail.py` 窗口**、交互应答自动喂入、
  heredoc 写配置、捕获 I/O、脱敏、`state.json` 断点续跑、`live.md` 进度、`--preflight` 出 `preflight.json`、远程 tmux。
- `render_shot.py` —— 真实终端流 → **FinalShell 风**终端 PNG(黑底白字/淡滚动条;提示符来自真实流、逐行重放不伪造;`--prompt` 仅兜底)。
- `convert_template.py` —— `.doc` → `.docx`(Windows 用 Word COM,LibreOffice `soffice` 备选)。
- `fill_report.py` —— 编辑现有学校模板,填段落/截图/#FFF2CC 代码块;紧凑排版(代码↔截图无缝);`--template`/`--into`。
- `live_tail.py` —— **纯 Python** 实时日志窗口(立即显示+150ms 跟随+VT 着色);由 ssh_runner 自动拉起,不碰 PowerShell。
- `popup.py` —— **纯 Python** 弹窗(ctypes `MessageBoxW`,原生中文/置顶/detached);远程帮修抓注意力用。
- `notify_popup.ps1` —— (旧)PowerShell 弹框,保留备用;现默认用 `popup.py`,不再需要它。

## 交付物
1. 可复用、可开源 skill 本体(本目录):`SKILL.md`、`README.md`、参考资料、知识库**生成器**(`build_series_kb.py`,
   知识库本身只在项目目录生成,不入库)、各脚本、`requirements.txt`、`.gitignore`、`LICENSE`、`lab_config.json` 的
   schema 与纯占位示例。
2. 验证:完整跑一遍 **P4**(`hadoop-e04`),产出符合模板的 `report.docx` 与 `run.log`。
