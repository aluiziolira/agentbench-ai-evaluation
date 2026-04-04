#!/usr/bin/env python3
"""Extract files from git patch."""

import re
import os

patch_content = open("/tmp/commits.patch").read()

# Find all file diffs
file_pattern = r"diff --git a/([^\n]+) b/[^\n]+\n.*?--- /dev/null\n\+\+\+ b/([^\n]+)\n@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@(.*?)\n(?:(?=diff --git)|(?=\Z))"

# Split by diff --git
parts = patch_content.split("diff --git a/")[1:]  # Skip first empty part

for part in parts:
    lines = part.split("\n")
    # Get the file path from first line
    first_line = lines[0]
    if " b/" not in first_line:
        continue

    file_a = first_line.split(" b/")[0]
    file_b = first_line.split(" b/")[1].split("\n")[0]

    # Only extract agentbench and tests files, skip pyproject.toml and uv.lock
    if not (file_b.startswith("agentbench/") or file_b.startswith("tests/")):
        continue

    # Find the +++ line to get actual file path
    filepath = None
    content_lines = []
    in_content = False

    for i, line in enumerate(lines[1:], 1):
        if line.startswith("+++ b/"):
            filepath = line[6:].strip()
        elif line.startswith("@@"):
            in_content = True
        elif in_content:
            if line.startswith("+") and not line.startswith("+++"):
                content_lines.append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                pass  # Skip removed lines (new files don't have these)
            elif line.startswith("\\"):
                pass  # Skip "\ No newline at end of file"
            elif line.startswith("diff "):
                break
            elif line.strip() == "" and in_content:
                content_lines.append("")

    if filepath and content_lines:
        # Write file
        full_path = os.path.join(
            "/home/aluizio/aluizio-projects/agentbench-ai-evaluation", filepath
        )
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write("\n".join(content_lines))
        print(f"Created: {filepath}")

print("\nDone extracting files from patch!")
