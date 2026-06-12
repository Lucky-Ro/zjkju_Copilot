# heisun.xyz e0* 教程页结构与解析规则

适用网址:`https://heisun.xyz/docs/hadoop-e/hadoop-eNN/`(NN = 01–07,对应 P1–P7)。
页面是**服务端渲染的 HTML**(原始 HTML 里就有标题与代码块,无需无头浏览器),`parse_tutorial.py`
直接 `GET` 后用 HTML 解析即可。编码为 UTF-8。

## 标题层级(以 e04 实测为准)

```
H1  → 实验标题          例:"P4 - Hive 数据库实验"        → 报告「实验名称」(连同 P 号)
H2  → 子任务 / 小节标题
       ├─ "任务N.M - xxx"   例:"任务4.1 - 部署 Hive"        ← 一个子任务的开始
       └─ "【...】" 区块标题(与子任务标题同为 H2):
            【任务目的】【任务环境】【任务资源】
            【任务说明】或【任务内容】【任务步骤】【常见问题】
H3  → 【常见问题】下的具体条目  例:"1. 在 Hive 执行 show tables 报错 MetaException 异常"
```

**关键**:`【...】` 区块标题与 `任务N.M` 标题**同为 H2**,所以解析必须**顺序扫描**:遇到
`任务N.M` 就开一个新子任务;后续的 `【...】` H2 都归到当前子任务,直到下一个 `任务N.M`。
`【常见问题】` 下的 H3 是其子条目。也有些教程开头有「本版本/版本说明」之类的 H2,归到一个 `_preamble`。

## 每个子任务要抽取的字段(写进 plan.json)

```jsonc
{
  "subtask_id": "4.1",
  "title": "部署 Hive",
  "purpose": "……【任务目的】正文……",        // → 报告「实验目的」
  "environment": "……【任务环境】正文……",     // → 报告「实验内容及实验器材」
  "resources": "……【任务资源】正文……",       // → 同上;含安装包清单
  "description": "……【任务说明/内容】正文……",
  "steps": [ /* 见下 */ ],
  "common_issues": [
    { "symptom": "show tables 报错 MetaException", "fix": "……解决办法正文……" }
  ]
}
```

## 步骤(steps)抽取规则

【任务步骤】正文里,**有序步骤**通常是「文字说明 + 紧跟的代码块」。每个 step:

```jsonc
{
  "idx": 3,
  "text": "创建员工表,注意替换为你的学号后3位。",  // 步骤说明(排版时作为图注/段落)
  "code": "create table emp你的学号后3位(...);",   // 已剥掉 hive>/mysql>/$ 提示符的可执行命令
  "lang": "shell|hiveql|sql|xml|zk|hbase|scala|interactive|null", // 见下「语言判定」
  "repl": "hive|mysql|hbase|zk|spark|null",     // 命令要送进哪个交互会话(由提示符前缀或上下文推出)
  "target_node": "nodea",                       // 说明里点名的节点;否则继承上一步
  "interactive": true,                          // lang==interactive 时为 true
  "kind": "auto|author|manual|note",            // 见下「kind 判定」
  "needs_sid": true,                            // 含学号占位,执行/排版前替换
  "expect_output": "……教程贴出的预期输出……"      // 用于执行后校验;author 类题目靠它对答案
}
```

**提示符剥离**:代码块里 `hive> ` / `mysql> ` / `MariaDB [..]> ` / `hbase(main):NNN:0> ` /
`[zk: host:2181(CONNECTED) N] ` / `scala> ` / `$ ` / `# ` 等前缀会被剥掉,存进 `code` 的是
「干净可执行」的命令,并据前缀推出 `repl`(送进对应交互会话执行)。

**裸命令块的 REPL 归属**(教程常给不带提示符的裸命令,如单独的 `create -e /x`、`get /x`、`list`):
按「子任务级上下文 + 动词白名单」判定——某代码块含 `zkCli.sh` / `hbase shell` / `spark-shell` 等
**启动命令**即为该子任务建立「活跃 REPL 上下文」;之后无提示符的块,若**每非空行首词都属于该 REPL 的
命令动词**(zk:`create/get/set/delete/ls/stat/getAcl/sync/addauth…`;hbase:`create/list/scan/put/get/
disable/drop…`)且不含 shell 元字符(`|`/`&&`/`>` 等),则判为送进该 REPL。**保守**:无上下文时绝不把
裸 `ls /`/`get` 误判成 REPL(降低把 shell 命令误塞进 zkCli 的概率)。判不准时 Claude 可手改 `plan.json` 的 `repl`。

**「期望结果」路由**:某代码块前的文字若含「期望结果/结果如下/运行结果」等,则该代码块是**预期输出**,
放进 `expect_output`、`code` 留空——这类是「**要求你自己写 HiveQL**」的题目(如 P4 后 7 问),
命令由 Claude 生成、执行,再与 `expect_output` 对答案。

### 语言判定(代码块)
HTML 里代码块形如 `<pre><code class="language-xxx">`。
- `language-sql` → `lang: "sql"`(HiveQL / MySQL,送进 `hive`/`mysql` 执行)。
- `language-xml` → `lang: "xml"`(配置文件内容,用 heredoc 写到目标文件,**绝不 vi**)。
- **无语言标签** → 默认 `lang: "shell"`(普通命令)或 `interactive`(命令内含 `mysql_secure_installation`、
  `ssh-keygen`、`ssh-copy-id`、`hive` 进入交互、`mysql -p` 等)。识别到交互命令时,从正文/配置里找应答值。

### 交互命令的应答来源
教程通常**已经把要输入的值写在说明里**(如「输入 y」「设置密码为 xxx」)。把这些抽进 `interactive[]`。
凡涉及密码(MariaDB root、hive 用户等),应答值写成占位 `"<from config: 字段名>"`,执行时由
`ssh_runner.py` 从 `lab_config.json` 取真值喂入,**不落盘明文**。

### 学号占位
步骤文字 / 代码 / 表名 / 主机名里出现「学号后3位 / 替换为你学号后3位 / nodea+你学号后3位」等,
解析阶段**保留原文 + 打标 `needs_sid: true`**;执行与排版阶段统一替换为 `student_id_last3`。
替换细则见 `report-template.md`。

## auto / manual 判定(阶段 2 用)

标 `manual`(不可在 SSH 终端自动完成,列入「前置条件」让用户确认/操作):
- VirtualBox 克隆虚拟机、导入/导出 appliance。
- 宿主机/虚拟机**网卡配置、网络模式**(Host-Only/NAT/桥接)、第一次设静态 IP 导致 SSH 才能通之前的步骤。
- 浏览器访问 Web UI 并查看/截图:NameNode `:9870`、YARN `:8088`、HDFS 浏览页等。
- 任何明确「在 VirtualBox 界面 / 图形界面 / 浏览器里点」的操作。

其余(在 shell 里敲命令、写配置、跑 SQL/HiveQL、启停服务、`jps`/`hdfs dfs`/`yarn` 等)标 `auto`。

另两类:`author` = 教程只给了**要求 + 期望结果**、要你**自己写命令**(如 P4 的 7 条查询),由 Claude 生成
HiveQL 后执行并对 `expect_output` 校验;`note` = 纯说明文字,无命令(排版时作上下文)。只有 `manual` 进
「前置条件清单」让用户操作。

判断不准时,**宁可标 manual 并问用户**,也不要盲目自动执行有副作用的步骤。

## 解析健壮性提示
- 不同教程小节命名可能略有差别(【任务内容】vs【任务说明】、个别缺【常见问题】),解析按「H2 文本是否被
  `【】` 包裹」来归类,不要硬编死六个名字。
- 代码块里 heisun 站点偶有行号/复制按钮的额外 HTML,取 `<code>` 纯文本即可。
- 解析完成后,把 `plan.json` 的子任务数、步骤数、manual 步骤数打印出来给用户过目。
