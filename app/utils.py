"""Utility functions shared across routes."""
import os
import re
import html as html_module


def read_version() -> str:
    """Return the contents of the top-level VERSION file (stripped).

    If the file cannot be read for any reason we return ``"unknown"`` so the
    UI doesn't break.
    """
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        with open(os.path.join(root, 'VERSION'), 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return 'unknown'


def md_to_html(md_text: str) -> str:
    """Convert simple Markdown to HTML without external dependencies."""
    lines = md_text.split('\n')
    html_parts = []
    in_code_block = False
    in_list = False
    in_table = False
    table_header_done = False

    for line in lines:
        if line.strip().startswith('```'):
            if in_code_block:
                html_parts.append('</code></pre>')
                in_code_block = False
            else:
                in_code_block = True
                html_parts.append('<pre><code>')
            continue
        if in_code_block:
            html_parts.append(html_module.escape(line))
            continue

        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            if in_table:
                html_parts.append('</tbody></table>')
                in_table = False
                table_header_done = False
            html_parts.append('')
            continue

        if '|' in stripped and stripped.startswith('|'):
            cells = [c.strip() for c in stripped.strip('|').split('|')]
            if all(re.match(r'^[:\-]+$', c) for c in cells):
                table_header_done = True
                continue
            if not in_table:
                in_table = True
                table_header_done = False
                html_parts.append('<table class="table table-bordered"><thead><tr>')
                for c in cells:
                    html_parts.append(f'<th>{_md_inline(c)}</th>')
                html_parts.append('</tr></thead><tbody>')
                continue
            html_parts.append('<tr>')
            for c in cells:
                html_parts.append(f'<td>{_md_inline(c)}</td>')
            html_parts.append('</tr>')
            continue

        if in_table:
            html_parts.append('</tbody></table>')
            in_table = False
            table_header_done = False

        m = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if m:
            level = len(m.group(1))
            html_parts.append(f'<h{level}>{_md_inline(m.group(2))}</h{level}>')
            continue

        m = re.match(r'^[-*]\s+(.*)', stripped)
        if m:
            if not in_list:
                html_parts.append('<ul>')
                in_list = True
            html_parts.append(f'<li>{_md_inline(m.group(1))}</li>')
            continue

        m = re.match(r'^\d+\.\s+(.*)', stripped)
        if m:
            if not in_list:
                html_parts.append('<ol>')
                in_list = True
            html_parts.append(f'<li>{_md_inline(m.group(1))}</li>')
            continue

        if in_list:
            html_parts.append('</ul>')
            in_list = False

        html_parts.append(f'<p>{_md_inline(stripped)}</p>')

    if in_code_block:
        html_parts.append('</code></pre>')
    if in_list:
        html_parts.append('</ul>')
    if in_table:
        html_parts.append('</tbody></table>')

    return '\n'.join(html_parts)


def _md_inline(text: str) -> str:
    """Handle inline markdown: bold, italic, code, links."""
    text = html_module.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text
