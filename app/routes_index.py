"""Dashboard, documentation, and about routes."""
import os
import re
import html as html_module

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.models import DockerServer
from app.forms import SelectServerForm
from app.ssh_tunnel import _docker_client_cache

main_bp = Blueprint('main', __name__)


def _read_version() -> str:
    """Return the contents of the top-level VERSION file (stripped).

    If the file cannot be read for any reason we return ``"unknown"`` so the
    UI doesn't break. This helper lives here because it is only used by the
    simple ``/about`` view; no need to clutter the app config.
    """
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        with open(os.path.join(root, 'VERSION'), 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return 'unknown'


@main_bp.route('/', methods=['GET', 'POST'])
def index():
    """Dashboard: show summary metrics and recent activity."""
    from app.docker_helpers import get_dashboard_stats
    from app.ssh_tunnel import conf

    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()

    def get_server_label(s):
        return s.display_name

    select_form.server.choices = [(s.id, get_server_label(s)) for s in servers]

    if request.method == 'POST' and 'server' in request.form:
        server_id = None
        if select_form.validate_on_submit():
            server_id = select_form.server.data
        else:
            raw = request.form.get('server')
            try:
                server_id = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                server_id = None

        if server_id is None:
            flash('Invalid server selection.', 'danger')
            return redirect(url_for('main.index'))

        server = DockerServer.query.get(server_id)
        if server:
            try:
                if server.is_ssh_tunnel:
                    from app.ssh_tunnel import _open_ssh_tunnel
                    _open_ssh_tunnel(server)
                    base_url = server.connection_url
                else:
                    base_url = f"tcp://{server.host}:{server.port}" if server.is_configured else 'unix://var/run/docker.sock'
                import docker
                client = docker.DockerClient(base_url=base_url, timeout=60)
                client.ping()
                DockerServer.set_active(server_id)
                _docker_client_cache.clear()
                flash(f'Connected to "{server.display_name}".', 'success')
            except docker.errors.DockerException as exc:
                flash(f"Cannot connect to Docker at {base_url}: {exc}", 'warning')
        return redirect(url_for('main.index'))

    # Ensure there's an active server
    if not active_server and servers:
        active_server = servers[0]
        DockerServer.set_active(active_server.id)

    if active_server:
        select_form.server.data = active_server.id

    stats = get_dashboard_stats()

    return render_template('index.html',
                           servers_count=stats['servers_count'],
                           containers_count=stats['containers_count'],
                           running_count=stats['running_count'],
                           images_count=stats['images_count'],
                           total_images=stats['total_images'],
                           total_images_size_gb=stats['total_images_size_gb'],
                           networks_count=stats['networks_count'],
                           volumes_count=stats['volumes_count'],
                           compose_stacks_count=stats['compose_stacks_count'],
                           git_compose_total=stats['git_compose_total'],
                           recent_activity=stats['recent_activity'],
                           select_form=select_form)


@main_bp.route('/api/stats', methods=['GET'])
def api_stats():
    """API endpoint returning dashboard stats as JSON."""
    from app.docker_helpers import get_dashboard_stats
    stats = get_dashboard_stats()
    return jsonify(stats)


@main_bp.route('/about', methods=['GET'])
def about():
    version = _read_version()
    return render_template('about.html', version=version)


# ------------------------------------------------------------------
# Documentation routes
# ------------------------------------------------------------------

_DOCS_DIR = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), 'docs')
_DOCS_REGISTRY = [
    {
        'slug': 'git-compose-guide',
        'file': 'git-compose-guide.md',
        'title': 'Git Compose — Deploy Guide',
        'description': 'How to use Git Compose to deploy projects to Docker servers without CI/CD.',
    },
    {
        'slug': 'gitea-actions',
        'file': 'gitea-actions-example.md',
        'title': 'Gitea Actions Integration',
        'description': 'Deploy docker-compose projects automatically via Gitea Actions CI/CD.',
    },
    {
        'slug': 'ssh-tunnel',
        'file': 'ssh-tunnel.md',
        'title': 'SSH Tunnel — Docker Remote Access',
        'description': 'Set up a restricted SSH user and tunnel to securely access a remote Docker daemon.',
    },
]


def _md_to_html(md_text: str) -> str:
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


@main_bp.route('/docs')
def docs():
    """Documentation index page."""
    return render_template('docs.html', docs=_DOCS_REGISTRY)


@main_bp.route('/docs/<slug>')
def docs_page(slug):
    """Render a single documentation page from a Markdown file."""
    doc = next((d for d in _DOCS_REGISTRY if d['slug'] == slug), None)
    if not doc:
        flash('Documentation page not found.', 'warning')
        return redirect(url_for('main.docs'))

    file_path = os.path.join(_DOCS_DIR, doc['file'])
    if not os.path.isfile(file_path):
        flash('Documentation file missing.', 'danger')
        return redirect(url_for('main.docs'))

    with open(file_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    html_content = _md_to_html(md_content)
    return render_template('docs_page.html', title=doc['title'], content=html_content)
