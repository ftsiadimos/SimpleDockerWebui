"""Global context processors for Jinja2 templates."""
from flask import request
from app.forms import SelectServerForm
from app.models import DockerServer


def _get_server_label(server):
    """Return a human-readable label for a server."""
    label = server.display_name or server.host
    if server.host and server.port:
        label = f"{label}:{server.port}"
    return label


def select_form_processor():
    """Make select_form available in all templates."""
    form = SelectServerForm()
    servers = DockerServer.query.filter_by(is_active=True).all()
    if servers:
        form.server.choices = [(s.id, _get_server_label(s)) for s in servers]
    else:
        form.server.choices = []
    active = DockerServer.get_active()
    if active:
        form.server.data = active.id
    return {'select_form': form}
