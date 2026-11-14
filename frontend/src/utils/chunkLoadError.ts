// 部署会删掉旧版本的懒加载分包：还开着旧页面时进入一个没加载过的工作区，动态 import 会失败。
// React.lazy 会缓存这次失败，只清掉错误状态会原样再报一次，得整页重载拿到新的外壳。
// Chrome / Firefox / Safari 的报错文字不同，Vite 预加载 CSS 失败时也走这里。
const CHUNK_LOAD_ERROR = /dynamically imported module|Importing a module script failed|Unable to preload CSS/i;

export function isChunkLoadError(error: unknown): boolean {
  return error instanceof Error && CHUNK_LOAD_ERROR.test(error.message);
}
