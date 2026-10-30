"""Generate the readable project state from its one authoritative JSON manifest."""
import argparse
import json
import os
from pathlib import Path


def render(manifest_path, output_path):
    manifest_path, output_path = Path(manifest_path).resolve(), Path(output_path).resolve()
    m = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest_path.parent.name != "05_校验记录" or m.get("project_root") != "..":
        raise ValueError("schema v1 manifest must be in project/05_校验记录 with project_root '..'")
    root = (manifest_path.parent / m["project_root"]).resolve()
    if output_path != manifest_path.with_suffix(".md"):
        raise ValueError("output must be the manifest's sibling Markdown view")
    def paths(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "path" and isinstance(child, str): yield (root / child).resolve()
                else: yield from paths(child)
        elif isinstance(value, list):
            for child in value: yield from paths(child)
    registered = set(paths(m))
    registered.update((root / p).resolve() for page in m.get("pages", []) for p in page.get("audits", []) if isinstance(p, str))
    if output_path in registered:
        raise ValueError("output is a registered deliverable, source, or audit record")
    def link(record):
        if not record: return "未登记"
        p = record if isinstance(record, str) else record.get("path")
        if not p: return "未登记"
        destination = (root / p).resolve()
        if not destination.is_relative_to(root): raise ValueError("artifact outside project")
        relative = os.path.relpath(destination, output_path.parent).replace(os.sep, "/")
        return "[" + destination.name + "](<" + relative + ">)"
    project = m.get("project", {})
    lines = ["# " + (project.get("name") or "新项目") + "｜当前交付清单", "",
             "由当前交付清单 JSON 生成；只更新源清单，不手改此视图。", "",
             "状态更新时间：" + (project.get("updated_at") or "未登记"), "",
             "| 对象 | 内容 |", "|---|---|"]
    for field, label in [("client", "客户"), ("sku", "SKU／产品"), ("market", "市场")]:
        lines.append("| " + label + " | " + str(project.get(field) or "待明确").replace("|", "／") + " |")
    baseline = m["baseline"]
    lines += ["", "正文基准：" + link(baseline), "", "正文确认：" + str(baseline.get("approval", {}).get("status", "未登记")), ""]
    for page in m["pages"]:
        visual = page.get("visuals", {})
        lines += ["## " + page["id"] + "｜" + page.get("part", "") + "｜" + page.get("heading", "待定标题"), "",
                  "- 正文：" + link(baseline),
                  "- Excel：" + ("；".join(link(x) for x in page.get("excel", [])) or "未制作／未登记"),
                  "- Visual：" + str(visual.get("status", "not_started")) + "；" + ("；".join(link(x) for x in visual.get("files", [])) or "未制作／不适用，见依据"),
                  "- Visual 依据：" + str(visual.get("basis") or "未登记"),
                  "- 审计：" + ("；".join(link(x) for x in page.get("audits", [])) or "未登记"),
                  "- 文字确认：" + str(page.get("confirmation", {}).get("status", "not_started")) + "；" + str(page.get("confirmation", {}).get("basis") or "未登记"),
                  "- Claim 映射覆盖：" + str(page.get("trace_coverage", "none")) + "；" + ", ".join(page.get("trace_claim_ids", [])), ""]
    pub = m.get("publication", {})
    snapshot = pub.get("snapshot", {})
    lines += ["## 外部与缺口", "", "- 目标：" + str(pub.get("target") or "未指定"),
              "- 本次授权：" + str(pub.get("authorization", {}).get("status", "not_granted")),
              "- 回读：" + link(snapshot) + "；revision=" + str(snapshot.get("revision")) + "；时间=" + str(snapshot.get("read_at")), ""]
    lines += ["- " + str(x) for x in project.get("open_items", [])]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    render(args.manifest, args.output)
