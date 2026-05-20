"""
check_venv_refs.py
Run this from H:\hayeong\ to find every file that references venv or .venv
Usage: python check_venv_refs.py
"""

import os

ROOT = r"H:\hayeong"
EXTENSIONS = {".py", ".bat", ".ps1", ".json", ".txt", ".md", ".cfg", ".ini", ".toml", ".yaml", ".yml"}
SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", "chromadb", ".git"}

results_venv = []      # files referencing plain 'venv'
results_dotvenv = []   # files referencing '.venv'
results_both = []      # files referencing both

for dirpath, dirnames, filenames in os.walk(ROOT):
    # Skip irrelevant directories
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

    for filename in filenames:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in EXTENSIONS:
            continue

        filepath = os.path.join(dirpath, filename)
        relative = os.path.relpath(filepath, ROOT)

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            continue

        found_venv = []
        found_dotvenv = []

        for i, line in enumerate(lines, 1):
            has_dotvenv = ".venv" in line
            has_venv = "venv" in line and not has_dotvenv

            if has_dotvenv:
                found_dotvenv.append((i, line.strip()))
            if has_venv:
                found_venv.append((i, line.strip()))

        if found_venv and found_dotvenv:
            results_both.append((relative, found_venv, found_dotvenv))
        elif found_venv:
            results_venv.append((relative, found_venv))
        elif found_dotvenv:
            results_dotvenv.append((relative, found_dotvenv))

# ── REPORT ──────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("  VENV REFERENCE SCAN — H:\\hayeong")
print("="*60)

if results_dotvenv:
    print(f"\n✅ FILES REFERENCING .venv (correct):")
    for rel, hits in results_dotvenv:
        print(f"\n  {rel}")
        for lineno, text in hits:
            print(f"    line {lineno}: {text}")

if results_venv:
    print(f"\n⚠️  FILES REFERENCING venv (old — check these):")
    for rel, hits in results_venv:
        print(f"\n  {rel}")
        for lineno, text in hits:
            print(f"    line {lineno}: {text}")

if results_both:
    print(f"\n❗ FILES REFERENCING BOTH (mixed — review carefully):")
    for rel, old_hits, new_hits in results_both:
        print(f"\n  {rel}")
        print(f"    venv references:")
        for lineno, text in old_hits:
            print(f"      line {lineno}: {text}")
        print(f"    .venv references:")
        for lineno, text in new_hits:
            print(f"      line {lineno}: {text}")

if not results_venv and not results_dotvenv and not results_both:
    print("\n  No venv references found in any file.")

print("\n" + "="*60)
print(f"  SUMMARY")
print("="*60)
print(f"  .venv references (correct): {len(results_dotvenv)} file(s)")
print(f"  venv references (old):      {len(results_venv)} file(s)")
print(f"  Mixed (both):               {len(results_both)} file(s)")
print("="*60 + "\n")
