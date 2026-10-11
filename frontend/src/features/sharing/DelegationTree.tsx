import type { ShareState, TreeNode } from "@/types/api";

import { Badge, Button } from "@/components/ui";

export const STATE_TONE: Record<ShareState, "green" | "slate" | "red" | "amber"> = {
  ACTIVE: "green",
  EXPIRED: "slate",
  REVOKED: "red",
  CONSUMED: "amber",
};

export const PERMISSION_TEXT = { VIEW: "View", EDIT: "Edit", SHARE: "Share" } as const;

interface Props {
  owner: string;
  nodes: TreeNode[];
  /** Called for active grants the viewer may try to revoke (the server decides). */
  onRevoke?: (node: TreeNode) => void;
}

function children(nodes: TreeNode[], parent: string | null) {
  return nodes.filter((n) => n.parent_share === parent);
}

function Branch({ nodes, parent, onRevoke, level }: { nodes: TreeNode[]; parent: string | null; onRevoke?: (n: TreeNode) => void; level: number }) {
  const items = children(nodes, parent);
  if (items.length === 0) return null;
  return (
    <ul role={level === 1 ? "tree" : "group"} aria-label={level === 1 ? "Delegation tree" : undefined} className={level > 1 ? "ml-6 border-l border-slate-200 pl-4" : ""}>
      {items.map((node) => (
        <li key={node.id} role="treeitem" aria-level={level} aria-expanded={children(nodes, node.id).length > 0 || undefined} className="py-1">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{node.grantee}</span>
            <span className="text-xs text-slate-500">{node.grantee_email}</span>
            <Badge tone="blue">{PERMISSION_TEXT[node.permission]}</Badge>
            {node.is_view_once && <Badge tone="amber">View once</Badge>}
            <Badge tone={STATE_TONE[node.state]}>{node.state.toLowerCase()}</Badge>
            <span className="text-xs text-slate-500">
              from {node.grantor} · until {new Date(node.expires_at).toLocaleString()}
            </span>
            {onRevoke && node.state === "ACTIVE" && (
              <Button variant="ghost" className="min-h-8 px-2 text-red-700" onClick={() => onRevoke(node)} aria-label={`Revoke access for ${node.grantee}`}>
                Revoke
              </Button>
            )}
          </div>
          <Branch nodes={nodes} parent={node.id} onRevoke={onRevoke} level={level + 1} />
        </li>
      ))}
    </ul>
  );
}

/** Nested view of a credential's grants. Children of revoked or expired grants are shown but unusable. */
export function DelegationTree({ owner, nodes, onRevoke }: Props) {
  const ids = new Set(nodes.map((n) => n.id));
  // A partial tree (e.g. a grantee's own subtree) starts at nodes whose parent is not visible.
  const roots = nodes.filter((n) => n.parent_share === null || !ids.has(n.parent_share));
  const normalised = nodes.map((n) => (roots.includes(n) ? { ...n, parent_share: null } : n));
  return (
    <div>
      <p className="mb-2 text-sm text-slate-600">
        Owner: <strong>{owner}</strong>
      </p>
      {nodes.length === 0 ? <p className="text-sm text-slate-500">Not shared with anyone.</p> : <Branch nodes={normalised} parent={null} onRevoke={onRevoke} level={1} />}
    </div>
  );
}
