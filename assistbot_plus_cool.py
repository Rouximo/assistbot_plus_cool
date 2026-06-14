#!/usr/bin/env python3
"""
AssistBot+ — Cyberpunk Dystopian Edition.
Pure ANSI aesthetic, no external UI dependencies.

Features:
- Neon cyan/red/green dystopian color scheme
- ASCII box-drawing UI panels
- Hacker-style boot animation
- Readline-safe prompt wrapping
- Safe Calculator Node
- Persisted Graph Designer & Visualizer
- Persistent Note Fragments
- Background Asynchronous Cortical Reminders
- Robust `search` command with platform-friendly URL opening
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
import time
import ast
import operator
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import urllib.parse

# =============== DYSTOPIAN ANSI COLOR PALETTE ===============
ANSI = {
    "sys": "\033[1;96m",    # Neon Cyan
    "err": "\033[1;91m",    # Neon Red
    "warn": "\033[1;93m",   # Yellow
    "mut": "\033[90m",      # Dark Gray/Steel
    "head": "\033[1;95m",   # Magenta
    "succ": "\033[1;92m",   # Neon Green
    "reset": "\033[0m",
}

def _np(seq: str) -> str:
    """
    Wrap non-printing ANSI sequence for readline safety.
    readline needs non-printing sequences wrapped in \001...\002
    to avoid cursor position miscalculation.
    """
    if not seq:
        return seq
    return f"\001{seq}\002"

def p(text: str, style: str = "mut", end: str = "\n"):
    """
    Dystopian print function with ANSI styling.
    Automatically wraps text in requested color and resets.
    """
    code = ANSI.get(style, ANSI["mut"])
    reset = ANSI["reset"]
    print(f"{code}{text}{reset}", end=end)

def animate_boot():
    """
    Hacker-style boot animation on startup.
    Clears screen and simulates system initialization.
    """
    os.system("cls" if os.name == "nt" else "clear")
    time.sleep(0.3)
    
    boot_steps = [
        "INITIALIZING NEURAL LINK...",
        "BYPASSING SECURITY PROTOCOLS...",
        "LOADING CONSCIOUSNESS MATRIX...",
        "SYNCHRONIZATION COMPLETE.",
    ]
    
    for step in boot_steps:
        p(step, style="sys")
        time.sleep(0.5)
    
    time.sleep(0.3)
    os.system("cls" if os.name == "nt" else "clear")

def draw_box(title: str, rows: list, col_widths: list) -> str:
    """
    Draw an ASCII box with neon borders.
    Returns a complete bordered panel as a string.
    """
    if not rows and not col_widths:
        return ""
    
    border_width = sum(col_widths) + len(col_widths) * 3 + 1
    top = "┌" + "─" * (border_width - 2) + "┐"
    
    if title:
        title_fmt = f" {title} "
        title_padded = title_fmt.center(border_width - 2)
        title_line = "│" + title_padded + "│"
        separator = "├" + "─" * (border_width - 2) + "┤"
        lines = [top, title_line, separator]
    else:
        lines = [top]
    
    for row in rows:
        row_parts = []
        for i, cell in enumerate(row):
            if i < len(col_widths):
                cell_str = str(cell).ljust(col_widths[i])
            else:
                cell_str = str(cell)
            row_parts.append(cell_str)
        row_line = "│ " + " │ ".join(row_parts) + " │"
        lines.append(row_line)
    
    bottom = "└" + "─" * (border_width - 2) + "┘"
    lines.append(bottom)
    
    return "\n".join(lines)

def disk_meter(used: int, total: int, width: int = 20) -> str:
    """
    Create a simple disk usage meter using block characters.
    """
    if total == 0:
        return "█" * width
    
    ratio = used / total
    filled = int(width * ratio)
    empty = width - filled
    
    blocks = ["▂", "▃", "▄", "▅", "▆", "▇", "█"]
    meter = "".join(blocks[min(6, (i * 7 // width))] for i in range(filled))
    meter += "░" * empty
    
    return f"[{meter}] {int(ratio * 100)}%"

# =============== SAFE CALCULATOR LOGIC ===============
def safe_eval(expr):
    """
    Safely evaluate mathematical expressions using AST parsing
    without risking shell injection vulnerabilities from basic eval().
    """
    bin_ops = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow
    }
    unary_ops = {
        ast.UAdd: operator.pos, ast.USub: operator.neg
    }
    def _eval(node):
        if isinstance(node, ast.Num): 
            return node.n
        elif isinstance(node, ast.BinOp): 
            return bin_ops[type(node.op)](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp): 
            return unary_ops[type(node.op)](_eval(node.operand))
        else: 
            raise TypeError(node)
    return _eval(ast.parse(expr, mode='eval').body)


# =============== ASSISTBOT+ CORE ===============
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
        
        # Reminder Background Monitor System
        self.run_reminders = True
        self.reminder_thread = threading.Thread(target=self._reminder_daemon, daemon=True)
        self.reminder_thread.start()
        
        self._print_banner()

    # =============== DATABASE OPERATIONS ===============
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
        # Added tracking schemas for notes, graphs, and reminders
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, ts TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS graphs (name TEXT PRIMARY KEY, data TEXT)"
        )
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, msg TEXT, trigger_time REAL)"
        )
        self.db.commit()

    def _load_mappings(self):
        self.cursor.execute("SELECT key, template FROM commands")
        self.mappings = {r[0]: r[1] for r in self.cursor.fetchall()}

    def _load_knowledge(self):
        self.cursor.execute("SELECT key, responses FROM brain")
        self.knowledge = {r[0]: r[1] for r in self.cursor.fetchall()}

    def _save_mapping(self, key, template):
        meta = json.dumps({"created": datetime.now(timezone.utc).isoformat()})
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

    # =============== PLUGIN SYSTEM ===============
    def _load_plugins(self):
        os.makedirs(self.PLUGINS_DIR, exist_ok=True)
        for path in glob.glob(os.path.join(self.PLUGINS_DIR, "*.py")):
            name = os.path.splitext(os.path.basename(path))[0]
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.plugins[name] = mod
                p(f"[PLUGIN] Loaded: {name}", style="sys")
            except Exception:
                p(f"[PLUGIN] Failed to load {name}: {traceback.format_exc()}", style="err")

    # =============== READLINE & COMPLETION ===============
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
                "unmap", "forget", ".map", ".teach", "map",
                "calc", "note", "graph", "remind"
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

    # =============== PROMPT DESIGN & TIME SYSTEM ===============
    def get_sys_time(self):
        """Updated Time System: Dystopian Hex-Splice Cycle Format."""
        now = datetime.now()
        return f"CYC-{now.strftime('%y.%m')} | T-{now.strftime('%H:%M:%S')}"

    def prompt_short(self):
        user = self.user
        time_str = self.get_sys_time()
        
        # Line 1: ┌──[username]──[time]
        line1 = f"┌──{_np(ANSI['sys'])}[{user}]{_np(ANSI['reset'])}──{_np(ANSI['warn'])}[{time_str}]{_np(ANSI['reset'])}"
        
        # Line 2: └──> ▒ (cursor line)
        line2 = f"└──{_np(ANSI['head'])}>{_np(ANSI['reset'])} {_np(ANSI['succ'])}▒{_np(ANSI['reset'])} "
        
        return f"{line1}\n{line2}"

    # =============== SECURITY & MATCHING ===============
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

    # =============== TEMPLATE EXPANSION ===============
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
            p(f"[SECURITY] Refused to run command containing blocked pattern: {patt}", style="err")
            return None

        tokens = self._expand_template(template, args)
        if not tokens:
            p("[EXEC] Nothing to run after expansion.", style="warn")
            return None

        if dry:
            p("[DRY] expanded -> " + " ".join(shlex.quote(t) for t in tokens), style="warn")
            return None

        try:
            p(f"[EXEC] Running: {tokens[0]} {' '.join(shlex.quote(t) for t in tokens[1:])}", style="succ")
            cp = subprocess.run(tokens, check=False)
            return cp
        except FileNotFoundError:
            p("[EXEC] Command not found. Try shell form or map a full path.", style="err")
        except Exception as e:
            p(f"[EXEC] Execution failed: {e}", style="err")
            traceback.print_exc()

    def exec_shell(self, command_str):
        blocked, patt = self._is_blocked(command_str)
        if blocked:
            p(f"[SECURITY] Refused to run shell command containing blocked pattern: {patt}", style="err")
            return None
        p(f"[SHELL] Running via shell: {command_str}", style="warn")
        try:
            cp = subprocess.run(command_str, shell=True)
            return cp
        except Exception as e:
            p(f"[SHELL] Failed: {e}", style="err")
            traceback.print_exc()

    # =============== URL OPENER (PLATFORM-FRIENDLY) ===============
    def _open_url(self, url: str) -> bool:
        if shutil.which("am"):
            try:
                rc = subprocess.run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url], check=False)
                if rc.returncode == 0: return True
            except Exception: pass

        if shutil.which("termux-open-url"):
            try:
                rc = subprocess.run(["termux-open-url", url], check=False)
                if rc.returncode == 0: return True
            except Exception: pass

        if shutil.which("xdg-open"):
            try:
                rc = subprocess.run(["xdg-open", url], check=False)
                if rc.returncode == 0: return True
            except Exception: pass

        if shutil.which("open"):
            try:
                rc = subprocess.run(["open", url], check=False)
                if rc.returncode == 0: return True
            except Exception: pass

        try:
            opened = webbrowser.open(url, new=2)
            if opened: return True
        except Exception: pass
        return False

    # =============== EXTENDED DYSTOPIAN MODULES ===============
    def cmd_calc(self, args):
        """Safe calculation parser built right in."""
        if not args:
            p("[ERR] REQ EXPRESSION NODE. Usage: calc 2+5*20", style="err")
            return
        expr = "".join(args)
        try:
            res = safe_eval(expr)
            p(f"[SYS] LOGIC COMPUTATION RESULT: {res}", style="sys")
        except Exception:
            p("[ERR] CORRUPT DATA NODE OR INVALID SYNTAX IDENTIFIED.", style="err")

    def cmd_note(self, args):
        """Archived personal information text chunks."""
        if not args:
            p("Usage: note add <title> <content> | note list | note read <id> | note drop <id>", style="warn")
            return
        action = args[0].lower()
        if action == "add" and len(args) >= 3:
            title, content = args[1], " ".join(args[2:])
            self.cursor.execute("INSERT INTO notes (title, content, ts) VALUES (?, ?, ?)", (title, content, self.get_sys_time()))
            self.db.commit()
            p(f"[SYS] TEXT DATA FRAGMENT '{title}' COMMITTED TO MEMORY.", style="succ")
        elif action == "list":
            self.cursor.execute("SELECT id, title, ts FROM notes")
            rows = self.cursor.fetchall()
            if not rows:
                p("[SYS] THE PERSONAL ARCHIVE MEMORY BANCS ARE VACANT.", style="mut")
                return
            p(draw_box("DATA FRAGMENTS", rows, [4, 20, 26]), style="sys")
        elif action == "read" and len(args) == 2:
            self.cursor.execute("SELECT title, content, ts FROM notes WHERE id=?", (args[1],))
            row = self.cursor.fetchone()
            if row:
                print(f"{ANSI['sys']}┌─ {row[0]} ".ljust(60, "─") + f"┐{ANSI['reset']}")
                p(f"│ GENERATED: {row[2]}", style="mut")
                print(f"{ANSI['sys']}├" + "─" * 58 + f"┤{ANSI['reset']}")
                p(f"│ {row[1]}", style="reset")
                print(f"{ANSI['sys']}└" + "─" * 58 + f"┘{ANSI['reset']}")
            else:
                p("[ERR] CORRUPT TARGET: DATA FRAGMENT IDENTIFIER NOT FOUND.", style="err")
        elif action == "drop" and len(args) == 2:
            self.cursor.execute("DELETE FROM notes WHERE id=?", (args[1],))
            self.db.commit()
            p("[SYS] TARGET DATA BLOCK HAS BEEN PURGED PERMANENTLY.", style="err")

    def cmd_graph(self, args):
        """Topological Data Matrix Graphics Engine."""
        if not args:
            p("Usage: graph create <name> <10,50,30,80> | graph view <name> | graph list", style="warn")
            return
        action = args[0].lower()
        if action == "create" and len(args) >= 3:
            name, data = args[1], args[2]
            try:
                [float(x) for x in data.split(",")]  # Topology check verification
                self.cursor.execute("REPLACE INTO graphs (name, data) VALUES (?, ?)", (name, data))
                self.db.commit()
                p(f"[SYS] VECTOR GRAPH TOPOLOGY CONFIGURATION '{name}' RETAINED.", style="succ")
            except ValueError:
                p("[ERR] MATRIX DATA CAN ONLY CONTAIN COMMA-SEPARATED INTEGERS.", style="err")
        elif action == "list":
            self.cursor.execute("SELECT name FROM graphs")
            rows = self.cursor.fetchall()
            p("[SYS] IDENTIFIED RETAINED TOPOLOGIES:", style="sys")
            for r in rows: 
                p(f" -> {r[0]}", style="mut")
        elif action == "view" and len(args) == 2:
            self.cursor.execute("SELECT data FROM graphs WHERE name=?", (args[1],))
            row = self.cursor.fetchone()
            if not row:
                p("[ERR] ARBITRARY DATA TOPOLOGY COORD SET UNKNOWN.", style="err")
                return
            
            data = [float(x) for x in row[0].split(",")]
            max_val = max(data) if data else 1
            blocks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
            
            p(f"\nTOPOLOGY RENDER ENGINE MONITOR: {args[1]}", style="sys")
            for i, val in enumerate(data):
                idx = int((val / max_val) * 7) if max_val > 0 else 0
                bar = blocks[idx] * int((val / max_val) * 25)
                print(f"{ANSI['head']}{i:02d}{ANSI['reset']} | {ANSI['succ']}{bar.ljust(25)}{ANSI['reset']} Matrix Vector Node: {val}")
            print()

    def cmd_remind(self, args):
        """Inject cortical custom notification timer blocks."""
        if len(args) < 2:
            p("Usage: remind <seconds> <message...>", style="warn")
            return
        try:
            delay = float(args[0])
            msg = " ".join(args[1:])
            trigger = time.time() + delay
            self.cursor.execute("INSERT INTO reminders (msg, trigger_time) VALUES (?, ?)", (msg, trigger))
            self.db.commit()
            p(f"[SYS] INJECTED REAL-TIME CORTICAL ALERT IMPLANT TARGETED IN {delay}s.", style="succ")
        except ValueError:
            p("[ERR] TEMPORAL TIME INTERVAL VALUE TYPE MUST BE NUMERIC.", style="err")

    def _reminder_daemon(self):
        """Asynchronous background loop handling alerts."""
        while self.run_reminders:
            try:
                now = time.time()
                # Query direct connection thread assets securely
                self.cursor.execute("SELECT id, msg FROM reminders WHERE trigger_time <= ?", (now,))
                due = self.cursor.fetchall()
                for r in due:
                    # Thread terminal flash trigger ring bell sound (\a)
                    print("\a", end="")
                    print(f"\n\n{ANSI['err']}>>> WARNING: CORTICAL NOTIFICATION DETECTED <<<{ANSI['reset']} {r[1]}")
                    print(f"{ANSI['succ']}▒{ANSI['reset']} ", end="", flush=True)
                    self.cursor.execute("DELETE FROM reminders WHERE id=?", (r[0],))
                if due: 
                    self.db.commit()
            except Exception:
                pass
            time.sleep(1.5)

    # =============== BUILTIN ROUTING AND RUN TIME ===============
    def cmd_help(self):
        help_text = f"""{ANSI['sys']}AssistBot+ — Cyberpunk Dystopian Edition{ANSI['reset']}

Core commands:
  {ANSI['head']}help{ANSI['reset']}                 Show this help menu matrix layout
  {ANSI['head']}sys{ANSI['reset']}                  Show disk structure allocations and core load metric meters
  {ANSI['head']}calc <expr>{ANSI['reset']}          Evaluate mathematical logic matrices securely via AST
  {ANSI['head']}note{ANSI['reset']}                 add / list / read / drop personal information fragments
  {ANSI['head']}graph{ANSI['reset']}                create / view / list visual horizontal terminal graph datasets
  {ANSI['head']}remind <s.> <msg>{ANSI['reset']}   Inject active threaded background custom notification parameters
  {ANSI['head']}search <query>{ANSI['reset']}       Open browser query portals (use -y for YouTube, -g for Google)
  {ANSI['head']}.map key = template{ANSI['reset']}  Map a shorthand system configuration macro
  {ANSI['head']}.teach key = resp{ANSI['reset']}     Impart conscious prompt responses to the mainframe block
  {ANSI['head']}maps / brain{ANSI['reset']}         Display active configuration structural layouts
  {ANSI['head']}clear / cd / exit{ANSI['reset']}     Terminal environmental state configurations
"""
        print(help_text)

    def cmd_sys(self):
        """Display system info with neon disk meter."""
        try:
            total, used, free = shutil.disk_usage(self.cwd)
            load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
            
            used_gb = used // (2**30)
            total_gb = total // (2**30)
            
            meter = disk_meter(used, total, width=20)
            
            p("[DISK]", style="sys", end="")
            p(f" {used_gb}GB used / {total_gb}GB total", end="")
            p(f" {meter}", style="succ")
            
            p(f"[LOAD] {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}", style="sys")
        except Exception as e:
            p(f"[SYS] Info failed: {e}", style="err")

    def cmd_search(self, raw_query: str):
        if not raw_query or not raw_query.strip():
            p("Usage: search <query>  (use -y for YouTube or -g for Google)", style="warn")
            return

        try: tokens = shlex.split(raw_query)
        except Exception: tokens = raw_query.split()

        tokens_l = [t.lower() for t in tokens]
        force_yt, force_google, is_youtube = False, False, False

        cleaned = []
        for tok, tl in zip(tokens, tokens_l):
            if tl in ('-y', '--youtube'): is_youtube = True; continue
            if tl in ('-g', '--google'): force_google = True; continue
            if tl.endswith(':') and tl[:-1] in ('yt', 'youtube'): is_youtube = True; continue
            if ':' in tok and tok.split(':', 1)[0].lower() in ('yt', 'youtube'):
                is_youtube = True
                parts = tok.split(':', 1)
                if parts[1]: cleaned.append(parts[1])
                continue
            cleaned.append(tok)

        if force_google: is_youtube = False

        new_cleaned = []
        i = 0
        while i < len(cleaned):
            tok = cleaned[i]
            tl = tok.lower()
            if tl in ('on', 'of') and i + 1 < len(cleaned) and cleaned[i+1].lower() == 'youtube':
                is_youtube = True; i += 2; continue
            if tl == 'youtube' or tl == 'yt':
                is_youtube = True; i += 1; continue
            new_cleaned.append(tok)
            i += 1

        query = ' '.join(new_cleaned).strip()

        if is_youtube and not query:
            url = 'https://www.youtube.com'
            p('[WEB] Opening YouTube home', style='sys')
            self._open_url(url)
            return

        enc = urllib.parse.quote_plus(query if query else raw_query)
        url = f'https://www.youtube.com/results?search_query={enc}' if is_youtube else f'https://www.google.com/search?q={enc}'
        p(f"[WEB] Routing Portal Request: {query if query else raw_query}", style='sys')
        p(url, style='mut')
        self._open_url(url)

    def cmd_maps(self):
        if not self.mappings:
            p("No mappings yet. Use: .map key = command", style="warn")
            return
        rows = [(k, self.mappings[k]) for k in sorted(self.mappings.keys())]
        col_widths = [max(len(r[0]) for r in rows) + 2, max(len(r[1]) for r in rows) + 2]
        p(draw_box("MAPPINGS", rows, col_widths), style="sys")

    def cmd_brain(self):
        if not self.knowledge:
            p("Brain empty. Use: .teach key = resp1|resp2", style="warn")
            return
        rows = [(k, self.knowledge[k]) for k in sorted(self.knowledge.keys())]
        col_widths = [max(len(r[0]) for r in rows) + 2, max(len(r[1]) for r in rows) + 2]
        p(draw_box("BRAIN", rows, col_widths), style="sys")

    def _print_banner(self):
        banner_lines = [
            r"   ___    ____  ____  _____ ____  _   _ ",
            r"  / _ \  / ___|| __ )| ____|  _ \| \ | |",
            r" | | | | \___ \|  _ \|  _| | |_) |  \| |",
            r" | |_| |  ___) | |_) | |___|  _ <| |\  |",
            r"  \___/  |____/|____/|_____|_| \_\_| \_|",
        ]
        for line in banner_lines:
            p(line, style="head")
        p("", end="")
        p(">>> ASSISTBOT+ — CYBERPUNK DYSTOPIAN EDITION // SYSTEM RUNNING", style="sys")
        p(">>> Mainframe terminal ready. Input directive sequence.", style="mut")
        p("", end="")

    def run(self):
        p("Starting AssistBot+ — neural link active.", style="sys")
        while True:
            try:
                prompt_str = self.prompt_short()
                raw = input(prompt_str)
                if raw is None: break
                line = raw.strip()
                if not line: continue

                try: self.add_history(line)
                except Exception: pass

                if line.startswith("."):
                    if " = " in line:
                        header, body = line[1:].split(" = ", 1)
                        header = header.strip()
                        if header.startswith("map"):
                            key = header[3:].strip()
                            if not key: continue
                            blocked, patt = self._is_blocked(body)
                            if blocked: continue
                            self._save_mapping(key, body)
                            p(f"[MAP] Saved shorthand code template assignment.", style="succ")
                        elif header.startswith("teach"):
                            key = header[5:].strip()
                            if not key: continue
                            parts = [s.strip() for s in body.split("|") if s.strip()]
                            self._save_brain(key, parts)
                            p(f"[BRAIN] Consciousness data structural map configured.", style="succ")
                    continue

                try: parts = shlex.split(line)
                except Exception: parts = line.split()
                if not parts: continue
                
                cmd = parts[0].lower()
                args = parts[1:]

                # Integrated core routing modules
                if cmd in ("exit", "quit"):
                    p("Severing direct neural connection uplink. Systems offline.", style="head")
                    self.run_reminders = False
                    break
                elif cmd == "help": self.cmd_help()
                elif cmd == "sys": self.cmd_sys()
                elif cmd == "calc": self.cmd_calc(args)
                elif cmd == "note": self.cmd_note(args)
                elif cmd == "graph": self.cmd_graph(args)
                elif cmd == "remind": self.cmd_remind(args)
                elif cmd == "search": self.cmd_search(" ".join(args))
                elif cmd == "maps": self.cmd_maps()
                elif cmd == "brain": self.cmd_brain()
                elif cmd == "clear": os.system("cls" if os.name == "nt" else "clear")
                elif cmd == "cd":
                    target = args[0] if args else os.path.expanduser("~")
                    try:
                        os.chdir(os.path.expanduser(target))
                        self.cwd = os.getcwd()
                        p(f"[DIR] {self.cwd}", style="succ")
                    except Exception: p("[DIR] Critical path unresolvable.", style="err")
                elif cmd in ("unmap", "forget"):
                    if args and args[0] in self.mappings: self._delete_mapping(args[0])
                elif cmd == "exec" and args:
                    try: subprocess.run(args, check=False)
                    except Exception: pass
                elif cmd == "shell" and args:
                    self.exec_shell(" ".join(args))
                elif cmd == "map" and args:
                    mapping = self.mappings.get(args[0])
                    if mapping: self.execute_mapped(mapping, args[1:])
                elif cmd in self.mappings:
                    self.execute_mapped(self.mappings[cmd], args)
                elif cmd in self.knowledge:
                    resps = self.knowledge[cmd]
                    p(random.choice(resps.split("|")) if "|" in resps else resps, style="mut")
                elif shutil.which(cmd):
                    try: subprocess.run([cmd] + args)
                    except Exception: pass
                else:
                    sugg = self.fuzzy_match(cmd)
                    if sugg: p(f"[SUGGEST] Direct command invalid. Did you mean '{sugg}'?", style="warn")
                    else: p("[??] Command string unknown. Mainframe security access denied.", style="err")

            except KeyboardInterrupt: p("\n[WARN] Uplink alert loop signal interrupted.", style="warn")
            except EOFError: break
            except Exception as e: p(f"[ERROR] Mainframe panic condition: {e}", style="err")

if __name__ == "__main__":
    animate_boot()
    bot = AssistBotPlus()
    bot.run()

