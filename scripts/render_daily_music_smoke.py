"""Offline renderer regression using the already reviewed October 3 preview. Never publishes."""
import json
import shutil
from pathlib import Path

from src.config import ROOT
from src.video.horizontal_news import render, save


def main() -> None:
    fixture = ROOT / "out/horizontal_2026-10-03"
    output = ROOT / "out/daily-render-regression"
    output.mkdir(parents=True, exist_ok=True)
    package = json.loads((fixture / "package.json").read_text(encoding="utf-8"))
    selections = {row["id"]: row["assets"] for row in json.loads((fixture / "media_selection.json").read_text(encoding="utf-8"))}
    for story in package["stories"]:
        for prefix, suffix in (("voice", "mp3"), ("alignment", "json")):
            shutil.copy2(fixture / f"{prefix}-{story['id']}.{suffix}", output / f"{prefix}-{story['id']}.{suffix}")
        story["assets"] = selections[story["id"]]
        for asset in story["assets"]:
            asset.setdefault("reviewed_ranges", [[asset.get("reviewed_start", 0), asset["duration"] - .15]])
    save(output / "package.json", package)
    print(render(package["stories"], package["date"], output))


if __name__ == "__main__":
    main()
