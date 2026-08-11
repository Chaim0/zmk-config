#!/usr/bin/env python3
"""
Reformat the layer `bindings = < ... >;` blocks in a ZMK .keymap file so
they look like the boxed, column-aligned style used elsewhere in this repo:
a comment header row of box-drawing characters + key labels above each row
of physical bindings.

Only touches whitespace and comment lines inside `bindings = < ... >;`
blocks that live inside the `keymap { ... }` node (i.e. layers). Behavior
definitions (e.g. hold-tap `bindings = <&kp>, <&kp>;`) are left untouched.
Behavior/keycode tokens themselves are never modified or reordered.

Usage:
    python3 scripts/format_keymap_layers.py path/to/some.keymap [options]

Targets 6x3-per-hand Corne boards: the 3 finger rows always draw a fixed
LEFT+RIGHT (default 6+6) outline and the thumb row always draws a fixed
THUMB_LEFT+THUMB_RIGHT (default 3+3) outline, regardless of how many
tokens a given row actually parsed to - so an unfinished/mismatched row
still gets a full, correctly-shaped outline; only its labels may be off.
The thumb outline sits flush against the two inner (center-most) finger
columns on each hand, so the whole row reads as centered on the board
rather than centered separately under each hand.
"""

import argparse
import re
import sys

GAP = "   "  # spacing between the left and right half of a row


def tokenize_row(line: str) -> list[str]:
    """Split a source line into ZMK binding tokens (each starts with '&')."""
    words = line.split()
    tokens: list[str] = []
    current: list[str] = []
    for word in words:
        if word.startswith("&"):
            if current:
                tokens.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        tokens.append(" ".join(current))
    return tokens


def label_of(token: str) -> str:
    """Derive a short comment label from a binding token."""
    parts = token.split()
    if len(parts) == 1:
        return parts[0].lstrip("&")
    return " ".join(parts[1:])


def half_border(n: int, cw: int, left_c: str, mid_c: str, right_c: str) -> str:
    if n <= 0:
        return ""
    return left_c + mid_c.join(["─" * cw] * n) + right_c


def half_width(n: int, cw: int) -> int:
    """Rendered width of an n-cell half-block (border/label style: n*(cw+1)+1)."""
    return 0 if n <= 0 else n * (cw + 1) + 1


def combine_halves(
    left_str: str, right_str: str, left_n: int, right_n: int, ref_left: int, ref_right: int, cw: int
) -> str:
    """Join a row's two halves against a wider reference block (the finger
    rows). A narrower left half (e.g. a thumb cluster) is pushed flush
    against the right edge of the reference block, and a narrower right
    half is pushed flush against the left edge of its reference block -
    i.e. both halves hug the center gap, so the row reads as centered in
    the keyboard as a whole rather than centered within each hand."""
    if not left_str and not right_str:
        return ""

    ref_left_w = half_width(ref_left, cw)
    ref_right_w = half_width(ref_right, cw)
    left_pad = max(0, ref_left_w - half_width(left_n, cw))
    right_pad = 0

    if not right_str:
        return " " * left_pad + left_str
    if not left_str:
        return " " * (ref_left_w + len(GAP) + right_pad) + right_str

    right_start = ref_left_w + len(GAP) + right_pad
    mid_spaces = max(len(GAP), right_start - (left_pad + len(left_str)))
    return " " * left_pad + left_str + " " * mid_spaces + right_str


def border_line(left_n: int, right_n: int, ref_left: int, ref_right: int, cw: int, kind: str) -> str:
    corners = {
        "top": ("╭", "┬", "╮"),
        "mid": ("├", "┼", "┤"),
        "bottom": ("╰", "┴", "╯"),
    }[kind]
    left_half = half_border(left_n, cw, *corners)
    right_half = half_border(right_n, cw, *corners)
    return "//" + combine_halves(left_half, right_half, left_n, right_n, ref_left, ref_right, cw)


def label_slots(tokens: list[str], n_slots: int) -> list[str]:
    """Map however many tokens a row actually parsed to a fixed number of
    display slots. Short rows leave trailing slots blank; long rows spill
    the extra labels into the last slot. The outline always has n_slots
    cells even when the label-to-key correspondence isn't exact."""
    labels = [label_of(t) for t in tokens]
    if n_slots <= 0:
        return []
    if len(labels) <= n_slots:
        return labels + [""] * (n_slots - len(labels))
    head = labels[: n_slots - 1]
    head.append(" ".join(labels[n_slots - 1 :]))
    return head


def label_line(left_labels: list[str], right_labels: list[str], left_n: int, right_n: int, ref_left: int, ref_right: int, cw: int) -> str:
    def half(labels: list[str]) -> str:
        if not labels:
            return ""
        cells = [f"  {label}".ljust(cw) for label in labels]
        return "│" + "│".join(cells) + "│"

    left_half = half(left_labels)
    right_half = half(right_labels)
    return "//" + combine_halves(left_half, right_half, left_n, right_n, ref_left, ref_right, cw)


def code_line(tokens: list[str], left_n: int, right_n: int, ref_left: int, ref_right: int, cw: int) -> str:
    def half(toks: list[str]) -> str:
        return " ".join(t.ljust(cw + 1) for t in toks)

    left_half = half(tokens[:left_n])
    right_half = half(tokens[left_n:])
    return combine_halves(left_half, right_half, left_n, right_n, ref_left, ref_right, cw).rstrip()


def display_split(row_index: int, opts: argparse.Namespace) -> tuple[int, int]:
    """Fixed outline column counts: this tool targets 6x3-per-hand Corne
    boards, so the finger rows always draw 6+6 cells and the thumb row
    always draws thumb-left+thumb-right cells, regardless of how many
    tokens a given (possibly unfinished) row actually parsed to."""
    if row_index < 3:
        return opts.left_cols, opts.right_cols
    return opts.thumb_left, opts.thumb_right


def format_bindings_block(content: str, indent: str, opts: argparse.Namespace) -> str:
    rows: list[list[str]] = []
    for raw_line in content.split("\n"):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        tokens = tokenize_row(stripped)
        if tokens:
            rows.append(tokens)

    if not rows:
        return content

    cw = opts.cell_width
    inner_indent = indent + "    "
    splits = [display_split(i, opts) for i in range(len(rows))]
    ref_left, ref_right = opts.left_cols, opts.right_cols

    out: list[str] = []
    out.append(inner_indent + border_line(*splits[0], ref_left, ref_right, cw, "top"))
    for i, row in enumerate(rows):
        left_n, right_n = splits[i]
        labels = label_slots(row, left_n + right_n)
        out.append(inner_indent + label_line(labels[:left_n], labels[left_n:], left_n, right_n, ref_left, ref_right, cw))
        code_left_n = len(row) // 2
        code_right_n = len(row) - code_left_n
        out.append(inner_indent + code_line(row, code_left_n, code_right_n, ref_left, ref_right, cw))
        is_last = i == len(rows) - 1
        if is_last:
            out.append(inner_indent + border_line(*splits[i], ref_left, ref_right, cw, "bottom"))
        elif splits[i] == splits[i + 1]:
            out.append(inner_indent + border_line(*splits[i], ref_left, ref_right, cw, "mid"))
        else:
            out.append(inner_indent + border_line(*splits[i], ref_left, ref_right, cw, "bottom"))
            out.append(inner_indent + border_line(*splits[i + 1], ref_left, ref_right, cw, "top"))

    return "\n" + "\n".join(out) + "\n" + indent


def find_keymap_node_span(text: str) -> tuple[int, int]:
    marker = re.search(r'compatible\s*=\s*"zmk,keymap"', text)
    if marker is None:
        raise ValueError('Could not find `compatible = "zmk,keymap"` in file')
    open_brace = text.rfind("{", 0, marker.start())
    if open_brace == -1:
        raise ValueError("Could not find opening brace of keymap node")
    depth = 0
    i = open_brace
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return open_brace, i + 1
        i += 1
    raise ValueError("Could not find matching closing brace of keymap node")


def process(text: str, opts: argparse.Namespace) -> str:
    start, end = find_keymap_node_span(text)
    head, keymap_block, tail = text[:start], text[start:end], text[end:]

    pattern = re.compile(
        r"(?P<pre>[ \t]*)bindings\s*=\s*<(?P<content>.*?)>;", re.DOTALL
    )

    def repl(m: re.Match) -> str:
        indent = m.group("pre")
        formatted = format_bindings_block(m.group("content"), indent, opts)
        return f"{indent}bindings = <{formatted}>;"

    new_keymap_block = pattern.sub(repl, keymap_block)
    return head + new_keymap_block + tail


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keymap_file", help="Path to the .keymap file to reformat in place")
    parser.add_argument("--left-cols", type=int, default=6, help="Finger-row columns, left half (default: 6)")
    parser.add_argument("--right-cols", type=int, default=6, help="Finger-row columns, right half (default: 6)")
    parser.add_argument("--thumb-left", type=int, default=3, help="Thumb-row keys, left half (default: 3)")
    parser.add_argument("--thumb-right", type=int, default=3, help="Thumb-row keys, right half (default: 3)")
    parser.add_argument("--cell-width", type=int, default=10, help="Interior width of each box cell (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Print the result instead of writing the file")
    opts = parser.parse_args()

    with open(opts.keymap_file, "r") as f:
        text = f.read()

    result = process(text, opts)

    if opts.dry_run:
        sys.stdout.write(result)
    else:
        with open(opts.keymap_file, "w") as f:
            f.write(result)
        print(f"Reformatted layer bindings in {opts.keymap_file}")


if __name__ == "__main__":
    main()
