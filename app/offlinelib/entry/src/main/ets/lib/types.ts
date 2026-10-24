/**
 * 离线资料库 —— 核心数据结构（接口冻结）
 *
 * WHY THIS FILE EXISTS FIRST
 *   老师对开题的批评里有一条是"全文检索技术路线无法核实"。
 *   核实不了的原因不是想法不行，而是**没有任何可运行的证据**。
 *
 *   所以这个模块的设计原则是：**纯 TypeScript，零依赖，可在 Node 里单测**。
 *   它同时满足三件事：
 *     1. 能在 PC 上跑单测 → 检索路线立刻变成"可核实"
 *     2. 能直接编译进 ArkTS 应用（无 any / 无动态导入 / 无平台 API）
 *     3. 软著登记需要的是"体现软件功能逻辑的源代码"，这本身就是
 *
 *   ⚠️ 本文件**不导入任何 HarmonyOS Kit**。
 *      原因见 docs/11：HMS Kit 在缺少 HSP 的设备上会在**模块加载期**让整个应用崩溃。
 *      核心算法必须与平台解耦，才能既被单测、又不把应用拖死。
 */

/** 一份被导入的资料（一张照片、一个 PDF、一段文本）。 */
export interface DocItem {
  /** 稳定 id，入库后不变。 */
  id: string;
  /** 显示名（文件名或用户命名）。 */
  title: string;
  /** 来源类型。用于界面分组，也用于决定是否需要 OCR。 */
  source: DocSource;
  /** 原始内容的存储位置（URI 或沙箱内路径）。**不存内容本身**，避免重复占空间。 */
  uri: string;
  /** 入库时间（毫秒）。 */
  addedAt: number;
  /** 原文纯文本。OCR 之后填充；纯文本资料直接填充。 */
  text: string;
}

export type DocSource = 'camera' | 'album' | 'file' | 'note';

/**
 * 一个可检索的文本块。
 *
 * 为什么要分块：资料库的文档可能很长，检索需要定位到**具体片段**而不是整篇。
 * 分块策略直接影响召回质量，因此块大小是可调参数。
 */
export interface Chunk {
  /** 全局唯一：`${docId}#${seq}`。 */
  id: string;
  docId: string;
  /** 在原文中的序号。用于"前后文"与高亮定位。 */
  seq: number;
  /** 原文起点（字符偏移）。高亮回原图/原文时用。 */
  start: number;
  /** 原文终点（不含）。 */
  end: number;
  /** 块文本。 */
  text: string;
}

/**
 * 一条检索命中。
 *
 * 注意 `score` 与 `matched` 是两个不同的东西：
 *   score 是 BM25 相关度，用于排序；
 *   matched 是**具体命中了哪些词**，用于生成高亮与向用户解释"为什么给你这条"。
 */
export interface Hit {
  chunk: Chunk;
  /** BM25 得分。合并后的命中取被合并块中的**最高分**，不累加。 */
  score: number;
  /**
   * 命中的词项 → 该块中的出现次数。
   *
   * 用 `Map` 而不是 `Record<string, number>`：ArkTS 拒绝给索引签名类型赋对象字面量
   * （`arkts-no-untyped-obj-literals`），而 `Map` 在 TS 与 ArkTS 下行为一致。
   */
  matched: Map<string, number>;
  /** 高亮区间（相对 chunk.text 的字符偏移）。 */
  spans: Span[];
  /**
   * 这一条由几个原始块合并而成。未合并不设此字段（等价于 1）。
   *
   * 为什么需要暴露它：合并会改变"返回几条"的含义。
   * 界面上如果只说"找到 2 条"，用户不知道它原本是 5 个块，
   * 也就看不出合并起了多大作用。
   */
  mergedCount?: number;
}

/** 高亮区间，左闭右开。 */
export interface Span {
  start: number;
  end: number;
}

/** 检索选项。`topK` 由预算决策给出，不在这里写死。 */
export interface SearchOptions {
  /** 返回多少条。<=0 表示由得分分布自适应决定。 */
  topK: number;
  /** 最少返回几条（自适应时作为下界）。 */
  minK: number;
  /** 最多返回几条（自适应时作为上界）。 */
  maxK: number;
  /**
   * 是否把同一文档中**重叠或首尾相接**的命中块合并成一条。
   *
   * 默认关闭（不设即为不合并），这样既有的 87 个测试与评估基线不受影响。
   * 应用里打开它，因为对用户来说"同一段话被切成 3 条"是噪音。
   *
   * 合并发生在**选出 top-k 之后**：
   * 因此它会让最终显示条数变少，但不改变 k 的决策过程。
   * 这个顺序是刻意选的 —— 若在 k 之前合并，"按得分断层决定 k"的语义就变了。
   */
  mergeAdjacent?: boolean;
}

/** 检索结果，含决策依据，便于向用户解释。 */
export interface SearchResult {
  hits: Hit[];
  /** 实际使用的 k。 */
  k: number;
  /** k 是怎么定的：'fixed' | 'score-gap'。 */
  kSource: 'fixed' | 'score-gap';
  /** 用于决策的得分统计（自适应时为断层信息）。 */
  diagnostics: ScoreDiagnostics;
}

export interface ScoreDiagnostics {
  /** 命中的候选数（未截断前）。 */
  candidateCount: number;
  /** 最高分。 */
  topScore: number;
  /** 全部候选得分的均值和标准差。 */
  mean: number;
  std: number;
  /** 相邻得分之间的最大相对落差，以及它出现在第几位。 */
  maxGap: number;
  maxGapAt: number;
}

/** 预算决策的输入。字段都在手机上有真实含义，不是抽象参数。 */
export interface BudgetInput {
  /** 可用于检索的时间预算（毫秒）。 */
  latencyBudgetMs: number;
  /** 可用于本次检索的内存预算（KB）。 */
  memoryBudgetKb: number;
  /** 当前电量百分比（0-100）。低于阈值时降级。 */
  batteryPercent: number;
}

/** 预算决策的输出：这一次该取几条。 */
export interface BudgetDecision {
  k: number;
  /** 决策理由，直接显示给用户（"为什么只给你 3 条"）。 */
  reason: string;
}

/**
 * 持久化存档格式。
 *
 * 只存文档，不存倒排索引——理由见 `store.ts` 顶部的 DESIGN DECISION。
 * `version` 用于将来做格式迁移；目前只支持 1。
 */
export interface DocStoreSnapshot {
  version: number;
  docs: DocItem[];
}

