# HarmonyOS 工程构建工作流

> 日期：2026-09-23 · 全部结论来自**实际构建**，非文档推断
> 产物：`app/harmony/_out/entry-default-unsigned.hap`（**190,066 字节**）

---

## 1. 结论

**命令行构建已打通。** 移动应用课程要求的"可运行代码"不再只是设计文档，
而是一个真实产出 HAP 的 ArkTS 工程。

```
> hvigor  BUILD SUCCESSFUL in 13 s 105 ms
> hvigor  Finished :entry:default@CompileArkTS
[hb] artifact -> app\harmony\_out\entry-default-unsigned.hap (190,066 bytes)
```

产物大小从模板骨架的 110,146 字节增长到 190,066 字节，证明包含的是我们自己的代码。

---

## 2. 工具链（本机已核验）

| 组件 | 路径 |
|---|---|
| hvigor | `D:\develop\DevEco Studio\tools\hvigor\bin\hvigorw.bat` |
| ohpm | `D:\develop\DevEco Studio\tools\ohpm\bin\ohpm.bat` |
| 内置 node | `D:\develop\DevEco Studio\tools\node\node.exe` |
| SDK | `D:\develop\DevEco Studio\sdk`（`DEVECO_SDK_HOME`） |
| 设备工具 | `sdk\default\openharmony\toolchains\hdc.exe`（v3.2.0f） |
| 官方工程模板 | `plugins\codegenie-plugin\previewProject`（本项目骨架来源） |

hvigor 自带 `@ohos/hvigor` 与 `@ohos/hvigor-ohos-plugin`，均为 **6.26.4**。

---

## 3. 两道必须绕过的限制（均实测确认）

### 3.1 hvigor 拒绝非 ASCII 工程路径

```
ERROR: 00306003 Specification Limit Violation
Error Message: Invalid project path. Current path does not match:
  C:\Users\86178\Documents\deepseek-harness\项目开发\app\harmony
* Try the following:
  > Please modify the project path to ensure that it only contains letters,
    digits, hyphens (-), underscores (_), periods (.), english parentheses (()),
    spaces, or the @ symbol
```

**这与仓颉 `cjpm` 的限制是同一类问题，但成因完全不同**：

| 工具链 | 限制 | 成因 |
|---|---|---|
| `cjpm`（仓颉） | 工程目录不能含非 ASCII | `cjc --scan-dependency` 用 **GBK** 输出路径，`cjpm` 按 UTF-8 解析 JSON 失败 |
| `hvigor`（鸿蒙） | 工程目录不能含非 ASCII | **显式的路径白名单校验**，直接拒绝 |

**含义**：本工作目录（`...\项目开发`）不能作为任何一套工具链的构建目录。
两套工具链都必须走 ASCII 镜像区。

### 3.2 hvigor 必须创建符号链接

hvigor 会把自带的 `@ohos/hvigor` 与其插件**符号链接**进工作区：

```
EPERM: operation not permitted, symlink
  'D:\develop\DevEco Studio\tools\hvigor\hvigor'
  -> '<HVIGOR_USER_HOME>\project_caches\<hash>\workspace\node_modules\@ohos\hvigor'
```

Windows 创建符号链接需要特权，本沙箱直接拒绝。已试过且**无效**的两条替代路径：

| 尝试 | 结果 |
|---|---|
| `pnpm` 的 `node-linker=hoisted`（改用复制而非链接） | ❌ 链接由 hvigor 自身逻辑发起，不受 pnpm 配置影响 |
| 目录 junction（`mklink /J`，通常不需特权） | ❌ 沙箱同样拒绝 reparse point |
| 预先复制依赖目录占位 | ❌ hvigor 无条件重建链接，不检查是否已存在 |

**结论**：这一限制**只影响沙箱内的自动化构建**。在 DevEco Studio 或不带沙箱的普通终端里
不存在该问题。因此本工程的构建命令已交付给你，可直接在沙箱外复现。

---

## 4. 构建脚本 `tools/hb.ps1`

机制与仓颉侧的 `tools/cj.ps1` 一致：**源码以工作目录为准，构建在 ASCII 镜像区进行**。

```powershell
powershell -ExecutionPolicy Bypass -File tools\hb.ps1 sync          # 仅同步
powershell -ExecutionPolicy Bypass -File tools\hb.ps1 assembleHap   # 构建（默认目标）
powershell -ExecutionPolicy Bypass -File tools\hb.ps1 clean         # 清理
```

脚本内部处理：

1. `robocopy /MIR` 把 `app/harmony` 镜像到 `%TEMP%\hb\harmony`（排除 `node_modules`、`build`、`.hvigor` 等）
2. 重定向 `HVIGOR_USER_HOME` / `USERPROFILE` / `HOME` / `npm_config_cache` 到 ASCII 暂存区
   （否则 hvigor 与 npm 会写工作目录外的用户目录，被沙箱拒绝）
3. 设置 `DEVECO_SDK_HOME` 与 `PATH`
4. 执行 `hvigorw <args> --no-daemon`
5. **仅在构建成功时**回收 `.hap` 到 `app/harmony/_out/`

> 第 5 条是一个实测修正：初版无论成败都回收，导致一次构建失败后仍把**上一次的旧 HAP**
> 报成新产物。现在失败时会先清空旧 `.hap` 并明确输出 `build FAILED ... no artifact published`。
> 这类"看起来正常但产物是旧的"错误，比构建直接失败更危险。

---

## 5. 工程结构

```
app/harmony/
├── AppScope/app.json5                 bundleName = com.xjtu.agentbudget
├── build-profile.json5                 compatible/target SDK 5.0.0(12)
├── oh-package.json5                   依赖为空（无需 ohpm 联网安装）
├── hvigor/hvigor-config.json5
└── entry/
    ├── build-profile.json5            仅 default target（已移除 ohosTest）
    └── src/main/
        ├── module.json5               含 ohos.permission.GET_NETWORK_INFO
        ├── ets/
        │   ├── entryability/EntryAbility.ets
        │   ├── pages/Index.ets              编排控制台 UI
        │   ├── model/Types.ets              与仓颉库一致的类型词汇
        │   ├── core/Tokens.ets              token 估算（与仓颉实现行为一致）
        │   ├── core/MessageCodec.ets        三种消息表示（含 40 字符截断预算）
        │   ├── core/BudgetPolicy.ets        联合决策阶梯
        │   ├── core/NetworkProbe.ets        网络状态探测
        │   └── agents/ToolRegistry.ets      15 个工具 + 归一化检索
        │   └── agents/AgentRuntime.ets      Planner→Executor→Verifier
        └── resources/…
```

### 关于 `BudgetPolicy.ets` 的重要说明

**这不是方法的权威实现。** 权威实现是仓颉库 `projects/agentbudget4cj`，
它才是被研究测量的对象。ArkTS 版本存在的原因，是让应用在仓颉 ↔ ArkTS 桥接打通之前
能够自洽运行与演示。

**任何被报告的数字必须来自仓颉侧。** 理由不是洁癖：若应用与库的决策不同，
演示与实验就在描述两个不同的系统，却声称描述同一个。

---

## 6. 实测发现：权限需求的不对称性

构建输出的 ArkTS 告警指出了网络探测的权限需求：

```
ArkTS:WARN NetworkProbe.ets:21:28
  To use this API, you need to apply for the permissions: ohos.permission.GET_NETWORK_INFO
ArkTS:WARN NetworkProbe.ets:26:31   （同上）
```

已在 `module.json5` 声明：

```json5
"requestPermissions": [
  {
    "name": "ohos.permission.GET_NETWORK_INFO",
    "reason": "$string:reason_network_info",
    "usedScene": { "abilities": ["EntryAbility"], "when": "inuse" }
  }
]
```

**值得记录的不对称性**：A2A 与 Agent Framework 的 API **不需要任何权限**，
而一次普通的网络状态探测**需要**声明权限。这与前面"检索 `@permission` 零结果"的发现一致。

> 该告警是编译器的**提示性说明**（在源码层告知需要哪些权限），
> 声明权限后不会消失，属预期行为，不是缺陷。

---

## 7. 应用能演示什么

`Index.ets` 把论文的决策可视化在手机上：给定一个任务，显示
**在哪一层执行 / 工具上下文如何渲染 / 智能体用哪种消息形式 / 为什么**，
并给出证明验证器确实收到参数的执行轨迹。

**刻意保留的可见失败模式**：把预算滑块推过 30%、网络设为弱网，
`summary` 形式会截断工具参数，验证器报告 FAIL。
这就是"朴素摘要被结构化编码严格支配"这一结论的**交互式复现**。

---

## 7.5 应用与库的一致性验证（可执行，不需真机）

**要解决的问题**：应用侧曾有一份 `BudgetPolicy` 的本地移植版本，而仓颉库后来改成了
得分驱动的自适应 top-k。两者规则不同，就意味着**演示与实验在描述两个不同的系统，
却声称描述同一个**——这正是 `BudgetPolicy.ets` 文件头自己警告过的问题。

**一致性缺陷已修复**：`ToolRegistry.ets` 新增 `scoreAll()` 与 `adaptiveK()`，
`BudgetPolicy.ets` 在 `topK <= 0` 时调用它，与仓颉库的约定（CLI 协议中 `k = -1`）一致。
UI 的默认值也改为自适应（按钮循环 自适应 → 1 → 3 → 5 → 8）。

**但"改了"不等于"对了"。** 应用无法在没有真机时运行，然而这些纯逻辑模块
（`Types` / `Tokens` / `MessageCodec` / `ToolRegistry` / `BudgetPolicy`）
**不含任何 ArkUI 装饰器，本质是普通 TypeScript**，因此可以直接在 Node 下执行。

Node 24 原生支持类型变换，于是可以真正跑起来比对：

```powershell
python tools\verify_app_logic.py
```

实现细节：类型剥离会擦除 `interface` / `type` 声明，因此**只导入类型的 import 语句
在运行时会变成未解析的值导入**。脚本把模块镜像到工作目录内，
并按目标模块的实际导出**剔除纯类型名**，从不修改应用源码。

**实测结果（应用侧 vs 仓颉库）**：

| 查询 | 应用 k | 库 k | 结果 |
|---|---|---|---|
| search my files for the quarterly report | 3 | 3 | ✅ |
| look up a contact named Li Wei in my address book | 2 | 2 | ✅ |
| send a notification to remind me about the deadline | 2 | 2 | ✅ |
| find online the release notes for the new version | 5 | 5 | ✅ |

决策阶梯也一致（wifi/弱网/离线三种网络档在同一预算下给出相同的 route / msgForm / 策略）。

**选择器语义（库、CLI、应用三者统一）**：

| 选择器 | 含义 | 备注 |
|---|---|---|
| `k < 0` | **得分驱动自适应**，`\|k\|` = 阈值占最高分的百分比 | `-50` 是提议的方法，也是 CLI 与应用默认值 |
| `k = 0` | **预算驱动自适应** | 仅作为基线保留（论文实测它被固定 k 支配） |
| `k > 0` | 固定 k | 论文的固定基线 |

> **一个曾经踩到的坑**：请求里的 `topK = 0` 与响应里的 `kUsed = 0` 含义**无关**——
> 前者是"预算驱动策略"，后者是"全量注入（eager）"。我一度把 CLI 默认改成 `0`
> 并以为那是自适应，实测输出 `two-stage-top6` 才发现选中的是**被支配的那个策略**。
> 现在默认值是 `-50`，且协议注释里显式写明了这个歧义。

应用侧新增 `adaptiveKByBudget()`，因此**三种选择器在应用里都能复现**，
演示可以交互式重放论文的每一条对比臂（含负面结果）：

| 选择器 | 语义 | 库 | 应用 |
|---|---|---|---|
| −50 | 得分驱动 | `two-stage-top3` | `two-stage-top3` ✅ |
| 0 | 预算驱动 | `two-stage-top6` | `two-stage-top6` ✅ |
| 3 | 固定 | `two-stage-top3` | `two-stage-top3` ✅ |

> **这一验证的地位**：它检查的是**移植的一致性**，不是设备行为。
> 网络探测与 A2A HSP 仍必须在真机上验证。
> 但它把"演示与实验是同一个系统"从一个断言变成了一个**可复现的检查**。

### 7.5.1 为什么不能做仓颉 ↔ ArkTS 直接桥接（工具链结论）

**问题**：应用侧是 ArkTS 移植版，而"权威实现"是仓颉库。
这构成一个结构性风险——两套实现可能漂移（本项目已因此出过两次错误）。
最彻底的解法是让应用直接调用仓颉库，消除第二套实现。

**实测结论：在当前工具链下不可行。** 证据：

| 检验 | 结果 |
|---|---|
| `cjc --help` 是否支持 `--target` | ✅ 支持 |
| `cjc --target aarch64-linux-ohos` | 目标**被识别**（未报"未知架构"），但报 `target library path is not exist` |
| SDK 实际提供的标准库 | **只有** `modules/windows_x86_64_cjnative` 与 `lib/windows_x86_64_cjnative` |
| 机器上是否存在 Linux/aarch64/ohos 仓颉工具链 | 无 |
| DevEco 是否自带仓颉 SDK | 无 |

也就是说：**编译器认识这个目标，但这个 Windows 版 SDK 不提供它的标准库。**
交叉编译需要华为的 Linux/ohos 版仓颉 SDK。

**因此 ArkTS 移植版不是权宜之计，而是当前唯一可行的端侧实现方式。**
这反过来提升了 `tools/verify_app_logic.py` 的地位——它不是锦上添花，
而是**消除"两套实现漂移"这一结构性风险的唯一手段**。

### 7.5.2 把抽查升级为全任务集差分测试

既然移植无法消除，就把它的正确性保证做到最强。
原先的验证只检查 **4 条硬编码样例**，那可能通过而两套实现在别处全部发散。

现在改为**差分测试**：

1. 两侧输入**同一批查询**（直接取 `experiments/experiment.py` 的 `TASKS`，**30 条**）
2. 仓颉侧：一次批处理调用 CLI，取每个查询实际选出的 `k`
3. 应用侧：Node 下执行 ArkTS 纯逻辑模块，取同一批查询的 `k`
4. **逐条比较，任何一条不一致即失败**

实测结果：**30/30 完全一致**。

> **新增任务会自动进入差分测试**——查询列表来自任务集本身，
> 而不是维护一份独立的手写清单（手写清单正是会漂移的那种东西）。

---

## 7.6 真实 `@hms.ai.A2A` 协议集成

**此前的问题**：应用演示的是调度策略，但它对协议层只是"进程内等价实现"。
这足以展示决策逻辑，却**回答不了论文在协议层真正要问的问题**：
消息表示的选择**是否真的改变了线缆上的字节**？

**现在改变了**：`agents/A2AAgentServer.ets` 把 Executor 实现为真实的 A2A 服务端，
`planStep` 返回的消息形式**直接决定用哪个 `Part` 通道**——
`structured` 走 `Part.data`（带 `mediaType`），其余走 `Part.text`。
**决策与线缆格式是同一个对象**，而不是两件恰好一致的事。

**用到的真实 API**（签名取自 SDK 声明文件）：

| API | 出处 |
|---|---|
| `createA2AServer(card, onData, want?)` | `@hms.ai.A2A.d.ts:460` |
| `Server.start/stop/onMessage(data, sender)` | `@hms.ai.A2A.d.ts:477-535` |
| `RequestContext.getUserInput/getTaskId/getContextId/getMetadata` | `@hms.ai.A2A.d.ts:543-618` |
| `AgentCard` / `AgentSkill` / `AgentAppInfo` | `AgentCard.d.ts:29/283/374` |

**设计要点**：预算遥测放在 `Part.metadata`，**绝不放进 `Part.text`**。
协议本身就提供了消费者自定义数据的通道；把遥测塞进模型载荷是自找的成本，
而论文的整个论点就是这类成本在移动端占主导。

### 一个关于"编译通过"的教训

第一次写完该模块时构建显示 `BUILD SUCCESSFUL`，但**HAP 体积没有变化**。
这说明模块**没有被任何文件导入，因而根本没进入编译图**——"编译通过"是一句未经验证的话。

把模块接入 `Index.ets` 后构建**失败**，暴露出 6 个真实类型错误
（`AgentSkill` 缺 `tags`、`AgentCard` 缺 `defaultInputModes`/`defaultOutputModes`/`appInfo`）。
逐个补齐后：

| 阶段 | HAP 体积 | 含义 |
|---|---|---|
| 模块未被导入 | 196,153 B | BUILD SUCCESSFUL 但**未编译该文件** |
| 接入后（6 错误） | 构建失败 | 类型检查真正生效 |
| 补齐后 | **221,866 B** | 模块已进入产物（+25.7 KB） |

> **体积变化是"真的编译进去了"的一条廉价证据。** 在只有一个构建产物、
> 且编译器可能跳过未引用文件的情况下，"构建成功"与"代码被检查过"是两件事。

### 验证边界（诚实声明）

**真机之外无法验证的部分**：A2A HSP 是否附加自有帧头、`Task.history` 是否每次调用都重传、
真实鉴权握手。`experiments/a2a_overhead.py` 的信封数字因此明确标注为 **schema 级估计**。

`A2AAgentServer.dryRun()` 走完整的调度与编码路径但**不经过传输层**，
因此它既让该模块进入编译图，也让演示在无真机时可运行。

---

## 7.7 真机接入与环境实测（2026-09）

设备已通过**无线调试**接入。实测数据如下，**与 SDK 元数据的预测一致，但暴露了一个硬约束**。

### 设备与环境

| 项 | 值 |
|---|---|
| 型号 | HAD-W32（MateBook Pro） |
| 系统 | OpenHarmony-6.1.0.115，dist 6.1.0（`6.1.0.117(SP68C00E100R13P3)`） |
| **API 版本** | **23** |
| **设备类型** | **2in1** |
| 电脑上的 SDK | **仅一个版本：API 26（HarmonyOS 26.0.0）** |
| 连接方式 | 无线（`hdc tconn`），不需要 USB |

### ⚠️ 硬约束：A2A 在这台设备上不可用

两个**独立**的原因叠加，任一成立都会导致 A2A 失效：

1. **API 版本不足**：`@hms.ai.A2A` 标注 `@since 26.0.0`，设备是 **API 23**。
   电脑上**只有 API 26 的 SDK**，无法降级编译来规避。
2. **形态不在支持列表**：SDK 的 `device-define/*-hmos.json` 显示
   `SystemCapability.AI.Agent.AgentKit` 只在 **phone / tablet** 中公开，**2in1 没有**——
   而本设备正是 2in1。

设备端直接查证（`hdc shell bm dump -a`）也**未发现任何 A2A / Agent 相关包**
（只有 `aibase` / `aidataservice` / `ailife` / `ailifesvc` 等）。

### 影响与应对

| 演示镜头 | 依赖 | 在本设备上 |
|---|---|---|
| 1–5、7（三层放置 / 消息形式 / 验证器） | 仅 `BudgetPolicy` + `MessageCodec` + UI | **应可运行** |
| 6（A2A 试运行） | `@hms.ai.A2A` 的 `createA2AServer` | **不可用** |

**待验证的风险**：`A2AAgentServer.ets` 被 `Index.ets` 静态导入。
若该模块在设备上解析失败，**可能连带影响整个应用的启动**——
首次安装后须立即确认应用能否启动；若不能，需把 A2A 部分改为可选依赖
（`A2AAgentServer` 的实际调用点只有 `dryRun()`，`createA2AServer` 从未被 UI 调用，
因此改造成本低）。

### 对论文的影响（必须同步）

1. **§2.7 的架构论断不受影响**——它由 SDK 元数据支撑（first-hand），而非由演示支撑。
2. **但演示设备不属于目标形态**：本文面向手机；实测设备是 2in1，
   且 2in1 **具备** `AI.CANN.LLMEngine`（手机与平板都没有）。
   因此演示**不能**用来支撑"手机无法自部署 LLM"这一论断。
3. **§4.3 的 A2A 集成在这台设备上无法运行**——这一点必须在报告中如实写明，
   而不能因为"代码编译通过"就当作已验证。

### 这一步的方法论价值

本项目此前多次栽在同一类错误上：**把"编译通过"当成"验证过"**（见 §7.6）。
本次真机接入给出了一个更彻底的例子：
**A2A 代码编译通过、进了产物（HAP 增大 25.7 KB），却在目标设备上根本无法运行。**
产物变大只能证明"代码被编译进去了"，**不能证明"它能工作"**。

---

## 8. 尚未完成

| # | 事项 | 阻塞 |
|---|---|---|
| 1 | 真机安装与运行 | 需华为开发者实名认证 + 自动签名（`hdc list targets` 当前为空） |
| 2 | A2A 真实传输层联调 | 代码已完成并通过编译；HSP 的字节级行为仍需真机确认 |
| 3 | A2A 协议开销真机测量 | 同上；schema 级估计见 `experiments/a2a_overhead.py` |
| 4 | 仓颉 ↔ ArkTS 桥接 | 需要仓颉库可作为本地服务/进程被应用调用 |
| 5 | 沙箱内免提权构建 | 符号链接限制，仅在沙箱内存在 |

---

## 9. 复现（沙箱外的普通终端，无需任何特殊权限）

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
powershell -ExecutionPolicy Bypass -File tools\hb.ps1 assembleHap
# 产物：app\harmony\_out\entry-default-unsigned.hap
```

或用 DevEco Studio 直接打开 `app/harmony`（IDE 会自动处理签名与符号链接）。

> **注意**：若把工程复制到别处，目标路径**必须只含 ASCII 字符**。
