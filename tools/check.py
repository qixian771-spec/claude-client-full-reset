#!/usr/bin/env python3
"""Validate packaging and syntax without executing any operational scripts."""
import ast
import json
from pathlib import Path
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    text = (ROOT / "SKILL.md").read_text()
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
    require(match is not None, "Missing skill YAML frontmatter")
    meta = yaml.safe_load(match.group(1))
    require(isinstance(meta, dict), "Skill metadata must be a mapping")
    require(meta.get("name") == "claude-client-full-reset", "Unexpected skill name")
    require(isinstance(meta.get("description"), str) and 0 < len(meta["description"]) <= 1024,
            "Missing or oversized skill description")
    require(meta.get("license") == "MIT", "Expected MIT license metadata")
    require(set(meta) <= {"name", "description", "license", "metadata", "allowed-tools"},
            "Unsupported skill metadata")
    for ref in set(re.findall(r"(?:scripts|references)/[\w.-]+\.(?:md|sh|py|js)", text)):
        require((ROOT / ref).is_file(), f"Missing skill resource: {ref}")
    ui = yaml.safe_load((ROOT / "agents/openai.yaml").read_text())["interface"]
    require(25 <= len(ui["short_description"]) <= 64, "Invalid UI description length")
    require("$" + meta["name"] in ui["default_prompt"], "Default prompt must name skill")
    for name in ("README.md", "LICENSE", ".gitignore", ".github/workflows/validate.yml"):
        require((ROOT / name).is_file(), f"Missing release file: {name}")
    pkg = json.loads((ROOT / "package.json").read_text())
    lock = json.loads((ROOT / "package-lock.json").read_text())
    require(pkg["dependencies"] == lock["packages"][""]["dependencies"],
            "Dependency lock does not match package.json")
    require(pkg["private"] is True, "Package is intended for GitHub distribution")
    counts = {"python": 0, "bash": 0, "javascript": 0}
    for directory in ("scripts", "tools"):
        for path in sorted((ROOT / directory).glob("*")):
            if path.suffix == ".py":
                ast.parse(path.read_text(), filename=str(path))
                counts["python"] += 1
            elif path.suffix == ".sh":
                subprocess.run(["bash", "-n", str(path)], check=True)
                counts["bash"] += 1
            elif path.suffix == ".js":
                subprocess.run(["node", "--check", str(path)], check=True)
                counts["javascript"] += 1
    print("PASS: metadata, resources, dependency lock, and syntax", counts)
    print("Operational scripts were not executed. Functional release acceptance remains separate.")


if __name__ == "__main__":
    main()
