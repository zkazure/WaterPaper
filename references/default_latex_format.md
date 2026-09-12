# LaTeX 默认格式规范

`assets/default_paper.tex` 的排版依据，也是 `references/default_format.md`（DOCX 默认格式）
的 LaTeX 等价物。当用户模板残缺、或只给了文字格式要求时，由此骨架兜底。

## 字号对照（ctex `\zihao`）

| 中文号数 | `\zihao` | 约合 |
| --------- | ---------- | ------ |
| 一号 | `1` | 26pt |
| 小一 | `-1` | 24pt |
| 二号 | `2` | 22pt |
| 小二 | `-2` | 18pt |
| 三号 | `3` | 16pt |
| 小三 | `-3` | 15pt |
| 四号 | `4` | 14pt |
| 小四 | `-4` | 12pt |
| 五号 | `5` | 10.5pt |
| 小五 | `-5` | 9pt |

负号表示"小"号。**注意 `-4` 不是"四号减一档"，而是"小四"**。

## 页面与正文

| 属性 | 值 | 对应 LaTeX |
| ------ | ----- | ----------- |
| 纸张 | A4 | `\documentclass[12pt,a4paper]{ctexart}` |
| 边距 | 上下 2.54cm，左右 3.18cm | `\usepackage[top=...,bottom=...,left=...,right=...]{geometry}` |
| 正文 | 宋体小四，1.5 倍行距，首行缩进 2 字符 | `\linespread{1.5}` + `\setlength{\parindent}{2em}` |
| 标题层级 | 黑体，二号 / 小三 / 四号 / 小四 | `\ctexset{section={format=\zihao{-3}\heiti}}` 等 |

## 章节格式

```latex
\ctexset{
  section = {
    format = \zihao{-3}\heiti,
    name   = {,、},            % 编号后加顿号 → "一、引言"
    number = \chinese{section},% 中文数字编号
    beforeskip = 12pt,
    afterskip  = 6pt,
  },
  subsection = {
    format = \zihao{4}\heiti,
    name   = {,.},             % → "1.1 小节"（点号 + 空格）
    number = \arabic{section}.\arabic{subsection},
  },
  subsubsection = { format = \zihao{-4}\heiti },
}
```

## 摘要与关键词

ctexart **没有内置 `\keywords` 命令**，必须自己定义（学校模板通常也自己定义）：

```latex
\newcommand{\keywords}[1]{%
  \par\vspace{0.8em}\noindent{\heiti\zihao{-4}关键词：}{\zihao{-4}#1}%
}
```

摘要标题的字体字号**不能**用 `\renewcommand{\abstractnamefont}` —— ctexart 里没有
这个命令，`\renewcommand` 会以 "Command \abstractnamefont undefined" 直接编译失败。
实测可行写法是把格式写进 `\abstractname`：

```latex
\ctexset{abstractname = {\heiti\zihao{-4}摘要}}   % ctexart 默认已居中
```

## 图表

| 属性 | 值 | 对应 LaTeX |
|------|-----|-----------|
| 图题 | 宋体五号居中，置于图**下方** | `\caption` 放在 `\includegraphics` 之后 |
| 表题 | 宋体五号加粗居中，置于表**上方** | `\caption` 放在 `tabular` 之前 |

```latex
\usepackage{caption}
\captionsetup[figure]{font=small,labelfont=small,labelsep=colon,position=below}
\captionsetup[table]{font={small,bf},labelfont={small,bf},labelsep=colon,position=above}
```

三线表（模板加载了 `booktabs` 时）：

```latex
\begin{tabular}{lll}
\toprule
表头 & 列二 & 列三 \\
\midrule
数据 & 数据 & 数据 \\
\bottomrule
\end{tabular}
```

## 参考文献

模板没有参考文献机制时，正文内嵌 `thebibliography`（其内部会自带 `\section*{\refname}`
标题，**不要再手写"参考文献"标题**，否则会出现两个）：

```latex
\begin{thebibliography}{99}
\bibitem{lit1} 李四, 王五. 基于 LSTM 的城市用水量短期预测[J]. 水利学报, 2024, 55(3): 301-310.
\end{thebibliography}
```

宽度参数 `{99}` 是标签预留宽度：条数 < 100 用 `99`，否则用 `999`。

## 常见编译陷阱

| 现象 | 原因 | 处理 |
| ------ | ------ | ------ |
| `Missing \begin{document}`，且报在正文首行 | 正文被注入到了 `\documentclass` 之前（如占位符替换命中了文档注释） | 检查占位符是否在文件里出现多次 |
| 英文大写被改成小写（`LSTM` → `lstm`） | `.bst` 样式对 `title` 做大小写折叠 | 值外面多包一层 `{}`：`title = {{...}}` |
| 中文全是 `Missing character` | 用 pdflatex 编译了 ctex 文档 | 改用 xelatex |
| 引用渲染成 `[?]` | `.bib` 缺失或 `\bibliography` 没被保留 | 确认 `.bib` 落盘文件名与 `\bibliography{X}` 的 `X` 一致 |
| 多文献引用降序（`[3, 2]`） | `.bst` 不做排序 | 加载 `cite` 宏包，或改用 `gbt7714` 样式 |
| 图位空白、但编译不报错 | `graphicx` 缺图只给 `LaTeX Warning`，PDF 照常产出 | 检查日志里的 `File ... not found` |
