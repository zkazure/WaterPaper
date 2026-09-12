"""LaTeX 链路测试。

重点不是覆盖率，而是给「实测踩过的坑」上回归防线：每个测试对应一个真实 bug
或一条不可违反的约定，注释里写明它防的是什么。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import analyze_latex_template as alt
import build_paper_pdf as bpp
import md_to_latex as mtl
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEMPLATES = FIXTURES / "templates"
REPO_ROOT = Path(__file__).resolve().parent.parent
SKELETON = REPO_ROOT / "assets" / "default_paper.tex"

HAS_LATEXMK = shutil.which("latexmk") is not None
HAS_XELATEX = shutil.which("xelatex") is not None

# 这三个 fixture 覆盖了模板处理的三种真实形态
FULL_TEMPLATE = TEMPLATES / "full" / "template.tex"
NO_BIB_TEMPLATE = TEMPLATES / "no_bib" / "template.tex"
BROKEN_TEMPLATE = TEMPLATES / "broken" / "template.tex"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def analyze_no_probe(template: Path) -> dict[str, Any]:
    return alt.analyze(template, do_probe=False)


@pytest.fixture(scope="module")
def full_profile() -> dict[str, Any]:
    return analyze_no_probe(FULL_TEMPLATE)


@pytest.fixture(scope="module")
def no_bib_profile() -> dict[str, Any]:
    return analyze_no_probe(NO_BIB_TEMPLATE)


def minimal_profile(**capabilities: Any) -> dict[str, Any]:
    caps = {
        "graphicx": True, "booktabs": True, "tabularx": False,
        "hyperref": True, "bibtex": False, "biblatex": False,
    }
    caps.update(capabilities)
    return {
        "capabilities": caps,
        "styles": {"heading1": {"auto_number": True}},
        "engine": "xelatex",
    }


def run_tool(*args: object) -> subprocess.CompletedProcess[str]:
    """按 CLI 契约跑工具脚本（测的是命令行接口，不是内部函数）。"""
    return subprocess.run([sys.executable, *[str(a) for a in args]],
                          capture_output=True, text=True, check=False)


def convert(md_text: str, profile: dict[str, Any] | None = None,
            **kwargs: Any) -> mtl.MarkdownToLatex:
    converter = mtl.MarkdownToLatex(profile or minimal_profile(), **kwargs)
    converter.convert(md_text)
    return converter


# ---------------------------------------------------------------------------
# 转义：% 是最高频事故点（不转义会把后半行整段注释掉）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("占比 43.2% 上升", r"占比 43.2\% 上升"),
    ("MSE & MAE", r"MSE \& MAE"),
    ("变量 lstm_hidden", r"变量 lstm\_hidden"),
    ("编号 #2024", r"编号 \#2024"),
    ("花费 $5 元", r"花费 \$5 元"),
    ("集合 {a, b}", r"集合 \{a, b\}"),
    ("x^2 与 y~z", r"x\textasciicircum{}2 与 y\textasciitilde{}z"),
])
def test_escape_latex_specials(raw, expected):
    assert mtl.escape_latex(raw) == expected


def test_escape_latex_keeps_author_escape():
    """作者自己写好的 \\% / \\& 不能被二次转义成 \\textbackslash{}% 之类。"""
    assert mtl.escape_latex(r"已完成 50\% 的样本") == r"已完成 50\% 的样本"
    assert mtl.escape_latex(r"公式 \alpha 与 \beta") == r"公式 \alpha 与 \beta"


def test_inline_protects_math_from_escaping():
    """数学环境里的 ^ _ \\ 不能被我方转义（否则公式直接编译不过）。"""
    assert mtl.MarkdownToLatex(minimal_profile()).inline(r"$R^2$ 为 0.912") \
        == r"$R^2$ 为 0.912"


def test_inline_code_escapes_inside_but_keeps_tt():
    assert mtl.MarkdownToLatex(minimal_profile()).inline("`dry_bulb` 字段") \
        == r"\texttt{dry\_bulb} 字段"


def test_inline_bold_and_link():
    profile = minimal_profile(hyperref=True)
    result = mtl.MarkdownToLatex(profile).inline(
        "**要点**，见 [原文](https://example.org/a_b)")
    assert r"\textbf{要点}" in result
    assert r"\href{https://example.org/a\_b}{原文}" in result


def test_inline_link_without_hyperref_degrades_to_text():
    result = mtl.MarkdownToLatex(minimal_profile(hyperref=False)).inline(
        "[原文](https://example.org)")
    assert result == "原文"


# ---------------------------------------------------------------------------
# 引用标注
# ---------------------------------------------------------------------------

def _converter_with_refs(numbers=(1, 2, 3), **caps) -> mtl.MarkdownToLatex:
    converter = mtl.MarkdownToLatex(minimal_profile(**caps))
    for n in numbers:
        converter.add_ref_entry(n, f"条目{n}")
    return converter


def test_inline_citation_single_and_ranges():
    converter = _converter_with_refs()
    assert converter.inline("见[1]") == r"见\cite{lit1}"
    assert converter.inline("见[2-3]") == r"见\cite{lit2,lit3}"
    assert converter.inline("见[1,3]") == r"见\cite{lit1,lit3}"


def test_inline_bracket_number_that_is_not_a_citation_is_left_alone():
    """[2024] 这类年份不能被认成引用，否则会渲染成 [??]。"""
    converter = _converter_with_refs()
    assert converter.inline("（2024）与[2024]年") == "（2024）与[2024]年"


def test_undefined_citation_is_warned_not_silently_dropped():
    """回归：漏引检测曾是死代码。

    原判据是「所有数字都在文献表里才算引用」，于是 [9] 直接原样返回，永远不会
    进入 cite_used，finalize 里的 `cite_used - ref_numbers` 恒为空集 —— 即
    「正文引用了不存在的编号」这条警告一次也不可能触发。结果：[9] 被安静地
    写进 PDF，排版完全正常，指向空处。
    """
    converter = _converter_with_refs(numbers=(1, 2))
    converter.convert("正文[1]。又见[9]。\n\n## 参考文献\n\n[1] 甲\n[2] 乙\n")
    assert converter.undefined_cites == [9]
    assert any("不存在的编号" in w for w in converter.warnings)
    # [2024] 这类年份不能被误判成漏引
    assert converter.inline("（2024）与[2024]年") == "（2024）与[2024]年"


# ---------------------------------------------------------------------------
# 章节号 / 图题号剥离
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("一、引言", "引言"),
    ("二、模型与方法", "模型与方法"),
    ("1.1 研究背景", "研究背景"),
    ("1.1.1 数据来源", "数据来源"),
    ("第一章 绪论", "绪论"),
    ("第2章 方法", "方法"),
])
def test_strip_heading_number(raw, expected):
    assert mtl.strip_heading_number(raw) == expected


@pytest.mark.parametrize("raw", ["一体化设计", "2024年数据", "第三方接口", "十分重要的结论"])
def test_strip_heading_number_never_eats_real_words(raw):
    """编号必须带分隔符/空格才算编号，否则「一体化」会被剥成「体化」。"""
    assert mtl.strip_heading_number(raw) == raw


@pytest.mark.parametrize("raw,expected", [
    ("图 1 LSTM 预测模型结构示意图", "LSTM 预测模型结构示意图"),
    ("表 2-1 变量说明", "变量说明"),
    ("图 3: 对比结果", "对比结果"),
])
def test_strip_caption_number(raw, expected):
    assert mtl.strip_caption_number(raw) == expected


def test_strip_caption_number_keeps_text_when_only_number():
    assert mtl.strip_caption_number("图 1") == "图 1"


# ---------------------------------------------------------------------------
# 模板分析器
# ---------------------------------------------------------------------------

def test_analyzer_prefers_comment_anchor_not_starred_section(full_profile):
    """回归：注释锚点检测曾因传入去注释文本而完全失效，退化成「首个 \\section」。

    更糟的是那个 section 是 \\section*{学位论文原创性声明} —— 会把声明页整段删掉。
    """
    injection = full_profile["injection"]
    assert injection["anchor_kind"] == "comment"
    assert injection["is_guess"] is False
    assert "正文开始" in injection["anchor_text"]
    assert full_profile["usable_as_shell"] is True


def test_analyzer_keeps_bibliographystyle_in_tail(full_profile):
    """回归：区间终点落在 \\bibliography 上时，紧邻的 \\bibliographystyle 被误删，
    模板的著录格式声明会静默丢失。"""
    tail = full_profile["shell"]["tail"]
    assert r"\bibliographystyle{plain}" in tail
    assert r"\bibliography{refs}" in tail
    assert full_profile["injection"]["keeps_template_bibliography"] is True


def test_analyzer_never_removes_front_matter(full_profile):
    """封面页与原创性声明页必须在替换区间之外。"""
    front = full_profile["shell"]["front_matter"]
    assert "原创性声明" in front
    assert "titlepage" in front
    assert r"\tableofcontents" in front
    assert "原文性声明" not in full_profile["injection"]["removed_preview"]


def test_analyzer_body_zihao_not_polluted_by_cover_page(full_profile):
    """回归：全文扫 \\zihao{} 会取到封面姓名处的字号当正文默认字号。"""
    assert full_profile["styles"]["body"]["zihao"] is None
    assert full_profile["styles"]["body"]["line_spread"] == "1.5"
    assert full_profile["styles"]["body"]["par_indent"] == "2em"
    assert full_profile["styles"]["heading1"]["zihao"] == "3"


def test_analyzer_detects_engine_from_magic_comment(full_profile, no_bib_profile):
    assert full_profile["engine"] == "xelatex"
    assert no_bib_profile["engine"] == "lualatex"
    assert "magic_comment" in full_profile["engine_source"]


def test_analyzer_auto_number_flag(full_profile):
    """模板自动编号时必须告诉转换器剥掉 md 标题序号，否则渲染成「一、 一、引言」。"""
    assert full_profile["styles"]["heading1"]["auto_number"] is True


def test_analyzer_auto_number_false_when_template_defines_own_number(tmp_path):
    text = FULL_TEMPLATE.read_text(encoding="utf-8").replace(
        r"number = \chinese{section},", "number = {},")
    patched = tmp_path / "manual.tex"
    patched.write_text(text, encoding="utf-8")
    profile = analyze_no_probe(patched)
    assert profile["styles"]["heading1"]["auto_number"] is False


def test_analyzer_broken_template_not_usable():
    profile = analyze_no_probe(BROKEN_TEMPLATE)
    assert profile["usable_as_shell"] is False
    assert profile["injection"]["usable"] is False
    assert any("回退" in note for note in profile["diagnostics"])


def test_analyzer_detects_absent_bib_mechanism(no_bib_profile):
    assert no_bib_profile["capabilities"]["has_bib_mechanism"] is False
    assert no_bib_profile["capabilities"]["bibtex"] is False
    assert no_bib_profile["capabilities"]["biblatex"] is False


# ---------------------------------------------------------------------------
# md → LaTeX
# ---------------------------------------------------------------------------

def converted_sample(profile: dict[str, Any]) -> mtl.MarkdownToLatex:
    converter = mtl.MarkdownToLatex(
        profile,
        structured_refs=json.loads(
            (FIXTURES / "sample_refs.json").read_text(encoding="utf-8")),
        charts_dir=str(FIXTURES / "charts"),
        md_dir=str(FIXTURES),
        output_dir=str(FIXTURES),
    )
    converter.convert((FIXTURES / "sample_paper.md").read_text(encoding="utf-8"))
    return converter


def test_keywords_are_captured_and_never_leak_into_body(full_profile):
    """回归：`## 关键词` 标题没有冒号时，标题字面量被当成关键词值，
    真正那行关键词就泄漏进正文，渲染成正文首行孤立的「深度学习；水资源；…」。"""
    converter = converted_sample(full_profile)
    assert converter.keywords == "深度学习；水资源；需求预测；长短期记忆网络"
    body = "\n".join(converter.body)
    assert "需求预测；长短期记忆网络" not in body
    assert "关键词" not in body


def test_abstract_is_extracted_and_kept_out_of_body(full_profile):
    converter = converted_sample(full_profile)
    assert converter.abstract_parts
    assert converter.abstract_parts[0].startswith("本文以某市 2019")
    assert "本文以某市" not in "\n".join(converter.body)


def test_headings_are_mapped_and_numbers_stripped(full_profile):
    body = "\n".join(converted_sample(full_profile).body)
    assert r"\section{引言}" in body
    assert r"\subsection{研究背景}" in body
    assert r"\subsubsection{数据来源}" in body
    # 不能出现「一、引言」这种自带序号（模板会自己编号）
    assert r"\section{一、" not in body


def test_percent_and_ampersand_render_safely_in_body(full_profile):
    body = "\n".join(converted_sample(full_profile).body)
    assert r"43.2\%" in body
    assert r"MSE \& MAE" in body
    assert "43.2%" not in body


def test_citations_map_to_bib_keys(full_profile):
    body = "\n".join(converted_sample(full_profile).body)
    assert r"\cite{lit2,lit3}" in body
    assert r"\cite{lit1,lit3}" in body
    assert "[2-3]" not in body


def test_figures_and_tables_are_emitted_with_correct_caption_side(full_profile):
    body = "\n".join(converted_sample(full_profile).body)
    assert body.count(r"\begin{figure}") == 2
    assert body.count(r"\begin{table}") == 1
    # 图题在图之后（\includegraphics 先于 \caption）
    fig = body[body.index(r"\begin{figure}"):body.index(r"\end{figure}")]
    assert fig.index(r"\includegraphics") < fig.index(r"\caption")
    # 表题在表之前
    table = body[body.index(r"\begin{table}"):body.index(r"\end{table}")]
    assert table.index(r"\caption") < table.index(r"\begin{tabular}")


def test_image_width_follows_aspect_ratio(full_profile):
    """回归：宽度启发式曾拿「写进 tex 的相对路径」去读 PNG，解析不到文件后静默
    退化成兜底宽度。宽图应铺满、竖长图应收窄。"""
    body = "\n".join(converted_sample(full_profile).body)
    assert r"width=0.98\textwidth" in body   # fig1 900x380
    assert r"width=0.6\textwidth" in body    # fig2 520x900


def test_bib_mode_follows_template_mechanism(full_profile, no_bib_profile):
    assert converted_sample(full_profile).bib_mode == "bibtex"
    assert converted_sample(no_bib_profile).bib_mode == "thebibliography"


def test_thebibliography_embeds_md_citation_text(no_bib_profile):
    body = "\n".join(converted_sample(no_bib_profile).body)
    assert r"\begin{thebibliography}" in body
    assert r"\bibitem{lit1}" in body
    # md 原文大小写必须原样保留
    assert "基于 LSTM 的城市用水量短期预测" in body


def test_bib_protects_title_case(full_profile):
    """回归：.bst（plain 等）会把 title 整体小写，实测「基于 LSTM 的…」被渲染成
    「基于 lstm 的…」。must 多包一层 {} 保护。"""
    bib = converted_sample(full_profile).build_bib()
    assert "title = {{基于 LSTM 的城市用水量短期预测}}" in bib
    assert "@article{lit1" in bib
    assert "@inproceedings{lit2" in bib
    assert "@phdthesis{lit3" in bib
    assert "pages = {301--310}" in bib
    assert "doi = {10.13243/j.cnki.slxb.2024.03.007}" in bib


def test_happy_path_is_warning_free_notes_do_not_flip_exit_code(full_profile):
    """回归：bibtex 模式下「编号会被重排」是**本模板下必然如此**的说明，不是稿件
    缺陷。它曾与真问题共用一个 warnings 列表，于是 bibtex 模式下退出码永远是 3，
    「3 = 有问题」的信号被噪声抹平；漏引那条真警告就淹在里面了。

    现在：notes 只说明、不改退出码；warnings 才是稿件缺陷。
    """
    converter = converted_sample(full_profile)
    assert converter.warnings == []          # 样本论文本身无缺陷
    assert converter.notes                   # 但 bibtex 说明必然存在
    assert any("重排" in n for n in converter.notes)


def test_captionless_table_is_reported(full_profile):
    """无表题的表格在论文里是缺陷，不能安静输出一张裸表。"""
    converter = mtl.MarkdownToLatex(full_profile, md_dir=str(FIXTURES),
                                    charts_dir=str(FIXTURES / "charts"))
    converter.convert("## 一、引言\n\n正文。\n\n| a | b |\n| - | - |\n| 1 | 2 |\n")
    assert any("缺少题注" in w for w in converter.warnings)


def test_chart_placeholder_is_reported_not_silently_dropped():
    converter = convert("# 标题\n\n## 一、引言\n\n正文。\n\n<!-- chart: 折线图 -->\n")
    assert any("图表占位符" in w for w in converter.warnings)
    assert "chart" not in "\n".join(converter.body)


def test_missing_image_is_reported(full_profile):
    converter = mtl.MarkdownToLatex(
        full_profile, md_dir=str(FIXTURES), charts_dir=str(FIXTURES / "charts"))
    converter.convert("# 标题\n\n## 一、引言\n\n![图 9 不存在的图](charts/nope.png)\n")
    assert any("图片未找到" in w for w in converter.warnings)


def test_ref_metadata_mismatch_is_reported(full_profile):
    """编号→结构化元数据是按位置下标映射的，口径不一致会张冠李戴，
    直接威胁「参考文献必须真实可核验」这条硬门槛。"""
    wrong_refs = json.loads((FIXTURES / "sample_refs.json").read_text(encoding="utf-8"))
    wrong_refs[0]["title"] = "完全不相干的一篇天文物理论文标题"
    converter = mtl.MarkdownToLatex(full_profile, structured_refs=wrong_refs,
                                    md_dir=str(FIXTURES),
                                    charts_dir=str(FIXTURES / "charts"))
    converter.convert((FIXTURES / "sample_paper.md").read_text(encoding="utf-8"))
    assert any("对不上" in w for w in converter.warnings)


# ---------------------------------------------------------------------------
# 组装（不编译）
# ---------------------------------------------------------------------------

def test_abstract_injection_drops_template_sample_text(full_profile):
    """回归：注入摘要时保留了整个 abstract 区原内容，模板的示例摘要文字与真实
    摘要并存，两段都渲染进 PDF。"""
    template = FULL_TEMPLATE.read_text(encoding="utf-8")
    report = {
        "title": "基于深度学习的水资源需求预测研究",
        "abstract": "这是一段真实摘要正文。",
        "keywords": "深度学习；水资源",
        "bib_mode": "bibtex",
    }
    notes: list[str] = []
    paper, bib_name = bpp.assemble_from_shell(
        full_profile, template, r"\section{引言}" + "\n\n正文。", report, notes)

    assert "这是一段真实摘要正文。" in paper
    assert "这里是一段模板自带的示例摘要文字" not in paper
    assert r"\keywords{深度学习；水资源}" in paper
    assert bib_name == "refs.bib"
    assert any("示例文字" in n for n in notes)


def test_abstract_without_template_keywords_command_still_keeps_keywords():
    """回归：模板 abstract 区没有 \\keywords 命令时，关键词曾静默消失。"""
    template = NO_BIB_TEMPLATE.read_text(encoding="utf-8")
    profile = analyze_no_probe(NO_BIB_TEMPLATE)
    report = {"title": "标题", "abstract": "真实摘要。",
              "keywords": "甲；乙", "bib_mode": "thebibliography"}
    notes: list[str] = []
    paper, _ = bpp.assemble_from_shell(
        profile, template, "正文。", report, notes)
    assert "真实摘要。" in paper
    assert "甲；乙" in paper
    assert "模板自带示例摘要" not in paper


def test_strip_bib_mechanism_removes_all_forms():
    tail = (
        "\n"
        r"\bibliographystyle{plain}" "\n"
        r"\bibliography{refs}" "\n"
        r"\printbibliography" "\n"
        r"\addbibresource{x.bib}" "\n"
        r"\end{document}"
    )
    stripped, removed = bpp.strip_bib_mechanism(tail)
    assert r"\bibliography" not in stripped
    assert r"\bibliographystyle" not in stripped
    assert r"\printbibliography" not in stripped
    assert r"\addbibresource" not in stripped
    assert r"\end{document}" in stripped
    assert len(removed) == 4


def shell_profile(start: int, stop: int) -> dict[str, Any]:
    """最小可用的外壳 profile（只给 assemble_from_shell 必需字段）。"""
    return {
        "injection": {"start_line": start, "stop_line": stop,
                      "keeps_template_bibliography": True},
        "capabilities": {},
        "styles": {},
    }


SYNTH_TEMPLATE = r"""\documentclass{ctexart}
\usepackage{biblatex}
\addbibresource{refs.bib}
\begin{document}
\maketitle
\section{占位}
\printbibliography
\end{document}"""


def assemble_synthetic(template: str, body: str, report: dict[str, Any] | None = None):
    lines = template.split("\n")
    stop = next(i + 1 for i, line in enumerate(lines)
                if line.strip() and r"\section{占位}" in line)
    notes: list[str] = []
    return bpp.assemble_from_shell(
        shell_profile(stop, stop), template, body,
        report or {"bib_mode": "bibtex"}, notes) + (notes,)


def test_clearpage_flushes_floats_before_bibliography(full_profile):
    r"""回归：参考文献标题独占一页时，正文末尾的图会被 LaTeX 浮动进该页，
    参考文献列表被图从中间切断（实测：p5 [1][2] / p6 图 2 / p7 [3]）。
    """
    report = {"title": "标题", "abstract": "摘要。", "keywords": "甲",
              "bib_mode": "bibtex"}
    notes: list[str] = []
    paper, _ = bpp.assemble_from_shell(
        full_profile, FULL_TEMPLATE.read_text(encoding="utf-8"),
        r"\section{引言}" + "\n\n正文。", report, notes)
    assert r"\clearpage" + "\n" + r"\bibliographystyle{plain}" in paper
    assert any("浮动" in n for n in notes)


def test_clearpage_never_lands_in_the_preamble():
    r"""回归：biblatex 的 \addbibresource 在导言区。若按全文找插入点，
    \clearpage 会被插到 \documentclass 之后、\begin{document} 之前，直接改坏文档。"""
    paper, _, _ = assemble_synthetic(SYNTH_TEMPLATE, "正文。")
    preamble = paper[:paper.index(r"\begin{document}")]
    assert r"\clearpage" not in preamble
    assert r"\addbibresource{refs.bib}" in preamble     # 导言区保持原样
    assert r"\clearpage" + "\n" + r"\printbibliography" in paper


def test_clearpage_is_not_duplicated_when_template_already_clears():
    """模板自己已经清过页就不要再插一个（不改变模板的分页意图）。"""
    template = SYNTH_TEMPLATE.replace(
        r"\printbibliography", r"\clearpage" + "\n" + r"\printbibliography")
    paper, _, _ = assemble_synthetic(template, "正文。")
    assert paper.count(r"\clearpage") == 1


def test_skeleton_also_flushes_floats():
    report = {"title": "标题", "abstract": "摘要。", "keywords": "甲",
              "bib_mode": "bibtex"}
    notes: list[str] = []
    paper = bpp.assemble_from_skeleton(
        minimal_profile(), "正文。", report, SKELETON, notes)
    assert r"\clearpage" + "\n" + r"\bibliographystyle{plain}" in paper


def test_bib_target_filename_reads_template_declaration():
    assert bpp.bib_target_filename(r"\bibliography{refs}") == "refs.bib"
    assert bpp.bib_target_filename(r"\addbibresource{my.bib}") == "my.bib"
    assert bpp.bib_target_filename("no bib here") is None


def test_missing_deps_never_creates_empty_bib(tmp_path):
    """回归：用空 .bib 占位会把「响亮的编译失败」变成「安静的 [?] 错稿」。"""
    filled = bpp.fill_missing_deps(tmp_path, ["refs.bib", "charts/a.png"])
    assert not (tmp_path / "refs.bib").exists()
    assert (tmp_path / "charts" / "a.png").exists()
    assert len(filled) == 1
    assert "refs.bib" not in filled[0]


def test_replace_braced_command_handles_multiline_and_optional_args():
    text = "\\title[short]{\n  旧标题\n}\n\\keywords{旧关键词}"
    replaced, count = bpp.replace_braced_command(text, "title", "新标题")
    assert count == 1
    assert "\\title[short]{新标题}" in replaced
    assert "旧标题" not in replaced
    replaced, count = bpp.replace_braced_command(replaced, "keywords", "甲；乙")
    assert count == 1
    assert "\\keywords{甲；乙}" in replaced


def test_safe_int_and_match_group():
    assert bpp.safe_int("42") == 42
    assert bpp.safe_int(None) is None
    assert bpp.safe_int("abc") is None
    assert bpp.match_group("{a{b}c}", 0, "{", "}") == ("a{b}c", 7)


def test_skeleton_placeholders_each_appear_exactly_once():
    """回归：骨架头部文档注释里曾写出占位符字面量，朴素替换会先命中注释，
    把正文注入到 \\documentclass 之前，报错是令人费解的 Missing \\begin{document}。"""
    text = SKELETON.read_text(encoding="utf-8")
    for key in ("%%WP_TITLE%%", "%%WP_AUTHOR%%", "%%WP_STYLE_OVERRIDES%%",
                "%%WP_BIBLIOGRAPHY%%", "%%WP_ABSTRACT%%", "%%WP_KEYWORDS%%",
                "%%WP_ABSTRACT_BEGIN%%", "%%WP_ABSTRACT_END%%", "%%WP_CONTENT%%"):
        assert text.count(key) == 1, key


def test_skeleton_assembly_leaves_no_placeholder(full_profile):
    report = {"title": "标题", "abstract": "摘要。", "keywords": "甲；乙",
              "bib_mode": "bibtex"}
    notes: list[str] = []
    paper = bpp.assemble_from_skeleton(full_profile, "正文。", report, SKELETON, notes)
    assert "%%WP_" not in paper
    assert r"\bibliographystyle{plain}" in paper
    assert r"\bibliography{refs}" in paper
    assert r"\title{标题}" in paper
    assert "摘要。" in paper


def test_skeleton_without_abstract_removes_the_abstract_block():
    report = {"title": "标题", "abstract": "", "keywords": "",
              "bib_mode": "thebibliography"}
    notes: list[str] = []
    paper = bpp.assemble_from_skeleton(
        minimal_profile(), "正文。", report, SKELETON, notes)
    assert r"\begin{abstract}" not in paper
    assert "%%WP_" not in paper


def test_skeleton_thebibliography_mode_adds_no_bibliography_command():
    """正文已内嵌 thebibliography，骨架不能再加 \\bibliography，否则两份参考文献。"""
    report = {"title": "标题", "abstract": "摘要。", "keywords": "甲",
              "bib_mode": "thebibliography"}
    notes: list[str] = []
    paper = bpp.assemble_from_skeleton(
        minimal_profile(), "正文。", report, SKELETON, notes)
    assert r"\bibliography{" not in paper


def test_style_overrides_carry_template_params(full_profile):
    overrides = bpp.make_style_overrides(full_profile)
    assert r"\linespread{1.5}" in overrides
    assert r"\setlength{\parindent}{2em}" in overrides
    assert r"\geometry{" in overrides


def test_style_overrides_guard_missing_fonts():
    """模板指定的字体本机可能没装，不能让回退路径因为一个字体名直接编译失败。"""
    profile = minimal_profile()
    profile["styles"] = {"fonts": {"cjk_main": "学校的私有宋体"}}
    overrides = bpp.make_style_overrides(profile)
    assert r"\IfFontExistsTF{学校的私有宋体}" in overrides


# ---------------------------------------------------------------------------
# 端到端（真实编译；缺 TeX Live 时跳过）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (HAS_LATEXMK and HAS_XELATEX),
                    reason="需要 TeX Live（latexmk + xelatex）")
@pytest.mark.parametrize("template_name", ["full", "no_bib", "broken"])
def test_pipeline_builds_pdf_end_to_end(template_name, tmp_path):
    """三种模板形态各跑一遍完整链路，断言真的产出 PDF 且引用已解析。"""
    work = tmp_path / "20260912_001"
    charts = work / "charts"
    charts.mkdir(parents=True)
    template = TEMPLATES / template_name / "template.tex"
    work.joinpath("template.tex").write_text(
        template.read_text(encoding="utf-8"), encoding="utf-8")
    for png in (FIXTURES / "charts").glob("*.png"):
        _ = shutil.copyfile(png, charts / png.name)
    md = work / "paper.md"
    _ = shutil.copyfile(FIXTURES / "sample_paper.md", md)
    refs = work / "refs.json"
    _ = shutil.copyfile(FIXTURES / "sample_refs.json", refs)

    tools = REPO_ROOT / "tools"
    profile_path = work / "profile.json"
    body_path = work / "body.tex"
    report_path = work / "convert.json"
    bib_path = work / "refs.bib"
    pdf_path = work / "out.pdf"
    build_report = work / "build.json"

    # 退出码 2 = 模板不可用作外壳（由 design 定义）；build 会自动回退骨架，不是错误
    assert run_tool(tools / "analyze_latex_template.py", template,
                    "--json-out", profile_path, "--no-probe").returncode in (0, 2)
    # 样本论文无缺陷 → 0（bibtex 模式下的编号重排说明走 notes，不翻转退出码）
    assert run_tool(tools / "md_to_latex.py", md, "-o", body_path,
                    "--profile", profile_path, "--refs", refs,
                    "--charts-dir", charts, "--bib-out", bib_path,
                    "--report", report_path).returncode == 0
    build = run_tool(tools / "build_paper_pdf.py", "--body", body_path,
                     "--profile", profile_path, "--report", report_path,
                     "--bib", bib_path, "-o", pdf_path,
                     "--build-report", build_report)
    assert build.returncode == 0, build.stderr
    assert pdf_path.exists() and pdf_path.stat().st_size > 0

    info = json.loads(build_report.read_text(encoding="utf-8"))
    assert info["success"] is True
    assert info["pages"] and info["pages"] > 0
    assert info["compile"]["missing_deps"] == []
    assert info["compile"]["undefined_refs"] == []
    # 缺图占位图不允许留在交付物里
    assert info["compile"]["filled_placeholders"] == []


@pytest.mark.skipif(not (HAS_LATEXMK and HAS_XELATEX), reason="需要 TeX Live")
def test_pipeline_falls_back_to_skeleton_when_template_broken(tmp_path):
    """残缺模板必须回退骨架，且回退后引用仍能正常解析（骨架要补 \\bibliography）。"""
    work = tmp_path / "20260912_002"
    work.mkdir(parents=True)
    charts = work / "charts"
    charts.mkdir()
    for png in (FIXTURES / "charts").glob("*.png"):
        _ = shutil.copyfile(png, charts / png.name)
    broken = work / "template.tex"
    _ = shutil.copyfile(BROKEN_TEMPLATE, broken)
    md = work / "paper.md"
    _ = shutil.copyfile(FIXTURES / "sample_paper.md", md)
    refs = work / "refs.json"
    _ = shutil.copyfile(FIXTURES / "sample_refs.json", refs)

    tools = REPO_ROOT / "tools"
    profile_path = work / "profile.json"
    body_path = work / "body.tex"
    report_path = work / "convert.json"
    bib_path = work / "refs.bib"
    build_report = work / "build.json"

    _ = run_tool(tools / "analyze_latex_template.py", broken,
                 "--json-out", profile_path, "--no-probe")
    _ = run_tool(tools / "md_to_latex.py", md, "-o", body_path,
                 "--profile", profile_path, "--refs", refs,
                 "--charts-dir", charts, "--bib-out", bib_path,
                 "--report", report_path)
    build = run_tool(tools / "build_paper_pdf.py", "--body", body_path,
                     "--profile", profile_path, "--report", report_path,
                     "--bib", bib_path, "-o", work / "out.pdf",
                     "--build-report", build_report)
    assert build.returncode == 0, build.stderr
    assert "[FALLBACK]" in build.stderr

    info = json.loads(build_report.read_text(encoding="utf-8"))
    assert info["mode"] == "skeleton"
    assert info["fallback_reason"]
    assert info["success"] is True
    assert info["compile"]["undefined_refs"] == []


def test_fixture_charts_can_be_regenerated():
    """make_charts.py 必须可重复执行（fixture 自愈能力）。"""
    script = FIXTURES / "make_charts.py"
    assert script.exists()
    result = subprocess.run([sys.executable, str(script)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    for name in ("fig1_model.png", "fig2_compare.png"):
        assert (FIXTURES / "charts" / name).exists()
