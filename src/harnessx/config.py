"""Configuration: .env parsing (no third-party deps) and run limits.

Precedence (high to low): explicit overrides > real environment variables >
workspace/.env > repo-root/.env > defaults. HARNESSX_* names win over MYAGENT_*.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

PREFIXES = ('HARNESSX_', 'MYAGENT_')


def parse_dotenv(path: Path) -> dict:
    out: dict = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        out[key] = val
    return out


@dataclass
class Config:
    base_url: str = 'https://api.deepseek.com'
    model: str = 'deepseek-v4-flash'
    api_key: str = ''
    max_steps: int = 30
    max_cost: float = 0.5
    max_seconds: float = 600.0
    tool_timeout: float = 60.0
    # 0 disables compaction. Estimated tokens above this trigger compaction.
    context_limit: int = 0
    keep_turns: int = 2
    # llm preserves facts from tool output; rule is deterministic and avoids extra model calls.
    summarizer: str = 'llm'
    # Placeholder estimates per million tokens; override via env. Not an official price list.
    price_in: float = 1.0
    price_out: float = 2.0
    request_timeout: float = 120.0

    @classmethod
    def load(cls, root: Path, workspace: Path | None = None, **overrides) -> 'Config':
        values: dict = {}
        for p in (Path(root) / '.env', (Path(workspace) / '.env') if workspace else None):
            if p is not None:
                values.update(parse_dotenv(p))
        values.update({k: v for k, v in os.environ.items() if k.startswith(PREFIXES)})
        cfg = cls()
        for f in fields(cls):
            raw = None
            for pre in PREFIXES:
                key = pre + f.name.upper()
                if key in values and values[key] != '':
                    raw = values[key]
                    break
            if raw is not None:
                setattr(cfg, f.name, type(getattr(cfg, f.name))(raw))
        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    def redacted(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        key = d.get('api_key') or ''
        d['api_key'] = (key[:3] + '***') if key else ''
        return d
