# 远程帮修电脑模式 —— 暂停/续跑协议

目标:遇到你搞不定、必须用户在他那头动手的情况(典型:**网卡没配好导致 SSH 不通**、VirtualBox 里要点、
浏览器里要登录),像朋友远程帮修电脑那样**停在原地说清楚**,但**不结束、不丢进度、不断会话**。

## 为什么能「无缝续跑」
进度不在对话里,而在磁盘:`lab_config.json`(配置)、`runs/<eNN>/plan.json`(计划)、
`runs/<eNN>/state.json`(进行到第几步)、`runs/<eNN>/run.log`(已发生的一切)。
只要这些文件在,任何时候都能从 `state.json` 的游标接着跑。**所以暂停 ≠ 重来。**

## 远程长任务用 tmux(SSH 断了也不丢)
在节点上跑耗时/会被网络中断打断的命令时,包进持久会话:
```bash
tmux new-session -d -s labrun 'set -o pipefail; <command> 2>&1 | tee -a ~/labrun.out'
# 重连后看进度:
tmux capture-pane -pt labrun -S -200
```
`ssh_runner.py` 对 `kind:"long"` 的步骤自动走 tmux;SSH 掉线重连后用 `capture-pane` 把输出补回 `run.log`。

## 暂停时要做的三件事
1. **不要 abort、不要清空进度。** 把当前步骤在 `state.json` 标为 `blocked`,写明 `blocked_reason`。
2. **在对话里讲清楚四点**(像帮人修电脑):
   - 卡在**哪一步**(子任务 + 步骤序号);
   - **报什么错**(贴 `run.log` 里的关键几行,已脱敏);
   - **需要你手动做什么**(具体到「在 VirtualBox 里…/在浏览器打开 http://…:9870 截图给我」);
   - 做完**回复什么继续**(约定一个词,如「好了」「继续」)。
3. **弹一个 Windows 提醒抓注意力** —— 用封装好的 `popup.py`,一行搞定(中文 OK):
   ```
   python scripts/popup.py "卡在 4.1 第3步,需要你配一下网卡,弄好回我『继续』"
   ```
   `popup.py` 已处理三个坑:① 中文写进 UTF-8 临时文件再用 `-MessageFile` 传(PowerShell 5.1 命令行按 GBK 会乱码);
   ② 用 `-WindowStyle Hidden` 且不带 `-NoExit`——**只弹对话框,不留空白 PS 控制台**;③ detached 启动,不阻塞主流程。
   底层 `notify_popup.ps1` 仍是先检测再选(BurntToast → System.Windows.Forms.MessageBox → `msg.exe` → 响铃),
   Win10 家庭版也能弹。**提醒文案里绝不含密码。**

   > 注:`ssh_runner.py --run/--preflight` 启动时已**自动弹出实时日志窗口**(`live_tail.ps1`),用户能实时看到在干啥;
   > `popup.py` 是另起的一次性「抓注意力」提醒,二者互不冲突。

## 收到「继续 / 好了」后
1. **先重新核对那个被卡的条件**,别假设已好:
   - SSH 不通 → 用 `ssh_runner.py --probe <node>` 重测能否登录、节点间能否互通;
   - 网页/GUI 步骤 → 确认 `runs/<eNN>/manual/` 里已有用户给的截图。
2. **通过**:把该步从 `blocked` 改回继续,从 `state.json` 游标**接着往下跑**。
3. **仍不通**:再讲一次「现在卡在哪、还差什么」,继续等待。不要反复盲目重试或退出。

## 心态
你是「停下来等」,不是「失败退出」。用户那头照做、回一句话,你就从刚才那一步接着跑——全程一个会话、一份磁盘状态。
