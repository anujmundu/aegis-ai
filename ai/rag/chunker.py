"""Markdown Structure-Aware Hierarchical Chunker for AegisAI.

Splits operational documentation and runbooks along structural heading boundaries
while keeping diagnostic code blocks, tables, and commands intact.
"""

import re
from pathlib import Path
from typing import List, Union

from ai.rag.models import DocumentChunk


def slugify(text: str) -> str:
    """Convert header text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text)


class MarkdownHierarchicalChunker:
    """Structure-aware chunker parsing markdown by header levels."""

    def __init__(self, min_chunk_chars: int = 60) -> None:
        self.min_chunk_chars = min_chunk_chars

    def chunk_file(self, filepath: Union[str, Path]) -> List[DocumentChunk]:
        """Read a markdown file and return hierarchical chunks."""
        path = Path(filepath)
        content = path.read_text(encoding="utf-8")
        doc_type = "runbook" if "runbook" in path.parts else "postmortem"
        return self.chunk_text(content, source_uri=str(path.as_posix()), doc_type=doc_type)

    def chunk_text(
        self,
        text: str,
        source_uri: str = "unknown.md",
        doc_type: str = "document",
    ) -> List[DocumentChunk]:
        """Split markdown text into logical section chunks."""
        lines = text.split("\n")
        chunks: List[DocumentChunk] = []

        file_stem = Path(source_uri).stem
        doc_title = file_stem.replace("_", " ").title()
        current_section = "Overview"
        current_lines: List[str] = []

        in_code_block = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block

            # Identify headers outside of code blocks
            if not in_code_block and re.match(r"^#{1,3}\s+", line):
                # Flush previous section if it contains enough content
                section_text = "\n".join(current_lines).strip()
                if len(section_text) >= self.min_chunk_chars:
                    chunk_id = f"{file_stem}#{slugify(current_section)}"
                    chunks.append(
                        DocumentChunk(
                            chunk_id=chunk_id,
                            source_uri=source_uri,
                            doc_title=doc_title,
                            section_title=current_section,
                            content=section_text,
                            token_count=len(section_text.split()),
                            metadata={"doc_type": doc_type, "file_stem": file_stem},
                        )
                    )
                current_lines = [line]
                header_match = re.match(r"^#{1,3}\s+(.+)$", line)
                if header_match:
                    header_title = header_match.group(1).strip()
                    if line.startswith("# ") and doc_title == file_stem.replace("_", " ").title():
                        doc_title = header_title
                    current_section = header_title
            else:
                current_lines.append(line)

        # Flush final section
        section_text = "\n".join(current_lines).strip()
        if len(section_text) >= self.min_chunk_chars:
            chunk_id = f"{file_stem}#{slugify(current_section)}"
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    source_uri=source_uri,
                    doc_title=doc_title,
                    section_title=current_section,
                    content=section_text,
                    token_count=len(section_text.split()),
                    metadata={"doc_type": doc_type, "file_stem": file_stem},
                )
            )

        return chunks

    def chunk_directory(self, dir_path: Union[str, Path]) -> List[DocumentChunk]:
        """Recursively chunk all markdown files in a directory."""
        directory = Path(dir_path)
        all_chunks: List[DocumentChunk] = []
        for md_file in sorted(directory.rglob("*.md")):
            all_chunks.extend(self.chunk_file(md_file))
        return all_chunks
