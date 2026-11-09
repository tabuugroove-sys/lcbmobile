"""Re-edit saved narration/footage without publishing or generating paid voice."""
import argparse
import json
import os
import shutil
from pathlib import Path

from src.video.horizontal_news import render, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stories", type=int, default=3)
    parser.add_argument("--infographics", type=Path, help="Reviewed fact proposals keyed by story id")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve() or args.output.exists():
        raise SystemExit("Use a new output folder; existing editions are not overwritten")
    package = json.loads((args.input/"package.json").read_text(encoding="utf-8"))
    stories = package["stories"][:args.stories]
    if args.infographics:
        facts = json.loads(args.infographics.read_text(encoding="utf-8"))
        if not isinstance(facts, dict) or set(facts)-{s["id"] for s in stories}:
            raise SystemExit("Infographic facts must be keyed by selected story ids")
        for story in stories:
            story["infographics"] = facts.get(story["id"], [])
    args.output.mkdir(parents=True)
    for story in stories:
        if "item" not in story:
            story["item"] = {"source_id": "saved_preview", "source_name": story.get("source", ""),
                             "title": story["headline"], "url": story["url"], "category": "musica"}
        for prefix, suffix in (("voice", "mp3"), ("alignment", "json")):
            shutil.copy2(args.input/f"{prefix}-{story['id']}.{suffix}", args.output/f"{prefix}-{story['id']}.{suffix}")
    os.environ["LONGFORM_PLANNER"] = "beats"
    edition = package.get("edition") or package["date"]
    save(args.output/"package.json", {"edition": edition, "purpose": "historical edit preview, not today's news",
                                     "publish": False, "stories": stories})
    result = render(stories, edition, args.output)
    save(args.output/"package.json", {"edition": edition, "publish": False, "stories": stories})
    print(str(result), flush=True)


if __name__ == "__main__":
    main()
