"""Synthetic network, provenance, and failure tests; no customer inputs."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from audit_market import Audit
from trace_graph import GraphAudit, digest, effective_claims, use_input_hash


class GraphChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="market-graph-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "05_校验记录").mkdir()
        self.manifest = self.root / "05_校验记录/state.json"
        self.apa = "Synthetic Agency (2026). Test dataset. https://example.org/test"
        self.statement = "本测试样本销量为10台。"
        self.excerpt = 'Testland residential device sales: 10 units in 2026. "Synthetic only".'
        (self.root / "source.txt").write_text(self.excerpt, encoding="utf-8")
        (self.root / "review.md").write_text("Synthetic review fixture, not a real user approval.", encoding="utf-8")
        self.text = "## Page 1/1｜Synthetic only\n\n### Big conclusion\n\n" + self.statement + "\n\n### Sources\n\n" + self.apa + "\n"
        (self.root / "report.md").write_text(self.text, encoding="utf-8")
        scope = dict(geography="Testland", category="Test device", application="Residential",
                     population="Test households", period="2026", metric="Sales", unit="units",
                     denominator="Test sample", channel="All test channels", data_status="Actual")
        self.m = {
            "schema_version": 1, "project_root": "..", "project": {"name": "Synthetic only"},
            "baseline": {"path": "report.md", "sha256": digest(self.root / "report.md")},
            "pages": [{"id": "P1", "part": "Part1", "heading": "Page 1/1｜Synthetic only",
                       "trace_claim_ids": ["C1"]}],
            "sources": {"S1": {"path": "source.txt", "sha256": digest(self.root / "source.txt"),
                                "apa": self.apa, "review_status": "verified", "audit_basis": "review.md"}},
            "claims": [{"id": "C1", "page": "P1", "kind": "direct", "scope_id": "SC1",
                        "report_quote": self.statement, "display": {"text": "10"}}],
            "trace_graph": {"schema_version": 1, "project_id": "synthetic-only",
                            "scopes": {"SC1": scope},
                            "evidence": {"E1": {"source_id": "S1", "kind": "datum", "quote": self.excerpt,
                                                "locator": "Synthetic table 1", "scope_id": "SC1"}},
                            "locations": {"L1": {"path": "report.md", "page": "P1", "kind": "text",
                                                  "sha256": digest(self.root / "report.md"),
                                                  "selector": "P1/Big conclusion", "quote": self.statement}},
                            "uses": [{"id": "U1", "from": "Evidence:E1", "claim_id": "C1", "location_id": "L1",
                                      "role": "support", "rationale": "Direct citation of the synthetic sample."}]}}
        self.stamp()

    def stamp(self):
        for use in self.m["trace_graph"]["uses"]:
            use["scope_review"] = {"status": "verified", "basis": "review.md: synthetic mapping review",
                                   "input_sha256": use_input_hash(self.m, use)}

    def trace_issues(self):
        self.manifest.write_text(json.dumps(self.m,ensure_ascii=False),encoding="utf-8")
        audit=Audit(self.manifest);audit.trace()
        return [row for row in audit.rows if row["status"]!="PASS"]

    def test_graph_bibliography_accepts_metadata_style_variant(self):
        self.m["sources"]["S1"]["apa"]="Synthetic Agency. (2026). *Test dataset*. https://example.org/test"
        self.m["trace_graph"]["locations"]["LB"]={"path":"report.md","sha256":digest(self.root/"report.md"),
            "page":"P1","kind":"text","selector":"Sources/1","quote":self.apa}
        self.m["trace_graph"]["source_references"]=[{"id":"REF","source_id":"S1","location_id":"LB","purpose":"bibliography"}]
        self.stamp()
        self.assertFalse(any(row["check"]=="apa_in_page" for row in self.trace_issues()))

    def test_missing_direct_reference_remains_failure(self):
        text=self.text.replace(self.apa,"")
        (self.root/"report.md").write_text(text,encoding="utf-8")
        self.m["baseline"]["sha256"]=digest(self.root/"report.md")
        self.m["trace_graph"]["locations"]["L1"]["sha256"]=digest(self.root/"report.md")
        self.stamp()
        self.assertTrue(any(row["check"]=="apa_in_page" for row in self.trace_issues()))

    def test_multifile_extraction_pins_each_input(self):
        extra=self.root/"second.txt";extra.write_text("Second acquired page.",encoding="utf-8")
        self.m["sources"]["S1"]["input_files"]=[{"path":"second.txt","sha256":digest(extra)}]
        self.stamp()
        self.assertFalse(self.issues())
        extra.write_text("Changed second page.",encoding="utf-8")
        self.assertTrue(any(row["check"]=="graph_file_version" for row in self.issues()))

    def coverage_fixture(self):
        graph=self.m["trace_graph"]
        graph["coverage_documents"]=[self.m["baseline"].copy()]
        graph["locations"]["LB"]={"path":"report.md","sha256":digest(self.root/"report.md"),
            "page":"P1","kind":"text","selector":"Sources/1","quote":self.apa}
        graph["source_references"]=[{"id":"REF","source_id":"S1","location_id":"LB",
            "purpose":"bibliography","url_as_cited":"https://example.org/test"}]

    def test_actual_document_coverage_catches_unregistered_citation(self):
        self.coverage_fixture();self.stamp()
        self.assertFalse(self.issues())
        self.m["trace_graph"]["source_references"]=[]
        self.assertTrue(any(row["check"]=="graph_reference_coverage" for row in self.issues()))

    def test_reference_url_must_be_at_its_claimed_location(self):
        self.coverage_fixture()
        self.m["trace_graph"]["locations"]["LB"]["quote"]=self.statement
        self.stamp()
        self.assertTrue(any(row["check"]=="graph_reference_url" for row in self.issues()))

    def test_project_definition_cannot_support_external_numeric_fact(self):
        self.m["sources"]["S1"]["source_type"]="project_definition"
        self.stamp()
        self.assertTrue(any(row["check"]=="graph_internal_source_support" for row in self.issues()))

    def test_project_definition_can_support_explicit_definition(self):
        self.m["sources"]["S1"]["source_type"]="project_definition"
        self.m["claims"][0]["kind"]="definition"
        self.stamp()
        self.assertFalse(self.issues())

    def test_inherited_source_does_not_require_repeated_reference(self):
        self.add_claim()
        q=self.m["claims"][1]["report_quote"]
        text=self.text.replace("Page 1/1","Page 1/2")+"\n## Page 2/2｜Downstream\n\n"+q+"\n"
        (self.root/"report.md").write_text(text,encoding="utf-8")
        self.m["pages"][0].update(heading="Page 1/2｜Synthetic only",trace_claim_ids=["C1"])
        self.m["pages"].append({"id":"P2","part":"Part2","heading":"Page 2/2｜Downstream","trace_claim_ids":["C2"]})
        self.m["claims"][1]["page"]="P2"
        self.m["trace_graph"]["locations"]["L2"]["page"]="P2"
        for loc in self.m["trace_graph"]["locations"].values():loc["sha256"]=digest(self.root/"report.md")
        self.m["baseline"]["sha256"]=digest(self.root/"report.md")
        self.stamp()
        self.assertFalse(any(row["check"]=="apa_in_page" for row in self.trace_issues()))

    def test_audit_only_counterevidence_is_not_a_client_citation(self):
        self.m["sources"]["S2"]={**self.m["sources"]["S1"],"apa":"Other Agency (2026). Not cited by client."}
        self.m["trace_graph"]["evidence"]["E2"]={**self.m["trace_graph"]["evidence"]["E1"],"source_id":"S2"}
        self.m["trace_graph"]["uses"].append({"id":"UC","from":"Evidence:E2","claim_id":"C1","location_id":"L1",
            "role":"contradict","rationale":"Review-only counterevidence.","citation_policy":"audit_only"})
        self.stamp()
        self.assertFalse(any(row["check"]=="apa_in_page" for row in self.trace_issues()))

    def graph(self):
        return GraphAudit(self.m, self.root,require_substantive=False).build()

    def issues(self):
        return [row for row in self.graph().rows if row["status"] != "PASS"]

    def add_claim(self):
        text = "本测试样本记录到设备销量。"
        self.m["claims"].append({"id": "C2", "page": "P1", "kind": "qualitative", "scope_id": "SC1", "report_quote": text})
        self.m["pages"][0]["trace_claim_ids"].append("C2")
        (self.root / "report.md").write_text(self.text.replace("### Sources", "### Supporting\n\n" + text + "\n\n### Sources"), encoding="utf-8")
        self.m["trace_graph"]["locations"]["L2"] = {"path": "report.md", "page": "P1", "kind": "text",
                                                       "selector": "P1/Supporting", "quote": text}
        for location in self.m["trace_graph"]["locations"].values():
            location["sha256"] = digest(self.root / "report.md")
        self.m["baseline"]["sha256"] = digest(self.root / "report.md")
        self.m["trace_graph"]["uses"].append({"id": "U2", "from": "Claim:C1", "claim_id": "C2", "location_id": "L2",
                                                "role": "support", "rationale": "Synthetic upstream fact informs the next judgment."})
        self.stamp()

    def test_complete_network_and_bidirectional_index(self):
        graph = self.graph()
        self.assertFalse(self.issues())
        data = graph.data()
        self.assertEqual({n["type"] for n in data["nodes"]}, {"Source", "Evidence", "Scope", "Claim", "Use", "Location"})
        self.assertTrue(data["incoming"]["Claim:C1"])
        self.assertTrue(data["outgoing"]["Source:S1"])

    def test_downstream_impact_and_source_projection(self):
        self.add_claim()
        graph = self.graph()
        self.assertFalse(self.issues())
        focus = graph.focus("Source:S1")
        self.assertIn("Claim:C2", focus["downstream"])
        self.assertEqual(focus["affected_locations"], ["Location:L1", "Location:L2"])
        self.assertIn("Evidence:E1", graph.focus("Claim:C2")["upstream"])
        projected = effective_claims(self.m)
        self.assertEqual(projected[1]["source_ids"], ["S1"])
        self.assertEqual(projected[1]["source_checks"][0]["token"], self.excerpt)

    def test_same_evidence_and_claim_reused_at_multiple_locations(self):
        (self.root / "report.md").write_text(self.text.replace("### Sources", "### Summary\n\n" + self.statement + "\n\n### Sources"), encoding="utf-8")
        self.m["trace_graph"]["locations"]["L2"] = {**self.m["trace_graph"]["locations"]["L1"], "selector": "P1/Summary"}
        for location in self.m["trace_graph"]["locations"].values():
            location["sha256"] = digest(self.root / "report.md")
        self.m["baseline"]["sha256"] = digest(self.root / "report.md")
        self.m["trace_graph"]["uses"].append({**self.m["trace_graph"]["uses"][0], "id": "U2", "location_id": "L2"})
        self.stamp()
        self.assertFalse(self.issues())
        self.assertEqual(self.graph().focus("Evidence:E1")["affected_locations"], ["Location:L1", "Location:L2"])
        self.assertEqual(len(effective_claims(self.m)[0]["source_checks"]), 1)

    def test_binary_source_extraction_is_bound_to_original_version(self):
        (self.root / "source.pdf").write_bytes(b"Synthetic binary fixture, not a real research paper")
        source = self.m["sources"]["S1"]
        source["path"], source["sha256"] = "source.pdf", digest(self.root / "source.pdf")
        source["extraction"] = {"path": "source.txt", "sha256": digest(self.root / "source.txt"), "original_sha256": source["sha256"]}
        self.stamp()
        self.assertFalse(self.issues())
        source["extraction"]["original_sha256"] = "incorrect"
        self.stamp()
        self.assertIn("graph_source_extract", {r["check"] for r in self.issues()})

    def test_context_and_contradiction_do_not_supply_support(self):
        for role in ("context", "contradict"):
            self.m["trace_graph"]["uses"][0]["role"] = role
            self.stamp()
            self.assertIn("graph_support_path", {r["check"] for r in self.issues()})

    def test_source_or_scope_reference_missing(self):
        self.m["trace_graph"]["evidence"]["E1"]["source_id"] = "missing"
        self.assertIn("graph_evidence_source", {r["check"] for r in self.issues()})
        self.m["trace_graph"]["evidence"]["E1"]["scope_id"] = "missing"
        self.assertIn("graph_evidence_scope", {r["check"] for r in self.issues()})

    def test_scope_missing_denominator_remains_not_checked(self):
        del self.m["trace_graph"]["scopes"]["SC1"]["denominator"]
        self.stamp()
        self.assertTrue(any(r["check"] == "graph_scope_fields" and r["status"] == "NOT_CHECKED" for r in self.issues()))

    def test_scope_change_invalidates_old_review(self):
        self.m["trace_graph"]["scopes"]["SC1"]["application"] = "Commercial"
        self.assertIn("graph_scope_review", {r["check"] for r in self.issues()})

    def test_scope_difference_is_visible_even_when_reviewed(self):
        self.m["trace_graph"]["scopes"]["SC2"] = {**self.m["trace_graph"]["scopes"]["SC1"], "geography": "Subset"}
        self.m["claims"][0]["scope_id"] = "SC2"
        self.stamp()
        rows = [r for r in self.graph().rows if r["check"] == "graph_scope_review"]
        self.assertEqual(rows[0]["status"], "PASS")
        self.assertIn('"geography": ["Testland", "Subset"]', rows[0]["detail"])

    def test_source_and_location_hash_drift(self):
        (self.root / "source.txt").write_text(self.excerpt + " changed", encoding="utf-8")
        self.assertIn("graph_file_version", {r["check"] for r in self.issues()})
        (self.root / "report.md").write_text("Replaced", encoding="utf-8")
        self.assertTrue(any(r["check"] == "graph_file_version" and r["detail"] == "L1" for r in self.issues()))

    def test_unrelated_container_edit_preserves_unchanged_citation_review(self):
        old = self.m["trace_graph"]["uses"][0]["scope_review"]["input_sha256"]
        (self.root / "report.md").write_text(self.text + "\nUnrelated formatting note.\n", encoding="utf-8")
        self.m["trace_graph"]["locations"]["L1"]["sha256"] = digest(self.root / "report.md")
        self.m["baseline"]["sha256"] = digest(self.root / "report.md")
        self.assertEqual(old, use_input_hash(self.m, self.m["trace_graph"]["uses"][0]))
        self.assertFalse(self.issues())

    def test_unread_p0_source_does_not_pass(self):
        self.m["sources"]["S1"].pop("path")
        self.m["sources"]["S1"]["review_status"] = "blocked"
        self.stamp()
        self.assertIn("graph_file_pin", {r["check"] for r in self.issues()})
        self.assertIn("graph_source_review", {r["check"] for r in self.issues()})

    def test_circular_conclusion_support_fails(self):
        self.add_claim()
        self.m["trace_graph"]["uses"].append({"id": "U3", "from": "Claim:C2", "claim_id": "C1", "location_id": "L1",
                                                "role": "support", "rationale": "Invalid circular test."})
        self.stamp()
        self.assertIn("graph_support_cycle", {r["check"] for r in self.issues()})

    def test_duplicate_use_id_fails(self):
        self.m["trace_graph"]["uses"].append(copy.deepcopy(self.m["trace_graph"]["uses"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate node"):
            self.graph()

    def test_blank_rationale_and_review_basis_do_not_pass(self):
        self.m["trace_graph"]["uses"][0]["rationale"] = "  "
        self.stamp()
        self.m["trace_graph"]["uses"][0]["scope_review"]["basis"] = "  "
        self.assertIn("graph_use_role", {r["check"] for r in self.issues()})
        self.assertIn("graph_scope_review", {r["check"] for r in self.issues()})

    def test_legacy_mismatch_is_not_hidden_by_projection(self):
        self.m["claims"][0]["source_ids"] = ["wrong"]
        self.assertIn("graph_legacy_projection", {r["check"] for r in self.issues()})

    def test_graph_hooks_into_existing_trace_without_duplicate_quotes(self):
        from test_source_review import add_test_grounding
        add_test_grounding(self.m,self.root)
        self.stamp()
        self.manifest.write_text(json.dumps(self.m), encoding="utf-8")
        audit = Audit(self.manifest)
        audit.trace()
        self.assertFalse([r for r in audit.rows if r["status"] != "PASS"], audit.rows)
        self.m["trace_graph"]["uses"][0]["scope_review"]["input_sha256"] = "stale"
        self.manifest.write_text(json.dumps(self.m), encoding="utf-8")
        audit = Audit(self.manifest)
        audit.trace()
        self.assertTrue(any(r["check"] == "graph_scope_review" and r["status"] != "PASS" for r in audit.rows))

    def test_legacy_manifest_does_not_claim_graph_coverage(self):
        del self.m["trace_graph"]
        self.assertIn("graph_registered", {r["check"] for r in self.issues()})

    def test_path_escape_rejected(self):
        self.m["trace_graph"]["locations"]["L1"]["path"] = "../outside.txt"
        self.assertIn("graph_file", {r["check"] for r in self.issues()})

    def test_document_aliases_expand_source_impact(self):
        self.m["sources"]["S1"]["same_document_group"] = "same-original-version"
        self.m["sources"]["S2"] = {**self.m["sources"]["S1"]}
        self.stamp()
        self.assertIn("Claim:C1", self.graph().focus("Source:S2")["downstream"])

    def test_bibliographic_reference_does_not_create_support(self):
        self.m["sources"]["S2"] = {**self.m["sources"]["S1"], "path": None, "sha256": None, "review_status": "not_acquired"}
        self.m["trace_graph"]["locations"]["L2"] = {**self.m["trace_graph"]["locations"]["L1"], "selector": "P1/Sources", "quote": self.apa}
        self.m["trace_graph"]["source_references"] = [{"id": "REF1", "source_id": "S2", "location_id": "L2", "purpose": "bibliography"}]
        self.assertFalse(self.issues())
        focus = self.graph().focus("Source:S2")
        self.assertIn("Location:L2", focus["affected_locations"])
        self.assertNotIn("Claim:C1", focus["downstream"])

    def test_unresolved_bibliography_binding_remains_visible(self):
        self.m["trace_graph"]["source_references"] = [{"id": "REF1", "source_id": "S1", "location_id": "L1", "purpose": "unresolved_binding"}]
        self.assertIn("graph_reference_binding", {r["check"] for r in self.issues()})

    def test_real_markdown_sections_cover_summary_and_appendix(self):
        (self.root / "full.md").write_text("# Report\n\n## Executive Summary\n\nSummary finding.\n\n## Annex\n\nAnnex finding.\n", encoding="utf-8")
        self.m["trace_graph"]["units"] = {"ES": {"kind": "summary"}}
        self.m["claims"].append({"id": "C2", "kind": "qualitative", "page": "ES", "scope_id": "SC1", "report_quote": "Summary finding."})
        self.m["trace_graph"]["locations"]["L2"] = {"path": "full.md", "sha256": digest(self.root / "full.md"), "page": "ES", "section_heading": "Executive Summary", "selector": "Executive Summary/paragraph", "kind": "text", "quote": "Summary finding."}
        self.m["trace_graph"]["uses"].append({"id": "U2", "from": "Claim:C1", "claim_id": "C2", "location_id": "L2", "role": "support", "rationale": "Synthetic summary derives from main text."})
        self.stamp()
        self.assertFalse(self.issues())
        self.m["trace_graph"]["locations"]["L2"]["section_heading"] = "Annex"
        self.assertIn("graph_location_page", {r["check"] for r in self.issues()})

    def test_registered_header_can_be_a_citation_location(self):
        self.m["trace_graph"]["locations"]["L1"]["quote"] = "Page 1/1｜Synthetic only"
        self.stamp()
        self.assertFalse(self.issues())

    def test_text_source_can_use_hash_bound_extraction(self):
        (self.root / "raw.html").write_text("<p>Raw source rendering fixture</p>", encoding="utf-8")
        source = self.m["sources"]["S1"]
        source["path"], source["sha256"] = "raw.html", digest(self.root / "raw.html")
        source["extraction"] = {"path": "source.txt", "sha256": digest(self.root / "source.txt"), "original_sha256": source["sha256"]}
        self.stamp()
        self.assertFalse(self.issues())

    def test_explicitly_rejected_review_is_a_failure(self):
        self.m["trace_graph"]["uses"][0]["scope_review"]["status"] = "rejected"
        self.assertTrue(any(r["check"] == "graph_scope_review" and r["status"] == "FAIL" for r in self.issues()))

    def test_quote_present_on_wrong_page_is_not_a_valid_location(self):
        self.m["trace_graph"]["locations"]["L1"]["page"] = "P2"
        self.assertIn("graph_location_page", {r["check"] for r in self.issues()})

    def test_cli_outputs_and_refuses_overwrite_without_changing_inputs(self):
        self.manifest.write_text(json.dumps(self.m, ensure_ascii=False), encoding="utf-8")
        before = {p: digest(p) for p in (self.manifest, self.root / "report.md", self.root / "source.txt")}
        cmd = [sys.executable, "-X", "utf8", str(Path(__file__).with_name("trace_graph.py")),
               "--manifest", str(self.manifest), "--out", str(self.root / "out"), "--focus", "Source:S1", "--structural-only"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / "out/graph-review.json").read_text(encoding="utf-8"))
        self.assertEqual(report["result"],"STRUCTURE_ONLY")
        self.assertIn("Claim:C1", report["focus"]["downstream"])
        ttl = (self.root / "out/graph.ttl").read_text(encoding="utf-8")
        self.assertIn('ma:hasEvidence', ttl)
        self.assertIn('\\"Synthetic only\\"', ttl)
        repeated = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(before, {p: digest(p) for p in before})


if __name__ == "__main__":
    unittest.main()
