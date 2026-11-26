# cgm-report-advisor

把一套已经在人工分析中使用的流程，写成可以公开复用的目录、说明和轻量代码骨架。输入是已经整理出的 CGM 图形报告指标，以及按本地知识库需要补齐的用药、病史和身高体重等资料；输出是能对上知识库出处、并只在知识库写明了份量或动作时才配示意图的患者饮食、运动和监测建议草稿。

这不是医院信息系统，也不是医疗器械。生成的文字是辅助建议，不能替代执业医师的判断，也不能用来自行调整处方药物剂量。

## English overview

This repository packages a reusable workflow for CGM graphic-report review: extract only values printed on the report, ask once for the clinical intake that a local knowledge base actually requires, interpret metrics in a fixed order, and draft diet or activity advice only when the wording can be traced to that knowledge base. It does not ship guideline full texts, real patient data, or a complete vendor PDF parser. The output is supportive advice, not a formal medical opinion and not a medical device.

## 做什么

- 说明从收到报告到写出患者文稿的标准步骤，以及“先看数据质量，再看低血糖，再看 TIR / TAR / CV”的解读顺序。
- 提供报告指标字段、资料收集原则、建议可追溯性、配图规则和知识库导入方式的文档。
- 用 Python 骨架把上述步骤串起来：资料不齐时停在询问清单，并不输出饮食或运动处方；配图前检查份量或动作是否来自知识库。
- 给出明确标明为虚构的示例，便于本地试跑。

## 不做什么

- 不内置任何指南或共识全文，也不在仓库中存放大段摘录。知识库由使用者自行导入自己有权使用的文献。
- 不把指南 PDF 自动下载进仓库。书目监测只报告可能的新版本和官方获取位置。
- 不提供各厂商 CGM PDF 的完整自动解析。第一版请先按字段说明把报告原文整理成 JSON。
- 知识库没有写明的用法、剂量、服药时点、食物清单、具体份量或运动处方，不会用通识补上，也不会编造。
- 不建议患者自行改药。未提供的毫克数或时点不会猜测。
- 不做登录系统、云端报告库、医院系统对接或微信小程序。这些若要做，属于后续工作，并且涉及健康数据合规，见 [docs/roadmap.md](docs/roadmap.md)。
- 不声称已经通过医疗器械认证，或可以代替医生完成诊疗。

## 快速开始

需要 Python 3.10 或更高版本。第一版只使用标准库，没有必装的第三方依赖。

```bash
git clone <your-fork-or-local-copy>
cd cgm-report-advisor

# 资料齐全时的虚构示例（会引用示例知识库中已写明的份量和动作）
PYTHONPATH=src python3 -m cgm_report_advisor \
  --metrics examples/fictional-report-metrics.json \
  --intake examples/fictional-intake.json \
  --knowledge-base knowledge-base/sources.example.json

# 资料不齐时，会先打印询问清单，并只输出不含饮食运动处方的指标解读
PYTHONPATH=src python3 -m cgm_report_advisor \
  --metrics examples/fictional-report-metrics.json \
  --intake examples/fictional-intake-incomplete.json \
  --knowledge-base knowledge-base/sources.example.json

# 只想先看曲线和指标时
PYTHONPATH=src python3 -m cgm_report_advisor \
  --metrics examples/fictional-report-metrics.json \
  --intake examples/fictional-intake.json \
  --knowledge-base knowledge-base/sources.example.json \
  --metrics-only
```

运行规则测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

把输出写入文件时，加上 `--output path/to/draft.md`。不要把真实报告 PDF 或真实资料提交到本仓库。

## 文献监测与受约束导入

这两条命令是第一版流水线之外的入口，不改变 `--metrics` 仍然必填的原有用法。

监测只比较书目。没有更新时会直接说明；可能有更新时，报告写明系列、年份和官方获取位置。`--fixture` 完全离线。`--live` 只查询题名和年份，不下载 PDF。

```bash
PYTHONPATH=src python3 -m cgm_report_advisor.watch \
  --watchlist knowledge-base/watchlist.json \
  --index knowledge-base/sources.json \
  --fixture path/to/fixture.json

PYTHONPATH=src python3 -m cgm_report_advisor.watch \
  --watchlist knowledge-base/watchlist.json \
  --index knowledge-base/sources.json \
  --live
```

导入只根据你已经放在本地的文本生成**待审**草稿。原文没有写明的份量不会被补上。接受之前，草稿不能进入饮食、运动或监测建议。

```bash
PYTHONPATH=src python3 -m cgm_report_advisor.ingest draft \
  --file knowledge-base/sources/your-file.txt \
  --source-id your-id \
  --title "文献名称"

PYTHONPATH=src python3 -m cgm_report_advisor.ingest accept \
  --draft knowledge-base/drafts/your-id.json \
  --index knowledge-base/sources.json \
  --read-status selected_sections_read \
  --entry-id your-id-001
```

`knowledge-base/sources/`、`knowledge-base/drafts/` 和 `knowledge-base/extracted/` 都被 Git 忽略。`watchlist.json` 可以提交，里面只有系列书目。说明见 [docs/knowledge-base.md](docs/knowledge-base.md) 和 [docs/roadmap.md](docs/roadmap.md)。

使用自己的知识库前，请先阅读 [docs/knowledge-base.md](docs/knowledge-base.md)，复制索引模板并如实填写阅读状态。未读全文的文献不得当作已经掌握。

## 标准流程

1. 收到 CGM 图形报告后，先从报告原文提取已有信息。没有写出的值不要编造。单位和指标名称保留原文。
2. 同一批有多份报告时，先核对是否同一佩戴者。不能确认时分开处理，用药和病史不可混套。
3. 对照本地知识库中已阅读的共识或指南，一次列出仍缺的临床资料。只问分析该类患者或给出饮食、运动建议真正需要的项目；已经提供的不要再问。常见缺项往往包括糖尿病类型与病程，用药名称、剂量和服药时间，身高体重，合并症（如心血管疾病、眼底病变、肾脏病），用餐时间与大致内容，运动习惯，睡眠，近期化验室糖化血红蛋白，但不要把这份常见列表当成每次必问的万能问卷。
4. 资料补齐后再写饮食和运动建议。若只要先看曲线，可先做不含饮食运动处方的指标解读，并标明缺口。
5. 给患者的饮食、运动、监测建议必须能追溯到知识库，并注明来源。知识库没有的内容不要用通识补，也不要编造。
6. 每条具体、且知识库已写明份量或动作的饮食或运动建议，可配一张示意图。例如知识库写每日半个水果，就画半个而不是一整盘。不得为配图而编造食物、份量或动作，不要做“好水果 / 坏水果”分类图。图上不要出现药盒商标、患者面部或身份信息。
7. 不建议自行调整处方药物剂量；调药一律写咨询医生。保留使用者提供的药物原名。
8. 对外文稿不要写出报告里的掩码电话等身份信息。报告若标明“仅供测试参考”或同类声明，须如实说明。
9. 分析是辅助建议，不是正式诊疗意见，也不是医疗器械。

更完整的步骤说明见 [docs/workflow.md](docs/workflow.md)。

## 解读顺序

解读指标时采用固定顺序，不要一开始就谈总体控制情况而跳过质量和低血糖：

1. **先看数据质量。** 不少共识常用的参考是建议约 14 天、有效数据至少约 70%，但这不是本仓库写死的阈值。具体采用哪一条、适用于哪类患者，以导入的知识库为准，并写明来源。
2. **再看低血糖。** 2 级低血糖即便只出现一次，也应建议尽快联系医生。不要把软件里单独的低血糖风险仪表，在知识库未支持或与低于目标时间（TBR）明显不符时，直接说成风险高。
3. **再看 TIR / TAR / CV 等。** 指标定义、切点和目标必须来自已收录共识，并写明适用人群。同一问题若有不同框架，应并列写出，不要自行折中成一条新标准。

## 仓库里有什么

- `docs/`：流程、资料收集、报告字段、建议与配图、知识库导入和路线图。
- `knowledge-base/`：说明、示例索引模板，以及可提交的书目监测清单。不要把指南正文、导入草稿或抽出的文本放进来。
- `examples/`：虚构的资料和指标，仅供演示。
- `src/cgm_report_advisor/`：流水线骨架，模块包括 `extract_report`、`intake`、`analyze`、`illustrate`、`render_report`，以及分开的 `watch` 与 `ingest`。
- `tests/`：针对“缺资料则不输出饮食运动处方”“禁止编造份量”等规则的测试。

## 免责声明

本项目提供的是方法说明和辅助草稿，不是对任何个人的诊疗意见，也不是医疗器械软件。作者和贡献者不对依据本仓库输出作出的医疗决定承担责任。涉及具体患者的诊断、治疗和药物调整，请咨询具备资质的医生，并遵循你所在机构的规范和当地法律法规。

仓库中的示例数据、示例知识库条目和示例建议全部为虚构，不得当作真实病例、真实指南或真实处方。

## 许可

以 [MIT License](LICENSE) 发布。请不要在该许可下再分发你没有权利公开的指南全文或真实患者资料。
