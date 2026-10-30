# Solid Market Researcher

Solid Market Researcher provides reusable skills for researchers and analysts using AI agents to develop evidence-backed market research and client marketing proposals. The three skills cover judgment-led writing, research and delivery review, and visual design and inspection.

Python tools link sources and evidence to scope, claims, report and chart locations, and APA references. They export a TTL evidence graph and flag missing, stale, or inconsistent records. Analysts review original sources to judge whether the evidence supports the current report's conclusions. External publication requires explicit authorization and readback.

[中文介绍](docs/overview.zh-CN.md). The detailed research instructions are primarily in Chinese; the writing skill also includes English guidance.

## What is included

| Component | Purpose |
|---|---|
| [Writing skill](skills/write-market-analysis-pitch/SKILL.md) | Turn researched facts into conclusions a client can understand and use. |
| [Review skill](skills/review-market-analysis/SKILL.md) | Define the research question, assess source fit, check calculations and review the argument and delivery. |
| [Visual skill](skills/build-market-analysis-visuals/SKILL.md) | Choose a chart for the supported relationship and inspect its actual output. |
| [Project templates](skills/review-market-analysis/references/project-state.md) | Keep page questions, versions, evidence gaps, approvals and readbacks in a consistent structure. |
| [Python checks](skills/review-market-analysis/references/executable-checks.md) | Check registered artifacts, evidence links, scope review records, calculations and delivery differences. |

The toolkit contains generic instructions, blank templates and synthetic tests. Keep client research in a separate private directory.

## Use the workflow

Read [AGENTS.md](AGENTS.md) as the workspace entry point. An agent that supports `SKILL.md` can load the three skills from `skills/`. Keep them together: their references use sibling directories. Choose document, spreadsheet and chart tools for the delivery format available in your environment.

1. Establish the decision, scope, time period and required output. Ask about missing business intent before researching dependent sections.
2. Write page questions and acquire the original sources. Record access gaps and their impact together by Part or research phase.
3. Read the original definitions, methods, tables and footnotes. Record evidence and scope, then compare them with the current report sentence.
4. Calculate where needed, write the argument, and create visuals from the reviewed evidence.
5. Review downstream uses when a source or conclusion changes. Record the exact version approved for any authorized publication and verify the actual target after writing.

Start a private project using the [README and manifest templates](skills/review-market-analysis/references/project-state.md). The v1 tools expect its manifest under `05_校验记录/` with `project_root` set to `..`. An empty template is a starting point, not a completed analysis.

## Evidence and original-source review

```text
Source -> Evidence + Scope -> Use -> Claim -> downstream Claim
                              |
                           Location -> report / chart / reference

SourceReview -> acquired original context and field anchors
UseReview   -> source meaning compared with the current report sentence
```

Each use records whether evidence supports, contradicts or supplies background for a claim. Reviews retain the original population and denominator, alongside the analyst's interpretation. Changes to source content, scope, interpretation or claim text invalidate the corresponding review bindings.

Prepare a new original-source reading packet with:

```bash
python skills/review-market-analysis/scripts/source_review.py --manifest "path/to/project/05_校验记录/state.json" --evidence E1 --out "path/to/project/reviews/E1-read-1"
```

Read the packet and the relevant original context, then complete the source and use review records as described in [source-grounded-review.md](skills/review-market-analysis/references/source-grounded-review.md). Export and check the registered graph with:

```bash
python skills/review-market-analysis/scripts/trace_graph.py --manifest "path/to/project/05_校验记录/state.json" --out "path/to/project/reviews/graph-1" --focus Claim:C1
```

Use a fresh output directory for each review. The tools refuse to overwrite existing output or registered input files.

| Result | Meaning |
|---|---|
| `SOURCE_REVIEW_COMPLETE` | The registered graph and required original-source review records pass the implemented checks. The analyst remains responsible for meaning and inference. |
| `NEEDS_REVIEW` | Required records are missing, stale, unsupported or inconsistent. Inspect the review report. |
| `STRUCTURE_ONLY` | An explicit `--structural-only` run checks structure. It does not clear substantive review. |

The tools work locally. They check registered coverage and record bindings; full-report review also requires checking actual text and references for omitted claims. Workbook checks read existing formula caches and independently evaluate supported arithmetic. Other formulas and final chart rendering require the appropriate tools and analyst checks. See the [schemas and limits](skills/review-market-analysis/references/executable-checks.md).

## Run the synthetic tests

The suite was tested with Python 3.12. Workbook checks use `openpyxl`; graph export and original-source packet preparation use the Python standard library.

In an activated virtual environment, run:

```bash
python -m pip install -r requirements.txt
python scripts/run_tests.py
```

The tests build fictional sources, report text and workbooks in `tmp/tests/`. They cover changed denominators, unsupported claims, altered original text, stale reviews, missing references, arithmetic and publication comparisons. They do not read client research or publish anything.

## Repository contents

```text
AGENTS.md
docs/overview.zh-CN.md
scripts/run_tests.py
skills/
  write-market-analysis-pitch/
  review-market-analysis/
    references/
    assets/
    scripts/
  build-market-analysis-visuals/
```

Keep acquired reports, briefs, datasets, source archives, screenshots, credentials and delivery outputs outside this repository. Before pushing changes, inspect the staged files and commit metadata as well as the ignore rules.
