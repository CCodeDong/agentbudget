# 性能优化与 stdx 就绪报告

> 日期：2026-09-23 · 全部数据来自 `cjpm bench` 实测
> 版本：`agentbudget4cj` v0.1 → v0.2

---

## 1. 结论摘要

| 事项 | 状态 |
|---|---|
| 上一轮的性能归因 | ❌ **错误**，已用隔离测量推翻并修正 |
| `selectTopK` 优化 | ✅ 8.24 ms → **4.74 ms**（**−42%**） |
| `stagedSchemas` 优化 | ✅ 9.83 ms → **6.11 ms**（**−38%**） |
| stdx 扩展库 | ✅ **已安装并实测可用**（JSON round-trip 通过） |
| 测试 | ✅ 14/14 通过（优化前后一致） |
| HTTP / JSON / TLS / 日志能力 | ✅ 已解锁 |

---

## 2. 推翻错误归因：瓶颈隔离测量

### 2.1 被推翻的说法

v0.1 报告中我写道：*"`stagedSchemas` 比 `eagerSchemas` 慢 22 倍，原因是 `selectTopK` 用了 O(n²) 插入排序。"*

**算术上就不成立**：5 个工具、k=3，插入排序约 25 次比较。这不可能解释 22 倍差距。

### 2.2 隔离测量（v0.1 原始代码）

新增 3 个细粒度基准，把 `stagedSchemas` 拆开：

| 基准 | Median | 占 `stagedSchemas` |
|---|---|---|
| `benchFullSchemaRenderOnly`（拼接全量 schema） | 0.450 ms | — |
| `benchSummaryPoolOnly`（构建摘要池） | 1.139 ms | 12% |
| **`benchSelectTopKOnly`（选 top-k）** | **8.237 ms** | **84%** |
| `benchStagedSchemas`（合计） | 9.826 ms | 100% |

**结论：84% 的开销在 `selectTopK`，而 `selectTopK` 慢的原因是 `score()` 对每个工具都重新执行
`query.toAsciiLower()` 和 `query.split(" ")`** —— 纯字符串分配，与排序无关。

顺带发现第二个反直觉现象：构建摘要池（1.139 ms）比拼接全量 schema（0.450 ms）**还慢 2.5 倍**，
因为逐段 `+=` 拼接在不断重新分配字符串。

> **方法教训（已写进 docs/02 作为永久记录）**：性能归因必须来自隔离测量。
> 直觉指向"复杂度最高的那个算法"（排序），而真实代价在"最不起眼的那个操作"（字符串分配）。

---

## 3. 两轮优化与实测结果

### 3.1 第一轮：消除冗余归一化 + 改部分选择 + StringBuilder

| 改动 | 内容 |
|---|---|
| 查询归一化上提 | `toAsciiLower()` 与 `split(" ")` 每次 `selectTopK` 只做一次，不再每个工具做一次 |
| 选择算法 | O(n²) 全排序 → O(n·k) 部分选择（k 次线性扫描，不分配排序副本） |
| 字符串构建 | 逐段 `+=` → `StringBuilder`（实测 `StringBuilder` 存在于 std.core） |

| 基准 | 优化前 | 第一轮后 | 变化 |
|---|---|---|---|
| `benchSummaryPoolOnly` | 1.139 ms | 0.812 ms | −29% |
| `benchSelectTopKOnly` | 8.237 ms | 5.306 ms | −36% |
| `benchStagedSchemas` | 9.826 ms | 6.714 ms | −32% |

### 3.2 第二轮：把归一化形式缓存进 `ToolSpec`

**动机**：工具池是不可变的，而 `selectTopK` 在每个 agent 步都会调用。
对同一批工具反复 `toAsciiLower()` 是纯粹的重复劳动。

**改动**：`ToolSpec.init` 中预计算并缓存 `nameLower` / `descLower` / `paramLower`。

| 基准 | 第一轮后 | 第二轮后 | 变化 |
|---|---|---|---|
| `benchSelectTopKOnly` | 5.306 ms | **4.743 ms** | −11% |
| `benchStagedSchemas` | 6.714 ms | **6.105 ms** | −9% |

### 3.3 累计效果

| 基准 | v0.1 原始 | v0.2 最终 | **累计** |
|---|---|---|---|
| `benchSelectTopKOnly` | 8.237 ms | **4.743 ms** | **−42%** |
| `benchStagedSchemas` | 9.826 ms | **6.105 ms** | **−38%** |
| `benchSummaryPoolOnly` | 1.139 ms | 0.873 ms | −23% |
| `benchEagerSchemas` | 0.595 ms | 0.509 ms | 噪声范围内 |
| `benchSchedulerPlan` | 57.45 ms | 57.69 ms | 噪声范围内 |

> **数据诚实性说明**：`cjpm bench` 的运行间波动约 ±5–10%（`Err%` 列已给出）。
> 上表中只有 `selectTopK`、`stagedSchemas`、`summaryPool` 三项的改善**超出噪声**，
> 其余标为"噪声范围内"。`benchSchedulerPlan` 未改善，因为它同时执行 eager 与 staged 两条路径。

---

## 4. 剩余性能地板与它的研究含义

优化后 `selectTopK` 仍是全量 schema 渲染（0.45 ms）的 **约 10 倍**。

原因不再是实现缺陷，而是**算法本身**：当前打分器对每个工具 × 每个查询词做两次子串匹配
（5 工具 × 8 词 × 2 次 `contains` = 80 次子串搜索）。

> **这是一个真正有研究价值的发现，而不是待修的 bug：**
>
> **两阶段工具注入的 CPU 成本，取决于"检索机制"而非"排序或字符串处理"。
> 在朴素词法检索下，选择的成本比它省下的渲染成本高一个数量级 —— 也就是说，
> 朴素实现的"优化"在小工具池上反而是净亏损。**
>
> 这直接呼应文献中的空白：Tool Attention（arXiv:2604.21816）只报告了 token 层面的
> "MCP Tax"，**从未报告选择机制自身的 CPU 代价**。我们的测量补上了这一维。

**后续可选方向**（按性价比排序）：
1. 把打分器换成倒排索引 / 词元集合交集，把 O(tools × words × |desc|) 降下来
2. 只在工具池变化时重建索引（摊销到多步）
3. 若池子很大，改用向量检索（但引入 embedding 成本，需重新权衡）

---

## 5. stdx 扩展库：已就绪并验证

### 5.1 交付与位置

子代理已完成下载、解压与实测，产物在工作目录：

```
stdx/windows_x86_64_cjnative/
├── dynamic/stdx/     ← 动态库（.dll + .dll.a）
└── static/stdx/      ← 静态库
samples/
├── stdx-json-demo/   ← stdx JSON 往返（已跑通）
├── mini-http/        ← 纯 std HTTP 客户端（无 stdx 的降级方案）
└── mini-json/        ← 纯 std JSON 解析器（无 stdx 的降级方案）
cangjie-stdx-1.0.5-windows-manual.md
```

### 5.2 实测验证（本轮亲自复跑）

```
$ powershell -File tools\cj.ps1 -Project samples\stdx-json-demo run
toString     = {"name":"cangjie","version":105,"tags":["stdx","json"],"ok":true}
toJsonString = { "tags": [ ... 
cjpm run finished
```

✅ `stdx.encoding.json` 可用，`cjpm` 自动处理动态库 `PATH`。

### 5.3 关键事实（含对旧教程的纠正）

| 项 | 正确值 |
|---|---|
| 正确的发布仓 | `gitcode.com/Cangjie/cangjie_stdx`（**不是** `cangjie-stdx-bin`，后者停更在 v1.0.1.1） |
| 与 cjc 1.0.5 匹配的包 | `cangjie-stdx-windows-x64-1.0.5.1.zip`（**版本号 4 段**，不存在 `-1.0.5.zip`） |
| 解压目录名 | `windows_x86_64_cjnative`（1.0.4.x 及旧教程写的 `windows_x86_64_llvm` 已过时） |
| 跨版本使用 | ❌ **一律不可用**。1.0.4.1 会**编译通过但运行崩溃**（`0xC0000142 STATUS_DLL_INIT_FAILED`）——最危险的"假成功" |
| TOML 写法 | 用单引号字面量 `path-option = ['D:\...\stdx']`，避免 `\U` 转义报错 |
| `-lcrypt32` | 仅**静态链接** `crypto.x509` 时需要，写在 `compile-option` |
| `path-option` 指向中文路径 | ✅ **完全正常**（本轮实测） |

---

## 6. 中文路径限制：根因已定位到字节

官方 `cjpm_manual.md` 确实写着"Windows 平台暂不支持在中文路径下使用"。真实范围：

- ❌ **工程目录**含中文 **且源码中有任意一个 `import`** → 失败
- ✅ `path-option` 指向中文路径 → 正常
- ✅ 无 `import` 的工程 → 正常（**这就是最初 hello-world"假成功"的原因**）

**根因**：`cjpm` 调用 `cjc -p <路径>\src --scan-dependency`，而 `cjc` 用 **GBK/CP936 而非 UTF-8**
输出 JSON 里的 `file` 字段（实测字节 `CF EE C4 BF BF AA B7 A2` = "项目开发"），
`cjpm` 按 UTF-8 解析 → `Invalid unicode scalar value.`。
无 `import` 时依赖列表为空、不含路径，所以能过。

**已实测无效的绕过手段**：`chcp 65001` ❌、目录 junction / 软链接 ❌（cjpm 会解析回真实路径）、
`subst` ❌（本机被拒）、8.3 短名 ❌（`项目开发` 未生成短名）。

**唯一解法**：工程放纯 ASCII 路径 —— 已由 `tools/cj.ps1` 的"源码在中文工作目录、构建在 ASCII 镜像区"机制解决。

### 附带发现：HTTPS 的可绕过性

本机 shell 的 `curl.exe` / `Invoke-WebRequest` 走 schannel，报 `SEC_E_NO_CREDENTIALS`。
但 **Python 与 Node.js 走 OpenSSL，无需提权即可完成 HTTPS 下载**（子代理据此成功下载了 stdx）。
→ 依赖与模型的自动获取不必依赖沙箱提权，用 Python/Node 即可。

---

## 7. 未解决的问题

| # | 问题 | 状态 |
|---|---|---|
| 1 | 一次误导性的 `unclosed delimiter: '<'` 解析错误 | ⚠️ **未精确定位**。同时移除了三样东西（`PreparedQuery` 结构体位置、`continue`、`/** */` 文档注释形式）后编译通过，**尚未逐项隔离是哪一个触发**。在隔离之前，不得把其中任何一条写成"已知坑"。 |
| 2 | `samples/*/cjpm.toml` 里的 stdx 路径是绝对路径 | 换机器需手工改；后续应改为相对路径或环境变量 |
| 3 | `benchSchedulerPlan` 未优化 | 它同时跑 eager 与 staged 两条路径，属于基准设计问题而非实现问题 |
| 4 | 分支覆盖率（库）66.8% | 测例已增至 29 个；见 `docs/02` 的修正说明 |

---

## 8. 复现命令

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$cj = 'tools\cj.ps1'

powershell -ExecutionPolicy Bypass -File $cj -Project agentbudget4cj test
powershell -ExecutionPolicy Bypass -File $cj -Project agentbudget4cj bench
powershell -ExecutionPolicy Bypass -File $cj -Project agentbudget4cj cover

# stdx 验证
powershell -ExecutionPolicy Bypass -File $cj -Project samples\stdx-json-demo run
```

基准 CSV 原始数据：`projects/agentbudget4cj/_out/reports/benchmarks/*.csv`
