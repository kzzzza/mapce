"""Paper ↔ Code mapper.

Prepares the context for and processes the output of a subagent that
establishes mappings between paper methods and code implementations.

The actual mapping logic runs via a Claude subagent; this module provides
the data preparation and result parsing infrastructure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract_paper_methods(paper_dir: Path) -> list[dict[str, str]]:
    """Extract method/algorithm names mentioned in a parsed paper.

    Scans the MinerU markdown for method names, algorithm references,
    and implementation indicators that could link to code.

    Args:
        paper_dir: MinerU-parsed paper directory.

    Returns:
        List of {"name": str, "context": str, "section": str} dicts.
    """
    from mapce.mineru.parser import MinerUOutput
    import re

    mineru = MinerUOutput(paper_dir)
    sections = mineru.extract_sections()

    methods = []

    # Patterns that indicate a named method/algorithm
    method_patterns = [
        # "We propose X" / "We present X" / "Our X"
        re.compile(r"(?:we\s+(?:propose|present|introduce|develop|design))\s+(?:a\s+)?(?:novel\s+)?(?:method|called\s+)?[\"']?([A-Z][\w\s-]{3,40}?)[\"']?(?:,|\.|\s*\()", re.IGNORECASE),
        # "X is a / X algorithm" named entities
        re.compile(r"([A-Z][\w\s-]{3,40}?)\s+(?:is\s+a\s+|algorithm|method|approach|model|policy|architecture)", re.IGNORECASE),
        # "Algorithm N: Name" or "Algorithm N Name"
        re.compile(r"[Aa]lgorithm\s+\d+[:\s]+(.+?)(?:\n|$)", re.IGNORECASE),
        # Named in section headings
        re.compile(r"^#+\s+(.+?(?:Method|Model|Policy|Architecture|Algorithm|Network|Framework).+?)$", re.MULTILINE),
    ]

    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", "")

        # Check heading first
        for pat in method_patterns:
            for match in pat.finditer(heading):
                name = match.group(1).strip()
                if len(name) > 5:
                    methods.append({
                        "name": name,
                        "context": heading,
                        "section": heading,
                    })

        # Then content (first 5000 chars of each section to avoid noise)
        text = content[:5000]
        for pat in method_patterns[:2]:  # only the sentence patterns for body text
            for match in pat.finditer(text):
                name = match.group(1).strip()
                # Filter out common non-method phrases
                if name.lower() in ("the", "this", "these", "our", "each", "such", "figure", "table"):
                    continue
                if len(name) > 5:
                    methods.append({
                        "name": name,
                        "context": text[max(0, match.start() - 100):match.end() + 100],
                        "section": heading,
                    })

    # Deduplicate by name similarity
    seen = set()
    unique = []
    for m in methods:
        key = m["name"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique


def extract_code_symbols(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract symbol summaries from code chunks for the mapper subagent.

    Args:
        chunks: All code chunks from chunk_repo().

    Returns:
        Summary list with {symbol_name, symbol_type, file_path, docstring, signature}.
    """
    symbols = []
    for c in chunks:
        if c.get("chunk_type") in ("code_l3", "code_l5") and c.get("symbol_name"):
            symbols.append({
                "symbol_name": c["symbol_name"],
                "symbol_type": c.get("symbol_type", ""),
                "file_path": c.get("file_path", ""),
                "signature": c.get("signature", ""),
                "docstring": c.get("docstring", ""),
            })
    return symbols


def build_mapping_prompt(
    paper_methods: list[dict[str, str]],
    code_symbols: list[dict[str, Any]],
    repo_name: str,
    paper_title: str = "",
) -> str:
    """Build the prompt for the subagent that performs Paper↔Code mapping.

    This prompt is designed to be used by a Claude subagent via the Agent tool.
    The subagent returns a JSON array of mapping objects.

    Args:
        paper_methods: Output of extract_paper_methods().
        code_symbols: Output of extract_code_symbols().
        repo_name: Repository name for context.
        paper_title: Paper title for context.

    Returns:
        A prompt string for the subagent.
    """
    methods_text = "\n".join(
        f"- {m['name']} (section: {m.get('section', '?')})"
        for m in paper_methods[:30]
    ) if paper_methods else "(no methods extracted)"

    symbols_text = "\n".join(
        f"- [{s['symbol_type']}] {s['symbol_name']}  @ {s['file_path']}\n"
        f"  signature: {s.get('signature', '?')}\n"
        f"  docstring: {s.get('docstring', '?')[:150]}"
        for s in code_symbols[:50]
    ) if code_symbols else "(no symbols extracted)"

    prompt = f"""You are mapping research paper methods to their code implementations.

## Paper
Title: {paper_title or '(unknown)'}

### Methods mentioned in the paper:
{methods_text}

## Code Repository: {repo_name}

### Code symbols found:
{symbols_text}

## Task
Establish mappings between paper methods and code symbols using these heuristics:

1. **Exact match**: Paper method name appears as a class/function name in code
2. **Semantic match**: Method description matches the docstring/signature
3. **Structural match**: Algorithm pseudocode structure matches code structure
4. **README clues**: README often says "see model/diffusion.py for details"

For each mapping found, assess confidence: "high", "medium", or "low".
Only return mappings with confidence "high" or "medium".

Return a JSON array:
```json
[
  {{
    "paper_method": "Diffusion Policy",
    "code_chunk_id": "code:paper_id:repo_name:l3:42",  // from the chunk_id of the code symbol
    "repo_name": "{repo_name}",
    "confidence": "high",
    "evidence": "Class name DiffusionUNet matches; README confirms this implements the diffusion policy"
  }}
]
```

Use the exact code_chunk_id values provided. If you don't know the chunk_id, use the symbol_name and file_path.
"""
    return prompt


def parse_mapping_response(response: str, paper_id: str) -> list[dict[str, Any]]:
    """Parse the subagent's JSON response into mapping dicts ready for DB insert.

    Args:
        response: The raw text response from the subagent.
        paper_id: The paper ID to associate mappings with.

    Returns:
        List of mapping dicts matching the paper_code_mapping schema.
    """
    import re

    # Try to extract JSON from the response
    json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to find a raw JSON array
        json_match = re.search(r"\[\s*\{.*?\}\s*\]", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = response

    try:
        raw_mappings = json.loads(json_str)
    except json.JSONDecodeError:
        return []

    mappings = []
    for i, m in enumerate(raw_mappings):
        mappings.append({
            "mapping_id": f"map:{paper_id}:{i:04d}",
            "paper_id": paper_id,
            "paper_method": m.get("paper_method", ""),
            "code_chunk_id": m.get("code_chunk_id", m.get("symbol_name", "")),
            "repo_name": m.get("repo_name", ""),
            "confidence": m.get("confidence", "medium"),
            "evidence": m.get("evidence", ""),
            "created_by": "subagent",
            "verified": False,
        })

    return mappings
