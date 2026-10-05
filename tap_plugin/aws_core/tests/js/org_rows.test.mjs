// req-aws-core-layout-hints-4: the organization's best-effort top-level rows.
// Run: node --test tap_plugin/aws_core/tests/js/   (no JS lane runs this in CI yet)
import {test} from "node:test";
import assert from "node:assert/strict";

import {FOUNDATIONAL_OUS, hasPlacement, isFoundational, planOrgRows, subtreeSizes} from "../../static/aws_core/js/runtime/org-rows.js";
import {arrangeRows, stampColumns} from "../../static/aws_core/js/runtime/layout-hints.js";

const ou = (name, size = 0, tags = {}) => ({id: `ou:${name}`, name, kind: "ou", size, tags});
const acct = (name, tags = {}) => ({id: `acct:${name}`, name, kind: "account", size: 0, tags});

test("the expected org: Tenants, then highbar-backend, then the foundational row", () => {
    const rows = planOrgRows([
        ou("Security", 2), ou("Suspended"), ou("highbar-backend", 10), ou("Sandbox"),
        ou("Tenants", 14), acct("management"),
    ]);
    assert.deepEqual(rows, [
        ["ou:Tenants"],
        ["ou:highbar-backend"],
        ["ou:Sandbox", "ou:Security", "ou:Suspended", "acct:management"],
    ]);
});

test("highbar's design tags keep the tag-driven placement", () => {
    // The level-1 tags highbar's design-staging seed carries (highbar tools/gen/org.py).
    const children = [
        ou("Security", 2, {"layout:column": "1", "layout:order": "31", "layout:columns": "1", "layout:row": "20"}),
        ou("highbar-backend", 10, {"layout:order": "20", "layout:columns": "1", "layout:fill": "true"}),
        ou("Tenants", 6, {"layout:order": "10", "layout:columns": "1", "layout:fill": "true"}),
        ou("Sandbox", 0, {"layout:column": "1", "layout:order": "32"}),
        ou("Suspended", 0, {"layout:column": "1", "layout:order": "33"}),
        acct("management", {"layout:column": "1", "layout:order": "30", "layout:row": "20"}),
    ];
    assert.equal(planOrgRows(children), null);
});

test("one placement tag on any top-level child makes the whole level explicit", () => {
    assert.equal(planOrgRows([ou("Tenants", 5), ou("Security", 0, {"layout:order": "1"})]), null);
});

test("layout:fill and layout:columns size a box; they do not place it", () => {
    assert.equal(hasPlacement({"layout:fill": "true", "layout:columns": "1"}), false);
    assert.equal(hasPlacement({"layout:order": ""}), false);
    assert.equal(hasPlacement({"layout:row": "0"}), true);
    assert.deepEqual(planOrgRows([ou("Tenants", 1, {"layout:fill": "true"})]), [["ou:Tenants"]]);
});

test("only foundational OUs: one row, by name", () => {
    assert.deepEqual(planOrgRows([ou("Suspended"), ou("Security", 3), ou("Sandbox")]),
        [["ou:Sandbox", "ou:Security", "ou:Suspended"]]);
});

test("no OUs: nothing, or the root accounts in one row", () => {
    assert.deepEqual(planOrgRows([]), []);
    assert.deepEqual(planOrgRows([acct("b"), acct("a")]), [["acct:a", "acct:b"]]);
});

test("unknown names are workload OUs: largest subtree first, ties by name", () => {
    assert.deepEqual(planOrgRows([ou("zeta", 3), ou("alpha", 3), ou("Workloads", 9), ou("Foo")]),
        [["ou:Workloads"], ["ou:alpha"], ["ou:zeta"], ["ou:Foo"]]);
});

test("foundational names match case-insensitively, and only AWS's list", () => {
    assert.equal(FOUNDATIONAL_OUS.length, 9);
    for (const name of FOUNDATIONAL_OUS) {
        assert.ok(isFoundational(name.toUpperCase()), name);
        assert.ok(isFoundational(` ${name.toLowerCase()} `), name);
    }
    for (const name of ["Tenants", "highbar-backend", "Workloads", "Prod", "PolicyStaging", "", null]) {
        assert.equal(isFoundational(name), false, String(name));
    }
    assert.deepEqual(planOrgRows([ou("POLICY STAGING"), ou("infrastructure"), ou("Tenants", 1)]),
        [["ou:Tenants"], ["ou:infrastructure", "ou:POLICY STAGING"]]);
});

test("subtree size counts OUs and accounts at every depth, once each", () => {
    const sizes = subtreeSizes([
        {child: "T", parent: "org"}, {child: "T/Prod", parent: "T"}, {child: "T/Prod/a", parent: "T/Prod"},
        {child: "a1", parent: "T/Prod/a"}, {child: "a2", parent: "T/Prod/a"}, {child: "B", parent: "org"},
        {child: "b1", parent: "B"},
    ]);
    assert.equal(sizes.get("T"), 4);
    assert.equal(sizes.get("B"), 1);
    assert.equal(sizes.get("org"), 7);
    assert.equal(sizes.get("a1"), undefined);
    const loop = subtreeSizes([{child: "x", parent: "y"}, {child: "y", parent: "x"}]);
    assert.equal(loop.get("x"), 1);
});

// ---- the cytoscape side, on a minimal stand-in for nodes and cy ----

function node(id, tags = {}) {
    const data = new Map([["id", id], ["label", id], ["tags", tags]]);
    return {
        id: () => id,
        data: (k, v) => { if (v === undefined) return data.get(k); data.set(k, v); return undefined; },
    };
}

function fakeCy() {
    const added = [];
    return {added, add: (el) => { added.push(el); }};
}

test("arrangeRows with explicit rows: one row box per row, in the given order", () => {
    const [t, b, s, x] = ["Tenants", "backend", "Security", "Sandbox"].map((id) => node(id));
    const cy = fakeCy();
    arrangeRows(cy, node("org"), [s, x, b, t], {rows: [[t], [b], [x, s]]});
    const rowBoxes = cy.added.filter((e) => e.group === "nodes");
    assert.deepEqual(rowBoxes.map((e) => [e.data.id, e.data._order]),
        [["_layout_row:org:0", 0], ["_layout_row:org:1", 1], ["_layout_row:org:2", 2]]);
    const holds = cy.added.filter((e) => e.group === "edges" && e.data.source.startsWith("_layout_row:org:2"));
    assert.deepEqual(holds.map((e) => e.data.target), ["Sandbox", "Security"]);
    assert.deepEqual([x.data("_stage"), s.data("_stage")], [0, 1]);
});

test("arrangeRows with every row a single child stacks them, no row boxes", () => {
    const [t, b] = ["Tenants", "backend"].map((id) => node(id));
    const cy = fakeCy();
    arrangeRows(cy, node("org"), [b, t], {rows: [[t], [b]]});
    assert.equal(cy.added.length, 0);
    assert.deepEqual([t.data("_stage"), t.data("_order"), b.data("_stage"), b.data("_order")], [0, 0, 0, 1]);
});

test("stampColumns (the explicit path) still places highbar's design by its tags", () => {
    const kids = [
        node("Security", {"layout:column": "1", "layout:order": "31"}),
        node("highbar-backend", {"layout:order": "20"}),
        node("Tenants", {"layout:order": "10"}),
        node("Sandbox", {"layout:column": "1", "layout:order": "32"}),
        node("Suspended", {"layout:column": "1", "layout:order": "33"}),
        node("management", {"layout:column": "1", "layout:order": "30"}),
    ];
    stampColumns(kids);
    const placed = Object.fromEntries(kids.map((n) => [n.id(), [n.data("_stage"), n.data("_order")]]));
    assert.deepEqual(placed, {
        "Tenants": [0, 0], "highbar-backend": [0, 1], "management": [1, 2],
        "Security": [1, 3], "Sandbox": [1, 4], "Suspended": [1, 5],
    });
});
