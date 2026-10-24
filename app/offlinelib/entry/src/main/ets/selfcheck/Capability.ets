/**
 * 设备能力探测 —— 用 `canIUse` 查系统能力是否存在。
 *
 * WHY canIUse AND NOT A DIRECT IMPORT
 *   这个工程在早期版本里踩过一个真实的坑：
 *   应用静态 `import { createA2AServer } from '@hms.ai.A2A'`，
 *   而设备上没有对应的 HSP 时，ArkTS 运行时会在**模块加载期**直接 abort 整个进程——
 *   不是"功能不可用"，是"应用起不来"（崩溃日志里是 LoadJSPandaFile ... abort）。
 *
 *   所以探测能力必须用 `canIUse`：它是全局函数，**不需要 import 任何模块**，
 *   因此不存在把应用拖死的风险。
 *
 *   `canIUse` 返回 true 只说明"这个 syscap 被声明可用"，
 *   不代表 API 一定调得通；但返回 false 就**一定别去 import**。
 */

/** 一条能力探测结果。 */
export interface CapabilityProbe {
  /** 界面上显示的名字。 */
  label: string;
  /** syscap 全名。 */
  syscap: string;
  /** canIUse 的结果。 */
  available: boolean;
  /** 这个能力在本项目里用来做什么。 */
  purpose: string;
}

/**
 * 探测本项目关心的四项能力。
 *
 * 顺序刻意从"最需要"到"最不需要"：
 * OCR 是资料库入口，检索是核心，VisionBase 是 OCR 的底座，
 * AgentKit 只是拿来和当年崩溃的 A2A 做对照。
 */
export function probeCapabilities(): CapabilityProbe[] {
  const out: CapabilityProbe[] = [];

  const ocr: CapabilityProbe = {
    label: 'OCR 文字识别',
    syscap: 'SystemCapability.AI.OCR.TextRecognition',
    available: canIUse('SystemCapability.AI.OCR.TextRecognition'),
    purpose: '拍照导入：把图片转成可检索的文字'
  };
  out.push(ocr);

  const retrieval: CapabilityProbe = {
    label: '端侧检索',
    syscap: 'SystemCapability.DataAugmentation.Retrieval',
    available: canIUse('SystemCapability.DataAugmentation.Retrieval'),
    purpose: '系统级向量召回（本项目目前用自建 BM25，不依赖它）'
  };
  out.push(retrieval);

  const vision: CapabilityProbe = {
    label: '视觉基础能力',
    syscap: 'SystemCapability.AI.Vision.VisionBase',
    available: canIUse('SystemCapability.AI.Vision.VisionBase'),
    purpose: 'OCR 的底座，通常与 OCR 同时存在'
  };
  out.push(vision);

  const agent: CapabilityProbe = {
    label: 'AgentKit',
    syscap: 'SystemCapability.AI.Agent.AgentKit',
    available: canIUse('SystemCapability.AI.Agent.AgentKit'),
    purpose: '对照组：当年静态导入 A2A 导致加载期崩溃的那一族'
  };
  out.push(agent);

  return out;
}
