#!/usr/bin/env python3
"""
AssistBot+ — Cooler colors, visible ANSI fallback, and a sleeker prompt.

Single-file assistant shell. Optional dependency: `rich` for prettier output.
If `rich` is not installed, the script falls back to ANSI color codes with
clearly visible defaults.

Save as `assistbot_plus_cool.py` and run with Python 3.8+.
"""

import os
import sqlite3
import shlex
import subprocess
import random
import shutil
import difflib
import webbrowser
import importlib.util
import traceback
import json
import readline
import glob
import getpass
import atexit
from datetime import datetime, UTC
from concurrent.futures import ThreadPoolExecutor
import urllib.parse

# ---------------- Rich detection and unified printing ----------------
USE_RICH = False
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    console = Console()
    USE_RICH = True
except Exception:
    USE_RICH = False

# Define logical styles we'll use across the program
STYLE_KEYS = [
    "header", "cyan", "green", "gold", "red", "magenta", "bold", "muted", "warning"
]

# ANSI codes for fallback (visible, high-contrast)
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "header": "\033[95m",   # bright magenta
    "cyan": "\033[96m",     # bright cyan
    "green": "\033[92m",    # bright green
    "gold": "\033[93m",     # bright yellow (gold)
    "red": "\033[91m",      # bright red
    "magenta": "\033[35m",  # magenta (less bright fallback)
    "muted": "\033[90m",    # dark gray
    "warning": "\033[33m",  # yellow-ish
}

def p(text: str, style: str = None, end: str = "\n"):
    """
    Central print function.
    - If rich is available, prints with rich styles.
    - Otherwise emits ANSI sequences using the friendly ANSI mapping above.
    Acceptable style values: one of STYLE_KEYS or a space-separated combo like "bold green".
    """
    if USE_RICH:
        if style:
            console.print(text, style=style, end=end)
        else:
            console.print(text, end=end)
    else:
        if style:
            # support "bold green" combos
            parts = style.split()
            codes = ""
            for part in parts:
                codes += ANSI.get(part, "")
            print(f"{codes}{text}{ANSI['reset']}", end=end)
        else:
            print(text, end=end)

def pretty_table(columns, rows, title=None):
    """
    Nicely render tables using rich if available, otherwise a simple ASCII table.
    """
    if USE_RICH:
        t = Table(title=title) if title else Table()
        for c in columns:
            t.add_column(str(c))
        for r in rows:
            # pad row to column count
            rpad = [str(r[i]) if i < len(r) else "" for i in range(len(columns))]
            t.add_row(*rpad)
        console.print(t)
    else:
        if title:
            p(title, style="bold header")
            p("-" * max(len(title), 20), style="muted")
        if not rows:
            p(" | ".join(columns), style="bold")
            return
        # compute widths
        colwidths = []
        for i, c in enumerate(columns):
            maxw = len(str(c))
            for r in rows:
                if i < len(r):
                    maxw = max(maxw, len(str(r[i])))
            colwidths.append(maxw)
        header = " | ".join(columns[i].ljust(colwidths[i]) for i in range(len(columns)))
        p(header, style="bold")
        p("-" * len(header), style="muted")
        for r in rows:
            line = " | ".join(str(r[i]).ljust(colwidths[i]) if i < len(r) else "".ljust(colwidths[i])
                              for i in range(len(columns)))
            p(line)

# ---------------- AssistBotPlus core ----------------
class AssistBotPlus:
    DB_FILE = "assistbot_plus.db"
    PLUGINS_DIR = "plugins"
    PROMPT_TEMPLATE_SHORT = "{header}{user}{reset}{at}{time}{reset}{sep}{path}{reset}\n{arrow} "
    # blocked substrings to prevent catastrophic commands
    BLOCKED_PATTERNS = [
        "rm -rf", "rm -rf /", "mkfs", ":(){:|:&};:", "dd if=",
        ">/dev", ">: /dev", "sudo rm", "chmod 000", "halt", "reboot", "poweroff"
    ]

    def __init__(self):
        # identity
        try:
            self.user = getpass.getuser()
        except Exception:
            self.user = os.environ.get("USER", "user")

        self.cwd = os.getcwd()
        self.db = sqlite3.connect(self.DB_FILE, check_same_thread=False)
        self.cursor = self.db.cursor()
        self._setup_db()
        self._load_mappings()
        self._load_knowledge()

        # plugins
        self.plugins = {}
        self._load_plugins()

        # readline + history
        self._setup_readline()

        # threadpool for background tasks if needed
        self.executor = ThreadPoolExecutor(max_workers=2)

        # show a cool banner
        self._print_banner()

    # ---------------- DB ----------------
    def _setup_db(self):
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS commands (key TEXT PRIMARY KEY, template TEXT, meta TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS brain (key TEXT PRIMARY KEY, responses TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS history (ts TEXT, entry TEXT)"
        )
        self.db.commit()

    def _load_mappings(self):
        self.cursor.execute("SELECT key, template FROM commands")
        self.mappings = {r[0]: r[1] for r in self.cursor.fetchall()}

    def _load_knowledge(self):
        self.cursor.execute("SELECT key, responses FROM brain")
        self.knowledge = {r[0]: r[1] for r in self.cursor.fetchall()}

    def _save_mapping(self, key, template):
        meta = json.dumps({"created": datetime.utcnow().isoformat()})
        self.cursor.execute("REPLACE INTO commands (key, template, meta) VALUES (?, ?, ?)", (key, template, meta))
        self.db.commit()
        self.mappings[key] = template

    def _delete_mapping(self, key):
        self.cursor.execute("DELETE FROM commands WHERE key=?", (key,))
        self.db.commit()
        self.mappings.pop(key, None)

    def _save_brain(self, key, responses):
        text = "|".join(responses) if isinstance(responses, (list, tuple)) else responses
        self.cursor.execute("REPLACE INTO brain (key, responses) VALUES (?, ?)", (key, text))
        self.db.commit()
        self.knowledge[key] = text

    def _delete_brain(self, key):
        self.cursor.execute("DELETE FROM brain WHERE key=?", (key,))
        self.db.commit()
        self.knowledge.pop(key, None)

    def add_history(self, entry):
        ts = datetime.now(UTC).isoformat()
        self.cursor.execute("INSERT INTO history VALUES (?, ?)", (ts, entry))
        self.db.commit()

    # ---------------- Plugins ----------------
    def _load_plugins(self):
        os.makedirs(self.PLUGINS_DIR, exist_ok=True)
        for path in glob.glob(os.path.join(self.PLUGINS_DIR, "*.py")):
            name = os.path.splitext(os.path.basename(path))[0]
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.plugins[name] = mod
                p(f"[PLUGIN] Loaded: {name}", style="cyan")
            except Exception:
                p(f"[PLUGIN] Failed to load {name}: {traceback.format_exc()}", style="red")

    # ---------------- Readline / Completion ----------------
    def _setup_readline(self):
        histfile = os.path.expanduser("~/.assistbot_plus_history")
        try:
            readline.read_history_file(histfile)
        except Exception:
            pass
        atexit.register(lambda: readline.write_history_file(histfile))

        self._completions_cache = None
        readline.set_completer(self._completer)
        try:
            readline.parse_and_bind("tab: complete")
        except Exception:
            # some platforms may not support parse_and_bind
            pass

    def _completer(self, text, state):
        if state == 0:
            builtins = [
                "help", "sys", "search", "maps", "brain", "memo",
                "exit", "quit", "clear", "cd", "exec", "shell",
                "unmap", "forget", ".map", ".teach", "map"
            ]
            keys = list(self.mappings.keys()) + list(self.knowledge.keys()) + builtins
            try:
                if text and (os.path.isdir(text) or "/" in text or text.startswith(".")):
                    dirname = os.path.dirname(text) or "."
                    prefix = os.path.basename(text)
                    try:
                        files = [f for f in os.listdir(dirname) if f.startswith(prefix)]
                        keys += [os.path.join(dirname, f) for f in files]
                    except Exception:
                        pass
            except Exception:
                pass
            self._completions_cache = sorted(set(keys))
        options = [c for c in self._completions_cache if c.startswith(text)]
        try:
            return options[state]
        except IndexError:
            return None

    # ---------------- Helpers ----------------
    def prompt_short(self):
        """
        Returns a short colorful prompt string for input().
        Uses ANSI when rich is not available. When rich is available, we will use console.input.
        """
        user = self.user
        time = datetime.now().strftime("%H:%M")
        path = self.cwd.replace(os.path.expanduser("~"), "~")
        # compose color pieces for ANSI fallback
        if USE_RICH:
            # rich handles styling at input time via console.input which accepts markup in some contexts.
            header = f"[bold magenta]ASSIST[/bold magenta] "
            user_part = f"[bold cyan]{user}[/bold cyan]"
            at = " @ "
            time_part = f"[bold green]{time}[/bold green]"
            sep = f" [{path}]"
            arrow = "[bold green]λ[/bold green]"
            return f"{header}{user_part}{at}{time_part}{sep}\n{arrow} "
        else:
            header = f"{ANSI['header']}{ANSI['bold']}ASSIST{ANSI['reset']} "
            user_part = f"{ANSI['cyan']}{ANSI['bold']}{user}{ANSI['reset']}"
            at = " @ "
            time_part = f"{ANSI['green']}{ANSI['bold']}{time}{ANSI['reset']}"
            sep = f" {ANSI['gold']}{path}{ANSI['reset']}"
            arrow = f"{ANSI['green']}{ANSI['bold']}λ{ANSI['reset']}"
            return f"{header}{user_part}{at}{time_part}{sep}\n{arrow} "

    @staticmethod
    def _is_blocked(cmd_text):
        if not cmd_text:
            return False, None
        lower = cmd_text.lower()
        for patt in AssistBotPlus.BLOCKED_PATTERNS:
            if patt in lower:
                return True, patt
        return False, None

    def fuzzy_match(self, word):
        pool = list(self.mappings.keys()) + list(self.knowledge.keys())
        matches = difflib.get_close_matches(word, pool, n=1, cutoff=0.6)
        return matches[0] if matches else None

    # ---------------- Expand & Execute ----------------
    def _expand_template(self, template, args):
        try:
            tokens = shlex.split(template)
        except Exception:
            tokens = template.split()

        final_tokens = []
        for tok in tokens:
            if "$*" in tok:
                if tok == "$*":
                    final_tokens.extend(args)
                    continue
                else:
                    tok = tok.replace("$*", " ".join(args))
            if "$@" in tok:
                tok = tok.replace("$@", " ".join(shlex.quote(a) for a in args))
            for i, a in enumerate(args):
                tok = tok.replace(f"${i+1}", a)
                tok = tok.replace("${%d}" % (i+1), a)
            final_tokens.append(tok)
        return final_tokens

    def execute_mapped(self, template, args, dry=False):
        blocked, patt = self._is_blocked(template)
        if blocked:
            p(f"[SECURITY] Refused to run command containing blocked pattern: {patt}", style="red")
            return None

        tokens = self._expand_template(template, args)
        if not tokens:
            p("[EXEC] Nothing to run after expansion.", style="warning")
            return None

        if dry:
            p("[DRY] expanded -> " + " ".join(shlex.quote(t) for t in tokens), style="warning")
            return None

        try:
            p(f"[EXEC] Running: {tokens[0]} {' '.join(shlex.quote(t) for t in tokens[1:])}", style="green")
            cp = subprocess.run(tokens, check=False)
            return cp
        except FileNotFoundError:
            p("[EXEC] Command not found. Try shell form or map a full path.", style="red")
        except Exception as e:
            p(f"[EXEC] Execution failed: {e}", style="red")
            traceback.print_exc()

    def exec_shell(self, command_str):
        blocked, patt = self._is_blocked(command_str)
        if blocked:
            p(f"[SECURITY] Refused to run shell command containing blocked pattern: {patt}", style="red")
            return None
        p(f"[SHELL] Running via shell: {command_str}", style="warning")
        try:
            cp = subprocess.run(command_str, shell=True)
            return cp
        except Exception as e:
            p(f"[SHELL] Failed: {e}", style="red")
            traceback.print_exc()

    # ---------------- Builtins ----------------
    def cmd_help(self):
        help_text = """AssistBot+ — Cool mode enabled.

Core commands:
  help                 Show this help
  sys                  Show disk and load info
  search <query>       Open browser search
  .map key = template  Map a key to a command template (use $1, $2, $*, $@)
  .teach key = resp1|resp2  Teach bot responses (separate with |)
  maps                 List mapped commands
  map <key> [args...]  Run mapped command
  unmap <key>          Remove mapping
  brain                List brain keys
  <brain_key>          Print a stored response (randomly if multiple)
  exec <cmd> [args..]  Execute raw command (split like shell)
  shell <command str>  Run via shell (explicit, gated)
  memo                 Open the assistant DB with sqlite3 if available
  cd <path>            Change working directory
  clear                Clear screen
  exit / quit          Quit

Examples:
  .map greet = echo Hello $1
  .teach joke = Why did the chicken cross? | To get to the other side
  map greet Harsh
"""
        p(help_text, style="muted")

    def cmd_sys(self):
        try:
            total, used, free = shutil.disk_usage(self.cwd)
            load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
            p(f"[DISK] {used // (2**30)}GB used / {total // (2**30)}GB total", style="cyan")
            p(f"[LOAD] {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}", style="cyan")
        except Exception as e:
            p(f"[SYS] Info failed: {e}", style="red")

    def cmd_search(self, query):
        if not query:
            p("Usage: search <query>", style="warning")
            return
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        p(f"[WEB] Searching for: {query}", style="green")
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            p("[WEB] Could not open browser.", style="red")

    def cmd_maps(self):
        if not self.mappings:
            p("No mappings yet. Use: .map key = command", style="warning")
            return
        rows = [(k, self.mappings[k]) for k in sorted(self.mappings.keys())]
        pretty_table(["key", "template"], rows, title="Mappings")

    def cmd_brain(self):
        if not self.knowledge:
            p("Brain empty. Use: .teach key = resp1|resp2", style="warning")
            return
        rows = [(k, self.knowledge[k]) for k in sorted(self.knowledge.keys())]
        pretty_table(["key", "responses"], rows, title="Brain")

    def _print_banner(self):
        # A compact colored banner that looks "real" and cool
        banner_lines = [
            r"   ___    ____  ____  _____ ____  _   _ ",
            r"  / _ \  / ___|| __ )| ____|  _ \| \ | |",
            r" | | | | \___ \|  _ \|  _| | |_) |  \| |",
            r" | |_| |  ___) | |_) | |___|  _ <| |\  |",
            r"  \___/  |____/|____/|_____|_| \_\_| \_|",
        ]
        if USE_RICH:
            console.print(Panel("\n".join(banner_lines), title="[bold magenta]AssistBot+[/bold magenta]", subtitle="[bold cyan]Cool Mode[/bold cyan]"))
            p("Type 'help' to get started.", style="muted")
        else:
            p("\n".join(banner_lines), style="header")
            p(">>> AssistBot+ — Cool Mode (type 'help')", style="cyan")

    # ---------------- Main loop ----------------
    def run(self):
        p("Starting AssistBot+ — ready.", style="magenta")
        while True:
            try:
                prompt_str = self.prompt_short()
                if USE_RICH:
                    # console.input supports simple prompt strings (rich styles are applied by markup)
                    try:
                        raw = console.input(prompt_str)
                    except Exception:
                        raw = input(prompt_str.replace("[", "").replace("]", ""))
                else:
                    raw = input(prompt_str)
                if raw is None:
                    break
                line = raw.strip()
                if not line:
                    continue

                # save history (best-effort)
                try:
                    self.add_history(line)
                except Exception:
                    pass

                # dotted meta commands
                if line.startswith("."):
                    if " = " in line:
                        header, body = line[1:].split(" = ", 1)
                        header = header.strip()
                        if header.startswith("map"):
                            key = header[3:].strip()
                            if not key:
                                p("Usage: .map key = template", style="warning")
                                continue
                            blocked, patt = self._is_blocked(body)
                            if blocked:
                                p(f"[SECURITY] Refused to store mapping containing blocked pattern: {patt}", style="red")
                                continue
                            self._save_mapping(key, body)
                            p(f"[MAP] Saved mapping '{key}' -> {body}", style="green")
                        elif header.startswith("teach"):
                            key = header[5:].strip()
                            if not key:
                                p("Usage: .teach key = resp1|resp2", style="warning")
                                continue
                            parts = [s.strip() for s in body.split("|") if s.strip()]
                            self._save_brain(key, parts)
                            p(f"[BRAIN] Learned key '{key}' with {len(parts)} response(s).", style="green")
                        else:
                            p("Unknown .command. Use .map or .teach", style="warning")
                    else:
                        p("Malformed dot-command. Use '.map key = template' or '.teach key = resp1|resp2'", style="warning")
                    continue

                try:
                    parts = shlex.split(line)
                except Exception:
                    parts = line.split()
                if not parts:
                    continue
                cmd = parts[0].lower()
                args = parts[1:]

                # builtins
                if cmd in ("exit", "quit"):
                    p("Goodbye — stay curious.", style="magenta")
                    break
                if cmd == "help":
                    self.cmd_help(); continue
                if cmd == "sys":
                    self.cmd_sys(); continue
                if cmd == "search":
                    self.cmd_search(" ".join(args)); continue
                if cmd == "maps":
                    self.cmd_maps(); continue
                if cmd == "brain":
                    self.cmd_brain(); continue
                if cmd == "memo":
                    dbpath = os.path.abspath(self.DB_FILE)
                    if shutil.which("sqlite3"):
                        p(f"[MEMO] Opening sqlite3 CLI for {dbpath}", style="green")
                        subprocess.run(["sqlite3", dbpath])
                    else:
                        p(f"[MEMO] DB file at: {dbpath}", style="green")
                    continue
                if cmd == "clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    continue
                if cmd == "cd":
                    target = args[0] if args else os.path.expanduser("~")
                    try:
                        os.chdir(os.path.expanduser(target))
                        self.cwd = os.getcwd()
                        p(f"[DIR] {self.cwd}", style="green")
                    except Exception as e:
                        p(f"[DIR] Failed to change dir: {e}", style="red")
                    continue
                if cmd in ("unmap", "forget"):
                    if not args:
                        p("Usage: unmap <key>", style="warning"); continue
                    key = args[0]
                    if key in self.mappings:
                        self._delete_mapping(key)
                        p(f"[MAP] Deleted mapping: {key}", style="green")
                    else:
                        p("[MAP] Key not found.", style="warning")
                    continue
                if cmd == "exec":
                    if not args:
                        p("Usage: exec <cmd> [args...]", style="warning"); continue
                    try:
                        subprocess.run(args, check=False)
                    except Exception as e:
                        p(f"[EXEC] Failed: {e}", style="red")
                    continue
                if cmd == "shell":
                    if not args:
                        p("Usage: shell <command string>", style="warning"); continue
                    cmdstr = " ".join(args)
                    self.exec_shell(cmdstr)
                    continue

                # map <key> shorthand runs mapping
                if cmd == "map" and args:
                    key = args[0]
                    mapping = self.mappings.get(key)
                    if mapping:
                        self.execute_mapped(mapping, args[1:])
                    else:
                        p(f"[MAP] No mapping named '{key}'", style="warning")
                    continue

                # direct mapping invocation
                if cmd in self.mappings:
                    self.execute_mapped(self.mappings[cmd], args)
                    continue

                # brain responses
                if cmd in self.knowledge:
                    responses = self.knowledge[cmd]
                    if isinstance(responses, str) and "|" in responses:
                        cand = [r for r in responses.split("|") if r.strip()]
                        reply = random.choice(cand) if cand else responses
                    elif isinstance(responses, str):
                        reply = responses
                    else:
                        reply = str(responses)
                    p(reply, style="muted")
                    continue

                # run system commands if available
                if shutil.which(cmd):
                    try:
                        subprocess.run([cmd] + args)
                    except Exception as e:
                        p(f"[SYS] Failed to run {cmd}: {e}", style="red")
                    continue

                # fuzzy suggestion
                suggestion = self.fuzzy_match(cmd)
                if suggestion:
                    p(f"[SUGGEST] Unknown command. Did you mean '{suggestion}'? Try it.", style="warning")
                    continue

                p("[??] Command unknown. Use .map or .teach to extend me, or 'help' for builtins.", style="red")

            except KeyboardInterrupt:
                p("\nInterrupted (Ctrl-C). Type exit to quit.", style="warning")
            except EOFError:
                p("\nEOF. Exiting.", style="magenta")
                break
            except Exception as e:
                p(f"[ERROR] {e}", style="red")
                traceback.print_exc()

# ---------------- Run ----------------
if __name__ == "__main__":
    bot = AssistBotPlus()
    bot.run()
