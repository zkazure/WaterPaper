# WaterPaper / 水论文

## Overview

本技能支持两大工作模式，写作模式可选两种产出格式：

1. **论文写作模式**：从一句话出选题→真实文献采集→大纲→写作→图表→成稿，稳定生成格式规范、参考文献真实可核验的中文本科课程期末论文（3000-8000 字）
   - **Word 链路**：`学校 .docx 模板` → 提样式 → `.docx`
   - **LaTeX 链路**：`学校 .tex 模板` → 注入外壳 → `.pdf`（另交付 `.tex` 源）
2. **检测/改写模式**：对已有论文进行 5 维度 AIGC 特征深度分析 + 7 大技法智能改写，降低 AI 检测率

两条链路共用同一套中继（Markdown 终稿）与同一套降AI/降重流程，只在「格式提取」
与「成稿」两端分开。收完需求后必须先问清用户要哪种产出。

水论文不是真的水——而是让选题、文献、格式这些体力活自动化，把你的时间用在更有价值的事情上。

## Mode Routing（模式路由）

根据用户意图自动判断工作模式：

**触发论文写作模式的关键词**："写论文""撰写""生成论文""毕业论文""帮我写""写一篇"
→ 执行下方「论文写作模式」流程（第 1-12 步）

**触发检测/改写模式的关键词**："分析""检测""改写""降低AI率""降AI""AIGC""AI率"
→ 执行「检测/改写模式」流程（参考 `prompts/detection_pass.md`）

**如果意图不明确**，使用 AskUserQuestion 询问：

1. "撰写新论文（论文写作模式）"
2. "检测或改写已有论文（检测/改写模式）"

核心差异化能力：

1. **格式提取**：支持用户上传学校模板 `.docx` / `.doc`（自动提样式并转为 `.docx`）
   或 `.tex` LaTeX 模板（外壳注入，见 `references/latex_template_guide.md`），
   也支持直接粘贴格式要求
2. **选题工作流**：根据用户需求生成 5 角度 × 2 选题的结构化选题表
3. **真实文献采集**：通过多源爬虫脚本抓取真实学术文献，杜绝编造
4. **HTML 科研图表**：用 HTML/CSS/JS 绘制科研级别图表，Playwright 渲染为 PNG 插入正文
5. **完整交付链**：格式 → 选题 → 文献 → 大纲 → 正文 → 图表 → DOCX / PDF，一步到位
6. **AIGC 检测+改写**：5 维度语义分析定位 AI 痕迹 + 7 大改写技法精准降AI（新增）

## Hard Gates

以下规则不可违反：

<!-- 门禁编号跨子节连续：通用 1-15、检测/改写 16-20、LaTeX 21-24，刻意不从 1 开始。 -->
<!-- markdownlint-disable MD029 -->

1. 用户提出论文需求后，必须先索要学校模板或格式要求：
   - Word 模板：`D:\学校论文模板.docx` / `.doc`
   - LaTeX 模板：`D:\学校模板\template.tex`（同目录的 `.cls` / `.sty` / `.bib` 会一并扫描）
   - 或粘贴：格式要求文字描述
   - 如果用户明确说"没有模板，用默认格式"，才能跳过格式提取
   - **必须同时确认产出格式**：Word（`.docx`）还是 LaTeX（`.pdf`）？两者都没有指示时用 AskUserQuestion 问
2. 收到模板或格式描述后，必须先完成格式提取和分析，回传给用户确认，才能进入选题。
3. 选题阶段必须生成 5 个角度 × 每个角度 2 个选题 = 共 10 个选题，等待用户确认后才能继续。
4. 选题确认后，必须先跑文献采集脚本，拿到真实文献列表，再生成大纲。禁止先写大纲再补文献。
5. 参考文献必须全部来自采集脚本的真实输出，禁止 AI 自行编造任何参考文献条目。
6. 文献采集脚本跑完后，必须向用户展示文献核验清单，标注每个条目的来源和可信度，由用户确认保留哪些。
7. 正文中出现的数据、观点、引用必须标注对应文献编号，确保句句有出处。
8. 图表必须通过 HTML 文件渲染为 PNG 插入，禁止使用 Mermaid/PlantUML 占位（课程论文不需要系统架构图）。每篇文章至少 3 张图或表，3000 字短文也须满足。图表生成全程自动完成：写完正文后自动扫描插图位置 → 自动判断图表类型 → 自动生成 HTML → 自动渲染 PNG → 自动插入正文。禁止询问用户"是否需要生成图表""生成什么类型""放在哪里"等问题。
8a. 如果论文内容确实不适合配图（如纯理论思辨且无数据、无流程、无框架），可以跳过图表生成，但必须在最终交付时说明原因。
9. 最终交付物必须包含成稿：Word 链路为 `.docx`，LaTeX 链路为 `.pdf` + `.tex` 源文件；文件名使用论文标题。
10. 如果爬虫脚本运行失败或返回空结果，必须如实告知用户，不得偷偷用 AI 编造文献替代。
11. 生成成稿时，如果用户提供了模板/格式要求，必须使用提取的样式配置，不能退回默认格式。
12. 写作阶段必须应用 D0-D7 降AI约束（参考 `prompts/humanize_constraints.md`，默认 medium 档；参考 `references/ai_pattern_taxonomy.md` 了解 30+ AI 模式；参考 `references/paperpass_patterns.md` 了解 PaperPass 五大致命模式及破解实例；参考 `references/ai_vocabulary_blacklist.md` 了解三级词汇黑名单；参考 `references/term_whitelist.md` 了解术语保护白名单），不得使用禁用的 AI 高频连接词和套话。
13. 成稿前必须运行 `uv run python tools/humanize_check.py <paper.md> --markdown` 验证，句长标准差 ≥ 6、连接词密度 ≤ 8/千字、无红色高风险词、无术语保护违规 才能交付。
14. 所有产物（中间产物 + 最终交付物）必须存放在 `papers/{YYYYMMDD}_{序号}/` 目录下，文件名统一使用 `{YYYYMMDD}_{序号}_{描述}.{ext}` 格式。包括论文 `.md` 终稿、`.docx` 成稿、`.pdf` 成稿、`.tex` 源文件、图表 `.png` 渲染成品。禁止将任何产物散落在用户模板文件所在目录。
15. 降AI检查通过后，必须运行 `prompts/plagiarism_pass.md` 降重流程，对全文中高风险段落（标准定义、文献综述、方法描述、结论汇总）进行深度语义改写，确保通用知识表述不与现有文献雷同。

**LaTeX 链路专属 Hard Gates：**

21. LaTeX 链路必须先跑 `tools/analyze_latex_template.py` 并读取 `latex_profile.json`，确认 `usable_as_shell`；为 `false` 时必须走内置骨架回退，并**如实告知用户未使用其模板及原因**，禁止假装套用了模板。
22. `tools/build_paper_pdf.py` 必须编译成功（`success: true`）才能进入 `delivery`；编译失败不得交付半成品 PDF。
23. 交付前必须检查 `build_report.json`：`compile.missing_deps` 为空（缺图会静默留空图位）、`compile.undefined_refs` 为空（未解析引用会渲染成 `[?]`）、`compile.filled_placeholders` 里若有占位图必须补上真实图表后重编。
24. 若分析器判定 `injection.is_guess: true`（未找到显式占位注释，锚点是推测的），必须核对 `removed_preview` 确认没有误删封面/声明/目录页后再编译。

**检测/改写模式 Hard Gates：**

16. 检测论文时，必须先读取全文再进行 5 维度语义分析，不得跳过任何维度。
17. 检测报告必须包含完整的维度评分表、段落级分析和改写优先级排序。
18. 改写时必须遵循 9 大改写技法优先级（句式重构 > 破解模板 > 碎片化断句 > 论证补全 > 概念具象 > 空行破并列 > 困惑度提升 > 风格断裂 > 添加主语），详见 `references/rewrite_methods.md`。PaperPass 五模式优先使用技法八（碎片化断句）和技法九（空行分段破并列），详见 `references/paperpass_patterns.md`。
19. 改写后必须运行 `uv run python tools/humanize_check.py <file> --markdown` 验证通过（句长标准差 ≥ 6、连接词密度 ≤ 8/千字、无红色高风险词、无术语保护违规）。
20. 检测/改写产物必须放入 `papers/{YYYYMMDD}_{序号}/` 目录，与写作模式产物管理规则一致。

<!-- markdownlint-restore -->

## Execution States

```
intake → format_confirmed → topic_selection → topic_confirmed → literature_collected → outline_confirmed → writing → humanize_check → plagiarism_check → docx_built / pdf_built → delivery
```

1. `intake` — 收集需求信息，确认课程、学科、字数，索要模板或格式要求
2. `format_confirmed` — 已完成模板/格式分析，样式配置已确认
3. `topic_selection` — 已生成 10 个选题，等待用户选择
4. `topic_confirmed` — 用户已选定题目
5. `literature_collected` — 文献爬虫已完成，文献池已确认
6. `outline_confirmed` — 大纲和字数预算已确认
7. `writing` — 正文写作中
8. `humanize_check` — 降AI检查完成（句长/连接词/套话扫描通过）
9. `plagiarism_check` — 降重处理完成（高风险区域深度语义改写通过）
10. `docx_built` / `pdf_built` — 成稿生成完成（Word 链路为 `.docx`；LaTeX 链路为 `.pdf` + `.tex`，且 `build_report.json` 的 `success` 为 `true`）
11. `delivery` — 已交付全部产物

状态约束：

- 未进入 `format_confirmed` 前，禁止生成选题（除非用户明确说用默认格式）
- 未进入 `topic_confirmed` 前，禁止运行文献采集
- 未进入 `literature_collected` 前，禁止生成大纲
- 未进入 `outline_confirmed` 前，禁止写正文
- 未通过 `humanize_check` 前，禁止进入 `plagiarism_check`
- 未通过 `plagiarism_check` 前，禁止进入 `docx_built` / `pdf_built`
- LaTeX 链路未进入 `pdf_built` 前，禁止进入 `delivery`
- 若用户中途更换选题，状态退回 `topic_selection`
- 若用户中途更换模板，状态退回 `format_confirmed`

## Detection Mode Execution States

```
intake → language_detected → doc_loaded → analysis_done → report_done → rewrite_done → verified → delivery
                                                                    ↑                      ↑
                                                            paperpass_feedback ──→ targeted_rewrite
```

1. `intake` — 接收用户提供的论文（.docx 路径 或 粘贴文本）+ 可选学科类型
2. `language_detected` — 语言检测完成（中文/英文自动识别）
3. `doc_loaded` — 文档读取完成（docx_io.py 或文本解析）
4. `analysis_done` — 5 维度语义分析完成
5. `report_done` — 检测报告已输出，用户已选择后续操作
6. `rewrite_done` — 改写完成（仅当用户选择改写时）
7. `paperpass_feedback` — 用户提供 PaperPass 检测报告反馈（新增子状态：从报告提取 50+ 片段，映射到段落，执行针对性 PaperPass 五模式破解）
8. `verified` — humanize_check.py 验证通过
9. `delivery` — 检测报告 / 改写后 .docx 已交付

## Core Flow — 论文写作模式

### 1. 需求收集 (intake)

用户首次提出论文需求时，必须确认：

| 信息项 | 说明 | 示例 |
| -------- | ------ | ------ |
| 课程名称 | 哪门课的期末论文 | 《管理学原理》 |
| 学科领域 | 论文所属学科 | 企业管理 / 计算机科学 / 经济学 |
| 字数要求 | 正文字数范围 | 5000 字 |
| 格式要求 | 引用格式、排版要求 | GB/T 7714 |
| 偏好方向 | 用户感兴趣的方向（可选） | 数字化转型 |

如果用户未提供上述信息，必须主动询问。

### 2. 格式提取 (format_confirmed)

用户首次提出需求时，必须主动索要格式输入与产出格式：

```
我需要了解你学校的论文排版要求和产出格式。

格式方面（三选一）：
A. 提供 Word 论文模板，如：D:\论文模板.docx
B. 提供 LaTeX 论文模板，如：D:\学校模板\template.tex
C. 直接粘贴格式要求，如："标题黑体二号居中，正文宋体小四..."

产出方面：你需要 Word（.docx）还是 PDF？
（选 PDF 需要你本地（或本机）装了 TeX Live；选 PDF 时我会同时交付 .tex 源文件）

如果没有模板也没有格式要求，我会使用默认格式。
```

**如果用户提供了 .docx 模板：**

1. 运行 `uv run python tools/analyze_template.py <模板路径> --json-out style_profile.json --text-out template_text.txt`
2. 读取 `style_profile.json` 获取正则提取的结构化样式
3. 读取 `template_text.txt`，由 LLM 逐段分析全文，发现正则遗漏的格式特征（详见 `prompts/format_extractor.md` 中"LLM 全量文字分析"部分）
4. 合并两套结果，检查冲突项
5. 将格式分析结果回传用户确认

**如果用户粘贴了格式要求：**

1. 按照 `prompts/format_extractor.md` 中的维度解析文字描述
2. 将字号映射（"小四" → 12pt, "二号" → 22pt 等）
3. 构建结构化样式配置
4. 回传格式分析表给用户确认

**如果用户提供了 .tex LaTeX 模板：**

1. 运行：

   ```
   uv run python tools/analyze_latex_template.py <模板路径> \
       --json-out latex_profile.json --text-out template_text.txt
   ```

2. 读取 `latex_profile.json`：引擎、文档类、宏包能力、注入点与替换区间、排版参数、编译探测结论
3. 读取 `template_text.txt`（带行号标注），由 LLM 核对注入区间是否合理、有无正则遗漏的格式特征
4. **重点核对三件事**（详见 `references/latex_template_guide.md`）：
   - `usable_as_shell` 是否为 `true`（否则必须回退内置骨架并告知用户）
   - `injection.is_guess` 是否为 `true`（是则看 `removed_preview` 确认没误删封面/声明页）
   - `styles.heading1.auto_number`（决定是否剥掉 md 标题里自带的"一、"序号）
5. `compile_probe.status` 为 `partial`（仅缺附属文件）时模板仍可用，但**不得**用空 `.bib` 占位
6. 将格式分析结果回传用户确认

**如果用户说"没有模板，用默认格式"：**

- Word 链路：直接使用 `references/default_format.md`
- LaTeX 链路：直接使用 `assets/default_paper.tex`（规范见 `references/default_latex_format.md`）
- 跳过格式提取，进入选题阶段

格式分析回传必须包含：

1. 格式配置表（所有元素：字体、字号、加粗、对齐、行距、缩进）
2. 与默认格式的差异/冲突项
3. 样式配置文件路径（如有）

必须明确等待用户确认格式后，才能进入选题阶段。

### 3. 选题生成 (topic_selection)

基于用户需求，生成 5 个角度 × 每个角度 2 个选题 = 10 个选题。

选题生成规则：

- 每个角度必须是不同的切入点（理论分析 / 案例分析 / 实证研究 / 比较研究 / 应用研究）
- 每个选题必须具体、可操作，不能是空泛标题
- 选题难度应与本科课程论文匹配
- 必须考虑文献可得性（过于冷门的选题会导致文献采集失败）

输出格式：

```
## 选题方案

### 角度一：[切入点名称]
1. **[选题标题]** — [一句话说明研究内容和可行性]
2. **[选题标题]** — [一句话说明研究内容和可行性]

### 角度二：[切入点名称]
...
```

选题展示后，等待用户选择 1 个。

### 4. 文献采集 (literature_collected)

用户确认选题后，立即运行文献采集脚本。

采集流程：

1. 根据选题提取 3-5 组关键词（中文 + 英文）
2. 调用 `tools/literature_scraper.py` 逐关键词搜索
3. 脚本返回结果后，AI 进行去重和相关性初筛
4. 生成文献核验清单展示给用户

文献采集规则：

- 中文文献目标：5-8 篇（优先近 5 年核心期刊）
- 英文文献目标：2-3 篇（优先有 DOI 的期刊论文）
- 总数目标：8-12 篇
- 不达目标时如实告知，不编造

文献核验清单展示格式：

```
| # | 标题 | 作者 | 年份 | 来源 | 可信度 | 相关性 |
|---|------|------|------|------|--------|--------|
| 1 | ... | ... | 2022 | CNKI | ✅高 | ⭐⭐⭐ |
| 2 | ... | ... | 2020 | 百度学术 | ⚠️中 | ⭐⭐ |
```

用户确认后进入大纲阶段。

### 5. 大纲生成 (outline_confirmed)

基于选题和文献池，生成论文大纲。

课程论文标准结构：

1. 摘要 + 关键词
2. 引言
3. 正文（2-3 章，根据字数调整）
4. 结论
5. 参考文献

大纲输出格式：

```
## 论文大纲

### 题目：[论文标题]

### 摘要（约 200 字）

### 关键词：XXX；XXX；XXX

### 一、引言（约 800 字）
- 研究背景
- 研究意义
- 文献综述
- 研究方法

### 二、[正文第一章标题]（约 1500 字）
- 2.1 [小节]
- 2.2 [小节]

### 三、[正文第二章标题]（约 1500 字）
- 3.1 [小节]
- 3.2 [小节]

### 四、结论（约 500 字）

### 参考文献（8-12 篇）

### 字数预算
| 章节 | 目标字数 |
|------|----------|
| 摘要 | 200 |
| 引言 | 800 |
| 正文一 | 1500 |
| 正文二 | 1500 |
| 结论 | 500 |
| **合计** | **4500** |
```

等待用户确认（可修改章节结构、字数分配），确认后进入写作阶段。

### 6. 正文写作 (writing)

按章节顺序逐一写作。每写完一章统计字数，超出预算则压缩。**写完所有正文后，立即自动扫描并生成全部图表（不询问用户）。**

写作规则：

- 每引用一个观点或数据，必须标注文献编号，如 `[1]`
- 正文语言避免 AI 套话（"具有重要意义""实现了良好效果"等）
- 优先用文献中的具体观点和数据，不写空泛结论
- 引文格式：正文中 `[序号]`，参考文献列表用 GB/T 7714 格式
- 图表按章节编号：图 1、图 2、表 1、表 2
- 正文中用 `<!-- chart: 图表描述 -->` 标记需要插图的位置，写完正文后自动生成全部图表并替换占位符

对应资源：

- `prompts/chapter_writer.md` — 章节写作 prompt

### 7. 图表生成

正文中需要图表的地方，**自动判断并生成**科研级 HTML 图表文件，再用 Playwright 渲染为 PNG 插入。**全程自动完成，不许询问用户是否生成、生成什么类型、放在哪里。**

图表类型：

- 数据对比图（柱状图、折线图）
- 流程图
- 理论框架图
- 表格（复杂表格）

图表规则：

- 每篇文章至少 3 张图或表（Hard Gate），在此基础上每 1500-2000 字再增配 1 张，写完正文后自动扫描需要插图的位置并全部生成
- 图题置于图下方，表题置于表上方
- 图表必须与正文内容直接相关
- 图表来源如果是引用文献数据，需在题注中标注 `（数据来源：[X]）`
- 图表类型和内容由 AI 根据上下文自行判断决定，不询问用户

对应资源：

- `prompts/chart_designer.md` — 图表设计 prompt
- `tools/render_html_chart.py` — HTML 渲染脚本

### 8. DOCX 成稿

生成格式规范的 `.docx` 文件。

**如果用户提供了模板/格式要求：**

- 必须使用 `analyze_template.py` 输出的样式配置
- 模板提取的样式已内置在 `generate_paper_docx.py` 中，通过 `-i` 参数指定图表目录：

  ```
  uv run python tools/generate_paper_docx.py paper.md -o 论文标题.docx -i charts/
  ```

- 不得退回默认格式

**如果用户使用默认格式：**

- 默认格式如下：
  - 论文标题：黑体二号加粗居中
  - 摘要/Abstract 标题：黑体小四加粗居中
  - 摘要正文：宋体小四
  - 关键词：黑体小四加粗，"关键词："标签加粗，内容宋体小四
  - 一级标题：黑体小三加粗
  - 二级标题：黑体四号加粗
  - 正文：宋体小四，1.5 倍行距，首行缩进 2 字符
  - 参考文献：宋体五号，悬挂缩进（GB/T 7714 格式）
  - 图题：宋体五号居中
  - 表题：宋体五号居中加粗

对应资源：

- `tools/generate_paper_docx.py` — DOCX 生成脚本
- `tools/analyze_template.py` — 模板格式提取脚本
- `prompts/format_extractor.md` — 格式提取 prompt
- `references/default_format.md` — 默认格式规范

### 8b. PDF 成稿（LaTeX 链路）

当用户选择 PDF 产出时，走三步（详见 `references/latex_template_guide.md`）：

**步骤 1：md → LaTeX 正文**

```
uv run python tools/md_to_latex.py <论文终稿.md> -o body.tex \
    --profile latex_profile.json --refs literature.json \
    --charts-dir charts/ --bib-out refs.bib --report convert_report.json
```

转换器按 profile 自动处理：章节映射、剥离 md 标题序号（模板自动编号时）、
图题在下/表题在上、按模板宏包能力降级表格样式、`[1]/[2-4]/[1,3]` → `\cite{}`、
LaTeX 特殊字符转义（`%` 是最高频事故点）、按模板有无 bib 机制决定 `.bib` 还是内嵌 `thebibliography`。

**退出码为 3 时必须逐条看完 `convert_report.json` 的 `warnings`**：预警包括图片未找到、
残留的 `<!-- chart: -->` 占位符、引用编号在文献表里不存在、md 文献条目与结构化元数据对不上。

**步骤 2：组装 + 编译**

```
uv run python tools/build_paper_pdf.py --body body.tex --profile latex_profile.json \
    --report convert_report.json --bib refs.bib \
    -o "论文标题.pdf" --build-report build_report.json
```

- 模板可用时注入外壳（保留封面/声明/目录，整段替换示例正文与示例摘要）；
  不可用时用 `assets/default_paper.tex` 骨架并在 stderr 明确打印 `[FALLBACK]` 原因
- 缺图片会自动补占位图并重编（避免 graphicx 只警告、图位静默留空），但**必须补回真实图表后重编**
- 编译失败会自动回退骨架重试；两者都失败则退出码 3 并保留 `paper.tex` 与 `.log`

**步骤 3：交付前检查 `build_report.json`**

- `success: true`、`pages` 正常、`compile.missing_deps` 为空、`compile.undefined_refs` 为空
- `compile.filled_placeholders` 非空 ⇒ 有占位图，必须补回真实图表后重编
- `mode: skeleton` ⇒ 未用上用户模板，交付时必须说明原因

对应资源：

- `tools/analyze_latex_template.py` — LaTeX 模板分析（引擎/宏包/注入点/排版参数/编译探测）
- `tools/md_to_latex.py` — Markdown → LaTeX 正文
- `tools/build_paper_pdf.py` — 外壳注入 + latexmk 编译 + 回退
- `assets/default_paper.tex` — 内置兜底骨架（占位符由 build 脚本替换）
- `references/latex_template_guide.md` — 模板处理指南
- `references/default_latex_format.md` — LaTeX 默认格式规范

### 9. 最终检查

交付前检查：

- 所有参考文献是否来自爬虫真实输出
- 正文引用编号是否与参考文献列表一一对应
- 文献核验清单中是否有"不可信"条目
- 字数是否在目标范围内
- 图表编号是否连续
- `.docx` 文件是否真实生成（Word 链路）
- **LaTeX 链路**：`build_report.json` 的 `success` 是否为 `true`、`missing_deps` / `undefined_refs` 是否为空、有无占位图、`.tex` 源文件是否与 PDF 一起交付
- 文件名是否为论文标题
- **降AI检查是否通过**（`uv run python tools/humanize_check.py <paper.md> --markdown`）

### 10. 降AI检查（humanize_check）

在降重处理之前，对完整论文运行降AI验证：

```bash
uv run python tools/humanize_check.py paper.md --markdown --write
```

检查通过标准：

- ✅ 句长标准差 ≥ 6
- ✅ 连接词密度 ≤ 8/千字
- ✅ 无红色高风险词（`references/ai_vocabulary_blacklist.md`）
- ✅ 未检测到 AI 高频套话
- ✅ 无长横线分隔符
- ✅ 无术语保护违规（`references/term_whitelist.md`）

如果未通过：

1. 根据 `humanize_report.md` 中的问题列表逐项修复
2. 对问题段落使用 `prompts/humanize_pass.md` 的改写流程（含模式扫描 + 句式多样化 + 语气自然化 + 逻辑人性化）
3. 重新运行检查直到通过

**仅限用户明确要求时才产出** `humanize_matrix.md`（改动记录矩阵）。
日常课程论文默认只做检查和修复，不产出矩阵。

### 11. 降重处理（plagiarism_check）

降AI检查通过后，对论文运行降重处理（参考 `prompts/plagiarism_pass.md`）：

处理重点：

1. **标准定义段**：重新组织语序，增加上下文特定说明
2. **文献综述段**：分类归纳，融入个人视角，避免逐一罗列
3. **方法描述段**：增加"为什么选择此方法"的动机说明
4. **结论总结段**：用具体发现替换泛泛总结

处理规则：

- 应用表述角度转换（"是什么" → "为什么"；"做什么" → "怎么做"）
- 应用引用归并（多源合并引用，按主题分类）
- 全程保护专业术语（对照 `references/term_whitelist.md`）

**该步骤为必执行步骤**。如果论文内容特殊（如纯原创理论、无标准定义段），可以快速通过但必须在最终交付时说明跳过了哪些区域及原因。

### 12. 中间产物管理

每次运行产生的中间文件必须集中管理，不得散落在用户模板文件所在目录。

**目录规则：**

- 所有中间产物写入 `papers/{YYYYMMDD}_{序号}/` 目录
- 序号从 `001` 起递增，同一次运行共享同一序号
- 示例：`papers/20260621_001/`

**命名规则：**

- 所有文件使用 `{YYYYMMDD}_{序号}_{描述}.{ext}` 前缀
- 示例：`20260621_001_style_profile.json`、`20260621_001_literature_cn.json`

**中间产物清单（必须归档到 papers/）：**

| 产物 | 命名示例 | 产生阶段 |
| ------ | --------- | --------- |
| 样式配置 JSON | `{ts}_style_profile.json` | format_confirmed |
| 模板文本 TXT（脚本自动导出） | `{ts}_template_text.txt` | format_confirmed |
| 中文文献 JSON | `{ts}_literature_cn.json` | literature_collected |
| 英文文献 JSON | `{ts}_literature_en.json` | literature_collected |
| 图表 HTML 源码 | `{ts}_fig1_xxx.html` | writing |
| 文献核验清单 | `{ts}_reference_checklist.md` | delivery |
| **LaTeX 模板配置 JSON** | `{ts}_latex_profile.json` | format_confirmed |
| **LaTeX 模板全文 TXT（带行号标注）** | `{ts}_latex_template_text.txt` | format_confirmed |
| **LaTeX 正文片段** | `{ts}_body.tex` | pdf_built |
| **参考文献 .bib（bibtex 模式）** | `{ts}_refs.bib` | pdf_built |
| **转换报告 JSON** | `{ts}_convert_report.json` | pdf_built |
| **编译报告 JSON** | `{ts}_build_report.json` | pdf_built |

**不清扫的文件（与中间产物一起保留在 papers/ 目录）：**

- 论文 `.md` 终稿 → `papers/{YYYYMMDD}_{序号}/{YYYYMMDD}_{序号}_论文终稿.md`
- 论文 `.docx` 终稿 → `papers/{YYYYMMDD}_{序号}/{YYYYMMDD}_{序号}_论文终稿.docx`
- 论文 `.pdf` 成稿 → `papers/{YYYYMMDD}_{序号}/{YYYYMMDD}_{序号}_论文终稿.pdf`
- LaTeX 源工程 → `papers/{YYYYMMDD}_{序号}/paper.tex`、`refs.bib`、`charts/`
  （学校常要求交可编译源文件，三者必须齐备；`paper.tex` 与图表相对路径已就位，
  用户拿到目录后直接 `latexmk -xelatex paper.tex` 即可重编）
- 图表 `.png` 渲染成品 → `papers/{YYYYMMDD}_{序号}/{YYYYMMDD}_{序号}_fig1_xxx.png`
- 降AI检测报告 → `papers/{YYYYMMDD}_{序号}/{YYYYMMDD}_{序号}_aigc_report.md`
- 改写后论文 → `papers/{YYYYMMDD}_{序号}/{YYYYMMDD}_{序号}_rewritten.docx`

## Core Flow — 检测/改写模式

当用户触发检测/改写模式时，按以下步骤执行。详细指令见 `prompts/detection_pass.md`。

**Step 0：语言检测**

分析输入文本的前 500 字符，自动识别中文/英文，后续步骤使用对应语言模板。

**Step 1：读取文档**

- .docx 文件：`uv run python tools/docx_io.py read "<路径>"`
- 粘贴文本：直接使用

**Step 2：5 维度语义分析**

基于语义理解（非规则匹配）对文本进行 5 维度 AI 特征分析：
句式规整度 (25%) + 逻辑词密度 (20%) + 语态特征 (15%) + 词汇多样性 (15%) + 论证深度 (25%)

评分时考虑学科类型（文科/理工科/医学/经管），使用 `references/detection_principles.md` 中的特化阈值。

**Step 3：输出检测报告**

输出结构化 Markdown 检测报告，包含：

- 整体 AIGC 风险评分 + 维度评分表
- 段落级分析（每段标注评分、问题、风险原因）
- 改写优先级排序表 + 总体建议

**Step 4：询问用户**

使用 AskUserQuestion 询问后续操作：

1. "保存报告为 Markdown 文件"
2. "对高风险段落进行改写并输出 .docx"
3. "仅查看改写建议（不修改文档）"

**Step 5：改写并输出（仅当用户选择时）**

改写遵循 7 大技法优先级（详见 `references/rewrite_methods.md`）：

1. 句式重构 → 2. 破解AI模板 → 3. 论证补全 → 4. 概念具象 → 5. 困惑度提升 → 6. 风格断裂 → 7. 添加主语

使用 `uv run python tools/docx_io.py replace` 逐段替换，保留原始格式。
改写后运行 `uv run python tools/humanize_check.py <file> --markdown` 验证通过。

产物归档到 `papers/{YYYYMMDD}_{序号}/` 目录。

## Style Guardrails

**改写技法参考（详见 `references/rewrite_methods.md` 的 9 大改写技法中英文版）：**

1. **D0 最小干预**：句内微调优先，不推翻原段落逻辑，不搞大段 AI 式重写。保留作者原始逻辑与思维跳跃。
2. **D1 句长**：每 3-4 句必须有一句长度显著偏离（≤10字 或 ≥35字），禁止连续 3 句长度差 < 8 字。
3. **D2 段落结构**：全文使用至少 4 种段落模板（提问驱动/对比判断/因果链/点题收束/正反综合），相邻段落不同模板。
4. **D3 信息密度**：核心段高密度（配具体证据）+ 过渡段低密度（1-2 句过渡），形成"高-低-高"交替。
5. **D4 连接词**：禁用红色高风险词（"首先/其次/最后""综上所述""此外""至关重要""深入探讨"等），控制黄色中风险词密度。每千字连接词 ≤ 6 个。
6. **D5 术语**（heavy 档）：偶尔使用同义学术表达替代标准术语。**必须遵循 `references/term_whitelist.md` 白名单约束。**
7. **D6 逻辑人性化**：打破 AI 式"问题→方法→结论"直线型逻辑，增加背景铺垫、保留探索过程的曲折性、渐进式引入复杂概念。
8. **D7 并列必死**（元规则，2026-06 新增）：任何 3+ 项中文数字/字母序号并列必须拆散或砍掉序号，每 500 字至少 1 处 2-4 字碎片化断句。详见 `references/paperpass_patterns.md`。
9. **禁用套话**："具有重要意义""为……奠定基础""在……的过程中""随着……的快速发展""从而凸显了……"。
10. **禁止长横线**：如 "————"，用空白行或章节标题替代。
11. **术语保护**：数学公式、专业术语缩写、参考文献编号——禁止修改。只调整外围连词和语序。
12. 正文不用"本文""笔者"开篇太多，适当变化句式。
13. 每个观点尽量配文献支撑，不写无出处断言。
14. 致谢可自然一些，但正文不能口语化。

## Resource Map

### Prompts

- `prompts/format_extractor.md` — 格式提取（DOCX 模板 / LaTeX 模板 / 文字描述）
- `prompts/topic_selector.md` — 选题生成
- `prompts/outline_builder.md` — 大纲构建
- `prompts/chapter_writer.md` — 章节写作
- `prompts/chart_designer.md` — 科研图表设计
- `prompts/plagiarism_pass.md` — 独立降重改写 Prompt
- `prompts/detection_pass.md` — AIGC 检测 + 7 技法改写 Prompt（新增）

### Tools

- `tools/analyze_template.py` — DOCX 模板格式提取
- `tools/analyze_latex_template.py` — LaTeX 模板分析（引擎/宏包/注入点/排版参数/编译探测）
- `tools/md_to_latex.py` — Markdown → LaTeX 正文片段
- `tools/build_paper_pdf.py` — LaTeX 外壳注入 + latexmk 编译 + 骨架回退
- `tools/literature_scraper.py` — 多源文献爬虫
- `tools/render_html_chart.py` — HTML 图表渲染
- `tools/diagram_gen.py` — Mermaid 图表渲染（新增：流程图/架构图/UML/ER图）
- `tools/count_words.py` — 字数统计
- `tools/generate_paper_docx.py` — DOCX 成稿（Markdown→DOCX 整体转换）
- `tools/docx_io.py` — DOCX 段落级读写替换（新增：检测/改写模式用）

**运行环境（首次使用必做）**：所有 `tools/` 命令都在**本 skill 仓库根目录**下用 `uv run` 执行。

```bash
uv sync                                  # 建/更新 .venv（必做）
uv run playwright install chromium       # 图表渲染需浏览器（uv sync 不含浏览器）
```

- `pyproject.toml` 为依赖真源，`uv.lock` 锁定版本，`uv sync` 生成 `.venv/`
- `requirements.txt` 是 `uv export` 产物（供不用 uv 的人 `pip install -r`），**不要手工编辑**
- `uv run` 会向上查找 `pyproject.toml`，故在 `papers/<某目录>/` 子目录内执行同样有效
- LaTeX 链路额外需系统安装 TeX Live（含 `latexmk`、`ctex`、`xeCJK`，页数统计用 `pdfinfo`）

### Assets

- `assets/default_paper.tex` — LaTeX 内置兜底骨架（占位符由 build 脚本替换）

### References

- `references/course_paper_structure.md` — 课程论文结构模板
- `references/default_format.md` — 默认格式规范（Word）
- `references/default_latex_format.md` — LaTeX 默认格式规范 + 字号/常见坑速查
- `references/latex_template_guide.md` — LaTeX 模板处理指南（注入点规则 + 实测坑）
- `references/humanize_platforms.md` — 各平台降AI策略
- `references/humanize_matrix_template.md` — humanize_matrix.md 模板
- `references/ai_pattern_taxonomy.md` — 35+ AI 模式分类学（含 S06-S10 PaperPass 五模式）
- `references/paperpass_patterns.md` — PaperPass 五大致命模式 + 破解实例（2026-06 新增）
- `references/ai_vocabulary_blacklist.md` — 三级词汇黑名单
- `references/term_whitelist.md` — 术语保护白名单
- `references/rewrite_methods.md` — 9 大改写技法中英文版（2026-06 新增技法八、九）
- `references/detection_principles.md` — AIGC 检测原理知识库

### Humanize（降AI + 降重）

- `prompts/humanize_constraints.md` — D0-D6 降AI写作约束（含三级词汇体系）
- `prompts/humanize_pass.md` — 独立降AI改写 Prompt（含模式扫描 + 句式/语气/逻辑三维改写）
- `prompts/plagiarism_pass.md` — 独立降重改写 Prompt（含深度语义改写 + 表述角度转换）
- `prompts/detection_pass.md` — AIGC 检测 + 7 技法改写 Prompt（新增）
- `tools/humanize_check.py` — 降AI效果验证脚本（含三级词汇报告 + 术语保护检查 + 密度波动检查）
