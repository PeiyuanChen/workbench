// 文件夹树组树纯函数（#5）。
//
// 后端给的是扁平 [{path, name}]（path 如 "k8s/网络"），不持有树状态
// （ADR-0002：视图 ≠ 数据）。前端在视图层现组树，算法不依赖 DOM，便于阅读。

import type { NoteFolder } from "../types";

export interface FolderNode extends NoteFolder {
  /** 相对 notes/ 的目录深度（根层直接子目录为 1） */
  depth: number;
  children: FolderNode[];
}

/**
 * 扁平文件夹列表 → 树。入参乱序也可（内部按 path 排序，保证父先于子）。
 * 后端保证父目录一定伴随子目录出现（rglob 枚举真实目录），
 * 找不到父节点的孤儿段兜底挂到根，不丢数据。
 */
export function buildFolderTree(folders: NoteFolder[]): FolderNode[] {
  const roots: FolderNode[] = [];
  const byPath = new Map<string, FolderNode>();
  const sorted = [...folders].sort((a, b) => a.path.localeCompare(b.path));

  for (const f of sorted) {
    const segments = f.path.split("/");
    const node: FolderNode = { ...f, depth: segments.length, children: [] };
    byPath.set(f.path, node);
    if (segments.length === 1) {
      roots.push(node);
    } else {
      const parentPath = segments.slice(0, -1).join("/");
      const parent = byPath.get(parentPath);
      if (parent) parent.children.push(node);
      else roots.push(node); // 兜底：理论不可达
    }
  }
  return roots;
}

/** 判断 noteFolder 是否为 folder 的本层或深层子树（folder 为空串 = 根层散放，精确匹配） */
export function isInFolder(noteFolder: string, folder: string): boolean {
  if (folder === "") return noteFolder === "";
  return noteFolder === folder || noteFolder.startsWith(`${folder}/`);
}

/**
 * 文件夹重命名后同步选中态路径：path 正好是 oldPrefix 或落在其子树才替换前缀，
 * 其余路径原样返回（folder 为空串的场景由调用方先行排除）。
 */
export function replaceFolderPrefix(path: string, oldPrefix: string, newPrefix: string): string {
  if (path === oldPrefix) return newPrefix;
  if (path.startsWith(`${oldPrefix}/`)) {
    return `${newPrefix}${path.slice(oldPrefix.length)}`;
  }
  return path;
}
