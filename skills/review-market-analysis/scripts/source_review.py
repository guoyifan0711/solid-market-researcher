"""Source-first reading packets and auditable field-by-field scope reviews.

No command marks a source or use verified. The agent reads the original context,
reconstructs its scope, and records its assessment separately from graph labels.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

FIELDS = ("geography", "category", "application", "population", "period",
          "metric", "unit", "denominator", "channel", "data_status")
CRITICAL = {"population", "denominator"}
TEXT = {".txt", ".md", ".json", ".xml", ".html", ".csv", ".ttl"}
MAX_TEXT_BYTES = 2 * 1024 * 1024


def hash_value(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def norm(value):
    return re.sub(r"\s+","",value or "")


def path_at(root,relative):
    if not isinstance(relative,str) or not relative or Path(relative).is_absolute():
        raise ValueError("project-relative path required")
    path=(Path(root)/relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):raise ValueError("review path outside project")
    return path


def pin(root,record):
    path=path_at(root,record["path"])
    if digest(path)!=record.get("sha256"):raise ValueError("version changed: "+record["path"])
    return path


def source_binding(manifest,eid):
    e=manifest["trace_graph"]["evidence"][eid]
    s=manifest["sources"][e["source_id"]]
    # A review flag is never part of the acquired-content identity.
    acquired={k:s[k] for k in ("path","sha256","url","title","published_date","data_period","read_scope","access_state","source_type","extraction") if k in s}
    return {"evidence_id":eid,"source_id":e["source_id"],"acquired":acquired,
            "quote":e["quote"],"locator":e["locator"]}


def evidence_input_hash(manifest,eid):
    e=manifest["trace_graph"]["evidence"][eid]
    return hash_value({"source":source_binding(manifest,eid),"scope":manifest["trace_graph"]["scopes"][e["scope_id"]]})


def use_review_key(manifest,use):
    g=manifest["trace_graph"];claims={c["id"]:c for c in manifest["claims"]}
    kind,key=use["from"].split(":",1)
    meaningful=lambda c:{k:c[k] for k in ("id","kind","report_quote","scope_id","excel","calculation","display") if k in c}
    origin=g["evidence"][key] if kind=="Evidence" else claims[key]
    source=evidence_input_hash(manifest,key) if kind=="Evidence" else meaningful(origin)
    original_review=(g.get("source_grounding",{}).get("evidence_reviews",{}).get(key)) if kind=="Evidence" else None
    return hash_value({"origin":source,"origin_scope":g["scopes"][origin["scope_id"]],
        "original_review":hash_value(original_review) if kind=="Evidence" else None,
        "claim":meaningful(claims[use["claim_id"]]),"target_scope":g["scopes"][claims[use["claim_id"]]["scope_id"]],
        "role":use["role"],"rationale":use["rationale"]})


def source_text(manifest,root,eid):
    binding=source_binding(manifest,eid);s=binding["acquired"];original=pin(root,s)
    record=s
    if s.get("extraction"):
        record=s["extraction"]
        if record.get("original_sha256")!=s["sha256"]:raise ValueError("extraction not bound to original")
        for item in record.get("input_files",[]):pin(root,item)
    elif original.suffix.lower() not in TEXT:
        raise ValueError("original requires faithful, version-bound extraction or page read")
    readable=pin(root,record)
    if readable.stat().st_size>MAX_TEXT_BYTES:raise ValueError("prepare a bounded faithful page/section extraction first")
    text=readable.read_text(encoding="utf-8-sig")
    if readable.suffix.lower()==".json":
        try:decoded=json.loads(text)
        except ValueError:decoded=None
        if isinstance(decoded,str):text=decoded
    return text,{"path":record["path"],"sha256":record["sha256"],"original_path":s["path"],"original_sha256":s["sha256"]}


def prepare(manifest,root,eid,out):
    """Write unapproved raw context. Do not copy the existing Scope into the packet."""
    root=Path(root).resolve();out=Path(out).resolve()
    if not out.is_relative_to(root):raise ValueError("reading packet must stay in project")
    if out.exists():raise ValueError("use a new reading-session directory")
    text,readable=source_text(manifest,root,eid)
    if norm(manifest["trace_graph"]["evidence"][eid]["quote"]) not in norm(text):
        raise ValueError("evidence quotation is absent from acquired source")
    receipt={"schema_version":1,"read_session_id":str(uuid.uuid4()),"prepared_at":datetime.now(timezone.utc).isoformat(),
        "source_binding":source_binding(manifest,eid),"readable":readable,"text":text,
        "instructions":"先读原文，重新填写十项口径；不从旧Scope复制答案。重点查样本、分母、定义、方法、脚注及数据期。此读取包不代表已审。"}
    out.mkdir(parents=True)
    rp=out/"source-read.json";rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding="utf-8")
    numbered="\n".join(f"{i}: {line}" for i,line in enumerate(text.splitlines(),1))
    (out/"source-read.md").write_text("# 返回来源原文\n\n"+receipt["instructions"]+"\n\n来源："+readable["original_path"]+"\n\n```text\n"+numbered+"\n```\n",encoding="utf-8")
    draft={"outcome":"pending","receipt":{"path":str(rp.relative_to(root)),"sha256":digest(rp)},
        "input_sha256":"","metric_kind":"","finding":"",
        "fields":{f:{"status":"pending","value":"","verbatim_value":"","meaning":"","anchor":{"line_start":None,"line_end":None,"quote":""},"interpretation":""} for f in FIELDS}}
    (out/"evidence-review-draft.json").write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding="utf-8")
    return draft


class SubstanceAudit:
    def __init__(self,manifest,root,claim_ids=None):
        self.m=manifest;self.root=Path(root).resolve();self.g=manifest["trace_graph"]
        self.rows=[];self.cache={};self.checked=set()
        self.claim_ids=claim_ids

    def check(self,name,ok,detail,unknown=False):
        self.rows.append({"check":"substance_"+name,"status":"PASS" if ok else ("NOT_CHECKED" if unknown else "FAIL"),"detail":detail})
        return ok

    def evidence(self,eid):
        if eid in self.checked:return
        self.checked.add(eid)
        records=self.g.get("source_grounding",{}).get("evidence_reviews",{})
        review=records.get(eid)
        if not self.check("source_review",isinstance(review,dict),eid+" 缺原文逐字段审查；verified不予替代",unknown=True):return
        if not self.check("source_outcome",review.get("outcome")=="supported",eid+" "+str(review.get("outcome")),unknown=review.get("outcome") not in {"unsupported","rejected"}):return
        self.check("source_input",review.get("input_sha256")==evidence_input_hash(self.m,eid),eid+" 原文/证据/口径变化须重新审查")
        self.check("source_finding",bool(str(review.get("finding","")).strip()),eid+" 须回答原文到底调查谁、数值如何定义")
        try:
            record=review["receipt"];rp=pin(self.root,record)
            if rp.stat().st_size>4*1024*1024:raise ValueError("reading receipt too large")
            receipt=json.loads(rp.read_text(encoding="utf-8-sig"))
            text,readable=source_text(self.m,self.root,eid)
            valid=receipt.get("schema_version")==1 and bool(receipt.get("read_session_id")) and receipt.get("source_binding")==source_binding(self.m,eid) and receipt.get("readable")==readable and receipt.get("text")==text
            if not self.check("receipt",valid,eid+" 读取回执须匹配实际取得的原文，不能以自写摘要替换"):return
        except (KeyError,OSError,ValueError,TypeError) as exc:
            self.check("receipt",False,eid+": "+str(exc),unknown=True);return
        scope=self.g["scopes"][self.g["evidence"][eid]["scope_id"]]
        fields=review.get("fields",{});metric=review.get("metric_kind")
        self.check("metric_kind",metric in {"ratio","rate","amount","count","qualitative"},eid+" 指标性质")
        for field in FIELDS:
            row=fields.get(field,{})
            matched=row.get("value")==scope.get(field)
            self.check("field_value",matched,eid+"/"+field+" 审查值必须对应当前Scope")
            state=row.get("status")
            if not self.check("field_interpretation",bool(str(row.get("interpretation","")).strip()),eid+"/"+field+" 说明原文含义/未披露范围"):continue
            if state=="stated":
                a=row.get("anchor",{});start,end=a.get("line_start"),a.get("line_end")
                lines=text.splitlines();valid=type(start) is int and type(end) is int and 1<=start<=end<=len(lines)
                quote=a.get("quote","");actual="\n".join(lines[start-1:end]) if valid else ""
                self.check("field_anchor",valid and bool(quote.strip()) and norm(quote)==norm(actual),eid+"/"+field+" 原文行与摘录须一致")
                raw=row.get("verbatim_value","")
                self.check("verbatim",bool(raw.strip()) and norm(raw) in norm(quote),eid+"/"+field+" 字段原词须出现在原文锚点")
                if field in CRITICAL:
                    self.check("critical_literal",norm(row.get("value"))==norm(raw),eid+"/"+field+" 人群/分母用原文原词作口径值，中文解释另存；不能自由改写扩大总体")
            elif state=="not_stated":
                self.check("unknown",row.get("value") in {"","未披露"},eid+"/"+field+" 未披露项不可填成已知总体")
            elif state=="not_applicable":
                self.check("not_applicable",str(row.get("value","")).startswith(("不适用","N/A")),eid+"/"+field+" 不适用须明确标识")
            else:self.check("field_status",False,eid+"/"+field+" 未完成原文判断",unknown=True)
            if metric in {"ratio","rate"} and field in CRITICAL:
                self.check("ratio_scope_known",state=="stated",eid+"/"+field+" 比例/采用率须有已知原文人群和分母")
        self.cache[eid]=review

    def build(self):
        grounding=self.g.get("source_grounding",{})
        if not isinstance(grounding,dict) or not isinstance(grounding.get("evidence_reviews",{}),dict) or not isinstance(grounding.get("use_reviews",{}),dict):
            raise ValueError("source_grounding must contain evidence_reviews/use_reviews objects")
        if len(grounding.get("evidence_reviews",{}))+len(grounding.get("use_reviews",{}))>20000:
            raise ValueError("substantive review records exceed bounded local limit")
        self.check("schema",grounding.get("schema_version")==1,"缺实质审查记录；结构通过不予替代",unknown=True)
        uses=self.g.get("uses",[]);claims={c["id"]:c for c in self.m.get("claims",[])}
        if self.claim_ids is not None:
            needed=set(self.claim_ids)
            while True:
                upstream={u["from"].split(":",1)[1] for u in uses if u.get("claim_id") in needed and u.get("from","").startswith("Claim:")}-needed
                if not upstream:break
                needed|=upstream
            uses=[u for u in uses if u.get("claim_id") in needed]
        reviews=grounding.get("use_reviews",{});seen=set()
        for use in uses:
            if use.get("claim_id") not in claims or ":" not in use.get("from",""):continue
            kind,key=use["from"].split(":",1)
            if kind=="Evidence":
                if key not in self.g.get("evidence",{}):continue
                self.evidence(key);origin=self.g["evidence"][key]
            elif kind=="Claim" and key in claims:origin=claims[key]
            else:continue
            h=use_review_key(self.m,use)
            if h in seen:continue
            seen.add(h);record=reviews.get(h)
            if not self.check("use_review",isinstance(record,dict),use["id"]+" 缺原文到结论的逐字段对照",unknown=True):continue
            self.check("use_input",record.get("input_sha256")==h,use["id"]+" 实质审查绑定当前含义，不以旧scope_review签名替代")
            outcome=record.get("outcome")
            self.check("use_outcome",outcome=="supported",use["id"]+" "+str(outcome),unknown=outcome not in {"unsupported","rejected"})
            decision=record.get("decision");target=claims[use["claim_id"]]
            self.check("claim_quote",record.get("claim_quote")==target.get("report_quote"),use["id"]+" 审查须面对当前报告原句，不能只看Scope标签")
            self.check("decision",decision in {"direct_support","analysis_inference","calculation","background","contradiction"},use["id"]+" 引用职责")
            self.check("role_decision",use["role"]=={"direct_support":"support","analysis_inference":"support","calculation":"support","background":"context","contradiction":"contradict"}.get(decision),use["id"]+" 审查结论与实际用途一致")
            self.check("use_reason",bool(str(record.get("reason","")).strip()) and bool(str(record.get("limits","")).strip()),use["id"]+" 写清可支持的判断、推导和限制")
            source_scope=self.g["scopes"].get(origin.get("scope_id"),{});target_scope=self.g["scopes"].get(target.get("scope_id"),{})
            numeric=target.get("kind") in {"direct","calculated","source_numeric"} or bool(re.search(r"\d\s*(?:%|％|percent|procent)",target.get("report_quote",""),re.I))
            for field in FIELDS:
                comp=record.get("comparisons",{}).get(field,{})
                literal_same=norm(source_scope.get(field))==norm(target_scope.get(field))
                source_field=self.cache.get(key,{}).get("fields",{}).get(field,{}) if kind=="Evidence" else {}
                meaning=source_field.get("meaning")
                equivalent=not literal_same and field in CRITICAL and bool(meaning) and norm(meaning)==norm(target_scope.get(field))
                same=literal_same or equivalent
                judgment="equivalent" if equivalent else ("same" if same else "different")
                self.check("comparison",comp.get("source")==source_scope.get(field) and comp.get("target")==target_scope.get(field)
                    and comp.get("judgment")==judgment and bool(str(comp.get("reason","")).strip()),use["id"]+"/"+field+" 逐字段核对")
                if use["role"]=="support" and numeric and field in CRITICAL:
                    anchor=comp.get("claim_anchor","")
                    self.check("claim_scope_anchor",bool(re.search(r"[^\W\d_]",anchor,re.U)) and norm(anchor) in norm(target.get("report_quote","")) and norm(anchor)==norm(target_scope.get(field)),use["id"]+"/"+field+" Claim口径值须是报告原句中的人群/分母原词，不能把旧标签套在新原句上")
                if use["role"]=="support" and numeric:
                    if decision=="calculation":
                        self.check("calculation_scope",bool(target.get("calculation")) and bool(target.get("excel")) and bool(record.get("derivation")),use["id"]+" 新分母须有原始数据、公式与换算说明")
                        if not same and field!="unit":
                            proofs=comp.get("supporting_claim_ids",[])
                            upstream={u["from"].split(":",1)[1] for u in uses if u.get("claim_id")==target["id"] and u.get("role")=="support" and u.get("from","").startswith("Claim:")}
                            self.check("scope_derivation_evidence",bool(proofs) and all(cid in upstream and cid!=target["id"] and claims.get(cid,{}).get("kind") in {"direct","calculated","source_numeric"} and norm(self.g["scopes"].get(claims[cid].get("scope_id"),{}).get(field))==norm(target_scope.get(field)) for cid in proofs),use["id"]+"/"+field+" 改变统计范围须有支持目标范围的上游原始数据判断")
                    else:self.check("no_broadening",same,use["id"]+"/"+field+" 数值引用不得把原文人群/分母扩大；推断标签不能放行")
            if decision=="analysis_inference":
                self.check("inference_kind",not numeric and target.get("kind") in {"qualitative","recommendation","method","definition"},use["id"]+" 分析建议与数值事实分开")
        return self


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--manifest",required=True);p.add_argument("--evidence",required=True);p.add_argument("--out",required=True)
    args=p.parse_args();mp=Path(args.manifest).resolve()
    if mp.parent.name!="05_校验记录" or mp.stat().st_size>16*1024*1024:raise ValueError("expected bounded project/05_校验记录 manifest")
    m=json.loads(mp.read_text(encoding="utf-8-sig"));root=mp.parent.parent
    if m.get("project_root")!="..":raise ValueError("project_root must be '..'")
    prepare(m,root,args.evidence,args.out)
    print(json.dumps({"status":"READ_REQUIRED","reading_packet":str(Path(args.out)/"source-read.md"),"review_draft":str(Path(args.out)/"evidence-review-draft.json"),"instruction":"agent读取原文后重建口径，再核对目标结论；此命令不批准任何引用。"},ensure_ascii=False))


if __name__=="__main__":
    try:main()
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("source review preparation failed: "+str(exc),file=sys.stderr);sys.exit(2)
