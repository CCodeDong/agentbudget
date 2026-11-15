# 方案重定位：因 HarmonyOS 可行性核验而调整

> 日期：2026-09-23
> 触发原因：对「手机端能不能跑自己的小模型」做了硬核验，结论与原假设相反
> 影响：架构从**双层**改为**三层**；研究问题更锐利；实验可立即开始

---

## 1. 核验结论（本机 SDK 实测，非文档推断）

### 1.1 否决项：手机无法运行自部署 LLM ❌

| 证据 | 内容 |
|---|---|
| **设备能力矩阵** | `sdk\default\hms\ets\api\device-define\phone-hmos.json` **有** `AI.Agent.AgentKit`、`AI.InsightIntent`、`AI.HiAIFoundation`、`DataAugmentation.Retrieval`；**没有** `AI.CANN.LLMEngine`、`DataAugmentation.LocalChatModel`、`DataAugmentation.RAG` |
| **对照设备** | 上述三项缺失的能力，全部出现在 `2in1-hmos.json`（PC 形态） |
| **逐 API 统计** | `api-version\CANNKit.json` 共 **265** 个 `deviceTypes` 块，其中 **37 个为 `2in1`-only**（不含 phone），全部属于 `CANNKit/llm_engine.h`，`syscap = SystemCapability.AI.CANN.LLMEngine` |
| **旁证** | `localChatModel` 整个命名空间只有 `init()` 与 `chat()`，**无任何模型装载 API**，即使可用也换不成 Qwen |
| **旁证** | HiAI Foundation 为纯 native（无 ArkTS 包），需 Ubuntu 上 `tools_omg`/`tools_dopt` 转 `.om`，**不支持 GGUF/safetensors**；官方 Model Zoo 无 LLM |

**结论**：本科生无法在 HarmonyOS NEXT 真机上部署自己的 1.5B–3B 模型并做工具调用。华为把 LLM 推理留给 PC 形态，这是明确的产品决策，不是配置问题。

### 1.2 意外收获：多智能体协作能力在手机上**完全可用** ✅

这是重定位后项目的技术基石，均为本机 SDK 文件级确认：

| 能力 | 声明文件 | 说明 |
|---|---|---|
| **A2A 协议** | `hms\ets\api\@hms.ai.A2A.d.ts` | since 26.0.0，与当前 SDK 版本一致；`Server`/`Task`/`Message`/`Part`/`Artifact`/`AgentCard`/`Role`/`TaskState` |
| **智能体框架** | `hms\ets\api\@hms.ai.AgentFramework.d.ets` | `AgentController`/`FunctionComponent` |
| **Agent 运行时** | `openharmony\ets\api\@ohos.app.agent.AgentExtensionAbility.d.ts` | since 24 |
| **Agent 常量** | `openharmony\ets\api\@ohos.app.agent.agentConstant.d.ts` | `AgentCardType{APP,ATOMIC_SERVICE}` |
| **能力声明** | `openharmony\ets\api\application\AgentCard.d.ts` | 字段与业界 A2A `AgentCard` 规范一致 |
| **意图声明** | `@hms.ai.insightIntent`（Intents Kit） | 装饰器式意图声明 |

**权限**：在 A2A / AgentFramework / localChatModel 三个声明文件中检索 `@permission` **零结果** → 无需 `ohos.permission.*`。
**可用性**：`SystemCapability.AI.Agent.AgentKit` 在 `phone-hmos.json` 中，且不在 `api-white-list.json` → 手机侧公开。

### 1.3 两个必须避开的陷阱 ⚠️

1. **`FunctionController` 不是 function calling**。官方原文：*"This API is reserved. In the current version, this API inherits from AgentController's methods without any additional implementation."* 名字极易误导。
2. **`AgentController` 是华为云侧智能体**，报错码包含 `Privacy agreement not accepted` / `HUAWEI ID not signed in`，且依赖 `com.huawei.hmsapp.hiai.hsp` → **不是你的模型、强绑账号、可复现性差**，不能作为主实验载体。

---

## 2. 重定位后的架构：从双层到三层

### 原假设（已否决）

```
手机：编排 + 本地小模型推理   ← 后半句不成立
云端：大模型
```

### 重定位后（三层，已被代码实现）

```
┌────────────────────────────────────────────────────────┐
│  HarmonyOS 手机（ArkTS）—— 真正的"端侧"                  │
│  · 多智能体编排：@hms.ai.A2A + AgentExtensionAbility     │
│  · 能力声明：AgentCard / Intents Kit                     │
│  · 设备能力工具：日历·联系人·文件·通知·网络搜索             │
│  · 端侧感知与记忆：CoreVisionKit / DataAugmentation.Retrieval│
│  · 决策核心：调用仓颉库 agentbudget4cj                    │
└───────────────┬────────────────────────────────────────┘
                │ 每步都要决策：去哪一层？
      ┌─────────┼──────────────┬───────────────┐
      ▼         ▼              ▼               ▼
   ①OnDevice  ②Edge          ③Cloud
   规则/感知  局域网 PC       云端 API
              上的 Ollama     (DeepSeek)
              /llama.cpp
```

**关键性质（已写成代码与测试）**：**局域网通常在广域网劣化时仍然存活**，因此边缘层是弱网/断网下**唯一仍然可用的远程选项**。这给了端云路由一个真正有研究价值的降级维度。

---

## 3. 研究问题（重写后更锐利）

> **在多智能体系统中，当「编排」位于设备侧、「推理」可分布于边缘与云侧时，网络状态与上下文预算如何共同决定每一步的执行位置？**

三层比两层多出的是**一个全新的决策维度**，而现有文献只做两层：

| 现有工作 | 它们做了什么 | 我们新增 |
|---|---|---|
| Hera (2605.24598) | 步级端云路由，**路由状态里没有网络条件** | 把网络状态纳入状态空间 |
| DoT (2502.04392) | 任务级端云分配 | 步级 + 三层的降级排序 |
| Tool Attention (2604.21816) | 仅工具 schema 注入；端到端结果作者自认是 projection | 与路由、消息表示**联合**决策 |
| CacheScout (2608.14624) | 仅服务端 GPU KV 复用 | 端侧编排开销的实测 |

### 新增的高价值测量点（重定位带来的红利）

1. **鸿蒙 A2A 协议本身的编排开销**——`AgentCard`/`Task`/`Message`/`Part` 的序列化与传输成本，**文献中完全空白**（检索无任何"鸿蒙智能体"同行评议论文）。
2. **弱网/断网下的三层降级成功率**——前人不报告的维度。
3. **工具能力声明（Intents Kit / FunctionComponent）的 schema 税**在手机侧的真实占比。

---

## 4. 为什么这比原方案更好

| 维度 | 原方案（端侧自部署 LLM） | 重定位后 |
|---|---|---|
| 可行性 | ❌ 已证伪 | ✅ 全部能力本机确认可用 |
| 阻塞依赖 | 需 `.om` 模型转换链、Ubuntu、可能的企业资质 | **无**，PC 跑 Ollama 即可开工 |
| 实验可立即开始 | 否 | **是** |
| 研究新颖度 | 中（端侧 agent 已有工作） | **高**（三层放置 + 鸿蒙 A2A 空白） |
| 网络状态的作用 | 辅助维度 | **核心维度** |
| 华为生态契合度 | 硬啃不可行路径 | 用官方主推的 A2A 做协作（叙事更顺） |
| 风险 | 高（依赖不可控） | 中低（有纯云 baseline 兜底） |

---

## 5. 代码侧的落地（已完成）

`projects/agentbudget4cj` 已按三层重构并通过测试：

| 变更 | 内容 |
|---|---|
| `RouteTarget` | `OnDevice \| Edge \| Cloud`（原为两层） |
| `NetState` | 新增 `lanAvailable: Bool`——边缘层可达性与广域网质量**解耦** |
| `NetState.edgeViable()` | 明确表达"边缘存活不依赖广域网" |
| `BudgetScheduler.plan` | 三层优先级：云仅用于"难步骤+有余量"；否则落到边缘；再否则落回设备 |
| 测试 | **14/14 通过**，新增 3 个三层路由测试，含 `testEdgeSurvivesWideAreaFailure` |

---

## 6. 对计划的影响

| 项 | 原计划 | 调整后 |
|---|---|---|
| 第 3–4 周 spike | 验证端侧模型在手机上表现 | **改为**：PC 跑 Ollama + 手机通过 A2A 调用；验证局域网延迟与工具调用 |
| 设备需求 | 1 台鸿蒙手机 | 1 台鸿蒙手机 + **1 台 PC**（已有） |
| 端侧模型 | Qwen INT4 于手机 | Qwen INT4 于 PC（Ollama），经局域网服务 |
| 论文定位 | on-device multi-agent | **edge-assisted / three-tier multi-agent orchestration** |
| 新增工作 | — | 接入 `@hms.ai.A2A`；测量 A2A 协议开销 |

> **诚实性要求**：论文中**不得**声称模型运行在手机端。正确表述是
> "orchestration on device, inference at edge/cloud"（设备侧编排、边缘/云侧推理）。

---

## 7. 待核实（不得当作已确认事实使用）

1. HiAI Foundation 是否需要企业资质/白名单——**未核实**（元数据 `isSystemApi:false`，但无权威文本）
2. Intents Kit 是否要求应用已上架或需申请——**未核实**
3. 真机 `/system/lib64/` 是否真的存在 `libcann_llm_engine.so`——需 `hdc shell` 确认（SDK 内 6.7 KB 文件是 NDK stub）
4. 华为文档中心正文无法抓取（SPA）——技术断言已改用本地 SDK 声明文件，更硬
5. A2A 在真机上的实际行为与性能——**必须通过真机实测**，文档不能替代

---

## 8. 一分钟自证命令（可复现本文件的核心结论）

```powershell
$sdk = 'D:\develop\DevEco Studio\sdk\default'

# 1) 手机 vs PC 的能力差异
Select-String -Path "$sdk\hms\ets\api\device-define\phone-hmos.json" -Pattern 'AI\.|DataAugmentation'
Select-String -Path "$sdk\hms\ets\api\device-define\2in1-hmos.json" -Pattern 'CANN|LocalChatModel|RAG'

# 2) LLM Engine 的 37 个 2in1-only API
$raw = Get-Content "$sdk\hms\ets\api\device-define\api-version\CANNKit.json" -Raw
$blocks = [regex]::Matches($raw, '(?s)\{[^{}]*?"deviceTypes"\s*:\s*\[(.*?)\][^{}]*?\}')
"total deviceTypes blocks: $($blocks.Count)"
$only2 = 0; foreach ($b in $blocks) { $t=$b.Groups[1].Value; if ($t -match '2in1' -and $t -notmatch 'phone') { $only2++ } }
"2in1-only blocks: $only2"    # 预期 37

# 3) A2A 与 Agent 运行时确实存在
Get-ChildItem $sdk -Recurse -Filter '*A2A*'
Get-ChildItem $sdk -Recurse | Where-Object { $_.Name -match 'AgentExtensionAbility|AgentCard|agentConstant' }
```
