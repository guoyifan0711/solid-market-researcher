"""Synthetic source-grounding tests. Never approves a real project or edits client sources."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from source_review import prepare,evidence_input_hash,use_review_key,digest,SubstanceAudit
from trace_graph import GraphAudit,use_input_hash

TRUTH=dict(geography="Testland",category="Test device",application="Residential",
    population="Test households",period="2026",metric="Sales",unit="units",
    denominator="Test sample",channel="All test channels",data_status="Actual")


def add_test_grounding(m,root):
    """Known synthetic truth is stated in the fixture, independently of editable Scope."""
    root=Path(root);source=root/"source.txt"
    line="Synthetic source definitions: "+"; ".join(TRUTH.values())+"."
    source.write_text(source.read_text(encoding="utf-8")+"\n"+line,encoding="utf-8")
    m["sources"]["S1"]["sha256"]=digest(source)
    draft=prepare(m,root,"E1",root/"source-reading-1")
    draft.update(outcome="supported",metric_kind="count",finding="原文给出Test sample中Test households的2026年销量10 units。")
    for field,value in TRUTH.items():
        draft["fields"][field]={"status":"stated","value":value,"verbatim_value":value,
            "meaning":"本测试样本" if field in {"population","denominator"} else value,
            "anchor":{"line_start":2,"line_end":2,"quote":line},"interpretation":"原文逐项列示该字段；不扩大总体。"}
    draft["input_sha256"]=evidence_input_hash(m,"E1")
    m["trace_graph"]["source_grounding"]={"schema_version":1,"evidence_reviews":{"E1":draft},"use_reviews":{}}
    target=copy.deepcopy(TRUTH);target.update(population="本测试样本",denominator="本测试样本")
    m["trace_graph"]["scopes"]["SC_TARGET"]=target;m["claims"][0]["scope_id"]="SC_TARGET"
    for use in m["trace_graph"]["uses"]:
        key=use_review_key(m,use)
        m["trace_graph"]["source_grounding"]["use_reviews"][key]={"input_sha256":key,"outcome":"supported",
            "claim_quote":m["claims"][0]["report_quote"],
            "decision":"direct_support","reason":"原句销量与原文相符，属于同一样本、年份及单位。","limits":"仅Test sample，未外推全国。",
            "comparisons":{f:{"source":v,"target":target[f],"judgment":"equivalent" if f in {"population","denominator"} else "same","reason":"逐项对应来源定义。","claim_anchor":"本测试样本"} for f,v in TRUTH.items()}}


class SourceReviewChecks(unittest.TestCase):
    def setUp(self):
        from test_trace_graph import GraphChecks
        GraphChecks.setUp(self)
        add_test_grounding(self.m,self.root);self.stamp()

    def stamp(self):
        for u in self.m["trace_graph"]["uses"]:
            u["scope_review"]={"status":"verified","basis":"synthetic review","input_sha256":use_input_hash(self.m,u)}

    def issues(self):
        return [r for r in GraphAudit(self.m,self.root,require_substantive=True).build().rows if r["status"]!="PASS"]

    def evidence_review(self):return self.m["trace_graph"]["source_grounding"]["evidence_reviews"]["E1"]

    def use_record(self):return next(iter(self.m["trace_graph"]["source_grounding"]["use_reviews"].values()))

    def resign_use_only(self):
        old=self.use_record();key=use_review_key(self.m,self.m["trace_graph"]["uses"][0])
        self.m["trace_graph"]["source_grounding"]["use_reviews"]={key:{**old,"input_sha256":key}}
        self.stamp()

    def test_source_anchored_review_passes(self):
        self.assertFalse(self.issues())

    def test_verified_flags_alone_cannot_pass(self):
        del self.m["trace_graph"]["source_grounding"]
        self.stamp()
        self.assertTrue(any(r["check"]=="substance_source_review" for r in self.issues()))

    def test_source_scope_changed_and_resigned_is_not_enough(self):
        self.m["trace_graph"]["scopes"]["SC1"]["denominator"]="all households"
        self.resign_use_only()
        self.assertTrue(any(r["check"]=="substance_source_input" for r in self.issues()))

    def test_rewriting_all_hashes_and_review_value_still_needs_raw_denominator(self):
        self.m["trace_graph"]["scopes"]["SC1"]["denominator"]="all households"
        review=self.evidence_review();review["fields"]["denominator"]["value"]="all households"
        review["input_sha256"]=evidence_input_hash(self.m,"E1");self.resign_use_only()
        self.assertTrue(any(r["check"]=="substance_critical_literal" for r in self.issues()))

    def test_fabricated_raw_value_cannot_pass(self):
        self.m["trace_graph"]["scopes"]["SC1"]["denominator"]="all households"
        review=self.evidence_review();review["fields"]["denominator"].update(value="all households",verbatim_value="all households")
        review["input_sha256"]=evidence_input_hash(self.m,"E1");self.resign_use_only()
        self.assertTrue(any(r["check"]=="substance_verbatim" for r in self.issues()))

    def test_target_universe_cannot_be_broadened_under_inference_label(self):
        new=copy.deepcopy(TRUTH);new["denominator"]="all households";self.m["trace_graph"]["scopes"]["TARGET"]=new
        self.m["claims"][0]["scope_id"]="TARGET";self.resign_use_only()
        record=self.use_record();record["decision"]="analysis_inference"
        record["comparisons"]["denominator"].update(target="all households",judgment="different",reason="Synthetic invalid broadening.")
        self.assertTrue(any(r["check"]=="substance_no_broadening" for r in self.issues()))

    def test_fake_quote_is_rejected(self):
        self.evidence_review()["fields"]["population"]["anchor"]["quote"]="Invented source sentence."
        self.assertTrue(any(r["check"]=="substance_field_anchor" for r in self.issues()))

    def test_keyword_without_population_context_is_insufficient(self):
        self.evidence_review()["fields"]["population"]["anchor"]={"line_start":1,"line_end":1,"quote":self.excerpt}
        self.assertTrue(any(r["check"]=="substance_verbatim" for r in self.issues()))

    def test_changed_receipt_text_cannot_be_resigned_into_source(self):
        review=self.evidence_review();path=self.root/review["receipt"]["path"]
        data=json.loads(path.read_text(encoding="utf-8"));data["text"]+="\nInvented all households."
        path.write_text(json.dumps(data),encoding="utf-8");review["receipt"]["sha256"]=digest(path)
        self.assertTrue(any(r["check"]=="substance_receipt" for r in self.issues()))

    def test_source_file_change_requires_fresh_read(self):
        p=self.root/"source.txt";p.write_text(p.read_text(encoding="utf-8")+"\nUpdated edition.",encoding="utf-8")
        self.m["sources"]["S1"]["sha256"]=digest(p);self.resign_use_only()
        self.assertTrue(any(r["check"]=="substance_receipt" for r in self.issues()))

    def test_read_packet_does_not_copy_wrong_scope_answer(self):
        self.m["trace_graph"]["scopes"]["SC1"]["denominator"]="FAKE_UNIVERSE_FROM_GRAPH"
        prepare(self.m,self.root,"E1",self.root/"fresh-session")
        self.assertNotIn("FAKE_UNIVERSE_FROM_GRAPH",(self.root/"fresh-session/source-read.json").read_text(encoding="utf-8"))
        draft=json.loads((self.root/"fresh-session/evidence-review-draft.json").read_text(encoding="utf-8"))
        self.assertEqual(draft["outcome"],"pending");self.assertEqual(draft["fields"]["denominator"]["value"],"")

    def test_reading_receipt_without_agent_assessment_is_pending(self):
        draft=prepare(self.m,self.root,"E1",self.root/"second-reading")
        self.m["trace_graph"]["source_grounding"]["evidence_reviews"]["E1"]=draft
        self.assertTrue(any(r["check"]=="substance_source_outcome" for r in self.issues()))

    def test_missing_comparison_does_not_pass(self):
        del self.use_record()["comparisons"]["period"]
        self.assertTrue(any(r["check"]=="substance_comparison" for r in self.issues()))

    def test_claim_text_changed_without_scope_change_requires_review(self):
        self.m["claims"][0]["report_quote"]="全国所有家庭销量为10台。"
        self.resign_use_only()
        self.assertTrue(any(r["check"]=="substance_claim_quote" for r in self.issues()))

    def test_report_population_phrase_must_be_located(self):
        self.use_record()["comparisons"]["denominator"]["claim_anchor"]="全国所有家庭"
        self.assertTrue(any(r["check"]=="substance_claim_scope_anchor" for r in self.issues()))

    def test_wrong_report_cannot_hide_behind_unchanged_scope_label(self):
        self.m["claims"][0]["report_quote"]="全国所有家庭销量为10台。"
        self.resign_use_only();record=self.use_record();record["claim_quote"]=self.m["claims"][0]["report_quote"]
        for field in ["population","denominator"]:record["comparisons"][field]["claim_anchor"]="全国所有家庭"
        self.assertTrue(any(r["check"]=="substance_claim_scope_anchor" for r in self.issues()))

    def test_changed_translation_reopens_use_review(self):
        self.evidence_review()["fields"]["denominator"]["meaning"]="全国所有家庭"
        self.assertTrue(any(r["check"]=="substance_use_review" for r in self.issues()))

    def second_claim_without_grounding(self):
        self.m["claims"].append({"id":"C2","page":"P2","kind":"qualitative","scope_id":"SC1","report_quote":"Other finding."})
        self.m["trace_graph"]["evidence"]["E2"]={**self.m["trace_graph"]["evidence"]["E1"]}
        self.m["trace_graph"]["uses"].append({"id":"U2","from":"Evidence:E2","claim_id":"C2","location_id":"L1","role":"support","rationale":"Another source facet."})

    def test_local_review_does_not_reopen_unrelated_claims(self):
        self.second_claim_without_grounding()
        rows=SubstanceAudit(self.m,self.root,claim_ids={"C1"}).build().rows
        self.assertFalse([r for r in rows if r["status"]!="PASS"])

    def test_local_review_includes_upstream_claims(self):
        self.second_claim_without_grounding()
        self.m["trace_graph"]["uses"].append({"id":"U3","from":"Claim:C2","claim_id":"C1","location_id":"L1","role":"support","rationale":"Depends on the other finding."})
        rows=SubstanceAudit(self.m,self.root,claim_ids={"C1"}).build().rows
        self.assertTrue(any(r["check"]=="substance_source_review" and r["status"]!="PASS" and r["detail"].startswith("E2 ") for r in rows))

    def test_unsupported_assessment_stops(self):
        self.use_record()["outcome"]="unsupported"
        self.assertTrue(any(r["check"]=="substance_use_outcome" and r["status"]=="FAIL" for r in self.issues()))

    def test_default_cli_requires_substantive_review(self):
        del self.m["trace_graph"]["source_grounding"]
        manifest=self.root/"05_校验记录/state.json";manifest.write_text(json.dumps(self.m),encoding="utf-8")
        result=subprocess.run([sys.executable,str(Path(__file__).with_name("trace_graph.py")),"--manifest",str(manifest),"--out",str(self.root/"default-out")],capture_output=True,text=True,encoding="utf-8",timeout=20)
        self.assertEqual(result.returncode,1)
        report=json.loads((self.root/"default-out/graph-review.json").read_text(encoding="utf-8"))
        self.assertEqual(report["result"],"NEEDS_REVIEW")

    def test_default_cli_accepts_complete_grounded_review(self):
        manifest=self.root/"05_校验记录/state.json";manifest.write_text(json.dumps(self.m),encoding="utf-8")
        result=subprocess.run([sys.executable,str(Path(__file__).with_name("trace_graph.py")),"--manifest",str(manifest),"--out",str(self.root/"complete-out")],capture_output=True,text=True,encoding="utf-8",timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads((self.root/"complete-out/graph-review.json").read_text(encoding="utf-8"))
        self.assertEqual(report["result"],"SOURCE_REVIEW_COMPLETE")


if __name__=="__main__":unittest.main()
