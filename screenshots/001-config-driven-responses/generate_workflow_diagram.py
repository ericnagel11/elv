"""Render the configuration-driven conversational experience workflow diagram.

Produces workflow-diagram.png next to this file. Reproducible: re-run to regenerate.

    python generate_workflow_diagram.py
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflow-diagram.png")

AZ_BLUE = "#0078D4"
AZ_DARK = "#004E8C"
BAND_CFG = "#E9F3FB"
BAND_RUN = "#F3F3F2"
GREEN = "#0B6A0B"
ORANGE = "#D83B01"
INK = "#201F1E"
MUTE = "#5C5A57"
WHITE = "#FFFFFF"

plt.rcParams["font.family"] = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(16, 9), dpi=200)
ax.set_xlim(0, 16)
ax.set_ylim(0, 9)
ax.axis("off")


def band(x0, y0, x1, y1, color, label):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.12",
                 linewidth=0, facecolor=color, zorder=0))
    ax.text(x0 + 0.22, (y0 + y1) / 2 if False else y1 - 0.16, label, ha="left", va="top",
            fontsize=11, weight="bold", color=AZ_DARK, zorder=1)


def box(x0, y0, x1, y1, title, lines=None, edge=AZ_BLUE, title_color=None,
        lw=1.8, fc=WHITE, title_size=11.5, line_size=9.3):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.06",
                 linewidth=lw, edgecolor=edge, facecolor=fc, zorder=2))
    cx = (x0 + x1) / 2
    ty = y1 - 0.26
    ax.text(cx, ty, title, ha="center", va="top", fontsize=title_size,
            weight="bold", color=title_color or AZ_DARK, zorder=3)
    if lines:
        yy = ty - 0.40
        for ln in lines:
            ax.text(cx, yy, ln, ha="center", va="top", fontsize=line_size, color=INK, zorder=3)
            yy -= 0.32
    return (cx, (y0 + y1) / 2)


def chip(x0, y0, x1, y1, text, edge=AZ_BLUE, fc=WHITE, tcolor=INK, size=9.2, weight="normal"):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.05",
                 linewidth=1.5, edgecolor=edge, facecolor=fc, zorder=3))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
            fontsize=size, color=tcolor, weight=weight, zorder=4)


def arrow(p0, p1, color=AZ_DARK, lw=2.2, dashed=False, rad=0.0):
    style = (0, (4, 3)) if dashed else "solid"
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=18, lw=lw,
                 color=color, linestyle=style, connectionstyle=f"arc3,rad={rad}", zorder=4))


def note(x, y, text, color=MUTE, size=8.6, ha="center", weight="normal"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=size, color=color, weight=weight, zorder=5)


def stepbox(x0, y0, x1, y1, num, title, lines=None, color=AZ_BLUE, title_color=None, fc=WHITE, line_size=9.2):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.06",
                 linewidth=2.0, edgecolor=color, facecolor=fc, zorder=2))
    bx, by = x0 + 0.46, y1 - 0.44
    ax.add_patch(Circle((bx, by), 0.30, facecolor=color, edgecolor=WHITE, linewidth=1.6, zorder=5))
    ax.text(bx, by, str(num), ha="center", va="center", color=WHITE, weight="bold",
            fontsize=13.5, zorder=6)
    cx = (x0 + x1) / 2
    ax.text(cx + 0.30, by, title, ha="center", va="center", fontsize=12,
            weight="bold", color=title_color or color, zorder=3)
    if lines:
        yy = by - 0.54
        for ln in lines:
            ax.text(cx, yy, ln, ha="center", va="top", fontsize=line_size, color=INK, zorder=3)
            yy -= 0.32
    return (cx, (y0 + y1) / 2)


# Title
ax.text(8, 8.74, "Configuration-Driven Conversational Experience: Step by Step, Input to Output",
        ha="center", va="center", fontsize=17.5, weight="bold", color=AZ_DARK)
ax.text(8, 8.36, "AI-WP-001 / AI-WP-002   -   tone, verbosity, reading level, structure and persona are configuration, changed without a release",
        ha="center", va="center", fontsize=10.0, color=MUTE)

# Configuration control plane (sources)
band(0.3, 6.1, 15.7, 8.14, BAND_CFG, "CONFIGURATION CONTROL PLANE   -   authored once, changed anytime (no release)")
box(0.7, 6.6, 3.4, 7.5, "Experience designer", ["/ CX team, edits messaging"],
    edge=GREEN, title_color=GREEN, title_size=11, line_size=9.0)
box(4.0, 6.15, 9.4, 7.66, "Azure App Configuration",
    ["experience:tone, verbosity, reading_level,",
     "response_structure, persona, prompt_asset",
     "labels:  baseline  |  candidate"], edge=AZ_BLUE, title_size=11.5, line_size=9.2)
box(10.1, 6.6, 13.9, 7.6, "Prompt assets (versioned)",
    ["response.v1 / v2 .prompty (Prompty format)"], edge=AZ_BLUE, title_size=11, line_size=9.2)
arrow((3.4, 7.05), (4.0, 7.05), color=GREEN)
note(3.7, 7.22, "edit", color=GREEN, size=8.5)
arrow((9.4, 7.0), (10.1, 7.0), color=AZ_DARK)
note(9.75, 7.17, "prompt_asset", color=MUTE, size=7.6)
note(9.75, 6.84, "selects", color=MUTE, size=7.6)

# ----- Numbered runtime workflow (snake: 1-2-3 across, down, 4-5-6 back) -----
COL1 = (0.6, 5.1)
COL2 = (5.65, 10.15)
COL3 = (10.6, 15.55)
TOP = (3.75, 5.3)
BOT = (1.2, 2.75)
cx1 = (COL1[0] + COL1[1]) / 2
cx2 = (COL2[0] + COL2[1]) / 2
cx3 = (COL3[0] + COL3[1]) / 2
rowA = (TOP[0] + TOP[1]) / 2
rowB = (BOT[0] + BOT[1]) / 2

stepbox(COL1[0], TOP[0], COL1[1], TOP[1], 1, "Customer message",
        ["A customer asks a question", '"Where is my order?..."'])
stepbox(COL2[0], TOP[0], COL2[1], TOP[1], 2, "Read experience profile",
        ["Read experience:* keys (tone, verbosity,", "reading level, ...) from App Configuration"])
stepbox(COL3[0], TOP[0], COL3[1], TOP[1], 3, "Load prompt asset",
        ["Load the versioned .prompty asset", "chosen by prompt_asset (v1 or v2)"])
arrow((COL1[1], rowA), (COL2[0], rowA), lw=2.6)
arrow((COL2[1], rowA), (COL3[0], rowA), lw=2.6)

arrow((cx3, TOP[0]), (cx3, BOT[1]), lw=2.6)

stepbox(COL3[0], BOT[0], COL3[1], BOT[1], 4, "Render prompt template",
        ["Inject config into  {{tone}}, {{verbosity}},",
         "{{reading_level}}, {{response_structure}}, {{persona}}"],
        color=ORANGE, title_color=ORANGE, fc="#FFF4EF", line_size=8.6)
stepbox(COL2[0], BOT[0], COL2[1], BOT[1], 5, "Call Azure OpenAI",
        ["Send the rendered prompt to the", "gpt-5-mini deployment; get the reply"])
stepbox(COL1[0], BOT[0], COL1[1], BOT[1], 6, "Configured response",
        ["Reply returned to the customer,", "reflecting the current configuration"],
        color=GREEN, title_color=GREEN)
arrow((COL3[0], rowB), (COL2[1], rowB), lw=2.6)
arrow((COL2[0], rowB), (COL1[1], rowB), lw=2.6)

note(cx3, 0.98, "Tone is applied here", color=ORANGE, size=9.5, weight="bold")

chip(COL1[0], 0.5, COL1[1], 1.02, "Preference / telemetry  ->  A/B evidence (feedback.csv or App Insights)",
     edge=MUTE, fc="#FBFBFA", tcolor=MUTE, size=8.6)
arrow((cx1, BOT[0]), (cx1, 1.02), color=MUTE, lw=1.8)

# Dashed "read at runtime" from control plane into steps 2 and 3
arrow((6.7, 6.15), (cx2, TOP[1]), color=AZ_DARK, dashed=True, rad=0.05)
arrow((12.0, 6.6), (cx3, TOP[1]), color=AZ_DARK, dashed=True, rad=0.05)
note(6.0, 5.7, "reads at runtime", color=AZ_DARK, size=8.2)
note(11.3, 5.7, "loads at runtime", color=AZ_DARK, size=8.2)

# Footer
ax.text(8, 0.18, "All service-to-service calls use Microsoft Entra ID managed identity (no keys).   "
        "Change a value in the Azure portal or CLI, click Refresh, and compare  -  no build or deploy.",
        ha="center", va="center", fontsize=9, color=MUTE, style="italic")

fig.savefig(OUT, dpi=200, bbox_inches="tight", facecolor="white")
print(f"wrote {OUT}")
