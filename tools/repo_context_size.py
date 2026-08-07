from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_EXTENSIONS = {
    ".py",
    ".html",
    ".css",
    ".js",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
}

IGNORE_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".zip",
    ".gz",
    ".gpg",
    ".pdf",
}

result = subprocess.run(
    ["git", "ls-files"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=True,
)

tracked_files = [
    ROOT / line
    for line in result.stdout.splitlines()
    if line.strip()
]

files = []

for path in tracked_files:
    if not path.is_file():
        continue

    if path.suffix.lower() in IGNORE_SUFFIXES:
        continue

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        continue

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except OSError:
        continue

    chars = len(text)

    # Conservative source-code estimate.
    estimated_tokens = chars // 3

    files.append(
        (
            estimated_tokens,
            chars,
            str(path.relative_to(ROOT)),
        )
    )

files.sort(reverse=True)

total_tokens = sum(item[0] for item in files)
total_chars = sum(item[1] for item in files)

print()
print("MARK-OS TRACKED AI CONTEXT AUDIT")
print("=" * 70)
print(f"Tracked text/code files: {len(files):,}")
print(f"Characters:              {total_chars:,}")
print(f"Estimated tokens:        {total_tokens:,}")
print()

if total_tokens < 400_000:
    print("STATUS: EXCELLENT")
elif total_tokens < 600_000:
    print("STATUS: GOOD")
elif total_tokens < 800_000:
    print("STATUS: ACCEPTABLE — use selective context")
elif total_tokens < 1_000_000:
    print("STATUS: WARNING — approaching 1M")
else:
    print("STATUS: TOO LARGE")

print()
print("Largest tracked context files")
print("-" * 70)

for tokens, chars, filename in files[:30]:
    print(
        f"{tokens:>10,} tokens  "
        f"{chars:>12,} chars  "
        f"{filename}"
    )