# scripts/ —— 脚本清单与接口(已实现并自测)

确定性、重复性的重活交给脚本,SKILL.md 只做编排。所有脚本共用 `_common.py`(配置加载、密码打码、
学号派生、URL→eNN、UTF-8 输出修复)。

## 依赖(执行机 = Windows + Python 3.14,已装)
`paramiko`(SSH)、`requests` + `beautifulsoup4`(抓/解析教程)、`python-docx`(填报告)。
终端截图用 Win 自带 **Edge** 无头模式(零额外安装)。模板 `.doc`→`.docx` 用 **Word COM**(本机有 Office)。
预览/校验报告可用 `pymupdf`(可选)把导出的 PDF 渲染成图。docx skill 的 `validate.py` 在 Windows 上读 XML
会按 GBK 报假错,**以「Word 能否打开/导出 PDF」为准**。

| 脚本 | 职责 | 关键接口 |
|---|---|---|
| `collect_config.py` | 教程缺省**直接落盘**(`--autofill`,不问用户、已有不覆盖)、**弹新控制台**收身份(`--popup` 跑 `--interactive` 完后自动校验、缺项再弹)、完整性校验(缺项/占位/格式,**无身份门禁**)、派生 `student_id_last3`、脱敏回显。写盘前过 `ensure_outside_skill` 边界。 | `--autofill [--tutorial URL]` / `--popup` / `--interactive` / `--validate` / `--show` / `--derive` `[--config ...]` |
| `parse_tutorial.py` | 抓教程 HTML → `plan.json`(子任务/步骤/命令/`lang`/`repl`/`kind`/`needs_sid`/`expect_output`/常见问题) | `<url> -o plan.json` |
| `ssh_runner.py` | paramiko 持久 shell:**实时逐行回显**(命令加 `>> ` 前缀,tee 进 `run.log` 兼作截图源);**启动自动弹实时窗口**(`--no-window` 关);交互应答自动喂入;`repl` 走 `hive -f`/`mysql`;heredoc 写配置;`state.json` 断点续跑;`****` 打码;`--preflight` 写 `preflight.json`(含 `missing[]`/`ready`) | `--preflight PLAN` / `--run PLAN [--continue-on-error] [--no-window]` / `--probe NODE` |
| `build_series_kb.py` | 抓 P1–P7 全系列 → **项目目录** `./series_defaults.json` + `./series-defaults.md`(缺省密码/IP/主机名/端口/包;含真实缺省值,过边界不进 skill 目录) | `[--max 7] [--out-dir .]`(在项目目录重建知识库) |
| `render_shot.py` | `run.log`(按 `### ` 分段)→ 深色终端 PNG(Edge 无头,2x 清晰);也支持单段即时渲染 | `--from-log run.log --out shots/`  或  `--title T --cmd C --output-text O --out x.png` |
| `convert_template.py` | `干净的模板.doc` → `assets/template.docx`(Word COM 优先,soffice 备选) | `[in.doc] [out.docx]`(缺省即转 bundle) |
| `fill_report.py` | python-docx 编辑**现有**模板:填表头 + 各栏目填段落/截图/#FFF2CC 代码块嵌表;**易读排版**(1.5 行距/首行缩进/步骤留白);`--into` 续写时裁末尾空白再追加 | `--config ... (--template 从零 \| --into 续写) (--content report.json \| --auto ...) -o report.docx` |
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
