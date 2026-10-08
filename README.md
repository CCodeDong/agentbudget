# 端侧多智能体预算调度 —— 课程项目 1.0

> **一份代码，两门课，一篇论文雏形。**
> 仓颉语言课程与移动应用开发课程的最终项目，收敛到同一个研究点。

| 项 | 内容 |
|---|---|
| 版本 | **1.0** |
| 日期 | 2026-09 |
| 研究点 | 端侧多智能体系统中，工具上下文 / 消息表示 / 执行放置三个维度的联合调度 |
| 核心主张 | **每个调度维度需要它自己的信号**——工具注入的正确信号是检索置信度，不是 token 预算 |
| 论文 | [paper/01-论文初稿.md](paper/01-论文初稿.md)（含 6 组实验、9 张图表、18 条已核实文献） |

---

## 1. 一句话说明

移动端的上下文窗口只有 4k–8k，而多智能体系统的 token 消耗约为普通对话的 15 倍。
本项目实现一个**预算感知的联合调度器**，在每一步决定三件事：

1. **注入哪些工具的完整 schema**（两阶段注入：常驻摘要池 + top-$k$ 全量 schema）
2. **智能体间消息采用什么表示**（自然语言 / 截断摘要 / 结构化）
3. **该步在设备本地、局域网边缘节点还是云端执行**

仓颉侧是**被测量对象**（调度决策库），鸿蒙侧是**承载与演示**（真实 A2A 编排）。

---

## 2. 两门课的产出

### 仓颉语言课程

| 交付物 | 位置 | 状态 |
|---|---|---|
| 调度器库 | `projects/agentbudget4cj/` | ✅ **29 个单元测试通过** |
| 覆盖率 | `projects/agentbudget4cj/_out/coverage_html/` | ✅ 库行覆盖 **88.6%** / 分支 **66.8%** |
| 可执行文件 | `projects/agentbudget4cj/bin/agentbudget4cj.exe` | ✅ 11.75 MB |
| 课程设计报告 | `deliverables/仓颉语言/课程设计报告.docx` | ✅ |
| 答辩 PPT | `deliverables/仓颉语言/答辩.pptx` | ✅ 18 张 |
| 演示实录 | `deliverables/演示素材/仓颉演示实录.md` | ✅ 脚本实际执行捕获，5 段 |

### 移动应用开发课程

| 交付物 | 位置 | 状态 |
|---|---|---|
| HarmonyOS 应用 | `app/harmony/` | ✅ 10 个 ArkTS 模块 |
| 安装包 | `app/harmony/_out/entry-default-unsigned.hap` | ✅ 221,866 B，`BUILD SUCCESSFUL` |
| 真实 A2A 集成 | `app/harmony/entry/src/main/ets/agents/A2AAgentServer.ets` | ✅ `@hms.ai.A2A` 服务端 |
| 课程设计报告 | `deliverables/移动应用开发/课程设计报告.docx` | ✅ |
| 答辩 PPT | `deliverables/移动应用开发/答辩.pptx` | ✅ 16 张 |
| 演示素材 | `deliverables/演示素材/移动端预期界面状态清单.md` | ⏳ 待真机录制 |

### 共用

| 交付物 | 位置 |
|---|---|
| 环境搭建与运行说明 | `deliverables/环境搭建与运行说明.docx` |
| 交付物索引 | `deliverables/README.md` |

---

## 3. 目录结构

```
.
├── projects/agentbudget4cj/     仓颉调度器库（被测量对象）
│   ├── src/                     budget / codec / router / scheduler / tool / main
│   ├── bin/agentbudget4cj.exe   已发布可执行文件（11.75 MB）
│   └── _out/                    覆盖率 HTML、基准 CSV
├── app/harmony/                 HarmonyOS 应用（承载与演示）
│   └── entry/src/main/ets/
│       ├── agents/              ToolRegistry / AgentRuntime / A2AAgentServer
│       ├── core/                Tokens / MessageCodec / BudgetPolicy / NetworkProbe
│       └── pages/Index.ets      编排控制台界面
├── experiments/                 实验框架与全部原始数据
│   ├── experiment.py            主实验驱动
│   ├── mock_llm_server.py       模拟推理端点
│   ├── a2a_overhead.py          A2A 信封开销（schema 级估算）
│   ├── MANIFEST.json            环境、套件参数、产物哈希
│   └── results*/                11 个套件，3960 次运行
├── paper/
│   ├── 01-论文初稿.md           论文全文（72.9 KB）
│   ├── 02-参考文献.md           18 条，含核实状态与三次自我纠错记录
│   └── figures/                 9 张图（PNG 300dpi + 矢量 PDF）
├── docs/                        15 份设计记录 00–15
├── tools/                       构建与自检工具（11 个）
└── deliverables/                两门课的正式交付文件
```

---

## 4. 快速开始

### 4.1 仓颉库（不需要真机、不需要模型）

```powershell
# 构建并发布可执行文件
powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project agentbudget4cj bin

# 跑测试
powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project agentbudget4cj test

# 覆盖率（含分支）
powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project agentbudget4cj cover
python tools\cov_report.py

# 演示（实际执行并捕获实录）
python tools\demo_run.py --show
```

> **注意**：工程目录**不得含非 ASCII 字符**——`cjpm` 调用 `cjc` 时后者以 GBK 输出路径、
> `cjpm` 按 UTF-8 解析会失败。`tools/cj.ps1` 通过 ASCII 临时镜像解决这一点，
> 所以**必须经该脚本构建**，不要直接调 `cjpm`。

### 4.2 完整实验复现

```powershell
# 校验套件声明与磁盘结果是否一致（不运行）
python tools\reproduce.py --check

# 重跑全部可复现套件并重建图表（自动启停模拟端点）
python tools\reproduce.py --run --all

# 写出环境与产物清单
python tools\reproduce.py --manifest
```

### 4.3 鸿蒙应用

```powershell
# 构建 HAP（同样经 ASCII 镜像）
powershell -ExecutionPolicy Bypass -File tools\hb.ps1 assembleHap

# 应用逻辑与仓颉库的一致性验证（不需真机）
python tools\verify_app_logic.py
```

---

## 5. 自检工具（四项，全部绿灯）

本项目的一条核心工程原则：**每个数字要么由脚本生成，要么由脚本校验**。
起因是过程中连续出错三次，而三次都不是"编造数字"，而是**数字真实存在却被错误地归给了另一个东西**。

| 工具 | 作用 | 当前结果 |
|---|---|---|
| `tools/reproduce.py --check` | 套件声明 vs 磁盘结果，抓**命令漂移** | 11 个套件一致 |
| `tools/check_paper.py` | 论文交叉引用 + 图表引用 + 字体字形 + 附录与图标题一致 | OK |
| `tools/verify_app_logic.py` | 应用 ↔ 仓颉库**全任务集差分**（30 条查询） | 30/30 一致 |
| `tools/cov_report.py` | 机械解析 cjcov 报告（不靠人读表） | 库 88.6% / 66.8% |

### 为什么需要这些工具

三次真实错误，都不是靠重读发现的：

| # | 错误 | 靠什么发现 |
|---|---|---|
| 1 | **§6.1 跨实现比较**——5 工具池数据来自检索修复前、15 工具来自修复后，"代价随池规模出现"的结论不成立 | `reproduce.py --check` 报出命令与数据不一致 → 重跑 → 逐行比对 |
| 2 | **覆盖率三个数字全错**——89.6% 是单文件行覆盖，63.0% 是另一个单文件的行覆盖被当成分支覆盖 | 读 `cjcov --help` 发现 `--branches` 未被传入 |
| 3 | **图 2/3 重绘后附录描述未更新** | `check_paper.py` 新增的图表标题一致性检查 |

---

## 6. 关键研究结果

| 结论 | 依据 | 图 |
|---|---|---|
| **token 节省随工具池规模增长，准确率代价不随之增长** | 5 工具省 31.8%、15 工具省 67.2%，两边都是 30 任务中损失 1 个 | 图 2 |
| **代价 100% 来自检索漏选** | 漏选→成功率 0.000，入选→1.000，整条 $k$ 扫描上逐点相等 | 图 5 |
| **存在免费压缩区间** | $k \ge 5$ 时用 −55.5% 上下文换取零准确率损失 | 图 1 |
| **截断式摘要的"省"与"完整"互斥** | 预算 ≤60 字符更便宜但验证器拿不到参数；≥80 字符恢复完整但成本追平结构化编码 | 图 3、图 7 |
| **三层放置提供独立收益** | 弱网下保住 30/30 边缘执行；云调用 −80% | 图 4 |
| **token 预算不是选择 $k$ 的正确信号**（负面结果） | 预算驱动的自适应策略**每一个工作点都被某个固定 $k$ 严格支配** | 图 8 |
| **检索得分分布是正确信号**（正解） | 得分驱动策略**支配每一个固定 $k$ 且自身不被支配**，成功率 1.000 下削减 −72.6% | 图 9 |

---

## 7. 诚实的边界

**这些不是"未来工作"的客套话，是真实存在的限制。**

| 限制 | 说明 |
|---|---|
| **所有数值来自模拟端点** | 论文 §7.1 自述为最大效度威胁。转换为最终结论需要真实推理端点 |
| **规模小于对标工作** | Tscg 是 6,566 次调用 / 14 个模型；本文 3,960 次 / 单一模拟端点 |
| **token 估算器未与真实分词器标定** | 用的是启发式 `ascii/4 + wide/3`；两套内部估算器在 ASCII 负载上恰好一致（已实测），但绝对标定未验证 |
| **验证器是规则化的** | 检查工具名与参数名存在，**不等于任务被真正解决**；成功率应理解为"正确工具被以结构完整的参数调用"的比例 |
| **移动端从未在设备上运行** | 只验证到"编译通过 + 与库逻辑一致" |
| **3 处引用细节未闭合** | LLMLingua 的会议出处、MCP 规范的稳定 URL、HMAF 2.0 的官方文档（**均不影响正文主张**） |

---

## 8. 环境

| 项 | 版本 |
|---|---|
| 仓颉 | 1.0.5 LTS（Windows x86_64） |
| stdx | 1.0.5.1（**必须与编译器版本严格对应**，跨版本会编译通过但运行崩溃） |
| DevEco Studio | 26.0.0.821 |
| HarmonyOS SDK | `default`（含 `@hms.ai.A2A`，since 26.0.0） |
| Python | 3.13（numpy / pandas / matplotlib / scipy / python-docx / python-pptx） |

详见 `deliverables/环境搭建与运行说明.docx`。

### 三条工具链限制（第一条已因改名而消失）

1. ~~**工程目录不得含非 ASCII 字符**~~ —— **已解决。**
   工作区原名 `...\项目开发`。`cjpm`（经 `cjc --scan-dependency`，以 GBK 输出路径）
   与 `hvigor`（ASCII 路径白名单，错误码 00306003）都在中文路径下失败，
   因此两个构建脚本原先都要把源码镜像到 ASCII 临时目录。
   **工作区已改名为 `...\Project`（纯 ASCII），镜像不再需要**：
   `cj.ps1` / `hb.ps1` 现在直接原地构建，仅当路径仍为非 ASCII 时才回退到镜像。
   附带收益：构建不再依赖会话 TEMP（TEMP 轮换曾多次清空镜像、导致必须重建），
   `hb.ps1` 的构建时间也从约 12 s 降到约 2 s。
2. **仓颉库无法交叉编译到 HarmonyOS** —— `cjc` 认识 `aarch64-linux-ohos` 目标，
   但 Windows 版 SDK 只提供 `windows_x86_64_cjnative` 标准库。
   因此应用侧是**移植实现**，用 `verify_app_logic.py` 的全任务集差分测试控制一致性
3. **hvigor 在本沙箱内仍需提权** —— 它在初始化时创建符号链接，沙箱拒绝。
   **这与路径无关，镜像也从未解决它。**

> 旧路径 `...\项目开发` 以**目录联接**保留，指向 `Project`，仅供会话解析。
> 两个构建脚本都会显式解析联接并使用真实的 ASCII 路径。

---

## 9. 平台事实（影响架构，已核实）

取自本地 SDK 的 `device-define/*-hmos.json`，**可复现**：

| 能力 | phone | tablet | 2in1 |
|---|---|---|---|
| `SystemCapability.AI.CANN.LLMEngine` | — | **—** | **有** |
| `SystemCapability.DataAugmentation.LocalChatModel` | — | **—** | **有** |
| `SystemCapability.AI.Agent.AgentKit` | **有** | **有** | — |
| `SystemCapability.DataAugmentation.Retrieval` | 有 | 有 | 有 |

**结论**：**手机与平板都不能自部署 LLM**，但都能跑 A2A 编排与端侧检索。
所以"端侧"在本项目中指**编排在设备**，推理在边缘或云端——
这不是设计偏好，是平台约束下的唯一选择。

---

## 10. 待办

| 项 | 阻塞 |
|---|---|
| 移动端演示录制 | 需真机（用户已具备设备，待接线与签名） |
| 全部数值的真实端点复验 | 需 API key 或本地 Ollama |
| 3 处引用细节 | 需补官方文档链接 |
| `main.cj`（CLI）覆盖为 0 | 单元测试不驱动命令行，由演示与实验实际执行 |

---

## 11. 复现所需的全部命令

```powershell
# --- 仓颉 ---
powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project agentbudget4cj bin
powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project agentbudget4cj test
powershell -ExecutionPolicy Bypass -File tools\cj.ps1 -Project agentbudget4cj cover
python tools\cov_report.py
python tools\demo_run.py --show

# --- 实验 ---
python tools\reproduce.py --check
python tools\reproduce.py --run --all
python tools\reproduce.py --manifest
python tools\make_figures.py

# --- 鸿蒙 ---
powershell -ExecutionPolicy Bypass -File tools\hb.ps1 assembleHap
python tools\verify_app_logic.py

# --- 交付物 ---
python tools\make_deliverables.py

# --- 论文自检 ---
python tools\check_paper.py
```
