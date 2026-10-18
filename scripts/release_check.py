"""Pre-release hygiene check for the Harbor-maester repository.

Scans source files for credential patterns and verifies required release
artifacts are present. Fails fast with a non-zero exit on any issue.
Filenames of suspicious files are reported; matched values are never printed.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Files/dirs to scan for accidental credential patterns
SCAN_DIRS = [
    ROOT / "src",
    ROOT / "harbor_simulation",
    ROOT / "simulator",
    ROOT / "scripts",
    ROOT / "config",
]
SCAN_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".env", ".toml"}

# Patterns that suggest a literal secret was left in code
CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)gsk_[a-z0-9]{50,}"),
    re.compile(r"(?i)sk-[a-zA-Z0-9]{40,}"),
    re.compile(r"(?i)GROQ_API_KEY\s*=\s*['\"][^'\"]+['\"]"),
    re.compile(r"(?i)hf_[a-zA-Z0-9]{30,}"),
]

# Required files for a complete release
REQUIRED_FILES = [
    ROOT / "README.md",
    ROOT / "app.py",
    ROOT / "requirements-space-lock.txt",
    ROOT / "pyproject.toml",
    ROOT / "data" / "procedures.json",
    ROOT / "config" / "demo_policy.yaml",
    ROOT / "src" / "harbor_engine" / "models" / "motion_forest.json",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "MODEL_CARD.md",
    ROOT / "docs" / "SECURITY.md",
    ROOT / "docs" / "DEPLOYMENT.md",
    ROOT / "scripts" / "prepare_space.py",
]


def check_credentials():
    issues = []
    for directory in SCAN_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if any(part in path.parts for part in ("tests", "__pycache__")):
                continue
            if path.stem.endswith(".example"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern in CREDENTIAL_PATTERNS:
                if pattern.search(text):
                    issues.append(f"  Possible credential pattern in: {path.relative_to(ROOT)}")
                    break
    return issues


def check_required_files():
    missing = []
    for path in REQUIRED_FILES:
        if not path.exists():
            missing.append(f"  Missing required release file: {path.relative_to(ROOT)}")
    return missing


def main():
    all_issues = []

    print("Harbor-maester release check")
    print("=" * 40)

    print("\n[1/2] Scanning for credential patterns...")
    cred_issues = check_credentials()
    if cred_issues:
        all_issues.extend(cred_issues)
        for issue in cred_issues:
            print(issue)
    else:
        print("  OK - no credential patterns found in scanned sources.")

    print("\n[2/2] Checking required release artifacts...")
    missing = check_required_files()
    if missing:
        all_issues.extend(missing)
        for issue in missing:
            print(issue)
    else:
        print("  OK - all required release files are present.")

    print("\n" + "=" * 40)
    if all_issues:
        print(f"FAILED - {len(all_issues)} issue(s) found. Resolve before pushing to main.")
        sys.exit(1)
    else:
        print("PASSED - release hygiene checks complete.")


if __name__ == "__main__":
    main()
