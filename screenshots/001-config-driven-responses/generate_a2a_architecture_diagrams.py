"""Render portable before-and-after A2A architecture diagrams."""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))

AZ_BLUE = "#0078D4"
AZ_DARK = "#004E8C"
AZ_LIGHT = "#E9F3FB"
GREEN = "#107C10"
ORANGE = "#D83B01"
INK = "#201F1E"
MUTE = "#5C5A57"
WHITE = "#FFFFFF"

plt.rcParams["font.family"] = "DejaVu Sans"


def canvas(title, subtitle, height=6):
    fig, ax = plt.subplots(figsize=(16, height), dpi=200)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, height)
    ax.axis("off")
    ax.text(
        8,
        height - 0.38,
        title,
        ha="center",
        va="center",
        fontsize=20,
        weight="bold",
        color=AZ_DARK,
    )
    ax.text(
        8,
        height - 0.82,
        subtitle,
        ha="center",
        va="center",
        fontsize=11,
        color=MUTE,
    )
    return fig, ax


def box(ax, x, y, width, height, title, detail="", edge=AZ_BLUE, fill=WHITE):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.03,rounding_size=0.08",
            linewidth=2,
            edgecolor=edge,
            facecolor=fill,
            zorder=2,
        )
    )
    ax.text(
        x + width / 2,
        y + height * 0.62,
        title,
        ha="center",
        va="center",
        fontsize=12,
        weight="bold",
        color=edge,
        zorder=3,
    )
    if detail:
        ax.text(
            x + width / 2,
            y + height * 0.30,
            detail,
            ha="center",
            va="center",
            fontsize=9,
            color=INK,
            zorder=3,
        )


def arrow(ax, start, end, label="", color=AZ_DARK, dashed=False, curve=0.0):
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=18,
            linewidth=2.2,
            color=color,
            linestyle=(0, (4, 3)) if dashed else "solid",
            connectionstyle=f"arc3,rad={curve}",
            zorder=4,
        )
    )
    if label:
        ax.text(
            (start[0] + end[0]) / 2,
            (start[1] + end[1]) / 2 + 0.18,
            label,
            ha="center",
            va="center",
            fontsize=8.5,
            color=color,
            bbox={"facecolor": WHITE, "edgecolor": "none", "pad": 1.5},
            zorder=5,
        )


def save(fig, filename):
    path = os.path.join(HERE, filename)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=WHITE)
    plt.close(fig)
    print(f"wrote {path}")


def render_before():
    fig, ax = canvas(
        "Before A2A: Streamlit Owns the Whole Response Path",
        "The user interface also reads configuration, renders prompts, retrieves knowledge, and calls the model.",
    )

    box(ax, 0.55, 2.2, 2.1, 1.0, "Customer", "asks a question", edge=GREEN)
    box(
        ax,
        3.35,
        1.65,
        3.25,
        2.1,
        "Streamlit",
        "UI + response orchestration",
        edge=ORANGE,
        fill="#FFF4EF",
    )
    box(ax, 8.0, 3.55, 3.0, 0.9, "App Configuration", "experience and knowledge settings")
    box(ax, 12.0, 3.55, 3.0, 0.9, "Prompty assets", "versioned prompt templates")
    box(ax, 8.0, 1.25, 3.0, 0.9, "Azure AI Search", "approved knowledge")
    box(ax, 12.0, 1.25, 3.0, 0.9, "Azure OpenAI", "model inference")

    arrow(ax, (2.65, 2.85), (3.35, 2.85), "question", color=GREEN)
    arrow(ax, (3.35, 2.30), (2.65, 2.30), "answer", color=GREEN)
    arrow(ax, (6.60, 3.30), (8.0, 3.85), "read")
    arrow(ax, (6.60, 3.05), (12.0, 3.85), "load", curve=-0.08)
    arrow(ax, (6.60, 2.30), (8.0, 1.70), "search")
    arrow(ax, (6.60, 2.05), (12.0, 1.70), "generate", curve=0.08)

    ax.text(
        8,
        0.48,
        "A second application would need a custom API or a copy of this orchestration logic.",
        ha="center",
        va="center",
        fontsize=10,
        color=MUTE,
        style="italic",
    )
    save(fig, "a2a-before-architecture.png")


def render_after():
    fig, ax = canvas(
        "A2A: A Reusable Response Service",
        "Current PoC001 response path: one UI, one configured agent, separate Azure services.",
        height=8,
    )

    ax.add_patch(
        FancyBboxPatch(
            (2.75, 1.45),
            8.40,
            5.05,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.5,
            edgecolor=AZ_DARK,
            facecolor=AZ_LIGHT,
            zorder=0,
        )
    )
    ax.text(
        3.02,
        6.15,
        "TRUSTED WINDOWS VM / LOOPBACK",
        ha="left",
        va="center",
        fontsize=10,
        weight="bold",
        color=AZ_DARK,
    )
    ax.add_patch(
        FancyBboxPatch(
            (11.90, 1.45),
            3.65,
            5.05,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.5,
            edgecolor=AZ_BLUE,
            facecolor="#F5F9FC",
            zorder=0,
        )
    )
    ax.text(
        12.15, 6.15, "AZURE SERVICES",
        ha="left", va="center", fontsize=10, weight="bold", color=AZ_DARK,
    )

    box(ax, 0.30, 3.70, 1.85, 1.45, "Presenter", "VM browser", edge=GREEN)
    box(
        ax, 3.05, 3.40, 2.65, 1.90, "Streamlit", "A2A client\ncomparison UI",
        edge=ORANGE, fill="#FFF4EF",
    )
    box(
        ax, 7.25, 3.40, 3.60, 1.90, "Configured-response\nagent",
        "Resolve / retrieve / render\nvalidate output", edge=AZ_DARK,
    )
    box(ax, 7.25, 1.80, 3.60, 0.95, "Prompty assets", "deployed local templates")
    box(ax, 12.15, 4.90, 3.15, 1.05, "App Configuration", "production profiles")
    box(ax, 12.15, 3.45, 3.15, 1.05, "Azure AI Search", "read-only query")
    box(ax, 12.15, 1.95, 3.15, 1.05, "Azure OpenAI", "model inference")

    arrow(ax, (2.15, 4.75), (3.05, 4.75), "question", color=GREEN)
    arrow(ax, (3.05, 4.05), (2.15, 4.05), "answer", color=GREEN)
    arrow(ax, (5.70, 5.12), (7.25, 5.12), "Agent Card", color=MUTE, dashed=True)
    arrow(ax, (5.70, 4.55), (7.25, 4.55), "A2A Message", color=ORANGE)
    arrow(ax, (7.25, 3.90), (5.70, 3.90), "Task / Artifact", color=ORANGE)

    arrow(ax, (10.85, 4.95), (12.15, 5.42), "read")
    arrow(ax, (10.85, 4.35), (12.15, 3.98), "query")
    arrow(ax, (10.85, 3.70), (12.15, 2.48), "inference")
    arrow(ax, (9.05, 2.75), (9.05, 3.40))
    ax.text(
        9.30, 3.07, "local read", ha="left", va="center",
        fontsize=8.5, color=AZ_DARK,
    )
    ax.text(
        4.38, 2.23,
        "Response flow shown.\nConfig editing and history use\nseparate UI-to-Azure calls.",
        ha="center", va="center", fontsize=9, color=MUTE,
    )

    ax.text(
        8, 0.84,
        "Solid arrows: execution calls   |   Dashed: discovery   |   Azure calls: HTTPS + managed identity",
        ha="center", va="center", fontsize=9.5, color=INK,
    )
    ax.text(
        8, 0.35,
        "Local A2A uses loopback HTTP. A separate process is not an authenticated user boundary.",
        ha="center", va="center", fontsize=9.5, color=MUTE,
    )
    save(fig, "a2a-after-architecture.png")


if __name__ == "__main__":
    render_before()
    render_after()