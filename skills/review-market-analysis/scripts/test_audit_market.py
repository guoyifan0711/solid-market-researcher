"""Synthetic forward tests; never reads or changes a client project."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from audit_market import Audit, arithmetic, digest, document, text_digest
from render_state import render


def workbook(path, value="0.5", formula="A2/A1-1"):
    # Minimal OOXML fixture, not a client deliverable or an authoring recommendation.
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Build" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{relns}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1" t="n"><v>10</v></c><c r="B1"><f>{formula}</f><v>{value}</v></c></row><row r="2"><c r="A2" t="n"><v>15</v></c></row></sheetData></worksheet>')


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="market-audit-test-")
        self.root = Path(self.temp.name)
        (self.root / "05_校验记录").mkdir()
        self.manifest = self.root / "05_校验记录/state.json"
        self.source = "Agency (2026). Dataset. https://example.org/data"
        self.text = "# Synthetic report\n\n## Page 1/1｜Revenue expanded\n\n### Big conclusion\n\nRevenue grew 50.0%.\n\n### Supporting evidence\n\nStarting revenue 10; ending revenue 15.\n\n### Sources\n\n" + self.source + "\n"
        (self.root / "report.md").write_text(self.text, encoding="utf-8")
        (self.root / "source.txt").write_text("Starting revenue 10; ending revenue 15.", encoding="utf-8")
        (self.root / "review.md").write_text("Synthetic fixture only; reviewed mapping and meaning.", encoding="utf-8")
        workbook(self.root / "book.xlsx")
        page = document(self.root / "report.md")["pages"]["P1"]
        page_hash = text_digest(page["heading"] + page["body"])
        cell = lambda c, v: {"path": "book.xlsx", "sheet": "Build", "cell": c, "expected_value": v}
        self.m = {"schema_version": 1, "project_root": "..", "project": {"name": "Synthetic only"},
                  "baseline": {"path": "report.md", "sha256": digest(self.root / "report.md"), "approval": {"status": "confirmed", "basis": "Synthetic user approval"}},
                  "pages": [{"id": "P1", "part": "Part1", "heading": page["heading"], "excel": [{"path": "book.xlsx", "sha256": digest(self.root / "book.xlsx")}], "visuals": {"status": "not_applicable", "basis": "Text-only test", "files": []}, "audits": ["review.md"], "confirmation": {"status": "confirmed", "basis": "Synthetic user approval", "text_sha256": page_hash}, "trace_coverage": "complete", "trace_claim_ids": ["C1"], "semantic_review": {"status": "verified", "basis": "review.md", "text_sha256": page_hash}}],
                  "sources": {"S1": {"path": "source.txt", "sha256": digest(self.root / "source.txt"), "apa": self.source, "review_status": "verified", "audit_basis": "review.md"}},
                  "claims": [{"id": "C1", "page": "P1", "source_ids": ["S1"], "report_quote": "Revenue grew 50.0%.", "display": {"text": "50.0%", "scale": 100, "decimals": 1}, "excel": {**cell("B1", .5), "expected_formula": "=A2/A1-1"}, "calculation": {"expression": "end/start-1", "inputs": {"start": cell("A1", 10), "end": cell("A2", 15)}}, "source_checks": [{"source_id": "S1", "token": "Starting revenue 10; ending revenue 15."}]}],
                  "publication": {"target": "https://example.org/publish", "authorization": {"target": "https://example.org/publish", "status": "granted", "basis": "Synthetic explicit request", "candidate_sha256": digest(self.root / "report.md"), "baseline_sha256": digest(self.root / "report.md"), "pages": ["P1"]}}}

    def tearDown(self): self.temp.cleanup()

    def run_audit(self, mode="release", candidate=None):
        f = self.manifest
        f.write_text(json.dumps(self.m), encoding="utf-8")
        audit = Audit(f)
        try:
            if mode in {"release", "compare"}: getattr(audit, mode)(candidate or self.root / "report.md")
            else: getattr(audit, mode)()
        except Exception as e: audit.check("execution_error", False, str(e))
        return audit

    def test_changed_publish_target(self):
        self.m["publication"]["target"] = "https://example.org/different-client"
        self.assertFailure(code="authorization")

    def test_unpinned_output_formula(self):
        self.m["claims"][0]["excel"].pop("expected_formula")
        self.assertFailure(code="output_formula_pin")

    def assertFailure(self, mode="release", code=None, candidate=None):
        rows = [r for r in self.run_audit(mode, candidate).rows if r["status"] != "PASS"]
        self.assertTrue(rows)
        if code: self.assertIn(code, {r["check"] for r in rows})

    def test_valid_calculation_and_release(self):
        a = self.run_audit()
        self.assertFalse([r for r in a.rows if r["status"] != "PASS"], a.rows)
        self.assertEqual(a.save(self.root / "out", "release", self.root / "report.md"), 0)

    def test_missing_source_id(self):
        self.m["claims"][0]["source_ids"] = ["missing"]
        self.assertFailure(code="source_registered")

    def test_source_hash_tamper(self):
        (self.root / "source.txt").write_text("New unreviewed evidence", encoding="utf-8")
        self.assertFailure(code="source_hash")

    def test_missing_apa(self):
        self.m["sources"]["S1"]["apa"] = "Different institution"
        self.assertFailure(code="apa_in_page")

    def test_missing_source_token(self):
        self.m["claims"][0]["source_checks"][0]["token"] = "Unreported result"
        self.assertFailure(code="source_token")

    def test_missing_file(self):
        self.m["pages"][0]["excel"][0]["path"] = "missing.xlsx"
        self.assertFailure(code="excel_file")

    def test_missing_sheet(self):
        self.m["claims"][0]["excel"]["sheet"] = "Unknown"
        self.assertFailure(code="excel_trace")

    def test_wrong_output_value(self):
        self.m["claims"][0]["excel"]["expected_value"] = .6
        self.assertFailure(code="excel_trace")

    def test_wrong_formula(self):
        self.m["claims"][0]["excel"]["expected_formula"] = "=A1/A2-1"
        self.assertFailure(code="excel_trace")

    def test_missing_formula_cache(self):
        workbook(self.root / "book.xlsx", value="")
        self.assertFailure(code="excel_trace")

    def test_independent_recalculation(self):
        self.m["claims"][0]["calculation"]["expression"] = "start/end-1"
        self.assertFailure(code="independent_calculation")

    def test_zero_denominator(self):
        self.m["claims"][0]["calculation"]["expression"] = "end/(start-start)"
        self.assertFailure(code="excel_trace")

    def test_wrong_display(self):
        self.m["claims"][0]["display"]["text"] = "60.0%"
        self.assertFailure(code="display_value")

    def test_title_and_nonnumeric_body_drift(self):
        candidate = self.root / "candidate.md"
        candidate.write_text(self.text.replace("Revenue expanded", "Demand disappeared").replace("Revenue grew", "Profit grew"), encoding="utf-8")
        self.assertFailure("compare", "compare_heading", candidate)
        self.assertFailure("compare", "compare_conclusion", candidate)

    def test_numerical_drift(self):
        candidate = self.root / "candidate.md"
        candidate.write_text(self.text.replace("50.0%", "80.0%"), encoding="utf-8")
        self.assertFailure("compare", "compare_numbers", candidate)

    def test_basic_feishu_xml_equivalence(self):
        candidate = self.root / "candidate.xml"
        candidate.write_text('<title>Synthetic report</title><h2>Page 1/1｜Revenue expanded</h2><h3>Big conclusion</h3><p>Revenue grew <b>50.0%</b>.</p><h3>Supporting evidence</h3><p>Starting revenue 10; ending revenue 15.</p><h3>Sources</h3><p>' + self.source + '</p>', encoding="utf-8")
        self.assertFalse([r for r in self.run_audit("compare", candidate).rows if r["status"] != "PASS"])

    def test_duplicate_page(self):
        candidate = self.root / "candidate.md"
        candidate.write_text(self.text + self.text, encoding="utf-8")
        self.assertFailure("compare", "execution_error", candidate)

    def test_unconfirmed_and_partial(self):
        self.m["pages"][0]["confirmation"]["status"] = "pending"
        self.m["pages"][0]["trace_coverage"] = "partial"
        self.assertFailure(code="page_approval")
        self.assertFailure(code="full_trace_coverage")

    def test_old_confirmation_hash(self):
        self.m["pages"][0]["confirmation"]["text_sha256"] = "stale"
        self.assertFailure(code="page_approval")

    def test_authorization_absent_or_stale(self):
        self.m["publication"]["authorization"]["status"] = "not_granted"
        self.assertFailure(code="authorization")
        self.m["publication"]["authorization"]["status"] = "granted"
        self.m["publication"]["authorization"]["candidate_sha256"] = "old"
        self.assertFailure(code="authorization")

    def test_unverified_source(self):
        self.m["sources"]["S1"]["review_status"] = "pending"
        self.assertFailure(code="source_audit")

    def test_image_removal_detected(self):
        candidate = self.root / "candidate.md"
        candidate.write_text(self.text + "\n![unreviewed image](new.png)", encoding="utf-8")
        self.assertFailure("compare", "image_inventory", candidate)

    def test_direct_quote_without_excel(self):
        c = self.m["claims"][0]
        c.update(kind="direct", report_quote="Starting revenue 10; ending revenue 15.", display={"text": "15"})
        c.pop("excel"); c.pop("calculation")
        self.assertFalse([r for r in self.run_audit("trace").rows if r["status"] != "PASS"])

    def test_qualitative_without_excel(self):
        c = self.m["claims"][0]
        c.update(kind="qualitative")
        c.pop("excel"); c.pop("calculation"); c.pop("display")
        self.assertFalse([r for r in self.run_audit("trace").rows if r["status"] != "PASS"])

    def test_safe_arithmetic_and_scope(self):
        with self.assertRaises(ValueError): arithmetic("__import__('os').getcwd()", {})
        with self.assertRaises(ValueError): arithmetic("2**100000", {})
        a = self.run_audit("inventory")
        with self.assertRaises(ValueError): a.path("../secret.xlsx")

    def test_generated_state_changes_with_manifest(self):
        self.run_audit("inventory")
        f, out = self.manifest, self.manifest.with_suffix('.md')
        render(f, out)
        self.assertIn("confirmed", out.read_text(encoding="utf-8"))
        self.m["pages"][0]["confirmation"]["status"] = "returned"
        f.write_text(json.dumps(self.m), encoding="utf-8")
        render(f, out)
        self.assertIn("returned", out.read_text(encoding="utf-8"))

    def test_empty_project_stays_unready(self):
        template = Path(__file__).parent.parent / "assets" / "project-state.json"
        self.m = json.loads(template.read_text(encoding="utf-8"))
        self.assertFailure("inventory", "baseline_pin")

    def test_orphan_claim_rejected(self):
        orphan = copy.deepcopy(self.m['claims'][0])
        orphan.update(id='C99', page='P99')
        self.m['claims'].append(orphan)
        self.assertFailure(code='claim_page_membership')

    def test_global_duplicate_claim_rejected(self):
        self.m['claims'].append(copy.deepcopy(self.m['claims'][0]))
        self.assertFailure(code='claim_ids')

    def test_every_source_needs_locator(self):
        self.m['sources']['S2'] = copy.deepcopy(self.m['sources']['S1'])
        self.m['claims'][0]['source_ids'].append('S2')
        self.assertFailure(code='source_locator')

    def test_renderer_cannot_overwrite_report(self):
        self.run_audit('inventory')
        before = (self.root / 'report.md').read_bytes()
        with self.assertRaises(ValueError): render(self.manifest, self.root / 'report.md')
        self.assertEqual(before, (self.root / 'report.md').read_bytes())

    def test_renderer_rejects_registered_sibling(self):
        self.m['sources']['S2'] = {'path': '05_校验记录/state.md'}
        self.manifest.write_text(json.dumps(self.m), encoding='utf-8')
        with self.assertRaises(ValueError): render(self.manifest, self.manifest.with_suffix('.md'))

    def test_broad_project_root_rejected(self):
        self.m['project_root'] = '../..'
        self.manifest.write_text(json.dumps(self.m), encoding='utf-8')
        with self.assertRaises(ValueError): Audit(self.manifest)

    def test_wrong_total_rejected(self):
        candidate = self.root / 'wrong-total.md'
        candidate.write_text(self.text.replace('Page 1/1', 'Page 1/10'), encoding='utf-8')
        with self.assertRaises(ValueError): document(candidate)

    def test_nonconsecutive_pages_rejected(self):
        candidate = self.root / 'wrong-sequence.md'
        candidate.write_text(self.text.replace('Page 1/1', 'Page 1/2') + self.text.replace('Page 1/1', 'Page 3/2'), encoding='utf-8')
        with self.assertRaises(ValueError): document(candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
