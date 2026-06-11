# hadoop-lab-report 使用示例

> 把一篇 [heisun.xyz](https://heisun.xyz/docs/hadoop-e/) 的 Hadoop 实验教程网址丢给 Claude，它就会：
> **读教程 → 在你的虚拟机上 SSH 真跑 → 终端截图 → 按湛江科技学院模板排版成 Word 实验报告**，直到交付。
>
> skill 本体在本仓库 [`../skill/hadoop-lab-report/`](../skill/hadoop-lab-report/)，详细说明见它自带的
> [`README.md`](../skill/hadoop-lab-report/README.md)。本页只给一个**最常用的一句话用法**。

⚠️ **学习辅助工具**：用于把"自己真做过的实验"整理成规范报告并留存证据（真实命令 + 真实输出 + 真实截图），
不是替你伪造实验。请遵守课程的学术诚信规定。

---

## 0. 先装好（一次性）

1. 把 [`skill/hadoop-lab-report/`](../skill/hadoop-lab-report/) 整个文件夹放到 Claude 的 skills 目录，让 Claude 能发现它：
   ```
   C:\Users\<你>\.claude\skills\hadoop-lab-report\     # Windows
   ~/.claude/skills/hadoop-lab-report/                 # macOS / Linux
   ```
2. 装 Python 依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 前提：Windows + 装了 **Word**（转模板用）、**Edge**（截图用，系统自带）、**Python 3.10+**、
   **[Claude Code](https://claude.com/claude-code)**，且你的 **实验虚拟机已就绪、能从本机 SSH 连上**。

---

## 1. 一句话开跑（以 P5 / hadoop-e05 为例）

在 Claude Code 的对话里**直接说**（会自动触发本 skill）：

```text
用 hadoop-lab-report skill 帮我跑 P5 实验并续写报告，教程地址
https://heisun.xyz/docs/hadoop-e/hadoop-e05

最终报告放工作目录根、命名 …-P5-完成.docx。

使用前记得备份虚拟机状态 NodeA、B、C（快照）

需要将老师发的 Hadoop 文件夹也拷贝入 Claude Code 的工作目录
```

就这么一段。Claude 会读你工作目录里的 `lab_config.json`（身份/连接信息）→ 抓教程 → 预检 SSH →
逐步执行（你能**实时看到终端输出**）→ 截图 → 排版，最后把报告放到工作目录根、命名 `…-P5-完成.docx`。

---

## 2. 这段话里几个「前置动作」为什么要写

| 你写的这句 | 为什么 / 它会怎么处理 |
|---|---|
| **备份虚拟机快照 NodeA、B、C** | 实验会真改虚拟机（装服务、改配置、写 HDFS/HBase）。**跑之前先在 VirtualBox 给三台节点各打一个快照**，万一搞挂了能一键回滚。这一步是 GUI 操作、skill 不替你点，所以提前自己做好。 |
| **把老师发的 Hadoop 文件夹拷进工作目录** | 有些实验要用老师下发的安装包/数据文件（如 `HadoopDemo/`、jar、样例数据）。先放进 Claude Code 的工作目录，跑的时候才能被 `scp` 上传到虚拟机 / 被脚本引用。注意 `.gitignore` 已把 `HadoopDemo/`、`*.tar.gz` 等排除，**不会误传到 Git**。 |
| **报告放工作目录根、命名 `…-P5-完成.docx`** | 默认产物在 `runs/<eNN>/report.docx`；这里显式指定了最终落点和命名，Claude 会按要求把成品拷到工作目录根目录。 |
| **「续写报告」** | 若工作目录里已有前几趴（P1–P4）的同一份报告，Claude 会**往现有文档里接着填 P5**，而不是新开一个，保持一份完整报告。 |

---

## 3. 卡住了会怎样

跑的过程中若某节点 SSH 不通、或遇到要人工 / GUI 的步骤，Claude **不会直接退出**：它会停下来说清楚卡在哪、
弹一个 Windows 提醒，等你处理好回一句「继续」，再**从断点接着跑**，不用重头来。

---

## 4. 安全提醒

- 密码/口令**只**存在你工作目录的 `lab_config.json`，脚本读后在所有日志/截图/报告里都打码成 `****`。
- `.gitignore` 已排除 `lab_config.json`、`runs/`（含真实日志截图）、`HadoopDemo/`、安装包等——**别手滑 push 上去**。
- 截图与日志含你的真实命令与输出，公开分享前自查一下有没有敏感信息。

---

> 换教程同理：把 `hadoop-e05` 换成 `hadoop-e01`～`hadoop-e07`（对应 P1–P7）即可，身份/连接信息**零重填**。
