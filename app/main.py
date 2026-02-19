"""Main routes and WebSocket handlers for LightDockerWebUI."""
import os
import subprocess

import docker
import paramiko # type: ignore
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_sock import Sock # type: ignore
import logging

log = logging.getLogger(__name__)

from app import db  # Only import db, not app, to avoid circular import
from app.models import DockerServer
from app.forms import AddServerForm, SelectServerForm

main_bp = Blueprint('main', __name__)
sock = Sock()


def init_sock(app):
    """Initialize the WebSocket extension with the app."""
    sock.init_app(app)


def _human_size(bytes_num: int) -> str:
    """Return human-readable size string from bytes (KB/MB/GB).

    Keep output short (e.g. "12.3 MB", "1.23 GB") used for image sizes.
    """
    try:
        b = float(bytes_num)
    except Exception:
        return "0 B"
    units = [(1024**3, 'GB'), (1024**2, 'MB'), (1024, 'KB')]
    for thresh, unit in units:
        if b >= thresh:
            return f"{b / thresh:.2f} {unit}"
    return f"{b:.0f} B"

# Legacy per-command container terminal removed. Interactive PTY via
# `/container` WebSocket provides full TTY shell; per-socket workdir no
# longer required.

# Cache for Docker client to avoid reconnecting on every request
_docker_client_cache = {}

import time


def get_docker_base_url():
    """Get the Docker base URL from the active server configuration."""
    server = DockerServer.get_active()
    if not server or not server.is_configured:
        return 'unix://var/run/docker.sock', server
    return f"tcp://{server.host}:{server.port}", server


def conf(use_cache=True):
    """
    Return a Docker client and the Owner record.

    If the Owner record does not specify a host/port, connect to the
    local Docker daemon via the Unix socket.

    Args:
        use_cache: If True, reuse cached client for the same base_url.

    Raises:
        ValueError: If the Docker endpoint cannot be reached.
    """
    base_url, serverurl = get_docker_base_url()

    # Return cached client if available and valid
    if use_cache and base_url in _docker_client_cache:
        try:
            client = _docker_client_cache[base_url]
            client.ping()
            return client, serverurl
        except docker.errors.DockerException:
            # Client is stale, remove from cache
            _docker_client_cache.pop(base_url, None)

    try:
        client = docker.DockerClient(base_url=base_url, timeout=60)
        client.ping()
        if use_cache:
            _docker_client_cache[base_url] = client
    except docker.errors.DockerException as exc:
        raise ValueError(f"Cannot connect to Docker at {base_url}: {exc}") from exc

    return client, serverurl

@main_bp.route('/', methods=['GET', 'POST'])
def index():
    """Dashboard: show summary metrics and recent activity."""
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
            log.warning("Server selection did not validate; fallback parsing server=%r -> %r", raw, server_id)

        if server_id is None:
            flash('Invalid server selection.', 'danger')
            return redirect(url_for('main.index'))

        server = DockerServer.query.get(server_id)
        if server:
            base_url = f"tcp://{server.host}:{server.port}" if server.is_configured else 'unix://var/run/docker.sock'
            try:
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

    servers_count = len(servers)
    containers_count = 0
    running_count = 0
    images_count = 0
    total_images = 0
    total_images_size_gb = "0.00 GB"
    networks_count = 0
    volumes_count = 0
    compose_stacks_count = 0

    try:
        client, serverurl = conf()
        raw_containers = client.containers.list(all=True)
        containers_count = len(raw_containers)
        running_count = sum(1 for c in raw_containers if getattr(c, 'status', '') == 'running')
        images_count = len({ (c.attrs.get('Config', {}).get('Image', '') if getattr(c, 'attrs', None) else '') for c in raw_containers })

        # new totals: actual images on the daemon, networks and volumes
        try:
            images = client.images.list()
            total_images = len(images)

            # sum image sizes (use attrs['Size'] when available) and format as GB
            total_images_size_bytes = 0
            for img in images:
                try:
                    total_images_size_bytes += img.attrs.get('Size', 0) if getattr(img, 'attrs', None) else 0
                except Exception:
                    # ignore individual image read errors
                    continue
            total_images_size_gb = f"{(total_images_size_bytes / (1024 ** 3)):.2f} GB"
        except Exception:
            total_images = 0
            total_images_size_gb = "0.00 GB"
        try:
            networks_count = len(client.networks.list())
        except Exception:
            networks_count = 0
        try:
            volumes_count = len(client.volumes.list())
        except Exception:
            volumes_count = 0

        # compose stacks: find unique compose project names from container labels
        try:
            compose_projects = set()
            for c in raw_containers:
                labels = getattr(c, 'labels', {}) or {}
                proj = labels.get('com.docker.compose.project')
                if proj:
                    compose_projects.add(proj)
            compose_stacks_count = len(compose_projects)
        except Exception:
            compose_stacks_count = 0

        recent_activity = []
        for c in raw_containers[-8:]:
            try:
                img = c.attrs.get('Config', {}).get('Image', '') if getattr(c, 'attrs', None) else ''
            except Exception:
                img = ''
            recent_activity.append({
                'name': getattr(c, 'name', '') or '',
                'status': getattr(c, 'status', '') or '',
                'image': img,
            })

        return render_template('index.html',
                               servers_count=servers_count,
                               containers_count=containers_count,
                               running_count=running_count,
                               images_count=images_count,
                               total_images=total_images,
                               total_images_size_gb=total_images_size_gb,
                               networks_count=networks_count,
                               volumes_count=volumes_count,
                               compose_stacks_count=compose_stacks_count,
                               recent_activity=recent_activity,
                               select_form=select_form)
    except ValueError as err:
        flash(str(err), 'warning')
        return render_template('index.html',
                               servers_count=servers_count,
                               containers_count=containers_count,
                               running_count=running_count,
                               images_count=images_count,
                               total_images=0,
                               total_images_size_gb="0.00 GB",
                               networks_count=0,
                               volumes_count=0,
                               compose_stacks_count=0,
                               recent_activity=[],
                               select_form=select_form)




@main_bp.route('/containers', methods=['GET', 'POST'])
def containers():
    """Full containers listing (moved from index)."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()

    def get_server_label(s):
        return s.display_name

    select_form.server.choices = [(s.id, get_server_label(s)) for s in servers]
    if active_server:
        select_form.server.data = active_server.id

    try:
        client, serverurl = conf()
        raw_containers = client.containers.list(all=True)

        containers = []
        for c in raw_containers:
            try:
                image_name = c.attrs.get('Config', {}).get('Image', '') if getattr(c, 'attrs', None) else ''
            except Exception:
                image_name = ''
            containers.append({
                'id': c.id,
                'name': getattr(c, 'name', '') or '',
                'status': getattr(c, 'status', '') or '',
                'ports': getattr(c, 'ports', {}) or {},
                'image': image_name,
            })

        return render_template('containers.html', containers=containers, serverurl=serverurl, select_form=select_form)
    except ValueError as err:
        flash(str(err), 'warning')
        return render_template('containers.html', containers=[], serverurl=active_server, select_form=select_form)


@main_bp.route('/favicon.ico')
def favicon():
    """Serve app favicon (avoid 404s from browsers requesting /favicon.ico)."""
    return current_app.send_static_file('dockermanager.png')


@main_bp.route('/about', methods=['GET'])
def about():
    return render_template('about.html')


@main_bp.route('/settings', methods=['GET','POST'])
def settings():
    """User settings: select UI theme."""
    current = request.cookies.get('ldwui_theme', 'default')
    themes = [('default','Default'), ('terminal-dark','Terminal Dark')]

    if request.method == 'POST':
        theme = request.form.get('theme', 'default')
        if theme not in [t[0] for t in themes]:
            theme = 'default'
        resp = redirect(url_for('main.settings'))
        # persist for 30 days
        resp.set_cookie('ldwui_theme', theme, max_age=30*24*3600)
        flash('Theme updated.', 'success')
        return resp

    return render_template('settings.html', current_theme=current, themes=themes)


@main_bp.route('/compose', methods=['GET', 'POST'])
def compose():
    """Manage Docker Compose projects."""
    home = os.path.expanduser('~')
    base_url, server_obj = get_docker_base_url()
    env = os.environ.copy()
    env['DOCKER_HOST'] = base_url
    
    if request.method == 'POST':
        action = request.form.get('action')
        compose_dir = request.form.get('compose_dir')
        if not compose_dir:
            flash('Invalid compose directory.', 'danger')
            return redirect(url_for('main.compose'))
        
        # Determine if remote server
        is_remote = (server_obj.host and 
                    server_obj.host not in ['localhost', '127.0.0.1', ''] and 
                    server_obj.user)
        
        if action == 'start':
            if is_remote:
                try:
                    ssh_client = paramiko.SSHClient()
                    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh_client.connect(server_obj.host, username=server_obj.user, password=server_obj.password)
                    cmd = f'cd "{compose_dir}" && docker compose -f docker-compose.yml up -d'
                    stdin, stdout, stderr = ssh_client.exec_command(cmd)
                    exit_code = stdout.channel.recv_exit_status()
                    result_stdout = stdout.read().decode()
                    result_stderr = stderr.read().decode()
                    ssh_client.close()
                    result = type('Result', (), {'returncode': exit_code, 'stdout': result_stdout, 'stderr': result_stderr})()
                except Exception as e:
                    flash(f'SSH error: {str(e)}', 'danger')
                    return redirect(url_for('main.compose'))
            else:
                command = f'docker compose -f "{os.path.join(compose_dir, "docker-compose.yml")}" up -d'
                try:
                    result = subprocess.run(command, shell=True, env=env, capture_output=True, text=True, timeout=60)
                except subprocess.TimeoutExpired:
                    flash('Timeout starting compose.', 'danger')
                    return redirect(url_for('main.compose'))
            
            if result.returncode == 0:
                flash(f'Compose in {compose_dir} started successfully.', 'success')
            else:
                flash(f'Error starting compose in {compose_dir}: {result.stderr}', 'danger')
                
        elif action == 'stop':
            if is_remote:
                try:
                    ssh_client = paramiko.SSHClient()
                    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh_client.connect(server_obj.host, username=server_obj.user, password=server_obj.password)
                    cmd = f'cd "{compose_dir}" && docker compose -f docker-compose.yml stop'
                    stdin, stdout, stderr = ssh_client.exec_command(cmd)
                    exit_code = stdout.channel.recv_exit_status()
                    result_stdout = stdout.read().decode()
                    result_stderr = stderr.read().decode()
                    ssh_client.close()
                    result = type('Result', (), {'returncode': exit_code, 'stdout': result_stdout, 'stderr': result_stderr})()
                except Exception as e:
                    flash(f'SSH error: {str(e)}', 'danger')
                    return redirect(url_for('main.compose'))
            else:
                command = f'docker compose -f "{os.path.join(compose_dir, "docker-compose.yml")}" stop'
                try:
                    result = subprocess.run(command, shell=True, env=env, capture_output=True, text=True, timeout=60)
                except subprocess.TimeoutExpired:
                    flash('Timeout stopping compose.', 'danger')
                    return redirect(url_for('main.compose'))
            
            if result.returncode == 0:
                flash(f'Compose in {compose_dir} stopped successfully.', 'success')
            else:
                flash(f'Error stopping compose in {compose_dir}: {result.stderr}', 'danger')
        
        return redirect(url_for('main.compose'))
    
    # GET: find all compose projects from containers on the server
    try:
        client, server = conf()
        containers = client.containers.list(all=True)
        compose_projects_dict = {}
        for container in containers:
            labels = container.labels or {}
            if 'com.docker.compose.project' in labels:
                project = labels['com.docker.compose.project']
                working_dir = labels.get('com.docker.compose.project.working_dir', '')
                service = labels.get('com.docker.compose.service', '')
                if project not in compose_projects_dict:
                    compose_projects_dict[project] = {
                        'dir': working_dir,
                        'path': os.path.join(working_dir, 'docker-compose.yml'),
                        'services': set(),
                        'running': False
                    }
                compose_projects_dict[project]['services'].add(service)
                if container.status == 'running':
                    compose_projects_dict[project]['running'] = True
        compose_projects = list(compose_projects_dict.values())
        for p in compose_projects:
            p['services'] = list(p['services'])
    except ValueError as e:
        compose_projects = []
        flash(f'Error connecting to Docker server: {e}', 'danger')
    
    running_count = sum(1 for p in compose_projects if p['running'])
    stopped_count = len(compose_projects) - running_count
    
    return render_template('compose.html', compose_projects=compose_projects, running_count=running_count, stopped_count=stopped_count)


@main_bp.route('/images', methods=['GET','POST'])
def images():
    """Images management and pruning."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()
    select_form.server.choices = [(s.id, s.display_name) for s in servers]
    if active_server:
        select_form.server.data = active_server.id

    images_count = 0
    dangling_count = 0
    try:
        client, serverurl = conf()
        images = client.images.list()
        images_count = len(images)
        try:
            prunable_images_raw = client.images.list(filters={'dangling': True})
            dangling_count = len(prunable_images_raw)
        except Exception:
            # fallback: count images with no repo tags
            prunable_images_raw = [i for i in images if not getattr(i, 'tags', None)]
            dangling_count = len(prunable_images_raw)

        # build image list for display (short id, tags, size, prunable)
        images_list = []
        prunable_ids = {getattr(i, 'id', '') for i in prunable_images_raw}
        for i in images:
            iid = (getattr(i, 'id', '') or '')[:12]
            tags = ', '.join(getattr(i, 'tags', []) or ['<none>:<none>'])
            size_bytes = 0
            try:
                size_bytes = int(i.attrs.get('Size', 0)) if getattr(i, 'attrs', None) else 0
            except Exception:
                size_bytes = 0
            images_list.append({
                'id': iid,
                'tags': tags,
                'size': _human_size(size_bytes),
                'prunable': (getattr(i, 'id', '') in prunable_ids)
            })

        # prepare short list of prunable images for preview
        prunable_preview = []
        for i in prunable_images_raw[:5]:
            prunable_preview.append({
                'id': (getattr(i, 'id', '') or '')[:12],
                'tags': ', '.join(getattr(i, 'tags', []) or ['<none>:<none>'])
            })

        if request.method == 'POST' and request.form.get('action') == 'prune':
            try:
                result = client.images.prune()
                reclaimed = result.get('SpaceReclaimed', 0)
                deleted = result.get('ImagesDeleted') or []
                num_deleted = len(deleted) if isinstance(deleted, list) else 1
                flash(f'Pruned {num_deleted} images — reclaimed {reclaimed // (1024**2)} MB', 'success')
            except Exception as exc:
                flash(f'Error pruning images: {exc}', 'danger')
            return redirect(url_for('main.images'))

        return render_template('images.html', images_count=images_count, dangling_count=dangling_count, images_list=images_list, prunable_preview=prunable_preview, select_form=select_form)
    except ValueError as err:
        flash(str(err), 'warning')
        return render_template('images.html', images_count=0, dangling_count=0, select_form=select_form)


@main_bp.route('/volumes', methods=['GET','POST'])
def volumes():
    """Volumes management and pruning."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()
    select_form.server.choices = [(s.id, s.display_name) for s in servers]
    if active_server:
        select_form.server.data = active_server.id

    volumes_count = 0
    dangling_count = 0
    try:
        client, serverurl = conf()
        volumes = client.volumes.list() or []
        volumes_count = len(volumes)
        try:
            prunable = client.volumes.list(filters={'dangling': True})
            dangling_count = len(prunable)
        except Exception:
            prunable = []
            dangling_count = 0

        # build volumes list for display and a preview of prunable volumes
        volumes_list = []
        prunable_names = {v.name for v in prunable}
        for v in volumes:
            name = getattr(v, 'name', '')
            mountpoint = (v.attrs.get('Mountpoint') if getattr(v, 'attrs', None) else '') or ''
            driver = (v.attrs.get('Driver') if getattr(v, 'attrs', None) else '') or ''
            volumes_list.append({
                'name': name,
                'driver': driver,
                'mountpoint': mountpoint,
                'prunable': (name in prunable_names)
            })
        prunable_preview = [ {'name': v.name} for v in prunable[:5] ]

        if request.method == 'POST' and request.form.get('action') == 'prune':
            try:
                result = client.volumes.prune()
                deleted = result.get('VolumesDeleted') or []
                num_deleted = len(deleted)
                flash(f'Pruned {num_deleted} volumes', 'success')
            except Exception as exc:
                flash(f'Error pruning volumes: {exc}', 'danger')
            return redirect(url_for('main.volumes'))

        return render_template('volumes.html', volumes_count=volumes_count, dangling_count=dangling_count, volumes_list=volumes_list, prunable_preview=prunable_preview, select_form=select_form)
    except ValueError as err:
        flash(str(err), 'warning')
        return render_template('volumes.html', volumes_count=0, dangling_count=0, select_form=select_form)


@main_bp.route('/networks', methods=['GET','POST'])
def networks():
    """Networks management and pruning."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()
    select_form.server.choices = [(s.id, s.display_name) for s in servers]
    if active_server:
        select_form.server.data = active_server.id

    networks_count = 0
    prunable_count = 0
    try:
        client, serverurl = conf()
        networks = client.networks.list() or []
        networks_count = len(networks)

        builtin = {'bridge', 'host', 'none'}
        prunable_networks = []
        networks_list = []

        # Some Docker endpoints do not populate network.attrs['Containers'] in
        # the listing response. Build a fallback map of network -> attached
        # container count by scanning all containers (single API call).
        container_network_counts = {}
        try:
            for c in client.containers.list(all=True):
                nets = getattr(c, 'attrs', {}).get('NetworkSettings', {}).get('Networks', {}) or {}
                for netname in nets.keys():
                    container_network_counts[netname] = container_network_counts.get(netname, 0) + 1
        except Exception:
            # If container listing fails, keep counts empty and rely on network attrs.
            container_network_counts = {}

        for n in networks:
            name = getattr(n, 'name', '')
            driver = (n.attrs.get('Driver') if getattr(n, 'attrs', None) else '') or ''
            # Prefer the network's own 'Containers' info when available; otherwise
            # fall back to the counts gathered from container listings.
            containers = (n.attrs.get('Containers') if getattr(n, 'attrs', None) else None)
            if isinstance(containers, dict):
                attached = len(containers)
            else:
                attached = container_network_counts.get(name, 0)

            prunable = (attached == 0 and name not in builtin)
            networks_list.append({'name': name, 'driver': driver, 'attached': attached, 'prunable': prunable})
            if prunable:
                prunable_networks.append({'name': name})
        prunable_count = len(prunable_networks)
        prunable_preview = prunable_networks[:5]

        if request.method == 'POST' and request.form.get('action') == 'prune':
            try:
                result = client.networks.prune()
                deleted = result.get('NetworksDeleted') or []
                num_deleted = len(deleted)
                flash(f'Pruned {num_deleted} networks', 'success')
            except Exception as exc:
                flash(f'Error pruning networks: {exc}', 'danger')
            return redirect(url_for('main.networks'))

        return render_template('networks.html', networks_count=networks_count, prunable_count=prunable_count, networks_list=networks_list, prunable_preview=prunable_preview, select_form=select_form)
    except ValueError as err:
        flash(str(err), 'warning')
        return render_template('networks.html', networks_count=0, prunable_count=0, select_form=select_form)


@main_bp.route('/addcon', methods=['GET', 'POST'])
def addcon():
    """Configure Docker server connections."""
    add_form = AddServerForm()
    select_form = SelectServerForm()
    
    # Get all servers and active server
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()
    
    # Populate server dropdown with only the display name
    def get_server_label(s):
        return s.display_name
    
    select_form.server.choices = [(s.id, get_server_label(s)) for s in servers]
    
    # Handle form submissions
    if request.method == 'POST':
        # Add new server
        if 'submit' in request.form:
            if add_form.validate():
                new_server = DockerServer(
                    display_name=add_form.display_name.data,
                    host=add_form.host.data or None,
                    port=add_form.port.data or None,
                    user=add_form.user.data or None,
                    password=add_form.password.data or None,
                    is_active=len(servers) == 0  # First server is active by default
                )
                db.session.add(new_server)
                db.session.commit()
                _docker_client_cache.clear()
                flash(f'Server "{new_server.display_name}" added successfully.', 'success')
                return redirect(url_for('main.addcon'))
            else:
                # Provide explicit feedback for validation failures (eg. CSRF/session issues)
                log.warning("AddCon: form validation failed: %s", add_form.errors)
                for field, errs in add_form.errors.items():
                    for err in errs:
                        # Use field label if possible for friendlier messages
                        try:
                            label = getattr(add_form, field).label.text
                        except Exception:
                            label = field
                        flash(f"{label}: {err}", 'danger')
                return redirect(url_for('main.addcon'))
        
        # Select active server
        if 'submit_select' in request.form:
            # Prefer form validation, but fall back to direct parsing if validation fails
            if select_form.validate():
                server_id = select_form.server.data
            else:
                raw = request.form.get('server')
                try:
                    server_id = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    server_id = None
                log.warning("AddCon select did not validate; fallback parsing server=%r -> %r", raw, server_id)

            if server_id is None:
                flash('Invalid server selection.', 'danger')
                return redirect(url_for('main.addcon'))

            server = DockerServer.set_active(server_id)
            _docker_client_cache.clear()
            if server:
                flash(f'Connected to "{server.display_name}".', 'success')
            return redirect(url_for('main.index'))
        
        # Delete server
        if 'delete_server' in request.form:
            server_id = request.form.get('delete_server')
            server = db.session.get(DockerServer, server_id)
            if server:
                name = server.display_name
                was_active = server.is_active
                db.session.delete(server)
                db.session.commit()
                # If deleted server was active, activate another one
                if was_active:
                    remaining = DockerServer.query.first()
                    if remaining:
                        DockerServer.set_active(remaining.id)
                _docker_client_cache.clear()
                flash(f'Server "{name}" deleted.', 'success')
            return redirect(url_for('main.addcon'))
    
    # Set default selection to active server (only for GET requests)
    if active_server:
        select_form.server.data = active_server.id

    return render_template('addcon.html', 
                          add_form=add_form, 
                          select_form=select_form,
                          servers=servers,
                          active_server=active_server)



@main_bp.route("/logs", methods=["POST"])
def logs():
    """Display logs for a specific container."""
    container_id = request.form.get("logs")
    if not container_id:
        flash('No container specified.', 'warning')
        return redirect(url_for('main.index'))

    try:
        t0 = time.time()
        client, _ = conf()
        t1 = time.time()
        container = client.containers.get(container_id)
        t2 = time.time()
        # Get last 1000 lines to avoid memory issues with large logs
        log_output = container.logs(tail=1000, timestamps=True)
        t3 = time.time()

        # Ensure we work with a decoded string in templates
        try:
            if isinstance(log_output, (bytes, bytearray)):
                logs_text = log_output.decode('utf-8', errors='replace')
            else:
                logs_text = str(log_output)
        except Exception as e:
            logs_text = ''
            log.exception('Failed to decode logs for %s', container_id)
        t4 = time.time()

        # Log timings and size
        lines = len(logs_text.splitlines())
        log.info("logs: container=%s lines=%d timings: conf=%.3fs get=%.3fs fetch=%.3fs decode=%.3fs",
                 container_id, lines, t1-t0, t2-t1, t3-t2, t4-t3)

        return render_template('logs.html', logs_text=logs_text)

    except docker.errors.NotFound:
        flash(f'Container {container_id} not found.', 'danger')
        return redirect(url_for('main.index'))
    except docker.errors.APIError as e:
        flash(f'Error fetching logs: {e}', 'danger')
        return redirect(url_for('main.index'))


@main_bp.route("/comma", methods=["POST"])
def comma():
    """Open a terminal session for a container."""
    container_id = request.form.get("comma")
    if not container_id:
        flash('No container specified.', 'warning')
        return redirect(url_for('main.index'))

    try:
        client, _ = conf()
        container = client.containers.get(container_id)
        return render_template('soc.html', id=container.id)
    except docker.errors.NotFound:
        flash(f'Container {container_id} not found.', 'danger')
        return redirect(url_for('main.index'))
    except docker.errors.APIError as e:
        flash(f'Error accessing container: {e}', 'danger')
        return redirect(url_for('main.index'))


@main_bp.route('/terminal', methods=['GET', 'POST'])
def terminal():
    """Open a terminal session to the Docker server via SSH."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()

    def get_server_label(s):
        return s.display_name

    select_form.server.choices = [(s.id, get_server_label(s)) for s in servers]

    # Handle server selection similar to index
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
            log.warning("Terminal select did not validate; fallback parsing server=%r -> %r", raw, server_id)

        if server_id is None:
            flash('Invalid server selection.', 'danger')
            return redirect(url_for('main.terminal'))

        server = DockerServer.query.get(server_id)
        if server:
            DockerServer.set_active(server_id)
            _docker_client_cache.clear()
            flash(f'Connected to "{server.display_name}".', 'success')
        return redirect(url_for('main.terminal'))

    # Determine server to connect to (query param overrides active)
    server = None
    r_server = request.args.get('server')
    if r_server:
        try:
            server = DockerServer.query.get(int(r_server))
        except Exception:
            server = None
    if not server:
        server = active_server

    if not server:
        flash('No server configured.', 'warning')
        return redirect(url_for('main.addcon'))

    return render_template('terminal.html', server=server, select_form=select_form)


@sock.route('/ssh')
def ssh(sock):
    """WebSocket handler to provide a full interactive PTY shell over SSH.

    Implements a background reader thread to stream data from the SSH channel
    to the WebSocket and accepts raw key data from the client. Clients may also
    send a JSON message {type:'resize', cols: N, rows: M} to resize the remote
    pty.
    """
    # Resolve server from query or active
    server_id = request.args.get('server')
    server = None
    if server_id:
        try:
            server = DockerServer.query.get(int(server_id))
        except Exception:
            server = None
    if not server:
        server = DockerServer.get_active()

    if not server:
        sock.send('Error: No server configured')
        return

    # Establish SSH connection
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = {'hostname': server.host, 'username': server.user, 'allow_agent': True, 'look_for_keys': True}
        if server.password:
            connect_kwargs['password'] = server.password
        ssh_client.connect(**connect_kwargs, timeout=10)
    except Exception as e:
        sock.send(f'SSH connection error: {e}')
        return

    transport = ssh_client.get_transport()

    # Default terminal size
    cols = int(request.args.get('cols') or 80)
    rows = int(request.args.get('rows') or 24)

    try:
        channel = transport.open_session()
        channel.get_pty(term='xterm', width=cols, height=rows)
        channel.invoke_shell()
        channel.settimeout(0.0)
    except Exception as e:
        sock.send(f'Failed to open interactive shell: {e}')
        try:
            ssh_client.close()
        except Exception:
            pass
        return

    stop_event = threading.Event()

    def _reader():
        """Read from SSH channel and forward to WebSocket."""
        try:
            while not stop_event.is_set():
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if not data:
                            break
                        try:
                            sock.send(data.decode('utf-8', errors='replace'))
                        except Exception:
                            break
                    else:
                        time.sleep(0.01)
                except Exception:
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            try:
                data = sock.receive()
            except Exception:
                break

            if data is None:
                break

            # Try to parse JSON control messages (e.g., resize)
            parsed = None
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = None

            if isinstance(parsed, dict) and parsed.get('type') == 'resize':
                try:
                    c = int(parsed.get('cols', cols))
                    r = int(parsed.get('rows', rows))
                    channel.resize_pty(width=c, height=r)
                except Exception as e:
                    try:
                        sock.send(f'Resize error: {e}')
                    except Exception:
                        pass
                continue

            # Local client-side commands
            if data == 'clear':
                try:
                    sock.send('__CLEAR__')
                except Exception:
                    pass
                continue

            if data == 'exit':
                try:
                    sock.send('Session closed. Bye!')
                except Exception:
                    pass
                break

            # Raw input: send directly to SSH channel
            try:
                if isinstance(data, str):
                    channel.send(data)
                else:
                    channel.send(str(data))
            except Exception as e:
                try:
                    sock.send(f'Error sending to channel: {e}')
                except Exception:
                    pass
                break

    finally:
        stop_event.set()
        try:
            channel.close()
        except Exception:
            pass
        try:
            ssh_client.close()
        except Exception:
            pass


@main_bp.route("/stats", methods=["GET", "POST"])
def stats():
    """Display stats for selected containers.

    Supports:
      - POST with multiple selected checkboxes (name="interests")
      - POST with single per-row button (name="stats")
      - GET with ?container=<id>
    """
    # Determine requested container ids from multiple possible sources
    container_ids = []
    # checkbox selections
    container_ids.extend(request.values.getlist('interests'))
    # single-button per-row value
    single = request.values.get('stats') or request.args.get('container')
    if single:
        container_ids.append(single)

    # Deduplicate and validate
    container_ids = [c for i, c in enumerate(container_ids) if c and c not in container_ids[:i]]

    if not container_ids:
        flash('No containers selected.', 'warning')
        return redirect(url_for('main.containers'))

    try:
        client, _ = conf()
        lines = []
        # Header similar to docker stats
        header = "CONTAINER ID  NAME                     CPU %  MEM USAGE  / LIMIT       MEM %  NET I/O           BLOCK I/O        PIDS"
        lines.append(header)

        def human_readable_bytes(n):
            try:
                n = float(n)
            except Exception:
                return str(n)
            units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
            for u in units:
                if abs(n) < 1024.0:
                    return f"{n:.1f}{u}"
                n /= 1024.0
            return f"{n:.1f}PiB"

        # Fetch stats in parallel to reduce latency when multiple containers are selected
        def _fetch(cid):
            try:
                t0 = time.time()
                container = client.containers.get(cid)
                stats = container.stats(stream=False)

                # CPU calculation
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats.get('precpu_stats', {}).get('cpu_usage', {}).get('total_usage', 0)
                system_delta = stats['cpu_stats'].get('system_cpu_usage', 0) - stats.get('precpu_stats', {}).get('system_cpu_usage', 0)
                online_cpus = stats['cpu_stats'].get('online_cpus') or len(stats['cpu_stats'].get('cpu_usage', {}).get('percpu_usage', []) or []) or 1
                cpu_pct = 0.0
                if system_delta > 0 and cpu_delta > 0:
                    cpu_pct = (cpu_delta / system_delta) * online_cpus * 100.0

                # Memory
                mem_used = stats.get('memory_stats', {}).get('usage', 0)
                mem_limit = stats.get('memory_stats', {}).get('limit', 0)
                mem_pct = (float(mem_used) / mem_limit * 100.0) if mem_limit else 0.0

                # Network
                net_rx = 0
                net_tx = 0
                networks = stats.get('networks') or {}
                for iface, data in networks.items():
                    net_rx += data.get('rx_bytes', 0)
                    net_tx += data.get('tx_bytes', 0)

                # Block IO
                blk_read = 0
                blk_write = 0
                for blk in stats.get('blkio_stats', {}).get('io_service_bytes_recursive', []) or []:
                    op = blk.get('op', '').lower()
                    val = blk.get('value', 0)
                    if op == 'read':
                        blk_read += val
                    elif op == 'write':
                        blk_write += val

                pids = stats.get('pids_stats', {}).get('current', '-')

                line = f"{container.id[:12]:12}  {container.name[:20]:20}  {cpu_pct:6.1f}%   {human_readable_bytes(mem_used):10} / {human_readable_bytes(mem_limit):7}   {mem_pct:5.1f}%   {human_readable_bytes(net_rx)} / {human_readable_bytes(net_tx)}   {human_readable_bytes(blk_read)} / {human_readable_bytes(blk_write)}   {pids}"
                log.debug("stats: container=%s fetch_time=%.3fs", cid[:12], time.time()-t0)
                return cid, line
            except docker.errors.NotFound:
                return cid, f"{cid[:12]}  (not found)"
            except Exception as e:
                return cid, f"{cid[:12]}  Error: {e}"

        max_workers = min(20, max(1, len(container_ids)))
        results = {}
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as exc:
            futures = {exc.submit(_fetch, cid): cid for cid in container_ids}
            for fut in as_completed(futures):
                try:
                    cid, line = fut.result()
                    results[cid] = line
                except Exception as e:
                    cid = futures.get(fut, '(unknown)')
                    results[cid] = f"{cid[:12]}  Error: {e}"
        log.info("stats: fetched %d containers in %.3fs (workers=%d)", len(container_ids), time.time()-start_time, max_workers)

        # Preserve original order
        for cid in container_ids:
            lines.append(results.get(cid, f"{cid[:12]}  Error: no result"))

        stats_text = '\n'.join(lines)
    except ValueError as e:
        stats_text = f"Error connecting to Docker server: {e}"
    except docker.errors.APIError as e:
        stats_text = f"Docker API error: {e}"

    return render_template('stats.html', stats_text=stats_text)

@main_bp.route("/inspect", methods=["POST"])
def inspect():
    """Display inspect data for a specific container."""
    container_id = request.form.get("inspect")
    if not container_id:
        flash('No container specified.', 'warning')
        return redirect(url_for('main.index'))

    try:
        t0 = time.time()
        client, _ = conf()
        t1 = time.time()
        container = client.containers.get(container_id)
        t2 = time.time()
        inspect_data = container.attrs
        t3 = time.time()

        log.info("inspect: container=%s timings: conf=%.3fs get=%.3fs inspect=%.3fs",
                 container_id, t1-t0, t2-t1, t3-t2)

        return render_template('inspect.html', inspect_data=inspect_data, container_id=container_id)
    except docker.errors.NotFound:
        flash(f'Container {container_id} not found.', 'danger')
        return redirect(url_for('main.index'))
    except docker.errors.APIError as e:
        flash(f'Error inspecting container: {e}', 'danger')
        return redirect(url_for('main.index'))
# Removed legacy built-in command handler; interactive PTY provides
# full shell functionality directly inside the container.

# Legacy echo-based container terminal removed. Use `/container` PTY
# WebSocket handler (implemented earlier) which provides a true
# interactive TTY shell and handles resizing, copy/paste, and raw I/O.

@sock.route('/container')
def container(sock):
    """WebSocket PTY for container shells (interactive).

    Establish a Docker exec with TTY and stream I/O between the exec socket and
    the WebSocket. Supports JSON resize messages: {type:'resize', cols: N, rows: M}.
    """
    container_id = request.args.get('id')
    if not container_id:
        sock.send('Error: No container ID provided')
        return

    try:
        client, _ = conf()
        container = client.containers.get(container_id)
    except (ValueError, docker.errors.NotFound) as e:
        sock.send(f'Error: {e}')
        return

    # Container must be running
    try:
        container.reload()
        state = container.attrs.get('State', {})
        if not state.get('Running'):
            sock.send('Error: Container is not running')
            return
    except Exception:
        sock.send('Error: Failed to inspect container')
        return

    # Try a list of common shells (prefer bash, then sh/ash/dash/zsh).
    # IMPORTANT: only set `exec_id` after exec_start succeeds to avoid a race
    # where the client sends a resize for an exec instance that hasn't started yet.
    exec_id = None
    sock_obj = None
    shells = ['/bin/bash', '/usr/bin/bash', '/bin/sh', '/bin/ash', '/bin/dash', '/bin/zsh']
    for shell in shells:
        created = None
        try:
            created = client.api.exec_create(container.id, cmd=[shell], tty=True, stdin=True)['Id']
            sock_obj = client.api.exec_start(created, tty=True, socket=True)

            # Poll exec_inspect briefly to ensure the exec process started and did
            # not immediately fail (e.g., binary missing such as /bin/bash).
            started = False
            try:
                for _ in range(8):  # poll ~400ms (8 * 50ms)
                    ins = client.api.exec_inspect(created)
                    # If 'Running' field exists and is True it's good
                    if ins.get('Running'):
                        started = True
                        break
                    # If ExitCode is present and non-zero, the exec failed to start
                    if ins.get('ExitCode') is not None and ins.get('ExitCode') != 0:
                        started = False
                        break
                    time.sleep(0.05)
            except Exception:
                # If inspect fails, fall back to assuming it failed to start
                started = False

            if not started:
                # cleanup and try next shell
                try:
                    if hasattr(sock_obj, 'close'):
                        sock_obj.close()
                except Exception:
                    pass
                exec_id = None
                sock_obj = None
                continue

            # success: assign exec_id only after the exec actually started
            exec_id = created
            try:
                # Notify client which shell was chosen (optional, helpful for debugging)
                sock.send(f'Connected to container shell: {shell}')
            except Exception:
                pass
            break
        except Exception:
            exec_id = None
            sock_obj = None
            continue
    if not sock_obj:
        sock.send('Failed to start container shell: no suitable shell found')
        return

    # Access underlying raw socket if present
    raw_sock = sock_obj._sock if hasattr(sock_obj, '_sock') else sock_obj
    try:
        raw_sock.setblocking(False)
    except Exception:
        pass

    stop_event = threading.Event()

    def _reader():
        try:
            while not stop_event.is_set():
                try:
                    data = None
                    try:
                        data = sock_obj.recv(4096)
                    except Exception:
                        try:
                            data = raw_sock.recv(4096)
                        except Exception:
                            data = None
                    if not data:
                        time.sleep(0.01)
                        continue
                    try:
                        sock.send(data.decode('utf-8', errors='replace'))
                    except Exception:
                        break
                except Exception:
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            try:
                data = sock.receive()
            except Exception:
                break

            if data is None:
                break

            parsed = None
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = None

            if isinstance(parsed, dict) and parsed.get('type') == 'resize':
                try:
                    c = int(parsed.get('cols', 80))
                    r = int(parsed.get('rows', 24))
                    try:
                        client.api.exec_resize(exec_id, height=r, width=c)
                    except Exception as e:
                        try:
                            sock.send(f'Resize error: {e}')
                        except Exception:
                            pass
                except Exception:
                    pass
                continue

            if data == 'clear':
                try:
                    sock.send('__CLEAR__')
                except Exception:
                    pass
                continue

            if data == 'exit':
                try:
                    sock.send('Session closed. Bye!')
                except Exception:
                    pass
                break

            # Forward raw input to container socket
            try:
                if isinstance(data, str):
                    to_send = data.encode('utf-8')
                else:
                    to_send = data
                try:
                    sock_obj.send(to_send)
                except Exception:
                    try:
                        raw_sock.send(to_send)
                    except Exception as e:
                        try:
                            sock.send(f'Error sending to container: {e}')
                        except Exception:
                            pass
                        break
            except Exception as e:
                try:
                    sock.send(f'Error: {e}')
                except Exception:
                    pass
                break

    finally:
        stop_event.set()
        try:
            if hasattr(sock_obj, 'close'):
                sock_obj.close()
        except Exception:
            pass
        try:
            # Best-effort: inspect to trigger cleanup / update state
            client.api.exec_inspect(exec_id)
        except Exception:
            pass


@main_bp.route("/submitadmin", methods=["POST"])
def submit_remove():
    """Handle container management actions (start, stop, restart, delete)."""
    action = request.form.get("submit_button")
    container_ids = request.form.getlist("interests")

    if not container_ids:
        flash('No containers selected.', 'warning')
        return redirect(url_for('main.containers'))

    action_map = {
        "Delete": (lambda c: c.remove(force=True), "deleted"),
        "Start": (lambda c: c.start(), "started"),
        "Restart": (lambda c: c.restart(), "restarted"),
        "Stop": (lambda c: c.stop(), "stopped"),
    }

    if action not in action_map:
        flash('Invalid action specified.', 'danger')
        return redirect(url_for('main.containers'))

    try:
        client, _ = conf()
        handler, past_tense = action_map[action]
        success_count = 0
        errors = []

        for cid in container_ids:
            try:
                container = client.containers.get(cid)
                handler(container)
                success_count += 1
            except docker.errors.NotFound:
                errors.append(f"Container {cid[:12]} not found")
            except docker.errors.APIError as e:
                errors.append(f"Container {cid[:12]}: {e}")

        if success_count:
            flash(f'{success_count} container(s) {past_tense}.', 'success')
        for error in errors:
            flash(error, 'danger')

        return redirect(url_for('main.containers'))

    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('main.containers'))

    return redirect(url_for('main.containers'))