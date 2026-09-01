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


def canvas(title, subtitle):
    fig, ax = plt.subplots(figsize=(16, 6), dpi=200)
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 6)
    ax.axis("off")
    ax.text(
        8,
        5.62,
        title,
        ha="center",
        va="center",
        fontsize=20,
        weight="bold",
        color=AZ_DARK,
    )
    ax.text(
        8,
        5.18,
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
        "With A2A: Streamlit Calls a Separate Response Agent",
        "A2A standardizes discovery, messages, tasks, contexts, and response artifacts.",
    )

    ax.add_patch(
        FancyBboxPatch(
            (6.95, 0.10),
            8.35,
            4.60,
            boxstyle="round,pad=0.04,rounding_size=0.12",
            linewidth=1.5,
            edgecolor=AZ_DARK,
            facecolor=AZ_LIGHT,
            zorder=0,
        )
    )
    ax.text(
        7.18,
        4.48,
        "PRIVATE AGENT BOUNDARY",
        ha="left",
        va="center",
        fontsize=10,
        weight="bold",
        color=AZ_DARK,
    )

    box(ax, 0.35, 2.2, 1.75, 1.0, "Customer", "asks a question", edge=GREEN)
    box(ax, 2.65, 1.8, 2.7, 1.8, "Streamlit", "A2A client and UI", edge=ORANGE, fill="#FFF4EF")
    box(ax, 7.35, 1.8, 3.05, 1.8, "Configured-response agent", "A2A task executor", edge=AZ_DARK)
    box(ax, 11.35, 3.45, 3.25, 0.8, "App Configuration", "production settings")
    box(ax, 11.35, 2.40, 3.25, 0.8, "Prompty assets", "private templates")
    box(ax, 11.35, 1.35, 3.25, 0.8, "Azure AI Search", "governed knowledge")
    box(ax, 11.35, 0.30, 3.25, 0.8, "Azure OpenAI", "model inference")

    arrow(ax, (2.10, 2.85), (2.65, 2.85), "question", color=GREEN)
    arrow(ax, (2.65, 2.30), (2.10, 2.30), "answer", color=GREEN)
    arrow(ax, (5.35, 3.00), (7.35, 3.00), "A2A Message + Task", color=ORANGE)
    arrow(ax, (7.35, 2.35), (5.35, 2.35), "A2A Artifact", color=ORANGE)
    arrow(ax, (5.35, 3.72), (7.35, 3.72), "discover Agent Card", color=MUTE, dashed=True)

    arrow(ax, (10.40, 3.30), (11.35, 3.75), "read")
    arrow(ax, (10.40, 2.95), (11.35, 2.80), "load")
    arrow(ax, (10.40, 2.45), (11.35, 1.75), "search")
    arrow(ax, (10.40, 2.05), (11.35, 0.70), "generate")

    ax.text(
        4.0,
        0.55,
        "Streamlit knows the capability contract,\nnot the prompt, filters, credentials, or Azure implementation.",
        ha="center",
        va="center",
        fontsize=9.5,
        color=MUTE,
        style="italic",
    )
    save(fig, "a2a-after-architecture.png")


if __name__ == "__main__":
    render_before()
    render_after()