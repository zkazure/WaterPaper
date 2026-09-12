#!/usr/bin/env python3
"""
LaTeX 模板分析工具

解析学校 LaTeX 论文模板，提取：
  1. 编译引擎（magic comment / 宏包推断）
  2. 文档类与宏包清单（含同目录 .cls/.sty 的 \\RequirePackage）
  3. 排版参数（\\zihao / \\linespread / \\geometry / \\ctexset / \\parindent）
  4. 外壳结构（preamble / 封面段 / 正文段 / 尾部）
  5. 正文注入锚点与替换区间（行号）
  6. 宏包能力（graphicx / booktabs / hyperref / bibtex / biblatex ...）
  7. 原样编译探测结论（ok / partial / broken / skipped）

依赖：无第三方 Python 依赖；编译探测需要系统安装 TeX Live + latexmk。

用法：
    python analyze_latex_template.py template.tex
    python analyze_latex_template.py template.tex --json-out latex_profile.json
    python analyze_latex_template.py template.tex --json-out p.json --text-out template_text.txt
    python analyze_latex_template.py template.tex --no-probe
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 正文注入点的显式占位注释关键词（注释内容里含这些词即认为是注入锚点）
PLACEHOLDER_KEYWORDS = (
    "正文",
    "论文正文",
    "从这里开始",
    "从这开始",
    "在此处撰写",
    "以下为正文",
    "你的正文",
    "content",
    "body",
    "main text",
)

# 章节命令（用于定位模板自带的示例章节）
SECTION_COMMANDS = ("chapter", "section", "part")

# 引擎推断：这些宏包/文档类要求 XeLaTeX 或 LuaLaTeX
XE_ONLY_PACKAGES = ("ctex", "xeCJK", "fontspec", "unicode-math", "polyglossia")

# 能力 → 触发它的宏包名集合
CAPABILITY_PACKAGES: dict[str, tuple[str, ...]] = {
    "graphicx": ("graphicx", "graphics"),
    "booktabs": ("booktabs",),
    "tabularx": ("tabularx",),
    "longtable": ("longtable",),
    "hyperref": ("hyperref",),
    "caption": ("caption",),
    "amsmath": ("amsmath", "mathtools"),
    "natbib": ("natbib",),
    "biblatex": ("biblatex",),
    "xcolor": ("xcolor", "color"),
    "enumitem": ("enumitem",),
    "makecell": ("makecell",),
    "threeparttable": ("threeparttable",),
    "ctex": ("ctex",),
    "xeCJK": ("xeCJK",),
    "geometry": ("geometry",),
    "fancyhdr": ("fancyhdr",),
}


# ---------------------------------------------------------------------------
# 基础解析工具
# ---------------------------------------------------------------------------

def strip_line_comment(line: str) -> str:
    """去掉行尾注释（保留 \\% 转义），用于避免匹配到被注释掉的代码。"""
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n:
            out.append(line[i:i + 2])
            i += 2
            continue
        if ch == "%":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def match_group(text: str, pos: int, open_ch: str, close_ch: str) -> tuple[str | None, int]:
    """从 text[pos] == open_ch 开始做配对匹配，返回 (内容, 闭合符之后的下标)。"""
    if pos >= len(text) or text[pos] != open_ch:
        return None, pos
    depth = 0
    for i in range(pos, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[pos + 1:i], i + 1
    return None, pos


def iter_command_args(text: str, command: str) -> list[dict[str, Any]]:
    """找出所有 `\\command[opt]{arg}` 形式，返回 [{opt, arg, start, end}, ...]。"""
    pattern = re.compile(r"\\" + re.escape(command) + r"\s*(\[[^\]]*\])?\s*\{")
    results: list[dict[str, Any]] = []
    for m in pattern.finditer(text):
        opt = m.group(1)
        body, end = match_group(text, m.end() - 1, "{", "}")
        if body is None:
            continue
        results.append({
            "opt": opt[1:-1].strip() if opt else None,
            "arg": body.strip(),
            "start": m.start(),
            "end": end,
        })
    return results


def split_top_level(text: str, sep: str = ",") -> list[str]:
    """按 sep 切分，但忽略花括号/方括号内部的分隔符。"""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            buf.append(text[i:i + 2])
            i += 2
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def unbrace(value: str) -> str:
    """去掉最外层的一对花括号（若整体被包裹）。"""
    value = value.strip()
    while value.startswith("{") and value.endswith("}"):
        inner, end = match_group(value, 0, "{", "}")
        if inner is None or end != len(value):
            break
        value = inner.strip()
    return value


def parse_key_values(text: str) -> dict[str, str]:
    """解析 `key = value, key2 = {a, b}` 形式的配置串。"""
    result: dict[str, str] = {}
    for item in split_top_level(unbrace(text)):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        result[key.strip()] = unbrace(value)
    return result


def parse_ctexset(text: str) -> dict[str, Any]:
    """解析 \\ctexset 内容为 {key_path: value} 字典；分组写法展开为嵌套字典。"""
    result: dict[str, Any] = {}
    for item in split_top_level(unbrace(text)):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith("{"):
            inner, end = match_group(value, 0, "{", "}")
            if inner is not None and end == len(value):
                if "=" in inner:
                    result[key] = parse_ctexset(inner)
                else:
                    result[key] = inner.strip()
                continue
        result[key] = value
    return result


def line_of(text: str, pos: int) -> int:
    """字符下标 → 1-based 行号。"""
    return text.count("\n", 0, pos) + 1


# 占位注释常见的装饰字符（真模板爱写成 `% ===== 正文开始 =====`）
DECORATION_CHARS = "=-*#~_+|/\\\t \u3000"


def clean_placeholder_comment(text: str) -> str:
    """剥掉占位注释两端的装饰字符，只留语义文字。"""
    return text.strip().strip(DECORATION_CHARS).strip()


# ---------------------------------------------------------------------------
# 模板结构解析
# ---------------------------------------------------------------------------

def load_template(template_path: Path) -> dict[str, Any]:
    """读取模板文本，并生成去注释版本（行数保持一致）。"""
    raw = template_path.read_text(encoding="utf-8", errors="replace")
    raw_lines = raw.split("\n")
    clean_lines = [strip_line_comment(line) for line in raw_lines]
    return {
        "raw": raw,
        "raw_lines": raw_lines,
        "clean": "\n".join(clean_lines),
        "clean_lines": clean_lines,
    }


def parse_documentclass(clean: str) -> dict[str, Any]:
    found = iter_command_args(clean, "documentclass")
    if not found:
        return {"name": None, "options": [], "line": None}
    first = found[0]
    options = split_top_level(first["opt"]) if first["opt"] else []
    options = [o.replace(" ", "") for o in options if o.strip()]
    return {
        "name": first["arg"],
        "options": options,
        "line": line_of(clean, first["start"]),
    }


def parse_packages(clean: str) -> tuple[list[str], dict[str, str]]:
    """返回 (宏包名列表[去重保序], {宏包名: 选项串})。"""
    packages: list[str] = []
    options: dict[str, str] = {}
    for item in iter_command_args(clean, "usepackage"):
        for name in item["arg"].split(","):
            name = name.strip()
            if not name:
                continue
            if name not in packages:
                packages.append(name)
            if item["opt"]:
                options[name] = item["opt"]
    return packages, options


def scan_local_class_files(template_dir: Path, docclass: str | None) -> dict[str, Any]:
    """扫描同目录 .cls/.sty，收集它们 RequirePackage 的宏包与是否缺失。"""
    required: list[str] = []
    scanned: list[str] = []
    candidates: list[Path] = []

    if docclass:
        candidates.append(template_dir / f"{docclass}.cls")
    for pattern in ("*.cls", "*.sty"):
        for path in sorted(template_dir.glob(pattern)):
            if path not in candidates:
                candidates.append(path)

    missing_class = None
    if (
        docclass
        and not (template_dir / f"{docclass}.cls").exists()
        and not any(p.stem == docclass for p in candidates)
    ):
        missing_class = docclass

    for path in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned.append(path.name)
        for item in iter_command_args(text, "RequirePackage"):
            for name in item["arg"].split(","):
                name = name.strip()
                if name and name not in required:
                    required.append(name)

    return {
        "scanned": scanned,
        "required_packages": required,
        "missing_class": missing_class,
    }


def detect_engine(
    raw: str,
    docclass: dict[str, Any],
    packages: list[str],
    required_packages: list[str],
) -> dict[str, Any]:
    """按 magic comment → 宏包 → 兜底 的顺序推断编译引擎。"""
    all_names = list(packages) + list(required_packages)
    class_name = (docclass.get("name") or "").lower()

    magic = None
    for line in raw.split("\n")[:8]:
        m = re.search(r"%\s*!TEX\s+(?:TS-)?program\s*=\s*([A-Za-z]+)", line)
        if m:
            magic = m.group(1).lower()
            break
        m = re.search(r"%\s*!TEX\s+program\s*:\s*([A-Za-z]+)", line)
        if m:
            magic = m.group(1).lower()
            break

    if magic in ("xelatex", "lualatex", "pdflatex"):
        return {"engine": magic, "source": "magic_comment"}

    if any(p in all_names for p in ("CJKutf8",)):
        return {"engine": "pdflatex", "source": "package:CJKutf8"}

    for pkg in XE_ONLY_PACKAGES:
        if pkg in all_names:
            return {"engine": "xelatex", "source": f"package:{pkg}"}

    if class_name.startswith("ctex"):
        return {"engine": "xelatex", "source": f"documentclass:{class_name}"}

    if not packages and not required_packages:
        return {"engine": "xelatex", "source": "default:no_packages"}

    return {"engine": "xelatex", "source": "default:xelatex"}


def detect_capabilities(
    packages: list[str],
    required_packages: list[str],
    clean: str,
) -> dict[str, Any]:
    all_names = set(packages) | set(required_packages)
    caps: dict[str, Any] = {}
    for cap, triggers in CAPABILITY_PACKAGES.items():
        caps[cap] = any(t in all_names for t in triggers)

    caps["bibtex"] = bool(
        re.search(r"\\bibliography\s*\{", clean)
        or re.search(r"\\bibliographystyle\s*\{", clean)
    )
    caps["thebibliography"] = bool(re.search(r"\\begin\s*\{thebibliography\}", clean))
    if re.search(r"\\addbibresource\s*\{", clean) or re.search(r"\\printbibliography", clean):
        caps["biblatex"] = True

    caps["has_bib_mechanism"] = bool(
        caps["bibtex"] or caps["thebibliography"] or caps["biblatex"]
    )
    return caps


def extract_styles(preamble_clean: str) -> dict[str, Any]:
    r"""提取排版参数。

    只应传入 preamble（\begin{document} 之前的文本）：正文里到处是
    封面页/标题页的局部 \zihao{}，全文扫描会把封面的字号当成正文默认字号。
    """
    clean = preamble_clean
    styles: dict[str, Any] = {
        "body": {
            "zihao": None,
            "line_spread": None,
            "par_indent": None,
            "par_skip": None,
        },
        "title": {"zihao": None},
        "heading1": {"zihao": None, "format": None, "auto_number": None},
        "heading2": {"zihao": None, "format": None, "auto_number": None},
        "heading3": {"zihao": None, "format": None, "auto_number": None},
        "page": {"geometry": {}},
        "ctexset": {},
        "fonts": {},
    }

    # --- \ctexset{...} ---
    ctexset_ranges: list[tuple[int, int]] = []
    for item in iter_command_args(clean, "ctexset"):
        parsed = parse_ctexset(item["arg"])
        styles["ctexset"].update(parsed)
        ctexset_ranges.append((item["start"], item["end"]))

    def assign_by_key(key: str, value: str) -> None:
        zihao = None
        m = re.search(r"\\zihao\s*\{([^}]*)\}", value)
        if m:
            zihao = m.group(1).strip()
        target = None
        if "subsubsection" in key:
            target = "heading3"
        elif "subsection" in key:
            target = "heading2"
        elif "section" in key or "chapter" in key or "part" in key:
            target = "heading1"
        elif "title" in key:
            target = "title"
        if target is None:
            return
        if zihao:
            styles[target]["zihao"] = zihao
        if "format" in key:
            styles[target]["format"] = value.strip()

    for key, value in styles["ctexset"].items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                path = f"{key}/{sub_key}"
                assign_by_key(path, str(sub_value))
        else:
            assign_by_key(key, str(value))

    # --- 裸 \zihao（ctexset 之外）→ 正文默认字号 ---
    for m in re.finditer(r"\\zihao\s*\{([^}]*)\}", clean):
        inside = any(start <= m.start() < end for start, end in ctexset_ranges)
        if not inside:
            styles["body"]["zihao"] = m.group(1).strip()

    # --- 行距 / 缩进 ---
    m = re.search(r"\\linespread\s*\{([^}]*)\}", clean)
    if m:
        styles["body"]["line_spread"] = m.group(1).strip()
    m = re.search(r"\\renewcommand\s*\{\\baselinestretch\}\s*\{([^}]*)\}", clean)
    if m and not styles["body"]["line_spread"]:
        styles["body"]["line_spread"] = m.group(1).strip()
    if "setspace" in clean:
        m = re.search(r"\\setstretch\s*\{([^}]*)\}", clean)
        if m:
            styles["body"]["line_spread"] = m.group(1).strip()

    m = re.search(r"\\setlength\s*\{\\parindent\}\s*\{([^}]*)\}", clean)
    if m:
        styles["body"]["par_indent"] = m.group(1).strip()
    m = re.search(r"\\setlength\s*\{\\parskip\}\s*\{([^}]*)\}", clean)
    if m:
        styles["body"]["par_skip"] = m.group(1).strip()

    # --- 章节是否自动编号 ---
    # 本工具产出的 md 标题自带中文序号（"一、引言" / "1.1 背景"）。若模板
    # 自身会编号（LaTeX 默认行为，或 ctexset 里 number 非空），再叠一层就会
    # 渲染成 "一、 一、引言"。md_to_latex 靠这个字段决定是否剥掉 md 里的序号。
    def _ctexset_lookup(path: str) -> Any:
        flat = styles["ctexset"].get(path)
        if flat is not None and not isinstance(flat, dict):
            return flat
        node: Any = styles["ctexset"]
        for part in path.split("/"):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return None
        return None if isinstance(node, dict) else node

    def _auto_number(candidate_paths: list[str]) -> bool:
        for path in candidate_paths:
            value = _ctexset_lookup(path)
            if value is not None:
                return bool(unbrace(str(value)).strip())
        # 模板没声明 → 走 LaTeX 默认行为：自动编号
        return True

    styles["heading1"]["auto_number"] = _auto_number(["section/number", "chapter/number"])
    styles["heading2"]["auto_number"] = _auto_number(["subsection/number"])
    styles["heading3"]["auto_number"] = _auto_number(["subsubsection/number"])

    # --- 页面边距 ---
    geometry: dict[str, str] = {}
    for item in iter_command_args(clean, "geometry"):
        geometry.update(parse_key_values(item["arg"]))
    if not geometry:
        for item in iter_command_args(clean, "usepackage"):
            if "geometry" in item["arg"].split(",") and item["opt"]:
                geometry.update(parse_key_values(item["opt"]))
    styles["page"]["geometry"] = geometry

    # --- 字体设置 ---
    for cmd, label in (
        ("setCJKmainfont", "cjk_main"),
        ("setCJKsansfont", "cjk_sans"),
        ("setCJKmonofont", "cjk_mono"),
        ("setmainfont", "latin_main"),
    ):
        for item in iter_command_args(clean, cmd):
            name = item["arg"].split(",")[0].strip()
            if name:
                styles["fonts"][label] = name
    for item in iter_command_args(clean, "setCJKfamilyfont"):
        parts = split_top_level(item["arg"])
        if parts:
            styles["fonts"].setdefault("cjk_families", {})[parts[0]] = (
                parts[1].strip() if len(parts) > 1 else ""
            )

    return styles


def find_document_bounds(clean_lines: list[str]) -> dict[str, int | None]:
    begin = None
    end = None
    for idx, line in enumerate(clean_lines, start=1):
        if begin is None and re.search(r"\\begin\s*\{document\}", line):
            begin = idx
        if re.search(r"\\end\s*\{document\}", line):
            end = idx
    return {"begin_line": begin, "end_line": end}


# 参考文献块的前导命令：回吞它们才能保住模板的著录格式声明
TAIL_BIB_PREAMBLE_RE = re.compile(
    r"^\s*$"
    r"|\\bibliographystyle\s*\{"
    r"|\\addbibresource\s*\{"
    r"|\\clearpage\b|\\cleardoublepage\b|\\newpage\b"
    r"|\\phantomsection\b"
    r"|\\addcontentsline\b"
    r"|\\nocite\b"
    r"|\\vspace\b"
)


def find_anchors(
    raw_lines: list[str],
    clean_lines: list[str],
    begin_line: int | None,
    end_line: int | None,
) -> dict[str, Any]:
    """定位正文注入锚点，并计算替换区间。

    raw_lines 用于识别注释占位符（注释内容在 clean_lines 里已被剥掉），
    clean_lines 用于识别章节命令（避免匹配到被注释掉的代码）。
    """
    empty = {
        "mode": None,
        "start_line": None,
        "stop_line": None,
        "anchor_kind": None,
        "anchor_text": None,
        "removed_preview": "",
        "keeps_template_bibliography": False,
        "usable": False,
        "reason": "模板缺少 \\begin{document} 或 \\end{document}",
        "is_guess": False,
    }
    if not begin_line or not end_line or end_line <= begin_line:
        return empty

    inner_start = begin_line + 1
    inner_stop = end_line  # 不含 \end{document} 行

    comment_anchor: tuple[int, str] | None = None
    section_anchor: tuple[int, str] | None = None
    maketitle_line: int | None = None

    # 只认带编号的章节命令：\section* 历来是前置页（声明、致谢、目录），
    # 把它当示例正文会直接删掉模板的原创性声明页
    section_re = re.compile(
        r"^\s*\\(?:{})\s*[\{{[]".format("|".join(SECTION_COMMANDS))
    )
    starred_section_re = re.compile(
        r"^\s*\\(?:{})\*".format("|".join(SECTION_COMMANDS))
    )
    comment_re = re.compile(r"^\s*%+\s*(.+?)\s*$")
    html_comment_re = re.compile(r"^\s*<!--\s*(.+?)\s*-->\s*$")

    for idx in range(inner_start, inner_stop):
        raw_line = raw_lines[idx - 1]
        stripped = clean_lines[idx - 1].strip()

        # 显式占位注释：必须看原始行，注释内容在 clean_lines 里已经没了
        m = comment_re.match(raw_line) or html_comment_re.match(raw_line)
        if comment_anchor is None and m:
            text = clean_placeholder_comment(m.group(1))
            if text and len(text) <= 40 and any(
                k in text.lower() for k in PLACEHOLDER_KEYWORDS
            ):
                comment_anchor = (idx, text)

        if section_anchor is None and not starred_section_re.match(stripped) \
                and section_re.match(stripped):
            section_anchor = (idx, stripped)

        if re.search(r"\\maketitle\b", stripped):
            maketitle_line = idx

    if comment_anchor:
        start_line, anchor_text = comment_anchor
        kind = "comment"
    elif section_anchor:
        start_line, anchor_text = section_anchor
        kind = "example_section"
    elif maketitle_line:
        start_line = min(maketitle_line + 1, inner_stop)
        anchor_text = "\\maketitle"
        kind = "after_maketitle"
    else:
        empty["reason"] = "模板内未找到占位注释、示例章节或 \\maketitle，无法定位注入点"
        return empty

    # 替换区间终点：模板自带的参考文献机制 / \end{document} / 全文结束
    stop_line = inner_stop
    keeps_bib = False
    for idx in range(start_line, inner_stop):
        line = clean_lines[idx - 1]
        if re.search(r"\\bibliography\s*\{", line) or re.search(r"\\printbibliography", line):
            stop_line = idx
            keeps_bib = True
            break
        if re.search(r"\\begin\s*\{thebibliography\}", line):
            stop_line = idx
            keeps_bib = True
            break

    if kind == "after_maketitle":
        # 没有示例正文，只在其后插入
        stop_line = start_line
    elif keeps_bib:
        # 从 \bibliography 行向前回吞紧邻的参考文献前导行。
        # 不回吞的话 \bibliographystyle{...} 会被当作正文删掉，
        # 模板的著录格式声明就静默丢了。
        walked = 0
        while stop_line > start_line and walked < 12:
            prev = clean_lines[stop_line - 2]
            if not TAIL_BIB_PREAMBLE_RE.match(prev):
                break
            stop_line -= 1
            walked += 1

    removed = raw_lines[start_line - 1:max(start_line, stop_line) - 1]
    removed_preview = "\n".join(removed).strip()

    return {
        "mode": "replace_range" if stop_line > start_line else "insert",
        "start_line": start_line,
        "stop_line": stop_line,
        "anchor_kind": kind,
        "anchor_text": anchor_text,
        "removed_preview": removed_preview[:400],
        "keeps_template_bibliography": keeps_bib,
        "usable": True,
        "reason": "OK",
        # 非注释锚点都是推测，需人工/LLM 核对替换区间没误删前置页
        "is_guess": kind != "comment",
    }


# ---------------------------------------------------------------------------
# 编译探测
# ---------------------------------------------------------------------------

MISSING_FILE_PATTERNS = (
    re.compile(r"File [`'\"]([^'\"]+)[`'\"] not found"),
    re.compile(r"I can't find file [`'\"]([^'\"]+)"),
    re.compile(r"! LaTeX Error: File [`'\"]([^'\"]+)[`'\"] not found"),
    re.compile(r"! I can't find file [`'\"]([^'\"]+)"),
)


def parse_log_errors(log_text: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """从 .log 抽取结构化的错误信息、缺失文件、未定义引用。"""
    errors: list[dict[str, Any]] = []
    missing: list[str] = []
    undefined: list[str] = []

    lines = log_text.split("\n")
    for i, line in enumerate(lines):
        # -file-line-error 格式： ./template.tex:42: ! Undefined control sequence.
        m = re.match(r"^(?:\./)?([^:]+):(\d+):\s*(!\s*.*)$", line)
        if m:
            try:
                line_no = int(m.group(2))
            except ValueError:
                line_no = None
            errors.append({
                "file": m.group(1),
                "line": line_no,
                "message": m.group(3).strip(),
                "context": "\n".join(lines[i + 1:i + 3]).strip(),
            })
            continue
        if line.startswith("!"):
            errors.append({
                "file": None,
                "line": None,
                "message": line.strip(),
                "context": "\n".join(lines[i + 1:i + 3]).strip(),
            })
            continue
        for pattern in MISSING_FILE_PATTERNS:
            fm = pattern.search(line)
            if fm:
                name = fm.group(1)
                if name not in missing:
                    missing.append(name)
                break
        if re.search(r"(Citation|Reference)\s+[`'\"][^'\"]+[`'\"]\s+undefined", line):
            item = line.strip()
            if item not in undefined:
                undefined.append(item)

    return errors, missing, undefined


def probe_compile(
    template_path: Path,
    engine: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """把模板原样编译一次（输出到临时目录，不污染用户目录）。"""
    if shutil.which("latexmk") is None:
        return {
            "status": "skipped",
            "reason": "未找到 latexmk，跳过编译探测",
            "engine_used": None,
            "pdf_produced": False,
            "errors": [],
            "missing_deps": [],
            "undefined_refs": [],
        }

    with tempfile.TemporaryDirectory(prefix="wp_latex_probe_") as tmp:
        cmd = [
            "latexmk",
            "-" + engine,
            "-interaction=nonstopmode",
            "-file-line-error",
            "-outdir=" + tmp,
            template_path.name,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(template_path.parent),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {
                "status": "timeout" if isinstance(exc, subprocess.TimeoutExpired) else "broken",
                "reason": str(exc),
                "engine_used": engine,
                "pdf_produced": False,
                "errors": [],
                "missing_deps": [],
                "undefined_refs": [],
            }

        log_path = Path(tmp) / (template_path.stem + ".log")
        pdf_path = Path(tmp) / (template_path.stem + ".pdf")
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        if not log_text:
            log_text = proc.stdout or ""

        errors, missing, undefined = parse_log_errors(log_text)
        pdf_produced = pdf_path.exists() and pdf_path.stat().st_size > 0

        if pdf_produced:
            status = "ok"
        elif errors and all(
            any(p.search(e["message"]) for p in MISSING_FILE_PATTERNS) for e in errors
        ) or missing and not errors:
            status = "partial"
        else:
            status = "broken"

        return {
            "status": status,
            "reason": "" if status == "ok" else "见 errors / missing_deps",
            "engine_used": engine,
            "pdf_produced": pdf_produced,
            "returncode": proc.returncode,
            "errors": errors[:20],
            "missing_deps": missing,
            "undefined_refs": undefined,
        }


# ---------------------------------------------------------------------------
# 诊断
# ---------------------------------------------------------------------------

def build_diagnostics(
    packages: list[str],
    class_scan: dict[str, Any],
    capabilities: dict[str, Any],
    bounds: dict[str, int | None],
    injection: dict[str, Any],
    probe: dict[str, Any],
    engine_info: dict[str, Any],
    styles: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    all_names = set(packages) | set(class_scan["required_packages"])

    if bounds["begin_line"] is None:
        notes.append("模板缺少 \\begin{document}，无法作为外壳使用 → 走内置骨架回退")
    if bounds["end_line"] is None:
        notes.append("模板缺少 \\end{document}，无法作为外壳使用 → 走内置骨架回退")
    if not injection["usable"]:
        notes.append("未定位到正文注入点（{}）→ 走内置骨架回退".format(injection["reason"]))
    elif injection.get("is_guess"):
        notes.append(
            "注入锚点为推测（kind={}，未找到显式占位注释）"
            "→ 请核对替换区间 L{}–L{} 未误删封面/声明/目录页".format(
                injection["anchor_kind"], injection["start_line"], injection["stop_line"]
            )
        )
    if not capabilities["graphicx"]:
        notes.append("模板未加载 graphicx 宏包，插图将不可用 → 建议回退内置骨架")
    if not capabilities["hyperref"]:
        notes.append("模板未加载 hyperref，正文中的超链接将退化为纯文本")
    if capabilities["bibtex"] and not capabilities["biblatex"]:
        notes.append("模板使用 \\bibliography/\\bibliographystyle，将生成 refs.bib 配合使用")
    if not capabilities["has_bib_mechanism"]:
        notes.append("模板无参考文献机制，正文将内嵌 thebibliography 手写条目")
    if class_scan["missing_class"]:
        notes.append(
            "未在模板目录找到文档类 {}.cls，编译依赖系统已安装该文档类".format(
                class_scan["missing_class"]
            )
        )
    if "ctex" in all_names and engine_info["engine"] == "pdflatex":
        notes.append("模板使用 ctex 但推断引擎为 pdflatex，中文将编译失败 → 已改用 xelatex")
        engine_info["engine"] = "xelatex"
        engine_info["source"] += "+forced_ctex_override"
    if not capabilities["booktabs"] and not capabilities["longtable"]:
        notes.append("模板未加载 booktabs/longtable，表格将退化为 \\hline 样式")
    if not capabilities["tabularx"]:
        notes.append("模板未加载 tabularx，宽表格将退化为 tabular + \\small")
    if injection["usable"] and styles.get("heading1", {}).get("auto_number"):
        notes.append(
            "模板章节自动编号（LaTeX 默认或 ctexset number 非空）"
            "→ 会把 md 标题里的\"一、\"\"1.1\"序号剥掉，避免渲染成\"一、 一、引言\""
        )

    if probe["status"] == "partial":
        notes.append(
            "模板可编译但依赖缺失（{}），注入时会自动补齐空占位".format(
                "、".join(probe["missing_deps"][:5]) or "未知"
            )
        )
    elif probe["status"] in ("broken", "timeout"):
        notes.append(
            "模板原样编译失败（status={}）→ 若注入后仍失败则回退内置骨架".format(probe["status"])
        )
    elif probe["status"] == "skipped":
        notes.append("未执行编译探测，模板可用性未知")

    return notes


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def analyze(template_path: Path, do_probe: bool = True, probe_timeout: int = 60) -> dict[str, Any]:
    data = load_template(template_path)
    clean = data["clean"]
    clean_lines = data["clean_lines"]

    docclass = parse_documentclass(clean)
    packages, package_options = parse_packages(clean)
    class_scan = scan_local_class_files(template_path.parent, docclass["name"])
    engine_info = detect_engine(data["raw"], docclass, packages, class_scan["required_packages"])
    capabilities = detect_capabilities(packages, class_scan["required_packages"], clean)
    bounds = find_document_bounds(clean_lines)
    styles = extract_styles(
        "\n".join(clean_lines[:bounds["begin_line"] - 1]) if bounds["begin_line"] else clean
    )
    injection = find_anchors(
        data["raw_lines"], clean_lines, bounds["begin_line"], bounds["end_line"]
    )

    if do_probe:
        probe = probe_compile(template_path, engine_info["engine"], probe_timeout)
    else:
        probe = {
            "status": "skipped",
            "reason": "--no-probe 指定跳过",
            "engine_used": None,
            "pdf_produced": False,
            "errors": [],
            "missing_deps": [],
            "undefined_refs": [],
        }

    diagnostics = build_diagnostics(
        packages, class_scan, capabilities, bounds, injection, probe, engine_info, styles
    )

    preamble = ""
    front_matter = ""
    tail = ""
    if bounds["begin_line"]:
        preamble = "\n".join(data["raw_lines"][:bounds["begin_line"] - 1]).strip("\n")
        if injection["usable"]:
            front_matter = "\n".join(
                data["raw_lines"][bounds["begin_line"] - 1:injection["start_line"] - 1]
            ).strip("\n")
            tail = "\n".join(
                data["raw_lines"][injection["stop_line"] - 1:
                                 (bounds["end_line"] or len(data["raw_lines"]))]
            ).strip("\n")

    return {
        "source_file": str(template_path),
        "engine": engine_info["engine"],
        "engine_source": engine_info["source"],
        "documentclass": docclass,
        "packages": packages,
        "package_options": package_options,
        "class_files": class_scan,
        "capabilities": capabilities,
        "shell": {
            "preamble": preamble,
            "front_matter": front_matter,
            "tail": tail,
        },
        "bounds": bounds,
        "injection": injection,
        "styles": styles,
        "compile_probe": probe,
        "diagnostics": diagnostics,
        "usable_as_shell": bool(
            injection["usable"] and bounds["begin_line"] and bounds["end_line"]
        ),
    }


def build_text_out(profile: dict[str, Any], raw_lines: list[str]) -> str:
    out: list[str] = []
    out.append("# LaTeX 模板全文（带行号与结构标注）")
    out.append("# 源文件: {}".format(profile["source_file"]))
    out.append("# 引擎: {}（来源: {}）".format(profile["engine"], profile["engine_source"]))
    dc = profile["documentclass"]
    out.append("# 文档类: {} 选项={}".format(dc["name"], ",".join(dc["options"]) or "无"))
    out.append("# 宏包: {}".format(", ".join(profile["packages"]) or "无"))
    bounds = profile["bounds"]
    out.append(
        "# \\begin{{document}} @ L{} | \\end{{document}} @ L{}".format(
            bounds["begin_line"], bounds["end_line"]
        )
    )
    inj = profile["injection"]
    if inj["usable"]:
        out.append(
            "# 注入点 @ L{} (kind={}, 锚点=\"{}\") | 替换区间 L{}–L{} | 保留模板参考文献={}".format(
                inj["start_line"], inj["anchor_kind"], inj["anchor_text"],
                inj["start_line"], inj["stop_line"], inj["keeps_template_bibliography"],
            )
        )
    else:
        out.append("# 注入点: 未找到（{}）".format(inj["reason"]))

    if profile["diagnostics"]:
        out.append("# 诊断:")
        for note in profile["diagnostics"]:
            out.append(f"#   - {note}")

    out.append("")
    out.append("## 全文原文（行号对应原文件）")
    for idx, line in enumerate(raw_lines, start=1):
        mark = ""
        if idx == bounds["begin_line"]:
            mark = "  % <== \\begin{document}"
        elif idx == bounds["end_line"]:
            mark = "  % <== \\end{document}"
        elif inj["usable"] and idx == inj["start_line"]:
            mark = "  % <== 正文注入点（替换区间起点）"
        elif inj["usable"] and idx == inj["stop_line"]:
            mark = "  % <== 替换区间终点"
        out.append(f"L{idx:04d}: {line}{mark}")
    return "\n".join(out)


def fmt_summary(profile: dict[str, Any], template_path: Path) -> str:
    lines: list[str] = []
    lines.append("=" * 62)
    lines.append(f"模板文件: {template_path}")
    lines.append("引擎: {}（来源: {}）".format(profile["engine"], profile["engine_source"]))
    dc = profile["documentclass"]
    lines.append("文档类: {}  选项: {}".format(dc["name"], ", ".join(dc["options"]) or "无"))
    lines.append("宏包({}): {}".format(
        len(profile["packages"]), ", ".join(profile["packages"][:12])
        + ("..." if len(profile["packages"]) > 12 else "")
    ))
    caps_on = [k for k, v in profile["capabilities"].items() if v]
    lines.append("能力: {}".format(", ".join(caps_on) or "无"))
    bounds = profile["bounds"]
    lines.append("\\begin{{document}} @ L{} | \\end{{document}} @ L{}".format(
        bounds["begin_line"], bounds["end_line"]))
    inj = profile["injection"]
    if inj["usable"]:
        lines.append("注入点: L{} ({}) 锚点=\"{}\"".format(
            inj["start_line"], inj["anchor_kind"], inj["anchor_text"]))
        lines.append("替换区间: L{} – L{}（保留模板参考文献: {}）".format(
            inj["start_line"], inj["stop_line"], inj["keeps_template_bibliography"]))
    else:
        lines.append("注入点: 未找到 — {}".format(inj["reason"]))
    lines.append("可用作外壳: {}".format("是" if profile["usable_as_shell"] else "否 → 将回退内置骨架"))
    probe = profile["compile_probe"]
    lines.append("编译探测: {}（引擎 {}）".format(probe["status"], probe["engine_used"]))
    if probe.get("missing_deps"):
        lines.append("  缺失依赖: {}".format(", ".join(probe["missing_deps"][:6])))
    for err in probe.get("errors", [])[:5]:
        lines.append("  错误: L{} {}".format(err.get("line"), err.get("message")))
    if profile["diagnostics"]:
        lines.append("-" * 62)
        lines.append("诊断:")
        for note in profile["diagnostics"]:
            lines.append(f"  - {note}")
    lines.append("=" * 62)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LaTeX 模板分析工具")
    # `_ =` 是有意为之：argparse/file I/O 的返回值在本脚本里没用，
    # 显式丢弃以免依赖 pyright 配置来消隐。
    _ = parser.add_argument("template", help="LaTeX 模板路径（.tex）")
    _ = parser.add_argument("--json-out", help="输出 latex_profile.json 的路径")
    _ = parser.add_argument("--text-out", help="输出带行号标注的模板全文（供 LLM 补充分析）")
    _ = parser.add_argument("--no-probe", action="store_true", help="跳过编译探测")
    _ = parser.add_argument("--probe-timeout", type=int, default=60,
                            help="编译探测超时秒数（默认 60）")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    template_path = Path(args.template).expanduser()
    if not template_path.exists():
        print(f"[ERROR] 文件不存在: {template_path}", file=sys.stderr)
        return 1
    if template_path.suffix.lower() != ".tex":
        print(f"[WARN] 输入不是 .tex 文件: {template_path.name}（仍按文本解析）",
              file=sys.stderr)

    profile = analyze(template_path, do_probe=not args.no_probe,
                      probe_timeout=args.probe_timeout)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _ = out_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] LaTeX 模板分析结果已保存到: {out_path}")

    if args.text_out:
        text_path = Path(args.text_out)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        raw_lines = load_template(template_path)["raw_lines"]
        _ = text_path.write_text(build_text_out(profile, raw_lines), encoding="utf-8")
        print(f"[OK] 模板全文（带行号标注）已导出到: {text_path}")

    print(fmt_summary(profile, template_path))

    if not profile["usable_as_shell"]:
        print("[WARN] 模板不可用作外壳，后续应使用内置骨架回退")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
