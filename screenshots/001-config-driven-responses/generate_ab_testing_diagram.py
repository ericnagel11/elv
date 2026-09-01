"""Render the A/B testing architecture diagram for the config-driven responses PoC.

Produces ab-testing-diagram.png next to this file. Reproducible: re-run to regenerate.

    python generate_ab_testing_diagram.py
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ab-testing-diagram.png")

AZ_BLUE = "#0078D4"
AZ_DARK = "#004E8C"
BAND_A = "#E9F3FB"
BAND_B = "#F3F3F2"
BAND_C = "#EAF6EC"
GREEN = "#0B6A0B"
ORANGE = "#D83B01"
RED = "#A4262C"
INK = "#201F1E"
MUTE = "#5C5A57"
WHITE = "#FFFFFF"

plt.rcParams["font.family"] = "DejaVu Sans"

fig, ax = plt.subplots(figsize=(16, 11), dpi=200)
ax.set_xlim(0, 16)
ax.set_ylim(0, 11)
ax.axis("off")


def band(x0, y0, x1, y1, color, label, label_y):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.12",
                 linewidth=0, facecolor=color, zorder=0))
    ax.text(x0 + 0.22, label_y, label, ha="left", va="center", fontsize=10.5,
            weight="bold", color=AZ_DARK, zorder=1)


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


def chip(x0, y0, x1, y1, text, edge=AZ_BLUE, fc=WHITE, tcolor=INK, size=9.6, weight="bold"):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                 boxstyle="round,pad=0.02,rounding_size=0.05",
                 linewidth=1.8, edgecolor=edge, facecolor=fc, zorder=3))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center",
            fontsize=size, color=tcolor, weight=weight, zorder=4)


def arrow(p0, p1, color=AZ_DARK, lw=2.3, dashed=False, rad=0.0):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=17,
                 lw=lw, color=color, zorder=4,
                 connectionstyle=f"arc3,rad={rad}",
                 linestyle=(0, (4, 3)) if dashed else "solid"))


# ---------------------------------------------------------------- title
ax.text(8, 10.62, "A/B Testing the Conversational Experience with Variant Feature Flags",
        ha="center", va="center", fontsize=17.5, weight="bold", color=AZ_DARK)
ax.text(8, 10.22, "The user is assigned a variant instead of an operator choosing one. Only the assignment step is new.",
        ha="center", va="center", fontsize=10.5, color=MUTE)

# ---------------------------------------------------------------- 1. assign
band(0.30, 7.45, 15.70, 9.78, BAND_A, "1. ASSIGN A VARIANT", 9.64)

box(0.45, 7.70, 2.75, 9.35, "Customer", ["sends a", "message"], line_size=8.2)
box(3.25, 7.70, 5.55, 9.35, "Targeting ID", ["stable per user,", "not per session"], line_size=8.2)
box(6.05, 7.70, 10.35, 9.35, "Variant feature flag",
    ["Azure App Configuration",
     "variants: baseline | candidate",
     "percentile allocation, plus overrides"], line_size=8.2)

chip(10.60, 8.60, 14.60, 9.35, "baseline   90% of users", edge=AZ_BLUE)
chip(10.60, 7.70, 14.60, 8.45, "candidate   10% of users", edge=ORANGE, tcolor=ORANGE)

arrow((2.75, 8.52), (3.25, 8.52))
arrow((5.55, 8.52), (6.05, 8.52))
arrow((10.35, 8.98), (10.60, 8.98))
arrow((10.35, 8.07), (10.60, 8.07))

# Both variants converge on the same downstream pipeline.
ax.add_patch(Circle((15.10, 8.05), 0.075, facecolor=AZ_DARK, edgecolor=AZ_DARK, zorder=5))
arrow((14.60, 8.98), (15.05, 8.15), lw=1.8)
arrow((14.60, 8.07), (15.02, 8.05), lw=1.8)

# ---------------------------------------------------------------- 2. render
band(0.30, 4.95, 15.70, 7.25, BAND_B, "2. RENDER AND RESPOND   (unchanged from the current build)", 7.11)

arrow((15.10, 7.97), (15.10, 6.90), lw=2.3)
ax.text(15.02, 7.44, "assigned label", ha="right", va="center", fontsize=8.2,
        color=AZ_DARK, weight="bold")

box(11.00, 5.35, 15.55, 6.85, "Load experience:* keys",
    ["for the assigned variant label"], line_size=8.4)
box(7.30, 5.35, 10.60, 6.85, "Render prompt template",
    ["tone, verbosity,", "reading level, structure"], line_size=8.4)
box(4.00, 5.35, 6.90, 6.85, "Azure OpenAI", ["generate the reply"], line_size=8.4)
box(0.45, 5.35, 3.60, 6.85, "Response", ["returned to the customer"],
    edge=GREEN, title_color=GREEN, line_size=8.4)

arrow((11.00, 6.10), (10.60, 6.10))
arrow((7.30, 6.10), (6.90, 6.10))
arrow((4.00, 6.10), (3.60, 6.10))

# ---------------------------------------------------------------- 3. measure
band(0.30, 0.58, 15.70, 4.62, BAND_C, "3. MEASURE AND DECIDE", 4.48)

box(0.45, 3.30, 6.50, 4.25, "Outcome event",
    ["same TargetingId: CSAT, containment, escalation"],
    edge=GREEN, title_color=GREEN, line_size=8.4)
box(0.45, 2.25, 6.50, 3.20, "FeatureEvaluation event",
    ["TargetingId, Variant, assignment reason"], line_size=8.4)
box(7.40, 2.25, 11.20, 4.25, "Application Insights",
    ["custom events from", "both sources"], line_size=8.4)
box(11.90, 2.25, 15.55, 4.25, "Analyze",
    ["join the two event", "types on TargetingId,", "compare per variant"], line_size=8.4)

# Curve clear of the band label on the left.
arrow((3.30, 5.35), (5.30, 4.25), color=GREEN, rad=-0.25)
arrow((6.50, 3.77), (7.40, 3.77), color=GREEN)
arrow((6.50, 2.72), (7.40, 2.72))
arrow((11.20, 3.25), (11.90, 3.25))
arrow((13.70, 2.25), (13.70, 2.00))

box(0.45, 0.70, 15.55, 1.95, "Decide",
    ["Winner: the release approver publishes the variant to production and it becomes the new baseline.",
     "Regression: set the flag to disabled and every user returns to the default variant, with no redeploy."],
    edge=ORANGE, title_color=ORANGE, fc="#FFF4EF", line_size=8.8, line_gap=0.30)

ax.text(8, 0.24, "The flag lives in App Configuration, so the same role model, approval gate, and audit trail "
        "apply to who may change an allocation.",
        ha="center", va="center", fontsize=8.8, color=MUTE, style="italic")

fig.savefig(OUT, dpi=200, bbox_inches="tight", facecolor="white")
print(f"wrote {OUT}")
