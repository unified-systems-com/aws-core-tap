/**
 * org-rows — the best-effort arrangement of an AWS organization's top level, for an organization
 * whose children carry no placement tag of their own (req-aws-core-layout-hints-4).
 *
 * Pure functions over plain objects: no cytoscape, no imports. aws-organization.js maps the scene
 * onto them.
 *
 *   - Foundational OUs: a top-level OU whose name, compared case-insensitively, is one of the OU
 *     names AWS recommends in "Organizing Your AWS Environment Using Multiple Accounts". They share
 *     one bottom row, in name order; accounts held directly by the organization (the management
 *     account) follow them in that row, in name order.
 *   - Every other top-level OU is a workload OU and takes a row of its own above the foundational
 *     row: the largest subtree first (OUs plus accounts beneath it), ties in name order.
 *
 * The name list is AWS's published guidance, not any deployment's names. Explicit placement wins:
 * when any top-level child carries `layout:order`, `layout:column` or `layout:row`, planOrgRows
 * returns null and the caller keeps its tag-driven placement for the whole level.
 */

//: AWS's recommended OU names (Organizing Your AWS Environment, "Recommended OUs").
export const FOUNDATIONAL_OUS = Object.freeze([
    "Security", "Infrastructure", "Sandbox", "Suspended", "Exceptions", "Policy Staging",
    "Transitional", "Deployments", "Individual Business Users",
]);
const FOUNDATIONAL = new Set(FOUNDATIONAL_OUS.map((s) => s.toLowerCase()));

//: The tags that place a node among its siblings; any one of them on a top-level child is explicit.
export const PLACEMENT_TAGS = Object.freeze(["layout:order", "layout:column", "layout:row"]);

export function isFoundational(name) {
    return FOUNDATIONAL.has(String(name || "").trim().toLowerCase());
}

export function hasPlacement(tags) {
    const t = new Map(Object.entries(tags || {}));
    return PLACEMENT_TAGS.some((k) => {
        const v = t.get(k);
        return v !== undefined && v !== null && v !== "";
    });
}

function _byName(a, b) {
    return String(a.name || "").localeCompare(String(b.name || "")) || String(a.id).localeCompare(String(b.id));
}

/**
 * How many nodes sit beneath each parent, at any depth.
 *
 * @param {{child: string, parent: string}[]} links - containment, child → parent
 * @returns {Map<string, number>} parent id → descendant count (a node with no children is absent)
 */
export function subtreeSizes(links) {
    const kids = new Map();
    links.forEach(({child, parent}) => {
        if (!kids.has(parent)) kids.set(parent, new Set());
        kids.get(parent).add(child);
    });
    const sizes = new Map();
    const count = (id, seen) => {
        let n = 0;
        (kids.get(id) || new Set()).forEach((c) => {
            if (seen.has(c)) return; // a cycle in the scene: count each node once, never loop
            seen.add(c);
            n += 1 + count(c, seen);
        });
        return n;
    };
    kids.forEach((_, id) => sizes.set(id, count(id, new Set([id]))));
    return sizes;
}

/**
 * Rows for an organization's direct children, top to bottom, or null when explicit placement wins.
 *
 * @param {{id: string, name: string, kind: "ou"|"account", size?: number, tags?: Object}[]} children
 * @returns {string[][]|null} rows of child ids; [] for no children
 */
export function planOrgRows(children) {
    if (children.some((c) => hasPlacement(c.tags))) return null;
    const ous = children.filter((c) => c.kind === "ou");
    const workload = ous.filter((c) => !isFoundational(c.name))
        .sort((a, b) => ((b.size || 0) - (a.size || 0)) || _byName(a, b));
    const foundational = ous.filter((c) => isFoundational(c.name)).sort(_byName);
    const accounts = children.filter((c) => c.kind !== "ou").sort(_byName);
    const rows = workload.map((c) => [c.id]);
    const bottom = [...foundational, ...accounts].map((c) => c.id);
    if (bottom.length) rows.push(bottom);
    return rows;
}
