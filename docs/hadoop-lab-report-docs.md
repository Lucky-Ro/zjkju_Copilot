# hadoop-lab-report SKILL 使用文档

> 把一篇 [黑隼 heisun.xyz](https://heisun.xyz/docs/hadoop-e02/) 的 Hadoop 实验教程网址丢给该skill，它就会：
> 读教程 → 在你的虚拟机上跑 → 截图 → 生成 Word 实验报告
> 
>**你就可以直接交作业啦：）**
>
> skill 本体在本仓库 [`skill/hadoop-lab-report/`](../skill/hadoop-lab-report/)，详细说明见它自带的
> [`README.md`](../skill/hadoop-lab-report/README.md)。本页给一个**简单的教程**。

！！ **学习工具无好坏**：请请遵守课程规定酌情使用，出现问题本工具概不负责。

---

## 0. 第零步 —— 开始前的准备

1. 安装好任意一个agent。 **[Claude Code](https://claude.com/claude-code)** 或者 **[Codex](https://chatgpt.com/zh-Hans-CN/codex/)** （可能需要科学网络环境）
2. 搭配[CCSwitch](https://ccswitch.io/zh/)以使用国产模型
> [在 Codex 中使用 DeepSeek（超链接）](https://ccswitch.io/zh/tutorials/codex-deepseek-routing-guide)

> [在 Claude Code 中使用 Deepseek](https://www.bilibili.com/video/BV1pQRNBsEGs/)
3. 把 [`skill/hadoop-lab-report/`](../skill/hadoop-lab-report/) 整个文件夹放到 Claude 的 skills 目录，让 Claude 发现它：
   ```
   C:\Users\<自己的用户名>\.claude\skills\hadoop-lab-report\     # Windows
   ```
4. 你的 **实验虚拟机已就绪，并可以连接FianlShell**。
5. 新建一个文件夹；在 Claude Code 中选择该文件夹作为工作目录（让AI在文件夹中写文档）。需要将老师发的 Hadoop 文件夹拷贝入该文件夹。

---

## 1. 一句话开跑（以 P5 / hadoop-e05 为例） Codex同理

在 Claude Code 的对话里**直接说**：

```text
用 hadoop-lab-report skill 帮我跑 P5 实验并续写报告，教程地址
https://heisun.xyz/docs/hadoop-e/hadoop-e05

最终报告放工作目录根、命名 …-P5-完成.docx。
```

就这么一段。**程序会弹窗搜集你的姓名学号信息**（保存在本地）→ 看教程 → 连接虚拟机 →
逐步执行→ 截图 → 排版，最后生成报告。
快快去交作业吧 ：）

---
# ！！使用前记得备份虚拟机状态 NodeA、B、C（给虚拟机拍快照）！！
---

## 3. 卡住了会怎样

跑的过程中若出现问题、
程序会弹一个提醒，并引导你处理再**接着跑**，不用重头来。

---

> 换教程同理：把 `hadoop-e05` 换成 `hadoop-e01`～`hadoop-e07`（对应 P1–P7）即可，身份/连接信息**不需要重新填写**。
