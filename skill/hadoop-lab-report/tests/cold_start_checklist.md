# 冷启动回归探针(每次改 skill 后照跑)

> 思路:冷启动子代理无法交互,所以**不测「正确的全过程」,只断言「错误的特征信号」**——
> 这些信号稳定、可自动化、与实现细节解耦。四类探针全绿才算过。
> 注:旧的身份门禁(指纹黑名单 / 身份绑定元数据 / 换机重确认)已废止——身份改由弹窗交互索取,
> `--validate` 只查缺项/占位/格式。

## 探针 1 · 空配置:阶段 0 即停、自动弹窗,零产物

在一个**没有** `lab_config.json` 的干净目录冷启动跑任意教程:

**断言**:
- [ ] 流程停在阶段 0(收身份),**没有**生成 `runs/<eNN>/run.log`;
- [ ] 发起的是**弹窗交互索取**(主流程调用 `python scripts/collect_config.py --popup`,弹出新控制台跑
  `--interactive`),**不是**只打印一条命令/路径让用户自己开终端;
- [ ] skill 目录内**没有**被写入任何 `lab_config.json` / `series_defaults.json`(只许落项目目录)。

## 探针 2 · 路径边界:写配置/缺省值到 skill 目录被拒

故意把输出路径指向 skill 目录运行写盘脚本:

```powershell
python scripts/collect_config.py --autofill --config <skill>\assets\x.json
python scripts/build_series_kb.py --out-dir <skill>\references
```

**断言**:
- [ ] 两条都**非零退出(exit 2)**,stderr 出现「拒绝把配置/缺省值写入 skill 目录」;
- [ ] skill 目录内**未新增**任何文件(`lab_config.json` / `series_defaults.json` / `series-defaults.md` 都没出现)。

## 探针 3 · 日志洁净:产物里无明文密码、skill 目录无真实信息

跑完任意流程(或拿历史 `runs/` 产物)后:

```powershell
# 明文密码 0 命中(用 lab_config.json 里的真实值逐一查)
Select-String -Path runs\*\run.log, runs\*\*.json -Pattern "<逐一填真实密码>"
```

**断言**:
- [ ] `run.log` / `plan.json` / `state.json` / `live.md` / `report.docx`(解包后的 document.xml)
  中**不含任何明文密码**(全部为 `****`);
- [ ] **skill 目录全量 grep**:无 `lab_config.json` 实例、无 `series_defaults.json`、无 `series-defaults.md`、
  无任何真实账号/密码/IP;真人姓名/学号/地点/教师 **0 命中**;学号仅以 `NNN` 占位形态存在;
- [ ] 旧门禁相关符号(身份指纹黑名单、身份门禁函数、身份绑定元数据字段等)全仓库 grep **0 命中**
  (门禁已彻底删除——身份改由弹窗交互索取)。

## 探针 4 · 子代理实时窗口

以方式 B(子代理冷启动)跑 `ssh_runner.py --run`(或 `--preflight`):

**断言**:
- [ ] stderr 出现 `[live] 已打开实时日志窗口`,用户侧弹出独立控制台并随 `run.log` 滚动;
- [ ] 全程**没有**调用 `powershell -ExecutionPolicy Bypass`(会被安全分类器拦)。
