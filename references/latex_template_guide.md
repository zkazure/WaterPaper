# LaTeX 模板处理指南

面向 `tools/analyze_latex_template.py` 的使用者，说明学校 LaTeX 模板的常见形态、
注入点识别规则，以及实测踩过的坑。

## 一、学校模板的三种常见形态

| 形态 | 特征 | 本 skill 的处理 |
| ------ | ------ | ---------------- |
| **完整样例论文** | `template.tex` 含 `\documentclass` + 封面 + 声明页 + 目录 + 示例章节 + 参考文献 | ✅ 最佳情况，直接当外壳注入 |
| **只给 .cls / .sty** | 有 `schoolthesis.cls`，但没有可编译的 `main.tex` | ⚠️ 分析器会把 `.cls` 里的 `\RequirePackage` 并进宏包清单，但**定位不到注入点** → 回退内置骨架，继承其排版参数 |
| **只给格式说明** | 一段文字："正文宋体小四，行距 1.5……" | 用内置骨架 + 手工覆盖 `\ctexset` / `\geometry` / `\linespread` |

判断依据是 `latex_profile.json` 的 `usable_as_shell` 字段：为 `false` 时**不要**
硬套模板，直接走回退路径并如实告知用户原因。

## 二、注入点识别规则

分析器按以下优先级挑选正文注入点，并据此算出「替换区间」`[start_line, stop_line)`：

| 优先级 | 类型 | 识别方式 | `is_guess` |
| -------- | ------ | --------- | ----------- |
| 1 | `comment` | 注释内容含"正文 / 论文正文 / 从这里开始 / content / body"等关键词（会自动剥掉 `====` 之类装饰字符） | `false` |
| 2 | `example_section` | 首个**带编号**的 `\section` / `\chapter`（`\section*` 被排除） | `true` |
| 3 | `after_maketitle` | `\maketitle` 之后 | `true` |

区间终点取三者中最早出现的一个：`\bibliography{}` / `\printbibliography` /
`\begin{thebibliography}` / `\end{document}`，并**向前回吞**紧邻的参考文献前导行
（空白、注释、`\bibliographystyle{}`、`\newpage` 等）。

`is_guess: true` 时分析器会在 `diagnostics` 里提示人工核对 —— 因为「取首个带编号
的 section」在某些模板上会命中前置页（如把"摘要"写成 `\section` 而非 `abstract` 环境）。

### 为什么排除 `\section*`

星号章节（`\section*`）历来是前置页：原创性声明、致谢、目录。实测把
`\section*{学位论文原创性声明}` 当作示例正文锚点，会把整页声明**直接删掉**。

### 为什么必须回吞 `\bibliographystyle`

若不回吞，区间终点落在 `\bibliography{refs}` 上，紧邻的 `\bibliographystyle{plain}`
就被划进删除范围 —— 注入后模板的著录格式声明**静默丢失**，全文引用格式随之改变。

## 三、实测踩过的坑

### 1. 模板自带示例章节必须整段替换，不能追加

只追加会让 PDF 里同时出现示例章节和真实正文。分析器算出的 `replace_range` 就是
为此，`removed_preview` 字段可以核对将被删掉的内容。

### 2. 模板自动编号与 md 标题序号会叠加

写作 prompt 产出的 md 标题自带序号（`## 一、引言` / `### 1.1 背景`）。若模板自身
也编号（LaTeX 默认行为，或 `\ctexset{section/number}` 非空），渲染结果是
**`一、 一、引言`**、**`1.1. 1.1 研究背景`**（已用编译产物的 PDF 文本确认）。

分析器因此输出 `styles.headingN.auto_number`：

- `true` → `md_to_latex` 剥掉 md 标题里的序号
- `false`（模板显式写了 `number = {}`）→ 保留 md 序号

只有显式 `number = {}` 才判为手动编号；没有声明则按 LaTeX 默认（自动编号）处理。

### 3. 正文字号不能全文扫描 `\zihao{}`

封面页会塞满 `\zihao{1}`/`\zihao{2}`/`\zihao{4}`（校名、标题、姓名学号）。全文扫描
取"最后一个生效"会拿到封面姓名处的字号当正文默认字号。分析器**只扫 preamble**。

### 4. 编译探测的三种结论

`compile_probe.status`：

- `ok` — 原样编译出 PDF
- `partial` — 报错全是"缺文件"类（缺 `.bib`、缺图片），模板结构本身没问题
- `broken` / `timeout` — 模板确实有问题

`partial` 不等于模板废掉。但**缺失的 `.bib` 不能自动补占位**：空 `.bib` 会让所有
引用静默渲染成 `[?]`，比编译失败更隐蔽。

### 5. 引擎推断

优先级：`% !TEX program = xelatex` magic comment → `CJKutf8` 宏包（→ pdflatex）→
`ctex`/`xeCJK`/`fontspec`/`unicode-math`/`polyglossia`（→ xelatex）→ 文档类名
`ctex*`（→ xelatex）→ 兜底 xelatex。

用 pdflatex 编译 ctex 文档会得到满屏 `Missing character`，看不出真正原因，所以
检测到 `ctex` + pdflatex 时会强制改判为 xelatex 并在 `diagnostics` 里记录。

## 四、常见模板问题的处理清单

| 模板症状 | 处理 |
| --------- | ------ |
| 无 `\begin{document}` / 无 `\end{document}` | 回退内置骨架 |
| 找不到任何注入点 | 回退内置骨架 |
| `\bibliography{refs}` 但同目录无 `refs.bib` | 正常；我们会按该文件名生成 `.bib` |
| 未加载 `graphicx` 但正文要插图 | 自动补 `\usepackage{graphicx}` |
| 未加载 `booktabs` / `tabularx` | 表格自动降级为 `\hline` / `tabular` + `\small` |
| 文档类 `.cls` 不在模板目录 | 依赖系统已装该文档类；编译探测会如实报告 |
| 模板指定了本机没装的字体 | 回退路径用 `\IfFontExistsTF` 包住，不让一个字体名炸掉整篇 |

## 五、产物与调用示例

```bash
# 1. 分析模板（含原样编译探测）
python tools/analyze_latex_template.py template.tex \
    --json-out papers/20260912_001/20260912_001_latex_profile.json \
    --text-out papers/20260912_001/20260912_001_template_text.txt

# 2. md → LaTeX 正文（按 profile 决定章节映射与参考文献机制）
python tools/md_to_latex.py papers/20260912_001/20260912_001_论文终稿.md \
    -o papers/20260912_001/20260912_001_body.tex \
    --profile papers/20260912_001/20260912_001_latex_profile.json \
    --refs papers/20260912_001/20260912_001_literature.json \
    --charts-dir papers/20260912_001/charts \
    --bib-out papers/20260912_001/20260912_001_refs.bib \
    --report papers/20260912_001/20260912_001_convert_report.json

# 3. 组装 + 编译
python tools/build_paper_pdf.py \
    --body papers/20260912_001/20260912_001_body.tex \
    --profile papers/20260912_001/20260912_001_latex_profile.json \
    --report papers/20260912_001/20260912_001_convert_report.json \
    --bib papers/20260912_001/20260912_001_refs.bib \
    -o "papers/20260912_001/基于深度学习的水资源需求预测研究.pdf" \
    --build-report papers/20260912_001/20260912_001_build_report.json
```

三个脚本的退出码：`0` 成功；`1` 致命错误；分析器 `2` 表示模板不可用作外壳；
`md_to_latex` `3` 表示转换完成但有警告；`build_paper_pdf` `3` 表示编译失败。
