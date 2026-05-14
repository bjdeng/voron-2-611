#!/usr/bin/env python3
"""
Parse every [gcode_macro X] body in the given .cfg files as a jinja2 template.
Exit 1 on any TemplateSyntaxError; print one diagnostic per error.
"""
import re
import sys
from pathlib import Path

from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError

MACRO_HEADER = re.compile(r"^\[gcode_macro\s+(\S+)\s*\]\s*$")
GCODE_FIELD = re.compile(r"^gcode\s*:\s*$")


def each_macro_body(path):
    """Yield (macro_name, body_first_line_no, body_text) for each [gcode_macro] block."""
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        m = MACRO_HEADER.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        j = i + 1
        while j < len(lines) and not lines[j].startswith("["):
            if GCODE_FIELD.match(lines[j]):
                body_first = j + 1
                k = body_first
                while k < len(lines) and (
                    lines[k].startswith((" ", "\t")) or lines[k].strip() == ""
                ):
                    k += 1
                body = "\n".join(line.lstrip() for line in lines[body_first:k])
                yield name, body_first + 1, body
                j = k
                continue
            j += 1
        i = j


def main(paths):
    # Klipper uses single-brace variable delimiters: { } instead of {{ }}
    # See vendor/klipper/klippy/extras/gcode_macro.py:
    #   self.env = jinja2.Environment('{%', '%}', '{', '}')
    env = Environment('{%', '%}', '{', '}')
    errors = 0
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue
        for name, lineno, body in each_macro_body(path):
            try:
                env.parse(body)
            except TemplateSyntaxError as e:
                abs_line = lineno + (e.lineno or 1) - 1
                print(f"{path}:{abs_line}: [gcode_macro {name}] {e.message}")
                errors += 1
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
