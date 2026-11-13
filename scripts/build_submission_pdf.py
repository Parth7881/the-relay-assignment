"""Render the final two-page Relay assignment write-up from its reviewed Markdown."""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "submission-writeup.md"
OUTPUT = ROOT / "output" / "pdf" / "the-relay-assignment-writeup.pdf"

INK = colors.HexColor("#142033")
MUTED = colors.HexColor("#526174")
BLUE = colors.HexColor("#2563A6")
BLUE_DARK = colors.HexColor("#173B63")
BLUE_PALE = colors.HexColor("#EAF2FA")
LINE = colors.HexColor("#B8C7D8")


def inline(value: str) -> str:
    escaped = html.escape(value.strip())
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    escaped = escaped.replace("**", "")
    return escaped


def table_widths(title: str, width: float, columns: int) -> list[float]:
    ratios = {
        "Table 1": [0.15, 0.24, 0.49, 0.12],
        "Table 2a": [0.15, 0.09, 0.05, 0.09, 0.10, 0.26, 0.26],
        "Table 2b": [0.17, 0.09, 0.09, 0.12, 0.12, 0.09, 0.15, 0.17],
        "Table 3": [0.22, 0.11, 0.09, 0.08, 0.12, 0.10, 0.12, 0.16],
    }.get(title)
    if ratios and len(ratios) == columns:
        return [width * ratio for ratio in ratios]
    return [width / columns] * columns


def footer(canvas, document) -> None:
    canvas.saveState()
    page_width, _ = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.35)
    canvas.line(12 * mm, 9.2 * mm, page_width - 12 * mm, 9.2 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 5.8)
    canvas.drawString(12 * mm, 6.3 * mm, "THE RELAY | Evidence-first RAG under provider limits")
    canvas.drawRightString(page_width - 12 * mm, 6.3 * mm, f"Page {document.page}")
    canvas.restoreState()


def parse_table(lines: list[str], title: str, width: float, cell_style) -> Table:
    rows = []
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index == 1 and all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append([Paragraph(inline(cell), cell_style) for cell in cells])
    table = Table(
        rows,
        colWidths=table_widths(title, width, len(rows[0])),
        repeatRows=1,
        hAlign="LEFT",
    )
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE_DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7),
    ]
    for row in range(1, len(rows)):
        commands.append(("BACKGROUND", (0, row), (-1, row), BLUE_PALE if row % 2 else colors.white))
    table.setStyle(TableStyle(commands))
    return table


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    page_width, _ = A4
    left = right = 12 * mm
    usable_width = page_width - left - right
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCompact",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=16,
        textColor=INK,
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    deck_style = ParagraphStyle(
        "Deck",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=8.4,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=5,
    )
    heading_style = ParagraphStyle(
        "HeadingCompact",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=9.4,
        leading=10.7,
        textColor=BLUE,
        spaceBefore=3.0,
        spaceAfter=1.2,
        keepWithNext=True,
    )
    subheading_style = ParagraphStyle(
        "TableTitle",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=8.8,
        textColor=INK,
        spaceBefore=2.4,
        spaceAfter=1.2,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "BodyCompact",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.0,
        leading=9.6,
        textColor=INK,
        spaceAfter=1.8,
        allowWidows=0,
        allowOrphans=0,
    )
    list_style = ParagraphStyle(
        "ListCompact",
        parent=body_style,
        leftIndent=7,
        firstLineIndent=-7,
        spaceAfter=1.2,
    )
    cell_style = ParagraphStyle(
        "CellCompact",
        parent=body_style,
        fontSize=6.1,
        leading=7.0,
        spaceAfter=0,
    )

    source_lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story = []
    index = 0
    current_table_title = ""
    while index < len(source_lines):
        line = source_lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), title_style))
            story.append(
                Paragraph(
                    "Python + Groq | fixed three-paper library | 12 real calibration calls | "
                    "46 formal stand-in load requests | 42 human-graded answers",
                    deck_style,
                )
            )
            index += 1
            continue
        if line.startswith("## "):
            if line.startswith("## 6."):
                story.append(PageBreak())
            story.append(Paragraph(inline(line[3:]), heading_style))
            index += 1
            continue
        if line.startswith("### "):
            current_table_title = line[4:].rstrip(".")
            story.append(Paragraph(inline(line[4:]), subheading_style))
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(source_lines) and source_lines[index].strip().startswith("|"):
                table_lines.append(source_lines[index].strip())
                index += 1
            story.append(parse_table(table_lines, current_table_title, usable_width, cell_style))
            story.append(Spacer(1, 1.8))
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(source_lines):
            candidate = source_lines[index].strip()
            if not candidate or candidate.startswith(("#", "|")):
                break
            if re.match(r"^\d+\.\s", candidate) and re.match(r"^\d+\.\s", paragraph_lines[0]):
                break
            paragraph_lines.append(candidate)
            index += 1
        text = " ".join(paragraph_lines)
        style = list_style if re.match(r"^\d+\.\s", text) else body_style
        story.append(Paragraph(inline(text), style))

    story.append(Spacer(1, 2))
    story.append(
        Paragraph(
            "Evidence: runs/formal-submission/results.csv and retained raw traces. "
            "Provider facts: console.groq.com/docs/rate-limits and /errors. "
            "Vaani review: vaani.dev, inspected 13 Nov 2026.",
            ParagraphStyle(
                "Sources", parent=body_style, fontSize=6.4, leading=7.5, textColor=MUTED
            ),
        )
    )

    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=left,
        rightMargin=right,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title="The Relay - Assignment Write-up",
        author="Dhruv",
        subject="Research-paper assistant evaluated under provider limits and load",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return OUTPUT


if __name__ == "__main__":
    print(build())
