"""Structured NOTES archive plus rendered markdown views."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NoteRecord:
    note_id: str
    heading_key: str
    title: str
    body: str
    summary: str = ""
    roadmap_id: str = ""
    roadmap_label: str = ""
    roadmap_index: int | None = None
    step_id: str = ""
    step_index: int | None = None
    prop_id: str = ""
    dependencies: list[str] = field(default_factory=list)

    def render_full(self) -> str:
        meta_parts: list[str] = []
        if self.note_id:
            meta_parts.append(f"note_id: {self.note_id}")
        if self.roadmap_id:
            meta_parts.append(f"roadmap_id: {self.roadmap_id}")
        if self.roadmap_label:
            meta_parts.append(f"roadmap_label: {self.roadmap_label}")
        elif self.roadmap_index is not None:
            meta_parts.append(f"roadmap: {self.roadmap_index}")
        if self.step_id:
            meta_parts.append(f"step_id: {self.step_id}")
        if self.step_index is not None:
            meta_parts.append(f"step: {self.step_index}")
        if self.prop_id:
            meta_parts.append(f"prop_id: {self.prop_id}")
        if self.dependencies:
            meta_parts.append(f"dependencies: {','.join(self.dependencies)}")
        meta = f"<!-- {'; '.join(meta_parts)} -->\n" if meta_parts else ""
        return f"## {self.heading_key}: {self.title}\n{meta}\n{self.body.rstrip()}\n"

    def render_compact(self) -> str:
        summary = self.summary or Notes.summarize_body(self.body)
        return (
            f"## {self.heading_key}: {self.title}\n"
            f"[compacted older proof note]\n"
            f"{summary}\n"
        )


class Notes:
    """Manages canonical ``NOTES.json`` plus rendered ``NOTES.md``."""

    _LEGACY_SECTION_RE = re.compile(
        r"^## (?P<key>[^:\n]+): (?P<title>.*?)\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    _META_RE = re.compile(r"<!--\s*(.*?)\s*-->")

    def __init__(self, path: Path) -> None:
        if path.suffix == ".json":
            self.json_path = path
            self.md_path = path.with_suffix(".md")
        else:
            self.md_path = path
            self.json_path = path.with_suffix(".json")
        self.path = self.md_path

    @staticmethod
    def summarize_body(body: str, *, max_chars: int = 400) -> str:
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        summary = " ".join(lines[:2])[:max_chars]
        if len(lines) > 2 or len(body) > max_chars:
            summary += " [...]"
        return summary

    def load(self) -> str:
        if self.md_path.exists():
            return self.md_path.read_text(encoding="utf-8")
        records = self.load_records()
        if not records:
            return ""
        text = self._render_markdown(records)
        self.md_path.write_text(text, encoding="utf-8")
        return text

    def load_records(self) -> list[NoteRecord]:
        if self.json_path.exists():
            try:
                raw = json.loads(self.json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, TypeError):
                raw = []
            if isinstance(raw, list):
                return [self._record_from_dict(item) for item in raw if isinstance(item, dict)]
        if self.md_path.exists():
            return self._parse_legacy_markdown(self.md_path.read_text(encoding="utf-8"))
        return []

    def save_records(self, records: list[NoteRecord]) -> None:
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(record) for record in records]
        self.json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.md_path.write_text(self._render_markdown(records), encoding="utf-8")

    @staticmethod
    def _record_from_dict(data: dict[str, Any]) -> NoteRecord:
        return NoteRecord(
            note_id=str(data.get("note_id", "")),
            heading_key=str(data.get("heading_key", "")),
            title=str(data.get("title", "")),
            body=str(data.get("body", "")),
            summary=str(data.get("summary", "")),
            roadmap_id=str(data.get("roadmap_id", "")),
            roadmap_label=str(data.get("roadmap_label", "")),
            roadmap_index=data.get("roadmap_index"),
            step_id=str(data.get("step_id", "")),
            step_index=data.get("step_index"),
            prop_id=str(data.get("prop_id", "")),
            dependencies=[str(item) for item in data.get("dependencies", [])],
        )

    def _parse_legacy_markdown(self, text: str) -> list[NoteRecord]:
        if not text.strip():
            return []
        records: list[NoteRecord] = []
        for match in self._LEGACY_SECTION_RE.finditer(text):
            key = match.group("key").strip()
            title = match.group("title").strip()
            body = match.group("body").strip()
            note_id = key
            roadmap_id = ""
            roadmap_label = ""
            roadmap_index = None
            step_id = ""
            step_index = None
            prop_id = key if not key.startswith("Step ") else ""
            meta_match = self._META_RE.match(body)
            if meta_match:
                meta_text = meta_match.group(1)
                body = body[meta_match.end():].lstrip()
                note_id = self._meta_value(meta_text, "note_id") or key
                roadmap_id = self._meta_value(meta_text, "roadmap_id")
                roadmap_label = self._meta_value(meta_text, "roadmap_label")
                step_id = self._meta_value(meta_text, "step_id")
                prop_id = self._meta_value(meta_text, "prop_id") or prop_id
                deps_raw = self._meta_value(meta_text, "dependencies")
                dependencies = [item.strip() for item in deps_raw.split(",") if item.strip()] if deps_raw else []
                roadmap_hit = re.search(r"roadmap:\s*(\d+)", meta_text)
                step_hit = re.search(r"step:\s*(\d+)", meta_text)
                if roadmap_hit:
                    roadmap_index = int(roadmap_hit.group(1))
                if step_hit:
                    step_index = int(step_hit.group(1))
            else:
                dependencies = []
                if key.startswith("Step "):
                    step_hit = re.match(r"Step\s+(\d+)", key)
                    if step_hit:
                        step_index = int(step_hit.group(1))
            records.append(
                NoteRecord(
                    note_id=note_id or key,
                    heading_key=key,
                    title=title,
                    body=body,
                    summary=self.summarize_body(body),
                    roadmap_id=roadmap_id,
                    roadmap_label=roadmap_label,
                    roadmap_index=roadmap_index,
                    step_id=step_id,
                    step_index=step_index,
                    prop_id=prop_id,
                    dependencies=dependencies,
                )
            )
        return records

    @staticmethod
    def _meta_value(meta_text: str, key: str) -> str:
        match = re.search(rf"{re.escape(key)}:\s*([^;]+)", meta_text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _render_markdown(records: list[NoteRecord]) -> str:
        if not records:
            return ""
        return "\n".join(record.render_full().rstrip() for record in records).strip() + "\n"

    @staticmethod
    def _choose_note_id(
        *,
        heading_key: str,
        step_index: int,
        roadmap_id: str,
        step_id: str,
        prop_id: str,
    ) -> str:
        if prop_id:
            return f"proof:{prop_id}"
        if step_id:
            return f"proof:{step_id}"
        if roadmap_id:
            return f"proof:{roadmap_id}:step:{step_index}"
        return f"proof:{heading_key}"

    def append_step_proof(
        self,
        step_index: int,
        step_description: str,
        proof_detail: str,
        *,
        key: str | None = None,
        roadmap_index: int | None = None,
        roadmap_id: str | None = None,
        roadmap_label: str | None = None,
        step_id: str | None = None,
        prop_id: str | None = None,
        dependencies: list[str] | None = None,
    ) -> str:
        records = self.load_records()
        heading_key = key if key else f"Step {step_index}"
        note_id = self._choose_note_id(
            heading_key=heading_key,
            step_index=step_index,
            roadmap_id=roadmap_id or "",
            step_id=step_id or "",
            prop_id=prop_id or "",
        )
        record = NoteRecord(
            note_id=note_id,
            heading_key=heading_key,
            title=step_description,
            body=proof_detail,
            summary=self.summarize_body(proof_detail),
            roadmap_id=roadmap_id or "",
            roadmap_label=roadmap_label or "",
            roadmap_index=roadmap_index,
            step_id=step_id or "",
            step_index=step_index,
            prop_id=prop_id or "",
            dependencies=list(dict.fromkeys(dependencies or [])),
        )
        filtered = [
            existing
            for existing in records
            if existing.note_id != note_id
            and existing.heading_key != heading_key
        ]
        filtered.append(record)
        self.save_records(filtered)
        return note_id

    def get_step_proof(self, step_index: int, *, step_id: str | None = None) -> str | None:
        for record in self.load_records():
            if step_id and record.step_id == step_id:
                return record.render_full().strip()
            if record.step_index == step_index or record.heading_key == f"Step {step_index}":
                return record.render_full().strip()
        return None

    def get_proposition_proof(self, prop_id: str) -> str | None:
        for record in self.load_records():
            if record.prop_id == prop_id or record.heading_key == prop_id:
                return record.render_full().strip()
        return None

    def get_note_summary(self, note_id: str) -> str | None:
        for record in self.load_records():
            if record.note_id == note_id:
                return record.summary
        return None

    def remove_sections(self, keys: list[str]) -> int:
        if not keys:
            return 0
        records = self.load_records()
        keep = [
            record for record in records
            if record.heading_key not in set(keys)
            and record.note_id not in set(keys)
        ]
        removed = len(records) - len(keep)
        if removed:
            self.save_records(keep)
        return removed

    def render_for_compile(
        self,
        *,
        current_roadmap: int | None = None,
        current_roadmap_id: str | None = None,
        keep_recent_roadmaps: int = 2,
        max_chars: int = 140_000,
    ) -> str:
        records = self.load_records()
        if not records:
            return ""
        rendered: list[str] = []
        for record in records:
            is_old = False
            if current_roadmap_id and record.roadmap_id and record.roadmap_id != current_roadmap_id:
                is_old = True
            elif (
                current_roadmap is not None
                and record.roadmap_index is not None
                and record.roadmap_index <= max(current_roadmap - keep_recent_roadmaps, 0)
            ):
                is_old = True
            rendered.append(record.render_compact() if is_old else record.render_full())
        text = "\n".join(block.rstrip() for block in rendered).strip()
        if len(text) <= max_chars:
            return text

        fit: list[str] = []
        total = 0
        omitted = 0
        for record in reversed(records):
            block = record.render_compact()
            if total + len(block) > max_chars:
                omitted += 1
                continue
            fit.append(block)
            total += len(block)
        fit.reverse()
        header = f"(omitted {omitted} older NOTES record(s) due to prompt budget)\n\n" if omitted else ""
        final = header + "\n".join(block.rstrip() for block in fit).strip()
        return final[:max_chars]

    def render_for_worker(
        self,
        *,
        relevant_keys: list[str] | None = None,
        max_chars: int = 12_000,
    ) -> str:
        records = self.load_records()
        if not records:
            return ""
        keys = set(relevant_keys or [])
        selected = [
            record
            for record in records
            if (
                not keys
                or record.heading_key in keys
                or record.note_id in keys
                or record.prop_id in keys
                or any(key in record.dependencies for key in keys)
            )
        ]
        if not selected:
            selected = records[-4:]
        rendered = "\n".join(record.render_compact() for record in selected).strip()
        return rendered[:max_chars]
