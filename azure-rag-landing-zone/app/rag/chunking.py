"""Heading-aware markdown chunking with overlap."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    title: str
    content: str


def chunk_markdown(text: str, source: str, max_chars: int = 900, overlap: int = 150) -> list[Chunk]:
    """Split on headings first, then on paragraph boundaries within max_chars."""
    sections: list[tuple[str, str]] = []
    title = Path(source).stem.replace("-", " ").title()
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)", line)
        if m:
            if "".join(buf).strip():
                sections.append((title, "\n".join(buf).strip()))
            title, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((title, "\n".join(buf).strip()))

    chunks: list[Chunk] = []
    for sec_title, body in sections:
        for piece in _split(body, max_chars, overlap):
            digest = hashlib.sha1(f"{source}|{len(chunks)}|{piece}".encode(), usedforsecurity=False).hexdigest()[:16]
            chunks.append(Chunk(id=digest, source=source, title=sec_title, content=piece))
    return chunks


def _split(body: str, max_chars: int, overlap: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    out, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            out.append(cur)
            cur = cur[-overlap:] + "\n\n" + p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def load_docs(docs_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("*.md")):
        chunks += chunk_markdown(path.read_text(encoding="utf-8"), path.name)
    return chunks
