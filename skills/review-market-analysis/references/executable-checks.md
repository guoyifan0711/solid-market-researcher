# 可执行检查

## 用途与边界

脚本检查产物路径／哈希、已登记 Claim 的来源／Excel／正文连接、派生数的独立复算，以及批准稿与候选／回读内容的差异。它不发布、不访问网络、不修改工作簿，也不自动判断来源可信度、市场口径、因果或营销判断。

实质审查由本Skill A／B／C及 [原文核对流程](source-grounded-review.md) 执行。图谱模式的trace/release强制检查原文逐字段审查记录，verified和重新签名不能替代。通过结果说明记录与锚点核对完整，agent仍须实际理解原文。全量覆盖须逐页反向核对，不能凭样例改成complete。

证据关系的类型、字段与人工自审路径见 [证据关系图谱](evidence-graph.md)。启用该扩展的清单在 trace／release 中同时检查图谱，来源引用从图谱投影给既有三流检查器；未启用的历史清单沿旧流程检查，不据此声称图谱完整。

运行前用工作区依赖工具定位 Python；Excel 只读检查使用该运行时的 openpyxl。没有依赖时如实记录未执行，不随意安装到客户项目。脚本支持带 `## Page 1/5｜标题` 等页头和 `### Big conclusion` 的 Markdown，以及飞书 Docx 回读 XML；页数不固定。其他平台先做保留语义的格式转换并人工审查，不能伪称原生支持。

## 执行

命令中的路径均为示意，Coordinator 替换为本次已存在的清单、文件和独立检查输出目录；不是让用户手动操作。

```text
python render_state.py --manifest 项目/05_校验记录/当前交付清单.json --output 项目/05_校验记录/当前交付清单.md
python audit_market.py --manifest 清单.json --mode inventory --out 本轮检查目录
python audit_market.py --manifest 清单.json --mode trace --pages P1,P2 --out 本轮检查目录
python audit_market.py --manifest 清单.json --mode compare --candidate 候选稿.md --out 本轮检查目录
python audit_market.py --manifest 清单.json --mode release --candidate 候选稿.md --out 本轮检查目录
```

脚本位于本 Skill 的 `scripts/`。`--pages` 可用于 trace／compare 等局部检查；完整整合和整篇发布不传该参数。每次在新版本的检查目录输出 JSON 和 MD，保留历史记录。状态渲染器只写与清单 JSON 同名、同目录的 `.md` 视图，并拒绝覆盖清单中登记的正文、来源、底稿或审计文件。

| 模式 | 实际检查 | 不代表 |
|---|---|---|
| inventory | 清单与正文页序、标题、文件存在及登记哈希 | 人工已审阅或用户已确认 |
| trace | Source ID、原文哈希／定位、原始 APA 在对应页、输出单元格／缓存／公式、独立算式、展示舍入及正文引用 | 未登记 Claim 也已核验，或原公式引擎已重算 |
| compare | 页序、标题、大结论、正文与数字标记、摘要；末页正文包括后续附录；图片引用及图像核对记录 | 平台真实渲染自动通过 |
| release | 以上检查 + 当前正文／逐页批准、完整映射、语义审计、Visual 确认、本次授权与版本绑定 | 工具获得写入权或已经发布 |

退出码 0 表示本模式登记范围通过；非 0 表示差异、未执行或运行错误。结果 `FAIL` 与 `NOT_CHECKED` 都不能充当发布通过。意外异常同样停止，不把缺缓存当零值。

compare 采取保守差异检查：只自动归一化空白、基础 Markdown 强调／链接等格式；表格转换、措辞替换、币种写法等可能被报告为差异。人工核对后提供语义不变且可比较的转换稿，保留原回读及转换记录。不得删除正文、数字、表格或引用来制造一致。

## 证据图谱检查与导出

```text
python source_review.py --manifest 项目/05_校验记录/当前交付清单.json --evidence E1 --out 项目/05_校验记录/本轮/E1_原文读取
python trace_graph.py --manifest 项目/05_校验记录/当前交付清单.json --out 本轮新检查目录 --focus Source:S1
python trace_graph.py --manifest 项目/05_校验记录/当前交付清单.json --out 另一新检查目录 --focus Claim:C1
```

`--focus` 可省略，也可使用 `Evidence:E1` 或 `Scope:SC1`。脚本生成 `graph.ttl`、包含节点／边／双向邻接表的 `graph.json`，以及 `graph-review.json/md`；focus 列出上下游与受影响引用地点。每轮使用新目录，脚本拒绝覆盖已有输出或登记输入，不回写清单、不访问网络。

先打开source-read.md从原文重建口径，再完成source_grounding的Evidence/Use两层审查。结构检查覆盖节点、原文摘录、哈希、位置、支持路径、循环、孤立项、引用对账及旧缓存指纹；实质记录检查核对原文行锚点、原词、十项字段与当前Scope/报告原句，数值范围变化的证据和推导，以及SourceReview到UseReview的绑定。原文或审查变化时重开相应记录。

默认要求实质记录，完整后为`SOURCE_REVIEW_COMPLETE`；缺项、未取得或不支持为`NEEDS_REVIEW`，FAIL与NOT_CHECKED均不能放行。`--structural-only`只输出`STRUCTURE_ONLY`诊断；trace/release不会以该选项跳过实质层。旧版TECHNICAL_PASS保留为历史结构检查记录。旧图谱未补实质记录时明确待审，不自动标完成或改写客户稿。原生图表、工作簿和外部渲染仍走对应检查。

运行只依赖 Python 标准库，按单进程、本地提案规模设计：清单上限16 MiB，图谱登记上限20,000条；文件哈希和文本摘录检查分块读取。超过上限先拆分或改用磁盘支持的处理方式，不直接取消边界。JSON 是编辑源，TTL是生成视图；Turtle词表及关系解释见图谱附件。

## 清单 schema_version=1

空白实例：[project-state.json](../assets/project-state.json)。字段按下表填入；可增加业务元数据，但脚本不会自动验证新增字段。

| 对象 | 必需内容 |
|---|---|
| project | name、client、sku、market、updated_at、open_items；当前已知对象与缺口 |
| baseline | path、sha256、approval.status／basis；当前待审或批准正文，状态必须真实 |
| pages[] | id、part、heading；excel[]、visuals、audits[]；confirmation、trace_coverage、trace_claim_ids、semantic_review |
| sources | 以 Source ID 为键；path、sha256、apa、locator、review_status、audit_basis；另存原始数据期、单位／总体等审计元数据 |
| claims[] | id、page、kind、source_ids、report_quote、source_checks；数字另填 display 与适用的 excel／calculation |
| trace_graph | 新项目默认的v1扩展；固定project_id，scopes／evidence／locations／uses见图谱附件；units登记摘要/附录，source_references及coverage_documents对账原稿链接；Claim另填scope_id |
| publication | target、authorization、snapshot；有图时可记录 image_review |

文件记录用 `{path, sha256}`；sha256 为实际文件小写 SHA-256。v1 只接受位于 `项目/05_校验记录/` 的清单，`project_root` 固定为 `..`，防止把工作区根目录误设为单个项目。所有来源、底稿与审计路径相对项目根目录，不能跨到别的项目。`pages[].excel`、`visuals.files` 登记真正交付件，不指向中间件。Excel 内嵌页面另在元数据中记录 Sheet／Range，不能因为没有 PNG 就认定无 Visual。

被检查正文的 `Page N/Total` 中 Total 必须与该文件实际页数一致，N 必须从 1 连续排列；局部检查从完整基准选取 `--pages`，不要制造缺页但仍沿用整篇总页数的候选文件。

### 页面确认与覆盖

- `confirmation.status`：not_started / pending / returned / confirmed；basis 记录用户决定及范围，`text_sha256` 绑定页面正文。
- 页面哈希使用脚本 `text_digest(heading + body)`，page 内容由 `document(path)['pages'][id]` 提取；标题／正文改变后不能继续沿用旧哈希。
- `trace_coverage`：none / partial / complete。`trace_claim_ids` 必须与该页实际登记 Claim 一致。
- `semantic_review`：status=verified、basis 指向本轮实际人工审计、text_sha256；未审内容不得只填 verified。
- `visuals`：status、files、basis；未制作／未单独确认记为 not_started 或 pending；不适用须写真实理由。
- `audits`：相关历史／本轮审计文件列表。依据文件需有可读的检查范围与结果，不只有空白标题。

### Claim 类型

未启用图谱时，`source_checks` 为 `{source_id, token}` 列表；每个 source_id 均须有非空 token。启用 `trace_graph` 时，这两项从 Evidence／Use 关系生成检查视图，省去逐 Claim 重填；手工保留的字段须与投影一致。token 为已读取原文的可定位摘录，不使用模型总结充当原文。Claim ID全局唯一，page属于正式页或显式补充单元。`report_quote`是已存在的精确语句。APA条目靠近该页或同一Part；图谱模式可核对已登记的书目Reference及同版来源别名，上游Claim的完整出处不必在每个下游策略重抄。审查新增反证的`audit_only`关系与客户实际引用分开。

- `kind=direct`：原文直接数值引用，不要求 Excel；`display.text` 必须同时出现在定位摘录与报告句子中。单位转换或派生比例应改走计算路径。
- `kind=qualitative`：定性判断／建议的证据链，不制造数值公式；脚本查定位与引用，人工审计其推导。
- 其他数字 Claim 使用 `excel`：path、sheet、cell（单一输出单元格）、expected_value；有公式则登记 expected_formula。
- `display`：text、scale、decimals。例如底稿 0.125 → 展示 12.5%，填写 text="12.5%", scale=100, decimals=1。采用常规四舍五入。
- `calculation`：expression 与 inputs 字典。每个输入使用同样的 Excel 单元格记录；输出 expected_formula 必填。expression 只允许数字、输入名、括号、加减乘除与有限幂，例如 `end/start-1` 或 `(end/start)**(1/years)-1`，不运行任意代码。

输入与原文是否属于同年、同单位、同总体，须在人工来源审计和元数据里确认；不能用相同数字或字符串出现就证明含义正确。

PDF／原始XLSX、JSON编码的web归档等可登记已审计提取文件`extraction={path,sha256,original_sha256}`；原文与提取版本对应。提取只解码或选择实际获得的段落，不把摘要扩成全文。内部定义/获取记录按图谱附件登记用途，不作为独立市场研究。提取命中不替代读取原文；公式缓存缺失时补等价复算，不伪造缓存。

### 发布与图像

`authorization` 默认 not_granted。真实授权后记录 status=granted、basis、target、candidate_sha256、baseline_sha256、pages；授权内 target 必须与本次发布目标完全一致。变更候选内容、目标或范围后重新核对授权，不复用旧通过记录。清单可由人编辑，因此它是工作流记录，不是安全权限系统。

`snapshot` 记录实际回读 path／revision／read_at／identity，不能把本地候选文件当平台回读。

有图片的发布检查默认 NOT_CHECKED，直到完成真实图像／渲染检查。`image_review` 须包含 status=verified、basis、baseline_sha256、candidate_sha256、pages，以及 `evidence={path,sha256}`。该证据应逐图记录实际核对方式和结果；文件数量、XML 图片名或代码运行成功不能作为依据。

## 维护验证

修改脚本后运行 `python -m unittest discover -s scripts -p 'test_*.py' -v`。测试只使用临时合成素材，不读取客户项目。新增支持格式或公式时补正例和故障例；未测试的能力不写入成功承诺。
