#!/usr/bin/env python3
r"""
Markdown 论文 → LaTeX 正文片段转换工具

把论文 md 终稿转成可注入模板的 body.tex（纯正文，不含 \documentclass）。
转换行为由 analyze_latex_template.py 产出的 latex_profile.json 决定：

  · 章节映射        ## 一、引言 → \section，### 1.1 → \subsection ...
  · 自动编号剥离    模板自身编号时剥掉 md 标题里的"一、""1.1"，
                    否则会渲染成"一、 一、引言"（已用编译产物确认）
  · 图表            图题在下、表题在上，编号同样剥离交给 LaTeX
  · 表格            按模板宏包能力在 booktabs / \hline / tabularx 之间降级
  · 引用            [1] [2-4] [1,3,5] → \cite{}；按模板有无参考文献机制
                    决定走 refs.bib 还是内嵌 thebibliography
  · 特殊字符转义    % & _ # $ { } ~ ^ \ ——其中 % 是最高频事故点
                    （论文里"4.3%"不转义会把后半行整段注释掉）

依赖：无第三方依赖（图片宽度启发式需要 Pillow，缺失时退化为固定宽度）。

用法：
    python md_to_latex.py paper.md -o body.tex --profile latex_profile.json
    python md_to_latex.py paper.md -o body.tex --profile p.json --refs refs.json
    python md_to_latex.py paper.md -o body.tex --profile p.json --report report.json

退出码：0 正常；1 致命错误；3 转换完成但有警告（须回读 stderr / report）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 正文里的 LaTeX 特殊字符。% 排第一是因为它最容易被忽略又后果最重。
LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "%": r"\%",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "$": r"\$",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# BibTeX 字段值里的特殊字符（花括号用于保护，不在此表内）
BIB_ESCAPES = {
    "\\": r"\textbackslash{}",
    "%": r"\%",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "$": r"\$",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "{": r"\{",
    "}": r"\}",
}

CJK_RE = re.compile(r"[\u3400-\u9fff\uff00-\uffef]")
REF_ENTRY_RE = re.compile(r"^\[(\d+)\]\s*(.+)$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
CHART_PLACEHOLDER_RE = re.compile(r"<!--\s*chart\s*:.*?-->", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->")
TABLE_SEP_RE = re.compile(r"^[\|\s\-:]+$")
CAPTION_ONLY_RE = re.compile(r"^\*\*(图|表)\s*\d[^*]*\*\*$")

ABSTRACT_HEADINGS = ("摘要", "abstract")
KEYWORD_HEADINGS = ("关键词", "关键字", "keywords", "key words")
REFERENCE_HEADINGS = ("参考文献", "references", "bibliography")

# 章节号：必须带分隔符或空格才算编号，否则"一体化"会被误剥成"体化"
HEADING_NUM_PATTERNS = (
    re.compile(r"^第\s*[一二三四五六七八九十百零\d]+\s*[章节篇]\s*[、.．:：]?\s*"),
    re.compile(r"^[一二三四五六七八九十]{1,3}\s*[、.．,，]\s*"),
    re.compile(r"^\d+(?:\.\d+)*\s*[、.．]?\s+"),
    re.compile(r"^[（(]\s*[一二三四五六七八九十\d]+\s*[）)]\s*"),
)
CAPTION_NUM_RE = re.compile(r"^(图|表)\s*\d+(?:[.\-]\d+)*\s*[:：、.．]?\s*")

# 结构化文献 source_type → BibTeX 条目类型
BIB_TYPE_BY_SOURCE = {
    "journal": "article",
    "conference": "inproceedings",
    "proceedings": "inproceedings",
    "thesis": "phdthesis",
    "dissertation": "phdthesis",
    "book": "book",
    "patent": "misc",
    "report": "techreport",
}


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------

def escape_latex(text: str) -> str:
    r"""转义 LaTeX 特殊字符，但放过已有的反斜杠转义（如作者自己写的 \%）。"""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        out.append(LATEX_ESCAPES.get(ch, ch))
        i += 1
    return "".join(out)


def bib_escape(text: str) -> str:
    return "".join(BIB_ESCAPES.get(ch, ch) for ch in text)


def tex_begin(env: str, opt: str = "") -> str:
    return "\\begin{" + env + "}" + ("[" + opt + "]" if opt else "")


def tex_end(env: str) -> str:
    return "\\end{" + env + "}"


def tex_cmd(name: str, arg: str) -> str:
    return "\\" + name + "{" + arg + "}"


def to_int(text: str) -> int | None:
    """安全取整。调用处虽已用 isdigit/正则守卫，仍在此统一兜住解析异常。"""
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


# 这些字段要额外包一层 {} 保护，否则许多 .bst（plain/abbrv 等）会把
# 标题整体小写：实测 "基于 LSTM 的..." 被渲染成 "基于 lstm 的..."。
BIB_CASE_PROTECTED = ("title", "booktitle", "journal", "school", "institution")


def bib_field_value(key: str, value: str) -> str:
    escaped = bib_escape(value)
    if key in BIB_CASE_PROTECTED:
        return "{" + escaped + "}"
    return escaped


def strip_heading_number(text: str) -> str:
    """剥掉标题里自带的章节号（仅在模板会自动编号时调用）。"""
    for pattern in HEADING_NUM_PATTERNS:
        stripped = pattern.sub("", text, count=1)
        if stripped != text and stripped.strip():
            return stripped.strip()
    return text


def strip_caption_number(text: str) -> str:
    """剥掉图题/表题里自带的"图 1""表 2"，交给 LaTeX 自动编号。"""
    stripped = CAPTION_NUM_RE.sub("", text, count=1).strip()
    return stripped or text


def join_wrapped_lines(lines: list[str]) -> str:
    """拼合被硬换行拆开的同一段。中文直接相连，西文补空格。"""
    if not lines:
        return ""
    out = lines[0]
    for line in lines[1:]:
        prev = out[-1:] if out else ""
        nxt = line[:1]
        if CJK_RE.match(prev) or CJK_RE.match(nxt):
            out += line
        else:
            out += " " + line
    return out


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text))


def looks_like_chapter_heading(text: str) -> bool:
    return any(p.match(text) for p in HEADING_NUM_PATTERNS)


def _norm_heading(text: str) -> str:
    return text.strip().strip("：:*# ").strip().lower()


def classify_heading(text: str) -> str:
    """把标题归类：abstract / keywords / references / normal"""
    norm = _norm_heading(text)
    if any(norm.startswith(k) for k in ABSTRACT_HEADINGS):
        return "abstract"
    if any(norm.startswith(k) for k in KEYWORD_HEADINGS):
        return "keywords"
    if any(norm.startswith(k) for k in REFERENCE_HEADINGS):
        return "references"
    return "normal"


# ---------------------------------------------------------------------------
# 转换器
# ---------------------------------------------------------------------------

class MarkdownToLatex:
    def __init__(
        self,
        profile: dict[str, Any],
        structured_refs: list[dict[str, Any]] | None = None,
        charts_dir: str | None = None,
        md_dir: str | None = None,
        output_dir: str | None = None,
        max_width_fraction: float = 1.0,
    ) -> None:
        self.profile = profile
        self.caps: dict[str, Any] = profile.get("capabilities") or {}
        self.charts_dir = charts_dir
        self.md_dir = md_dir
        self.output_dir = output_dir
        self.max_width_fraction = max_width_fraction
        self.structured_refs = structured_refs or []

        styles = profile.get("styles") or {}
        self.auto_number = bool((styles.get("heading1") or {}).get("auto_number", True))

        self.warnings: list[str] = []
        self.abstract_parts: list[str] = []
        self.keywords = ""
        self.title: str | None = None
        self.refs: list[dict[str, Any]] = []
        self.cite_used: dict[int, int] = {}
        self.multi_key_cites: list[str] = []
        self.undefined_cites: list[int] = []
        self.stats = {
            "sections": 0, "subsections": 0, "subsubsections": 0,
            "figures": 0, "tables": 0, "citations": 0, "chars": 0,
        }

        # 模板已有参考文献机制 → 走 refs.bib；否则正文内嵌 thebibliography
        self.uses_template_bib = bool(
            self.caps.get("bibtex") or self.caps.get("biblatex")
        )
        self.bib_mode = "bibtex" if self.uses_template_bib else "thebibliography"

        self.body: list[str] = []
        self.in_abstract = False
        self.in_keywords = False
        self.in_references = False

    # -- 引用键 ------------------------------------------------------------
    @staticmethod
    def key_for(n: int) -> str:
        return f"lit{n}"

    @property
    def ref_numbers(self) -> set[int]:
        return {r["n"] for r in self.refs}

    # -- 行内转换 ----------------------------------------------------------
    def inline(self, text: str) -> str:
        stash: list[str] = []

        def put(payload: str) -> str:
            stash.append(payload)
            return f"\x00{len(stash) - 1}\x00"

        def math_repl(m: re.Match[str]) -> str:
            return put(m.group(0))

        def code_repl(m: re.Match[str]) -> str:
            return put(r"\texttt{" + escape_latex(m.group(1)) + "}")

        def link_repl(m: re.Match[str]) -> str:
            label, url = m.group(1), m.group(2)
            if self.caps.get("hyperref"):
                return put(r"\href{" + escape_latex(url) + "}{" + escape_latex(label) + "}")
            return put(escape_latex(label))

        def cite_repl(m: re.Match[str]) -> str:
            nums: list[int] = []
            for part in m.group(1).split(","):
                part = part.strip()
                if "-" in part:
                    lo, _, hi = part.partition("-")
                    lo_i, hi_i = to_int(lo.strip()), to_int(hi.strip())
                    if lo_i is not None and hi_i is not None:
                        nums.extend(range(lo_i, hi_i + 1))
                        continue
                num = to_int(part)
                if num is not None:
                    nums.append(num)
                else:
                    return m.group(0)
            # 不在文献表里的方括号数字（如 [2024] 年份）原样保留
            if not nums or not all(n in self.ref_numbers for n in nums):
                return m.group(0)
            for n in nums:
                self.cite_used[n] = self.cite_used.get(n, 0) + 1
                self.stats["citations"] += 1
            keys = ",".join(self.key_for(n) for n in nums)
            if len(nums) > 1:
                self.multi_key_cites.append(keys)
            return put(r"\cite{" + keys + "}")

        # 保护顺序：数学 → 代码 → 链接 → 引用（都不允许被转义）
        text = re.sub(r"\$\$[^$]+\$\$|\$[^$\n]+\$", math_repl, text)
        text = re.sub(r"`([^`]+)`", code_repl, text)
        text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link_repl, text)
        text = re.sub(r"\[(\d+(?:\s*[-,]\s*\d+)*)\]", cite_repl, text)

        text = escape_latex(text)
        text = re.sub(r"\*\*([^*\n]+)\*\*", r"\\textbf{\1}", text)
        text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\\emph{\1}", text)

        def restore(m: re.Match[str]) -> str:
            idx = to_int(m.group(1))
            if idx is None or not 0 <= idx < len(stash):
                return ""
            return stash[idx]

        return re.sub(r"\x00(\d+)\x00", restore, text)

    # -- 图片 --------------------------------------------------------------
    def resolve_image(self, rel: str) -> tuple[str, str] | None:
        """返回 (磁盘真实路径, 写进 tex 的路径)。

        两者必须分开：宽度启发式要用真实路径去读 PNG，而写进 tex 的
        应该是相对 body.tex 的路径（否则交付的 .tex 换目录就断）。
        """
        candidates: list[Path] = []
        if self.charts_dir:
            candidates.append(Path(self.charts_dir) / Path(rel).name)
        if self.md_dir:
            candidates.append(Path(self.md_dir) / rel)
        candidates.append(Path(rel))
        for cand in candidates:
            if not cand.exists():
                continue
            real = str(cand)
            tex_path = real
            if self.output_dir:
                try:
                    tex_path = os.path.relpath(cand, self.output_dir)
                except ValueError:
                    tex_path = real
            return real, tex_path
        return None

    def image_width(self, path: str, is_table: bool) -> str:
        fraction = 0.85
        try:
            from PIL import Image

            with Image.open(path) as im:
                w_px, h_px = im.size
            if h_px > w_px * 1.5:
                fraction = 0.6
            elif w_px > h_px * 1.5:
                fraction = 0.98
        except (ImportError, OSError, ValueError):
            # 缺 Pillow / 图片损坏 → 退化为固定宽度
            fraction = 0.8 if not is_table else 0.9
        return f"{round(min(fraction, self.max_width_fraction), 2)}"

    def render_image(self, alt: str, rel: str) -> str:
        found = self.resolve_image(rel)
        is_table = alt.strip().startswith("表")
        if found is None:
            self.warnings.append(f"图片未找到: {rel}（alt={alt}）")
            return self.inline(f"[缺失图表: {alt or rel}]")
        real_path, tex_path = found

        caption = strip_caption_number(alt) if alt.strip() else ""
        width = self.image_width(real_path, is_table)
        env = "table" if is_table else "figure"
        # 表题在上、图题在下（与 DOCX 链路一致）
        parts = [tex_begin(env, "htbp"), r"\centering"]
        if is_table and caption:
            parts.append(tex_cmd("caption", self.inline(caption)))
        parts.append(
            r"\includegraphics[width=" + width + r"\textwidth]{" + tex_path + "}"
        )
        if not is_table and caption:
            parts.append(tex_cmd("caption", self.inline(caption)))
        parts.append(tex_end(env))
        self.stats["tables" if is_table else "figures"] += 1
        return "\n".join(parts)

    # -- 表格 --------------------------------------------------------------
    def render_table(self, rows: list[str], caption: str = "") -> str:
        header = [c.strip() for c in rows[0].strip("|").split("|")]
        data_start = 1
        aligns = ["l"] * len(header)
        if len(rows) > 1 and TABLE_SEP_RE.match(rows[1]):
            data_start = 2
            for i, cell in enumerate(rows[1].strip("|").split("|")):
                cell = cell.strip()
                if i >= len(aligns):
                    break
                if cell.startswith(":") and cell.endswith(":"):
                    aligns[i] = "c"
                elif cell.endswith(":"):
                    aligns[i] = "r"
        body_rows = [
            [c.strip() for c in r.strip("|").split("|")] for r in rows[data_start:]
        ]
        ncols = len(header)
        wide = ncols >= 5

        use_tabularx = bool(self.caps.get("tabularx")) and wide
        if use_tabularx:
            spec = aligns[0] + "X" * (ncols - 1)
            begin = "\\begin{tabularx}{\\textwidth}{" + spec + "}"
            end = tex_end("tabularx")
        else:
            begin = "\\begin{tabular}{" + "".join(aligns) + "}"
            end = tex_end("tabular")

        rule_top = r"\toprule" if self.caps.get("booktabs") else r"\hline"
        rule_mid = r"\midrule" if self.caps.get("booktabs") else r"\hline"
        rule_bot = r"\bottomrule" if self.caps.get("booktabs") else r"\hline"

        out = [tex_begin("table", "htbp"), r"\centering"]
        if caption:
            out.append(tex_cmd("caption", self.inline(strip_caption_number(caption))))
        if wide:
            out.append(r"\small")
        out.append(begin)
        out.append(rule_top)
        out.append(" & ".join(self.inline(c) for c in header) + r" \\")
        out.append(rule_mid)
        for row in body_rows:
            cells = [self.inline(c) for c in row]
            while len(cells) < ncols:
                cells.append("")
            out.append(" & ".join(cells[:ncols]) + r" \\")
        out.append(rule_bot)
        out.append(end)
        out.append(r"\end{table}")
        self.stats["tables"] += 1
        return "\n".join(out)

    # -- 参考文献 ----------------------------------------------------------
    def add_ref_entry(self, num: int, text: str) -> None:
        for ref in self.refs:
            if ref["n"] == num:
                ref["text"] = (ref["text"] + " " + text).strip()
                return
        self.refs.append({"n": num, "key": self.key_for(num), "text": text})

    def render_thebibliography(self) -> str:
        width = "99" if len(self.refs) < 100 else "999"
        out = [tex_begin("thebibliography") + "{" + width + "}"]
        for ref in sorted(self.refs, key=lambda r: r["n"]):
            out.append(
                tex_cmd("bibitem", ref["key"]) + " " + self.inline(ref["text"])
            )
        out.append(tex_end("thebibliography"))
        return "\n".join(out)

    def build_bib(self) -> str:
        """把文献表转成 refs.bib。有结构化元数据就用它，否则退化 @misc + note。"""
        blocks: list[str] = []
        for ref in sorted(self.refs, key=lambda r: r["n"]):
            idx = ref["n"] - 1
            meta = self.structured_refs[idx] if 0 <= idx < len(self.structured_refs) else None
            if not isinstance(meta, dict) or not meta.get("title"):
                self.warnings.append(
                    "文献[{}]无结构化元数据，refs.bib 退化为 @misc（原文完整保留在 note 字段）".format(
                        ref["n"])
                )
                blocks.append(
                    "@misc{{{},\n  note = {{{}}},\n}}".format(
                        ref["key"], bib_escape(ref["text"]))
                )
                continue
            source_type = str(meta.get("source_type", "")).lower()
            entry_type = BIB_TYPE_BY_SOURCE.get(source_type, "misc")
            fields: list[tuple[str, str]] = []
            authors = meta.get("authors") or []
            if authors:
                fields.append(("author", " and ".join(str(a) for a in authors)))
            fields.append(("title", str(meta["title"])))
            if entry_type == "inproceedings":
                if meta.get("source"):
                    fields.append(("booktitle", str(meta["source"])))
            elif entry_type == "phdthesis":
                if meta.get("source"):
                    fields.append(("school", str(meta["source"])))
            elif entry_type == "techreport":
                if meta.get("source"):
                    fields.append(("institution", str(meta["source"])))
            else:
                if meta.get("source"):
                    fields.append(("journal", str(meta["source"])))
            if meta.get("year"):
                fields.append(("year", str(meta["year"])))
            for src_key, bib_key in (("volume", "volume"), ("number", "number")):
                if meta.get(src_key):
                    fields.append((bib_key, str(meta[src_key])))
            if meta.get("pages"):
                pages = str(meta["pages"]).replace("--", "-")
                pages = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "--", pages)
                fields.append(("pages", pages))
            if meta.get("doi"):
                doi = str(meta["doi"]).replace("https://doi.org/", "").strip()
                if doi:
                    fields.append(("doi", doi))
            lang = "zh" if CJK_RE.search(str(meta["title"])) else "en"
            fields.append(("language", lang))

            rendered = "".join(
                f"  {k} = {{{bib_field_value(k, v)}}},\n" for k, v in fields
            )
            blocks.append("@{}{{{},\n{}}}".format(entry_type, ref["key"], rendered))
        return "\n\n".join(blocks) + "\n"

    # -- 主流程 ------------------------------------------------------------
    def prescan_references(self, lines: list[str]) -> None:
        """一遍预扫：先拿到文献表编号，行内引用才敢把 [k] 认成 \\cite。"""
        in_refs = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                in_refs = classify_heading(heading) == "references"
                continue
            if not in_refs or not stripped:
                continue
            m = REF_ENTRY_RE.match(stripped)
            num = to_int(m.group(1)) if m else None
            if m is not None and num is not None:
                self.add_ref_entry(num, m.group(2).strip())
            elif self.refs:
                self.refs[-1]["text"] = (self.refs[-1]["text"] + " " + stripped).strip()
        # 结构化文献可补齐 md 里没列出的编号
        for i in range(len(self.structured_refs)):
            if (i + 1) not in self.ref_numbers:
                meta = self.structured_refs[i]
                title = str(meta.get("title", "")) if isinstance(meta, dict) else ""
                self.refs.append({
                    "n": i + 1, "key": self.key_for(i + 1),
                    "text": title or f"（结构化文献条目 {i + 1}）",
                })

    def detect_title(self, lines: list[str]) -> None:
        level1 = [
            (i, ln[2:].strip())
            for i, ln in enumerate(lines)
            if ln.startswith("# ") and not ln.startswith("## ")
        ]
        if not level1:
            return
        if len(level1) == 1 and not looks_like_chapter_heading(level1[0][1]):
            self.title = level1[0][1]
        else:
            # 写作 prompt 里的 `# 一、标题` 变体：全部当章节，标题另给
            self.title = None
            self.warnings.append(
                f"文档含 {len(level1)} 个一级标题且形如章节（写作 prompt 的 `# 一、` 变体），"
                "已全部按章节处理；论文标题需由 --title 或模板提供"
            )

    def _check_ref_metadata(self) -> None:
        """校验 md 文献条目与结构化元数据是否指向同一篇。

        编号 → 元数据的映射是按位置下标（n-1）得的，若记录来自不同筛选口径
        （如 cn/en 两个文件按 key_before 拼接），就会张冠李戴 —— 这直接威胁
        "参考文献必须真实可核验"这条硬门槛，所以必须报警。
        """
        for ref in self.refs:
            idx = ref["n"] - 1
            if not 0 <= idx < len(self.structured_refs):
                continue
            meta = self.structured_refs[idx]
            if not isinstance(meta, dict):
                continue
            title = str(meta.get("title", "")).strip()
            if not title:
                continue
            probes = re.findall(r"[A-Za-z]{4,}|[\u4e00-\u9fff]{4,}", title)
            probe = max(probes, key=len) if probes else ""
            if probe and probe.lower() not in ref["text"].lower():
                self.warnings.append(
                    "文献[{}] 的 md 文本与结构化元数据标题（{}…）对不上，"
                    "可能不是同一篇 —— 请核对编号顺序与文献池拼接口径".format(
                        ref["n"], title[:24])
                )

    def convert(self, md_text: str) -> str:
        lines = md_text.split("\n")
        self.prescan_references(lines)
        self.detect_title(lines)

        level1_as_sections = self.title is None
        pending_caption = ""
        i = 0
        n = len(lines)
        while i < n:
            raw = lines[i]
            stripped = raw.strip()

            if not stripped:
                i += 1
                continue

            # ---- 未替换的图表占位符 ----
            if CHART_PLACEHOLDER_RE.search(stripped):
                self.warnings.append(
                    f"L{i + 1} 残留未替换的图表占位符：{stripped[:80]}"
                )
                i += 1
                continue
            if HTML_COMMENT_RE.search(stripped):
                i += 1
                continue

            # ---- 标题 ----
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading = stripped[level:].strip()
                kind = classify_heading(heading)
                if level == 1 and not level1_as_sections:
                    i += 1  # 已作为论文标题提取，不进正文
                    continue
                if kind == "abstract":
                    self.in_abstract, self.in_keywords, self.in_references = True, False, False
                elif kind == "keywords":
                    self.in_abstract, self.in_keywords, self.in_references = False, True, False
                    # 仅当标题里真的带冒号（如 `## 关键词：a；b`）才当场取值；
                    # 否则值在下一行，交给段落分支收。去掉这个冒号判定，
                    # 标题字面量"关键词"会被当成关键词，下一行就泄漏进正文了。
                    if "：" in heading or ":" in heading:
                        tail = re.sub(r"^[^：:]*[：:]", "", heading).strip()
                        if tail:
                            self.keywords = tail
                elif kind == "references":
                    self.in_abstract, self.in_keywords, self.in_references = False, False, True
                else:
                    self.in_abstract, self.in_keywords, self.in_references = False, False, False
                    # `#### x` → subsubsection；`### x` → subsection；`## x` → section
                    depth = min(max(level - 1, 1), 4)
                    text = strip_heading_number(heading) if self.auto_number else heading
                    cmd = {1: "section", 2: "subsection", 3: "subsubsection"}.get(depth, "paragraph")
                    self.stats[{"section": "sections", "subsection": "subsections"}.get(
                        cmd, "subsubsections")] += 1
                    self.body.append(tex_cmd(cmd, self.inline(text)))
                i += 1
                continue

            # ---- 表格题注（紧跟表格块之前）----
            if CAPTION_ONLY_RE.match(stripped):
                pending_caption = stripped.strip("*").strip()
                i += 1
                continue

            # ---- 图片 ----
            img = IMAGE_RE.match(stripped)
            if img:
                self.body.append(self.render_image(img.group(1), img.group(2)))
                i += 1
                continue

            # ---- 表格 ----
            if stripped.startswith("|") and stripped.endswith("|"):
                rows: list[str] = []
                while i < n and lines[i].strip().startswith("|"):
                    rows.append(lines[i].strip())
                    i += 1
                if len(rows) >= 2:
                    self.body.append(self.render_table(rows, pending_caption))
                pending_caption = ""
                continue

            # ---- 分隔线 ----
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
                i += 1
                continue

            # ---- 参考文献条目 ----
            if self.in_references:
                i += 1  # 文献表已由 prescan 收走，正文里只放 thebibliography
                continue

            # ---- 列表 ----
            list_m = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", stripped)
            if list_m:
                ordered = bool(re.match(r"^\d", list_m.group(1)))
                env = "enumerate" if ordered else "itemize"
                items: list[str] = [list_m.group(2)]
                i += 1
                while i < n:
                    nxt = lines[i].strip()
                    nm = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", nxt)
                    if not nm:
                        break
                    items.append(nm.group(2))
                    i += 1
                block = [tex_begin(env)]
                block += ["  \\item " + self.inline(it) for it in items]
                block.append(tex_end(env))
                self.body.append("\n".join(block))
                continue

            # ---- 引用块 ----
            if stripped.startswith(">"):
                quoted: list[str] = []
                while i < n and lines[i].strip().startswith(">"):
                    quoted.append(lines[i].strip().lstrip(">").strip())
                    i += 1
                self.body.append(
                    f"\\begin{{quote}}\n{self.inline(join_wrapped_lines(quoted))}\n\\end{{quote}}"
                )
                continue

            # ---- 普通段落（合并被硬换行拆开的同一段）----
            para = [stripped]
            i += 1
            while i < n:
                nxt = lines[i].strip()
                if not nxt or nxt.startswith(("#", "|", ">", "![")):
                    break
                if re.match(r"^([-*+]|\d+[.)])\s+", nxt):
                    break
                if CAPTION_ONLY_RE.match(nxt) or HTML_COMMENT_RE.search(nxt):
                    break
                para.append(nxt)
                i += 1
            text = self.inline(join_wrapped_lines(para))
            if not text.strip():
                continue
            if self.in_keywords and not self.keywords:
                self.keywords = re.sub(r"^[^：:]*[：:]\s*", "", text).strip()
                self.in_keywords = False
            elif self.in_abstract:
                self.abstract_parts.append(text)
            else:
                self.body.append(text)

        self.finalize()
        return "\n\n".join(self.body) + "\n"

    def finalize(self) -> None:
        if self.uses_template_bib and self.refs:
            pass  # refs.bib 由 build 阶段写盘，正文不放 thebibliography
        elif self.refs:
            self.body.append(self.render_thebibliography())

        self._check_ref_metadata()

        if self.bib_mode == "bibtex":
            self.warnings.append(
                "走 refs.bib：正文编号将由模板的 \\bibliographystyle 重排，"
                "PDF 里的编号可能不等于 md 里的 [n] 顺序（配对关系不受影响，"
                "参考文献列表顺序会同步改变）"
            )
            if self.multi_key_cites and not self.caps.get("cite"):
                self.warnings.append(
                    "模板未加载 cite 宏包，多文献引用不会升序排列"
                    "（实测渲染成 [3, 2] 这类降序）；GB/T 7714 要求升序，"
                    "建议模板改用 gbt7714 样式或加载 cite/natbib 宏包"
                )

        undefined = sorted(set(self.cite_used) - self.ref_numbers)
        if undefined:
            self.undefined_cites = undefined
            self.warnings.append(
                "正文引用了文献表中不存在的编号: {}（会渲染成 ??）".format(
                    ", ".join(str(u) for u in undefined))
            )
        unused = sorted(self.ref_numbers - set(self.cite_used))
        if unused:
            self.warnings.append(
                "文献表里未被正文引用的条目: {}（BibTeX 下不会出现在参考文献里）".format(
                    ", ".join(str(u) for u in unused))
            )
        self.stats["chars"] = count_cjk("\n".join(self.body))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def report_of(converter: MarkdownToLatex, md_path: Path, body_path: Path) -> dict[str, Any]:
    return {
        "source_md": str(md_path),
        "body_tex": str(body_path),
        "title": converter.title,
        "abstract": "\n\n".join(converter.abstract_parts),
        "keywords": converter.keywords,
        "bib_mode": converter.bib_mode,
        "uses_template_bib": converter.uses_template_bib,
        "auto_number": converter.auto_number,
        "refs": converter.refs,
        "cite_used": {converter.key_for(k): v for k, v in sorted(converter.cite_used.items())},
        "undefined_citations": converter.undefined_cites,
        "warnings": converter.warnings,
        "stats": converter.stats,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Markdown 论文 → LaTeX 正文片段")
    _ = parser.add_argument("markdown", help="论文 md 路径")
    _ = parser.add_argument("--output", "-o", required=True, help="输出 body.tex 路径")
    _ = parser.add_argument("--profile", required=True, help="latex_profile.json 路径")
    _ = parser.add_argument("--refs", help="literature_*.json（结构化文献池）")
    _ = parser.add_argument("--charts-dir", help="图表 PNG 所在目录")
    _ = parser.add_argument("--bib-out", help="refs.bib 输出路径（模板有 bib 机制时）")
    _ = parser.add_argument("--report", help="转换报告 JSON 输出路径")
    _ = parser.add_argument("--title", help="论文标题（md 里没有 # 标题时使用）")
    _ = parser.add_argument("--max-width", type=float, default=1.0,
                            help="图片最大宽度占 \\textwidth 比例（默认 1.0）")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    md_path = Path(args.markdown).expanduser()
    if not md_path.exists():
        print(f"[ERROR] md 文件不存在: {md_path}", file=sys.stderr)
        return 1
    profile_path = Path(args.profile).expanduser()
    if not profile_path.exists():
        print(f"[ERROR] profile 不存在: {profile_path}", file=sys.stderr)
        return 1

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 无法解析 profile: {profile_path} — {exc}", file=sys.stderr)
        return 1
    structured: list[dict[str, Any]] = []
    if args.refs:
        refs_path = Path(args.refs).expanduser()
        if refs_path.exists():
            try:
                loaded = json.loads(refs_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[ERROR] 无法解析文献池: {refs_path} — {exc}", file=sys.stderr)
                return 1
            structured = loaded if isinstance(loaded, list) else []
        else:
            print(f"[WARN] 文献池不存在: {refs_path}", file=sys.stderr)

    converter = MarkdownToLatex(
        profile,
        structured_refs=structured,
        charts_dir=args.charts_dir,
        md_dir=str(md_path.parent),
        output_dir=str(Path(args.output).parent),
        max_width_fraction=args.max_width,
    )
    md_text = md_path.read_text(encoding="utf-8")
    body = converter.convert(md_text)
    if args.title:
        converter.title = args.title

    body_path = Path(args.output)
    body_path.parent.mkdir(parents=True, exist_ok=True)
    _ = body_path.write_text(body, encoding="utf-8")

    bib_path = None
    if converter.bib_mode == "bibtex" and args.bib_out:
        bib_path = Path(args.bib_out)
        bib_path.parent.mkdir(parents=True, exist_ok=True)
        _ = bib_path.write_text(converter.build_bib(), encoding="utf-8")

    report = report_of(converter, md_path, body_path)
    report["bib_file"] = str(bib_path) if bib_path else None
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _ = report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] 正文已写入: {body_path}")
    if bib_path:
        print(f"[OK] 参考文献已写入: {bib_path}")
    st = converter.stats
    print("     章节 {sections} / 小节 {subsections} / 图 {figures} / 表 {tables} / "
          "引用 {citations} 次 / 中文 {chars} 字".format(**st))
    print("     参考文献 {} 条，模式：{}".format(
        len(converter.refs),
        "refs.bib（模板已有参考文献机制）" if converter.uses_template_bib
        else "正文内嵌 thebibliography（模板无参考文献机制）",
    ))
    print("     模板自动编号：{}".format("是，已剥离 md 标题序号" if converter.auto_number else "否，保留 md 序号"))

    if converter.warnings:
        print(f"\n[WARN] {len(converter.warnings)} 条警告：", file=sys.stderr)
        for w in converter.warnings:
            print(f"  - {w}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
