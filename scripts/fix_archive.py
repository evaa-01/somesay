"""Fix the broken archive in WORKLOG.md: remove ALL mangled lines after the Archive heading, append git content properly."""
import subprocess, pathlib

root = pathlib.Path(__file__).resolve().parent.parent
worklog = root / "WORKLOG.md"

# 1. Read current file, split into lines
full_text = worklog.read_text(encoding="utf-8")
lines = full_text.splitlines()

# Find the archive heading line index
archive_idx = None
for i, line in enumerate(lines):
    if line.startswith("## Archive:"):
        archive_idx = i
        break

if archive_idx is None:
    print("ERROR: Could not find ## Archive: heading")
    exit(1)

# Find where the NEXT section heading starts after the archive heading.
# Section headings are lines starting with "## " (not inside code blocks).
cut_idx = len(lines)  # default to end of file
in_code_block = False
for i in range(archive_idx + 1, len(lines)):
    stripped = lines[i].strip()
    if stripped.startswith("```"):
        in_code_block = not in_code_block
        continue
    if not in_code_block and stripped.startswith("## ") and not stripped.startswith("## Archive"):
        cut_idx = i
        break

# Keep everything up to and including the archive heading, then everything from cut_idx onward
keep_before = lines[:archive_idx + 1]       # includes the "## Archive:" line itself
keep_after = lines[cut_idx:]                  # next section headings onwards
print(f"Kept {len(keep_before)} lines before/heading + {len(keep_after)} lines after cut point")
print(f"Removed {(len(lines) - len(keep_before) - len(keep_after))} mangled/duplicate lines")

# 2. Get old NOTES.md content via git show and append line by line
result = subprocess.run(
    ["git", "show", "1e8222b^:NOTES.md"],
    capture_output=True, text=True, encoding="utf-8"
)
if result.returncode != 0:
    print(f"ERROR: git show failed: {result.stderr[:500]}")
else:
    old_notes = result.stdout
    with open(worklog, "w", encoding="utf-8") as f:
        for l in keep_before:
            f.write(l + "\n")
        for l in old_notes.splitlines():
            f.write(l + "\n")
        for l in keep_after:
            f.write(l + "\n")
    print(f"Appended {old_notes.count(chr(10))} lines from git show 1e8222b^:NOTES.md")

# 3. Delete temp file (if still exists)
temp = root / "_notes_archive_temp.md"
if temp.exists():
    temp.unlink()
    print("Deleted _notes_archive_temp.md")

# 4. Show longest line and diff --stat
all_text = worklog.read_text(encoding="utf-8")
longest = max(len(l) for l in all_text.splitlines()) if all_text.strip() else 0
print(f"Longest line in WORKLOG.md: {longest} chars")

# Also show total lines
total = len(all_text.splitlines())
print(f"Total lines in WORKLOG.md: {total}")

subprocess.run(["git", "diff", "--stat"], check=False)
