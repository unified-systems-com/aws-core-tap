/**
 * layout-hints — placement a layout reads from a node's own tags, never from its name or id
 * (req-aws-core-layout-hints).
 *
 * Neutral tag keys, set on the node in the data that seeds or collects it:
 *
 *   layout:order    integer; siblings are placed in ascending order (a row left to right, a
 *                   column top to bottom). Unordered siblings follow the ordered ones, by label.
 *   layout:column   integer; which column of its parent a node sits in (0 = main, default),
 *                   where the parent lays its children out in columns (stampColumns).
 *   layout:columns  integer, on a PARENT; at most this many children per row, wrapping into
 *                   further rows. 1 stacks the children in one column.
 *   layout:row      integer; which row of its parent a node sits in, where the parent groups
 *                   its children into rows by tag (arrangeRows with byRowTag). Inside a row,
 *                   siblings sharing a layout:column stack in one column, in layout:order.
 *   layout:fill     "true"; the box widens to its lane. Sharing a column with other siblings:
 *                   the parent's inner width when all siblings share that one column, else the
 *                   column's widest box. Alone in its column (a row cell): the rest of its row.
 *
 * The helpers stamp `_stage` / `_order` for tap_viz's `ranked` inner layout (nested-projection.js).
 * A parent laid out in several rows gets one invisible row box per row (type `_layout_row`,
 * joined by `_LAYOUT_ROW` view edges): the caller adds ROW_RELATIONSHIP and rowLayouts() to its
 * projectNested config, so each row is sized bottom-up like any other box. Everything here acts on
 * the view (cy) only. The helpers know no entity type and no deployment.
 */

export const LAYOUT_TAG = {
    order: "layout:order", column: "layout:column", columns: "layout:columns", row: "layout:row", fill: "layout:fill",
};
export const ROW = {type: "_layout_row", edge: "_LAYOUT_ROW"};
//: Add to projectNested's relationships whenever arrangeRows may run.
export const ROW_RELATIONSHIP = {name: "layout-rows", gryphon: `(parent)-[:${ROW.edge}]->(child)`};

const HIDDEN = "tap-elevation-hidden";

//: The integer value of a tag, or null when absent or not an integer.
export function intTag(n, key) {
    const raw = new Map(Object.entries(n.data("tags") || {})).get(key);
    if (raw === undefined || raw === null || raw === "") return null;
    const v = Number(raw);
    return Number.isInteger(v) ? v : null;
}

export function isFill(n) {
    return n.data("_layout_fill") === true || String((n.data("tags") || {})[LAYOUT_TAG.fill] || "") === "true";
}

export function childrenOf(cy, parentId) {
    return cy.nodes().filter((n) => n.data("_viewport_parent") === parentId);
}

//: Move a node and everything nested in it.
export function moveTree(cy, node, dx, dy) {
    if (!dx && !dy) return;
    const p = node.position();
    node.position({x: p.x + dx, y: p.y + dy});
    childrenOf(cy, node.id()).forEach((c) => moveTree(cy, c, dx, dy));
}

function _byLabel(a, b) {
    return String(a.data("label") || "").localeCompare(String(b.data("label") || ""));
}

//: Siblings in layout:order, unordered ones after, by label.
export function sortSiblings(siblings) {
    const order = (n) => intTag(n, LAYOUT_TAG.order);
    return [...siblings].sort((a, b) => {
        const oa = order(a);
        const ob = order(b);
        if ((oa === null) !== (ob === null)) return oa === null ? 1 : -1;
        return ((oa || 0) - (ob || 0)) || _byLabel(a, b);
    });
}

//: Columns: layout:column picks the column (default 0), layout:order the place in it.
export function stampColumns(siblings) {
    sortSiblings(siblings).forEach((n, i) => {
        const column = intTag(n, LAYOUT_TAG.column);
        n.data("_stage", column === null ? 0 : column);
        n.data("_order", i);
    });
}

/**
 * Lay a parent's children out in rows, for a parent whose inner layout is `ranked`.
 *
 * Rows come from `rows` when given (the caller's own rows, top to bottom, each already in order),
 * else from `layout:row` when `byRowTag` is set (untagged children each take their own row
 * after the tagged ones), else from wrapping the ordered children at `columns` per row
 * (default: the parent's layout:columns tag, else unlimited). One row: each child its own
 * `ranked` column. Every row a single child: one column, stacked. Otherwise each row becomes an
 * invisible row box holding its children; the children's containment edges to the parent are
 * hidden in the view so that the row box, not the parent, holds them.
 *
 * @param {cytoscape.Core} cy
 * @param {cytoscape.NodeSingular} parent
 * @param {cytoscape.NodeSingular[]} children - the parent's children, found by the caller
 * @param {{columns?: number, byRowTag?: boolean, rows?: cytoscape.NodeSingular[][],
 *          containEdges?: cytoscape.EdgeCollection}} [opts]
 *   containEdges: the edges that make `parent` the parent of each child (hidden when rows form).
 */
export function arrangeRows(cy, parent, children, opts) {
    const o = opts || {};
    const ordered = o.rows ? o.rows.flat() : sortSiblings(children);
    let rows;
    if (o.rows) {
        rows = o.rows.filter((r) => r.length);
    } else if (o.byRowTag) {
        const tagged = new Map();
        const loose = [];
        ordered.forEach((n) => {
            const r = intTag(n, LAYOUT_TAG.row);
            if (r === null) loose.push([n]);
            else { if (!tagged.has(r)) tagged.set(r, []); tagged.get(r).push(n); }
        });
        rows = [...[...tagged.keys()].sort((a, b) => a - b).map((k) => tagged.get(k)), ...loose];
    } else {
        const tagCols = intTag(parent, LAYOUT_TAG.columns);
        const k = o.columns || (tagCols && tagCols > 0 ? tagCols : ordered.length || 1);
        rows = [];
        for (let i = 0; i < ordered.length; i += k) rows.push(ordered.slice(i, i + k));
    }
    if (rows.length <= 1) {
        _stampRow(ordered);
        return;
    }
    if (rows.every((r) => r.length === 1)) {
        rows.forEach(([n], i) => { n.data("_stage", 0); n.data("_order", i); });
        return;
    }
    const childIds = new Set(ordered.map((n) => n.id()));
    const pid = parent.id();
    if (o.containEdges) {
        o.containEdges.filter((e) => (childIds.has(e.source().id()) && e.target().id() === pid)
            || (e.source().id() === pid && childIds.has(e.target().id()))).addClass(HIDDEN);
    }
    rows.forEach((row, r) => {
        const rowId = `${ROW.type}:${parent.id()}:${r}`;
        // shape / icon_url: the icon-badge node style maps both from data; a row box draws neither.
        cy.add({group: "nodes", data: {id: rowId, entity_type: ROW.type, label: "", shape: "rectangle", icon_url: "none",
                                       _stage: 0, _order: r, _layout_fill: true, _layout_inset: 0}, classes: ROW.type});
        cy.add({group: "edges", data: {id: `${ROW.edge}:${rowId}`, source: parent.id(), target: rowId, edge_type: ROW.edge}, classes: ROW.type});
        _stampRow(row);
        row.forEach((n) => {
            cy.add({group: "edges", data: {id: `${ROW.edge}:${n.id()}`, source: rowId, target: n.id(), edge_type: ROW.edge}, classes: ROW.type});
        });
    });
}

//: One row for `ranked`: each child its own column, unless children carry layout:column, in
//: which case those sharing a value stack in that column (in the row's sorted order).
function _stampRow(row) {
    const tagged = row.some((n) => intTag(n, LAYOUT_TAG.column) !== null);
    row.forEach((n, i) => {
        n.data("_stage", tagged ? (intTag(n, LAYOUT_TAG.column) || 0) : i);
        n.data("_order", i);
    });
}

//: projectNested pieces for row boxes: no padding, children in one ranked row.
export function rowLayouts(gap) {
    return {
        padding: {[ROW.type]: 0},
        innerLayout: {[ROW.type]: {name: "ranked", sort: "order", columnGap: gap, rowGap: gap}},
        baseSize: {[ROW.type]: {width: 1, height: 1}},
    };
}

//: Row boxes draw nothing; call after placeParentLabels.
export function styleRows(cy) {
    cy.style()
        .selector(`node.${ROW.type}`)
        .style({"background-opacity": 0, "border-width": 0, "label": "", "events": "no"})
        .selector(`edge.${ROW.type}`)
        .style({"display": "none"})
        .update();
}

function _depth(cy, n) {
    let d = 0;
    let p = n.data("_viewport_parent");
    while (p) {
        d += 1;
        p = cy.getElementById(p).data("_viewport_parent");
    }
    return d;
}

/**
 * Stretch every fill box, parents before children.
 *
 * @param {cytoscape.Core} cy
 * @param {{inset?: number, insets?: Object<string, number>}} [opts] - a parent's side padding:
 *   `insets` by the parent's entity_type, else `inset` (default 24). Row boxes have none.
 */
export function fill(cy, opts) {
    const o = opts || {};
    const insets = new Map(Object.entries(o.insets || {}));
    const insetOf = (p) => {
        if (p.data("_layout_inset") != null) return p.data("_layout_inset");
        const byType = insets.get(p.data("entity_type"));
        if (byType != null) return byType;
        return o.inset != null ? o.inset : 24;
    };
    const fills = cy.nodes().filter(isFill).sort((a, b) => _depth(cy, a) - _depth(cy, b));
    fills.forEach((n) => {
        const parentId = n.data("_viewport_parent");
        if (!parentId) return;
        const parent = cy.getElementById(parentId);
        const inset = insetOf(parent);
        const siblings = childrenOf(cy, parentId);
        const stage = n.data("_stage");
        const inColumn = Number.isInteger(stage) ? siblings.filter((s) => s.data("_stage") === stage) : [n];
        if (inColumn.length > 1) {
            const oneColumn = inColumn.length === siblings.length;
            const width = oneColumn ? parent.width() - inset * 2 : Math.max(...inColumn.map((s) => s.width()));
            if (width > n.width()) {
                n.style({width});
                if (oneColumn) moveTree(cy, n, parent.position().x - n.position().x, 0);
            }
            return;
        }
        const innerLeft = parent.position().x - parent.width() / 2 + inset;
        const innerW = parent.width() - inset * 2;
        const y0 = n.position().y - n.height() / 2;
        const y1 = n.position().y + n.height() / 2;
        const row = siblings.filter((s) => {
            const t = s.position().y - s.height() / 2;
            const b = s.position().y + s.height() / 2;
            return t < y1 && b > y0;
        }).sort((a, b) => a.position().x - b.position().x);
        const gap = row.length > 1 ? (row[1].position().x - row[1].width() / 2) - (row[0].position().x + row[0].width() / 2) : 0;
        const others = row.filter((s) => s.id() !== n.id()).reduce((w, s) => w + s.width(), 0);
        const width = innerW - others - gap * (row.length - 1);
        if (width <= n.width()) return;
        n.style({width});
        let x = innerLeft;
        row.forEach((s) => {
            moveTree(cy, s, x + s.width() / 2 - s.position().x, 0);
            x += s.width() + gap;
        });
    });
}
