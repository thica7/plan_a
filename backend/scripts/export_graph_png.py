from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "graph.png"

NODES = [
    ("planner", "Planner"),
    ("planner_hitl", "Plan HITL"),
    ("collector_dispatch", "Collector Dispatch\nSend competitor x dim"),
    ("collector", "Collectors\nparallel"),
    ("collect_join", "Collect Join"),
    ("collect_qa", "Collect QA"),
    ("analyst_dispatch", "Analyst Dispatch\nSend competitor x slice"),
    ("analyst", "Analysts\nparallel"),
    ("analyst_join", "Analyst Join"),
    ("analyst_qa", "Analyst QA"),
    ("comparator", "Comparator"),
    ("reflector", "Reflector"),
    ("writer", "Writer"),
    ("qa", "QA"),
    ("qa_hitl", "QA HITL\nredo routes"),
]


def main() -> None:
    width = 1280
    height = 1840
    image = Image.new("RGB", (width, height), "#f7f8fb")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
        small = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
        small = ImageFont.load_default()

    x = 360
    y = 40
    box_w = 560
    box_h = 76
    gap = 42
    centers: dict[str, tuple[int, int]] = {}

    for node_id, label in NODES:
        fill = "#ffffff"
        outline = "#b7c2d6"
        if "hitl" in node_id:
            fill = "#fff6df"
            outline = "#deb95e"
        if "qa" in node_id and "hitl" not in node_id:
            fill = "#ecf7ff"
            outline = "#74a8d8"
        if "dispatch" in node_id:
            fill = "#eef5ff"
        if node_id in {"collector", "analyst"}:
            fill = "#effaf3"
            outline = "#72b489"

        draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=10, fill=fill, outline=outline, width=3)
        lines = label.splitlines()
        for index, line in enumerate(lines):
            draw.text((x + 24, y + 18 + index * 24), line, fill="#202733", font=font if index == 0 else small)
        centers[node_id] = (x + box_w // 2, y + box_h // 2)
        y += box_h + gap

    for first, second in zip(NODES, NODES[1:]):
        _, y1 = centers[first[0]]
        _, y2 = centers[second[0]]
        x_mid = x + box_w // 2
        draw.line((x_mid, y1 + box_h // 2, x_mid, y2 - box_h // 2), fill="#65758d", width=3)
        draw.polygon(
            [(x_mid - 8, y2 - box_h // 2 - 10), (x_mid + 8, y2 - box_h // 2 - 10), (x_mid, y2 - box_h // 2 + 6)],
            fill="#65758d",
        )

    draw.text((40, 28), "Competiscope Plan A LangGraph DAG", fill="#202733", font=font)
    draw.text((40, 64), "Collector and analyst branches fan out through LangGraph Send; QA can route redo upstream.", fill="#526071", font=small)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT)


if __name__ == "__main__":
    main()
