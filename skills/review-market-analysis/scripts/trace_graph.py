"""Build a local evidence network and Turtle view from the existing manifest.

Standard library only. Reads inputs; writes new graph/audit outputs, never a manifest.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote


SCOPE_FIELDS = ("geography", "category", "application", "population", "period",
                "metric", "unit", "denominator", "channel", "data_status")
TEXT_SUFFIXES = {".txt", ".md", ".json", ".xml", ".html", ".csv", ".ttl"}
LIMITS = "核对登记网络、原文锚点、逐字段适配记录及版本；agent必须实际读原文并完成含义与推导审查。记录完整不等于自动证明来源可信或推导正确。"


def filled(value):
    return isinstance(value, str) and bool(value.strip())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def contains(path, token):
    target = re.sub(r"\s+", "", token)
    if not target:
        return False
    tail = ""
    with Path(path).open(encoding="utf-8-sig") as stream:
        for block in iter(lambda: stream.read(65536), ""):
            text = tail + re.sub(r"\s+", "", block)
            if target in text:
                return True
            tail = text[-max(len(target) - 1, 0):] if len(target) > 1 else ""
    return False


def evidence_for_claim(manifest, claim_id):
    graph = manifest.get("trace_graph") or {}
    uses = defaultdict(list)
    for use in graph.get("uses", []):
        uses[use["claim_id"]].append(use["from"])
    found, seen, stack = set(), set(), ["Claim:" + claim_id]
    while stack:
        ref = stack.pop()
        if ref in seen:
            continue
        seen.add(ref)
        kind, key = ref.split(":", 1)
        if kind == "Evidence":
            found.add(key)
        elif kind == "Claim":
            stack.extend(uses.get(key, []))
    return [graph["evidence"][key] for key in sorted(found) if key in graph.get("evidence", {})]


def effective_claims(manifest):
    if "trace_graph" not in manifest:
        return manifest.get("claims", [])
    result = []
    for claim in manifest.get("claims", []):
        evidence = evidence_for_claim(manifest, claim["id"])
        pairs = sorted({(e["source_id"], e["quote"]) for e in evidence})
        result.append({**claim, "source_ids": sorted({sid for sid, _ in pairs}),
                       "source_checks": [{"source_id": sid, "token": token} for sid, token in pairs]})
    return result


def use_input_hash(manifest, use):
    graph = manifest["trace_graph"]
    kind, key = use["from"].split(":", 1)
    claims = {c["id"]: c for c in manifest.get("claims", [])}
    origin = graph["evidence"].get(key, {}) if kind == "Evidence" else claims.get(key, {})
    target = claims.get(use["claim_id"], {})
    meaning = lambda c: {k: c[k] for k in ("id", "kind", "scope_id", "report_quote", "excel", "calculation", "display") if k in c}
    location = graph["locations"].get(use["location_id"], {})
    # Container edits elsewhere must not reopen an unchanged text citation's semantic review.
    if location.get("kind") in {"text", "external_snapshot"} and location.get("quote"):
        location = {"kind": location["kind"], "quote": location["quote"]}
    values = {"origin": origin if kind == "Evidence" else meaning(origin), "origin_scope": graph["scopes"].get(origin.get("scope_id")),
              "source": manifest.get("sources", {}).get(origin.get("source_id")),
              "target": meaning(target), "target_scope": graph["scopes"].get(target.get("scope_id")),
              "location": location,
              "role": use.get("role"), "rationale": use.get("rationale")}
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


class GraphAudit:
    def __init__(self, manifest, root, require_substantive=True, substantive_pages=None):
        self.m, self.root = manifest, Path(root).resolve()
        self.g = manifest.get("trace_graph") or {}
        self.nodes, self.edges, self.rows = {}, [], []
        self.influence = defaultdict(set)
        self.hashes, self.documents = {}, {}
        self.require_substantive = require_substantive
        self.substantive_pages = substantive_pages

    def check(self, code, ok, detail, unknown=False):
        self.rows.append({"check": "graph_" + code,
                          "status": "PASS" if ok else ("NOT_CHECKED" if unknown else "FAIL"),
                          "detail": detail})
        return ok

    def node(self, kind, key, record):
        if not filled(key):
            raise ValueError("non-empty node ID required: " + kind)
        ref = kind + ":" + key
        if ref in self.nodes:
            raise ValueError("duplicate node: " + ref)
        self.nodes[ref] = {"id": ref, "type": kind, "key": key, "attributes": record}
        return ref

    def edge(self, start, relation, end):
        self.edges.append({"from": start, "relation": relation, "to": end})

    def path(self, relative):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("project-relative path required")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("artifact outside project: " + relative)
        return path

    def file(self, record, label, token=None):
        if not filled(record.get("path")) or not filled(record.get("sha256")):
            self.check("file_pin", False, label + " 缺本地路径或版本哈希", unknown=True)
            return
        try:
            path = self.path(record["path"])
            if path not in self.hashes:
                self.hashes[path] = digest(path)
            pinned = self.check("file_version", self.hashes[path] == record["sha256"].lower(), label)
            for item in record.get("input_files", []):
                self.file(item, label + " 提取输入")
            if token is not None and pinned:
                if record.get("extraction") or path.suffix.lower() not in TEXT_SUFFIXES:
                    extraction = record.get("extraction", {})
                    if extraction.get("original_sha256") != self.hashes[path]:
                        self.check("source_extract", False, label + " 缺绑定原文版本的文本提取", unknown=True)
                        return
                    self.file(extraction, label + " 提取文本", token)
                else:
                    self.check("quote", contains(path, token), label + " 定位摘录")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            self.check("file", False, label + ": " + str(exc))

    def build(self):
        sources = self.m.get("sources", {})
        claims = self.m.get("claims", [])
        for sid, source in sources.items():
            self.node("Source", sid, source)
        for claim in claims:
            self.node("Claim", claim["id"], claim)
        if not self.g:
            self.check("registered", False, "尚无 trace_graph；未自动补造证据、口径或引用关系", unknown=True)
            return self
        if self.g.get("schema_version") != 1:
            raise ValueError("unsupported trace_graph schema")
        for name in ("scopes", "evidence", "locations"):
            if not isinstance(self.g.get(name), dict):
                raise ValueError("trace_graph." + name + " must be an object")
        if not isinstance(self.g.get("uses"), list):
            raise ValueError("trace_graph.uses must be an array")
        units = self.g.get("units", {})
        references = self.g.get("source_references", [])
        if not isinstance(units, dict) or not isinstance(references, list):
            raise ValueError("trace_graph.units must be an object; source_references must be an array")
        self.check("unit_ids", not (set(units) & {p["id"] for p in self.m.get("pages", [])}), "补充单元不得覆盖正式页 ID")
        # shortcut: bounded local proposal graphs; use disk-backed traversal for larger collections.
        if sum(len(self.g[k]) for k in ("scopes", "evidence", "locations", "uses")) + len(units) + len(references) > 20000:
            raise ValueError("graph exceeds bounded local limit (20000 records)")
        self.check("project_id", filled(self.g.get("project_id")), "图谱需固定项目 ID")
        self.check("claims", bool(claims), "至少登记一个结论；空模板尚不可核验", unknown=True)
        scopes, evidence, locations = (self.g[k] for k in ("scopes", "evidence", "locations"))
        claim_map = {c["id"]: c for c in claims}
        groups = defaultdict(list)
        for sid, source in sources.items():
            if source.get("same_document_group"):
                groups[source["same_document_group"]].append(sid)
        for members in groups.values():
            anchor = sorted(members)[0]
            for sid in sorted(members):
                if sid == anchor:
                    continue
                for left, right in [(sid, anchor), (anchor, sid)]:
                    self.edge("Source:" + left, "sameDocumentAs", "Source:" + right)
                    self.influence["Source:" + left].add("Source:" + right)
        for key, scope in scopes.items():
            self.node("Scope", key, scope)
            missing = [f for f in SCOPE_FIELDS if not isinstance(scope.get(f), str) or not scope[f].strip()]
            self.check("scope_fields", not missing, key + " 缺项: " + ", ".join(missing), unknown=True)
        for eid, item in evidence.items():
            ref = self.node("Evidence", eid, item)
            sid, scid = item.get("source_id"), item.get("scope_id")
            self.check("evidence_fields", item.get("kind") in {"datum", "source_conclusion"}
                       and filled(item.get("quote")) and filled(item.get("locator")), eid + " 原文摘录、位置及类型")
            if self.check("evidence_source", sid in sources, eid + " → " + str(sid)):
                self.edge("Source:" + sid, "hasEvidence", ref)
                self.influence["Source:" + sid].add(ref)
                self.file(sources[sid], eid, item.get("quote", ""))
                self.check("source_review", sources[sid].get("review_status") == "verified"
                           and filled(sources[sid].get("audit_basis")), sid + " 原文审查", unknown=True)
            if self.check("evidence_scope", scid in scopes, eid + " → " + str(scid)):
                self.edge(ref, "hasScope", "Scope:" + scid)
                self.influence["Scope:" + scid].add(ref)
        for cid, claim in claim_map.items():
            self.check("claim_fields", filled(claim.get("report_quote")) and claim.get("page") in ({p["id"] for p in self.m.get("pages", [])} | set(units)), cid + " 结论原句及主引用单元")
            scid = claim.get("scope_id")
            if self.check("claim_scope", scid in scopes, cid + " → " + str(scid)):
                self.edge("Claim:" + cid, "hasScope", "Scope:" + scid)
                self.influence["Scope:" + scid].add("Claim:" + cid)
        for lid, location in locations.items():
            self.node("Location", lid, location)
            self.check("location_fields", filled(location.get("selector")) and filled(location.get("page"))
                       and location.get("kind") in {"text", "visual", "workbook", "external_snapshot"}, lid)
            text_location = location.get("kind") in {"text", "external_snapshot"}
            self.check("location_quote", not text_location or filled(location.get("quote")), lid)
            self.file(location, lid)
            if text_location:
                try:
                    from audit_market import document, normalize
                    path = self.path(location["path"])
                    if path not in self.documents:
                        self.documents[path] = document(path)
                    doc = self.documents[path]
                    pid = location.get("page")
                    if location.get("section_heading"):
                        headings = list(re.finditer(r"^(#{1,6})\s+([^\n]+)", doc["text"], re.M))
                        matches = [h for h in headings if normalize(h[2]) == normalize(location["section_heading"])]
                        if len(matches) != 1:
                            raise ValueError("section heading missing or ambiguous: " + location["section_heading"])
                        start = matches[0]
                        end = next((h.start() for h in headings if h.start() > start.start() and len(h[1]) <= len(start[1])), len(doc["text"]))
                        body = doc["text"][start.start():end]
                    else:
                        page = doc["pages"].get(pid, {})
                        body = doc["intro"] if pid == "Summary" else page.get("heading", "") + "\n" + page.get("body", "")
                    token = location.get("quote", "")
                    self.check("location_page", filled(token) and normalize(token) in normalize(body), lid + " → " + str(pid))
                except (OSError, ValueError, KeyError, UnicodeError) as exc:
                    self.check("location_page", False, lid + ": " + str(exc), unknown=True)
        reference_locations = set()
        for reference in references:
            ref = self.node("Reference", reference["id"], reference)
            sid, lid = reference.get("source_id"), reference.get("location_id")
            valid = self.check("reference_refs", sid in sources and lid in locations and filled(reference.get("purpose")), reference["id"])
            if not valid:
                continue
            self.edge("Source:" + sid, "listedBy", ref)
            self.edge(ref, "atLocation", "Location:" + lid)
            self.influence["Source:" + sid].add(ref)
            self.influence[ref].add("Location:" + lid)
            reference_locations.add(lid)
            if reference.get("purpose") == "unresolved_binding":
                self.check("reference_binding", False, reference["id"] + " 仅见引用，尚无已确认的证据用途", unknown=True)
        support = defaultdict(set)
        rooted, used_evidence, used_locations = set(), set(), set()
        for use in self.g["uses"]:
            uid = use["id"]
            uref = self.node("Use", uid, use)
            start, cid, lid = use.get("from"), use.get("claim_id"), use.get("location_id")
            valid = self.check("use_refs", start in self.nodes and start.split(":", 1)[0] in {"Evidence", "Claim"}
                               and cid in claim_map and lid in locations, uid)
            self.check("use_role", use.get("role") in {"support", "contradict", "context"}
                       and filled(use.get("rationale")), uid + " 角色及推导理由")
            if not valid:
                continue
            review = use.get("scope_review", {})
            fingerprint = use_input_hash(self.m, use)
            origin = self.nodes[start]["attributes"]
            old_scope, new_scope = scopes.get(origin.get("scope_id"), {}), scopes.get(claim_map[cid].get("scope_id"), {})
            differences = {f: [old_scope.get(f), new_scope.get(f)] for f in set(old_scope) | set(new_scope) if old_scope.get(f) != new_scope.get(f)}
            self.check("scope_review", review.get("status") == "verified" and filled(review.get("basis"))
                       and review.get("input_sha256") == fingerprint,
                       uid + " scope differences=" + json.dumps(differences, ensure_ascii=False, sort_keys=True)
                       + "; expected_input_sha256=" + fingerprint,
                       unknown=review.get("status") not in {"rejected", "failed"})
            target = "Claim:" + cid
            is_evidence = start.startswith("Evidence:")
            if is_evidence and use.get("role") == "support":
                source = sources.get(origin.get("source_id"), {})
                if source.get("source_type") == "project_definition":
                    self.check("internal_source_support", claim_map[cid].get("kind") in {"definition", "method", "recommendation"},
                               uid + " 项目定义不能支撑外部市场事实或数值")
            self.edge(start, "citedBy" if is_evidence else "usedBy", uref)
            self.edge(uref, "atLocation", "Location:" + lid)
            self.edge(uref, "contributesTo", target)
            self.edge("Location:" + lid, "expresses", target)
            self.influence[start].add(uref)
            self.influence[uref].add(target)
            used_locations.add(lid)
            if is_evidence:
                used_evidence.add(start.split(":", 1)[1])
            if use.get("role") == "support":
                self.edge(target, "wasDerivedFrom", start)
                if is_evidence:
                    rooted.add(cid)
                else:
                    support[start.split(":", 1)[1]].add(cid)
        indegree = {cid: 0 for cid in claim_map}
        for children in support.values():
            for cid in children:
                indegree[cid] += 1
        ready = deque(cid for cid, n in indegree.items() if n == 0)
        visited = 0
        while ready:
            cid = ready.popleft()
            visited += 1
            for child in support[cid]:
                if cid in rooted:
                    rooted.add(child)
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        self.check("support_cycle", visited == len(claim_map), "结论支持关系不得循环")
        for cid in claim_map:
            self.check("support_path", cid in rooted, cid + " 必须存在回到 Evidence 的支持路径")
            self.check("primary_location", any(u.get("claim_id") == cid and locations.get(u.get("location_id"), {}).get("page") == claim_map[cid].get("page") for u in self.g["uses"]), cid + " 主引用单元须有实际采用位置")
        self.check("unused_evidence", used_evidence == set(evidence), "未使用证据: " + ", ".join(sorted(set(evidence) - used_evidence)), unknown=True)
        self.check("unused_locations", used_locations | reference_locations == set(locations), "未连接地点: " + ", ".join(sorted(set(locations) - used_locations - reference_locations)), unknown=True)
        if "coverage_documents" in self.g:
            documents = self.g["coverage_documents"]
            if not isinstance(documents, list) or len(documents) > 50:
                raise ValueError("coverage_documents must be a bounded list of file pins")
            self.check("coverage_documents", bool(documents), "完整引用核对须登记实际稿件", unknown=True)
            for record in documents:
                self.file(record, "引用覆盖稿件")
                path = self.path(record["path"])
                if path.suffix.lower() not in {".md", ".txt"}:
                    self.check("reference_coverage", False, record["path"] + " 尚未支持直接链接盘点，需保留语义的转换及等价核对", unknown=True)
                    continue
                actual = Counter()
                with path.open(encoding="utf-8-sig") as stream:
                    for line in stream:
                        actual.update(url.rstrip(".,;。") for url in re.findall(r"https?://[^\s<>\)]+", line))
                        if sum(actual.values()) > 20000:
                            raise ValueError("citation coverage exceeds 20000 links")
                registered = Counter()
                for reference in references:
                    location = locations.get(reference.get("location_id"), {})
                    if location.get("path") != record["path"]:
                        continue
                    url = reference.get("url_as_cited", "")
                    self.check("reference_url", filled(url) and url in location.get("quote", ""), reference["id"] + " 原样URL须出现在引用位置")
                    if url:
                        registered[url.rstrip(".,;。")] += 1
                self.check("reference_coverage", actual == registered,
                    record["path"] + "; missing=" + json.dumps(dict(actual - registered), ensure_ascii=False)
                    + "; extra=" + json.dumps(dict(registered - actual), ensure_ascii=False))
        for original, projected in zip(claims, effective_claims(self.m)):
            for field in ("source_ids", "source_checks"):
                if field in original:
                    a = original[field]
                    b = projected[field]
                    if field == "source_checks":
                        a = {(v.get("source_id"), v.get("token")) for v in a}
                        b = {(v["source_id"], v["token"]) for v in b}
                    else:
                        a, b = set(a), set(b)
                    self.check("legacy_projection", a == b, original["id"] + " " + field)
        if self.require_substantive:
            from source_review import SubstanceAudit, use_review_key
            selected=None if self.substantive_pages is None else {c["id"] for c in claims if c["page"] in self.substantive_pages}
            self.rows.extend(SubstanceAudit(self.m,self.root,claim_ids=selected).build().rows)
            grounding=self.g.get("source_grounding",{})
            for eid,review in grounding.get("evidence_reviews",{}).items():
                if eid in evidence:
                    ref=self.node("SourceReview",eid,review)
                    self.edge("Evidence:"+eid,"hasSourceReview",ref)
                    self.edge(ref,"readFrom","Source:"+evidence[eid]["source_id"])
            for key,review in grounding.get("use_reviews",{}).items():
                self.node("UseReview",key,review)
            for use in self.g["uses"]:
                if use.get("claim_id") not in claim_map:continue
                try:key=use_review_key(self.m,use)
                except KeyError:continue
                if key in grounding.get("use_reviews",{}):
                    self.edge("Use:"+use["id"],"hasUseReview","UseReview:"+key)
                    if use.get("from","").startswith("Evidence:"):
                        eid=use["from"].split(":",1)[1]
                        if eid in grounding.get("evidence_reviews",{}):self.edge("UseReview:"+key,"basedOnReview","SourceReview:"+eid)
        return self

    def focus(self, ref):
        if ref not in self.nodes:
            raise ValueError("unknown focus node: " + ref)
        reverse = defaultdict(set)
        for start, ends in self.influence.items():
            for end in ends:
                reverse[end].add(start)
        def walk(edges):
            found, stack = set(), [ref]
            while stack:
                node = stack.pop()
                if node in found:
                    continue
                found.add(node)
                stack.extend(edges.get(node, []))
            return found
        downstream = walk(self.influence)
        affected = {n.split(":", 1)[1] for n in downstream if n.startswith("Claim:")}
        locs = {u["location_id"] for u in self.g.get("uses", []) if u.get("claim_id") in affected}
        locs |= {node.split(":", 1)[1] for node in downstream if node.startswith("Location:")}
        return {"node": ref, "upstream": sorted(walk(reverse) - {ref}),
                "downstream": sorted(downstream - {ref}),
                "affected_locations": sorted("Location:" + lid for lid in locs)}

    def data(self):
        incoming, outgoing = defaultdict(list), defaultdict(list)
        for edge in self.edges:
            outgoing[edge["from"]].append(edge)
            incoming[edge["to"]].append(edge)
        return {"project_id": self.g.get("project_id"), "nodes": list(self.nodes.values()),
                "edges": self.edges, "incoming": dict(incoming), "outgoing": dict(outgoing)}

    def turtle(self):
        prefix = "urn:market-analysis:" + quote(str(self.g.get("project_id") or "unregistered"), safe="") + ":"
        iri = lambda ref: "<" + prefix + quote(ref, safe="") + ">"
        literal = lambda value: json.dumps(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True), ensure_ascii=False)
        lines = ['@prefix ma: <urn:market-analysis:ontology:> .',
                 '@prefix prov: <http://www.w3.org/ns/prov#> .', ""]
        for ref, node in sorted(self.nodes.items()):
            lines.append(iri(ref) + " a ma:" + node["type"] + " .")
            for key, value in sorted(node["attributes"].items()):
                predicate = "<urn:market-analysis:ontology:" + quote(key, safe="") + ">"
                lines.append(iri(ref) + " " + predicate + " " + literal(value) + " .")
        for edge in self.edges:
            predicate = ("prov:" if edge["relation"] == "wasDerivedFrom" else "ma:") + edge["relation"]
            lines.append(iri(edge["from"]) + " " + predicate + " " + iri(edge["to"]) + " .")
        return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--focus", help="Typed ID, e.g. Source:S1 or Claim:C1")
    parser.add_argument("--structural-only", action="store_true", help="仅诊断结构；结果不构成提交/发布放行")
    args = parser.parse_args()
    manifest_path = Path(args.manifest).resolve()
    if manifest_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("manifest exceeds 16 MiB bounded local limit")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != 1 or manifest_path.parent.name != "05_校验记录" or manifest.get("project_root") != "..":
        raise ValueError("expected project/05_校验记录 manifest, schema v1, project_root '..'")
    graph = GraphAudit(manifest, manifest_path.parent.parent,require_substantive=not args.structural_only).build()
    focus = graph.focus(args.focus) if args.focus else None
    out = Path(args.out).resolve()
    names = ["graph.json", "graph.ttl", "graph-review.json", "graph-review.md"]
    protected = {manifest_path}
    def paths(value):
        if isinstance(value, dict):
            if value.get("path"):
                protected.add(graph.path(value["path"]))
            for child in value.values():
                paths(child)
        elif isinstance(value, list):
            for child in value:
                paths(child)
    paths(manifest)
    if any((out / name).exists() or (out / name) in protected for name in names):
        raise ValueError("output would overwrite an existing file; use a new audit directory")
    issues = [r for r in graph.rows if r["status"] != "PASS"]
    report = {"result": "NEEDS_REVIEW" if issues else ("STRUCTURE_ONLY" if args.structural_only else "SOURCE_REVIEW_COMPLETE"), "limits": LIMITS,
              "substantive_review_required": not args.structural_only,
              "manifest_sha256": digest(manifest_path), "checks": graph.rows, "focus": focus}
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(graph.data(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "graph.ttl").write_text(graph.turtle(), encoding="utf-8")
    (out / "graph-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 证据图谱检查", "", report["result"], "", LIMITS, ""]
    for row in issues:
        lines.append("- " + row["status"] + " " + row["check"] + ": " + row["detail"])
    if focus:
        lines.extend(["", "## 节点影响范围", "", "```json", json.dumps(focus, ensure_ascii=False, indent=2), "```"])
    (out / "graph-review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "nodes": len(graph.nodes), "edges": len(graph.edges), "issues": len(issues)}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("graph execution failed: " + str(exc), file=sys.stderr)
        sys.exit(2)
