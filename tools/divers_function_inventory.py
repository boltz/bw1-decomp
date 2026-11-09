from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Definition:
    signature: str
    start: int
    body_start: int
    end: int
    line: int


def masked_source(source):
    lines = []
    continuation = False
    for line in source.splitlines(keepends=True):
        directive = continuation or re.match(r"^\s*#", line)
        continuation = bool(directive and line.rstrip("\r\n").endswith("\\"))
        lines.append(re.sub(r"[^\r\n]", " ", line) if directive else line)
    source = "".join(lines)
    tokens = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
    return tokens.sub(lambda m: re.sub(r"[^\r\n]", " ", m[0]), source)


def definitions(source):
    masked = masked_source(source)
    depth = 0
    boundary = 0
    active = None
    result = []
    for offset, char in enumerate(masked):
        if char == "{" and depth == 0:
            header = masked[boundary:offset].strip()
            start = boundary + len(masked[boundary:offset]) - len(masked[boundary:offset].lstrip())
            if "(" in header and re.search(r"\)(?:\s+(?:const|volatile))*\s*$", header):
                active = (start, offset)
            elif header.endswith("="):
                active = None
            elif re.fullmatch(r"struct\s+[A-Za-z_]\w*", header):
                closing = masked.find("}", offset + 1)
                members = masked[offset + 1:closing] if closing >= 0 else ""
                field = r"\s*[A-Za-z_]\w*(?:\s*\*)*\s+[A-Za-z_]\w*\s*;"
                if closing < 0 or not re.fullmatch(r"(?:" + field + r")*\s*", members):
                    raise ValueError("Unsupported type body; cannot omit possible methods")
                active = None
            else:
                raise ValueError("Unsupported top-level scope at line %d: %s" %
                                 (source.count("\n", 0, start) + 1, header[:120]))
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced closing brace")
            if depth == 0:
                if active is not None:
                    start, opening = active
                    result.append(Definition(" ".join(source[start:opening].split()), start,
                                             opening, offset + 1, source.count("\n", 0, start) + 1))
                active = None
                boundary = offset + 1
        elif char == ";" and depth == 0:
            boundary = offset + 1
    if depth:
        raise ValueError("Unbalanced braces")
    independent = {m.end() - 1 for m in re.finditer(r"^([^\n;{}]+\([^;{}]*\))(?:\s+(?:const|volatile))*\s*\{", masked, re.M)
                   if not m[1].startswith(("\t", " ", "#"))}
    if independent != {x.body_start for x in result}:
        raise ValueError("Independent function-body inventories disagree")
    return result


def function_inventory(source):
    return [{"id": "F%03d" % index, "line": definition.line, "signature": definition.signature}
            for index, definition in enumerate(definitions(source))]
