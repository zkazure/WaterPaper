"""docx_io 回归测试。

不做全面覆盖，只钉住实际踩到过的缺陷，保证它们不会复活：

`_add_markdown_runs` 用了 `Pt` / `qn` 却没导入 → 只要走模板（`props` 非空）就
`NameError`。这条路径正是「检测/改写模式」保留原格式写回的主路径。
"""

from __future__ import annotations

import docx_io
import pytest


def test_add_markdown_runs_applies_size_without_nameerror():
    """回归（缺陷 1）：`Pt` 未导入 → NameError: name 'Pt' is not defined。

    该块紧跟在每次 `_add_markdown_runs(...)` 调用之后还有一次 `_apply_format(...)`，
    所以缺导入时不会静默降级，而是直接抛异常中断整篇生成。
    """
    docx = pytest.importorskip("docx", reason="需要 python-docx")
    doc = docx.Document()
    para = doc.add_paragraph()
    props = {"size_pt": 14, "eastAsia": "宋体", "ascii": "Times New Roman"}

    docx_io._add_markdown_runs(para, "正文**加粗**文字", props, {})

    assert para.runs[-1].font.size.pt == 14  # 不再 NameError
    run_fonts = para.runs[-1]._element.rPr.rFonts
    assert run_fonts.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia") == "宋体"


def test_add_markdown_runs_splits_bold_and_italic():
    """顺带钉住 run 切分：字号块不能把 ** 标记弄丢或漏进正文。"""
    docx = pytest.importorskip("docx", reason="需要 python-docx")
    doc = docx.Document()
    para = doc.add_paragraph()

    docx_io._add_markdown_runs(para, "前缀**加粗**后缀", {}, {})

    assert [r.text for r in para.runs] == ["前缀", "加粗", "后缀"]
    assert para.runs[1].font.bold is True
    assert "*" not in "".join(r.text for r in para.runs)


def test_formatted_write_without_template_does_not_crash(tmp_path):
    """无模板（props 为空）时不应进字号分支 —— 确认修复没有把这条路弄坏。"""
    docx = pytest.importorskip("docx", reason="需要 python-docx")
    out = tmp_path / "plain.docx"

    docx_io.formatted_write_docx(str(out), "# 标题\n\n正文。\n")

    assert [p.text for p in docx.Document(str(out)).paragraphs if p.text.strip()] \
        == ["标题", "正文。"]
