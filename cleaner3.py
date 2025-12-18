from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except ImportError as e:
    raise SystemExit(
        "Saknar paketet 'openai'. Installera med:\n"
        "  pip install --upgrade openai\n"
        "Och sätt OPENAI_API_KEY som miljövariabel.\n"
    ) from e


# ============================================================
# cleaner2_v2.py
#
# - Tvättar råa prompts till en ren, engelsk Cursor-prompt
# - Sparar historik i .cleaner/
# - Maximerar OpenAI Prompt Caching (stabil prefix + variabel svans)
# - (Valfritt) Semantisk cache med embeddings för "nästan-samma" prompts
# ============================================================


# ---------- ANSI färger (valfritt) ----------
ANSI_RESET = "\033[0m"
ANSI_GRAY = "\033[90m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_CYAN = "\033[36m"


def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    # Windows Terminal / VS Code terminal brukar ha stöd
    return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM") or os.environ.get("ANSICON"))


ANSI_OK = _supports_ansi()


def _c(s: str, color: str) -> str:
    if not ANSI_OK:
        return s
    return f"{color}{s}{ANSI_RESET}"


# ---------- Projekt / .cleaner ----------
def find_project_and_cleaner(start: Path) -> Tuple[Path, Path]:
    """
    Leta upp projektrot via närmaste .cleaner/ när man går uppåt från start.
    Om start är .cleaner -> projektrot = parent.
    Om ingen .cleaner hittas -> projektrot = start (cwd).
    """
    start = start.resolve()
    if start.name == ".cleaner":
        return start.parent, start

    for p in [start] + list(start.parents):
        cand = p / ".cleaner"
        if cand.is_dir():
            return p, cand

    # fallback: anta att start är projektrot
    return start, start / ".cleaner"


PROJECT_ROOT, CLEANER_DIR = find_project_and_cleaner(Path.cwd())
CLEANER_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CLEANER_DIR / ".preprompt_config.json"
HISTORY_FILE = CLEANER_DIR / ".preprompt_history.json"
SEMANTIC_CACHE_FILE = CLEANER_DIR / ".semantic_cache.json"


# ---------- Modellval ----------
MODEL_MAP: Dict[str, str] = {
    "chat": "gpt-5.2-chat-latest",
    "standard": "gpt-5.2",
    "pro": "gpt-5.2-pro",
}

# Modeller som stöder "extended" prompt cache retention via prompt_cache_retention="24h"
# (enligt OpenAI docs är gpt-5.2 med i listan; vi inkluderar även chat-latest som brukar mappa dit)
EXTENDED_CACHE_SUPPORTED = {
    "gpt-5.2",
    "gpt-5.2-chat-latest",
    # Om du senare använder andra modeller, lägg till här vid behov.
}


# ---------- Priser (USD per 1M tokens) ----------
# KÄLLA: OpenAI API pricing (standard processing). (Cached input saknas för pro).
#
# OBS: OpenAI nämner även "processing priority" men listar inte alltid separata tokenpriser här.
# Den här tabellen är därför bara "standard".
PRICING_USD_PER_1M: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {
    "standard": {
        "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
        "gpt-5.2-chat-latest": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
        "gpt-5.2-pro": {"input": 21.00, "cached_input": None, "output": 168.00},
    },
}

# Responses API brukar returnera service_tier="default" för standard
TIER_ALIASES = {
    "default": "standard",
    "auto": "standard",
}


def _normalize_tier(tier: str) -> str:
    t = (tier or "").strip().lower()
    if not t:
        return "standard"
    return TIER_ALIASES.get(t, t)


def _fmt_usd(x: float) -> str:
    return f"${x:,.6f}"


def _safe_int(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def _estimate_cost_breakdown(model_id: str, tier: str, usage: Dict[str, Any]) -> Optional[Dict[str, float]]:
    tier_norm = _normalize_tier(tier)
    tier_rates = PRICING_USD_PER_1M.get(tier_norm)
    if not tier_rates:
        return None
    rates = tier_rates.get(model_id)
    if not rates:
        return None

    in_rate = rates.get("input")
    out_rate = rates.get("output")
    cached_rate = rates.get("cached_input")

    if in_rate is None or out_rate is None:
        return None

    input_tokens = _safe_int(usage.get("input_tokens"))
    output_tokens = _safe_int(usage.get("output_tokens"))

    input_details = usage.get("input_tokens_details") or {}
    cached_tokens = _safe_int(input_details.get("cached_tokens")) if isinstance(input_details, dict) else 0
    non_cached_input = max(0, input_tokens - cached_tokens)

    # Om cached_rate saknas (t.ex. pro), räkna cached som vanlig input
    if cached_rate is None:
        cached_rate = in_rate

    cost_in = (non_cached_input / 1_000_000.0) * float(in_rate)
    cost_cached = (cached_tokens / 1_000_000.0) * float(cached_rate)
    cost_out = (output_tokens / 1_000_000.0) * float(out_rate)

    return {
        "cost_in": float(cost_in),
        "cost_cached": float(cost_cached),
        "cost_out": float(cost_out),
        "total": float(cost_in + cost_cached + cost_out),
    }


def print_token_report(model_id: str, resp: Any, requested_service_tier: Optional[str]) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        # vissa svarstyper kan sakna usage
        print(_c("⚠️  Inget usage-fält från API-svaret, kan inte räkna kostnad.", ANSI_YELLOW))
        return

    # openai python SDK kan ge "usage" som dict-liknande
    if not isinstance(usage, dict):
        try:
            usage = usage.model_dump()  # pydantic-ish
        except Exception:
            try:
                usage = dict(usage)
            except Exception:
                usage = {}

    input_tokens = _safe_int(usage.get("input_tokens"))
    output_tokens = _safe_int(usage.get("output_tokens"))
    total_tokens = _safe_int(usage.get("total_tokens"))

    input_details = usage.get("input_tokens_details") or {}
    cached_tokens = _safe_int(input_details.get("cached_tokens")) if isinstance(input_details, dict) else 0

    out_details = usage.get("output_tokens_details") or {}
    reasoning_tokens = _safe_int(out_details.get("reasoning_tokens")) if isinstance(out_details, dict) else 0

    resp_tier = getattr(resp, "service_tier", None)
    tier_used_raw = resp_tier or requested_service_tier or "standard"

    breakdown = _estimate_cost_breakdown(model_id, tier_used_raw, usage)

    print(_c("\n=== TOKENKOSTNAD (ESTIMAT: standard pricing) ===", ANSI_CYAN))
    print(f"Model:   {model_id}")
    if resp_tier:
        print(f"API tier (response): {resp_tier}")
    if requested_service_tier:
        print(f"API tier (requested): {requested_service_tier}")
    print(f"Pricing tier (calc): {_normalize_tier(tier_used_raw)}")

    print(f"Tokens:  input={input_tokens} (cached={cached_tokens})  output={output_tokens}  total={total_tokens}")
    if reasoning_tokens:
        print(f"Reasoning tokens: {reasoning_tokens} (räknas in i output)")

    if breakdown is None:
        print(_c("⚠️  Saknar prisrad för denna modell/tier i tabellen.", ANSI_YELLOW))
    else:
        print(_c(f"In:     {_fmt_usd(breakdown['cost_in'])}", ANSI_GREEN))
        if cached_tokens:
            print(_c(f"Cached: {_fmt_usd(breakdown['cost_cached'])}", ANSI_GREEN))
        print(_c(f"Out:    {_fmt_usd(breakdown['cost_out'])}", ANSI_GREEN))
        print(_c(f"TOTAL:  {_fmt_usd(breakdown['total'])}", ANSI_GREEN))


# ---------- JSON helpers ----------
def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Config & historik ----------
def load_config() -> Dict[str, Any]:
    cfg = load_json(CONFIG_FILE, default={})
    if not isinstance(cfg, dict):
        return {}
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    save_json(CONFIG_FILE, cfg)


def load_history(max_items: int = 50) -> List[Dict[str, Any]]:
    hist = load_json(HISTORY_FILE, default=[])
    if not isinstance(hist, list):
        return []
    if max_items and len(hist) > max_items:
        return hist[-max_items:]
    return hist


def save_history(hist: List[Dict[str, Any]]) -> None:
    save_json(HISTORY_FILE, hist)


def add_history_item(role: str, content: str) -> None:
    hist = load_history(max_items=500)
    hist.append({"ts": int(time.time()), "role": role, "content": content})
    save_history(hist)


def summarize_history_for_context(history: List[Dict[str, Any]], max_items: int = 8) -> str:
    if not history:
        return ""
    items = history[-max_items:]
    lines: List[str] = []
    for item in items:
        role = str(item.get("role", "unknown")).upper()
        content = (item.get("content") or "").strip().replace("\n", " ")
        if len(content) > 220:
            content = content[:220] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


# ---------- .cleaner docs: project tree + instruktioner ----------
def load_precomputed_tree(cleaner_dir: Path) -> Optional[str]:
    """
    Föredrar förgenererade tree-filer i .cleaner.
    Du kan t.ex. lägga:
      .cleaner/project_tree.txt
      .cleaner/project_tree.ansi.txt
      .cleaner/tree.txt
    """
    candidates = [
        cleaner_dir / "project_tree.ansi.txt",
        cleaner_dir / "project_tree.txt",
        cleaner_dir / "tree.ansi.txt",
        cleaner_dir / "tree.txt",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                continue
    return None


def get_project_tree(root: Path, max_chars: int = 2500, max_depth: int = 3) -> str:
    """
    Enkel, snabb tree-walk. Inte ANSI, bara text.
    """
    lines: List[str] = []

    def walk(base: Path, depth: int = 0):
        if depth > max_depth:
            return
        try:
            entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except Exception:
            return

        for entry in entries:
            if entry.name in {".git", "node_modules", ".venv", "__pycache__", ".idea", ".vscode"}:
                continue
            indent = "  " * depth
            if entry.is_dir():
                lines.append(f"{indent}- {entry.name}/")
                walk(entry, depth + 1)
            else:
                lines.append(f"{indent}- {entry.name}")

    walk(root, 0)
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n...[truncated]"
    return out


def discover_instruction_files(cleaner_dir: Path) -> List[Path]:
    """
    Om användaren inte konfigurerat några instruction_files: försök hitta relevanta docs i .cleaner/.
    """
    preferred = [
        "instructions.md",
        "cursor_instructions.md",
        "project_instructions.md",
        "conventions.md",
        "architecture.md",
        "notes.md",
        "README.md",
    ]
    found: List[Path] = []
    for name in preferred:
        p = cleaner_dir / name
        if p.exists() and p.is_file():
            found.append(p)

    # fallback: plocka upp kortare .md/.txt i .cleaner (max 80k)
    if not found:
        for p in sorted(cleaner_dir.glob("*.md")) + sorted(cleaner_dir.glob("*.txt")):
            try:
                if p.stat().st_size <= 80_000:
                    found.append(p)
            except Exception:
                continue

    # dedupe
    out: List[Path] = []
    seen = set()
    for p in found:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def read_instruction_files(cfg: Dict[str, Any], root: Path, cleaner_dir: Path, max_chars: int = 2500) -> str:
    """
    Läser ett antal "instruktionsfiler" som hjälper Cursor-assistenten (arkitektur, conventions, etc).
    1) Om cfg.instruction_files finns -> använd dem (relativt root eller absolut).
    2) Annars -> försök auto-hitta i .cleaner/.
    """
    cfg_files = cfg.get("instruction_files")
    paths: List[Path] = []
    if isinstance(cfg_files, list) and cfg_files:
        for x in cfg_files:
            if not isinstance(x, str) or not x.strip():
                continue
            p = Path(x).expanduser()
            if not p.is_absolute():
                p = (root / p).resolve()
            paths.append(p)
    else:
        paths = discover_instruction_files(cleaner_dir)

    chunks: List[str] = []
    total = 0
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        rel = None
        try:
            rel = str(p.resolve().relative_to(root.resolve()))
        except Exception:
            rel = str(p)
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # korta ner per fil
        if len(txt) > 1600:
            txt = txt[:1600] + "\n...[truncated]"
        block = f"### {rel}\n{txt.strip()}"
        chunks.append(block)
        total += len(block)
        if total >= max_chars:
            break

    return "\n\n".join(chunks).strip()


def detect_focus_files(raw_prompt: str, root: Path) -> List[str]:
    """
    Plockar upp @relative/path eller relativa paths i prompten.
    Returnerar relativa paths (med /) där filen faktiskt finns.
    """
    candidates = set()
    for token in raw_prompt.replace("\n", " ").split():
        t = token.strip()
        if not t:
            continue
        clean = t.strip(",.;:()[]{}<>\"'`")
        if clean.startswith("@"):
            clean = clean[1:]
        if not clean or clean.startswith(("-", "#")):
            continue
        if any(clean.startswith(prefix) for prefix in ("http://", "https://")):
            continue
        # enkel heuristik: en path brukar ha / eller \ eller en filändelse
        if ("/" in clean) or ("\\" in clean) or ("." in Path(clean).name):
            candidates.add(clean)

    focus_paths: List[str] = []
    seen = set()
    for cnd in candidates:
        # normalisera \ -> /
        cnd_norm = cnd.replace("\\", "/")
        p = (root / cnd_norm).resolve()
        if p.exists() and p.is_file():
            try:
                rel = p.relative_to(root.resolve())
                rel_s = str(rel).replace("\\", "/")
            except Exception:
                rel_s = cnd_norm
            if rel_s not in seen:
                seen.add(rel_s)
                focus_paths.append(rel_s)

    return focus_paths[:12]


# ---------- Prompt building (cache-friendly) ----------
def build_static_instructions(cfg: Dict[str, Any]) -> str:
    """
    STABILT prefix: ska ändras så sällan som möjligt för maximal prompt caching.
    """
    project_name = (cfg.get("project_name") or "(unknown)").strip()
    tech_stack = (cfg.get("tech_stack") or "").strip()
    language_mode = (cfg.get("language_mode") or "sv_to_en").strip()

    return textwrap.dedent(
        f"""
        You are a prompt pre-processor for a coding assistant inside the Cursor editor.

        Your ONLY job:
        - Transform the user's raw, messy request (possibly Swedish) into ONE clean, structured English prompt.
        - The user will paste your output directly into Cursor.
        - You must NOT answer the coding task yourself.

        Output rules:
        - Output ONLY the cleaned prompt, nothing else.
        - Write in clear English.
        - Keep it concise but complete.
        - Do not mention tokens, pricing, OpenAI, or internal tooling.

        Formatting:
        - Use Markdown.
        - Use these exact headings in this order:
          1) Goal
          2) Context
          3) Constraints
          4) Assumptions / Questions (only if needed)
          5) Steps
          6) Likely involved files
          7) Acceptance criteria

        In "Likely involved files":
        - List 3–6 items total.
        - Prefer concrete files. You may use up to 2 globs/directories total.
        - For each item, include:
          - @relative/path (p_involved=NN%, p_relevance=MM%)
        - Sort by p_involved desc, then p_relevance desc.

        Project metadata:
        - Project name: {project_name}
        - Tech stack: {tech_stack}
        - Language mode: {language_mode}
        """
    ).strip()


def build_context_blocks(
    project_tree: str,
    instructions_text: str,
) -> str:
    """
    Relativt stabilt block (tree + instruktioner).
    Lämna detta tidigt i input så att det kan bli cached prefix när det inte ändras.
    """
    tree_section = project_tree.strip() or "(no tree available)"
    instr_section = instructions_text.strip() or "(no instruction docs found)"

    return textwrap.dedent(
        f"""
        [PROJECT TREE]
        {tree_section}

        [PROJECT DOCS / INSTRUCTIONS]
        {instr_section}
        """
    ).strip()


def build_variable_tail(history_summary: str, focus_files: List[str], raw_prompt: str) -> str:
    """
    Variabel svans som ofta ändras (historik, fokusfiler, själva prompten).
    LÄGG SIST för att inte sabba caching av tidigare prefix.
    """
    if focus_files:
        focus_block = "\n".join(f"- @{p}" for p in focus_files)
    else:
        focus_block = "- (none detected)"

    hist = history_summary.strip() or "(no recent history)"

    return textwrap.dedent(
        f"""
        [FOCUS FILES]
        {focus_block}

        [RECENT CONTEXT]
        {hist}

        [USER RAW REQUEST]
        {raw_prompt.strip()}
        """
    ).strip()


def _sha256_short(s: str, n: int = 16) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:n]


def compute_project_fingerprint(static_context: str) -> str:
    """
    Fingerprint för att undvika att semantisk cache återanvänder resultat när projektet ändrats.
    (Baseras på tree + docs-snippets som vi ändå skickar).
    """
    return _sha256_short(static_context, 16)


def compute_prompt_cache_key(cfg: Dict[str, Any], model_id: str, project_root: Path) -> str:
    """
    prompt_cache_key grupperar cache per 'projekt' på serversidan.
    Håll den stabil och kort.
    """
    project_id = (cfg.get("project_id") or "").strip()
    if not project_id:
        # fallback: hash av absolut sökväg (maskinspecifikt men stabilt lokalt)
        project_id = _sha256_short(str(project_root.resolve()), 10)
    return f"cleaner2:{project_id}:{model_id}"


# ---------- Semantisk cache (valfritt) ----------
@dataclass
class SemanticCacheConfig:
    enabled: bool = False
    embedding_model: str = "text-embedding-3-small"
    threshold: float = 0.92
    max_items: int = 500


def load_semantic_cache() -> List[Dict[str, Any]]:
    data = load_json(SEMANTIC_CACHE_FILE, default=[])
    if not isinstance(data, list):
        return []
    return data


def save_semantic_cache(items: List[Dict[str, Any]]) -> None:
    save_json(SEMANTIC_CACHE_FILE, items)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def get_embedding(client: OpenAI, text: str, model: str) -> Optional[List[float]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        resp = client.embeddings.create(
            model=model,
            input=text,
        )
        return list(resp.data[0].embedding)
    except Exception as e:
        print(_c(f"⚠️  Embedding misslyckades: {e}", ANSI_YELLOW))
        return None


def semantic_cache_lookup(
    client: OpenAI,
    cfg: SemanticCacheConfig,
    project_fingerprint: str,
    raw_prompt: str,
) -> Optional[Tuple[str, float]]:
    """
    Returnerar (cached_cleaned_prompt, similarity) om vi hittar en tillräckligt lik match.
    Notera: detta gör en embeddings-call (billig) men kan spara en hel LLM-call.
    """
    items = load_semantic_cache()
    if not items:
        return None

    q_emb = get_embedding(client, raw_prompt, cfg.embedding_model)
    if q_emb is None:
        return None

    best_sim = -1.0
    best_item: Optional[Dict[str, Any]] = None

    for it in items[-cfg.max_items:]:
        if not isinstance(it, dict):
            continue
        if it.get("project_fingerprint") != project_fingerprint:
            continue
        emb = it.get("embedding")
        if not isinstance(emb, list) or not emb:
            continue
        try:
            sim = cosine_similarity(q_emb, [float(x) for x in emb])
        except Exception:
            continue
        if sim > best_sim:
            best_sim = sim
            best_item = it

    if best_item and best_sim >= cfg.threshold:
        cleaned = str(best_item.get("cleaned_prompt") or "").strip()
        if cleaned:
            return cleaned, float(best_sim)

    return None


def semantic_cache_store(
    client: OpenAI,
    cfg: SemanticCacheConfig,
    project_fingerprint: str,
    raw_prompt: str,
    cleaned_prompt: str,
) -> None:
    if not cfg.enabled:
        return
    emb = get_embedding(client, raw_prompt, cfg.embedding_model)
    if emb is None:
        return

    items = load_semantic_cache()
    items.append(
        {
            "ts": int(time.time()),
            "project_fingerprint": project_fingerprint,
            "embedding_model": cfg.embedding_model,
            "embedding": emb,
            "raw_prompt": raw_prompt[:5000],
            "cleaned_prompt": cleaned_prompt[:15000],
        }
    )

    # prune
    if len(items) > cfg.max_items:
        items = items[-cfg.max_items :]

    save_semantic_cache(items)


# ---------- Interaktiv config ----------
def configure_project() -> None:
    cfg = load_config()

    def ask(key: str, label: str, allow_empty: bool, multiline: bool) -> str:
        current = str(cfg.get(key, "") or "")
        print("\n" + _c(label, ANSI_CYAN))
        if current:
            print(_c(f"(nuvarande) {current}", ANSI_GRAY))
        if multiline:
            print(_c("Skriv flera rader. Avsluta med en tom rad.", ANSI_GRAY))
            lines: List[str] = []
            while True:
                line = input()
                if line.strip() == "":
                    break
                lines.append(line)
            value = "\n".join(lines).strip()
        else:
            value = input("> ").strip()

        if value:
            cfg[key] = value
        elif not value and current:
            # behåll
            pass
        elif not value and not allow_empty:
            print(_c("Värde krävs, försök igen.", ANSI_YELLOW))
            return ask(key, label, allow_empty, multiline)
        return str(cfg.get(key, "") or "")

    print(_c("\n=== Konfiguration (.cleaner) ===", ANSI_CYAN))
    print(f"Projektrot (auto): {PROJECT_ROOT}")
    print(f".cleaner:          {CLEANER_DIR}")

    ask("project_id", "Projekt-id (valfritt, stabilt id för cache-key; ex: mitt-projekt):", allow_empty=True, multiline=False)
    ask("project_name", "Projekt-namn (valfritt):", allow_empty=True, multiline=False)
    ask("tech_stack", "Tech stack (valfritt):", allow_empty=True, multiline=False)
    ask("language_mode", "Language mode (sv_to_en / en / etc) (valfritt):", allow_empty=True, multiline=False)

    # instruktioner
    print("\nInstruktionsfiler (relativt projektrot eller absolut).")
    print("Lämna tomt för auto-discovery i .cleaner/.")
    print("Skriv flera rader. Avsluta med tom rad.")
    lines: List[str] = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line.strip())
    if lines:
        cfg["instruction_files"] = lines
    else:
        cfg.pop("instruction_files", None)

    # semantisk cache
    print("\nSemantisk cache (embeddings) – valfritt:")
    cur_enabled = bool(cfg.get("semantic_cache_enabled", False))
    print(_c(f"(nuvarande) enabled={cur_enabled}", ANSI_GRAY))
    yn = input("Aktivera semantisk cache? [y/N]: ").strip().lower()
    if yn in {"y", "yes", "j", "ja"}:
        cfg["semantic_cache_enabled"] = True
    elif yn in {"n", "no", "nej"}:
        cfg["semantic_cache_enabled"] = False

    save_config(cfg)
    print(_c("\n✅ Sparade config i .cleaner.\n", ANSI_GREEN))


# ---------- CLI input helpers ----------
def read_multiline_input() -> str:
    print(_c("Klistra in din råa prompt. Avsluta med en tom rad (eller Ctrl+Z + Enter i Windows).", ANSI_GRAY))
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def choose_model(cli_choice: Optional[str]) -> str:
    if cli_choice in MODEL_MAP:
        return MODEL_MAP[cli_choice]

    print("Välj modell:")
    print("  [1] chat     = gpt-5.2-chat-latest (snabb, ofta bra för prompt-tvätt)")
    print("  [2] standard = gpt-5.2 (balans)")
    print("  [3] pro      = gpt-5.2-pro (dyrast, bäst reasoning)")
    choice = input("Val [1]: ").strip() or "1"

    if choice == "1":
        return MODEL_MAP["chat"]
    if choice == "3":
        return MODEL_MAP["pro"]
    return MODEL_MAP["standard"]


def add_cursor_reply_to_history() -> None:
    print(_c("Klistra in Cursor-svaret. Avsluta med en tom rad.", ANSI_GRAY))
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        lines.append(line)
    txt = "\n".join(lines).strip()
    if not txt:
        print(_c("Inget innehåll, sparar inget.", ANSI_YELLOW))
        return
    add_history_item("cursor_reply", txt)
    print(_c("✅ Cursor-svar sparat i historiken.\n", ANSI_GREEN))


# ---------- Kärnlogik: tvätta prompt ----------
def wash_prompt(
    model_id: str,
    raw_prompt: str,
    *,
    service_tier: Optional[str],
    max_output_tokens: int,
    use_extended_prompt_cache: bool,
    semantic_cache_override: Optional[bool],
) -> str:
    client = OpenAI()

    cfg = load_config()
    history = load_history(max_items=80)
    history_summary = summarize_history_for_context(history)

    # tree / docs
    precomputed = load_precomputed_tree(CLEANER_DIR)
    if precomputed:
        project_tree = precomputed
    else:
        project_tree = get_project_tree(PROJECT_ROOT)

    instr_text = read_instruction_files(cfg, PROJECT_ROOT, CLEANER_DIR)
    focus_files = detect_focus_files(raw_prompt, PROJECT_ROOT)

    static_instructions = build_static_instructions(cfg)
    static_context = build_context_blocks(project_tree=project_tree, instructions_text=instr_text)
    variable_tail = build_variable_tail(history_summary=history_summary, focus_files=focus_files, raw_prompt=raw_prompt)

    # semantisk cache config
    sem_cfg = SemanticCacheConfig(
        enabled=bool(cfg.get("semantic_cache_enabled", False)),
        embedding_model=str(cfg.get("semantic_cache_embedding_model", "text-embedding-3-small")),
        threshold=float(cfg.get("semantic_cache_threshold", 0.92)),
        max_items=int(cfg.get("semantic_cache_max_items", 500)),
    )
    if semantic_cache_override is not None:
        sem_cfg.enabled = bool(semantic_cache_override)

    project_fingerprint = compute_project_fingerprint(static_context)

    if sem_cfg.enabled:
        hit = semantic_cache_lookup(
            client=client,
            cfg=sem_cfg,
            project_fingerprint=project_fingerprint,
            raw_prompt=raw_prompt,
        )
        if hit is not None:
            cleaned, sim = hit
            print(_c(f"✅ Semantisk cache-hit (similarity={sim:.3f}) – ingen LLM-call behövdes.\n", ANSI_GREEN))
            add_history_item("user_raw", raw_prompt)
            add_history_item("cleaned_prompt", cleaned)
            return cleaned

    # prompt caching params
    request_kwargs: Dict[str, Any] = {
        "model": model_id,
        "instructions": static_instructions,
        "input": f"{static_context}\n\n{variable_tail}",
        "temperature": 0.2,
        "max_output_tokens": max_output_tokens,
    }

    # service tier (kan saknas i vissa SDK-versioner)
    if service_tier:
        request_kwargs["service_tier"] = service_tier

    # prompt_cache_key / retention (Responses API)
    # prompt_cache_retention="24h" aktiverar extended retention (upp till 24h) för modeller som stöder det.
    prompt_cache_key = compute_prompt_cache_key(cfg, model_id, PROJECT_ROOT)
    request_kwargs["prompt_cache_key"] = prompt_cache_key

    if use_extended_prompt_cache and model_id in EXTENDED_CACHE_SUPPORTED:
        request_kwargs["prompt_cache_retention"] = "24h"

    add_history_item("user_raw", raw_prompt)

    # call
    try:
        resp = client.responses.create(**request_kwargs)
    except TypeError:
        # om service_tier/prompt_cache_* inte stöds i just din SDK-version
        fallback_kwargs = dict(request_kwargs)
        fallback_kwargs.pop("service_tier", None)
        fallback_kwargs.pop("prompt_cache_key", None)
        fallback_kwargs.pop("prompt_cache_retention", None)
        resp = client.responses.create(**fallback_kwargs)

    cleaned = (getattr(resp, "output_text", None) or "").strip()
    if not cleaned:
        # fallback: försöka plocka ut text på flera sätt
        try:
            cleaned = str(resp.output[0].content[0].text).strip()  # type: ignore
        except Exception:
            cleaned = ""

    if not cleaned:
        raise RuntimeError("Fick tomt svar från modellen.")

    add_history_item("cleaned_prompt", cleaned)

    # store semantic cache
    if sem_cfg.enabled:
        semantic_cache_store(
            client=client,
            cfg=sem_cfg,
            project_fingerprint=project_fingerprint,
            raw_prompt=raw_prompt,
            cleaned_prompt=cleaned,
        )

    # report
    print_token_report(model_id=model_id, resp=resp, requested_service_tier=service_tier)

    # hint for caching
    try:
        usage = getattr(resp, "usage", None)
        usage_d = usage if isinstance(usage, dict) else getattr(usage, "model_dump", lambda: {})()
        cached = _safe_int((usage_d.get("input_tokens_details") or {}).get("cached_tokens")) if isinstance(usage_d, dict) else 0
        if cached:
            print(_c("✅ Prompt caching: cached_tokens > 0", ANSI_GREEN))
        else:
            print(
                _c(
                    "ℹ️  Prompt caching: cached_tokens=0 (förvänta dig bättre efter 2:a körningen om prefixet är stabilt).",
                    ANSI_GRAY,
                )
            )
    except Exception:
        pass

    return cleaned


# ---------- main ----------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="cleaner2_v2.py – tvättar prompts innan de skickas till Cursor + optimerar caching."
    )
    parser.add_argument("--config", action="store_true", help="Konfigurera .cleaner (project_id, docs, cache m.m.)")
    parser.add_argument("--add-reply", action="store_true", help="Lägg till ett Cursor-svar i historiken (multiline).")
    parser.add_argument("--show-tree", action="store_true", help="Visa tree som kommer användas (först .cleaner, sen auto).")
    parser.add_argument("--clear-history", action="store_true", help="Rensa historikfilen i .cleaner.")
    parser.add_argument("--clear-semantic-cache", action="store_true", help="Rensa semantiska cache-filen i .cleaner.")

    parser.add_argument("--model", choices=list(MODEL_MAP.keys()), help="Välj modell: chat / standard / pro")
    parser.add_argument("--service-tier", default="auto", help="API service_tier (auto/default/priority/... om din org stödjer).")
    parser.add_argument("--max-output-tokens", type=int, default=900, help="Max output tokens från preprompt-modellen.")
    parser.add_argument(
        "--extended-prompt-cache",
        action="store_true",
        help='Aktivera prompt_cache_retention="24h" (extended) för modeller som stöder det.',
    )
    parser.add_argument("--semantic-cache", action="store_true", help="Aktivera semantisk cache för denna körning.")
    parser.add_argument("--no-semantic-cache", action="store_true", help="Stäng av semantisk cache för denna körning.")

    args = parser.parse_args()

    print(_c(f"Projektrot: {PROJECT_ROOT}", ANSI_GRAY))
    print(_c(f".cleaner:  {CLEANER_DIR}", ANSI_GRAY))

    if args.clear_history:
        save_history([])
        print(_c("✅ Historik rensad.\n", ANSI_GREEN))
        return

    if args.clear_semantic_cache:
        save_semantic_cache([])
        print(_c("✅ Semantisk cache rensad.\n", ANSI_GREEN))
        return

    if args.config:
        configure_project()
        return

    if args.add_reply:
        add_cursor_reply_to_history()
        return

    if args.show_tree:
        pre = load_precomputed_tree(CLEANER_DIR)
        if pre:
            print(_c("\n--- TREE (från .cleaner) ---\n", ANSI_CYAN))
            print(pre)
        else:
            print(_c("\n--- TREE (auto) ---\n", ANSI_CYAN))
            print(get_project_tree(PROJECT_ROOT))
        print()
        return

    model_id = choose_model(args.model)
    print(_c(f"\nAnvänder modell: {model_id}\n", ANSI_CYAN))

    raw = read_multiline_input()
    if not raw.strip():
        print(_c("Ingen input. Avslutar.", ANSI_YELLOW))
        return

    semantic_override: Optional[bool] = None
    if args.semantic_cache and args.no_semantic_cache:
        print(_c("⚠️  Du angav både --semantic-cache och --no-semantic-cache. Jag kör utan semantic cache.", ANSI_YELLOW))
        semantic_override = False
    elif args.semantic_cache:
        semantic_override = True
    elif args.no_semantic_cache:
        semantic_override = False

    cleaned = wash_prompt(
        model_id=model_id,
        raw_prompt=raw,
        service_tier=str(args.service_tier or "").strip() or None,
        max_output_tokens=int(args.max_output_tokens),
        use_extended_prompt_cache=bool(args.extended_prompt_cache),
        semantic_cache_override=semantic_override,
    )

    print("\n--- TVÄTTAD PROMPT (klistra in i Cursor-chatten) ---\n")
    print(cleaned)
    print("\n----------------------------------------------------\n")


if __name__ == "__main__":
    main()