from pathlib import PurePosixPath
import re

from divers_function_inventory import definitions


_TOKENS = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_IMPLEMENTATION_SUFFIXES = {".inc", ".c", ".cc", ".cpp", ".cxx"}


def translation_unit_inventory(files, root, implementation_files=()):
    """Inventory explicit implementation files with physical citation locations.

    Headers remain declaration context, as in the original monolithic review.
    Unlisted implementation includes, macro includes, cycles, repeated includes
    and functions spanning physical files fail closed.
    """
    implementations = list(implementation_files)
    if len(implementations) != len(set(implementations)) or root in implementations:
        raise ValueError("Duplicate implementation manifest entry")
    for path in [root, *implementations]:
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts or str(p) != path:
            raise ValueError("Noncanonical implementation path")
        if path not in files:
            raise ValueError("Missing implementation file: " + path)
    if any(PurePosixPath(p).suffix.lower() not in _IMPLEMENTATION_SUFFIXES for p in implementations):
        raise ValueError("Manifest must identify implementation files")
    expanded, origins, consumed = [], [], set()

    def visit(path):
        if path in consumed:
            raise ValueError("Repeated or cyclic implementation include: " + path)
        consumed.add(path)
        source = files[path]
        if source and not source.endswith("\n"):
            raise ValueError("Implementation file must end with newline: " + path)
        scan = _TOKENS.sub(lambda m: re.sub(r"[^\r\n]", " ", m[0])
                           if m[0].startswith(("//", "/*")) else m[0], source)
        for line_number, (line, scanned) in enumerate(zip(source.splitlines(keepends=True), scan.splitlines(keepends=True)), 1):
            include = re.match(r"^\s*#\s*include\b(.*)", scanned)
            if include:
                operand = include[1].strip()
                literal = re.fullmatch(r'"([^"\n]+)"|<([^>\n]+)>', operand)
                if not literal:
                    raise ValueError("Unsupported include operand: " + path)
                name = literal[1] or literal[2]
                if PurePosixPath(name).suffix.lower() in _IMPLEMENTATION_SUFFIXES:
                    if literal[1] is None or ".." in PurePosixPath(name).parts or PurePosixPath(name).is_absolute():
                        raise ValueError("Unsupported implementation include path")
                    child = str(PurePosixPath(path).parent / name)
                    if child not in implementations:
                        raise ValueError("Unlisted implementation include: " + child)
                    visit(child)
                    continue
            expanded.append(line)
            origins.append((path, line_number))

    visit(root)
    if consumed != {root, *implementations}:
        raise ValueError("Unconsumed implementation manifest entries")
    source = "".join(expanded)
    functions = []
    for index, definition in enumerate(definitions(source)):
        path, line = origins[definition.line - 1]
        last_line = source.count("\n", 0, definition.end - 1)
        if any(p != path for p, _ in origins[definition.line - 1:last_line + 1]):
            raise ValueError("Function spans physical implementation files")
        functions.append({"id": "F%03d" % index, "path": path,
                          "line": line, "signature": definition.signature})
    return source, functions
