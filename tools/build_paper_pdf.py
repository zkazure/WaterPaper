#!/usr/bin/env python3
r"""
LaTeX 论文组装与 PDF 编译工具

把 md_to_latex 产出的 body.tex 注入模板外壳（或内置兜底骨架），编译出 PDF。

组装顺序：
  1. 按 latex_profile.json 的注入区间切出 head（preamble + 封面/声明/目录）
     与 tail（模板自带的参考文献块）
  2. 头部打补丁：替换 \title、把摘要/关键词写进模板的 abstract 区、
     按正文实际用到的命令补 \usepackage
  3. 尾部处理：thebibliography 模式下剥掉模板自带的参考文献机制（避免双份）；
     refs.bib 模式下按模板要求的文件名落盘 .bib
  4. 编译（latexmk，多趟解交叉引用），失败则解析 .log 做结构化诊断
  5. 有界自动修复：缺图片/缺 .bib 就补占位后重编；仍失败则回退内置骨架

本脚本刻意保持自包含（不 import 同目录的其他工具）：仓库既有的 10 个脚本
全部零交叉导入，且脚本式运行时 `from sibling import x` 属隐式相对导入，
一旦被当作模块加载就会断。代价只是重复约 25 行日志正则。

依赖：无第三方依赖（需要系统安装 TeX Live + latexmk；页数统计用 pdfinfo）。

用法：
    python build_paper_pdf.py --body body.tex --profile latex_profile.json \
        --report convert_report.json --bib refs.bib -o paper.pdf
    python build_paper_pdf.py --body body.tex --profile p.json -o paper.pdf --dry-run
    python build_paper_pdf.py --body body.tex --profile p.json -o paper.pdf \
        --fallback-skeleton --title "论文标题"

退出码：0 成功；1 致命错误；3 编译失败（附 paper.tex 与 .log 供排查）
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKELETON = REPO_ROOT / "assets" / "default_paper.tex"

# 正文用到这些命令/环境时，模板缺对应宏包就必须补上
REQUIRED_PACKAGES = (
    (re.compile(r"\\includegraphics"), "graphicx", "\\usepackage{graphicx}"),
    (re.compile(r"\\(top|mid|bottom)rule"), "booktabs", "\\usepackage{booktabs}"),
    (re.compile(r"\\begin\{tabularx\}"), "tabularx",
     "\\usepackage{tabularx}\n\\usepackage{array}"),
)

AUX_SUFFIXES = (
    ".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex.gz",
    ".blg", ".bbl", ".nav", ".snm", ".vrb", ".xdv", ".run.xml", ".bcf",
)

# 缺文件类报错（这类可以自动补占位后重编）
MISSING_FILE_PATTERNS = (
    re.compile(r"File [`'\"]([^'\"]+)[`'\"] not found"),
    re.compile(r"I can't find file [`'\"]([^'\"]+)"),
    re.compile(r"! LaTeX Error: File [`'\"]([^'\"]+)[`'\"] not found"),
)

LOG_ERROR_LINE_RE = re.compile(r"^(?:\./)?([^:]+):(\d+):\s*(!\s*.*)$")
LOG_UNDEFINED_RE = re.compile(r"(Citation|Reference)\s+[`'\"][^'\"]+[`'\"]\s+undefined")

PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
    b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def match_group(text: str, pos: int, open_ch: str, close_ch: str) -> tuple[str | None, int]:
    """从 text[pos] == open_ch 开始配对匹配，返回 (内容, 闭合符后下标)。"""
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


def parse_latex_log(
    log_text: str,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    """从 .log 抽取 (错误, 缺失文件, 未解析引用, LaTeX 警告)。"""
    errors: list[dict[str, Any]] = []
    missing: list[str] = []
    undefined: list[str] = []
    warnings: list[str] = []

    lines = log_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("LaTeX Warning"):
            warnings.append(line.strip())
            # 不能 continue：缺图提示正是 "LaTeX Warning: File `x.png' not found"，
            # 提前 continue 会让下面的缺文件检测永远扫不到这类行。
        m = LOG_ERROR_LINE_RE.match(line)
        if m:
            errors.append({
                "file": m.group(1),
                "line": safe_int(m.group(2)),
                "message": m.group(3).strip(),
                "context": "\n".join(lines[i + 1:i + 3]).strip(),
            })
            continue
        if line.startswith("!"):
            errors.append({
                "file": None, "line": None, "message": line.strip(),
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
        if LOG_UNDEFINED_RE.search(line):
            item = line.strip()
            if item not in undefined:
                undefined.append(item)

    return errors, missing, undefined, warnings


# ---------------------------------------------------------------------------
# 文本补丁工具
# ---------------------------------------------------------------------------

def replace_braced_command(text: str, command: str, new_arg: str) -> tuple[str, int]:
    r"""替换所有 `\command[opt]{...}` 的括号内容，返回 (新文本, 替换次数)。"""
    pattern = re.compile(r"\\" + command + r"\s*(\[[^\]]*\])?\s*\{")
    pieces: list[str] = []
    last = 0
    count = 0
    for m in pattern.finditer(text):
        _old, end = match_group(text, m.end() - 1, "{", "}")
        if _old is None:
            continue
        pieces.append(text[last:m.end() - 1])
        pieces.append("{" + new_arg + "}")
        last = end
        count += 1
    if count == 0:
        return text, 0
    pieces.append(text[last:])
    return "".join(pieces), count


def find_abstract_span(text: str) -> tuple[int, int] | None:
    r"""返回 abstract 环境的 (内容起点, 内容终点)。"""
    m = re.search(r"\\begin\{abstract\}", text)
    if not m:
        return None
    start = m.end()
    end = text.find(r"\end{abstract}", start)
    if end < 0:
        return None
    return start, end


def strip_bib_mechanism(tail: str) -> tuple[str, list[str]]:
    r"""剥掉模板自带的参考文献机制（我们已在正文内嵌 thebibliography）。"""
    out = tail
    removed: list[str] = []

    m = re.search(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}",
                  out, re.DOTALL)
    if m:
        out = out[:m.start()] + out[m.end():]
        removed.append("thebibliography 环境")

    for pattern, label in (
        (r"\\bibliography\s*\{[^}]*\}", "\\bibliography"),
        (r"\\bibliographystyle\s*\{[^}]*\}", "\\bibliographystyle"),
        (r"\\printbibliography(\[[^\]]*\])?", "\\printbibliography"),
        (r"\\addbibresource\s*\{[^}]*\}", "\\addbibresource"),
    ):
        out, n = re.subn(pattern, "", out)
        if n:
            removed.append(label)

    return out, removed


def bib_target_filename(tail: str) -> str | None:
    r"""读出模板要求的 .bib 文件名（\bibliography{X} / \addbibresource{X.bib}）。"""
    for cmd in ("bibliography", "addbibresource"):
        m = re.search(r"\\" + cmd + r"\s*\{([^}]*)\}", tail)
        if m:
            name = m.group(1).strip()
            if not name:
                continue
            return name if name.endswith(".bib") else name + ".bib"
    return None


def bib_style_from_profile(profile: dict[str, Any]) -> str:
    r"""取模板声明的 \bibliographystyle（回退路径也要照顾学校的引用格式）。"""
    sources = [(profile.get("shell") or {}).get("tail") or ""]
    source_file = profile.get("source_file")
    if source_file and Path(str(source_file)).exists():
        with contextlib.suppress(OSError):
            sources.append(Path(str(source_file)).read_text(
                encoding="utf-8", errors="replace"))
    for text in sources:
        m = re.search(r"\\bibliographystyle\s*\{([^}]*)\}", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return "plain"


def bib_block(profile: dict[str, Any], report: dict[str, Any]) -> str:
    r"""骨架用的参考文献机制。

    bibtex 模式的 body.tex 里只有 \cite{}（参考文献交给了模板的 \bibliography），
    回退到骨架时必须补上 \bibliography，否则引用全部渲染成 [?]。
    """
    if report.get("bib_mode") != "bibtex":
        return "% 正文已内嵌 thebibliography，无需 \\bibliography"
    return ("\\bibliographystyle{" + bib_style_from_profile(profile) + "}\n"
            + "\\bibliography{refs}")


def ensure_packages(head: str, body: str, capabilities: dict[str, Any]) -> tuple[str, list[str]]:
    r"""正文用到但 preamble 没加载的宏包，补在 \begin{document} 之前。"""
    notes: list[str] = []
    additions: list[str] = []
    for pattern, package, command in REQUIRED_PACKAGES:
        if not pattern.search(body):
            continue
        if capabilities.get(package):
            continue
        if re.search(r"\\usepackage(\[[^\]]*\])?\{" + package + r"\}", head):
            continue
        additions.append(command)
        notes.append(
            "正文用到 " + package + " 但模板未加载 → 已补 " + package + " 宏包"
        )
    if not additions:
        return head, notes
    block = "\n".join(additions)
    m = re.search(r"\\begin\{document\}", head)
    if not m:
        return head + "\n" + block, notes
    return head[:m.start()] + block + "\n" + head[m.start():], notes


def make_style_overrides(profile: dict[str, Any]) -> str:
    """把从用户模板抽到的排版参数转成可插入骨架的 LaTeX 覆盖块。"""
    styles = profile.get("styles") or {}
    lines: list[str] = []

    body_style = styles.get("body") or {}
    line_spread = body_style.get("line_spread")
    par_indent = body_style.get("par_indent")
    par_skip = body_style.get("par_skip")
    zihao = body_style.get("zihao")
    if line_spread:
        lines.append("\\linespread{" + str(line_spread) + "}")
    if par_indent:
        lines.append("\\setlength{\\parindent}{" + str(par_indent) + "}")
    if par_skip:
        lines.append("\\setlength{\\parskip}{" + str(par_skip) + "}")

    geometry = (styles.get("page") or {}).get("geometry") or {}
    if geometry:
        pairs = ",".join(str(k) + "=" + str(v) for k, v in geometry.items())
        lines.append("\\geometry{" + pairs + "}")
    if zihao:
        lines.append("\\zihao{" + str(zihao) + "}")

    for key, env in (("heading1", "section"), ("heading2", "subsection"),
                     ("heading3", "subsubsection")):
        style = styles.get(key) or {}
        fmt = style.get("format")
        level_zihao = style.get("zihao")
        if fmt:
            lines.append("\\ctexset{" + env + "/format={" + str(fmt) + "}}")
        elif level_zihao:
            lines.append(
                "\\ctexset{" + env + "/format={\\zihao{" + str(level_zihao) + "}\\heiti}}"
            )

    fonts = styles.get("fonts") or {}
    for key, setter in (("cjk_main", "setCJKmainfont"), ("cjk_sans", "setCJKsansfont")):
        # 模板指定的字体本机可能没装；用 IfFontExistsTF 兜住，
        # 不让回退路径因为一个字体名直接编译失败
        name = fonts.get(key)
        if name:
            lines.append(
                "\\IfFontExistsTF{" + str(name) + "}{\\" + setter + "{"
                + str(name) + "}}{}"
            )

    if not lines:
        return "% (无模板参数可继承，使用骨架默认格式)"
    return "\n".join(["% ==== 以下排版参数继承自用户模板 ===="] + lines)


def make_title_block(title: str) -> str:
    return "\n".join([
        "\\begin{center}",
        "  {\\zihao{2}\\heiti " + title + "\\par}",
        "\\end{center}",
        "\\vspace{1em}",
    ])


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------

def _inject_abstract_into_template(
    head: str, report: dict[str, Any], notes: list[str]
) -> str:
    """模板有 abstract 环境时把摘要/关键词写进去；无则原样返回（由调用方另处理）。"""
    abstract = (report.get("abstract") or "").strip()
    keywords = (report.get("keywords") or "").strip()
    span = find_abstract_span(head)
    if span is None:
        return head

    if not abstract:
        begin = head.rfind(r"\begin{abstract}", 0, span[0])
        notes.append("md 无摘要 → 已删除模板 abstract 环境里的示例摘要")
        return head[:begin] + head[span[1] + len(r"\end{abstract}"):]

    inner = head[span[0]:span[1]]
    # 模板抽象区的内容 = 示例摘要文字 + \keywords{...}。只应保留 keywords
    # 命令（它是模板的样式钩子），它之前的示例文字必须丢掉 —— 否则真实摘要
    # 会和示例文字并存，两段都渲染进 PDF。
    kw_cmd = ""
    kw_at: int | None = None
    if keywords:
        m = re.search(r"\\(keywords?)\s*(\[[^\]]*\])?\s*\{", inner)
        if m:
            kw_cmd = m.group(1)
            kw_at = m.start()

    if kw_at is not None:
        kept, replaced = replace_braced_command(inner[kw_at:], kw_cmd, keywords)
        if replaced:
            inner = "\n" + abstract + "\n" + kept
        else:
            inner = "\n" + abstract + "\n"
            notes.append("模板 abstract 区的 keywords 命令未能替换，已丢弃该区原内容")
    else:
        inner = "\n" + abstract + "\n"

    notes.append("已把摘要写入模板 abstract 环境（并丢弃模板的示例文字）")
    new_head = head[:span[0]] + inner + head[span[1]:]

    # 模板摘要区没有 keywords 命令时，把关键词补在 abstract 环境之后。
    # 不能让关键词静默消失 —— 它是课程论文的必备结构。
    if keywords and kw_at is None:
        end_pos = len(head[:span[0]]) + len(inner) + len(r"\end{abstract}")
        new_head = (new_head[:end_pos]
                    + "\n\noindent\\textbf{关键词：}" + keywords
                    + new_head[end_pos:])
        notes.append("模板 abstract 区无 \\keywords 命令 → 关键词已补在 abstract 环境之后")
    return new_head


def abstract_block(abstract: str, keywords: str) -> str:
    block = ["\\begin{abstract}", abstract]
    if keywords:
        block.append("\\noindent\\textbf{关键词：}" + keywords)
    block.append("\\end{abstract}")
    return "\n".join(block)


def assemble_from_shell(
    profile: dict[str, Any],
    template_text: str,
    body: str,
    report: dict[str, Any],
    notes: list[str],
) -> tuple[str, str | None]:
    """把正文注入模板外壳。返回 (paper.tex 内容, 模板要求的 bib 文件名)。"""
    lines = template_text.split("\n")
    inj = profile["injection"]
    start_line = safe_int(inj.get("start_line"))
    stop_line = safe_int(inj.get("stop_line"))
    if start_line is None or stop_line is None:
        raise ValueError("profile.injection 缺少有效的 start_line/stop_line")

    head = "\n".join(lines[:start_line - 1])
    tail = "\n".join(lines[stop_line - 1:])

    title = (report.get("title") or "").strip()
    if title:
        head, n = replace_braced_command(head, "title", title)
        if n:
            notes.append("已用论文标题替换模板 \\title 的内容")

    had_abstract_env = find_abstract_span(head) is not None
    head = _inject_abstract_into_template(head, report, notes)

    if title and not re.search(r"\\title\s*\{", head):
        if re.search(r"\\maketitle\b", head):
            m = re.search(r"\\begin\{document\}", head)
            ins = "\\title{" + title + "}\n"
            head = (head[:m.start()] + ins + head[m.start():]) if m else head + ins
            notes.append("模板无 \\title → 已在正文开始前补入（\\maketitle 生效）")
        else:
            body = make_title_block(title) + "\n\n" + body
            notes.append("模板无 \\maketitle → 标题以居中标题块加到正文开头")

    abstract = (report.get("abstract") or "").strip()
    if abstract and not had_abstract_env:
        body = abstract_block(abstract, (report.get("keywords") or "").strip()) \
            + "\n\n" + body
        notes.append("模板无 abstract 环境 → 摘要已加到正文开头")

    head, pkg_notes = ensure_packages(head, body, profile.get("capabilities") or {})
    notes.extend(pkg_notes)

    # ---- 尾部：参考文献 ----
    bib_name = None
    if report.get("bib_mode") == "thebibliography":
        stripped_tail, removed = strip_bib_mechanism(tail)
        if removed:
            tail = stripped_tail
            notes.append(
                "模板自带 " + "、".join(removed)
                + " 已剥离（正文内嵌 thebibliography，否则会出现两份参考文献）"
            )
    else:
        bib_name = bib_target_filename(tail)
        if bib_name:
            notes.append("模板要求的 .bib 文件名为 " + bib_name)
        else:
            notes.append(
                "模板声明了 bib 机制但未找到 \\bibliography/\\addbibresource，"
                "参考文献可能不会渲染"
            )

    return head + "\n" + body.rstrip("\n") + "\n\n" + tail, bib_name


def assemble_from_skeleton(
    profile: dict[str, Any],
    body: str,
    report: dict[str, Any],
    skeleton_path: Path,
    notes: list[str],
) -> str:
    if not skeleton_path.exists():
        raise FileNotFoundError("内置骨架不存在: " + str(skeleton_path))

    text = skeleton_path.read_text(encoding="utf-8")
    abstract = (report.get("abstract") or "").strip()
    keywords = (report.get("keywords") or "").strip()
    title = (report.get("title") or "").strip()

    if not abstract:
        text = re.sub(
            r"%%WP_ABSTRACT_BEGIN%%.*?%%WP_ABSTRACT_END%%", "", text, flags=re.DOTALL
        )

    replacements = {
        "%%WP_TITLE%%": title or "（缺论文标题）",
        "%%WP_AUTHOR%%": "",
        "%%WP_STYLE_OVERRIDES%%": make_style_overrides(profile),
        "%%WP_BIBLIOGRAPHY%%": bib_block(profile, report),
        "%%WP_ABSTRACT%%": abstract,
        "%%WP_KEYWORDS%%": keywords,
        "%%WP_ABSTRACT_BEGIN%%": "",
        "%%WP_ABSTRACT_END%%": "",
        "%%WP_CONTENT%%": body.rstrip("\n"),
    }
    for key, value in replacements.items():
        count = text.count(key)
        if count == 0:
            continue
        if count > 1:
            # 占位符多份会导致正文被注入到错误位置（例如注入到 \documentclass
            # 之前，报错是让人摸不着头脑的 "Missing \begin{document}"）
            raise ValueError(
                "骨架占位符 " + key + " 出现 " + str(count) + " 次（应为 1 次）"
            )
        text = text.replace(key, value)
    notes.append("已使用内置骨架 assets/default_paper.tex")
    return text


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------

def run_latexmk(workdir: Path, engine: str, jobname: str, timeout: int) -> dict[str, Any]:
    cmd = [
        "latexmk", "-" + engine,
        "-interaction=nonstopmode",
        "-file-line-error",
        jobname + ".tex",
    ]
    empty: dict[str, Any] = {
        "errors": [], "missing_deps": [], "undefined_refs": [], "warnings": [],
    }
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        returncode: int | None = proc.returncode
        stdout = proc.stdout or ""
    except subprocess.TimeoutExpired:
        return dict(empty, status="timeout", returncode=None,
                    stdout_tail="latexmk 超时（" + str(timeout) + "s）")
    except OSError as exc:
        return dict(empty, status="error", returncode=None, stdout_tail=str(exc))

    log_path = workdir / (jobname + ".log")
    log_text = log_path.read_text(encoding="utf-8", errors="replace") \
        if log_path.exists() else ""
    if not log_text:
        log_text = stdout

    errors, missing, undefined, warnings = parse_latex_log(log_text)
    return {
        "status": "ok",
        "returncode": returncode,
        "errors": errors[:25],
        "missing_deps": missing,
        "undefined_refs": undefined,
        "warnings": warnings[:15],
        "stdout_tail": "\n".join((stdout or "").strip().split("\n")[-8:]),
    }


def fill_missing_deps(workdir: Path, missing: list[str]) -> list[str]:
    r"""给缺失的图片补占位，让编译能继续（全部记入报告，不静默）。

    刻意不为缺失的 .bib 生成空占位文件：空 .bib 会让所有 \cite 静默渲染成
    [?]，比直接编译失败更隐蔽 —— 那是把“响亮的错误”换成“安静的错稿”。
    """
    filled: list[str] = []
    for name in missing:
        target = Path(name)
        if not target.is_absolute():
            target = workdir / name
        if target.exists():
            continue
        if target.suffix.lower() != ".png":
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = target.write_bytes(_placeholder_png(target.name))
        except OSError:
            continue
        filled.append(name + "（已生成占位图）")
    return filled


def _placeholder_png(label: str) -> bytes:
    """生成带边框的占位图。尺寸取常规比例，避免极端宽高比带来的排版意外。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return PLACEHOLDER_PNG
    image = Image.new("RGB", (800, 400), "#f7f7f7")
    draw = ImageDraw.Draw(image)
    draw.rectangle([2, 2, 797, 397], outline="#cc0000", width=5)
    draw.line([2, 2, 797, 397], fill="#cc0000", width=3)
    draw.line([797, 2, 2, 397], fill="#cc0000", width=3)
    draw.text((16, 16), "MISSING FIGURE", fill="#cc0000")
    draw.text((16, 36), label if label.isascii() else "(non-ascii name)",
              fill="#cc0000")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build(
    workdir: Path,
    jobname: str,
    engine: str,
    timeout: int,
    max_repair: int,
    notes: list[str],
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    filled: list[str] = []
    compile_info: dict[str, Any] = {}
    pdf = workdir / (jobname + ".pdf")

    # 每次 build 从干净状态起跑：外壳阶段可能留下 bibtex 的 .aux/.bbl，
    # 回退到骨架（thebibliography）时会与残留状态互相污染。
    clean_aux(workdir, jobname)

    for attempt in range(1, max_repair + 2):
        # 先删掉上一轮的 PDF。否则本轮编译失败时，残留的旧 PDF 会被
        # "PDF 存在且非空"的判定误认为本次成功，交付出错版本还毫无察觉。
        with contextlib.suppress(OSError):
            pdf.unlink()

        compile_info = run_latexmk(workdir, engine, jobname, timeout)
        produced = pdf.exists() and pdf.stat().st_size > 0
        missing = compile_info.get("missing_deps") or []
        compile_info["produced_pdf"] = produced

        # status 必须反映编译结果，不能因为"子进程跑完了"就报 ok：
        # latexmk 在有 LaTeX 错误时会删掉输出 PDF，此时 status 应为 failed。
        raw_status = compile_info.get("status")
        if raw_status in ("timeout", "error"):
            status = raw_status
        elif not produced:
            status = "failed"
        elif missing:
            status = "partial"
        else:
            status = "ok"
        compile_info["status"] = status

        attempts.append({
            "attempt": attempt,
            "result": status,
            "produced_pdf": produced,
            "missing_deps": missing,
            "errors": [e.get("message") for e in compile_info.get("errors", [])][:5],
        })

        # 干净成功才提前结束
        if produced and not missing:
            break
        if attempt > max_repair:
            break

        # 缺图不会让 LaTeX 报错（graphicx 只警告），PDF 照样生成 —— 但这种
        # "图位留空"的 PDF 不能直接交付。所以缺依赖时主动补占位并重编。
        new_fills = fill_missing_deps(workdir, missing)
        if not new_fills:
            bib_missing = [d for d in missing if d.lower().endswith(".bib")]
            if bib_missing:
                notes.append(
                    "缺失的 .bib 不可用占位修补（空 .bib 会让引用全部渲染成 [?]，"
                    "比编译失败更隐蔽），请先生成文献文件：" + "、".join(bib_missing)
                )
            break  # 没有可自动修复的项，再编也是同样结果
        filled.extend(new_fills)
        notes.extend("编译缺失依赖已补占位：" + f for f in new_fills)

    compile_info["attempts"] = attempts
    compile_info["filled_placeholders"] = filled
    compile_info["missing_deps"] = [
        d for d in (compile_info.get("missing_deps") or [])
        if not any(d in f for f in filled)
    ]
    return compile_info


def pdf_pages(pdf: Path) -> int | None:
    if shutil.which("pdfinfo") is None:
        return None
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True,
                             text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    return safe_int(m.group(1)) if m else None


def clean_aux(workdir: Path, jobname: str) -> None:
    for suffix in AUX_SUFFIXES:
        candidate = workdir / (jobname + suffix)
        if candidate.exists():
            with contextlib.suppress(OSError):
                candidate.unlink()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LaTeX 论文组装与 PDF 编译")
    _ = parser.add_argument("--body", required=True, help="md_to_latex 产出的 body.tex")
    _ = parser.add_argument("--profile", required=True, help="latex_profile.json")
    _ = parser.add_argument("--report", help="md_to_latex 产出的转换报告 JSON")
    _ = parser.add_argument("--bib", help="md_to_latex 产出的 refs.bib")
    _ = parser.add_argument("--template", help="模板 .tex（默认取 profile.source_file）")
    _ = parser.add_argument("--skeleton", help="内置骨架路径")
    _ = parser.add_argument("--output", "-o", required=True, help="输出 PDF 路径")
    _ = parser.add_argument("--workdir", help="编译工作目录（默认 body.tex 所在目录）")
    _ = parser.add_argument("--jobname", default="paper", help="TeX 作业名（默认 paper）")
    _ = parser.add_argument("--title", help="论文标题（覆盖报告）")
    _ = parser.add_argument("--engine", help="编译引擎（默认取 profile.engine）")
    _ = parser.add_argument("--fallback-skeleton", action="store_true",
                            help="强制使用内置骨架，不注入用户模板")
    _ = parser.add_argument("--keep-aux", action="store_true", help="保留 .aux/.log 等中间文件")
    _ = parser.add_argument("--dry-run", action="store_true", help="只写 paper.tex，不编译")
    _ = parser.add_argument("--timeout", type=int, default=180, help="单次编译超时秒数")
    _ = parser.add_argument("--max-repair", type=int, default=2, help="缺依赖自动补齐重编轮数")
    _ = parser.add_argument("--build-report", help="编译报告 JSON 输出路径")
    return parser


def _load_json(path: Path, label: str) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print("[ERROR] 无法解析" + label + "：" + str(exc), file=sys.stderr)
        return None


def main() -> int:
    args = build_parser().parse_args()

    body_path = Path(args.body).expanduser()
    profile_path = Path(args.profile).expanduser()
    for path, label in ((body_path, "body.tex"), (profile_path, "profile")):
        if not path.exists():
            print("[ERROR] " + label + " 不存在：" + str(path), file=sys.stderr)
            return 1

    profile = _load_json(profile_path, "profile")
    if profile is None:
        return 1
    try:
        body = body_path.read_text(encoding="utf-8")
    except OSError as exc:
        print("[ERROR] 读取 body.tex 失败：" + str(exc), file=sys.stderr)
        return 1

    report: dict[str, Any] = {}
    if args.report:
        report_path = Path(args.report).expanduser()
        if report_path.exists():
            loaded = _load_json(report_path, "转换报告")
            if loaded is None:
                return 1
            report = loaded
    if args.title:
        report["title"] = args.title

    workdir = Path(args.workdir).expanduser() if args.workdir else body_path.parent
    workdir.mkdir(parents=True, exist_ok=True)

    skeleton_path = Path(args.skeleton).expanduser() if args.skeleton else DEFAULT_SKELETON
    engine = args.engine or profile.get("engine") or "xelatex"
    notes: list[str] = []
    fallback_reason = ""

    template_path: Path | None = None
    if args.fallback_skeleton:
        fallback_reason = "--fallback-skeleton 指定"
    elif profile.get("usable_as_shell"):
        candidate = Path(args.template).expanduser() if args.template \
            else Path(profile["source_file"]).expanduser()
        if candidate.exists():
            template_path = candidate
        else:
            fallback_reason = "模板文件不存在：" + str(candidate)
    else:
        fallback_reason = "模板不可用作外壳（" + str(
            (profile.get("injection") or {}).get("reason", "未知")) + "）"

    mode = "skeleton" if template_path is None else "shell"
    bib_name: str | None = None
    try:
        if template_path is None:
            paper_tex = assemble_from_skeleton(profile, body, report, skeleton_path, notes)
        else:
            template_text = template_path.read_text(encoding="utf-8")
            paper_tex, bib_name = assemble_from_shell(
                profile, template_text, body, report, notes)
    except (OSError, ValueError) as exc:
        print("[ERROR] 组装失败：" + str(exc), file=sys.stderr)
        return 1

    paper_tex_path = workdir / (args.jobname + ".tex")
    _ = paper_tex_path.write_text(paper_tex, encoding="utf-8")

    # bib 模式下落盘 .bib，文件名必须跟模板声明的对上
    bib_written = None
    if args.bib and report.get("bib_mode") == "bibtex":
        src = Path(args.bib).expanduser()
        if src.exists():
            # 骨架固定声明 \bibliography{refs}，所以回退路径必须落成 refs.bib
            target_name = bib_name or ("refs.bib" if mode == "skeleton" else src.name)
            target = workdir / target_name
            if src.resolve() != target.resolve():
                _ = shutil.copyfile(src, target)
            bib_written = target.name
            notes.append("参考文献已落盘为 " + target.name)

    if mode == "skeleton":
        print("[FALLBACK] 未使用用户模板，原因：" + fallback_reason, file=sys.stderr)

    if args.dry_run:
        print("[OK] 已组装 " + str(paper_tex_path) + "（--dry-run，未编译）")
        for note in notes:
            print("     - " + note)
        return 0

    compile_info = build(workdir, args.jobname, engine, args.timeout,
                         args.max_repair, notes)
    pdf_path = workdir / (args.jobname + ".pdf")
    success = bool(compile_info.get("produced_pdf"))

    # 外壳路径编译失败 → 用内置骨架再试一次（用户仍有 PDF 可交，且原因明示）
    if not success and mode == "shell":
        reason = "模板外壳编译失败（" + str(len(compile_info.get("attempts", []))) + " 轮）"
        print("[RETRY] " + reason + " → 改用内置骨架重试", file=sys.stderr)
        notes.append("模板外壳编译失败，已回退内置骨架：" + reason)
        # 保留外壳阶段的诊断：否则回退后 report 里只剩骨架阶段的信息，
        # 外壳为何失败就彻底断线了
        shell_compile = compile_info
        try:
            paper_tex = assemble_from_skeleton(profile, body, report, skeleton_path, notes)
        except (OSError, ValueError) as exc:
            print("[ERROR] 骨架组装失败：" + str(exc), file=sys.stderr)
            return 3
        _ = paper_tex_path.write_text(paper_tex, encoding="utf-8")
        mode = "skeleton"
        fallback_reason = reason
        if report.get("bib_mode") == "bibtex" and args.bib:
            src = Path(args.bib).expanduser()
            if src.exists() and src.resolve() != (workdir / "refs.bib").resolve():
                _ = shutil.copyfile(src, workdir / "refs.bib")
                bib_written = "refs.bib"
        compile_info = build(workdir, args.jobname, engine, args.timeout,
                             args.max_repair, notes)
        compile_info["shell_phase"] = shell_compile
        success = bool(compile_info.get("produced_pdf"))
        print("[FALLBACK] 未使用用户模板，原因：" + fallback_reason, file=sys.stderr)

    result: dict[str, Any] = {
        "mode": mode,
        "fallback_reason": fallback_reason or None,
        "template_used": str(template_path) if template_path else None,
        "skeleton_used": str(skeleton_path) if mode == "skeleton" else None,
        "engine": engine,
        "paper_tex": str(paper_tex_path),
        "bib_written": bib_written,
        "pdf": str(pdf_path) if success else None,
        "pages": None,
        "pdf_bytes": None,
        "success": success,
        "compile": compile_info,
        "notes": notes,
    }

    if success:
        result["pdf_bytes"] = pdf_path.stat().st_size
        result["pages"] = pdf_pages(pdf_path)
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copyfile(pdf_path, out_path)
        print("[OK] PDF 已生成：" + str(out_path))
        print(
            "     模式："
            + ("用户模板外壳" if mode == "shell" else "内置骨架（回退）")
            + " | 引擎：" + engine
            + " | 页数：" + str(result["pages"] or "?")
            + " | 大小：" + str(round(result["pdf_bytes"] / 1024, 1)) + " KB"
        )
        if compile_info.get("errors"):
            print(
                "     [WARN] 编译日志里有 " + str(len(compile_info["errors"]))
                + " 条错误信息（PDF 已生成，可能是非致命）",
                file=sys.stderr,
            )
        if compile_info.get("missing_deps"):
            print(
                "     [WARN] 仍有缺失依赖（图位可能是空的，请补上对应文件后重编）："
                + "、".join(compile_info["missing_deps"][:6]),
                file=sys.stderr,
            )
        if compile_info.get("undefined_refs"):
            print("     [WARN] 存在未解析的引用/Citation：", file=sys.stderr)
            for item in compile_info["undefined_refs"][:5]:
                print("       - " + item, file=sys.stderr)
    else:
        print("[ERROR] 编译失败，未生成 PDF", file=sys.stderr)
        print("  保留 paper.tex：" + str(paper_tex_path), file=sys.stderr)
        for err in (compile_info.get("errors") or [])[:8]:
            print("  L" + str(err.get("line")) + ": " + str(err.get("message")),
                  file=sys.stderr)

    for note in notes:
        print("     · " + note)

    if args.build_report:
        report_out = Path(args.build_report)
        report_out.parent.mkdir(parents=True, exist_ok=True)
        _ = report_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.keep_aux:
        clean_aux(workdir, args.jobname)

    return 0 if success else 3


if __name__ == "__main__":
    raise SystemExit(main())
