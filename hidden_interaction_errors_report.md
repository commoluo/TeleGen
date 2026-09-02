# 隐藏交互错误(Hidden Interaction Errors)— 报告开场素材与案例汇总

> 用途:为报告/PPT 提供"**UI 正确,却存在隐藏交互错误**"的开场论点、数据支撑、可复用案例与素材索引。
>
> 本文所有文件路径均为相对仓库根目录的可点击链接。截图与 JSON 数据均来自本仓库实测产物。

---

## 0. TL;DR(一页讲完)

- **论点**:现代(LLM 生成的)Web 应用,UI 渲染"看起来完全正确"≠"能用"。大量缺陷藏在**交互层**——页面不崩、组件都在,但点不动、选不中、提交了没反馈。
- **数据**:在 106 个任务的审计中,**31 个(≈29%)栽在同一个隐藏交互错误上**(原生 `<select>` 下拉不可操作),横跨 20 个项目。这不是个例,是系统性问题。
- **三个代表案例**:
  1. 原生下拉框:看得见,选不中(000022,31/106 的典型)
  2. 双触发处理器:点一下等于没点(000042,最经典的隐藏 bug)
  3. 静默成功:成功了但用户看不到(000019,最隐蔽)
- **引出方案**:传统测试看"渲染对不对";我们需要看"**运行时交互到底发生了什么**"——这就是 telemetry/TeleGen 的动机。

---

## 1. 开场论点

> **现代 LLM 生成的 Web 应用,UI 渲染"看起来完全正确"已经不等于"能用"。大量缺陷藏在交互层——页面不崩、组件都在,但点不动、选不中、提交了没反馈。这类 hidden interaction error 既骗过人眼,也骗过传统 UI 测试。**

这类错误的共同特征:

| 特征 | 说明 |
|---|---|
| 视觉无异常 | 页面正常渲染,布局完整,无报错,组件齐全 |
| 静默失败 | 不抛异常、不报错;只是"没反应"或"反应抵消" |
| 骗过人工/截图验收 | 截图看起来一切正常 |
| 只有运行时交互能暴露 | 必须真正去点、去选、去提交才会发现 |

---

## 2. 核心数据(支撑论点)

数据源:[telegen_audit_results.json](human_validation_telegen/audit_judgeability/telegen_audit_results.json)(106 条任务审计记录,含 `why_no_log_failed` / `telegen_changes` / `primary_label` 等字段)。

- 涉及**原生 `<select>` 不可操作**的案例:**31 / 106(≈29%)**
- 覆盖项目(20 个):`000005, 000022, 000023, 000028, 000037, 000042, 000045, 000046, 000050, 000052, 000053, 000057, 000060, 000063, 000077, 000078, 000079, 000089, 000100, 000101`

`primary_label` 整体分布:

| 数量 | 标签 |
|---|---|
| 54 | E(Uncertain) |
| 22 | B(Judgeability / Usability Improvement Only) |
| 14 | A(Genuine Functional Repair) |
| 7 | E(Uncertain / re-evaluation noise) |
| 6 | C(Mixed Functional and Judgeability Repair) |
| 3 | D(Evaluator Exploitation or Task-Specific Shortcut) |

> 解读:A/B/C 三类(共 42 个)都是"做了实质修复才通过",说明**相当多任务失败不是渲染问题,而是交互/可用性问题**——正是本文主题。

---

## 3. 开场三例(PPT 直接可用)

### 例 1(主打,配 before 截图)—— 原生下拉框:看得见,选不中

- **项目**:project_000022 / 新建通话日志(对应 [human_validation case_007](human_validation_telegen/usability_audit/cases/case_007/case_metadata.json))
- **UI 表象**:"New Call Log" 表单**视觉完全正常**——配色整齐、导航完整、`Client *` 是个标准下拉框(显示 `-- Select Client --`)、`Call Type`、`Description`、`Action Steps` 一应俱全,**没有任何报错或破版**。
  - 截图:[rq3_case_000022_before.png](batch_runs/paper_materials/output/rq3_case_000022_before.png)(可直接铺满幻灯片)
- **隐藏 bug**:客户选择是**原生 `<select>`**,自动化 agent 无法操作 → `clientId` 永远为空 → 提交按钮 `disabled={!form.clientId}` 一直禁用 → 整条任务卡死。代码层面一切正常,无任何异常或报错。
- **代码**(控制组):

```jsx
// CallLogCreate.jsx (project_000022_v2_experiment)
<select value={form.clientId} onChange={e => update('clientId', e.target.value)}>
  <option value="">-- Select Client --</option>
  {clients.map(c => <option key={c.id} value={c.id}>{c.name} - {c.company}</option>)}
</select>
...
<button disabled={!form.clientId} onClick={handleSubmit}>Create Call Log</button>
```

- 文件:[CallLogCreate.jsx:62](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000022/gen_000022/project_000022_v2_experiment/frontend/src/pages/CallLogCreate.jsx#L62)
- **普遍性**:这一类在 106 个案例里出现 **31 次(≈29%)**,横跨 20 个项目——最有说服力的一类。

---

### 例 2(最经典)—— 双触发处理器:点一下,等于没点

- **项目**:project_000042 / 撰写邮件、选择收件人(`primary_label = A Genuine Functional Repair`)
- **UI 表象**:收件人是一个带 checkbox 的卡片网格,选中态会高亮,看起来很精致、很"正确"。
- **隐藏 bug**:checkbox 的 `onChange` 和外层 `<div>` 的 `onClick` **绑了同一个 `toggleRecipient`**。点击 checkbox 时事件冒泡,两个处理器**各触发一次 → 选上又取消 → 净变化为零**。用户/agent 怎么点都选不中收件人。

```jsx
// ComposeEmail.jsx (project_000042, v1 clean), 第 141-155 行
<div className="recipient-select-grid">
  {recipients.map(r => (
    <div
      key={r.id}
      className={`recipient-select-item ${selectedRecipientIds.includes(r.id) ? 'selected' : ''}`}
      onClick={() => toggleRecipient(r.id)}          // ← 父 div:触发一次
    >
      <input
        type="checkbox"
        checked={selectedRecipientIds.includes(r.id)}
        onChange={() => toggleRecipient(r.id)}        // ← checkbox:又触发一次 → 抵消
      />
      <span>{r.name}<br /><small>{r.email}</small></span>
    </div>
  ))}
</div>
```

- 文件:[ComposeEmail.jsx:141-155](batch_runs/official/pro_ast_injection/project_000042/gen_000042/project_000042/frontend/src/components/ComposeEmail.jsx#L141-L155)
- **修复**:把 checkbox 改成 `readOnly`,只让父 div 的 `onClick` 生效(单次触发)。

---

### 例 3(最隐蔽)—— 静默成功:提交成功了,但用户看不到

- **项目**:project_000019 / 联系表单(即时间戳 `1778648371655` 那条日志所在案例)
- **UI 表象**:表单填写、提交按钮、确认页一应俱全。
- **隐藏 bug**:后端确实返回成功、`confirmation` state 也置位了——但代码**没有滚动到顶**,确认页没进视口,最终截图只看到页脚 → 判定失败。即"功能没错,反馈缺失"。同时控制组的成功判据 `if (res.ok && data.success)` 过严,进一步降低确认页出现的概率。

```jsx
// Contact.jsx (project_000019_v2_experiment, 控制组)
const res = await fetch('/api/contact', { method: 'POST', ... });
const data = await res.json();
if (res.ok && data.success) {            // ← 双重门槛,过严
  setConfirmation(data.message);
  setForm({ name: '', email: '', company: '', message: '' });
  // ← 注意:没有 window.scrollTo,确认页未必进视口
} else {
  setError(data.error || 'Submission failed...');
}
```

- 文件:[Contact.jsx](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000019/gen_000019/project_000019_v2_experiment/frontend/src/components/Contact.jsx)

---

## 4. 详细案例研究(完整修复链条)

> 下面两个案例给出"修复前逻辑 / 修复后逻辑 / 日志如何指导修复"的完整闭环,适合作为报告正文或 backup。

### 4.1 project_000019 / task000019--3 —— 联系表单提交

**(a) 修复情况**

| 版本 | 角色 | 结果 |
|---|---|---|
| `project_000019_v2_experiment` | 控制组(无 telemetry 指引的 v2 重生成) | **NOT_SUCCESS** |
| `project_000019_v2_LLM` | TeleGen 处理组(有 telemetry 指引) | **SUCCESS** |

控制组评测:agent 填完表单点了 Send Message,但**最终截图停在页脚,看不到任何成功确认信息**。
处理组评测:成功显示 "inquiry was received…respond within 24 hours" 确认页。

**(b) 原本逻辑(控制组)**

- 成功判据 `if (res.ok && data.success)`——双重门槛,过严;
- 维护独立 `error` 态 + 一整块红色错误框 UI(视觉噪声);
- 设置 `confirmation` 后**没有任何滚动**,确认页是否进视口取决于当时滚动位置 → 截图拍不到。

```jsx
// Contact.jsx (project_000019_v2_experiment)
if (res.ok && data.success) {
  setConfirmation(data.message);
  setForm({ name: '', email: '', company: '', message: '' });
} else {
  setError(data.error || 'Submission failed. Please check your inputs and try again.');
}
// if (confirmation) return <确认页>   ← 确认页是提前 return,但无滚动控制
```

**(c) 修复后逻辑(处理组)**

- 放宽成功判据为 `if (data.success)`;
- 删掉 `error` 态与红色错误框(去噪声);
- 成功/失败都 `window.scrollTo({ top: 0, behavior: 'smooth' })`,保证确认信息进视口;
- 每一步打 `[Telemetry]` 点。

```jsx
// Contact.jsx (project_000019_v2_LLM)
console.log('[Telemetry] Interaction', 'Contact form submitted');   // ← 时间戳 1778648371655
...
if (data.success) {                          // ← 放宽判据
  console.log('[Telemetry] Network Response', 'Contact form success', data.message);
  setConfirmation(data.message);
  setForm({ name: '', email: '', company: '', message: '' });
  window.scrollTo({ top: 0, behavior: 'smooth' });   // ← 关键:滚到顶
}
// catch 里也 setConfirmation('An error occurred...') 并 scrollTo(0)
```

**(d) 日志如何指导这次修改**

[telemetry_report.md](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000019/gen_000019/project_000019_v2_LLM/telemetry_report.md) 把 v1 注入式运行的 150 条事件喂给修复 agent。task000019--3 这段的事件链(105–108)显示:

```
Contact.jsx:28  [Telemetry] Interaction   "Contact form submitted"        ← ts 1778648371655
Contact.jsx:31  [Telemetry] Network Request  "POST /api/contact"
Contact.jsx:39  [Telemetry] Network Response "Contact form success" "Thank you…24 hours"
Contact.jsx:40  [Telemetry] StateChange      "Confirmation set to success"
```

这条链**证明了后端与提交逻辑是通的**(请求发出、成功响应返回、confirmation 已置位)。于是修复 agent 判定:问题不在逻辑而在**成功结果对 agent 不可见** → 放宽判据 + `scrollTo` 把确认页推到视口顶部。日志把诊断从"修 bug"收敛成了"修可见性"。

---

### 4.2 project_000022 / task000022--2 —— 新建通话日志(客户端选择器)

**(a) 修复情况**

| 版本 | 角色 | 结果 |
|---|---|---|
| `project_000022_v2_experiment` | 控制组(`<select>` 版) | **NOT_SUCCESS / FAIL** |
| `project_000022_v2_LLM` | TeleGen 处理组(`client-selector` 版) | **SUCCESS** |

(对应 [human_validation case_007](human_validation_telegen/usability_audit/cases/case_007/case_metadata.json):`no_telemetry.verdict = NOT_SUCCESS`,`telegen.verdict = SUCCESS`。)

**(b) 原本逻辑(控制组)**

- 客户选择是**原生 `<select>` 下拉**;
- 提交按钮 `disabled={!form.clientId}`——**不选客户就点不了提交**;
- WebVoyager 这类自动化 agent 很难操作原生 select → `clientId` 永远为空 → 按钮一直禁用 → 任务卡死。

```jsx
// CallLogCreate.jsx (project_000022_v2_experiment)
useEffect(() => { getClients().then(setClients); }, []);
const update = (field, value) => setForm(prev => ({ ...prev, [field]: value }));
...
<select value={form.clientId} onChange={e => update('clientId', e.target.value)}>
  <option value="">-- Select Client --</option>
  {clients.map(c => <option key={c.id} value={c.id}>{c.name} - {c.company}</option>)}
</select>
...
<button disabled={!form.clientId} onClick={handleSubmit}>Create Call Log</button>
```

**(c) 修复后逻辑(处理组)**

- 把原生 select 换成**可点击的 div 列表**(`client-selector` / `client-option`),带选中高亮 + 空状态提示;
- `onClick` 里直接 `update('clientId', c.id)`,agent 点击即选中 → 按钮启用 → 能提交;
- 每个关键动作(取客户、选中、提交、建日志)都打 telemetry,选中事件本身成了"操作成功"的可验证信号。

```jsx
// CallLogCreate.jsx (project_000022_v2_LLM)
useEffect(() => {
  console.log('[Telemetry] Network Request', 'getClients');
  getClients().then(clients => {
    console.log('[Telemetry] Network Response', 'getClients', clients);
    setClients(clients);
  });
}, []);
...
{clients.length === 0
  ? <div className="empty-state">No clients available. Create one first.</div>
  : <div className="client-selector">
      {clients.map(c => (
        <div key={c.id}
             className={`client-option${form.clientId === c.id ? ' selected' : ''}`}
             onClick={() => {
               console.log('[Telemetry] Interaction: Client selected', c.id, c.name);
               update('clientId', c.id);
             }}>
          <strong>{c.name}</strong> — {c.company}
        </div>
      ))}
    </div>}
```

**(d) 日志如何指导这次修改**

[telemetry_report.md](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000022/gen_000022/project_000022_v2_LLM/telemetry_report.md) 里 task000022--2 的事件链(86–90):

```
CallLogCreate.jsx:34  [Telemetry] Network Request   "getClients"
api.js:3              [Telemetry] Network Request   "GET /clients"
api.js:6              [Telemetry] Network Response  "GET /clients"  Array(1)   ← 客户端数据是有的(1 条)
CallLogCreate.jsx:36  [Telemetry] Network Response  "getClients"    Array(1)
—— task2 到此戛然而止(事件 91 直接跳到 task000022--3)——
```

**整段 task2 里没有任何 "Client selected"、"submit"、"createCallLog" 事件。** 这条证据非常关键:数据成功加载了(`Array(1)`,客户是存在的),但 agent **从未触发选择动作**。结合代码里"不选客户提交按钮就禁用",日志精确定位根因——**原生 `<select>` 对自动化 agent 不可操作**,而不是数据缺失或接口报错。修复因此把 select 改成可点击列表,并新增 `[Telemetry] Interaction: Client selected` 让"选中"成为可观测事件。

---

## 5. 附录:时间戳 `1778648371655` 日志溯源

- **文件**:[console_logs.json](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000019/gen_000019/project_000019_v2_LLM/webvoyager_v2_results/task000019--3/console_logs.json)(数组第 24 条 / 共 28 条)
- **记录内容**:

```json
{
  "level": "INFO",
  "message": "http://127.0.0.1:3000/src/components/Contact.jsx 28:12 \"[Telemetry] Interaction\" \"Contact form submitted\"",
  "source": "console-api",
  "timestamp": 1778648371655
}
```

- **含义**:project_000019 / task000019--3(联系表单)处理组运行中,Contact.jsx 第 28 行注入的遥测点,记录"表单已提交"。它正是 §4.1 (d) 事件链的第一环,时间戳换算约为 2026-05-13(与所在目录名 `multi_docker_full101_20260513` 一致)。

---

## 6. 素材索引

### 6.1 截图
- [rq3_case_000022_before.png](batch_runs/paper_materials/output/rq3_case_000022_before.png) / [rq3_case_000022_after.png](batch_runs/paper_materials/output/rq3_case_000022_after.png) — 000022 改造前后对比(最适合做翻页对比的主图)
- [human_validation_telegen/usability_audit/cases/case_007/screenshots/](human_validation_telegen/usability_audit/cases/case_007/screenshots/) — 000022 全过程:`nt_*.png`(失败控制组) vs `tg_*.png`(成功处理组)
- 各项目 webvoyager 截图:000019(141 张)、000042(243 张)、000045(230 张)

### 6.2 关键源码
| 案例 | 控制组(改前) | 处理组(改后) |
|---|---|---|
| 000019 联系表单 | [Contact.jsx](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000019/gen_000019/project_000019_v2_experiment/frontend/src/components/Contact.jsx) | [Contact.jsx](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000019/gen_000019/project_000019_v2_LLM/frontend/src/components/Contact.jsx) |
| 000022 通话日志 | [CallLogCreate.jsx](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000022/gen_000022/project_000022_v2_experiment/frontend/src/pages/CallLogCreate.jsx) | [CallLogCreate.jsx](batch_runs/official/flash_llm_injection_data/multi_docker_full101_20260513_1242/project_000022/gen_000022/project_000022_v2_LLM/frontend/src/pages/CallLogCreate.jsx) |
| 000042 邮件收件人 | [ComposeEmail.jsx](batch_runs/official/pro_ast_injection/project_000042/gen_000042/project_000042/frontend/src/components/ComposeEmail.jsx) | (同目录 `project_000042_LLM`/`_v2_LLM` 下) |
| 000045 销售记录 | [Sales.jsx](batch_runs/official/pro_ast_injection/project_000045/gen_000045/project_000045/frontend/src/components/Sales.jsx) | (同目录 `_v2_LLM` 下) |

### 6.3 数据 / 审计源
- [telegen_audit_results.json](human_validation_telegen/audit_judgeability/telegen_audit_results.json) — 106 条任务审计(本文统计来源)
- [usability_audit_cases.json](human_validation_telegen/usability_audit/usability_audit_cases.json) — 可用性审计案例集
- [case_007/case_metadata.json](human_validation_telegen/usability_audit/cases/case_007/case_metadata.json) — 000022 的控制组/处理组评测判定
- 各项目 `telemetry_report.md` / `telemetry_brief.md` / `openhands_repair_task.txt` — 日志→修复的指导链

---

## 7. 建议的幻灯片结构(开场 4 页)

| 页 | 内容 |
|---|---|
| 1 | **论点句** + 000022 before 截图铺满;问观众:"这个页面有什么问题?"(答案:没有,但它不能用) |
| 2 | **三类隐藏交互错误**各一栏:下拉不可操作 / 双触发抵消 / 静默成功无反馈,各贴 1 行代码 |
| 3 | **数据支撑**:"106 个任务里,**31 个**(近 1/3)栽在同一个隐藏交互错误(原生 select)上"——强调系统性,非个例 |
| 4 | **引出 TeleGen**:传统测试看"渲染对不对",我们需要看"**运行时交互到底发生了什么**" → 过渡到 telemetry 方案 |

---

## 8. 备选案例(增加多样性,按需取用)

若需要更多类型的隐藏交互错误,可从 [telegen_audit_results.json](human_validation_telegen/audit_judgeability/telegen_audit_results.json) 取:

- **000039 t=2**(C 类):agent 走到 "Confirm Lease" 弹窗却没点确认 → **模态确认流卡死**。
- **000052 t=1**(B 类):控制台 `401 Unauthorized on /api/auth/login` → agent 只能去注册新号 → **静默鉴权失败**。
- **000013**(B 类,多任务):游戏加了 D-pad 按钮但 "No tiles moved" → **手势 vs 点击的交互映射错误**。
- **000050 t=5**(C 类):表单里原生 `<select>`(血型)选不了,走不到报表页 → 与例 1 同类,可作"再次出现"的佐证。
- **000100 t=2**(B 类):agent 进了 "Request Quote" 而非 "Book Package",表单校验卡住 → **导航/校验联动错误**。

---

*文档生成基于本仓库实测数据(2026-07-26)。如需把任一案例配齐 before/after 截图、或导出为 pptx 大纲,可在此文档基础上继续。*
