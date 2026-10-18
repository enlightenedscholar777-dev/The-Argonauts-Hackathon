"""Create an allowlisted Hugging Face upload folder, never copy the workspace wholesale."""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ("README.md", "app.py", "pyproject.toml", "requirements-space.txt",
         "data/procedures.json")
TREES = {
    "src": {".py", ".json", ".html", ".css", ".js"},
    "config": {".yaml"},
    "harbor_simulation": {".py", ".csv"},
    "simulator": {".py"},
    "scripts": {".py"},
}


def sources():
    paths = [ROOT / name for name in FILES]
    for folder, suffixes in TREES.items():
        paths.extend(path for path in (ROOT / folder).rglob("*") if path.is_file()
                     and path.suffix in suffixes and not {"__pycache__", "tests"} & set(path.parts)
                     and path.name != "synthetic_ground_truth.csv")
    return sorted(set(paths))


def prepare(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new output directory; existing files are never overwritten or uploaded implicitly.")
    paths = sources()
    destination.mkdir(parents=True)
    for path in paths:
        target = destination / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(
        ROOT / "requirements-space.txt",
        destination / "requirements.txt",
    )
    return len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(f"Prepared {prepare(args.output)} public deployment files in {args.output}")


if __name__ == "__main__":
    main()
