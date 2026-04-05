"""
security.py — Multi-tier dangerous-code scanner for Remote Code Runner Bot.
Combines substring matching, regex patterns, and AST analysis.
"""

import re
import ast
from typing import Tuple, List

# ─────────────────────────────────────────────────────────────────────────────
# TIER-1a  :  Raw substring / token blocklist  (fast, pre-parse)
# ─────────────────────────────────────────────────────────────────────────────
BANNED_SUBSTRINGS: List[str] = [
    # Dynamic import helpers
    "__import__",
    "importlib",
    "builtins",
    "ctypes",
    "cffi",
    # Networking
    "socket",
    "urllib",
    "http.client",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
    "ssl",
    "asyncio",
    "aiohttp",
    "requests",
    "httpx",
    "pycurl",
    # File-system
    "pathlib",
    "tempfile",
    "shutil",
    "glob",
    "fnmatch",
    # Process / OS
    "subprocess",
    "multiprocessing",
    "threading",
    "signal",
    "pty",
    "tty",
    "atexit",
    # Dangerous execution
    "compile(",
    "codeop",
    "dis.",
    "inspect",
    "traceback",
    # Serialisation exploits
    "pickle",
    "marshal",
    "shelve",
    "copyreg",
    "mmap",
    # Platform probes
    "resource",
    "platform",
    "pwd",
    "grp",
    "termios",
    "fcntl",
    "msvcrt",
    "winreg",
    # Cloud metadata endpoints
    "169.254.169.254",
    "metadata.google",
    # Shell expansion characters
    "`",
    "$(",
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER-1b  :  Compiled regex patterns
# ─────────────────────────────────────────────────────────────────────────────
BANNED_PATTERNS: List[re.Pattern] = [
    re.compile(r'\bos\b'),
    re.compile(r'\bsys\b'),
    re.compile(r'\beval\s*\('),
    re.compile(r'\bexec\s*\('),
    re.compile(r'\bopen\s*\('),
    re.compile(r'__\w+__'),                 # any dunder usage
    re.compile(r'\bimport\s+os\b'),
    re.compile(r'\bimport\s+sys\b'),
    re.compile(r'\bimport\s+subprocess\b'),
    re.compile(r'\bfrom\s+os\b'),
    re.compile(r'\bfrom\s+sys\b'),
    re.compile(r'\bfrom\s+subprocess\b'),
    re.compile(r'\bfrom\s+socket\b'),
    re.compile(r'\bchr\s*\('),              # obfuscation via chr()
    re.compile(r'\bgetattr\s*\('),
    re.compile(r'\bsetattr\s*\('),
    re.compile(r'\bdelattr\s*\('),
    re.compile(r'\bglobals\s*\('),
    re.compile(r'\blocals\s*\('),
    re.compile(r'\bvars\s*\('),
    re.compile(r'\bdir\s*\('),
    re.compile(r'\bhash\s*\('),
    re.compile(r'\bbreakpoint\s*\('),
    re.compile(r'\b__class__\b'),
    re.compile(r'\b__mro__\b'),
    re.compile(r'\b__subclasses__\b'),
    re.compile(r'\b__bases__\b'),
    re.compile(r'\b__globals__\b'),
    re.compile(r'\b__builtins__\b'),
    re.compile(r'\b__code__\b'),
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER-2  :  AST-level analysis
# ─────────────────────────────────────────────────────────────────────────────
BANNED_AST_MODULES: frozenset = frozenset({
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
    "ctypes", "pickle", "marshal", "multiprocessing", "threading", "signal",
    "urllib", "http", "ftplib", "smtplib", "ssl", "asyncio", "resource",
    "platform", "mmap", "tempfile", "glob", "builtins", "gc",
    "inspect", "dis", "traceback", "code", "codeop", "pty", "tty",
    "requests", "aiohttp", "httpx", "cffi", "ctypes",
})

BANNED_BUILTIN_CALLS: frozenset = frozenset({
    "eval", "exec", "compile", "open", "__import__",
    "getattr", "setattr", "delattr", "globals", "locals",
    "vars", "dir", "chr", "breakpoint",
})

BANNED_DUNDER_ATTRS: frozenset = frozenset({
    "__class__", "__mro__", "__subclasses__", "__globals__",
    "__code__", "__builtins__", "__dict__", "__base__", "__bases__",
    "__import__", "__loader__", "__spec__",
})


class _ASTScanner(ast.NodeVisitor):
    def __init__(self):
        self.violations: List[str] = []

    def _add(self, msg: str):
        self.violations.append(msg)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in BANNED_AST_MODULES:
                self._add(f"Forbidden import '{alias.name}' at line {node.lineno}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = (node.module or "").split(".")[0]
        if module in BANNED_AST_MODULES:
            self._add(f"Forbidden from-import '{node.module}' at line {node.lineno}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id in BANNED_BUILTIN_CALLS:
                self._add(f"Forbidden call '{node.func.id}()' at line {node.lineno}")
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in BANNED_DUNDER_ATTRS:
                self._add(
                    f"Forbidden attribute call '.{node.func.attr}()'"
                    f" at line {node.lineno}"
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in BANNED_DUNDER_ATTRS:
            lineno = getattr(node, "lineno", "?")
            self._add(f"Forbidden dunder attribute '.{node.attr}' at line {lineno}")
        self.generic_visit(node)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def scan_code(source: str) -> Tuple[bool, List[str]]:
    """
    Scan *source* (raw Python source text) for dangerous constructs.

    Returns
    -------
    (is_safe, violations)
        is_safe    : True  → passed all checks; safe to execute
        violations : list of human-readable violation strings (empty if safe)
    """
    violations: List[str] = []

    # Tier-1a  substring scan
    lower_src = source.lower()
    for token in BANNED_SUBSTRINGS:
        if token.lower() in lower_src:
            violations.append(f"Blocked keyword/pattern: '{token}'")

    # Tier-1b  regex scan
    for pattern in BANNED_PATTERNS:
        if pattern.search(source):
            violations.append(f"Blocked regex match: /{pattern.pattern}/")

    # Tier-2  AST scan
    try:
        tree = ast.parse(source)
        visitor = _ASTScanner()
        visitor.visit(tree)
        violations.extend(visitor.violations)
    except SyntaxError as exc:
        violations.append(f"Syntax error in submitted file: {exc}")

    # Deduplicate while preserving order
    seen: set = set()
    unique: List[str] = []
    for v in violations:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    return (len(unique) == 0), unique


def scan_file(filepath: str) -> Tuple[bool, List[str]]:
    """Read *filepath* then delegate to scan_code()."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    return scan_code(source)
