#!/usr/bin/env python3
"""Read, search and statically check HDevelop .hdev files.

A .hdev file is an XML container: one <l> element per code line, one <c> per
comment line, with & < > escaped. Reading it raw wastes context and makes it
easy to misread escaped operators; editing it by hand makes it easy to break
the escaping. These subcommands work on the code as HDevelop shows it, while
keeping the XML line numbers so edits can be aimed precisely.

    python hdev.py outline FILE                 procedures, interfaces, extents
    python hdev.py code FILE [--proc NAME]      plain source + XML line numbers
    python hdev.py grep FILE PATTERN            search the code, not the markup
    python hdev.py check FILE                   static checks (see below)
    python hdev.py wrap < snippet.txt           plain code -> escaped <l> lines

`check` reports, in order of seriousness:
  * XML that will not load in HDevelop
  * unbalanced if/for/while/try blocks
  * operator calls whose argument count disagrees with the installed HALCON
    operator reference (the check that catches hand-written code fastest)
  * variables that are only ever assigned inside a conditional branch but read
    outside it - the usual cause of "variable has not been initialized"
  * notes: stop(), dev_* display calls, hard-coded absolute paths
"""

import argparse
import html as htmllib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# --------------------------------------------------------------------------
# HALCON installation / operator signatures
# --------------------------------------------------------------------------

SIG_CACHE = "signature_cache.json"

def _sig_cache_path() -> Path:
    """Return a writable path for the signature cache.

    When running as a PyInstaller bundle the __file__ trick points inside the
    temp extraction dir, which vanishes on exit.  Store the cache next to the
    executable instead so it persists across runs.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / SIG_CACHE
    return Path(__file__).with_name(SIG_CACHE)

KEYWORDS = {
    "if", "else", "elseif", "endif", "for", "to", "by", "downto", "endfor",
    "while", "endwhile", "repeat", "until", "try", "catch", "endtry",
    "switch", "case", "default", "endswitch", "break", "continue", "return",
    "exit", "stop", "global", "def", "tuple", "and", "or", "not", "xor",
    "band", "bor", "bxor", "bnot", "lsh", "rsh", "true", "false", "then",
}

# HDevelop-only instructions with no page in the operator reference. Listing
# them keeps `check` from calling them typos; their arity is left unverified
# rather than guessed.
NO_DOC_INSTRUCTIONS = {"dev_update_off", "dev_update_on", "dev_update_var",
                       "dev_update_pc", "dev_update_time", "dev_update_window"}

CONDITIONAL_BLOCKS = {"if", "elseif", "else", "case", "default", "catch"}


def halcon_root():
    env = os.environ.get("HALCONROOT")
    if env and (Path(env) / "doc").is_dir():
        return Path(env)
    bases = [Path.home() / "AppData/Local/Programs/MVTec",
             Path("C:/Program Files/MVTec"),
             Path("/opt/halcon"), Path("/usr/local/halcon")]
    hits = []
    for base in bases:
        if base.is_dir():
            hits += [p for p in base.glob("HALCON-*") if (p / "doc").is_dir()]
    return sorted(hits)[-1] if hits else None


class Signatures:
    """Operator argument layout, read lazily from the local HALCON docs.

    HDevelop signatures read (InputIconic : OutputIconic : InputControl :
    OutputControl), and call arguments appear in exactly that order. Knowing
    the split is what lets us tell an operator's outputs (which are
    assignments) from its inputs (which are reads).
    """

    def __init__(self, root):
        self.root = root
        self.cache_file = _sig_cache_path()
        self.cache = {}
        if self.cache_file.is_file():
            try:
                self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        self.dirty = False

    def save(self):
        if self.dirty:
            try:
                self.cache_file.write_text(json.dumps(self.cache), encoding="utf-8")
            except Exception:
                pass

    def get(self, name):
        """Return [in_iconic, out_iconic, in_ctrl, out_ctrl] name lists, or None."""
        if name in self.cache:
            return self.cache[name]
        groups = self._read(name)
        self.cache[name] = groups
        self.dirty = True
        return groups

    def _read(self, name):
        if not self.root:
            return None
        page = self.root / "doc/html/reference/operators" / (name + ".html")
        if not page.is_file():
            return None
        with page.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(80000)
        m = re.search(r"<code><b>" + re.escape(name) + r"</b>\((.*?)\)</code>",
                      head, re.S)
        if not m:
            return None
        raw = re.sub(r"<[^>]+>", "", m.group(1))
        raw = htmllib.unescape(raw)
        groups = []
        for part in raw.split(":"):
            names = [p.strip() for p in part.split(",") if p.strip()]
            groups.append(names)
        while len(groups) < 4:
            groups.append([])
        return groups[:4]


# --------------------------------------------------------------------------
# .hdev parsing
# --------------------------------------------------------------------------

RE_PROC = re.compile(r"<procedure\s+name=\"([^\"]+)\"")
# Lines generated by an HDevelop assistant carry as_id/as_name/as_grp
# attributes; a pattern that only matches a bare <l> drops them silently.
RE_LINE = re.compile(r"^\s*<l(?:\s[^>]*)?>(.*)</l>\s*$")
RE_COMMENT = re.compile(r"^\s*<c(?:\s[^>]*)?>(.*)</c>\s*$")
RE_PAR = re.compile(r"<par\s+name=\"([^\"]+)\"")


class Row:
    __slots__ = ("lineno", "kind", "text")

    def __init__(self, lineno, kind, text):
        self.lineno = lineno    # 1-based line number in the .hdev file
        self.kind = kind        # "code" or "comment"
        self.text = text        # unescaped, leading indent preserved

    @property
    def stripped(self):
        return self.text.strip()

    @property
    def is_active(self):
        """A <l> line beginning with * is code the author disabled."""
        return self.kind == "code" and not self.stripped.startswith("*")


class Procedure:
    def __init__(self, name, start):
        self.name = name
        self.start = start
        self.end = None
        self.rows = []
        self.iface = {"io": [], "oo": [], "ic": [], "oc": []}

    def signature_groups(self):
        return [self.iface["io"], self.iface["oo"],
                self.iface["ic"], self.iface["oc"]]


def parse(path: Path):
    """Split a .hdev into procedures with their code rows.

    HDevelop writes one element per physical line, so a line-oriented pass
    gives an exact mapping from code back to file line numbers - which
    ElementTree does not provide.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    procs = []
    cur = None
    in_iface = False
    iface_tag = None
    for i, raw in enumerate(lines, start=1):
        m = RE_PROC.search(raw)
        if m:
            cur = Procedure(m.group(1), i)
            procs.append(cur)
            continue
        if cur is None:
            continue
        if "</procedure>" in raw:
            cur.end = i
            cur = None
            continue
        if "<interface" in raw:
            in_iface = "/>" not in raw
            continue
        if in_iface:
            if "</interface>" in raw:
                in_iface = False
                iface_tag = None
                continue
            for tag in ("io", "oo", "ic", "oc"):
                if "<" + tag + ">" in raw:
                    iface_tag = tag
                if "</" + tag + ">" in raw and iface_tag == tag:
                    iface_tag = None
            p = RE_PAR.search(raw)
            if p and iface_tag:
                cur.iface[iface_tag].append(p.group(1))
            continue
        m = RE_LINE.match(raw)
        if m:
            cur.rows.append(Row(i, "code", htmllib.unescape(m.group(1))))
            continue
        m = RE_COMMENT.match(raw)
        if m:
            cur.rows.append(Row(i, "comment", htmllib.unescape(m.group(1))))
    return procs


# --------------------------------------------------------------------------
# expression helpers
# --------------------------------------------------------------------------

def split_args(s: str):
    """Split a call argument list on top-level commas."""
    out, depth, quote, buf = [], 0, False, []
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == "'":
                quote = False
            continue
        if ch == "'":
            quote = True
            buf.append(ch)
        elif ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail or out:
        out.append(tail)
    return out


def strip_strings(s: str) -> str:
    return re.sub(r"'[^']*'", "''", s)


RE_IDENT = re.compile(r"\b([A-Za-z_]\w*)\b")


def identifiers(expr: str):
    """Variable-ish names in an expression: not calls, keywords or literals."""
    clean = strip_strings(expr)
    found = []
    for m in RE_IDENT.finditer(clean):
        name = m.group(1)
        after = clean[m.end():m.end() + 1]
        if after == "(":          # a function or operator call, not a variable
            continue
        if name in KEYWORDS or name == "_":
            continue
        found.append(name)
    return found


RE_CALL = re.compile(r"^([a-z][a-z0-9_]*)\s*\((.*)\)\s*(?://.*|\*.*)?$")
RE_ASSIGN = re.compile(r"^([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*:=(.*)$")
RE_FOR = re.compile(r"^for\s+([A-Za-z_]\w*)\s*:=\s*(.*)$")


def strip_trailing_comment(code: str) -> str:
    """Drop a trailing // or * comment, without cutting inside a string."""
    quote = False
    for i, ch in enumerate(code):
        if ch == "'":
            quote = not quote
        elif not quote and code.startswith("//", i):
            return code[:i]
    return code


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_outline(args):
    procs = parse(Path(args.file))
    print(Path(args.file).name + ": " + str(len(procs)) + " procedure(s)")
    for p in procs:
        active = sum(1 for r in p.rows if r.is_active)
        print("")
        print("  " + p.name + "   lines " + str(p.start) + "-" +
              str(p.end or "?") + "   " + str(active) + " active code lines / " +
              str(len(p.rows)) + " total")
        for tag, label in (("io", "in  iconic"), ("oo", "out iconic"),
                           ("ic", "in  control"), ("oc", "out control")):
            if p.iface[tag]:
                print("      " + label + ": " + ", ".join(p.iface[tag]))
        calls = {}
        for r in p.rows:
            if not r.is_active:
                continue
            m = RE_CALL.match(strip_trailing_comment(r.stripped))
            if m and m.group(1) not in KEYWORDS:
                calls[m.group(1)] = calls.get(m.group(1), 0) + 1
        if calls:
            top = sorted(calls.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
            print("      most used: " +
                  ", ".join(k + "(" + str(v) + ")" for k, v in top))


def cmd_code(args):
    procs = parse(Path(args.file))
    for p in procs:
        if args.proc and p.name != args.proc:
            continue
        # HDevelop numbers a procedure's body from 1; --prog reports that
        # instead of the .hdev file line, so line references match what the
        # author sees in the IDE.
        numbered = [(i + 1 if args.prog else r.lineno, r)
                    for i, r in enumerate(p.rows)]
        shown = [(n, r) for n, r in numbered
                 if not (args.start and n < args.start)
                 and not (args.end and n > args.end)
                 and not (args.active and not r.is_active)]
        if not shown:
            continue          # a line range rarely spans every procedure
        print("### procedure " + p.name +
              "   [.hdev lines " + str(p.start) + "-" + str(p.end or "?") +
              ("; numbering = HDevelop program lines]" if args.prog else "]"))
        for n, r in shown:
            print(str(n).rjust(5) + "| " + r.text.rstrip())
        print("")


def cmd_grep(args):
    procs = parse(Path(args.file))
    flags = 0 if args.case else re.IGNORECASE
    pat = re.compile(args.pattern, flags)
    hits = 0
    for p in procs:
        for r in p.rows:
            if args.active and not r.is_active:
                continue
            if pat.search(r.text):
                n = (p.rows.index(r) + 1) if args.prog else r.lineno
                print(str(n).rjust(5) + "| " + p.name + ": " +
                      r.text.strip())
                hits += 1
    if not hits:
        print("no match")


def cmd_wrap(args):
    src = args.text if args.text else sys.stdin.read()
    lines = src.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()          # a trailing newline is not a blank code line
    for line in lines:
        line = line.rstrip("\r")
        esc = (line.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        tag = "c" if line.strip().startswith("*") and args.comments else "l"
        print("<" + tag + ">" + esc + "</" + tag + ">")


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------

OPENERS = {"if": "endif", "for": "endfor", "while": "endwhile",
           "try": "endtry", "switch": "endswitch", "repeat": "until"}
CLOSERS = {"endif": "if", "endfor": "for", "endwhile": "while",
           "endtry": "try", "endswitch": "switch", "until": "repeat"}
MIDDLES = {"else": ("if",), "elseif": ("if",), "catch": ("try",),
           "case": ("switch",), "default": ("switch",)}


def leading_keyword(code: str) -> str:
    m = re.match(r"^([a-z]+)\b", code.strip())
    return m.group(1) if m else ""


def check_blocks(proc, problems):
    stack = []
    for r in proc.rows:
        if not r.is_active:
            continue
        kw = leading_keyword(strip_trailing_comment(r.stripped))
        if kw in OPENERS:
            stack.append((kw, r.lineno))
        elif kw in CLOSERS:
            want = CLOSERS[kw]
            if not stack:
                problems.append((r.lineno, "block",
                                 kw + " with no matching " + want))
            elif stack[-1][0] != want:
                problems.append((r.lineno, "block",
                                 kw + " closes " + stack[-1][0] + " opened at line " +
                                 str(stack[-1][1]) + ", expected " +
                                 OPENERS[stack[-1][0]]))
                stack.pop()
            else:
                stack.pop()
        elif kw in MIDDLES:
            if not stack or stack[-1][0] not in MIDDLES[kw]:
                problems.append((r.lineno, "block",
                                 kw + " outside " + "/".join(MIDDLES[kw])))
    for kw, line in stack:
        problems.append((line, "block",
                         kw + " opened here is never closed with " + OPENERS[kw]))


def check_arity(proc, sigs, local_procs, problems, unknown):
    for r in proc.rows:
        if not r.is_active:
            continue
        code = strip_trailing_comment(r.stripped)
        m = RE_CALL.match(code)
        if not m:
            continue
        name, arglist = m.group(1), m.group(2)
        if name in KEYWORDS or name in NO_DOC_INSTRUCTIONS:
            continue
        groups = local_procs.get(name)
        source = "procedure"
        if groups is None:
            groups = sigs.get(name)
            source = "operator"
        if groups is None:
            unknown.setdefault(name, []).append(r.lineno)
            continue
        expected = sum(len(g) for g in groups)
        actual = len([a for a in split_args(arglist) if a != ""]) if arglist.strip() else 0
        if actual != expected:
            flat = " : ".join(", ".join(g) for g in groups)
            problems.append((r.lineno, "arity",
                             name + " called with " + str(actual) + " argument(s), " +
                             source + " takes " + str(expected) +
                             "  ->  " + name + "(" + flat + ")"))


def check_init(proc, sigs, local_procs, problems):
    """Flag variables assigned only inside a conditional branch, read outside.

    HDevelop has no declarations, so a variable that only gets a value on one
    path raises "variable has not been initialized" at runtime on the other -
    typically only on the rare image that takes that path, which is exactly
    when you least want it.
    """
    # One frame per open construct. Constructs that branch (if/try/switch)
    # also carry the id of the branch currently open, so that a variable
    # assigned in every branch is not treated as conditionally assigned,
    # while for/while frames contribute no branch at all.
    stack = []          # list of dicts: {"kind": str, "branch": int|None}
    block_id = 0
    assigns = {}        # var -> list of (line, frozenset of conditional ids)
    reads = {}          # var -> list of (line, frozenset of conditional ids)

    def cond_ids():
        return frozenset(f["branch"] for f in stack if f["branch"] is not None)

    def note_assign(var, line):
        assigns.setdefault(var, []).append((line, cond_ids()))

    def note_read(var, line):
        reads.setdefault(var, []).append((line, cond_ids()))

    # A procedure's input parameters always have a value on entry, so an
    # assignment to one is a reassignment, not the only definition.
    for name in proc.iface["io"] + proc.iface["ic"]:
        assigns.setdefault(name, []).append((0, frozenset()))

    for r in proc.rows:
        if not r.is_active:
            continue
        code = strip_trailing_comment(r.stripped)
        kw = leading_keyword(code)

        if kw in CLOSERS and stack:
            stack.pop()
        if kw in MIDDLES and stack:
            block_id += 1
            stack[-1]["branch"] = block_id

        mf = RE_FOR.match(code)
        if mf:
            note_assign(mf.group(1), r.lineno)
            for v in identifiers(mf.group(2)):
                note_read(v, r.lineno)
        else:
            ma = RE_ASSIGN.match(code)
            if ma:
                note_assign(ma.group(1), r.lineno)
                for v in identifiers(ma.group(2)):
                    note_read(v, r.lineno)
            else:
                mc = RE_CALL.match(code)
                if mc:
                    name, arglist = mc.group(1), mc.group(2)
                    groups = local_procs.get(name) or sigs.get(name)
                    args = split_args(arglist) if arglist.strip() else []
                    if groups and sum(len(g) for g in groups) == len(args):
                        idx = 0
                        for gi, g in enumerate(groups):
                            for _ in g:
                                a = args[idx]
                                is_out = gi in (1, 3)
                                if is_out and re.fullmatch(r"[A-Za-z_]\w*", a):
                                    note_assign(a, r.lineno)
                                else:
                                    for v in identifiers(a):
                                        note_read(v, r.lineno)
                                idx += 1
                    else:
                        for a in args:
                            for v in identifiers(a):
                                note_read(v, r.lineno)
                elif code and kw not in ("global",):
                    for v in identifiers(code):
                        note_read(v, r.lineno)

        if kw in OPENERS:
            branch = None
            if kw in ("if", "try", "switch"):
                block_id += 1
                branch = block_id
            stack.append({"kind": kw, "branch": branch})

    for var, places in assigns.items():
        guard = frozenset.intersection(*[ids for _, ids in places])
        if not guard:
            continue
        first_assign = min(line for line, _ in places)
        # Unsafe when the read sits outside at least one branch that every
        # assignment depended on. Sharing *some* enclosing branch (both inside
        # the same try, say) is not enough to make the read safe.
        outside = [line for line, ids in reads.get(var, [])
                   if line > first_assign and (guard - ids)]
        if outside:
            problems.append((outside[0], "init",
                             var + " is only assigned inside a conditional branch "
                             "(line " + str(first_assign) + ") but read here"))


def check_notes(proc, notes):
    for r in proc.rows:
        if not r.is_active:
            continue
        code = strip_trailing_comment(r.stripped)
        if re.match(r"^stop\s*\(\s*\)", code):
            notes.setdefault("stop() halts execution", []).append(r.lineno)
        if re.match(r"^dev_", code):
            notes.setdefault("dev_* display call", []).append(r.lineno)
        if re.search(r"'[A-Za-z]:[/\\\\]", code):
            notes.setdefault("hard-coded absolute path", []).append(r.lineno)


def cmd_check(args):
    path = Path(args.file)
    print("checking " + path.name)

    try:
        ET.parse(str(path))
        print("  xml: well-formed")
    except ET.ParseError as e:
        print("  XML ERROR: " + str(e))
        print("  HDevelop will refuse to open this file. Fix the markup first.")
        return 1

    root = halcon_root()
    if root is None:
        print("  note: no HALCON installation found, skipping signature checks")
    sigs = Signatures(root)
    procs = parse(path)
    local_procs = {p.name: p.signature_groups() for p in procs}

    total = 0
    for p in procs:
        problems, unknown, notes = [], {}, {}
        check_blocks(p, problems)
        if root:
            check_arity(p, sigs, local_procs, problems, unknown)
            check_init(p, sigs, local_procs, problems)
        check_notes(p, notes)

        print("")
        print("  procedure " + p.name)
        if not problems:
            print("    no structural problems")
        for line, kind, msg in sorted(problems):
            print("    line " + str(line).rjust(5) + "  [" + kind + "] " + msg)
            total += 1
        if unknown and not args.quiet:
            names = sorted(unknown)
            print("    unrecognised call(s) - user procedure in another file, or a "
                  "typo: " + ", ".join(n + " (line " + str(unknown[n][0]) + ")"
                                       for n in names[:10]))
        if notes and not args.quiet:
            for label in sorted(notes):
                lines = notes[label]
                shown = ", ".join(str(n) for n in lines[:8])
                more = "" if len(lines) <= 8 else ", +" + str(len(lines) - 8) + " more"
                print("    note: " + label + " x" + str(len(lines)) +
                      " (lines " + shown + more + ")")

    sigs.save()
    print("")
    print("  " + str(total) + " problem(s) reported")
    return 1 if total else 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("outline", help="procedures, interfaces and extents")
    p.add_argument("file")
    p.set_defaults(func=cmd_outline)

    p = sub.add_parser("code", help="plain HALCON source with .hdev line numbers")
    p.add_argument("file")
    p.add_argument("--proc", help="only this procedure")
    p.add_argument("--start", type=int, help="first .hdev line")
    p.add_argument("--end", type=int, help="last .hdev line")
    p.add_argument("--active", action="store_true",
                   help="hide comments and disabled code")
    p.add_argument("--prog", action="store_true",
                   help="number lines as HDevelop does (procedure body from 1)")
    p.set_defaults(func=cmd_code)

    p = sub.add_parser("grep", help="search code lines, not the XML")
    p.add_argument("file")
    p.add_argument("pattern")
    p.add_argument("--case", action="store_true", help="case sensitive")
    p.add_argument("--active", action="store_true", help="skip disabled code")
    p.add_argument("--prog", action="store_true",
                   help="number lines as HDevelop does (procedure body from 1)")
    p.set_defaults(func=cmd_grep)

    p = sub.add_parser("check", help="static checks against the local HALCON docs")
    p.add_argument("file")
    p.add_argument("--quiet", action="store_true", help="problems only, no notes")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("wrap", help="escape plain code into <l> elements")
    p.add_argument("--text", help="code to wrap (default: read stdin)")
    p.add_argument("--comments", action="store_true",
                   help="emit <c> for lines starting with *")
    p.set_defaults(func=cmd_wrap)

    args = ap.parse_args()
    rc = args.func(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
