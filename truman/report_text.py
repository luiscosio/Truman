"""Safe text rendering for reports: a small Markdown subset and word-level diffs.

Everything is escaped before any markup is added, so recorded text can never
inject HTML. Only http(s) links become anchors.
"""
import difflib
import html
import re


def esc(value) -> str:
    return html.escape(str(value), quote=True)


LINK = re.compile(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)')
CODE = re.compile(r'`([^`\n]+)`')
BOLD = re.compile(r'\*\*(.+?)\*\*')
ITALIC = re.compile(r'(?<![*\w])\*(?![\s*])([^*\n]+?)(?<!\s)\*(?![*\w])')


def inline(text):
    """Escape one line, then apply links, code spans, bold and italics."""
    out = esc(text)
    out = CODE.sub(lambda m: f'<code>{m[1]}</code>', out)
    out = LINK.sub(lambda m: f'<a href="{m[2]}" target="_blank" rel="noreferrer">{m[1]}</a>', out)
    out = BOLD.sub(lambda m: f'<strong>{m[1]}</strong>', out)
    return ITALIC.sub(lambda m: f'<em>{m[1]}</em>', out)


def table(rows):
    cells = [[c.strip() for c in row.strip().strip('|').split('|')] for row in rows]
    head, body = cells[0], [r for r in cells[2:]]
    return ('<div class="md-table"><table><thead><tr>' + ''.join(f'<th>{inline(c)}</th>' for c in head) + '</tr></thead><tbody>'
            + ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in row) + '</tr>' for row in body) + '</tbody></table></div>')


def markdown(text):
    """Render the Markdown subset agents write: headings, lists, tables, quotes, code."""
    lines, out, index = str(text or '').splitlines(), [], 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith('```'):
            block, index = [], index + 1
            while index < len(lines) and not lines[index].strip().startswith('```'):
                block.append(lines[index])
                index += 1
            out.append(f'<pre>{esc(chr(10).join(block))}</pre>')
            index += 1
            continue
        heading = re.match(r'(#{1,6})\s+(.*)', stripped)
        if heading:
            out.append(f'<h4 class="md-h{len(heading[1])}">{inline(heading[2])}</h4>')
            index += 1
            continue
        if stripped.startswith('|') and index + 1 < len(lines) and re.match(r'^\s*\|?[\s:|-]+\|?\s*$', lines[index + 1]) and '-' in lines[index + 1]:
            rows = []
            while index < len(lines) and lines[index].strip().startswith('|'):
                rows.append(lines[index])
                index += 1
            out.append(table(rows))
            continue
        item = re.match(r'([-*+]|\d+[.)])\s+(.*)', stripped)
        if item:
            ordered, items = item[1][0].isdigit(), []
            while index < len(lines):
                match = re.match(r'\s*([-*+]|\d+[.)])\s+(.*)', lines[index])
                if not match or match[1][0].isdigit() != ordered:
                    break
                items.append(f'<li>{inline(match[2])}</li>')
                index += 1
            tag = 'ol' if ordered else 'ul'
            out.append(f'<{tag}>{"".join(items)}</{tag}>')
            continue
        if stripped.startswith('>'):
            quote = []
            while index < len(lines) and lines[index].strip().startswith('>'):
                quote.append(inline(lines[index].strip()[1:].strip()))
                index += 1
            out.append(f'<blockquote>{"<br>".join(quote)}</blockquote>')
            continue
        if re.fullmatch(r'[-*_]{3,}', stripped):
            out.append('<hr>')
            index += 1
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip() and not re.match(r'\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|\|)', lines[index]):
            paragraph.append(inline(lines[index].strip()))
            index += 1
        if not paragraph:
            paragraph.append(inline(stripped))
            index += 1
        out.append(f'<p>{"<br>".join(paragraph)}</p>')
    return ''.join(out)


TOKEN = re.compile(r'\s+|\w+|[^\w\s]')


def segments(a, b, bridge=2):
    """Equal and changed token runs. Changes separated by at most `bridge` words merge,
    so a rewritten phrase reads as one old phrase and one new one, not alternating words."""
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'equal':
            out.append(['equal', a[i1:i2], a[i1:i2]])
        elif out and out[-1][0] == 'change':
            out[-1][1] += a[i1:i2]
            out[-1][2] += b[j1:j2]
        elif len(out) >= 2 and out[-2][0] == 'change' and sum(1 for t in out[-1][1] if t.strip()) <= bridge:
            same = out.pop()
            out[-1][1] += same[1] + a[i1:i2]
            out[-1][2] += same[2] + b[j1:j2]
        else:
            out.append(['change', a[i1:i2], b[j1:j2]])
    return out


def word_diff(before, after, context=14):
    """Before/after text as one run of unchanged, <del> and <ins> spans.

    Long unchanged stretches keep only `context` tokens on each side of a change.
    """
    parts = segments(TOKEN.findall(before or ''), TOKEN.findall(after or ''))
    out = []
    for index, (kind, old, new) in enumerate(parts):
        if kind == 'equal':
            first, last = index == 0, index == len(parts) - 1
            if len(old) > context * 2 + 4 or (first and len(old) > context) or (last and len(old) > context):
                head = [] if first else old[:context]
                tail = [] if last else old[-context:]
                out.append(esc(''.join(head)) + '<span class="gap" title="Unchanged text omitted">…</span>' + esc(''.join(tail)))
            else:
                out.append(esc(''.join(old)))
            continue
        if old:
            out.append(f'<del>{esc("".join(old))}</del>')
        if new:
            out.append(f'<ins>{esc("".join(new))}</ins>')
    return ''.join(out)


def excerpt(text, limit=420):
    """Plain text cut at a word boundary, for previews."""
    flat = re.sub(r'[#*`>|]+', '', str(text or ''))
    flat = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', flat)
    flat = ' '.join(flat.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(' ', 1)[0] + '…'
