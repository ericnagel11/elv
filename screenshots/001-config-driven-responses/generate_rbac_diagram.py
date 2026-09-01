"""Render the RBAC governance diagram for the config-driven responses PoC.

Produces rbac-diagram.png next to this file. Reproducible: re-run to regenerate.

    python generate_rbac_diagram.py
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rbac-diagram.png")

AZ_BLUE = "#0078D4"
AZ_DARK = "#004E8C"
BAND = "#E9F3FB"
ALLOW = "#0B6A0B"
DENY = "#A4262C"
ORANGE = "#D83B01"
INK = "#201F1E"
MUTE = "#5C5A57"
WHITE = "#FFFFFF"

plt.rcParams["font.family"] = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(16, 11), dpi=200)
ax.set_xlim(0, 16)
ax.set_ylim(0, 11)
ax.axis("off")


def box(x0, y0, x1, y1, title, lines=None, edge=AZ_BLUE, fc=WHITE,
        title_color=None, title_size=11.0, line_size=8.4, line_gap=0.30):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.06",
                 linewidth=2.0, edgecolor=edge, facecolor=fc, zorder=2))
    cx = (x0 + x1) / 2
    parts = title.split("\n")
    ty = y1 - 0.32
    for i, part in enumerate(parts):
        ax.text(cx, ty - i * 0.34, part, ha="center", va="top",
                fontsize=title_size, weight="bold",
                color=title_color or edge, zorder=3)
    yy = ty - 0.34 * (len(parts) - 1) - 0.46
    for ln in (lines or []):
        ax.text(cx, yy, ln, ha="center", va="top", fontsize=line_size,
                color=INK, zorder=3)
        yy -= line_gap


def arrow(p0, p1, color=AZ_DARK, lw=2.4, dashed=False):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=18,
                 lw=lw, color=color, zorder=4,
                 linestyle=(0, (4, 3)) if dashed else "solid"))


def cell(x0, y0, x1, y1, text, fc, tcolor=WHITE, size=9.5, weight="bold"):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.01,rounding_size=0.04",
                 linewidth=1.2, edgecolor=WHITE, facecolor=fc, zorder=3))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
            fontsize=size, color=tcolor, weight=weight, zorder=4)


# ---------------------------------------------------------------- title
ax.text(8, 10.62, "Who May Change the Conversational Experience",
        ha="center", va="center", fontsize=18, weight="bold", color=AZ_DARK)
ax.text(8, 10.22, "Azure RBAC enforces the separation. Two App Configuration stores create the approval gate.",
        ha="center", va="center", fontsize=10.5, color=MUTE)

# ---------------------------------------------------------------- promotion path
ax.add_patch(FancyBboxPatch((0.30, 7.30), 15.40, 2.45,
             boxstyle="round,pad=0.02,rounding_size=0.12",
             linewidth=0, facecolor=BAND, zorder=0))
ax.text(0.52, 9.62, "PROMOTION PATH", ha="left", va="top", fontsize=10.5,
        weight="bold", color=AZ_DARK, zorder=1)

BOX_Y0, BOX_Y1 = 7.62, 9.32
W, GAP, X0 = 2.34, 0.85, 0.45
xs = [X0 + i * (W + GAP) for i in range(5)]

box(xs[0], BOX_Y0, xs[0] + W, BOX_Y1, "Experience\ndesigner",
    ["Data Owner: draft", "Data Reader: production"],
    edge=ALLOW, title_color=ALLOW, title_size=10.5, line_size=8.2)
box(xs[1], BOX_Y0, xs[1] + W, BOX_Y1, "Draft store",
    ["App Configuration", "the proposed experience"], edge=AZ_BLUE, line_size=8.2)
box(xs[2], BOX_Y0, xs[2] + W, BOX_Y1, "Release\napprover",
    ["Data Owner:", "both stores"],
    edge=ORANGE, title_color=ORANGE, title_size=10.5, line_size=8.2)
box(xs[3], BOX_Y0, xs[3] + W, BOX_Y1, "Production store",
    ["App Configuration", "the live experience"], edge=AZ_BLUE, line_size=8.2)
box(xs[4], BOX_Y0, xs[4] + W, BOX_Y1, "App runtime",
    ["Data Reader:", "production only"], edge=AZ_BLUE, line_size=8.2)

ARROW_Y = 8.47
labels = ["edits", "reviews", "publishes", "reads"]
colors = [ALLOW, AZ_DARK, ORANGE, MUTE]
for i in range(4):
    start = xs[i] + W
    end = xs[i + 1]
    arrow((start, ARROW_Y), (end, ARROW_Y), color=colors[i])
    ax.text((start + end) / 2, ARROW_Y + 0.30, labels[i], ha="center",
            va="center", fontsize=7.8, color=colors[i], weight="bold")

# The designer is blocked from writing straight to production.
ax.add_patch(FancyArrowPatch((2.00, BOX_Y0), (11.20, 6.98), arrowstyle="-|>",
             mutation_scale=16, lw=2.0, color=DENY, zorder=4,
             linestyle=(0, (4, 3)), connectionstyle="arc3,rad=0.10"))
ax.text(6.60, 6.70, "the designer cannot write to production: Azure returns 403",
        ha="center", va="center", fontsize=9.2, color=DENY, weight="bold")

# ---------------------------------------------------------------- matrix
IDENT_X0, IDENT_X1 = 0.50, 4.50
COLS = ["Read live\nexperience", "Read draft\nexperience", "Edit draft\nexperience",
        "Publish to\nproduction"]
COL_W = (15.50 - IDENT_X1) / len(COLS)
HEADER_Y0, HEADER_Y1 = 5.72, 6.22
ROW_H = 0.85

ax.text(0.50, 6.42, "WHAT EACH IDENTITY IS ACTUALLY ALLOWED TO DO",
        ha="left", va="center", fontsize=10.5, weight="bold", color=AZ_DARK)

ax.text((IDENT_X0 + IDENT_X1) / 2, (HEADER_Y0 + HEADER_Y1) / 2,
        "Identity and roles held", ha="center", va="center",
        fontsize=10, weight="bold", color=AZ_DARK)
for i, label in enumerate(COLS):
    x0 = IDENT_X1 + i * COL_W
    ax.text(x0 + COL_W / 2, (HEADER_Y0 + HEADER_Y1) / 2, label, ha="center",
            va="center", fontsize=9.5, weight="bold", color=AZ_DARK)

ROWS = [
    ("Viewer / Auditor", "Data Reader on both stores", [True, True, False, False]),
    ("Experience designer", "Data Owner on draft, Reader on production", [True, True, True, False]),
    ("Release approver", "Data Owner on both stores", [True, True, True, True]),
    ("Application runtime", "Data Reader on production only", [True, False, False, False]),
]

for r, (name, roles, allowed) in enumerate(ROWS):
    y1 = HEADER_Y0 - r * ROW_H
    y0 = y1 - ROW_H + 0.08
    ax.add_patch(FancyBboxPatch((IDENT_X0, y0), IDENT_X1 - IDENT_X0, y1 - y0,
                 boxstyle="round,pad=0.01,rounding_size=0.04",
                 linewidth=1.2, edgecolor=WHITE, facecolor="#F3F3F2", zorder=3))
    ax.text(IDENT_X0 + 0.18, (y0 + y1) / 2 + 0.13, name, ha="left", va="center",
            fontsize=9.8, weight="bold", color=INK, zorder=4)
    ax.text(IDENT_X0 + 0.18, (y0 + y1) / 2 - 0.17, roles, ha="left", va="center",
            fontsize=8.2, color=MUTE, zorder=4)
    for c, ok in enumerate(allowed):
        x0 = IDENT_X1 + c * COL_W
        cell(x0 + 0.06, y0, x0 + COL_W - 0.06, y1,
             "ALLOW" if ok else "DENY  403", ALLOW if ok else DENY)

# ---------------------------------------------------------------- audit + note
box(0.50, 0.55, 7.60, 2.15, "Audit trail",
    ["Both stores stream resource logs to Log Analytics.",
     "AACAudit records writes with CallerIdentity.",
     "AACHttpRequest shows denied attempts (403)."],
    edge=AZ_BLUE, title_size=11, line_size=8.4, line_gap=0.28)

box(8.20, 0.55, 15.50, 2.15, "Why two stores, not two labels",
    ["Azure does not support ABAC role-assignment conditions",
     "for App Configuration, so a role cannot target one label.",
     "Microsoft guidance: a separate store per environment."],
    edge=ORANGE, title_color=ORANGE, fc="#FFF4EF",
    title_size=11, line_size=8.4, line_gap=0.28)

ax.text(8, 0.22, "Role assignments are scoped to a single store, never to the subscription. "
        "Allow up to 15 minutes for a new assignment to propagate.",
        ha="center", va="center", fontsize=8.8, color=MUTE, style="italic")

fig.savefig(OUT, dpi=200, bbox_inches="tight", facecolor="white")
print(f"wrote {OUT}")
