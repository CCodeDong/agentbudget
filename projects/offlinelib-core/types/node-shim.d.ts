// 最小类型声明 —— 只为让 tsc 认识 node:test / node:assert
//
// WHY NOT @types/node
//   npm install 需要联网，而当前环境连不上。
//   我们只用到少数几个断言函数与 test()，手写声明足够，
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
