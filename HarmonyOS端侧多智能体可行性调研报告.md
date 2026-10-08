# HarmonyOS NEXT 真机端侧多智能体 + 自部署 1.5B–3B 量化模型 —— 技术可行性调研报告

**调研对象环境**（本地实测确认，非推测）：

| 项 | 值 | 证据 |
|---|---|---|
| SDK 根目录 | `D:\develop\DevEco Studio\sdk\default` | 目录存在 |
| API 版本 | **apiVersion 26** | `sdk-pkg.json` |
| 平台版本 | **HarmonyOS 26.0.0**（`version 26.0.0.105`, `Release`） | `sdk-pkg.json` |
| 子目录 | `hms\`、`openharmony\`（各含 ets/js/native/previewer/toolchains） | 目录枚举 |
| 声明文件规模 | `hms/ets/api` = 194 个；`hms/ets/kits` = 56 个；`openharmony/ets/api` = 542 个；`openharmony/ets/kits` = 47 个 | 文件计数 |

**证据等级标记**（全文遵守）：
- 【官方-SDK元数据】= SDK 内华为生成的 `device-define/*.json` 设备能力矩阵 / `api-version/*.json`，**这是"某能力在哪种设备上可用"的权威答案**
- 【官方-SDK声明】= 我直接读取的 `.d.ts` / `.d.ets` / `.h` 文件内容
- 【官方-文档】= 华为官方文档（部分经官方内容镜像站转发，已在来源中注明）
- 【社区】= 开发者论坛 / CSDN 等
- 【未核实】= 未能确认

---

## 0. 结论速览（TL;DR）

> **一句话可行性结论：不能在 HarmonyOS NEXT 真机上跑你自己的 Qwen2.5-1.5B/3B INT4 并拿到官方 function calling —— 手机侧唯一的"可装载自有模型"官方通道是 MindSpore Lite（纯 CPU、无 NPU、需自行实现全部 LLM 推理与工具调用逻辑），而华为真正为 LLM 准备的 CANN LLM Engine 在 SDK 元数据里被明确限制为 2in1（PC）设备，手机上不可用。**

**推荐降级方案排序**（详见 §5）：
1. **局域网调用 PC 上的 Ollama/llama.cpp**（唯一能同时满足"真实跑 1.5B–3B + 真 function calling + 论文可声称 edge"的方案）
2. **MindSpore Lite 装载自转 `.ms` 小模型做端侧非 LLM 任务 + 云端 LLM 做智能体大脑**（混合，论文可声称 partial on-device）
3. **纯云端 LLM API（DeepSeek/通义）+ 端侧传统 ML Kit**（最好做、最稳，但**不能**声称 on-device）
4. **华为小艺/AgentFrameworkKit**（能用于多智能体叙事，但**不是你的模型**，且强绑定华为账号与云）

---

## 1. HarmonyOS NEXT / HarmonyOS 6 提供哪些端侧 AI 推理能力？

### 1.1 能力总表（逐个查证结果）

| # | 能力 | 实际包名 / 文件 | syscap | 手机可用？ | 普通个人开发者可用？ |
|---|---|---|---|---|---|
| 1 | **HiAI Foundation**（NPU/CPU 异构推理引擎） | 仅 native：`CANNKit/hiai_*.h` + `libhiai_foundation.so`；**无 ArkTS 包** | `SystemCapability.AI.HiAIFoundation` | ✅ **是**（phone since 5.0.0(12)） | ⚠️ **API 公开（`isSystemApi:false`），但需自训模型 → OMG 转 `.om` → Ubuntu 工具链**；是否另有白名单【未核实】 |
| 2 | **CANN LLM Engine**（专用 LLM 推理引擎） | 仅 native：`CANNKit/llm_engine.h` + `libcann_llm_engine.so` | `SystemCapability.AI.CANN.LLMEngine` | ❌ **否 —— 仅 2in1** | ❌ 手机侧无此能力，谈不上开放 |
| 3 | **MindSpore Lite Kit** | `@kit.MindSporeLiteKit` → `@ohos.ai.mindSporeLite`；native `libmindspore_lite_ndk.so` | `SystemCapability.AI.MindSporeLite`（ETS）/ `SystemCapability.Ai.MindSpore`（Native） | ✅ **是**（phone since 12） | ✅ **是**，位于 `openharmony/`（开源侧），无 HMS 白名单机制 |
| 4 | **Neural Network Runtime (NNRt)** | native `neural_network_runtime/*.h` + `libneural_network_runtime.so`、`libneural_network_core.so` | `SystemCapability.AI.NeuralNetworkRuntime` | ✅ 是 | ✅ 是（开源侧） |
| 5 | **端侧问答大模型 `localChatModel`** | `@kit.DataAugmentationKit` → `@hms.data.localChatModel` | `SystemCapability.DataAugmentation.LocalChatModel` | ❌ **否 —— 仅 2in1** | ❌ 且**无法装载自有模型**（见 §1.3） |
| 6 | **RAG（检索增强）** | `@kit.DataAugmentationKit` → `@hms.data.rag` | `SystemCapability.DataAugmentation.RAG` | ❌ **否 —— 仅 2in1** | ❌ 手机侧不可用 |
| 7 | **知识加工 KnowledgeProcessor** | `@hms.data.knowledgeProcessor` | `SystemCapability.DataAugmentation.KnowledgeProcessor` | ⚠️ syscap 列在 phone，但**声明文件明确写"仅 PC/2in1"** | ❌ 实际不可用 |
| 8 | **检索 Retrieval** | `@hms.data.retrieval` | `SystemCapability.DataAugmentation.Retrieval` | ✅ 是 | ✅ 是（可用于端侧向量检索，**这是你做多智能体记忆/知识库的好东西**） |
| 9 | **传统 ML Kit（ArkTS 直调）** | `@kit.CoreVisionKit`、`@kit.NaturalLanguageKit`、`@kit.VisionKit`、`@kit.SpeechKit` | 各 `SystemCapability.AI.*` | ✅ 是 | ✅ 是 |
| 10 | **小艺端侧模型能力** | **无任何第三方 API** | — | ❌ | ❌ 未对第三方开放 |

### 1.2 逐个说明

#### (1) HiAI Foundation Kit —— 公开但"重工具链"的 NPU 引擎

- **无 ArkTS API**。我在 `hms/ets/api` 全量搜索 `*hiai*`，**零结果**；不存在 `@hms.ai.hiai*` 之类的包。它是**纯 C/NAPI** 能力。网上若有人告诉你用 ArkTS 直接 `import` HiAI 某个模块，**那是编造的 API**。
- 【官方-SDK元数据】`device-define/api-version/CANNKit.json` 中所有 `SystemCapability.AI.HiAIFoundation` 条目均为 `"isSystemApi": "false"`，且 `deviceTypes` 含 `phone since 5.0.0(12)`。→ **是公开 API，手机可用，非系统应用专属**。
- 推理走 NNRt 接口 + 设备名 `HIAI_F`【官方-文档】：
  `OH_NNCompilation_ConstructWithOfflineModelFile` → `OH_NNDevice_GetAllDevicesID`（找 name 含 `HIAI_F` 的设备）→ `OH_NNCompilation_SetDevice` → `OH_NNCompilation_Build` → `OH_NNExecutor_Construct` → `OH_NNExecutor_RunSync`
- HiAI 专属增强在 `CANNKit/hiai_options.h`【官方-SDK声明】，与 LLM 高度相关的有：
  - **动态 shape + 编译缓存**：`HMS_HiAIOptions_SetDynamicShapeStatus` / `SetDynamicShapeMaxCache`（取值 `[1,10]`）/ `SetDynamicShapeCacheMode`（`HIAI_DYNAMIC_SHAPE_CACHE_BUILT_MODEL` / `..._LOADED_MODEL`）→ 这是为自回归解码的 KV-cache/变长序列准备的
  - `HMS_HiAIOptions_SetQuantConfig`（量化配置）、`SetModelDeviceOrder` / `SetOperatorDeviceOrder`（NPU/CPU 异构调度）、`SetFallbackMode`
- 【官方-文档】支持网络中**有 Transformer ☆☆☆☆（NPU 算力利用率≈70%）与 Bert ☆☆☆☆（≈70%）**，但 **Model Zoo 里全部是经典视觉 CNN**（AlexNet/ResNet/MobileNet/YOLO/DeepLab/VDSR…），**没有任何 LLM**；性能数据基于 Kirin 9000 手机。RNN/LSTM 仅 ☆☆"功能支持较为单一"。
- **是否为个人开发者开放 / 是否需要商务合作或白名单**：我未能取得权威文本。论坛存在标题级线索（如"开发app调用平板本地大模型，怎么解决本地大模型配置白名单问题"），但**页面为 JS 渲染，正文未能读取 → 标注【未核实】**。可以确定的是：**SDK 元数据层面没有把它标成系统 API**。

#### (2) CANN LLM Engine —— 华为真正的端侧 LLM 引擎，但**只给 PC**

这是本次调研**最关键、最决定性**的发现。

`CANNKit/llm_engine.h`【官方-SDK声明】提供的是一套**完整的、为 LLM 设计的流式推理 API**（`since 6.1.1(24)`，`libcann_llm_engine.so`）：

- `HMS_LLMEngineContext_CreateFromContextJson(const char* jsonFile)` —— **从 JSON 配置创建上下文**（即模型路径/参数由 JSON 描述）
- `HMS_LLMEngineExecutor_CreateFromExecutorJson(const char* jsonFile)`
- `HMS_LLMEnginePrompt_Create()` / `SetText()` / `SetTokenId()`
- 流式回调：`SetOnOneTokenGenerateDoneFunc` / `SetOnAllTokensGenerateDoneFunc` / `SetOnGenerateAsyncFailed`
- `Generate` / `GenerateAsync`
- **专业性能指标**：`GetPrefillTimeMs`（prefill 耗时）、`GetDecodeTimeMs`（decode 耗时）、`GetTotalTimeMs`、`GetInputTokenCount`、`GetOutputTokenCount` —— 这套指标是典型的 LLM serving 设计
- 性能档位 `HMS_LLMEngine_InferPerfMode`：`UNSET / LOW / MIDDLE / HIGH / EXTREME_HIGH`

**但是 —— 它只支持 2in1：**

- 【官方-SDK元数据】`device-define/2in1-hmos.json` 含 `"SystemCapability.AI.CANN.LLMEngine"`；**`phone-hmos.json` 不含**。
- 【官方-SDK元数据】`device-define/api-version/CANNKit.json` 中，`llm_engine.h` 的**全部 37 条 API，`deviceTypes` 一律为 `2in1`**（我逐条枚举确认，无一例外）。

> ⚠️ **重要澄清（避免过度乐观）**：`hms/native/sysroot/usr/lib/*/libcann_llm_engine.so` 文件**确实存在**（6736 字节），`libhiai_foundation.so` 也在（11968 字节）。但这些是 **NDK 链接用 stub 库**（体积极小即证），只用于编译期符号解析，真实实现在设备系统分区。**头文件/so 存在 ≠ 手机运行时可用**；`device-define` 元数据才是设备可用性的权威依据。手机开发者若链接 `libcann_llm_engine.so`，很可能在真机上 `dlopen`/调用失败。

**结论：把 Qwen2.5-1.5B/3B 用 CANN LLM Engine 跑在 HarmonyOS NEXT 手机上 —— 官方不支持。**

#### (3) MindSpore Lite Kit —— 手机唯一"能装自有模型"的官方通道

【官方-SDK声明】`openharmony/ets/kits/@kit.MindSporeLiteKit.d.ts` → `@ohos.ai.mindSporeLite`（`since 10`）：

- **可装载自有模型**（关键）：
  - `loadModelFromFile(model: string, context?: Context): Promise<Model>`
  - `loadModelFromBuffer(model: ArrayBuffer, ...)`
  - `loadModelFromFd(model: number, ...)`
- 执行：`model.predict(inputs: MSTensor[])`、`getInputs()`、`resize(inputs, dims)`
- 设备上下文 `Context`：`cpu?: CpuDevice`、**`nnrt?: NNRTDevice`**（→ 把算子下发给 NNRt → NNRt 可再落到 HiAI Foundation 的 NPU 上）
- `QuantizationType`、`OptimizationLevel`、`PerformanceMode`、`Priority`

**定位关键**：它位于 **`openharmony/`** 目录，且 `device-define/api-version/MindSporeLiteKit.json` 中每条 API 的 `"OS": "OpenHarmony"`、`"isSystemApi": "false"`、`deviceTypes` 含 `phone since 12`。→ **属于开源基线能力，没有 HMS 白名单/企业资质门槛**，这是个人开发者最容易走通的一条路。

**但代价**：MindSpore Lite 是**通用图推理运行时**（`predict(tensors) -> tensors`），**不是 LLM 运行时**。它不提供 tokenizer、不提供 chat template、不提供 KV-cache 管理、不提供采样/约束解码、**不提供 function calling**。用它跑 Qwen 意味着你要自己写完整的 LLM 推理闭环。

#### (4) Neural Network Runtime (NNRt)

【官方-SDK声明】`openharmony/native/sysroot/usr/include/neural_network_runtime/{neural_network_runtime,neural_network_core,neural_network_runtime_type}.h`，库 `libneural_network_runtime.so` / `libneural_network_core.so`，映射 `"neural_network_runtime": "SystemCapability.AI.NeuralNetworkRuntime"`。它是**推理框架与硬件（NPU）之间的桥梁**：MindSpore Lite / MNN / PaddleLite 通过 NNRt 把算子卸载到 NPU，而 NPU 后端就是 HiAI Foundation。个人开发者可用（开源侧）。

#### (5)(6)(7) 端侧大模型 / RAG / 知识加工 —— 全部锁在 PC

- `localChatModel`【官方-SDK声明】整个命名空间**只有两个函数**：`init(): Promise<boolean>` 和 `chat(info: QuestionInfo, config: Config, callback)`。**没有任何模型装载/路径/权重 API**。→ 它是**华为内置的固定端侧问答模型**，你只能给它 `content: string`（建议 ≤4500 字节）问问题，**不可能把它换成 Qwen**。
- 且 syscap `SystemCapability.DataAugmentation.LocalChatModel` 与 `...DataAugmentation.RAG` **只出现在 `2in1-hmos.json`**，`phone-hmos.json` 没有 → **手机不可用**。
- `knowledgeProcessor`【官方-SDK声明】原文："The embedding model on which the knowledge processing capability depends can be deployed only on PCs/2-in-1 devices. Therefore, the knowledge processing capability is supported only on PCs/2-in-1 devices." 且 `startProcess` 会抛 `801 - Device type error`。

#### (8) 小艺端侧模型是否对第三方开放？

**否。** 我遍历了 `hms/ets/api` 下全部 23 个 `@hms.ai.*` 模块，**没有任何一个是"调用小艺端侧大模型做生成"的 API**。小艺只能通过 AgentFrameworkKit **以"拉起小艺智能体"的方式**间接使用（见 §3），那是**云端智能体**，且模型不是你的。

#### (9) 传统 ML Kit（手机可用、可直接用 ArkTS 调、个人开发者无门槛）

【官方-SDK声明】`hms/ets/kits` 中实际导出：

| Kit | 模块 |
|---|---|
| `@kit.CoreVisionKit` | `textRecognition`(OCR)、`faceDetector`、`faceComparator`、`subjectSegmentation`、`visionBase`、`objectDetection`、`skeletonDetection`、`imageSuperResolution`、`textSearchImage` |
| `@kit.NaturalLanguageKit` | `textProcessing`、`EntityType` |
| `@kit.VisionKit` | `interactiveLiveness`、`CardRecognition`、`DocumentScanner`、`visionImageAnalyzer` |
| `@kit.SpeechKit` | `TextReader`、`AICaption` |
| 其他 | `@hms.ai.textToSpeech`、`@hms.ai.speechRecognizer` |

这些是**非 LLM 的端侧小模型**，但**开箱即用、手机可用、无需资质**——是 §5 混合方案的现成积木。

---

## 2. 如果要部署自己的模型：完整流程与明确结论

### 2.1 路线 A：HiAI Foundation（NPU 加速）【官方-文档】

```
① 环境：Ubuntu 64 位（OMG 模型转换工具只跑 Linux）
② 工具：tools_omg（模型转换）、tools_dopt（轻量化/量化）
③ 模型来源：自己训练的 Caffe / TensorFlow / ONNX / MindSpore 模型
   （或从华为 Model Zoo 下载 —— 但 Model Zoo 全是视觉 CNN，无 LLM）
④ 量化（可选）：tools_dopt → Quant_INT8-8（权重 8bit + 数据 8bit）
   模式：无训练量化（TF/PyTorch/ONNX）/ 插件式量化 / 网络结构搜索
   依赖：Python 3.10 + Ubuntu 22.04 + TF 2.8.0 或 PyTorch 1.11 或 ONNX 1.14/ORT 1.15
⑤ 模型转换：OMG 工具 → **`.om` 离线模型**（算子编译成硬件 AI 指令序列）
⑥ App 集成：C++ NAPI + CMakeLists，链接 libhiai_foundation.so + libneural_network_core.so
⑦ 推理：NNRt API，设备名找 HIAI_F
⑧ 官方示例：gitee.com/harmonyos_samples/hiaifoundationkit-samplecode-clientdemo-cpp
```

### 2.2 路线 B：MindSpore Lite（CPU，无工具链门槛）

```
① 训练/导出：MindSpore / PyTorch / TF → ONNX
② 转换：MindSpore Lite Converter → **`.ms` 模型**
③ 或直接使用 MindSpore Model Zoo 的 .ms 模型
④ 放进工程 rawfile，用 @ohos.ai.mindSporeLite loadModelFromFile/Buffer 装载
⑤ predict() 拿张量。NPU 需配 Context.nnrt
```

### 2.3 明确结论

| 问题 | 结论 |
|---|---|
| **模型格式要求** | HiAI：`.om`（OMG 转换）；MindSpore Lite：`.ms`（Lite Converter）。**两者都不吃 GGUF / safetensors** |
| **需要什么转换工具** | HiAI：`tools_omg` + `tools_dopt`（**仅 Linux/Ubuntu**）；MindSpore Lite：MindSpore Lite Converter |
| **模型从哪来** | 自己训练/转换，或华为 Model Zoo（**无 LLM**，仅视觉 CNN） |
| **是否需要华为审核** | 路线 B（MindSpore Lite，开源侧）**在 SDK 元数据中无审核/白名单标记**；路线 A 是否存在白名单**未能核实** |
| **是否需要特定芯片/算力** | HiAI 的 NPU 加速依赖**麒麟（Kirin）达芬奇架构 NPU**；无 NPU 时回落 CPU。MindSpore Lite 默认 CPU |
| **个人开发者能否走通？** | **路线 B 能走通（无资质门槛），但只能跑小模型/非 LLM 任务，且无 function calling**；**路线 A 理论可行但要把 Qwen 塞进"静态 `.om` 离线图"极其困难，且无官方 LLM 支持与文档，实际不可行** |

### 2.4 为什么把 Qwen 塞进 HiAI Foundation 不可行（技术推理）

HiAI Foundation 的 OMG 流程是**离线静态图编译**（"把算子离线编译成硬件专用 AI 指令序列，指令与数据融合生成离线模型"）。LLM 自回归解码需要：动态序列长度、KV-cache 跨步复用、每步不同的 attention mask。虽然 `hiai_options.h` 提供了动态 shape + 缓存（`SetDynamicShapeMaxCache` 上限仅 **10** 个缓存编译模型），但：
- **Model Zoo 与官方支持网络清单里完全没有 LLM/Decoder-only 模型**
- **没有任何官方文档、示例、算子清单表明 OMG 能吃下 Qwen 架构**
- 华为把 LLM 单独做成了 `llm_engine.h`（**只给 2in1**）——这本身就是"通用 `.om` 路线不适合 LLM"的最强反证

**关于 function calling 的硬事实**：HarmonyOS **不提供任何**针对自有模型的 function calling 能力。若你自建推理，工具调用必须由你自己实现（Qwen2.5 的 Hermes 风格 `<tool_call>` JSON 模板 + 约束解码 + 解析 + 回灌），SDK 不提供 tokenizer / chat template / 约束采样。

---

## 3. AI-Agent Framework Kit 与 Intents Kit

### 3.1 实际包名与模块名（本地实测，可直接 import）

**【官方-SDK声明】`hms/ets/kits/@kit.AgentFrameworkKit.d.ts`（`@since 6.0.0(20)`）实际内容：**

```ts
import { AgentController, BaseOptions, FunctionController, FunctionOptions,
         ButtonType, FunctionComponent } from '@hms.ai.AgentFramework';
import { Role, TaskState, Part, Message, Artifact, TaskStatus, Task,
         OnDataCallback, createA2AServer, ProxySender, Server,
         RequestContext, TaskArtifactParam } from '@hms.ai.A2A';
```

| 层 | 包名 | 说明 |
|---|---|---|
| Kit 入口 | `@kit.AgentFrameworkKit` | since 6.0.0(20)；**手机可用**（syscap `SystemCapability.AI.Agent.AgentKit` 在 `phone-hmos.json` ✅） |
| 智能体组件 | `@hms.ai.AgentFramework` (`@hms.ai.AgentFramework.d.ets`) | **since 6.0.0(20)**。`AgentController`、`FunctionController`、`FunctionComponent`(@Component)、`ButtonType{CIRCLE,CAPSULE,ICON_ABOVE_TITLE}`、`BaseOptions`、`FunctionOptions` |
| **A2A 协议** | `@hms.ai.A2A` (`@hms.ai.A2A.d.ts`) | **since 26.0.0** ← 你这个 SDK 版本刚好有！含 `createA2AServer(agentCard, onData, want?)`、`Role`、`TaskState`、`Part`、`Message`、`Artifact`、`TaskStatus`、`Task`、`Server`、`RequestContext`、`TaskArtifactParam`、`ProxySender`、`OnDataCallback` |
| Intents Kit | `@kit.IntentsKit` | since 4.1.0(11) |
| 意图共享 | `@hms.ai.insightIntent` | `@since 4.0.0(10)`，syscap `SystemCapability.AI.InsightIntent`（手机 ✅）。`shareIntent` / `deleteIntent` / `deleteEntity` |
| 意图 UI 扩展 | `@hms.ai.insightIntent.InsightIntentUIExtensionAbility` | — |

**两个关键注解（决定"是否还算端侧"）**：
- 所有 AgentFrameworkKit 与 A2A 成员都标 `@syscap SystemCapability.AI.Agent.AgentKit`、`@stagemodelonly`、`@atomicservice [since 6.0.1(21)]`
- `@hms.ai.AgentFramework.d.ets` 头部标注 **`@bundle com.huawei.hmsapp.hiai.hsp/agentKitHsp/Index 6.0.0(20)`** → 它是**华为 HMS 提供的系统 HSP**。本地 `hms/previewer/systemHsp/hmsapp/hiai/hsp/agentKitHsp.hsp` 文件确实存在。

### 3.2 是否有公开 API 参考文档与示例？

**有。**【官方-文档】已确认存在以下官方文档页（均已通过搜索定位到 URL）：
- A2A 协议 API 参考：`developer.huawei.com/consumer/cn/doc/doccenter-capabilities/api/hmaf-a2a-protocol`
- 通过 AgentAbilityExtension 实现智能体间 A2A 通信：`.../doccenter-capabilities/hmaf-a2a-dev-guide`
- AgentExtensionAbility 配置文件说明（端侧 A2A 框架开发指导）：`.../doccenter-capabilities/agent-extension-configuration?docScope=all`
- AgentCard 定义规范（端 A2A 协议技术规范，小艺开放平台）：`.../doc/service/agentcard-0000002678424557`

⚠️ **诚实说明**：华为文档中心是 **SPA/JS 渲染**，`web_fetch` 只能拿到 `文档中心` 骨架文本（我实测 3 次均如此）。以上文档**存在性已确认**，但**正文细节我未能读取**，故 §3 的所有技术断言均以**本地 SDK 声明文件**为准（这反而是更硬的证据）。

### 3.3 对个人开发者是否开放？是否需要权限申请？

- 【官方-SDK元数据】`SystemCapability.AI.Agent.AgentKit` 出现在 `phone-hmos.json` 与 `tablet-hmos.json`，**不在** `api-white-list.json` 中 → **手机侧是公开能力，无需白名单 syscap**。
- 【官方-SDK声明】我在 `@hms.ai.A2A.d.ts`、`@hms.ai.AgentFramework.d.ets`、`@hms.data.localChatModel.d.ts` 中**逐文件搜索 `@permission`，三者均为零结果** → **无需声明 `ohos.permission.*`**。
- ⚠️ **但有实质性门槛（不是权限，是账号+云+注册）**：`AgentController.isAgentSupport(context, agentId)` 抛出：
  - `1022400011 - Privacy agreement not accepted.`
  - `1022400012 - HUAWEI ID not signed in.`
  - `1022400013 - Internet error.`
  - `1022400010 - Parameter error` / `1022400014 - Internal error`

  `agentId` 的文档说明是"**when the agent is created**"，并链接到华为开发者服务端的快速开始页。→ **要跑通必须先注册华为账号、同意隐私协议、联网，并在华为侧"创建智能体"拿到 agentId。** 这是一条**云 + 账号绑定**的链路，不是本地 API。
- 【社区】Intents Kit 方面，论坛存在"现在需要接入意图框架的话是必须要有已经上架的应用吗？""应用不上架是否可以使用意图框架"等提问，**暗示存在上架/申请要求**；但正文未读取 → **【未核实】**。

### 3.4 能否用于实现多个智能体之间的协作（A2A）？

**能 —— 而且这是本 SDK 最令人惊喜的发现，但要分清两层。**

**第一层：HMS 层 `@hms.ai.A2A`（华为 HMAF）**
【官方-SDK声明】`since 26.0.0`，正好是你的版本。提供 `createA2AServer(agentCard, onData, want?) => Server`、`Server`、`RequestContext`、`Task`/`TaskStatus`/`TaskState`、`Message`/`Part`/`Artifact`、`Role`、`ProxySender`、`OnDataCallback`、`TaskArtifactParam` —— 这是一套**完整的 A2A 服务端实现**（可让**你的应用作为 A2A 服务端被调用**），而非只是客户端。

**第二层：OpenHarmony 开源基线层（端侧 A2A 运行时）**
【官方-SDK声明】`openharmony/ets/api` 下还有一整套 **Agent Runtime**：

| 文件 | 关键内容 | since |
|---|---|---|
| `@ohos.app.agent.AgentExtensionAbility` | `AgentExtensionAbility`，syscap `SystemCapability.Ability.AgentRuntime.Core`，`onCreate/onConnect/onData`，`AgentHostProxy`。注："**cannot be used in Harmony Archive(HAR)**" | **24** |
| `@ohos.app.agent.AgentUIExtensionAbility` | 带 UI 的智能体扩展 | 24 |
| `@ohos.app.agent.agentConstant` | `AgentCardType { APP = 0, ATOMIC_SERVICE = 1 }`（注：`LOW_CODE` 类型**必须系统应用**） | 26.0.0 |
| `application/AgentCard.d.ts` | **完整 A2A AgentCard 标准结构** | 24 |
| `application/AgentHostProxy`、`AgentExtensionContext` | 宿主代理与上下文 | 24 |
| `@ohos.bundle.skillManager` | `getSkillInfoForSelf(moduleName, skillName, flags)`、`SkillInfoFlag` | 26.0.0 |
| `@ohos.app.ability.InsightIntentDecorator` / `InsightIntentExecutor` / `InsightIntentProvider` / `InsightIntentEntryExecutor` / `InsightIntentContext` | 意图/技能声明与执行 | — |

**【官方-SDK声明】`AgentCard` 字段与业界 A2A 规范一致**（这就是"多智能体协作"的数据契约）：
```
agentId, name, description, version, iconUrl, category, documentationUrl, extension
type?: AgentCardType
provider?: { organization, url }
capabilities?: { streaming?, pushNotifications?, stateTransitionHistory?, extendedAgentCard?, extension? }
defaultInputModes: string[]      defaultOutputModes: string[]
skills: [{ id, name, description, tags[], examples?, inputModes?, outputModes?, extension? }]
appInfo: { bundleName, moduleName, abilityName, deviceTypes?, minAppVersion? }
```

**⚠️ 但对你的课题，"能不能用 A2A" 与 "能不能跑你自己的模型" 是两个独立问题：**
- A2A 解决的是**智能体之间怎么通信/协作**（协议层）→ ✅ HarmonyOS 26 提供了
- 它**不解决**"每个智能体的推理从哪来" → ❌ 手机侧没有可装载自有 LLM 的官方通道

所以你完全可以做出**架构正确、协议真实**的多智能体 A2A 应用，但每个智能体的"大脑"要么是**云端 LLM**，要么是**局域网 PC**，要么是你自己用 MindSpore Lite 硬啃的小模型。

**另一个必须点出的坑**：【官方-SDK声明】`FunctionController` 的文档原文写着——
> "Function component controller, which is used to control the interactions with Function components. **This API is reserved. In the current version, this API inherits from AgentController's methods without any additional implementation.**"

→ **`FunctionController` 是保留 API，没有任何额外实现。** 名字里有 "Function" 极易被误认为 "function calling"，**它不是**。不要把它当作工具调用的官方支持。

---

## 4. DevEco Studio 26 本机验证线索（可自行执行）

以下命令我已在本机执行验证，均可复现。

### 4.1 确认 SDK 版本与布局

```powershell
$sdk = "D:\develop\DevEco Studio\sdk\default"
Get-Content "$sdk\sdk-pkg.json"          # 期望: apiVersion 26, HarmonyOS 26.0.0
Get-ChildItem $sdk                        # 期望: hms, openharmony, sdk-pkg.json
```

### 4.2 列出全部 AI / Agent / Intent 相关 Kit 与模块

```powershell
# HMS 侧 Kit（56 个中的相关项）
Get-ChildItem "$sdk\hms\ets\kits" -File |
  Where-Object Name -match 'Agent|Intent|AI|Data|Vision|Speech|Natural|Core'

# HMS 侧 @hms.ai.* 模块全清单（23 个）
Get-ChildItem "$sdk\hms\ets\api" -File | Where-Object Name -like '@hms.ai.*'

# 开源侧 MindSpore / Agent Runtime / InsightIntent
Get-ChildItem "$sdk\openharmony\ets\api" -File |
  Where-Object Name -match 'mindSpore|agent|insightIntent|skillManager'
Get-ChildItem "$sdk\openharmony\ets\kits" -File |
  Where-Object Name -match 'MindSpore|Ability'
```

### 4.3 确认 HiAI / CANN / MindSpore 原生库与头文件

```powershell
# HiAI Foundation + CANN LLM Engine 头文件
Get-ChildItem "$sdk\hms\native\sysroot\usr\include\CANNKit"
# 期望: hiai_aipp_param.h hiai_helper.h hiai_options.h hiai_single_op.h hiai_tensor.h llm_engine.h

# 原生库（注意：是 NDK stub，体积很小）
Get-ChildItem "$sdk\hms\native\sysroot\usr\lib\aarch64-linux-ohos" |
  Where-Object Name -match 'llm|cann|hiai'
# 期望: libcann_llm_engine.so (~6.7KB), libhiai_foundation.so (~12KB)

# MindSpore Lite + NNRt
Get-ChildItem "$sdk\openharmony\native\sysroot\usr\include\mindspore"
Get-ChildItem "$sdk\openharmony\native\sysroot\usr\include\neural_network_runtime"
Get-ChildItem "$sdk\openharmony\native\sysroot\usr\lib\aarch64-linux-ohos" |
  Where-Object Name -match 'mindspore|neural'
```

### 4.4 ★ 最关键的一条：查"某能力在手机上是否可用"

这是本次调研的**方法论核心**，强烈建议你自己跑一遍：

```powershell
# 手机(HarmonyOS NEXT) 支持的 AI 能力 —— 注意这里没有 CANN.LLMEngine / LocalChatModel / RAG
Select-String -Path "$sdk\hms\ets\api\device-define\phone-hmos.json" `
  -Pattern 'AI\.|DataAugmentation'

# 2in1(PC) 才有的能力
Select-String -Path "$sdk\hms\ets\api\device-define\2in1-hmos.json" `
  -Pattern 'CANN|LocalChatModel|RAG|DataAugmentation'

# 逐条确认 LLM Engine 的设备归属（应为清一色 2in1）
$raw = Get-Content "$sdk\hms\ets\api\device-define\api-version\CANNKit.json" -Raw
[regex]::Matches($raw, '"apiText":\s*"([^"]*LLMEngine[^"]*)"') | ForEach-Object { $_.Groups[1].Value }
```

**phone-hmos.json 实测输出**（节选，AI 相关）：
```
SystemCapability.AI.AICaption
SystemCapability.AI.Agent.AgentKit          ← 手机有 ✅
SystemCapability.AI.Component.CardRecognition
SystemCapability.AI.Component.DocScan
SystemCapability.AI.Component.LivenessDetect
SystemCapability.AI.Component.TextReader
SystemCapability.AI.Face.Comparator
SystemCapability.AI.Face.Detector
SystemCapability.AI.HiAIFoundation          ← 手机有 ✅
SystemCapability.AI.InsightIntent           ← 手机有 ✅
SystemCapability.AI.NaturalLanguage.TextProcessing
SystemCapability.AI.OCR.TextRecognition
SystemCapability.AI.SpeechRecognizer
SystemCapability.AI.TextToSpeech
SystemCapability.AI.Vision.ObjectDetection
SystemCapability.AI.Vision.SkeletonDetection
SystemCapability.AI.Vision.SubjectSegmentation
SystemCapability.AI.Vision.VisionBase
SystemCapability.AI.VisionImageAnalyzer
SystemCapability.DataAugmentation.KnowledgeProcessor
SystemCapability.DataAugmentation.Retrieval  ← 手机有 ✅（端侧向量检索可用于智能体记忆）
# 无 SystemCapability.AI.CANN.LLMEngine ❌
# 无 SystemCapability.DataAugmentation.LocalChatModel ❌
# 无 SystemCapability.DataAugmentation.RAG ❌
```

### 4.5 其他值得查的文件

```powershell
# 各 AI Kit 的逐 API 设备矩阵
Get-ChildItem "$sdk\hms\ets\api\device-define\api-version" -File |
  Where-Object Name -match 'Agent|Intents|DataAugmentation|MindSpore|CANN|NeuralNetwork'

# 原生库 → syscap 映射
Get-Content "$sdk\hms\native\ndk_system_capability.json"
Get-Content "$sdk\openharmony\native\ndk_system_capability.json"
# 关键输出：cann_llm_engine → SystemCapability.AI.CANN.LLMEngine
#           hiai_foundation → SystemCapability.AI.HiAIFoundation
#           mindspore_lite_ndk → SystemCapability.Ai.MindSpore
#           neural_network_runtime → SystemCapability.AI.NeuralNetworkRuntime

# AgentFrameworkKit 是华为系统 HSP 的直接证据
Get-ChildItem "$sdk\hms\previewer\systemHsp\hmsapp\hiai\hsp"   # 含 agentKitHsp.hsp
```

### 4.6 代码层自检（编译期 + 运行期）

```ts
// 编译期：canIUse 判断能力是否存在（手机真机上 CANN.LLMEngine 预期为 false）
import { canIUse } from '@ohos.arkui.StateManagement';  // 视 SDK 版本调整引入
// 简单直接的方式：在代码里判断
if (canIUse('SystemCapability.AI.CANN.LLMEngine')) { /* 2in1 */ }

// 运行期：确认 syscap 集合（@ohos.deviceInfo / 相关接口按 SDK 实际声明使用）
```

```bash
# 真机侧确认系统库是否真的存在（需 hdc 已连接）
hdc shell "ls -l /system/lib64/ | grep -E 'cann|hiai|mindspore|neural'"
```
> ⚠️ 具体系统分区路径我**未核实**，请以真机输出为准；若 `libcann_llm_engine.so` 在手机上根本不存在，则从运行期再次印证 §1.2(2) 的结论。

---

## 5. 降级路径评估

评分说明：延迟为**量级估算**【估算】，非官方数据；"能否声称 on-device/edge"按学术审稿常见标准给出。

### 方案 A：手机直连云端 LLM API（DeepSeek / 通义千问）

| 维度 | 评估 |
|---|---|
| 实现难度 | ★☆☆☆☆ **最低**。`@ohos.net.http` 或 `@kit.RemoteCommunicationKit` 发 HTTPS POST，SSE 流式解析 |
| 延迟量级 | **0.5–3 s** 首 token（含网络 RTT，估算），依赖网络质量 |
| 额外硬件 | 无 |
| function calling | ✅ **原生支持**。DeepSeek / 通义都提供 OpenAI 兼容的 `tools`/`tool_calls` |
| 成本 | 按 token 计费；本科课题量级通常几元到几十元 |
| **能否声称 on-device/edge** | ❌ **不能**。纯云方案在审稿中会被直接判定为 "cloud-based"，只能算"端侧智能体编排（agent orchestration on device）" |
| 备注 | **必须做**，无论选哪条路，云端 LLM 都是最可靠的 baseline 与 fallback |

### 方案 B：局域网调用同 WiFi PC 上的 Ollama / llama.cpp ★ 推荐

| 维度 | 评估 |
|---|---|
| 实现难度 | ★★☆☆☆ **低**。PC 起 Ollama（`OLLAMA_HOST=0.0.0.0`）或 `llama-server`，手机 HTTP 调 `/v1/chat/completions`；同一 WiFi 即可，**无需公网、无需备案、无 API 费用** |
| 延迟量级 | **0.1–1 s** 首 token（局域网 RTT < 10 ms，估算）；瓶颈是 PC 算力 |
| 额外硬件 | **需要一台 PC/笔记本**（跑 Qwen2.5-3B INT4 只需 4–6 GB 显存或纯 CPU 也能跑） |
| function calling | ✅ **完整支持**。Ollama 支持 `tools`（Qwen2.5 / Llama3.1 等），llama.cpp 有 GBNF 语法约束解码 + `--jinja` chat template |
| 模型自由度 | ✅ **最高**。任意 GGUF：Qwen2.5-1.5B/3B INT4、甚至 7B |
| **能否声称 on-device/edge** | ✅ **可以声称 edge**（这是标准的 edge/cloud collaborative inference 或 edge offloading 设定，有大量可引用的学术先例）。❌ 但**不能声称 on-device / on-phone** |
| 学术定位建议 | 论文中明确写成 "**edge-assisted / LAN-offloaded multi-agent inference**"，并把"端侧智能体编排 + 边缘模型推理"作为贡献点——这是**诚实且仍然有卖点**的定位 |

### 方案 C：调用华为小艺 / 盘古开放能力

| 维度 | 评估 |
|---|---|
| 实现难度 | ★★★☆☆ 中。`AgentFrameworkKit` 的 `FunctionComponent` + `agentId` 是**最省事的"看起来很多智能体"**路径；但需注册华为开发者、同意隐私协议、登录 HUAWEI ID、**并在华为侧创建智能体拿 agentId** |
| 延迟量级 | **1–5 s**（云侧智能体，估算） |
| 额外硬件 | 无 |
| 模型归属 | ❌ **不是你的模型**，是华为云侧智能体 |
| **能否声称 on-device/edge** | ❌ **不能**（云侧），且**不可复现**（依赖华为账号与商业服务） |
| 风险 | `FunctionController` 是**保留空实现**；`AgentController` 报错码含隐私协议/账号/网络 → 演示与批改都不稳定 |
| 价值 | 可作为"生态兼容性"章节的**加分展示**，但**不能作为论文主实验** |

### 方案 D：端侧传统 ML Kit（非 LLM）+ 云端/边缘 LLM 混合

| 维度 | 评估 |
|---|---|
| 实现难度 | ★★★☆☆ 中。端侧跑 OCR/人脸/主体分割/图像超分/文本处理（`CoreVisionKit`、`VisionKit`、`NaturalLanguageKit`、`SpeechKit`），LLM 走云或局域 |
| 延迟量级 | 端侧 ML Kit：**10–200 ms**（本地小模型，估算）；LLM 部分同方案 A/B |
| 额外硬件 | 无（端侧部分） |
| function calling | 由 LLM 侧（云或局域）提供 |
| **能否声称 on-device/edge** | ⚠️ **Partial on-device**。可诚实声称"**多模态感知在端侧完成，推理大脑在云/边缘**"，即 **on-device perception + off-device reasoning** 的混合架构 |
| 学术定位 | **这是最容易讲成故事、也最贴合华为"端云协同"叙事的方案**，且端侧部分**完全可复现、无需资质** |

### 5.1 方案对比矩阵

| 方案 | 难度 | 首 token 延迟 | 额外硬件 | 真 function calling | on-device 声称 | 可复现性 |
|---|---|---|---|---|---|---|
| A 纯云 API | ★☆☆☆☆ | 0.5–3 s | 无 | ✅ | ❌ 纯云 | ✅ 高 |
| **B 局域网 PC** | ★★☆☆☆ | 0.1–1 s | **PC** | ✅ | ✅ **可称 edge** | ✅ 高 |
| C 华为智能体 | ★★★☆☆ | 1–5 s | 无 | ⚠️ 保留 API | ❌ 云侧 | ❌ 依赖账号 |
| D 传统 ML + LLM 混合 | ★★★☆☆ | 10–200 ms(端) + A/B | 无/PC | ✅（LLM 侧） | ⚠️ Partial | ✅ 高 |
| **（不可行）手机本地自部署 Qwen** | — | — | — | ❌ SDK 不提供 | ✅ 理论最优 | ❌ **官方不支持** |

---

## 6. 最终结论与建议

### 6.1 一句话可行性结论

> **不能**——这个本科生**无法**在 HarmonyOS NEXT 真机上跑自己的 Qwen2.5-1.5B/3B INT4 并获得官方 function calling：手机侧唯一能"装载自有模型"的官方通道是 **MindSpore Lite**（开源基线、CPU 为主、无 LLM 运行时、无工具调用支持，需自己实现整个 LLM 推理闭环），而华为真正为 LLM 设计的 **CANN LLM Engine（`CANNKit/llm_engine.h`）在 SDK 元数据中被明确限定为 2in1（PC）设备，手机上不可用**；`localChatModel` 与 `RAG` 同样仅限 2in1，且 `localChatModel` 根本不接受外部模型。

### 6.2 推荐的降级方案排序

1. **🥇 方案 B：局域网调用 PC 上的 Ollama / llama.cpp**
   —— 唯一同时满足"真实运行 1.5B–3B 量化模型 + 完整 function calling + 学术上可声称 edge"的方案。论文定位为 **edge-assisted multi-agent inference**。硬件门槛最低（一台 PC + 同一 WiFi）。

2. **🥈 方案 D：端侧传统 ML Kit + 云端/边缘 LLM 混合**
   —— 用 `CoreVisionKit` / `VisionKit` / `NaturalLanguageKit` / `SpeechKit` + `DataAugmentation.Retrieval`（手机侧可用）做端侧感知与记忆检索，LLM 大脑走方案 B 或 A。可诚实声称 **on-device perception + off-device reasoning**，最贴合华为"端云协同"叙事，且端侧部分零资质门槛。

3. **🥉 方案 A：纯云端 LLM API（DeepSeek / 通义）**
   —— 工程上最稳、最快出成果，**务必作为 baseline 与 fallback**。但审稿时**不能**声称 on-device。

4. **方案 C：华为 AgentFrameworkKit / 小艺智能体**
   —— 只建议作为"生态兼容性"章节的展示项。不要作为主实验：模型不是你的、`FunctionController` 是保留空实现、且强绑定华为账号与隐私协议，**可复现性差**。

### 6.3 给这个本科生的具体行动建议

1. **立即用 §4.4 的命令自证**：跑一遍 `phone-hmos.json` 的 syscap 检索，亲眼确认 `CANN.LLMEngine` / `LocalChatModel` / `RAG` 不在手机列表里。这一步 1 分钟，能避免几周弯路。
2. **把课题重新定位**：从"端侧自部署 LLM"改为 "**HarmonyOS 端侧多智能体编排 + 边缘模型推理**"。用真实的 `@hms.ai.A2A`（since 26.0.0）+ `AgentExtensionAbility` + `AgentCard` 构建 A2A 多智能体协作——**这是真实、可演示、且很有新意的技术点**，且手机可用、无权限门槛。
3. **端侧保留真材料**：用 `DataAugmentation.Retrieval`（手机可用）做智能体长期记忆，用 `CoreVisionKit` 等做端侧多模态感知。这样"端侧"是真的，不只是包装。
4. **可选加分项**：花 1–2 天用 MindSpore Lite 装载一个**小模型**（如端侧 Embedding 或分类器 `.ms`）跑通 `loadModelFromFile` → `predict`，证明"端侧自部署模型"能力，同时坦诚说明当前限制。这会让报告的技术深度显著提升。
5. **不要做的事**：不要绑定 `libcann_llm_engine.so` 或指望 ArkTS 直调 HiAI（不存在该包）；不要试图把 Qwen 转成 `.om`；不要把 `FunctionController` 当 function calling。

---

## 7. 未核实清单（诚实标注）

| 事项 | 状态 |
|---|---|
| HiAI Foundation Kit 是否需要企业开发者资质 / 白名单申请 / 商务合作 | **未核实**。SDK 元数据显示 `isSystemApi:false`（非系统 API），但取得权威文本失败；论坛有"本地大模型配置白名单"标题级线索，正文因 JS 渲染未读到 |
| Intents Kit 是否要求应用已上架 / 是否需申请 | **未核实**。论坛存在相关提问（"必须要有已经上架的应用吗"），正文未读到 |
| 华为文档中心各页正文（A2A dev guide、AgentExtensionAbility 配置、AgentCard 规范、CANNKit API） | **未能读取**。`developer.huawei.com` 文档为 SPA，`web_fetch` 仅返回骨架。存在性已由搜索结果确认；所有技术断言改用本地 SDK 声明文件作为依据 |
| HiAI Foundation 的 OMG 工具是否真能吃下 Qwen2.5 类 decoder-only 架构 | **未核实**（官方支持网络清单与 Model Zoo 中均无 LLM，故判断为不可行，但非官方明文否定） |
| 手机系统分区中 `libcann_llm_engine.so` 是否物理存在 | **未核实**（需 `hdc shell` 在真机上确认；SDK 中的是 NDK stub） |
| `SystemCapability.DataAugmentation.KnowledgeProcessor` 在手机上是否真的完全不可用 | **部分核实**。声明文件明文"仅 PC/2in1"且 `startProcess` 抛 `801 Device type error`，但该 syscap 又出现在 `phone-hmos.json` → 存在元数据与文档不一致，建议真机实测 |
| 各降级方案的延迟数值 | **【估算】**，非官方或实测数据 |
| llama.cpp / Ollama 在 HarmonyOS 上是否有官方移植 | **未核实**（社区广泛讨论的是"能否"，未发现官方支持；本报告未把"手机直接跑 llama.cpp"作为推荐路径） |

---

## 8. 来源

### 官方文档（华为）
- [MindSpore Lite Kit 简介](https://developer.huawei.com/consumer/cn/doc/HarmonyOS-Guides/mindspore-lite-kit-introduction)
- [CANN Kit（CANN 异构计算框架服务）C API](https://developer.huawei.com/consumer/cn/doc/harmonyos-references/cannkit)
- [llm_engine.h（CANN Kit LLM Engine API）](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/api/cannkit-llm-engine)
- [A2A（A2A 协议）API 参考 — AI-Agent Framework Kit](https://developer.huawei.com/consumer/cn/doc/doccenter-references/api/hmaf-a2a-protocol)
- [通过 AgentAbilityExtension 实现智能体间 A2A 协议通信](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/hmaf-a2a-dev-guide)
- [AgentExtensionAbility 配置文件说明 — 端侧 A2A 框架开发指导](https://developer.huawei.com/consumer/cn/doc/doccenter-capabilities/agent-extension-configuration?docScope=all)
- [AgentCard 定义规范 — 端 A2A 协议技术规范（小艺开放平台）](https://developer.huawei.com/consumer/cn/doc/service/agentcard-0000002678424557)
- [HiAI Foundation Kit 常见问题](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides-V13/hiaifoundation-faqs-V13)
- [InsightIntentUIExtensionAbility — Intents Kit ArkTS API](https://developer.huawei.com/consumer/en/doc/harmonyos-references-V14/intents-arkts-api-insightintent-uiextension-V14)
- [Intents Kit 集成方案（习惯推荐接入计划）](https://developer.huawei.com/consumer/en/doc/harmonyos-guides-V14/intents-habit-rec-access-programme-V14)
- [开发者资质要求说明](https://developer.huawei.com/consumer/es/doc/HMSCore-Guides/application-qualification-description-0000001425636570)
- [HiAI Foundation Kit 示例代码（Gitee）](https://gitee.com/harmonyos_samples/hiaifoundationkit-samplecode-clientdemo-cpp)

### 官方内容镜像 / 社区
- [HiAI Foundation Kit（HiAI Foundation 服务）— RZer（官方文档镜像）](https://nanhubrain.csdn.net/6a0176e70a2f6a37c5a92bf5.html)
- [【鸿蒙开发】第四十五章 HiAI Foundation Kit（官方文档镜像，含完整模型转换与部署流程）](https://harmonyosdev.csdn.net/689c3b9d080e555a88d8779c.html)
- [HiAI Foundation Kit 简介（CSDN）](https://rzone999.blog.csdn.net/article/details/146157492)
- [HarmonyOS Next 端侧部署基础之 HiAI Foundation Kit](https://blog.csdn.net/same4869/article/details/144363746)

### 开发者论坛（存在性引用，正文未读取）
- [鸿蒙手机支持 llamacpp 的 cann 来运行 gguf 模型吗？](https://developer.huawei.com/consumer/cn/forum/topic/0203211574958614735?fid=0109140870620153026)
- [手机端本地模型咨询](https://developer.huawei.com/consumer/cn/forum/topic/0204225565780311279?fid=0109140870620153026)
- [开发 app 调用平板本地大模型，怎么解决本地大模型配置白名单问题](https://developer.huawei.com/consumer/cn/forum/topic/0201209053123903162?fid=0109140870620153026)
- [鸿蒙安全模型下，应用沙箱、签名校验、强制访问控制对 NPU 推理、模型动态加载…设限](https://developer.huawei.com/consumer/cn/forum/topic/0204224519423918015?fid=0109140870620153026)
- [FunctionComponent 拉起小艺智能体：isAgentSupport=true，launch 返回 202，但对话框不弹出](https://developer.huawei.com/consumer.cn/consumer/cn/forum/topic/0202218833129112036?fid=0109140870620153026)
- [现在需要接入意图框架的话是必须要有已经上架的应用吗？](https://developer.huawei.com/consumer/cn/forum/topic/0204208432333082157?fid=0109140870620153026)
- [应用不上架是否可以使用意图框架](https://developer.huawei.com/consumer/cn/forum/topic/0201194546406578272?fid=0109140870620153026)

### 本地 SDK（一手证据，非网络来源）
`D:\develop\DevEco Studio\sdk\default`，HarmonyOS 26.0.0.105 / API 26：
`hms/ets/kits/@kit.AgentFrameworkKit.d.ts`、`@kit.IntentsKit.d.ts`、`@kit.DataAugmentationKit.d.ts`、`@kit.CoreVisionKit.d.ts`、`@kit.NaturalLanguageKit.d.ts`、`@kit.VisionKit.d.ts`、`@kit.SpeechKit.d.ts`；
`hms/ets/api/@hms.ai.AgentFramework.d.ets`、`@hms.ai.A2A.d.ts`、`@hms.ai.insightIntent.d.ts`、`@hms.data.localChatModel.d.ts`、`@hms.data.rag.d.ts`、`@hms.data.knowledgeProcessor.d.ts`；
`hms/ets/api/device-define/{phone-hmos.json, 2in1-hmos.json, api-white-list.json}`、`device-define/api-version/{CANNKit.json, AgentFrameworkKit.json, DataAugmentationKit.json, IntentsKit.json, MindSporeLiteKit.json}`；
`hms/native/sysroot/usr/include/CANNKit/{llm_engine.h, hiai_options.h, hiai_tensor.h, hiai_helper.h, hiai_aipp_param.h, hiai_single_op.h}`、`ndk_system_capability.json`、`nativeapi_syscap_config.json`；
`openharmony/ets/kits/@kit.MindSporeLiteKit.d.ts`、`openharmony/ets/api/{@ohos.ai.mindSporeLite.d.ts, @ohos.app.agent.*, @ohos.bundle.skillManager.d.ts, @ohos.app.ability.InsightIntent*.d.ts, application/AgentCard.d.ts}`；
`openharmony/native/sysroot/usr/include/{mindspore/*, neural_network_runtime/*}`。
