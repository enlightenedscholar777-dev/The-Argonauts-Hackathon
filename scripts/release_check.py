"""Pre-release hygiene check for the Harbor-maester repository.

Scans source files for credential patterns, verifies required release
artifacts are present, and confirms the .dockerignore allowlist contains
no plain credential files. Fails fast with a non-zero exit on any issue.
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
    re.compile(r"(?i)gsk_[a-z0-9]{50,}"),           # Groq API key prefix
    re.compile(r"(?i)sk-[a-zA-Z0-9]{40,}"),          # OpenAI-style key
    re.compile(r"(?i)GROQ_API_KEY\s*=\s*['\"][^'\"]+['\"]"),  # Inline assignment with value
    re.compile(r"(?i)hf_[a-zA-Z0-9]{30,}"),          # HuggingFace token
]

# Required files for a complete release
REQUIRED_FILES = [
    ROOT / "README.md",
    ROOT / "Dockerfile",
    ROOT / ".dockerignore",
    ROOT / "requirements-space-lock.txt",
    ROOT / "pyproject.toml",
    ROOT / "data" / "procedures.json",
    ROOT / "config" / "demo_policy.yaml",
    ROOT / "src" / "harbor_engine" / "models" / "motion_forest.json",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "MODEL_CARD.md",
    ROOT / "docs" / "SECURITY.md",
    ROOT / "docs" / "DEPLOYMENT.md",
    ROOT / "scripts" / "launch_space.py",
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
            # Skip test fixtures and example files
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
                    break  # One report per file
    return issues


def check_required_files():
    missing = []
    for path in REQUIRED_FILES:
        if not path.exists():
            missing.append(f"  Missing required release file: {path.relative_to(ROOT)}")
    return missing


def check_dockerignore():
    """The .dockerignore is an allowlist (**deny all, then !allow).
    Verify that .env files are not accidentally allowed."""
    issues = []
    di_path = ROOT / ".dockerignore"
    if not di_path.exists():
        return ["  .dockerignore not found"]
    lines = [l.strip() for l in di_path.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        if line.startswith("!") and ".env" in line and "example" not in line.lower():
            issues.append(f"  .dockerignore appears to allow a .env file: {line!r}")
    return issues


def main():
    all_issues = []

    print("Harbor-maester release check")
    print("=" * 40)

    print("\n[1/3] Scanning for credential patterns...")
    cred_issues = check_credentials()
    if cred_issues:
        all_issues.extend(cred_issues)
        for issue in cred_issues:
            print(issue)
    else:
        print("  OK — no credential patterns found in scanned sources.")

    print("\n[2/3] Checking required release artifacts...")
    missing = check_required_files()
    if missing:
        all_issues.extend(missing)
        for issue in missing:
            print(issue)
    else:
        print("  OK — all required release files are present.")

    print("\n[3/3] Checking .dockerignore allowlist...")
    di_issues = check_dockerignore()
    if di_issues:
        all_issues.extend(di_issues)
        for issue in di_issues:
            print(issue)
    else:
        print("  OK — .dockerignore does not expose .env files.")

    print("\n" + "=" * 40)
    if all_issues:
        print(f"FAILED — {len(all_issues)} issue(s) found. Resolve before pushing to main.")
        sys.exit(1)
    else:
        print("PASSED — release hygiene checks complete.")


if __name__ == "__main__":
    main()
