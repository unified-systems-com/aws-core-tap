"""Read the Terraform AWS provider's Go source with tree-sitter, by parsing only.

The provider is never built, imported or run. This layer supplies what the schema dump (terraform_reader.py)
lacks: the AWS API field behind each attribute (`d.Set("is_enabled", key.metadata.Enabled)`: attribute
`is_enabled` is filled from API field `Enabled`) and the read operations each resource makes
(`conn.DescribeKey(...)`). Terraform is a reference, not ground truth: this is what the provider's authors
wrote, and it can be wrong or out of date.

tree-sitter is an optional dependency (`pip install -r tools/crosscheck/requirements-terraform.txt`); the rest
of crosscheck does not import this module.

Everything taken from the tree is untrusted text. Strings stored here have control characters replaced.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from carto_reader import commit_of


class MissingDependency(RuntimeError):
    """tree-sitter is not installed; only the Terraform source reader needs it."""


def _parser() -> Any:
    try:
        import tree_sitter_go
        from tree_sitter import Language, Parser
    except ImportError as e:
        raise MissingDependency(
            "reading the Terraform provider source needs tree-sitter; run "
            "`pip install -r tools/crosscheck/requirements-terraform.txt` (" + str(e) + ")"
        ) from e
    return Parser(Language(tree_sitter_go.language()))


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")


def clean(s: object, limit: int = 240) -> str:
    """Text from the analysed tree: control characters become '?' and the length is capped."""
    t = _CTRL.sub("?", str(s))
    return t if len(t) <= limit else t[: limit - 1] + "…"


_READ_OP = re.compile(r"^(Describe|List|Get|BatchGet|Lookup|Search)[A-Z0-9]")
_PAGINATOR = re.compile(r"^New((?:Describe|List|Get|BatchGet|Lookup|Search)\w+?)Paginator$")
_INPUT = re.compile(r"^\w+\.([A-Z]\w+)Input$")
_FLAG_KEYS = ("Optional", "Required", "Computed", "ForceNew", "Sensitive")
_CLIENT_NAMES = ("conn", "client")
_NOT_ROOTS = {"d", "meta", "ctx", "diags", "err", "conn", "client", "r", "resp", "req"}
_MAP_TYPE = re.compile(r"^map\[string\](\*?\w+\.)?(Schema|Attribute|Block)\b")


def _txt(n: Any, src: bytes) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", "replace")


def _walk(n: Any):
    stack = [n]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(reversed(cur.children))


def _str_lit(n: Any, src: bytes) -> str | None:
    if n is not None and n.type in ("interpreted_string_literal", "raw_string_literal"):
        return _txt(n, src)[1:-1]
    return None


def _keyed(lit: Any, src: bytes) -> list[tuple[Any, Any]]:
    """[(key_node, value_node)] of a composite literal. Slice elements are literal_value nodes and keyed
    elements wrap each side in a literal_element, which is easy to miss."""
    body = lit if lit.type == "literal_value" else lit.child_by_field_name("body")
    out: list[tuple[Any, Any]] = []
    if body is None:
        return out
    for el in body.children:
        if el.type == "keyed_element":
            sides = [c for c in el.children if c.type == "literal_element"]
            if len(sides) == 2 and sides[0].children and sides[1].children:
                out.append((sides[0].children[0], sides[1].children[0]))
    return out


def _is_lit(n: Any) -> bool:
    return n is not None and n.type in ("composite_literal", "literal_value")


class _Pkg:
    """One Go package (a directory): its functions, methods and constants, and each file's imports."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.funcs: dict[str, tuple[Any, bytes, dict[str, str], str]] = {}
        self.methods: dict[tuple[str, str], tuple[Any, bytes, dict[str, str], str]] = {}
        self.method_names: dict[str, list[str]] = {}
        self.consts: dict[str, str] = {}
        self.vars: dict[str, tuple[Any, bytes]] = {}
        self.structs: dict[str, dict[str, str]] = {}  # type -> {tfsdk attr: Go field}
        self.embeds: dict[str, list[str]] = {}  # type -> embedded types, whose methods it promotes
        self.registry: list[dict[str, Any]] = []
        self.summaries: dict[tuple[str, str], dict[str, Any]] = {}

    def method(self, rtype: str, name: str, depth: int = 0) -> tuple[Any, bytes, dict[str, str], str, str] | None:
        """A method of a type, or of a type it embeds (Go promotes those); the declaring type is the last element."""
        ent = self.methods.get((rtype, name))
        if ent:
            return (*ent, rtype)
        if depth < 3:
            for e in self.embeds.get(rtype, []):
                got = self.method(e, name, depth + 1)
                if got:
                    return got
        return None


def _imports(root: Any, src: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in _walk(root):
        if n.type == "import_spec":
            path = _str_lit(n.child_by_field_name("path"), src)
            if not path:
                continue
            name = n.child_by_field_name("name")
            alias = _txt(name, src) if name is not None else path.rsplit("/", 1)[-1]
            if re.fullmatch(r"v\d+", alias):  # .../foo/v2 is package foo
                alias = path.rsplit("/", 2)[-2]
            out[alias] = path
    return out


def _pkg_key(import_path: str) -> str | None:
    m = re.search(r"/internal/service/([A-Za-z0-9_]+)$", import_path)
    return "internal/service/" + m.group(1) if m else None


def _load_names(root: Path, h: Any, parser: Any) -> dict[str, str]:
    consts: dict[str, str] = {}
    for f in sorted((root / "names").glob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        data = f.read_bytes()
        h.update(str(f.relative_to(root)).encode() + b"\0" + data + b"\0")
        tree = parser.parse(data)
        _collect_consts(tree.root_node, data, consts)
    return consts


def _collect_consts(root: Any, src: bytes, into: dict[str, str]) -> None:
    for n in _walk(root):
        if n.type == "const_spec":
            nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
            if nm is None or val is None:
                continue
            v = val.children[0] if val.type == "expression_list" and val.children else val
            s = _str_lit(v, src)
            if s is not None:
                into[_txt(nm, src)] = s


def _key(n: Any, src: bytes, pkg_consts: dict[str, str], names: dict[str, str]) -> str | None:
    """A schema or d.Set key: a string literal, `names.AttrX`, or a constant of the same package."""
    if n is None:
        return None
    s = _str_lit(n, src)
    if s is not None:
        return s
    if n.type == "selector_expression":
        return names.get(_txt(n.child_by_field_name("field"), src))
    if n.type == "identifier":
        t = _txt(n, src)
        return pkg_consts.get(t, names.get(t))
    return None


def _flatten(n: Any, src: bytes) -> tuple[str, list[str]] | None:
    """`x.a.B` -> ("x", ["a", "B"]); None unless the chain starts at a plain identifier."""
    names: list[str] = []
    cur = n
    while cur is not None:
        if cur.type == "selector_expression":
            names.append(_txt(cur.child_by_field_name("field"), src))
            cur = cur.child_by_field_name("operand")
        elif cur.type == "index_expression":
            cur = cur.child_by_field_name("operand")
        elif cur.type in ("parenthesized_expression", "unary_expression"):
            kids = [c for c in cur.children if c.is_named]
            cur = kids[-1] if kids else None
        elif cur.type == "identifier":
            return _txt(cur, src), list(reversed(names))
        else:
            return None
    return None


def api_fields(expr: Any, src: bytes, imports: dict[str, str]) -> list[str]:
    """The dotted API-field paths named in a d.Set value: `aws.ToString(out.Config.Name)` -> ["Config.Name"].

    A chain counts when it starts at a local variable (not an imported package) and ends in an exported name;
    leading lower-case segments (the provider's own struct fields) are dropped. A method call on a chain
    contributes the chain without the method.
    """
    found: list[str] = []
    for n in _walk(expr):
        if n.type != "selector_expression":
            continue
        p = n.parent
        if p is not None and p.type == "selector_expression" and p.child_by_field_name("operand") == n:
            continue  # an inner part of a longer chain
        target = n
        if p is not None and p.type == "call_expression" and p.child_by_field_name("function") == n:
            target = n.child_by_field_name("operand")  # `x.Name.String()`: the method is not a field
            if target is None:
                continue
        flat = _flatten(target, src)
        if not flat:
            continue
        root, fields = flat
        if root in imports or root in _NOT_ROOTS or not fields:
            continue
        while fields and not fields[0][:1].isupper():
            fields = fields[1:]
        if fields and fields[-1][:1].isupper():
            path = ".".join(fields)
            if path not in found:
                found.append(path)
    return found


def _recv_of(method: Any, src: bytes) -> tuple[str, str]:
    """(receiver variable, receiver type) of a method declaration."""
    recv = method.child_by_field_name("receiver")
    if recv is not None:
        for pd in recv.children:
            if pd.type == "parameter_declaration":
                nm, ty = pd.child_by_field_name("name"), pd.child_by_field_name("type")
                tt = re.sub(r"[^A-Za-z0-9_]", "", _txt(ty, src)) if ty is not None else ""
                return (_txt(nm, src) if nm is not None else "", tt)
    return "", ""


class _Source:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.parser = _parser()
        self.h = hashlib.sha256()
        self.pkgs: dict[str, _Pkg] = {}
        self.names: dict[str, str] = {}
        self.files = 0
        self.parse_errors = 0

    # ------------------------------------------------------------ indexing
    def load(self) -> None:
        svc_root = self.root / "internal" / "service"
        if not svc_root.is_dir():
            raise ValueError(f"{self.root} has no internal/service: this does not look like the Terraform AWS provider")
        self.names = _load_names(self.root, self.h, self.parser)
        for d in sorted(p for p in svc_root.iterdir() if p.is_dir()):
            pkg = _Pkg("internal/service/" + d.name)
            for f in sorted(d.glob("*.go")):
                if f.name.endswith("_test.go"):
                    continue
                data = f.read_bytes()
                self.h.update(str(f.relative_to(self.root)).encode() + b"\0" + data + b"\0")
                tree = self.parser.parse(data)
                self.files += 1
                if tree.root_node.has_error:
                    self.parse_errors += 1
                self._index_file(pkg, tree.root_node, data, str(f.relative_to(self.root)))
            self.pkgs[pkg.key] = pkg

    def _index_file(self, pkg: _Pkg, root: Any, src: bytes, rel: str) -> None:
        imports = _imports(root, src)
        _collect_consts(root, src, pkg.consts)
        for n in root.children:
            if n.type == "function_declaration":
                pkg.funcs.setdefault(_txt(n.child_by_field_name("name"), src), (n, src, imports, rel))
            elif n.type == "method_declaration":
                _, rtype = _recv_of(n, src)
                name = _txt(n.child_by_field_name("name"), src)
                pkg.methods.setdefault((rtype, name), (n, src, imports, rel))
                pkg.method_names.setdefault(name, []).append(rtype)
            elif n.type == "type_declaration":
                self._index_struct(pkg, n, src)
            elif n.type == "var_declaration":
                for spec in (x for x in _walk(n) if x.type == "var_spec"):
                    nm, val = spec.child_by_field_name("name"), spec.child_by_field_name("value")
                    if nm is not None and val is not None and val.named_children:
                        pkg.vars.setdefault(_txt(nm, src), (val.named_children[0], src))
        if rel.endswith("service_package_gen.go"):
            self._index_registry(pkg, root, src)

    def _index_struct(self, pkg: _Pkg, decl: Any, src: bytes) -> None:
        for spec in decl.children:
            if spec.type != "type_spec":
                continue
            ty = spec.child_by_field_name("type")
            if ty is None or ty.type != "struct_type":
                continue
            fields: dict[str, str] = {}
            tname = _txt(spec.child_by_field_name("name"), src)
            for fd in _walk(ty):
                if fd.type == "field_declaration":
                    tag, nm = fd.child_by_field_name("tag"), fd.child_by_field_name("name")
                    if nm is None and fd.child_by_field_name("type") is not None:  # an embedded type
                        emb = re.sub(r"[^A-Za-z0-9_]", "", _txt(fd.child_by_field_name("type"), src).split(".")[-1])
                        if "." not in _txt(fd.child_by_field_name("type"), src) and emb:
                            pkg.embeds.setdefault(tname, []).append(emb)
                    m = re.search(r'tfsdk:"([^"]+)"', _txt(tag, src)) if tag is not None else None
                    if m and nm is not None:
                        fields[m.group(1)] = _txt(nm, src)
            if fields:
                pkg.structs[_txt(spec.child_by_field_name("name"), src)] = fields

    def _index_registry(self, pkg: _Pkg, root: Any, src: bytes) -> None:
        for fn in root.children:
            if fn.type != "method_declaration":
                continue
            mname = _txt(fn.child_by_field_name("name"), src)
            if mname not in ("SDKResources", "FrameworkResources"):
                continue
            for lit in (n for n in _walk(fn) if _is_lit(n)):
                kv = {_txt(k, src): v for k, v in _keyed(lit, src)}
                if "TypeName" not in kv:
                    continue
                pkg.registry.append(
                    {
                        "kind": "sdk" if mname == "SDKResources" else "framework",
                        "type": _key(kv["TypeName"], src, pkg.consts, self.names),
                        "factory": _txt(kv["Factory"], src) if "Factory" in kv else None,
                        "has_tags": "Tags" in kv,
                        "identity": clean(_txt(kv["Identity"], src), 160) if "Identity" in kv else None,
                    }
                )

    # ------------------------------------------------------------ function summaries
    def _summary(self, pkg: _Pkg, ent: tuple[Any, bytes, dict[str, str], str], skey: tuple[str, str]) -> dict[str, Any]:
        cached = pkg.summaries.get(skey)
        if cached is not None:
            return cached
        node, src, imports, rel = ent
        rvar, rtype = _recv_of(node, src) if node.type == "method_declaration" else ("", "")
        ops: set[str] = set()
        sets: list[tuple[str, list[str], str, str]] = []
        callees: list[tuple[str, ...]] = []
        flatten = False
        for c in _walk(node):
            if c.type == "composite_literal":  # `cloudwatchlogs.DescribeLogGroupsInput{...}` names the operation it feeds
                ty = c.child_by_field_name("type")
                im = _INPUT.match(_txt(ty, src)) if ty is not None else None
                if im and _READ_OP.match(im.group(1)):
                    ops.add(im.group(1))
                continue
            if c.type != "call_expression":
                continue
            f, args = c.child_by_field_name("function"), c.child_by_field_name("arguments")
            if f is None:
                continue
            ft = _txt(f, src)
            if ft == "d.Set" and args is not None and len(args.named_children) >= 2:
                k = _key(args.named_children[0], src, pkg.consts, self.names)
                if k:
                    val = args.named_children[1]
                    sets.append((k, api_fields(val, src, imports), clean(_txt(val, src)), f"{rel}:{c.start_point[0] + 1}"))
            if f.type == "identifier":
                m = _PAGINATOR.match(ft)
                if m:
                    ops.add(m.group(1))
                callees.append(("ident", ft))
            elif f.type == "selector_expression":
                op, fld = f.child_by_field_name("operand"), _txt(f.child_by_field_name("field"), src)
                otext = _txt(op, src) if op is not None else ""
                if fld == "Flatten" or fld.endswith("Flatten"):
                    flatten = True
                if otext in _CLIENT_NAMES and _READ_OP.match(fld):
                    ops.add(fld)
                elif otext in imports:
                    pm = _PAGINATOR.match(fld)
                    if pm:
                        ops.add(pm.group(1))
                    callees.append(("pkg", imports[otext], fld))
                elif otext == rvar and rvar:
                    callees.append(("method", rtype, fld))
                elif op is not None and op.type == "identifier" and otext not in _NOT_ROOTS:
                    callees.append(("anymethod", fld))
        out = {"ops": ops, "sets": sets, "callees": callees, "flatten": flatten}
        pkg.summaries[skey] = out
        return out

    def _resolve(self, pkg: _Pkg, ref: tuple[str, ...]) -> tuple[_Pkg, tuple[Any, bytes, dict[str, str], str], tuple[str, str]] | None:
        kind = ref[0]
        if kind == "ident":
            ent = pkg.funcs.get(ref[1])
            return (pkg, ent, ("", ref[1])) if ent else None
        if kind == "method":
            got = pkg.method(ref[1], ref[2])
            return (pkg, got[:4], (got[4], ref[2])) if got else None
        if kind == "pkg":
            key = _pkg_key(ref[1])
            other = self.pkgs.get(key) if key else None
            ent = other.funcs.get(ref[2]) if other else None
            return (other, ent, ("", ref[2])) if other and ent else None
        if kind == "anymethod":  # a method on some other variable: credited only when the name is unique in the package
            owners = pkg.method_names.get(ref[1], [])
            if len(owners) == 1 and (owners[0], ref[1]) in pkg.methods:
                return (pkg, pkg.methods[(owners[0], ref[1])], (owners[0], ref[1]))
        return None

    def closure(self, pkg: _Pkg, ent: tuple[Any, bytes, dict[str, str], str], skey: tuple[str, str]) -> dict[str, Any]:
        """Everything reachable from a function through resolvable calls: d.Set calls, client reads, Flatten use."""
        seen: set[tuple[str, str, str]] = set()
        stack = [(pkg, ent, skey)]
        ops: set[str] = set()
        sets: list[tuple[str, list[str], str, str]] = []
        flatten = False
        while stack:
            p, e, k = stack.pop()
            ident = (p.key, k[0], k[1])
            if ident in seen:
                continue
            seen.add(ident)
            s = self._summary(p, e, k)
            ops |= s["ops"]
            sets += s["sets"]
            flatten = flatten or s["flatten"]
            for ref in s["callees"]:
                r = self._resolve(p, ref)
                if r:
                    stack.append(r)
        return {"ops": ops, "sets": sets, "flatten": flatten}

    # ------------------------------------------------------------ resources
    def _schema_names(self, lit: Any, src: bytes, pkg: _Pkg, ty_prefix: str) -> tuple[dict[str, list[str]], int]:
        """Top-level keys of the outermost schema map literal, with flags; nested maps (Elem) are not read."""
        attrs: dict[str, list[str]] = {}
        unresolved = 0
        for k, v in _keyed(lit, src):
            name = _key(k, src, pkg.consts, self.names)
            if name is None:
                unresolved += 1
                continue
            flags: set[str] = set()
            if _is_lit(v):
                for kk, vv in _keyed(v, src):
                    if _txt(kk, src) in _FLAG_KEYS and _txt(vv, src) == "true":
                        flags.add(_txt(kk, src))
            attrs[clean(name)] = sorted(flags)
        return attrs, unresolved

    def _maps_of(self, v: Any, src: bytes, pkg: _Pkg, scope: Any, depth: int = 0) -> list[tuple[Any, bytes]]:
        """The schema map literals a value stands for: a literal, a local or package variable, a function or
        function literal that returns one, or a call (`maps.Clone(x)`) whose arguments or callee do."""
        if v is None or depth > 5:
            return []
        t = v.type
        if t == "composite_literal":
            ty = v.child_by_field_name("type")
            return [(v, src)] if ty is not None and _MAP_TYPE.match(_txt(ty, src)) else []
        if t == "func_literal":
            return self._returned(v, src, pkg, depth)
        if t == "unary_expression":
            kids = [c for c in v.children if c.is_named]
            return self._maps_of(kids[-1], src, pkg, scope, depth + 1) if kids else []
        if t == "identifier":
            name = _txt(v, src)
            local = _local_value(scope, src, name) if scope is not None else None
            if local is not None:
                return self._maps_of(local, src, pkg, scope, depth + 1)
            if name in pkg.vars:
                vn, vs = pkg.vars[name]
                return self._maps_of(vn, vs, pkg, vn, depth + 1)
            if name in pkg.funcs:
                fn, fs, _fi, _fr = pkg.funcs[name]
                return self._returned(fn, fs, pkg, depth)
            return []
        if t == "call_expression":
            out: list[tuple[Any, bytes]] = []
            f = v.child_by_field_name("function")
            if f is not None and f.type == "identifier" and _txt(f, src) in pkg.funcs:
                fn, fs, _fi, _fr = pkg.funcs[_txt(f, src)]
                out += self._returned(fn, fs, pkg, depth)
            args = v.child_by_field_name("arguments")
            for a in args.named_children if args is not None else []:
                out += self._maps_of(a, src, pkg, scope, depth + 1)
            return out
        return []

    def _returned(self, fnode: Any, src: bytes, pkg: _Pkg, depth: int) -> list[tuple[Any, bytes]]:
        out: list[tuple[Any, bytes]] = []
        body = fnode.child_by_field_name("body")
        stack = [body] if body is not None else []
        while stack:
            cur = stack.pop()
            if cur.type == "func_literal":
                continue  # a nested function's returns are not this function's
            if cur.type == "return_statement":
                for e in cur.named_children:
                    for x in e.named_children if e.type == "expression_list" else [e]:
                        out += self._maps_of(x, src, pkg, fnode, depth + 1)
                continue
            stack.extend(cur.children)
        return out

    def _names_from(self, maps: list[tuple[Any, bytes]], pkg: _Pkg) -> tuple[dict[str, list[str]], int]:
        attrs: dict[str, list[str]] = {}
        unresolved = 0
        for lit, s in maps:
            a, u = self._schema_names(lit, s, pkg, "")
            attrs.update(a)
            unresolved += u
        return attrs, unresolved

    def _sdk_attrs(self, pkg: _Pkg, fent: tuple[Any, bytes, dict[str, str], str]) -> tuple[dict[str, list[str]], str | None, int, bool]:
        node, src, _imports_, _rel = fent
        read_name = None
        maps: list[tuple[Any, bytes]] = []
        lits = [n for n in _walk(node) if n.type == "composite_literal" and _txt(n.child_by_field_name("type"), src) == "schema.Resource"]
        # The resource the factory returns, not an earlier old-schema one kept for a state upgrade.
        lits.sort(key=lambda n: (0 if _in_return(n) else 1, _depth(n)))
        for lit in lits[:1]:
            for k, v in _keyed(lit, src):
                kt = _txt(k, src)
                if kt in ("ReadWithoutTimeout", "ReadContext", "Read"):
                    read_name = _txt(v, src)
                if kt in ("Schema", "SchemaFunc"):
                    maps = self._maps_of(v, src, pkg, node)
        attrs, unresolved = self._names_from(maps, pkg)
        if maps:
            return attrs, read_name, unresolved, True
        if not attrs:  # no recognisable Schema key: the first schema map literal in the factory
            for n in _walk(node):
                if n.type == "composite_literal" and _MAP_TYPE.match(_txt(n.child_by_field_name("type"), src) if n.child_by_field_name("type") is not None else ""):
                    attrs, unresolved = self._names_from([(n, src)], pkg)
                    break
        return attrs, read_name, unresolved, bool(attrs)

    def _read_func(self, pkg: _Pkg, fent: tuple[Any, bytes, dict[str, str], str], read_name: str | None):
        """(package, function entry, key) of an SDK resource's read function, same package first."""
        if not read_name:
            return None
        if re.fullmatch(r"\w+", read_name):
            ent = pkg.funcs.get(read_name)
            return (pkg, ent, ("", read_name)) if ent else None
        m = re.fullmatch(r"(\w+)\.(\w+)", read_name)
        if m:
            key = _pkg_key(fent[2].get(m.group(1), ""))
            other = self.pkgs.get(key) if key else None
            ent = other.funcs.get(m.group(2)) if other else None
            return (other, ent, ("", m.group(2))) if other and ent else None
        return None

    def _fw_attrs(self, pkg: _Pkg, fent: tuple[Any, bytes, dict[str, str], str]) -> tuple[dict[str, list[str]], str | None, int]:
        node, src, _i, _r = fent
        recv = None
        for lit in (x for x in _walk(node) if x.type == "composite_literal"):
            ty = lit.child_by_field_name("type")
            if ty is not None and ty.type == "type_identifier":
                recv = _txt(ty, src)
                break
        if recv is None:
            return {}, None, 0
        m = pkg.method(recv, "Schema")
        if not m:
            return {}, recv, 0
        mnode, msrc, _mi, _mr, _mt = m
        maps: list[tuple[Any, bytes]] = []
        for lit in (x for x in _walk(mnode) if x.type == "composite_literal"):
            ty = lit.child_by_field_name("type")
            if ty is not None and re.fullmatch(r"\w*\.?Schema", _txt(ty, msrc)):
                for k, v in _keyed(lit, msrc):
                    if _txt(k, msrc) in ("Attributes", "Blocks"):
                        maps += self._maps_of(v, msrc, pkg, mnode)
                break
        attrs, unresolved = self._names_from(maps, pkg)
        return attrs, recv, unresolved

    def resources(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for pkg in self.pkgs.values():
            for reg in pkg.registry:
                tname = reg["type"]
                if not tname:
                    continue
                tname = clean(tname)
                fent = pkg.funcs.get(reg["factory"] or "")
                row: dict[str, Any] = {
                    "service": pkg.key.rsplit("/", 1)[-1],
                    "kind": reg["kind"],
                    "factory": clean(reg["factory"] or ""),
                    "has_tags": reg["has_tags"],
                    "identity": reg["identity"],
                    "schema_found": False,
                    "attributes": {},
                    "unresolved_keys": 0,
                    "api": {},
                    "ops": [],
                    "read_found": False,
                    "mapping": None,
                }
                if fent is None:
                    out.setdefault(tname, row)
                    continue
                if reg["kind"] == "sdk":
                    attrs, read_name, unres, found = self._sdk_attrs(pkg, fent)
                    got = self._read_func(pkg, fent, read_name)
                    read_ent = got[1] if got else None
                    clos = self.closure(*got) if got else None
                else:
                    attrs, recv, unres = self._fw_attrs(pkg, fent)
                    found = bool(attrs)
                    rm = pkg.method(recv or "", "Read")
                    clos = self.closure(pkg, rm[:4], (rm[4], "Read")) if rm else None
                    read_ent = rm
                    if clos and attrs:  # model struct fields named by tfsdk tags: autoflex fills them by Go field name
                        best = max(pkg.structs.items(), key=lambda kv: len(set(kv[1]) & set(attrs)), default=None)
                        if best and clos["flatten"] and len(set(best[1]) & set(attrs)) * 2 >= len(attrs):
                            row["api"] = {
                                clean(a): {"expr": "tfsdk:" + clean(g), "api": [clean(g)], "at": ""} for a, g in sorted(best[1].items()) if a in attrs
                            }
                            row["mapping"] = "autoflex-convention"
                row["schema_found"] = found
                row["attributes"] = attrs
                row["file"] = clean(fent[3])
                for v in row["api"].values():
                    if v["expr"].startswith("tfsdk:"):
                        v["at"] = f"{row['file']} (autoflex: model field {v['api'][0]})"
                row["unresolved_keys"] = unres
                row["read_found"] = read_ent is not None
                if clos:
                    row["ops"] = sorted(clean(o) for o in clos["ops"])
                    if reg["kind"] == "sdk":
                        row["mapping"] = "d.Set"
                        for k, fields, expr, at in clos["sets"]:
                            cur = row["api"].setdefault(clean(k), {"expr": expr, "api": [], "at": clean(at)})
                            for f in fields:
                                if clean(f) not in cur["api"]:
                                    cur["api"].append(clean(f))
                out.setdefault(tname, row)
        # The provider framework adds these at runtime from the registry (the tags/tags_all schema) or for every
        # resource (id, region, timeouts are ignored by the comparison), so the dump has them and the source does not.
        for row in out.values():
            if row["has_tags"] and row["schema_found"]:
                row["attributes"].setdefault("tags", [])
                row["attributes"].setdefault("tags_all", ["Computed"])
        return out


def _depth(n: Any) -> int:
    d = 0
    while n.parent is not None:
        n = n.parent
        d += 1
    return d


def _in_return(n: Any) -> bool:
    p = n.parent
    while p is not None and p.type not in ("function_declaration", "func_literal"):
        if p.type == "return_statement":
            return True
        p = p.parent
    return False


def _local_value(scope: Any, src: bytes, name: str) -> Any:
    """The value a local variable is first declared with inside `scope` (`x := ...`, `var x = ...`)."""
    for n in _walk(scope):
        if n.type == "short_var_declaration":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            if left is not None and right is not None and [_txt(c, src) for c in left.named_children] == [name] and right.named_children:
                return right.named_children[0]
        elif n.type == "var_spec":
            nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
            if nm is not None and val is not None and _txt(nm, src) == name and val.named_children:
                return val.named_children[0]
    return None


def read(root: Path) -> dict[str, Any]:
    """Resources of the provider checkout at `root`: schema attribute names, attribute -> API field, read operations."""
    root = Path(root)
    src = _Source(root)
    src.load()
    res = src.resources()
    if not res:
        raise ValueError(f"no resources registered under {root / 'internal' / 'service'}: refusing to score against an empty reference")
    return {
        "commit": commit_of(root),
        "source_sha256": src.h.hexdigest(),
        "files_parsed": src.files,
        "files_with_parse_error": src.parse_errors,
        "resources": res,
    }
