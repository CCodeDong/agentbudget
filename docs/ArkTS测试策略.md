# ArkTS 相关代码该怎么测试

> 本文回答一个问题：**纯算法写完了，怎么证明它在鸿蒙上也能跑？**
>
> 结论：**分四层测，其中前两层已经实测通过。**

---

## 一、四层验证策略

| 层 | 测什么 | 怎么测 | 状态 |
|---|---|---|---|
| **L1** | 算法正确性 | Node 单测 | ✅ **87 个测试全过** |
| **L2** | **语法/类型子集兼容** | 放进 DevEco 工程 → `hvigorw assembleHap` | ✅ **已实测通过** |
| **L3** | **运行时行为一致** | 应用内自测页，结果显示在屏幕上 | 🟡 代码已就绪，待设备 |
| **L4** | 真实 OCR / 性能 | 真机或云真机 | ❌ 需要设备 |

**关键认知：L2 不需要设备、不需要运行，只要编译通过就证明了兼容性。** 这是最便宜也最决定性的一步。

---

## 二、L1：Node 单测（已完成）

```powershell
python tools\olib.py test
```

**87 个测试，全部通过。** 这一步证明算法本身是对的。

**但它证明不了两件事**：
- 这些 `.ts` 能不能被 ArkTS 编译
- 在设备的 ArkTS 运行时里行为是否一致

所以要往下走。

---

## 三、L2：编译验证（**已实测通过**）

### 怎么做的

1. 复制现有鸿蒙工程 → `app/offlinelib/`
2. 改 `bundleName` → `com.xjtu.offlinelib`
3. 把 `projects/offlinelib-core/src/*.ts` 复制进 `entry/src/main/ets/lib/`
4. 写一个自测页 `entry/src/main/ets/selfcheck/SelfCheck.ets`
5. 跑 `hvigorw assembleHap`

### 实测结果

```
CompileArkTS   ✅ 通过
PackageHap     ✅ 通过
SignHap        ❌ 失败（仅因改过包名，与代码无关）

产物：entry-default-unsigned.hap  231,331 B
```

**`CompileArkTS` 通过 = 我们的 `.ts` 与 `.ets` 全部被 ArkTS 编译器接受。**

`SignHap` 失败的原因与代码无关：签名配置里绑的是旧包名 `com.xjtu.agentbudget`，
而我们改成了 `com.xjtu.offlinelib`。要用新包名上架，需要去 AGC 申请新 Profile。

### 这条验证的价值

老师批评"OCR 与全文检索技术路线**无法核实**"。

现在可以回答：

> **核心检索模块 1,417 行 TypeScript，87 个单测在 Node 下全过，
> 且已被 ArkTS 编译器接受（`CompileArkTS` 通过），产物 HAP 231 KB。**

**这比"我们计划实现"强得多。**

---

## 四、L2 过程中踩到的 ArkTS 约束（实测清单）

**第一次编译失败，8 个错误全部出在我写的 `.ets` 胶水代码里，核心 `.ts` 一条错误都没有。**

这本身是个重要结论：**纯算法只要避开少数构造，就能直接进 ArkTS。**

### 实测踩到的三条硬约束

| 错误码 | 含义 | 我踩到的具体情形 |
|---|---|---|
| `arkts-no-untyped-obj-literals` | **对象字面量必须有上下文类型** | `results.push({ name, passed, detail })` —— 必须先声明 `const r: CheckResult = {...}` 再 push |
| `arkts-no-noninferrable-arr-literals` | **数组字面量元素类型必须可推断** | `const cands = [{...}, {...}, {...}]` —— 必须先逐个声明为 `Candidate`，再放进 `Candidate[]` |
| `arkts-no-any-unknown` | **禁止 any / unknown** | 我用了 `doc('a','x') as unknown as Chunk` 做双重断言，被拒 |

### 另外两条已知约束（之前就避开了）

| 约束 | 避开方式 |
|---|---|
| 不给索引签名类型赋对象字面量 | 全部用 `Map` 而不是 `Record<string, X>` |
| 不静态导入 HMS Kit | OCR 做成接口，真实实现由上层注入 |

### 还有一个不是 ArkTS 的问题

`OcrResult` / `OcrVerdict` 定义在 `ocr.ts` 而不是 `types.ts`，
我从 `types.ts` 导入它们时报"没有导出该成员"。

**这不是 ArkTS 的限制，是我导入路径写错了。** 已改为从 `ocr.ts` 导入。

> 这条值得记：**报错信息说"模块没有导出成员"时，先检查导入来源，别急着怀疑编译器。**

---

## 五、L3：设备内自测（代码已就绪）

### 设计

`app/offlinelib/entry/src/main/ets/pages/Index.ets` 是一个**自测页面**：

- 应用启动即跑 14 个关键断言
- 结果逐条显示在屏幕上（✓/✗ + 失败原因）
- 顶部显示"全部通过：14 / 14"

### 为什么用"屏幕上看结果"而不是日志

| 方式 | 给谁看 |
|---|---|
| `hilog` 日志 | 只有开发者会去翻 |
| **屏幕上的 ✓/✗** | **任何人都能截图，不用装环境、不用读代码** |

**这直接对应"可核实"三个字。**

### 现在卡在哪

需要设备在线才能安装运行。当前 `hdc list targets` 返回 `[Empty]`——**模拟器已关闭**。

**恢复步骤**：
1. 在 DevEco 里启动 Pura 90 Pro 模拟器
2. 由于改了包名，需要新的签名 Profile（或用旧包名跑一次验证）

---

## 六、L4：真机测试（暂不可行）

| 需要验证 | 为什么必须真机 |
|---|---|
| Vision Kit OCR 的真实识别率 | 模拟器不含 HMS Core，OCR 根本调不起来 |
| 端侧检索（`DataAugmentation.Retrieval`） | 同上 |
| 建索引在真实资料量下的耗时 | 模拟器性能与真机差异大 |
| 电量 / 发热 | 模拟器没有这个概念 |

**当前障碍**：没有鸿蒙手机。

**可选路径**：
1. 借一台（最快）
2. AGC 云调试（免费 360 分钟/天，需上传 release 签名包）
3. 买二手（保底）

---

## 七、当前状态小结

| 层 | 状态 | 证据 |
|---|---|---|
| L1 Node 单测 | ✅ | 87 个测试通过，`python tools/olib.py test` 可复现 |
| **L2 ArkTS 编译** | ✅ | **`CompileArkTS` 通过，HAP 231,331 B** |
| L3 设备自测 | 🟡 代码就绪 | 自测页已写好，等设备在线 |
| L4 真机 | ❌ | 无设备 |

**这意味着：老师说的"技术路线无法核实"，在 L1 + L2 这两层已经不再是问题。**
剩下的是"在真实设备上效果如何"——那是 L3/L4 的事，且需要设备。

---

## 八、一个副产物：新工程 `app/offlinelib/`

为了做 L2 验证，我建了一个真正的鸿蒙工程：

```
app/offlinelib/
├── AppScope/            bundleName = com.xjtu.offlinelib
├── entry/src/main/ets/
│   ├── lib/             7 个 .ts（从 offlinelib-core 复制）
│   ├── selfcheck/       SelfCheck.ets（14 个断言）
│   ├── entryability/    EntryAbility.ets
│   └── pages/           Index.ets（自测结果页）
└── build-profile.json5
```

**这就是"离线资料库"应用的骨架**——不是验证用完就扔的临时工程。

后续只需：
1. 申请 `com.xjtu.offlinelib` 的签名 Profile
2. 把 UI 从"自测页"换成真正的资料库界面
3. 接入 OCR（先探测能力是否存在）
