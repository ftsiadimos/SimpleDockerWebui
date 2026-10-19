"""Main routes and WebSocket handlers for LightDockerWebUI.

SSH tunnel support, dynamic tunnel management, and form field updates contributed by
Sven Hofrichter (sven@hofrichter.net)

This module re-exports all routes from split sub-modules for clean organization:
  - ssh_tunnel.py: SSH tunnel management
  - docker_helpers.py: Docker client helpers, stats
  - websocket_handlers.py: WebSocket handlers
  - routes_index.py: Dashboard, docs, about
  - routes_containers.py: Containers, logs, stats, inspect
  - routes_compose.py: Compose, Git Compose
  - routes_infra.py: Images, volumes, networks
  - routes_settings.py: Settings, addcon, terminal
"""
import os
import logging

log = logging.getLogger(__name__)

# Import db, forms, git_service before route modules to avoid circular imports
from app import db
from app.models import DockerServer, GitRepoConfig, ProjectServerMapping, ContainerActivity
from app.forms import AddServerForm, SelectServerForm, GitRepoForm
from app import git_service

# Import all route modules (registers Blueprints)
from app.ssh_tunnel import _docker_client_cache
from app.websocket_handlers import init_sock, sock
from app.routes_index import main_bp
# Import other route modules to register their routes on main_bp
from app import routes_containers  # noqa: F401
from app import routes_compose  # noqa: F401
from app import routes_infra  # noqa: F401
from app import routes_settings  # noqa: F401

# Re-export the combined blueprint
main_bp = main_bp

# WebSocket extension (used by app factory)
sock = sock

# SSH tunnel helpers (used by routes)
from app.ssh_tunnel import (
    _ssh_tunnels,
    _ssh_tunnels_lock,
    _SSHTunnel,
    _open_direct_streamlocal_channel,
    _ssh_connect_kwargs,
    _open_ssh_tunnel,
    _close_ssh_tunnel,
    _tunnel_status,
    _target_label,
    get_docker_base_url,
    conf,
    _docker_client_cache,
)

