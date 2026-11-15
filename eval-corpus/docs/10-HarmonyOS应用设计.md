# HarmonyOS 应用设计（移动应用开发课程交付物 P1）

> 日期：2026-09-23
> **本文件的 API 引用全部来自本机 SDK 声明文件**，非文档推断：
> `sdk\default\hms\ets\api\@hms.ai.A2A.d.ts`（19.5 KB, 683 行）
> `sdk\default\hms\ets\api\@hms.ai.AgentFramework.d.ets`
> `sdk\default\openharmony\ets\api\@ohos.app.agent.AgentExtensionAbility.d.ts`
> `sdk\default\openharmony\ets\api\application\AgentCard.d.ts`

---

## 1. 平台约束（已核验，决定架构）

| 事实 | 证据 |
|---|---|
| 手机**不能**运行自部署 LLM | `SystemCapability.AI.CANN.LLMEngine` 的 37 个 API 全部限定 `2in1`；手机侧 `phone-hmos.json` 无此 syscap |
| 手机**能**承载多智能体编排 | `SystemCapability.AI.Agent.AgentKit` 在 `phone-hmos.json` 中，且不在 `api-white-list.json` |
| **不需要任何权限** | 在 A2A / AgentFramework / localChatModel 三个声明文件中检索 `@permission` 零结果 |

**因此应用的定位是：编排在设备，推理在边缘/云端。**
这正是论文的核心叙事，也让"端侧"这个词是诚实的。

---

## 2. 架构与真实 API 的映射

```
┌──────────────────────────────────────────────────────────────┐
│  HarmonyOS 应用（ArkTS / Stage 模型）                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 编排层：A2A Server                                      │  │
│  │  createA2AServer(agentCard, onData, want?)              │  │
│  │    → Server.start() / stop()                            │  │
│  │  onData(method, RequestContext) 分派                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────┬──────────────┬──────────────────────────┐  │
│  │ Planner 智能体│ Executor 智能体│ Verifier 智能体          │  │
│  │ (AgentCard)  │ (AgentCard)  │ (AgentCard)              │  │
│  └──────────────┴──────────────┴──────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 决策层：调用仓颉库 agentbudget4cj                        │  │
│  │  route / msgForm / 工具注入策略                          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 设备能力工具（FunctionComponent）                       │  │
│  │  calendar.create · contact.lookup · file.search          │  │
│  │  notice.send · web.search （+ 10 个干扰工具）            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 端侧感知与记忆：DataAugmentation.Retrieval              │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
         │ 网络状态：@ohos.net.connection
         ▼
  ① 设备本地      ② 边缘（局域网 PC / Ollama）      ③ 云端 API
```

---

## 3. 编排层：使用真实的 A2A API

SDK 中的实际签名（逐字摘自 `@hms.ai.A2A.d.ts`，`@since 26.0.0`）：

```typescript
export enum Role { AGENT = 0, USER = 1, UNSPECIFIED = 2 }

export enum TaskState {
  SUBMITTED = 0, WORKING = 1, INPUT_REQUIRED = 2, COMPLETED = 3,
  CANCELED = 4, FAILED = 5, REJECTED = 6, AUTH_REQUIRED = 7, UNSPECIFIED = 8
}

export interface Part {
  text?: string; raw?: string; url?: string;
  data?: object | string | number | boolean;
  mediaType?: string; filename?: string; metadata?: object;
}

export interface Message {
  messageId: string; role: Role; parts: Part[];
  contextId?: string; extensions?: string[];
  metadata?: object; referenceTaskIds?: string[]; taskId?: string;
}

export interface Artifact {
  artifactId: string; parts: Part[]; description?: string;
  extensions?: string[]; metadata?: object; name?: string;
}

export interface TaskStatus { state: TaskState; timestamp?: string; message?: Message; }

export interface Task {
  id: string; contextId: string; status: TaskStatus;
  artifacts?: Artifact[]; history?: Message[]; metadata?: object;
}

export type OnDataCallback = (method: string, context: RequestContext) => void;
export function createA2AServer(agentCard: common.AgentCard,
                                onData: OnDataCallback, want?: Want): Server;

export interface Server {
  start(): void;
  stop(): void;
  onMessage(data: string, sender: ProxySender): void;
  onAuth(data: string): string;
  updateStatus(taskId: string, status: TaskStatus): void;
  addArtifact(taskId: string, taskArtifactParam: TaskArtifactParam): void;
}

export interface RequestContext {
  getAgentId(): string | undefined;
  getUserInput(delimiter?: string): string;
  getMessage(): Message | undefined;
  getRelatedTasks(): Task[];
  getCurrentTask(): Task | undefined;
  getTaskId(): string | undefined;
  getContextId(): string | undefined;
  getMetadata(): object;
}
```

### 3.1 三个设计要点

**要点 1：A2A 原生支持结构化载荷。**
`Part` 同时提供 `text`、`raw`、`data`、`url` 四种内容通道。
这意味着**自然语言消息是一个设计选择，而不是协议约束**。

这一点直接支撑论文的核心结论：我们的实验证明结构化编码同时赢了成本与正确性
（见 [09-消息表示实验.md](09-消息表示实验.md)），而 A2A 恰好提供了实现它的原生通道
（`Part.data` + `mediaType`），无需把 JSON 塞进 `text` 再转义。

> 附带的测量结论（`experiments/a2a_overhead.py`）：
> `Part.data` 比转义的 `Part.text` **多 21 B**（因为要带 `mediaType`），
> 所以它的价值是**类型保真**而非省字节。这必须诚实表述，不要声称它更省。

**要点 2：`Part.metadata` / `Message.metadata` 是携带预算状态的天然位置。**
调度器需要每步的预算余量与网络状态。把遥测放在 `metadata` 里，
可以**不污染面向模型的文本载荷**——两者的生命周期与消费者完全不同。

**要点 3：`Task.history` 是整份携带的。**
按 A2A 类型计算，每轮历史约增加 **133 B**（见 `a2a_overhead.py` 第 [4] 节）。
这就是本项目所攻击的"上下文增长"问题在 A2A 协议层的对应物。

### 3.2 编排骨架（签名均已核对）

```typescript
import { createA2AServer, Server, RequestContext, TaskState, Role } from '@hms.ai.A2A';
import { AgentCard } from '@ohos.app.ability.common';

// AgentCard 声明能力；字段与业界 A2A 规范一致
// （provider / capabilities{streaming,pushNotifications,stateTransitionHistory}
//   / skills[] / appInfo）
const card: AgentCard = /* ... */;

const server: Server = createA2AServer(card, (method: string, ctx: RequestContext) => {
  const agentId = ctx.getAgentId();          // 哪个智能体被调用
  const taskId  = ctx.getTaskId();
  const ctxId   = ctx.getContextId();
  const input   = ctx.getUserInput(' ');
  const msg     = ctx.getMessage();          // 原始 Message，含 parts 与 metadata

  server.updateStatus(taskId!, { state: TaskState.WORKING });
  // ... 调用仓颉调度器得到决策，按决策组装 prompt、调用推理端点 ...
  server.addArtifact(taskId!, { parts: [{ data: result, mediaType: 'application/json' }] });
  server.updateStatus(taskId!, { state: TaskState.COMPLETED });
});
server.start();
```

---

## 4. 决策层：如何调用仓颉库

仓颉库以**独立进程 / CLI** 形式暴露（见 [05-实验管线接口.md](05-实验管线接口.md)），
ArkTS 侧通过本地调用获取决策。这样做的理由：

1. 调度决策与被测方法同属仓颉产物，**不能**在 ArkTS 里重新实现一份
2. 避免仓颉 ↔ ArkTS 互操作的早期风险（该互操作在 1.2.0 才增强，且鸿蒙侧仓颉仍是体验版）
3. 保证 PC 实验与真机演示使用**同一份决策逻辑**

> **预留降级**：若进程内调用链路不通，仓颉库可作为本地服务运行，
> 应用走 loopback；实验数据不受影响，仅演示形态变化。

---

## 5. 设备能力工具

15 个工具与实验完全一致（5 个金标 + 10 个干扰项，见
[07-压缩代价实验.md](07-压缩代价实验.md)），以保证**演示与实验的可比性**。

能力声明走 Intents Kit 的装饰器式声明（`@hms.ai.insightIntent`），
其编程模型与 MCP 的 tool schema 高度类比——这正是"工具 schema 税"在鸿蒙上的对应物。

工具实现到系统能力的映射：

| 工具 | 系统能力 |
|---|---|
| `calendar.create` | Calendar Kit |
| `contact.lookup` | Contacts Kit |
| `file.search` | Core File Kit |
| `notice.send` | Notification Kit |
| `web.search` | 云端检索 API（同时充当"云调用"计费点） |

---

## 6. 待验证与阻塞

| # | 事项 | 阻塞原因 |
|---|---|---|
| 1 | **真机调试链路** | 需华为开发者实名认证 + DevEco 自动签名。`hdc.exe` 已定位（`sdk\default\openharmony\toolchains\hdc.exe`，v3.2.0f），但 `hdc list targets` 当前为空 |
| 2 | A2A 在真机上的实际行为 | 声明文件存在 ≠ 真机可用。`Server.onMessage(data, sender)` 的 `data` 实际格式、HSP 代理是否附加帧头，都必须实测 |
| 3 | `AgentCard` 的完整字段 | 位于 `openharmony` 侧 `application/AgentCard.d.ts`，尚未逐字段核对 |
| 4 | 局域网边缘节点的可达性探测 API | 需确认用 `@ohos.net.connection` 的哪个接口判断 LAN 可达 |

**A2A 协议开销的真机测量**是文献空白，也是本项目最有新意的端侧数据点：
需要测量 `AgentCard`、`Task`、`Message`、`Part` 的实际序列化与传输成本。

---

## 7. 与论文的对应关系

| 论文要素 | 应用中的对应物 |
|---|---|
| RQ1 工具 schema 税 | Intents Kit 能力声明的上下文占用 |
| RQ2 消息表示 | `Part.text` vs `Part.data` 的选择（A2A 原生支持） |
| RQ3 三层放置 | `@ohos.net.connection` 网络状态 → 设备/边缘/云 |
| RQ4 联合决策 | 编排层调用仓颉调度器的单一入口 |
| 端侧测量 | A2A 协议开销（`a2a_overhead.py` 给出 schema 级估计，真机值待测） |
