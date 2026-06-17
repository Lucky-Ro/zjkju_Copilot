# scripts/ —— 脚本清单与接口(已实现并自测)

确定性、重复性的重活交给脚本,SKILL.md 只做编排。所有脚本共用 `_common.py`(配置加载、密码打码、
学号派生、URL→eNN/tNN、UTF-8 输出修复)。

## 依赖(执行机 = Windows + Python 3.14,已装)
`paramiko`(SSH)、`requests` + `beautifulsoup4`(抓/解析教程)、`python-docx`(填报告)、
`Pillow`(截图裁切 + 默认 FinalShell 壁纸合成;缺失则回退纯黑底,不致命)、
`openpyxl`(读花名册 `学生演员分配*.xlsx` 匹配演员;缺失则 find_actor 退让大模型)。
终端截图用 Win 自带 **Edge** 无头模式(零额外安装)。模板 `.doc`→`.docx` 用 **Word COM**(本机有 Office)。
预览/校验报告可用 `pymupdf`(可选)把导出的 PDF 渲染成图。docx skill 的 `validate.py` 在 Windows 上读 XML
会按 GBK 报假错,**以「Word 能否打开/导出 PDF」为准**。

| 脚本 | 职责 | 关键接口 |
|---|---|---|
| `update_skill.py` | **阶段 -1 自更新**:每次 `git clone --depth 1` **新克隆**最新版(**默认 GitHub、超时退让 Gitee**,匿名 clone 无需凭据)→ 原子同步 `skill/hadoop-lab-report` 子树进安装目录(只覆盖有变化的文件、从不删除)→ 删临时目录;安装目录在 git 仓库内则跳过(不 clobber 开发改动)。退出码 0=已更新/跳过,3=两镜像都没 clone 成(用当前版本继续) | `[--prefer github\|gitee] [--timeout 30] [--no-install-sync]` |
| `collect_config.py` | 教程缺省**直接落盘**(`--autofill`,不问用户、已有不覆盖)、**弹新控制台**收身份(`--popup` 跑 `--interactive` 完后自动校验、缺项再弹)、完整性校验(缺项/占位/格式,**无身份门禁**)、派生 `student_id_last3`、脱敏回显。写盘前过 `ensure_outside_skill` 边界。 | `--autofill [--tutorial URL]` / `--popup` / `--interactive` / `--validate` / `--show` / `--derive` `[--config ...]` |
| `parse_tutorial.py` | 抓教程 HTML → `plan.json`(子任务/步骤/命令/`lang`/`repl`/`kind`/`needs_sid`/`expect_output`/常见问题);识别 hive/mysql/**hbase/zk/spark** 提示符 + 裸命令上下文动词,标 `step.repl`;**两套系列通吃**:e0*「任务N.M」+【任务步骤】、training-v2【任务名称】+【任务要求】+带样例代码的【任务提示】(→子任务 `hints[]`);training 子任务要用到「我的演员」时标 `needs_actor:true`(触发 find_actor) | `<url> -o plan.json` |
| `find_actor.py` | **(training-v2)按 姓名+学号 在花名册 `学生演员分配*.xlsx` 里查分配到的演员**,写回 `lab_config.identity.actor`。学号精确匹配为主键 + 姓名交叉校验;0/多命中或缺花名册/缺 openpyxl → 退出码 3 **退让大模型**人工核对(绝不瞎编)。写前过 `ensure_outside_skill` | `[--name N --student-id S] [--roster x.xlsx] [--no-write] [--print]` |
| `prepare_training_project.py` | **(training-v2)物化+参数化内置参考工程**(`assets/training-code/exp{1,2,3}`)到 `runs/tNN/project/`:包名 `hadoop9999`→`hadoop<sid3>`、`"我的演员"`→真实演员、拷资料库 `Film.json` 进 resources。缺省 sid3/actor 取 lab_config | `<P2\|P3\|P4> [--sid3 NNN] [--actor 名] [--film-json P] [--no-film]` |
| `ssh_runner.py` | paramiko 持久 shell:**实时逐行回显**(tee 进 `run.log` 兼作截图源);**启动自动弹实时窗口**(`--no-window` 关);交互应答自动喂入;**五种 REPL(hive/mysql/hbase/zk/spark)真交互逐句喂入、命令↔回显交错、同子任务复用一个会话(临时节点跨块保留)、每块独立成段→一图**(`--repl-batch` 退回非交互应急);heredoc 写配置;`state.json` 断点续跑;`****` 打码;`--preflight` 写 `preflight.json` | `--preflight PLAN` / `--run PLAN [--continue-on-error] [--no-window] [--repl-batch]` / `--probe NODE` |
| `build_series_kb.py` | 抓全系列 → **项目目录** `./series_defaults.json` + `./series-defaults.md`(缺省密码/IP/主机名/端口/包;含真实缺省值,过边界不进 skill 目录);**按 `--tutorial`/`--series` 自动选 e0* 或 training-v2** | `[--tutorial URL] [--series auto\|e\|training] [--max 7] [--out-dir .]` |
| `render_shot.py` | `run.log`(按 `### ` 分段)→ FinalShell 风终端 PNG(2x 清晰);**字体英文 DejaVu Sans Mono(skill 自带 ttf,@font-face 注入)/ 中文 Microsoft YaHei UI**;**默认叠 FinalShell 壁纸**(亮度当 alpha,文字浮于壁纸),`--black-bg` 退回纯黑底白字、`--bg-image` 换壁纸;**截图保真**:滤掉脚本日志/控制行、`>> (应答)` 注解、注入的 `--- xxx ---` 横线、zk 启动 log4j 噪声;识别 hbase/zk/spark 提示符着色;**Edge 无头失效自动回退 Chrome**;也支持单段即时渲染 | `--from-log run.log --out shots/ [--black-bg] [--bg-image P]`  或  `--title T --cmd C --output-text O --out x.png` |
| `convert_template.py` | `.doc` → `.docx`(Word COM 优先,soffice 备选);缺省转 `assets/template.docx`,也可显式转实训报告模板 | `[in.doc] [out.docx]` |
| `fill_report.py` | python-docx 编辑**现有**模板:填表头 + 各栏目填段落/截图/#FFF2CC 代码块嵌表;**两套模板**——`--series auto` 按 `tutorial_url` 判:e0*→`template.docx`(实验报告)、training-v2→`training_template.docx`(实训报告,栏目=实训目的/内容及过程/总结及体会);正文统一 `apply_sid`+`apply_actor` 双替换;**版式固化**(表头个人信息居中、正文左对齐、单倍行距、**黄色命令框满宽 pct100%**、步骤留白);`--into` 续写时裁末尾空白再追加 | `--config ... [--series auto\|e\|training] (--template \| --into) (--content report.json \| --auto ...) -o report.docx` |
| `popup.py` | **统一弹窗**(远程帮修抓注意力):中文写 UTF-8 临时文件 → `notify_popup.ps1 -WindowStyle Hidden`(只弹对话框、不留空白窗)→ detached | `popup.py "中文消息" [--title T]` |
| `notify_popup.ps1` | 底层弹框(BurntToast→Forms.MessageBox→msg.exe→响铃);**ASCII 脚本**,中文走 `-MessageFile`(UTF-8)。一般由 `popup.py` 调用 | `notify_popup.ps1 -MessageFile x.txt` |
| `live_tail.ps1` | 实时日志窗口:**立刻打印已有内容** + StreamReader 150ms 低延迟跟随 + 绝对路径 + UTF-8 + 着色(由 ssh_runner 自动拉起) | `live_tail.ps1 -Path <abs run.log>` |

## report.json 结构(给 fill_report.py 的内容规格,由 Claude 产出)
块类型:`para`(text)、`code`(code, lang)、`image`(path, caption)、`caption`(text)、
`step`(n, text, image?, caption?, code?, lang?)。学号占位由 fill_report 自动按配置替换。
```jsonc
{
  "sections": {
    "purpose":    [ {"type":"para","text":"任务4.1 ……;任务4.2 ……"} ],
    "materials":  [ {"type":"para","text":"JDK8 / IDEA / Hadoop3 / MariaDB / emp.csv …"} ],
    "process":    [ {"type":"step","n":"4.1.1","text":"使用 hadoop 登录 NodeA",
                     "image":"runs/e04/shots/step-4.1_1.png","caption":"登录并提权","code":"su hadoop","lang":"shell"} ],
    "conclusion": [ {"type":"image","path":"…","caption":"7 条查询结果"},
                    {"type":"code","code":"select * from empNNN;","lang":"hiveql"} ],
    "summary":    [ {"type":"para","text":"实验遇到的问题及解决方法:……"},
                    {"type":"para","text":"心得体会:……"} ]
  }
}
```

## 脱敏约定(所有脚本统一)
`lab_config.json` 里标 [敏感] 的值(各类密码),在写 `run.log`、`plan.json`、`state.json`、终端打印、截图前,
统一用其字符串做替换 → `***`。交互应答喂入 SSH 通道的瞬间才用明文,且该瞬间不写日志原文。

## 产物文件格式(放 `runs/<eNN>/`)
- `plan.json` —— 见 `references/tutorial-structure.md` 的字段定义。
- `state.json` —— `{ "cursor": {"subtask":"4.1","step":3}, "steps": {"4.1#1":"done", ...}, "issues":[{symptom,fix,subtask}], "blocked": null|{step,reason} }`
- `run.log` —— 每步一段:`### <subtask>#<idx> <text>` / `$ <cmd 脱敏>` / `<stdout+stderr 脱敏>` / `[exit N]`。
