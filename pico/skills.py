"""Local skill discovery and rendering.

Skills are lightweight prompt packs stored under ``.pico/skills/<name>/SKILL.md``.
They do not add executable power by themselves; they only give the agent a
task-specific working style inside the existing tool and approval boundary.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .workspace import clip

SKILL_FILE_NAME = "SKILL.md"
DEFAULT_SKILLS_DIR_NAME = ".pico/skills"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: tuple[str, ...]
    body: str
    path: str

    def matches(self, text):
        haystack = str(text or "").lower()
        return any(trigger.lower() in haystack for trigger in self.triggers if trigger)

    def to_prompt_text(self):
        lines = [f"### {self.name}"]
        if self.description:
            lines.append(f"Description: {self.description}")
        if self.triggers:
            lines.append("Triggers: " + ", ".join(self.triggers))
        if self.body:
            lines.append(self.body)
        return "\n".join(lines).strip()


class SkillCatalog:
    def __init__(self, skills=None, root=None):
        self.skills = dict(skills or {})
        self.root = Path(root).resolve() if root else None

    @classmethod
    def load(cls, root):
        root = Path(root).resolve()
        skills = {}
        if not root.exists():
            return cls(skills, root=root)
        for skill_file in sorted(root.glob(f"*/{SKILL_FILE_NAME}")):
            try:
                skill = parse_skill_file(skill_file)
            except ValueError:
                continue
            skills[skill.name] = skill
        return cls(skills, root=root)

    def names(self):
        return sorted(self.skills)

    def get(self, name):
        return self.skills.get(str(name or "").strip())

    def unknown_names(self, names):
        return [name for name in names if str(name).strip() and str(name).strip() not in self.skills]

    def select(self, request="", manual_names=()):
        selected = []
        seen = set()
        for name in manual_names or ():
            name = str(name or "").strip()
            if name in self.skills and name not in seen:
                selected.append(name)
                seen.add(name)
        for skill in self.skills.values():
            if skill.name not in seen and skill.matches(request):
                selected.append(skill.name)
                seen.add(skill.name)
        return tuple(selected)

    def render(self, names):
        selected = [self.skills[name] for name in names if name in self.skills]
        if not selected:
            return ""
        body = "\n\n".join(skill.to_prompt_text() for skill in selected)
        return "Active skills:\n" + clip(body, 6000)

    def summary_text(self):
        if not self.skills:
            location = str(self.root) if self.root else DEFAULT_SKILLS_DIR_NAME
            return f"No skills found in {location}."
        lines = []
        for skill in self.skills.values():
            description = f" - {skill.description}" if skill.description else ""
            triggers = f" (triggers: {', '.join(skill.triggers)})" if skill.triggers else ""
            lines.append(f"- {skill.name}{description}{triggers}")
        return "\n".join(lines)

    def signature(self, names):
        payload = []
        for name in names:
            skill = self.skills.get(name)
            if not skill:
                continue
            payload.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "triggers": list(skill.triggers),
                    "body": skill.body,
                    "path": skill.path,
                }
            )
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def default_skills_dir(repo_root):
    return Path(repo_root) / DEFAULT_SKILLS_DIR_NAME


def parse_skill_file(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    metadata, body = parse_frontmatter(text)
    name = str(metadata.get("name") or path.parent.name).strip()
    if not NAME_PATTERN.match(name):
        raise ValueError(f"invalid skill name: {name}")
    description = str(metadata.get("description", "")).strip()
    triggers = tuple(str(item).strip() for item in metadata.get("triggers", ()) if str(item).strip())
    return Skill(
        name=name,
        description=description,
        triggers=triggers,
        body=body.strip(),
        path=str(path),
    )


def parse_frontmatter(text):
    text = str(text or "")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw_metadata = text[4:end]
    body = text[end + len("\n---") :].lstrip("\r\n")
    return parse_simple_yaml(raw_metadata), body


def parse_simple_yaml(text):
    metadata = {}
    current_list_key = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            metadata.setdefault(current_list_key, []).append(_unquote(stripped[2:].strip()))
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if not value:
            metadata[key] = []
            current_list_key = key
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            metadata[key] = [_unquote(item.strip()) for item in inner.split(",") if item.strip()]
        else:
            metadata[key] = _unquote(value)
    return metadata


def _unquote(value):
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
