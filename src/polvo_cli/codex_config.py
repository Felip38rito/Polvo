"""Logic for updating the Codex CLI configuration to point at Polvo.

The Codex config (~/.codex/config.toml) uses TOML. We intentionally do not
do a full parse/rewrite because that would drop the [projects] trust blocks
and comments. Instead we do minimal, surgical text edits:

  - ensure the header sets model/adaptive, model_provider/polvo and
    model_catalog_json
  - replace any existing model_providers.<name> block with the polvo block
    (removing a legacy "nexus" provider if present)

The [projects] blocks and everything else are left byte-for-byte intact.
"""
from __future__ import annotations

import re
from pathlib import Path


PROVIDER_NAME = "polvo"


def _ensure_header(data: str, port: str) -> str:
    """Rewrite the top 'model = ...' / 'model_provider = ...' lines."""
    api = f"http://127.0.0.1:{port}/v1"

    def header_line(key: str, value: str) -> str:
        return f'{key} = "{value}"'

    lines = data.splitlines()
    out: list[str] = []
    seen_model = seen_provider = seen_catalog = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("model =") and not stripped.startswith("model_p"):
            out.append(header_line("model", "adaptive"))
            seen_model = True
            continue
        if stripped.startswith("model_provider =") or stripped.startswith("model_provider="):
            out.append(header_line("model_provider", PROVIDER_NAME))
            seen_provider = True
            continue
        if stripped.startswith("model_catalog_json =") or stripped.startswith("model_catalog_json="):
            out.append(header_line("model_catalog_json", str(Path.home() / ".codex" / "model.json")))
            seen_catalog = True
            continue
        out.append(line)

    # Fall back to inserting defaults before the first [ table header.
    if not (seen_model and seen_provider):
        extra = []
        if not seen_model:
            extra.append(header_line("model", "adaptive"))
        if not seen_provider:
            extra.append(header_line("model_provider", PROVIDER_NAME))
        if not seen_catalog:
            extra.append(header_line("model_catalog_json", str(Path.home() / ".codex" / "model.json")))

        # Insert extra lines right after the first line that starts a top-level key,
        # before any [table] header. Simpler: prepend the missing ones.
        result = "\n".join(out)
        for e in reversed(extra):
            result = e + "\n" + result
        return result

    return "\n".join(out)


def _replace_provider_block(data: str, provider_name: str) -> str:
    """Remove any existing [model_providers.<name>] block so we can rewrite it.

    A TOML table block runs from the [model_providers.X] header up to the
    next line that is a table/array header (starts with '[') or end of file.
    """
    header_re = re.compile(
        r"^\s*\[model_providers\.[A-Za-z0-9_\-\.]+\]\s*$", re.MULTILINE
    )

    out_lines: list[str] = []
    lines = data.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if header_re.match(line):
            # Extract the provider name inside the brackets.
            name_match = re.search(r"\[model_providers\.([A-Za-z0-9_\-.]+)\]", line)
            name = name_match.group(1) if name_match else ""
            # Skip this header and its body until the next [ header.
            while i < len(lines):
                current = lines[i]
                if current.strip().startswith("[") and current.strip() != line.strip():
                    break
                i += 1
            if name == provider_name:
                # We will re-insert the block in _append_provider_block.
                continue
            # Non-target provider: keep its block intact.
            out_lines.append(line)
            i -= 1 if i > 0 else 0
            continue
        out_lines.append(line)
        i += 1

    result = "\n".join(out_lines)
    # Normalize trailing blank lines.
    return result.rstrip() + "\n"


def _append_provider_block(data: str, port: str) -> str:
    """Append the [model_providers.polvo] block at the very end."""
    api = f"http://127.0.0.1:{port}/v1"
    block = (
        f"\n[model_providers.{PROVIDER_NAME}]\n"
        f'name = "Polvo Model Router (local)"\n'
        f'base_url = "{api}"\n'
        f'env_key = "POLVO_API_KEY"\n'
        f'wire_api = "responses"\n'
    )
    return data.rstrip() + block


def write_codex_config(port: str) -> str:
    """Rewrite ~/.codex/config.toml for Polvo. Returns the new contents."""
    path = Path.home() / ".codex" / "config.toml"
    if not path.exists():
        raise FileNotFoundError(
            "Codex config not found at ~/.codex/config.toml "
            "(is Codex CLI installed?)"
        )

    current = path.read_text()

    # Reorder: remove any pre-existing polvo block (so we don't append twice),
    # then rewrite the header, then append the fresh block.
    current = _replace_provider_block(current, PROVIDER_NAME)
    current = _ensure_header(current, port)
    updated = _append_provider_block(current, port)

    path.write_text(updated)
    return updated
