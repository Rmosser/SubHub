// 详情抽屉的 Esc 让路规则（纯函数，单测覆盖）：
// 只有真正展开着的弹出层先收自己——展开的组合框、展开的弹出按钮、列表框、菜单；
// 普通的展开/收起按钮（如 ReasonText 的「展开」）不算，焦点在它上面按 Esc 照常关闭抽屉。
export interface AttributeNode {
  getAttribute(name: string): string | null;
  parentElement: AttributeNode | null;
}

function isOpenPopup(node: AttributeNode): boolean {
  const role = node.getAttribute("role");
  if (role === "listbox" || role === "menu") return true;
  if (node.getAttribute("aria-expanded") !== "true") return false;
  if (role === "combobox") return true;
  const popup = node.getAttribute("aria-haspopup");
  return popup !== null && popup !== "false";
}

// 从事件目标向上找到抽屉本身为止；抽屉外（如挂到 body 的下拉）也照样向上找完
export function escapeBelongsToPopup(target: AttributeNode | null, boundary?: AttributeNode | null): boolean {
  for (let node = target; node && node !== boundary; node = node.parentElement) {
    if (isOpenPopup(node)) return true;
  }
  return false;
}
