#!/usr/bin/env python3
"""
AssistBot+ — improved version with platform-friendly search opener.

Features:
- Robust `search` command that detects YouTube intent and opens the correct URL.
- Tries multiple URL openers (am start, termux-open-url, xdg-open, open, webbrowser).
- Readline-friendly prompt (non-printing ANSI wrapped) to avoid wrapping/cursor bugs.
- SQLite-backed simple commands and brain.
- Plugin loading, mappings, and basic builtins preserved.
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
from datetime import datetime, timezone
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

STYLE_KEYS = [
    "header", "cyan", "green", "gold", "red", "magenta", "bold", "muted", "warning"
]

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "header": "\033[95m",
    "cyan": "\033[96m",
    "green": "\033[92m",
    "gold": "\033[93m",
    "red": "\033[91m",
    "magenta": "\033[35m",
    "muted": "\033[90m",
    "warning": "\033[33m",
}

def _np(seq: str) -> str:
    """
    Wrap non-printing ANSI sequence for readline-aware prompts.
    readline needs non-printing sequences wrapped in \001...\002 so it
    can correctly compute cursor position (prevents wrapping issues).
    """
    if not seq:
        return seq
    return f"\001{seq}\002"

def p(text: str, style: str = None, end: str = "\n"):
    """Central print function with optional ANSI/rich styling."""
    if USE_RICH:
        if style:
            console.print(text, style=style, end=end)
        else:
            console.print(text, end=end)
    else:
        if style:
            parts = style.split()
            codes = "".join(ANSI.get(part, "") for part in parts)
            print(f"{codes}{text}{ANSI['reset']}", end=end)
        else:
            print(text, end=end)

def pretty_table(columns, rows, title=None):
    """Render a simple table (rich if available)."""
    if USE_RICH:
        t = Table(title=title) if title else Table()
        for c in columns:
            t.add_column(str(c))
        for r in rows:
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
            line = " | ".join(
                str(r[i]).ljust(colwidths[i]) if i < len(r) else "".ljust(colwidths[i])
                for i in range(len(columns))
            )
            p(line)

# ---------------- AssistBotPlus core ----------------
class AssistBotPlus:
    DB_FILE = "assistbot_plus.db"
    PLUGINS_DIR = "plugins"
    BLOCKED_PATTERNS = [
        "rm -rf", "rm -rf /", "mkfs", ":(){:|:&};:", "dd if=",
        ">/dev", ">: /dev", "sudo rm", "chmod 000", "halt", "reboot", "poweroff"
    ]

    def __init__(self):
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

        self.plugins = {}
        self._load_plugins()

        self._setup_readline()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._print_banner()

    # DB helpers
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
        ts = datetime.now(timezone.utc).isoformat()
        self.cursor.execute("INSERT INTO history VALUES (?, ?)", (ts, entry))
        self.db.commit()

    # Plugins
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

    # Readline / Completion
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
            try:
                readline.parse_and_bind('set horizontal-scroll-mode Off')
            except Exception:
                pass
        except Exception:
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

    # Helpers
    def prompt_short(self):
        user = self.user
        time = datetime.now().strftime("%H:%M")
        path = self.cwd.replace(os.path.expanduser("~"), "~")
        if USE_RICH:
            header = f"[bold magenta]ASSIST[/bold magenta] "
            user_part = f"[bold cyan]{user}[/bold cyan]"
            at = " @ "
            time_part = f"[bold green]{time}[/bold green]"
            sep = f" [{path}]"
            arrow = "[bold green]λ[/bold green]"
            return f"{header}{user_part}{at}{time_part}{sep}\n{arrow} "
        else:
            header = f"{_np(ANSI['header'] + ANSI['bold'])}ASSIST{_np(ANSI['reset'])} "
            user_part = f"{_np(ANSI['cyan'] + ANSI['bold'])}{user}{_np(ANSI['reset'])}"
            at = " @ "
            time_part = f"{_np(ANSI['green'] + ANSI['bold'])}{time}{_np(ANSI['reset'])}"
            sep = f" {_np(ANSI['gold'])}{path}{_np(ANSI['reset'])}"
            arrow = f"{_np(ANSI['green'] + ANSI['bold'])}λ{_np(ANSI['reset'])}"
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

    # Expand & Execute
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

    # URL opener helper (tries many fallbacks without Termux:API requirement)
    def _open_url(self, url: str) -> bool:
        """
        Try multiple ways to open a URL. Returns True if one method appears to have been invoked.
        Order:
          1) Android 'am start' (available on most Android devices including Termux)
          2) termux-open-url (if present)
          3) xdg-open (Linux desktop)
          4) open (macOS)
          5) webbrowser.open()
        If none works, return False (caller should print the URL).
        """
        # 1) Try Android am start (Intent)
        if shutil.which("am"):
            try:
                # Use the Android intent to view the URL
                rc = subprocess.run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url], check=False)
                # rc.returncode == 0 is a good sign
                if rc.returncode == 0:
                    return True
            except Exception:
                pass

        # 2) termux-open-url (optional, won't be required)
        if shutil.which("termux-open-url"):
            try:
                rc = subprocess.run(["termux-open-url", url], check=False)
                if rc.returncode == 0:
                    return True
            except Exception:
                pass

        # 3) xdg-open (desktop linux)
        if shutil.which("xdg-open"):
            try:
                rc = subprocess.run(["xdg-open", url], check=False)
                if rc.returncode == 0:
                    return True
            except Exception:
                pass

        # 4) macOS open
        if shutil.which("open"):
            try:
                rc = subprocess.run(["open", url], check=False)
                if rc.returncode == 0:
                    return True
            except Exception:
                pass

        # 5) Python's webbrowser as last resort (may return False on Termux)
        try:
            opened = webbrowser.open(url, new=2)
            if opened:
                return True
        except Exception:
            pass

        # nothing worked
        return False

    # Builtins
    def cmd_help(self):
        help_text = """AssistBot+ — Cool mode enabled.

Core commands:
  help                 Show this help
  sys                  Show disk and load info
  search <query>       Open browser search (google or youtube). Accepts flags -y/--youtube or -g/--google.
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
  search mrbeast youtube
  search yt: \"mrbeast challenge\"
  search -y mrbeast
  search -g linux networking
  .map greet = echo Hello $1
  .teach joke = Why did the chicken cross? | To get to the other side
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

    def cmd_search(self, raw_query: str):
        """
        Robust search implementation:
          - supports flags -y/--youtube and -g/--google
          - supports prefixes 'yt:' or 'youtube:' and 'yt:term' inline
          - detects phrases like 'on youtube', trailing 'youtube' or 'yt'
          - tries to open the URL using _open_url() (which uses am/xdg-open/termux-open-url/webbrowser)
          - prints the final URL as fallback
        """
        if not raw_query or not raw_query.strip():
            p("Usage: search <query>  (use -y for YouTube or -g for Google)", style="warning")
            return

        try:
            tokens = shlex.split(raw_query)
        except Exception:
            tokens = raw_query.split()

        tokens_l = [t.lower() for t in tokens]

        force_yt = False
        force_google = False
        is_youtube = False

        # First pass: parse flags and prefixes; build cleaned tokens
        cleaned = []
        for tok, tl in zip(tokens, tokens_l):
            if tl in ('-y', '--youtube'):
                force_yt = True
                continue
            if tl in ('-g', '--google'):
                force_google = True
                continue
            if tl.endswith(':') and tl[:-1] in ('yt', 'youtube'):
                is_youtube = True
                continue
            if ':' in tok and tok.split(':', 1)[0].lower() in ('yt', 'youtube'):
                is_youtube = True
                parts = tok.split(':', 1)
                if parts[1]:
                    cleaned.append(parts[1])
                continue
            cleaned.append(tok)

        # Respect explicit flags
        if force_yt:
            is_youtube = True
        if force_google:
            is_youtube = False

        # Second pass: safely remove tokens like 'on youtube', 'of youtube', standalone 'youtube'/'yt'
        new_cleaned = []
        i = 0
        while i < len(cleaned):
            tok = cleaned[i]
            tl = tok.lower()
            # on youtube / of youtube
            if tl in ('on', 'of') and i + 1 < len(cleaned) and cleaned[i+1].lower() == 'youtube':
                is_youtube = True
                i += 2
                continue
            if tl == 'youtube' or tl == 'yt':
                is_youtube = True
                i += 1
                continue
            new_cleaned.append(tok)
            i += 1

        query = ' '.join(new_cleaned).strip()

        # If user asked only youtube (no extra terms)
        if is_youtube and not query:
            url = 'https://www.youtube.com'
            p('[WEB] Opening YouTube home', style='green')
            p(url, style='muted')
            opened = self._open_url(url)
            if not opened:
                p('[WEB] Could not open automatically. URL printed above.', style='warning')
            return

        # Build final URL
        if is_youtube:
            enc = urllib.parse.quote_plus(query if query else raw_query)
            url = f'https://www.youtube.com/results?search_query={enc}'
            p(f"[WEB] YouTube search: {query if query else raw_query}", style='green')
        else:
            enc = urllib.parse.quote_plus(query if query else raw_query)
            url = f'https://www.google.com/search?q={enc}'
            p(f"[WEB] Google search: {query if query else raw_query}", style='green')

        # Attempt to open
        p(url, style='muted')
        opened = self._open_url(url)
        if not opened:
            p('[WEB] No opener succeeded — copy/paste the URL above into a browser.', style='warning')

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

    # Main loop
    def run(self):
        p("Starting AssistBot+ — ready.", style="magenta")
        while True:
            try:
                prompt_str = self.prompt_short()
                if USE_RICH:
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

                # builtins routing
                if cmd in ("exit", "quit"):
                    p("Goodbye — stay curious.", style="magenta")
                    break
                if cmd == "help":
                    self.cmd_help(); continue
                if cmd == "sys":
                    self.cmd_sys(); continue
                if cmd == "search":
                    # pass raw substring so quotes/colons are preserved
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

                # map shorthand
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

                # run system commands directly if available
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
