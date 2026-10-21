// 最小类型声明 —— 只为让 tsc 认识我们用到的少数 Node 全局与模块
//
// WHY NOT @types/node
//   npm install 需要联网，而当前环境连不上。
//   我们只用到少数几个 API，手写声明足够，
//   而且让这个工程**零依赖**——别人克隆下来不需要 npm install 就能编译。

declare module 'node:test' {
  export function test(name: string, fn: () => void | Promise<void>): void;
}

declare module 'node:assert/strict' {
  interface AssertStrict {
    ok(value: unknown, message?: string): void;
    equal(actual: unknown, expected: unknown, message?: string): void;
    notEqual(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    match(value: string, regexp: RegExp, message?: string): void;
    throws(fn: () => void, message?: string): void;
    fail(message?: string): never;
  }
  const assert: AssertStrict;
  export default assert;
}

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: string): string;
  export function readdirSync(path: string): string[];
  export function existsSync(path: string): boolean;
  export function statSync(path: string): {
    isDirectory(): boolean;
    isFile(): boolean;
    size: number;
  };
  export function mkdirSync(path: string, opts?: { recursive?: boolean }): void;
}

declare module 'node:path' {
  export function join(...parts: string[]): string;
  export function resolve(...parts: string[]): string;
  export function basename(p: string, ext?: string): string;
  export function dirname(p: string): string;
  export function extname(p: string): string;
  export function relative(from: string, to: string): string;
}

// 基准与评估脚本用到的全局
declare const console: {
  log(...args: unknown[]): void;
  error(...args: unknown[]): void;
  warn(...args: unknown[]): void;
};

declare const process: {
  hrtime: { bigint(): bigint };
  argv: string[];
  exitCode?: number;
};
