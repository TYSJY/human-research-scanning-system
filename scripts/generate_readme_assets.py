from __future__ import annotations

import csv
import math
import textwrap
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOC_ASSETS = ROOT / "docs" / "assets"
GH_ASSETS = ROOT / ".github" / "assets"
DOC_ASSETS.mkdir(parents=True, exist_ok=True)
GH_ASSETS.mkdir(parents=True, exist_ok=True)

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

BG = "#07101E"
PANEL = "#0F1B2E"
PANEL_2 = "#13233A"
CARD = "#152847"
BORDER = "#263A5E"
TEXT = "#F8FAFC"
MUTED = "#9FB0CC"
ACCENT = "#4FD1C5"
ACCENT_2 = "#60A5FA"
ACCENT_3 = "#F59E0B"
SUCCESS = "#22C55E"
RED = "#F97316"
SOFT_WHITE = "#E5EDF7"


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_MONO if mono else FONT_BOLD if bold else FONT_REGULAR
    return ImageFont.truetype(path, size=size)


def rounded(draw: ImageDraw.ImageDraw, box, fill, outline=None, radius=24, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def shadowed_panel(img: Image.Image, box, *, fill=PANEL, outline=BORDER, radius=26, shadow=(0, 12, 24, 0)):
    draw = ImageDraw.Draw(img)
    x1, y1, x2, y2 = box
    sx, sy = 0, 8
    draw.rounded_rectangle((x1 + sx, y1 + sy, x2 + sx, y2 + sy), radius=radius, fill="#030814")
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def wrap_for_width(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        if draw.textlength(trial, font=fnt) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_wrapped(draw: ImageDraw.ImageDraw, text: str, xy, *, fnt, fill=TEXT, max_width=1000, line_gap=8):
    x, y = xy
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend(wrap_for_width(draw, paragraph, fnt, max_width))
    ascent, descent = fnt.getmetrics()
    step = ascent + descent + line_gap
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += step
    return y


def gradient_background(size, top="#08101E", bottom="#0E203B"):
    width, height = size
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    def hex_to_rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    t = hex_to_rgb(top)
    b = hex_to_rgb(bottom)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        rgb = tuple(int(t[i] + (b[i] - t[i]) * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=rgb)
    return img


def accent_orbs(img: Image.Image):
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    for cx, cy, r, color in [
        (w * 0.78, h * 0.18, 220, (96, 165, 250, 42)),
        (w * 0.18, h * 0.85, 260, (79, 209, 197, 30)),
        (w * 0.92, h * 0.78, 180, (245, 158, 11, 24)),
    ]:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)


def load_showcase_data() -> tuple[list[str], list[list[str]], list[str]]:
    brief = (ROOT / "projects" / "sample_joint_tri_runtime_v4_2" / "reports" / "research_brief.md").read_text(encoding="utf-8").splitlines()
    csv_path = ROOT / "projects" / "sample_joint_tri_runtime_v4_2" / "reports" / "evidence_matrix.csv"
    with csv_path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    deliverable_lines = (ROOT / "projects" / "sample_joint_tri_runtime_v4_2" / "reports" / "deliverable_index.md").read_text(encoding="utf-8").splitlines()
    return brief[:18], rows[:4], [line for line in deliverable_lines if line.startswith("- ")][:6]


def generate_hero_banner():
    img = gradient_background((1600, 900), top="#08111D", bottom="#112544")
    accent_orbs(img)
    draw = ImageDraw.Draw(img)

    draw.text((90, 80), "Research OS", font=font(30, bold=True), fill=ACCENT)
    draw.text((90, 122), "Professional AI Research Assistant", font=font(64, bold=True), fill=TEXT)
    subtitle = (
        "Turn research questions into evidence-backed reviews, study plans, writing packages, "
        "and reproducible deliverables."
    )
    draw_wrapped(draw, subtitle, (90, 210), fnt=font(28), fill=SOFT_WHITE, max_width=880, line_gap=10)

    pill_y = 305
    pills = ["Evidence-first", "Deliverable-oriented", "Traceable", "Reusable workspace"]
    px = 90
    for label in pills:
        tw = int(draw.textlength(label, font=font(20, bold=True))) + 44
        rounded(draw, (px, pill_y, px + tw, pill_y + 46), fill="#0E1C31", outline="#2A3D62", radius=23)
        draw.text((px + 22, pill_y + 11), label, font=font(20, bold=True), fill=TEXT)
        px += tw + 14

    cards = [
        ("Literature Review", "Search strategy · evidence registry · gap analysis", ACCENT),
        ("Study Design", "Claim graph · acceptance checks · experiment plan", ACCENT_2),
        ("Scholarly Writing", "Abstract · outline · reviewer response", ACCENT_3),
        ("Research Ops", "Run registry · audit report · showcase package", SUCCESS),
    ]
    card_x, card_y = 90, 410
    card_w, card_h, gap = 320, 176, 22
    for idx, (title, body, color) in enumerate(cards):
        x1 = card_x + idx % 2 * (card_w + gap)
        y1 = card_y + idx // 2 * (card_h + gap)
        x2, y2 = x1 + card_w, y1 + card_h
        shadowed_panel(img, (x1, y1, x2, y2), fill=CARD)
        draw.ellipse((x1 + 24, y1 + 22, x1 + 62, y1 + 60), fill=color)
        draw.text((x1 + 80, y1 + 20), title, font=font(28, bold=True), fill=TEXT)
        draw_wrapped(draw, body, (x1 + 24, y1 + 84), fnt=font(20), fill=MUTED, max_width=card_w - 48, line_gap=6)

    # right visual panel
    panel = (990, 110, 1510, 760)
    shadowed_panel(img, panel, fill="#0C1729")
    x1, y1, x2, y2 = panel
    # fake app chrome
    draw.rounded_rectangle((x1 + 24, y1 + 24, x2 - 24, y1 + 82), radius=18, fill="#111F36", outline="#2A3D62", width=2)
    for i, c in enumerate(["#FB7185", "#F59E0B", "#34D399"]):
        draw.ellipse((x1 + 44 + i * 26, y1 + 43, x1 + 60 + i * 26, y1 + 59), fill=c)
    draw.text((x1 + 100, y1 + 39), "showcase / sample project", font=font(22, bold=True), fill=TEXT)

    # three columns
    inner_x = x1 + 28
    top = y1 + 106
    left_w = 138
    center_w = 225
    right_w = 88
    total_inner = x2 - x1 - 56
    right_w = total_inner - left_w - center_w - 28
    sections = [
        (inner_x, top, inner_x + left_w, y2 - 28),
        (inner_x + left_w + 14, top, inner_x + left_w + 14 + center_w, y2 - 28),
        (inner_x + left_w + center_w + 28, top, x2 - 28, y2 - 28),
    ]
    for sec in sections:
        rounded(draw, sec, fill="#101D31", outline="#253757", radius=20)
    sx1, sy1, sx2, sy2 = sections[0]
    draw.text((sx1 + 16, sy1 + 16), "Workspace", font=font(21, bold=True), fill=TEXT)
    tree_lines = [
        "sample project",
        "├─ notes/scan.md",
        "├─ notes/outline.md",
        "├─ reports/research_brief.md",
        "├─ reports/evidence_matrix.csv",
        "├─ state/evidence_registry.json",
        "└─ runs/20260327_joint-budget-mvp",
    ]
    y = sy1 + 56
    for line in tree_lines:
        draw.text((sx1 + 16, y), line, font=font(18, mono=True), fill=SOFT_WHITE)
        y += 32

    cx1, cy1, cx2, cy2 = sections[1]
    draw.text((cx1 + 16, cy1 + 16), "Research brief", font=font(21, bold=True), fill=TEXT)
    brief_excerpt = [
        "Project: official demo workspace",
        "Question: does unified budgeting beat",
        "          pipeline-combo baseline?",
        "Evidence: E1, E2, E3",
        "Claim C1: reduce peak VRAM and latency",
        "Checks: VRAM <= -10%, latency <= -8%",
        "Results: pass / pass / pass",
        "Next: no open tasks",
    ]
    y = cy1 + 58
    for line in brief_excerpt:
        draw.text((cx1 + 16, y), line, font=font(18, mono=True), fill=SOFT_WHITE)
        y += 30

    rx1, ry1, rx2, ry2 = sections[2]
    draw.text((rx1 + 16, ry1 + 16), "Evidence", font=font(21, bold=True), fill=TEXT)
    headers = ["ID", "Kind", "Note"]
    cols = [56, 104, rx2 - rx1 - 32 - 56 - 104]
    hx = rx1 + 16
    hy = ry1 + 56
    rounded(draw, (hx, hy, rx2 - 16, hy + 36), fill="#12253E", outline="#2B3D62", radius=10)
    draw.text((hx + 10, hy + 8), headers[0], font=font(16, bold=True), fill=TEXT)
    draw.text((hx + cols[0] + 10, hy + 8), headers[1], font=font(16, bold=True), fill=TEXT)
    draw.text((hx + cols[0] + cols[1] + 10, hy + 8), headers[2], font=font(16, bold=True), fill=TEXT)
    sample_rows = [
        ("E1", "paper", "Prior work misses joint budgets"),
        ("E2", "analysis", "Pipeline combo mismatches budgets"),
        ("E3", "system", "Resource fronts drift on edge"),
    ]
    row_y = hy + 48
    for rid, kind, note in sample_rows:
        rounded(draw, (hx, row_y, rx2 - 16, row_y + 38), fill="#101E31", outline="#223557", radius=10)
        draw.text((hx + 10, row_y + 9), rid, font=font(15, mono=True), fill=TEXT)
        draw.text((hx + cols[0] + 10, row_y + 9), kind, font=font(15, mono=True), fill=MUTED)
        draw.text((hx + cols[0] + cols[1] + 10, row_y + 9), note, font=font(15), fill=SOFT_WHITE)
        row_y += 50

    draw.text((rx1 + 16, row_y + 12), "Deliverables", font=font(21, bold=True), fill=TEXT)
    checks = [("research_brief.md", SUCCESS), ("evidence_matrix.csv", SUCCESS), ("deliverable_index.md", SUCCESS)]
    cy = row_y + 52
    for label, color in checks:
        draw.ellipse((rx1 + 20, cy + 5, rx1 + 34, cy + 19), fill=color)
        draw.text((rx1 + 44, cy), label, font=font(16, mono=True), fill=SOFT_WHITE)
        cy += 32

    img.save(DOC_ASSETS / "hero-banner.png", format="PNG")


def generate_showcase_view():
    img = gradient_background((1600, 980), top="#08111D", bottom="#10233F")
    accent_orbs(img)
    draw = ImageDraw.Draw(img)
    draw.text((90, 64), "Visual tour · workspace, reports, and deliverables", font=font(46, bold=True), fill=TEXT)
    draw.text((90, 122), "A README screenshot that makes the project feel like a product, not just a codebase.", font=font(24), fill=MUTED)

    shadowed_panel(img, (72, 180, 1528, 902), fill="#0B1627")
    x1, y1, x2, y2 = 72, 180, 1528, 902
    # chrome
    rounded(draw, (96, 208, 1504, 270), fill="#111E34", outline="#28405F", radius=18)
    for i, c in enumerate(["#F87171", "#FBBF24", "#34D399"]):
        draw.ellipse((124 + i * 28, 232, 142 + i * 28, 250), fill=c)
    draw.text((220, 226), "Research OS · Official demo workspace", font=font(24, bold=True), fill=TEXT)
    draw.text((1230, 226), "stage: audit", font=font(20, bold=True), fill=ACCENT)

    left = (96, 292, 368, 874)
    center = (388, 292, 1008, 874)
    right_top = (1028, 292, 1504, 576)
    right_bottom = (1028, 594, 1504, 874)
    for box, fill in [(left, PANEL_2), (center, PANEL), (right_top, PANEL_2), (right_bottom, PANEL_2)]:
        rounded(draw, box, fill=fill, outline=BORDER, radius=22)

    lx1, ly1, lx2, ly2 = left
    draw.text((lx1 + 20, ly1 + 18), "Workspace tree", font=font(24, bold=True), fill=TEXT)
    tree_lines = [
        "sample_joint_tri_runtime_v4_2/",
        "├─ notes/",
        "│  ├─ scan.md",
        "│  ├─ experiment_plan.md",
        "│  └─ results_synthesis.md",
        "├─ reports/",
        "│  ├─ research_brief.md",
        "│  ├─ evidence_matrix.csv",
        "│  └─ deliverable_index.md",
        "├─ runs/20260327_joint-budget-mvp/",
        "├─ state/evidence_registry.json",
        "└─ state/run_registry.json",
    ]
    y = ly1 + 62
    for line in tree_lines:
        draw.text((lx1 + 18, y), line, font=font(18, mono=True), fill=SOFT_WHITE)
        y += 34
    rounded(draw, (lx1 + 18, ly2 - 78, lx2 - 18, ly2 - 22), fill="#12253F", outline="#29415F", radius=16)
    draw.text((lx1 + 34, ly2 - 62), "showcase package ready", font=font(19, bold=True), fill=SUCCESS)
    draw.text((lx1 + 34, ly2 - 36), "brief · evidence matrix · deliverable index", font=font(16), fill=MUTED)

    cx1, cy1, cx2, cy2 = center
    draw.text((cx1 + 24, cy1 + 18), "research_brief.md", font=font(24, bold=True), fill=TEXT)
    y = cy1 + 64
    brief_preview = [
        "# Research Brief",
        "",
        "- Topic: evidence-traceable AI",
        "  research workflows",
        "- Objective: reduce unsupported",
        "  claims in scholarly drafting",
        "",
        "## Main findings",
        "- Structured evidence mapping",
        "  improves reviewability",
        "- Acceptance checks make",
        "  design trade-offs explicit",
        "- Result provenance lowers",
        "  audit ambiguity",
        "",
        "## Next actions",
        "- Add evidence trace view in UI",
    ]
    for line in brief_preview:
        draw.text((cx1 + 24, y), line, font=font(17, mono=True), fill=SOFT_WHITE)
        y += 28

    rx1, ry1, rx2, ry2 = right_top
    draw.text((rx1 + 20, ry1 + 18), "evidence_matrix.csv", font=font(24, bold=True), fill=TEXT)
    headers = ["id", "kind", "summary"]
    row_y = ry1 + 64
    col_x = [rx1 + 20, rx1 + 92, rx1 + 210]
    for i, header in enumerate(headers):
        draw.text((col_x[i], row_y), header, font=font(15, bold=True), fill=ACCENT)
    row_y += 32
    preview_rows = [
        ("E1", "paper", "Joint budgeting missing"),
        ("E2", "analysis", "Pipeline mismatch risk"),
        ("E3", "system", "Resource fronts drift"),
    ]
    for rid, kind, summary in preview_rows:
        rounded(draw, (rx1 + 16, row_y - 6, rx2 - 16, row_y + 26), fill="#101E31", outline="#243757", radius=10)
        draw.text((col_x[0], row_y), rid, font=font(14, mono=True), fill=SOFT_WHITE)
        draw.text((col_x[1], row_y), kind, font=font(14, mono=True), fill=SOFT_WHITE)
        draw.text((col_x[2], row_y), summary, font=font(14, mono=True), fill=SOFT_WHITE)
        row_y += 42

    bx1, by1, bx2, by2 = right_bottom
    draw.text((bx1 + 20, by1 + 18), "deliverable_index.md", font=font(24, bold=True), fill=TEXT)
    y = by1 + 64
    items = [
        "configs · ready",
        "scripts · ready",
        "tables · ready",
        "notes/admin_weekly_status.md",
        "notes/claim_evidence_map.md",
        "run: joint-budget-mvp · succeeded",
    ]
    for idx, line in enumerate(items):
        color = SUCCESS if "ready" in line or "succeeded" in line else ACCENT_2
        draw.ellipse((bx1 + 22, y + 6, bx1 + 34, y + 18), fill=color)
        draw.text((bx1 + 46, y), line, font=font(16, mono=True), fill=SOFT_WHITE)
        y += 34

    img.save(DOC_ASSETS / "showcase-view.png", format="PNG")


def generate_research_flow():
    img = gradient_background((1600, 760), top="#08111D", bottom="#0F2240")
    accent_orbs(img)
    draw = ImageDraw.Draw(img)
    draw.text((86, 62), "Research workflow", font=font(48, bold=True), fill=TEXT)
    draw.text((86, 120), "From a research question to an auditable showcase package.", font=font(24), fill=MUTED)

    steps = [
        ("Question", "Define scope, claim direction, target venue"),
        ("Evidence", "Register papers, observations, baselines, risks"),
        ("Design", "Shape MVP, acceptance checks, experiment plan"),
        ("Execute", "Track runs, metrics, result provenance"),
        ("Write", "Produce brief, outline, rebuttal-ready notes"),
        ("Audit", "Export deliverables for review and handoff"),
    ]
    start_x, y = 70, 230
    step_w, step_h, gap = 206, 210, 20
    for i, (title, body) in enumerate(steps):
        x1 = start_x + i * (step_w + gap)
        x2 = x1 + step_w
        shadowed_panel(img, (x1, y, x2, y + step_h), fill=CARD)
        draw.ellipse((x1 + 18, y + 18, x1 + 56, y + 56), fill=[ACCENT, ACCENT_2, ACCENT_3, SUCCESS, "#A78BFA", "#FB7185"][i])
        draw.text((x1 + 72, y + 16), title, font=font(28, bold=True), fill=TEXT)
        draw_wrapped(draw, body, (x1 + 18, y + 82), fnt=font(18), fill=MUTED, max_width=step_w - 36, line_gap=6)
        if i < len(steps) - 1:
            ax1 = x2 + 6
            ay = y + 102
            draw.line((ax1, ay, ax1 + gap - 18, ay), fill=ACCENT_2, width=7)
            draw.polygon([(ax1 + gap - 18, ay - 10), (ax1 + gap, ay), (ax1 + gap - 18, ay + 10)], fill=ACCENT_2)

    footer = "Evidence-first flow keeps claims, runs, results, and writing outputs connected instead of scattered across chat logs."
    draw_wrapped(draw, footer, (86, 530), fnt=font(24), fill=SOFT_WHITE, max_width=1420, line_gap=10)
    img.save(DOC_ASSETS / "research-flow.png", format="PNG")


def generate_evidence_traceability():
    img = gradient_background((1600, 900), top="#08111D", bottom="#10233F")
    accent_orbs(img)
    draw = ImageDraw.Draw(img)
    draw.text((90, 62), "Evidence traceability", font=font(48, bold=True), fill=TEXT)
    draw.text((90, 122), "Show how a conclusion is supported, checked, and turned into a deliverable.", font=font(24), fill=MUTED)

    claim_box = (100, 220, 470, 440)
    shadowed_panel(img, claim_box, fill="#112342")
    draw.text((126, 246), "Claim C1", font=font(32, bold=True), fill=TEXT)
    claim_text = "Unified budgeting reduces peak VRAM and end-to-end latency more reliably than pipeline-combo baselines."
    draw_wrapped(draw, claim_text, (126, 302), fnt=font(20), fill=SOFT_WHITE, max_width=310, line_gap=8)
    rounded(draw, (126, 390, 286, 426), fill="#0F1D34", outline="#2D4063", radius=16)
    draw.text((144, 398), "status: draft", font=font(17, bold=True), fill=ACCENT)

    ev_boxes = [
        (590, 180, 970, 330, "Evidence E1", "Prior work does not jointly model all three budgets.", ACCENT),
        (590, 376, 970, 526, "Evidence E2", "Pipeline-style combinations often create budget mismatch.", ACCENT_2),
        (590, 572, 970, 722, "Evidence E3", "Edge inference bottlenecks come from unsynchronized resource fronts.", ACCENT_3),
    ]
    for x1, y1, x2, y2, title, body, color in ev_boxes:
        shadowed_panel(img, (x1, y1, x2, y2), fill="#0F1E34")
        draw.ellipse((x1 + 18, y1 + 18, x1 + 54, y1 + 54), fill=color)
        draw.text((x1 + 72, y1 + 16), title, font=font(27, bold=True), fill=TEXT)
        draw_wrapped(draw, body, (x1 + 22, y1 + 74), fnt=font(18), fill=MUTED, max_width=330, line_gap=6)

    result_box = (1100, 260, 1480, 470)
    shadowed_panel(img, result_box, fill="#112342")
    draw.text((1126, 286), "Acceptance checks", font=font(30, bold=True), fill=TEXT)
    checks = [
        ("VRAM <= -10%", "pass", SUCCESS),
        ("Latency <= -8%", "pass", SUCCESS),
        ("Accuracy >= -1.0", "pass", SUCCESS),
    ]
    y = 340
    for label, status, color in checks:
        rounded(draw, (1126, y, 1454, y + 44), fill="#0E1C31", outline="#2A3D61", radius=16)
        draw.text((1144, y + 11), label, font=font(17, mono=True), fill=SOFT_WHITE)
        sw = int(draw.textlength(status, font=font(17, bold=True)))
        draw.text((1454 - 18 - sw, y + 11), status, font=font(17, bold=True), fill=color)
        y += 58

    deliverable_box = (1090, 560, 1480, 790)
    shadowed_panel(img, deliverable_box, fill="#0F1E34")
    draw.text((1116, 586), "Deliverables", font=font(30, bold=True), fill=TEXT)
    deliverables = [
        "research_brief.md",
        "evidence_matrix.csv",
        "deliverable_index.md",
        "runtime_audit_report.md",
    ]
    y = 646
    for item in deliverables:
        draw.ellipse((1118, y + 7, 1132, y + 21), fill=SUCCESS)
        draw.text((1144, y), item, font=font(18, mono=True), fill=SOFT_WHITE)
        y += 36

    # connectors
    def arrow(p1, p2, color=ACCENT_2):
        draw.line((p1, p2), fill=color, width=6)
        angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        size = 14
        left = (p2[0] - size * math.cos(angle) + 8 * math.sin(angle), p2[1] - size * math.sin(angle) - 8 * math.cos(angle))
        right = (p2[0] - size * math.cos(angle) - 8 * math.sin(angle), p2[1] - size * math.sin(angle) + 8 * math.cos(angle))
        draw.polygon([p2, left, right], fill=color)
    claim_center = (470, 330)
    arrow(claim_center, (590, 250))
    arrow(claim_center, (590, 450))
    arrow(claim_center, (590, 648))
    arrow((970, 256), (1100, 340), color=ACCENT)
    arrow((970, 450), (1100, 398), color=ACCENT_2)
    arrow((970, 648), (1090, 672), color=ACCENT_3)
    arrow((1290, 470), (1290, 560), color=SUCCESS)

    img.save(DOC_ASSETS / "evidence-traceability.png", format="PNG")


def generate_github_growth_panel():
    img = gradient_background((1600, 920), top="#08111D", bottom="#10233F")
    accent_orbs(img)
    draw = ImageDraw.Draw(img)
    draw.text((90, 62), "GitHub launch panel", font=font(48, bold=True), fill=TEXT)
    draw.text((90, 122), "Keep local visuals for product storytelling, but prefer live badges and star history in the public README.", font=font(24), fill=MUTED)

    # badge row
    badges = [
        ("Stars", "TYSJY/human-research-scanning-system", ACCENT),
        ("Release", "latest tag badge", ACCENT_2),
        ("Python", "3.11+", ACCENT_3),
        ("License", "MIT", SUCCESS),
    ]
    bx = 90
    by = 184
    for title, value, color in badges:
        w = 320 if title != "Release" else 300
        rounded(draw, (bx, by, bx + w, by + 62), fill="#11213A", outline="#29405F", radius=20)
        draw.rectangle((bx + 18, by + 15, bx + 36, by + 47), fill=color)
        draw.text((bx + 52, by + 12), title, font=font(22, bold=True), fill=TEXT)
        draw.text((bx + 52, by + 36), value, font=font(16), fill=MUTED)
        bx += w + 18

    chart_box = (90, 286, 1016, 826)
    shadowed_panel(img, chart_box, fill="#0F1E34")
    cx1, cy1, cx2, cy2 = chart_box
    draw.text((cx1 + 24, cy1 + 18), "GitHub repository signals", font=font(30, bold=True), fill=TEXT)
    draw.text((cx1 + 24, cy1 + 58), "Use this image as a static explainer, but wire the public README to the live Star History SVG.", font=font(18), fill=MUTED)
    plot = (cx1 + 46, cy1 + 118, cx2 - 28, cy2 - 76)
    px1, py1, px2, py2 = plot
    draw.rectangle(plot, outline="#2B3D61", width=2)
    # grid
    for i in range(1, 5):
        y = py1 + i * (py2 - py1) / 5
        draw.line((px1, y, px2, y), fill="#1E3254", width=1)
    for i in range(1, 7):
        x = px1 + i * (px2 - px1) / 7
        draw.line((x, py1, x, py2), fill="#1E3254", width=1)
    draw.text((px1 + 10, py1 + 10), "Static explainer image", font=font(18, bold=True), fill=RED)
    points = [
        (px1 + 40, py2 - 40),
        (px1 + 160, py2 - 52),
        (px1 + 280, py2 - 70),
        (px1 + 400, py2 - 98),
        (px1 + 520, py2 - 130),
        (px1 + 640, py2 - 158),
        (px1 + 760, py2 - 184),
    ]
    draw.line(points, fill=ACCENT, width=7)
    for x, y in points:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=ACCENT)
    labels = ["Launch", "Week 1", "Week 2", "Month 1", "Month 2", "Month 3", "Month 6"]
    for i, label in enumerate(labels):
        x = px1 + i * (px2 - px1) / (len(labels) - 1)
        draw.text((x - 24, py2 + 14), label, font=font(15), fill=MUTED)

    side = (1050, 286, 1510, 826)
    shadowed_panel(img, side, fill="#0F1E34")
    sx1, sy1, sx2, sy2 = side
    draw.text((sx1 + 24, sy1 + 18), "README launch kit", font=font(30, bold=True), fill=TEXT)
    steps = [
        "1. Keep local screenshots in docs/assets/",
        "2. Set .github/assets/social-preview.png as the repository social preview.",
        "3. Point badges at TYSJY/human-research-scanning-system (or your forked slug).",
        "4. Keep the live Star History SVG in the public README.",
        "5. Keep screenshots relative so GitHub renders them reliably.",
    ]
    y = sy1 + 74
    for step in steps:
        y = draw_wrapped(draw, step, (sx1 + 24, y), fnt=font(18), fill=SOFT_WHITE, max_width=392, line_gap=6) + 12
    rounded(draw, (sx1 + 24, sy2 - 230, sx2 - 24, sy2 - 26), fill="#11213A", outline="#29405F", radius=20)
    draw.text((sx1 + 46, sy2 - 206), "Suggested live snippet", font=font(18, bold=True), fill=ACCENT)
    snippet_lines = [
        "[![GitHub stars](https://img.shields.io/",
        "github/stars/TYSJY/human-research-scanning-system?style=",
        "for-the-badge&logo=github)](...) ",
        "[![Star History Chart](https://api.star-history.com/",
        "svg?repos=TYSJY/human-research-scanning-system&type=Date)](...) ",
    ]
    yy = sy2 - 170
    for line in snippet_lines:
        draw.text((sx1 + 44, yy), line, font=font(15, mono=True), fill=SOFT_WHITE)
        yy += 26

    img.save(DOC_ASSETS / "github-growth-panel.png", format="PNG")


def generate_social_preview():
    img = gradient_background((1280, 640), top="#08111D", bottom="#10233F")
    accent_orbs(img)
    draw = ImageDraw.Draw(img)
    draw.text((76, 62), "Research OS", font=font(32, bold=True), fill=ACCENT)
    draw.text((76, 110), "Professional AI", font=font(56, bold=True), fill=TEXT)
    draw.text((76, 172), "Research Assistant", font=font(56, bold=True), fill=TEXT)
    subtitle = "Literature review · Study design · Scholarly writing · Reproducible research ops"
    draw_wrapped(draw, subtitle, (76, 248), fnt=font(24), fill=SOFT_WHITE, max_width=760, line_gap=8)

    cards = [
        ("Evidence first", ACCENT),
        ("Traceable outputs", ACCENT_2),
        ("Showcase-ready", SUCCESS),
    ]
    x = 76
    y = 338
    for label, color in cards:
        w = int(draw.textlength(label, font=font(20, bold=True))) + 42
        rounded(draw, (x, y, x + w, y + 44), fill="#102036", outline="#29405F", radius=22)
        draw.text((x + 20, y + 10), label, font=font(20, bold=True), fill=color)
        x += w + 16

    shadowed_panel(img, (770, 90, 1210, 536), fill="#0B1627")
    draw.text((804, 120), "Deliverables", font=font(28, bold=True), fill=TEXT)
    items = [
        "research_brief.md",
        "evidence_matrix.csv",
        "deliverable_index.md",
        "runtime_audit_report.md",
    ]
    yy = 184
    for item in items:
        draw.ellipse((804, yy + 8, 818, yy + 22), fill=SUCCESS)
        draw.text((832, yy), item, font=font(20, mono=True), fill=SOFT_WHITE)
        yy += 52

    footer = "Workspace-backed research assistant for teams that need evidence, structure, and reproducibility."
    draw_wrapped(draw, footer, (76, 520), fnt=font(22), fill=MUTED, max_width=620, line_gap=8)
    img.save(GH_ASSETS / "social-preview.png", format="PNG")


def main():
    generate_hero_banner()
    generate_showcase_view()
    generate_research_flow()
    generate_evidence_traceability()
    generate_github_growth_panel()
    generate_social_preview()
    print("Generated README media assets in docs/assets and .github/assets")


if __name__ == "__main__":
    main()
