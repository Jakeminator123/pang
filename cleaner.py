from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import List, Dict, Any, Optional

from openai import OpenAI

# === Paths och globala saker ===

THIS_FILE = Path(__file__).resolve()
DEFAULT_ROOT = THIS_FILE.parent  # fallback om projektrot inte är satt
CONFIG_FILE = THIS_FILE.with_name(".preprompt_config.json")
HISTORY_FILE = THIS_FILE.with_name(".preprompt_history.json")

client = OpenAI()  # använder OPENAI_API_KEY från miljön


# === Små hjälp-funktioner för JSON-filer ===

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# === Konfiguration (projektrot, instruktioner, språk mm) ===

def load_config() -> Dict[str, Any]:
    cfg = load_json(CONFIG_FILE, default={})
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    save_json(CONFIG_FILE, cfg)


def get_project_root(cfg: Dict[str, Any]) -> Path:
    """
    Hämta projektrot. Om inget är satt -> mappen där skriptet ligger.
    """
    root_str = cfg.get("project_root", "").strip()
    if root_str:
        p = Path(root_str).expanduser()
        return p
    return DEFAULT_ROOT


def configure_project() -> None:
    """
    Interaktiv konfiguration:
    - projektrot
    - projekt-namn, beskrivning, tech stack, mål
    - nyckelkataloger
    - instruktionsfiler
    - språk-läge
    """
    print("=== Projektkonfiguration för preprompt ===")
    cfg = load_config()

    def ask(key: str, label: str, allow_empty: bool = True, multiline: bool = False) -> str:
        current = cfg.get(key, "")
        print()
        print(label)
        if current:
            print(f"(Nuvarande värde: {current})")
        if multiline:
            print("Skriv din text. Avsluta med tom rad.")
            lines = []
            while True:
                line = input("> ")
                if line.strip() == "":
                    break
                lines.append(line)
            value = "\n".join(lines).strip()
        else:
            value = input("> ").strip()

        if value:
            cfg[key] = value
        elif not value and not current and not allow_empty:
            print("Värde krävs, försök igen.")
            return ask(key, label, allow_empty, multiline)
        return cfg.get(key, "")

    print("\nVar ligger projektroten?")
    print("Lämna tomt för att använda mappen där detta skript ligger:")
    print(f"  {DEFAULT_ROOT}")
    ask("project_root", "Projektrot (absolut sökväg, eller tom för standard):", allow_empty=True, multiline=False)

    ask("project_name", "Projekt-namn (valfritt):", allow_empty=True, multiline=False)
    ask("project_description", "Kort projektbeskrivning (valfritt):", allow_empty=True, multiline=True)
    ask("tech_stack", "Teknisk stack (t.ex. React, TS, Python-backend) (valfritt):", allow_empty=True, multiline=False)
    ask("main_goals", "Huvudmål/syfte (kodkvalitet, performance, mm) (valfritt):", allow_empty=True, multiline=True)

    print("\nNyckelkataloger i projektet (relativt projektroten, komma-separerade).")
    print("Exempel: src, src/components, backend")
    dirs_str = input("> ").strip()
    if dirs_str:
        cfg["key_directories"] = [d.strip() for d in dirs_str.split(",") if d.strip()]

    print("\nInstruktionsfiler (relativa paths från projektroten, komma-separerade).")
    print("Exempel: README.md, docs/architecture.md, docs/GOALS.md")
    instr_str = input("> ").strip()
    if instr_str:
        cfg["instruction_files"] = [p.strip() for p in instr_str.split(",") if p.strip()]

    print("\nSpråk-läge:")
    print("  sv_to_en = du skriver ofta på svenska, prompten ska bli teknisk engelska.")
    print("  en_only  = du skriver på engelska, prompten blir teknisk engelska.")
    lang = input("Välj [sv_to_en/en_only] (default sv_to_en): ").strip().lower() or "sv_to_en"
    if lang not in {"sv_to_en", "en_only"}:
        lang = "sv_to_en"
    cfg["language_mode"] = lang

    save_config(cfg)
    print("\n✅ Konfiguration sparad i", CONFIG_FILE)


# === Historik (råfrågor, tvättade prompts, Cursor-svar) ===

def load_history(max_items: Optional[int] = None) -> List[Dict[str, Any]]:
    hist = load_json(HISTORY_FILE, default=[])
    if not isinstance(hist, list):
        hist = []
    if max_items is not None and len(hist) > max_items:
        hist = hist[-max_items:]
    return hist


def save_history(history: List[Dict[str, Any]]) -> None:
    save_json(HISTORY_FILE, history)


def add_history_item(role: str, content: str) -> None:
    history = load_history()
    history.append({"role": role, "content": content})
    # hård cap
    if len(history) > 80:
        history = history[-80:]
    save_history(history)


def summarize_history_for_context(history: List[Dict[str, Any]], max_items: int = 8) -> str:
    """
    Gör en enkel text-sammanfattning (trunkera) av senaste historiken.
    Ingen magi, bara tillräckligt för att modellen ska se vad vi håller på med.
    """
    if not history:
        return ""
    items = history[-max_items:]
    lines: List[str] = []
    for item in items:
        role = item.get("role", "unknown").upper()
        content = (item.get("content") or "").strip().replace("\n", " ")
        if len(content) > 220:
            content = content[:220] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


# === Projektträd & instruktionsfiler ===

def get_project_tree(root: Path, max_chars: int = 2000, max_depth: int = 2) -> str:
    lines: List[str] = []

    def walk(base: Path, depth: int = 0):
        if depth > max_depth:
            return
        try:
            entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name in {".git", "node_modules", ".venv", "__pycache__", ".idea", ".vscode"}:
                continue
            indent = "  " * depth
            if entry.is_dir():
                lines.append(f"{indent}/{entry.name}/")
                if sum(len(l) for l in lines) < max_chars:
                    walk(entry, depth + 1)
            else:
                lines.append(f"{indent}{entry.name}")
            if sum(len(l) for l in lines) >= max_chars:
                return

    walk(root)
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text


def read_instruction_files(cfg: Dict[str, Any], root: Path, max_chars: int = 4000) -> str:
    """
    Läs in "projektinstruktionsfiler" som du valt (README, docs osv).
    Vi tar små snippets för att hålla context nere.
    """
    files = cfg.get("instruction_files") or []
    chunks: List[str] = []
    for rel in files:
        p = (root / rel).resolve()
        if not p.exists() or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(text) > 1500:
            text = text[:1500] + "\n...[truncated]"
        chunks.append(f"### {rel}\n{text}")
        if sum(len(c) for c in chunks) >= max_chars:
            break
    return "\n\n".join(chunks)


# === Fokuserade filer: @filnamn från prompten ===

def detect_focus_files(raw_prompt: str, root: Path) -> List[str]:
    """
    Plocka ut tokens som ser ut som filer/paths (eller är @-prefixade),
    och kolla om de faktiskt finns under projektroten.
    Returnerar relativa paths (utan @), sorterade.
    """
    tokens = raw_prompt.replace("\n", " ").split()
    candidates = set()
    for t in tokens:
        clean = t.strip(",.;:()[]{}")
        # ta bort @ om användaren redan skrivit det
        if clean.startswith("@"):
            clean = clean[1:]
        # skippa URLs
        if any(clean.startswith(prefix) for prefix in ("http://", "https://")):
            continue
        # enkel heuristik: det finns en punkt => troligen fil
        if "." in clean and not clean.startswith("-"):
            candidates.add(clean)

    focus_paths: List[str] = []
    seen = set()
    for c in candidates:
        p = (root / c).resolve()
        if p.exists():
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            rel_str = str(rel).replace("\\", "/")
            if rel_str not in seen:
                seen.add(rel_str)
                focus_paths.append(rel_str)
    return sorted(focus_paths)


# === Systeminstruktion till modellen ===

def build_system_instructions(
    cfg: Dict[str, Any],
    project_tree: str,
    instructions_text: str,
    history_summary: str,
    focus_files: List[str],
) -> str:
    project_name = cfg.get("project_name") or "(okänt projekt)"
    project_description = cfg.get("project_description") or ""
    tech_stack = cfg.get("tech_stack") or ""
    main_goals = cfg.get("main_goals") or ""
    key_dirs = cfg.get("key_directories") or []
    language_mode = cfg.get("language_mode", "sv_to_en")

    key_dirs_str = ", ".join(key_dirs) if key_dirs else "(inte specificerat)"

    if language_mode == "sv_to_en":
        lang_block = """
        - The user often writes in Swedish (sometimes with typos or slang).
        - You MUST output the final prompt in clear, technical English.
        - Preserve the user's intent and general tone when possible (direct, informal is fine),
          but make the instruction unambiguous and professional enough for a coding assistant.
        - You may keep existing Swedish identifiers (function/variable names) if they already exist in the codebase.
        """
    else:
        lang_block = """
        - Assume the user writes in English and wants the final prompt in clear, technical English.
        - Preserve the user's intent and general tone when possible,
          but make the instruction unambiguous and professional enough for a coding assistant.
        """

    if focus_files:
        focus_block = "\n".join(f"@{path}" for path in focus_files)
        focus_section = f"[FOCUS FILES]\n{focus_block}\n"
    else:
        focus_section = "[FOCUS FILES]\n(none explicitly detected)\n"

    instr_section = instructions_text or "(no dedicated instruction files configured)"
    history_section = history_summary or "(no recent history)"

    return textwrap.dedent(f"""
    You are a "prompt pre-processor" that prepares high-quality prompts for a coding assistant inside the Cursor editor.

    Your ONLY task:
    - Take the user's raw question or instruction (possibly in Swedish and messy).
    - Transform it into ONE single, clean, well-structured English prompt that is ideal for a coding/code-refactoring assistant working on this specific project.
    - The user will paste your output directly into Cursor. You must NEVER answer the coding question yourself.

    --- PROJECT METADATA ---
    Name: {project_name}
    Description: {project_description}
    Tech stack: {tech_stack}
    Main goals / priorities: {main_goals}
    Key directories: {key_dirs_str}

    --- PROJECT TREE (truncated) ---
    {project_tree}

    --- PROJECT INSTRUCTION FILES (snippets) ---
    {instr_section}

    --- RECENT Q/A SUMMARY ---
    {history_section}

    --- EXPLICIT FOCUS FILES FROM USER (@paths) ---
    {focus_section}

    --- LANGUAGE & STYLE RULES ---
    {lang_block}

    --- MAPPING USER LANGUAGE TO CODE ---
    - When the user refers to UI concepts or features in natural language (e.g. "about us modal",
      "settings page", "home screen", "poker diary", etc.), use the project tree and instruction
      files to infer which files and routes are most likely involved.
    - In the cleaned prompt, explicitly list these as candidate files using '@relative/path' notation
      under a short section like "Likely involved files".
    - It is OK to say things like "This likely involves @path1 and @path2" or
      "Most probably implemented around @path1". You do NOT need to be 100% certain, but you must
      make your best guess from the project tree and names.
    - If multiple files are plausible, list several candidates and let the coding assistant disambiguate.

    --- HOW TO FORMAT THE CLEANED PROMPT ---
    The cleaned prompt you output should be written as if it is directly addressed to a coding assistant
    running inside Cursor, for example:

      1) Start with a short, clear statement of the overall goal.
      2) Add a brief explanation of the context if the user's message suggests it.
      3) Add a section like "Likely involved files" where you reference relevant files with '@paths'
         (using your own reasoning from the project tree and the user's description, even if the
         user did not specify them explicitly).
      4) Then enumerate the requested work in bullet points or numbered steps.
      5) Mention constraints or expectations (performance, readability, styling, tests, etc.).
      6) If the work depends on previous issues or answers, connect briefly to them using the summary above.

    --- IMPORTANT ---
    - NEVER answer the user's coding question or perform the requested changes yourself.
    - NEVER mention this pre-processing step or that you are a "prompt washer".
    - Do NOT describe your reasoning process (no "I think", "I guess", or explanations of how you chose files).
    - Your output must be fully usable as a stand-alone instruction for the coding assistant.
    """)


# === Modellval ===

MODEL_MAP = {
    "chat": "gpt-5.2-chat-latest",
    "standard": "gpt-5.2",
    "pro": "gpt-5.2-pro",
}


def choose_model(cli_choice: Optional[str]) -> str:
    if cli_choice in MODEL_MAP:
        return MODEL_MAP[cli_choice]

    print("Välj 5.2-modell:")
    print("  [1] chat     = gpt-5.2-chat-latest (snabb & billig, perfekt för prompt-tvätt)")
    print("  [2] standard = gpt-5.2 (balans, mer reasoning)")
    print("  [3] pro      = gpt-5.2-pro (max reasoning, dyrast)")
    choice = input("Val [1]: ").strip() or "1"

    if choice == "1":
        return MODEL_MAP["chat"]
    elif choice == "3":
        return MODEL_MAP["pro"]
    else:
        return MODEL_MAP["standard"]


# === Input för rå fråga ===

def read_multiline_input() -> str:
    print("Skriv din fråga/instruktion till Cursor (slarvig går bra).")
    print("Du kan skriva flera rader. Avsluta med tom rad.\n")
    lines: List[str] = []
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if line.strip() == "":
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    if not text:
        print("Ingen text angavs, avbryter.")
        sys.exit(0)
    return text


# === Kärnfunktion: tvätta prompt ===

def wash_prompt(model_id: str, raw_prompt: str) -> str:
    cfg = load_config()
    root = get_project_root(cfg)

    history = load_history(max_items=40)
    history_summary = summarize_history_for_context(history)

    project_tree = get_project_tree(root)
    instr_text = read_instruction_files(cfg, root)
    focus_files = detect_focus_files(raw_prompt, root)

    system_instructions = build_system_instructions(
        cfg=cfg,
        project_tree=project_tree,
        instructions_text=instr_text,
        history_summary=history_summary,
        focus_files=focus_files,
    )

    add_history_item("user_raw", raw_prompt)

    try:
        response = client.responses.create(
            model=model_id,
            instructions=system_instructions,
            input=raw_prompt,
            temperature=0.2,
            max_output_tokens=1000,
        )
    except Exception as e:
        print("\n❌ Fel vid anrop till OpenAI API:")
        print(e)
        sys.exit(1)

    cleaned = (response.output_text or "").strip()
    if not cleaned:
        print("\n❌ Tomt svar från modellen.")
        sys.exit(1)

    add_history_item("washed_prompt", cleaned)
    return cleaned


# === Lägg till Cursor-svar i historiken ===

def add_reply_from_cursor() -> None:
    print("Klistra in Cursor-svaret nedan.")
    print("Avsluta med Ctrl+Z + Enter (Windows) för att skicka in.\n")

    chunks: List[str] = []
    try:
        while True:
            line = input()
            chunks.append(line)
    except EOFError:
        pass

    text = "\n".join(chunks).strip()
    if not text:
        print("Inget innehåll, ingen historik uppdaterad.")
        return

    add_history_item("cursor_reply", text)
    print("\n✅ Cursor-svar sparat i historiken.\n")


# === main() ===

def main():
    parser = argparse.ArgumentParser(
        description="preprompt.py – tvättar prompts innan de skickas till Cursor."
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Konfigurera projektrot, mål, instruktionsfiler m.m.",
    )
    parser.add_argument(
        "--add-reply",
        action="store_true",
        help="Lägg till ett Cursor-svar i historiken (klistra in från terminalen).",
    )
    parser.add_argument(
        "--model",
        choices=["chat", "standard", "pro"],
        help="Välj 5.2-modell: chat, standard eller pro.",
    )
    args = parser.parse_args()

    if args.config:
        configure_project()
        return

    if args.add_reply:
        add_reply_from_cursor()
        return

    cfg = load_config()
    root = get_project_root(cfg)
    print("=== preprompt.py ===")
    print(f"Projektrot: {root}")
    if cfg.get("project_name"):
        print(f"Projekt:   {cfg.get('project_name')}")
    print()

    model_id = choose_model(args.model)
    print(f"Använder modell: {model_id}\n")

    raw = read_multiline_input()
    cleaned = wash_prompt(model_id, raw)

    print("\n--- TVÄTTAD PROMPT (klistra in i Cursor-chatten) ---\n")
    print(cleaned)
    print("\n----------------------------------------------------\n")


if __name__ == "__main__":
    main()
