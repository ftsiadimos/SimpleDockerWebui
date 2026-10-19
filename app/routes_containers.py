"""Containers, logs, stats, and inspect routes."""
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import docker
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.models import DockerServer, ContainerActivity
from app.forms import SelectServerForm
from app.ssh_tunnel import conf
from app.routes_index import main_bp

log = logging.getLogger(__name__)


@main_bp.route('/containers', methods=['GET', 'POST'])
def containers():
    """Full containers listing (moved from index)."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()

    def get_server_label(s):
        return s.display_name

    select_form.server.choices = [(s.id, get_server_label(s)) for s in servers]
    
    # Handle server selection from dropdown
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
            return redirect(url_for('main.containers'))

        server = DockerServer.query.get(server_id)
        if server:
            try:
                if server.is_ssh_tunnel:
                    from app.ssh_tunnel import _open_ssh_tunnel
                    _open_ssh_tunnel(server)
                else:
                    pass
                DockerServer.set_active(server_id)
                flash(f'Connected to "{server.display_name}".', 'success')
            except Exception as exc:
                flash(f"Error connecting to server: {exc}", 'warning')
        return redirect(url_for('main.containers'))
    
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


@main_bp.route('/submit_remove', methods=['POST'])
def submit_remove():
    """Handle container actions: Start, Stop, Restart, Delete."""
    container_ids = request.form.getlist('interests')
    action = request.form.get('submit_button', '').strip()

    if not container_ids:
        flash('No containers selected.', 'warning')
        return redirect(url_for('main.containers'))

    if not action:
        flash('No action specified.', 'warning')
        return redirect(url_for('main.containers'))

    try:
        client, _ = conf()
        success_count = 0
        error_count = 0

        for container_id in container_ids:
            try:
                container = client.containers.get(container_id)
                
                if action == 'Start':
                    container.start()
                    success_count += 1
                elif action == 'Stop':
                    container.stop()
                    success_count += 1
                elif action == 'Restart':
                    container.restart()
                    success_count += 1
                elif action == 'Delete':
                    container.remove(force=True)
                    success_count += 1
                else:
                    error_count += 1
                    
                # Log the activity
                try:
                    ContainerActivity.log_activity(container_id, action, 'success')
                except Exception:
                    pass
                    
            except docker.errors.NotFound:
                error_count += 1
                log.warning(f"Container {container_id} not found")
            except docker.errors.APIError as e:
                error_count += 1
                log.error(f"Error performing {action} on {container_id}: {e}")
            except Exception as e:
                error_count += 1
                log.error(f"Unexpected error performing {action} on {container_id}: {e}")

        if success_count > 0:
            flash(f'{action} operation completed on {success_count} container(s).', 'success')
        if error_count > 0:
            flash(f'Error operating on {error_count} container(s).', 'warning')

    except ValueError as e:
        flash(f'Connection error: {e}', 'danger')
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('main.containers'))


@main_bp.route('/logs', methods=["POST"])
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
        log_output = container.logs(tail=1000, timestamps=True)
        t3 = time.time()

        try:
            if isinstance(log_output, (bytes, bytearray)):
                logs_text = log_output.decode('utf-8', errors='replace')
            else:
                logs_text = str(log_output)
        except Exception as e:
            logs_text = ''
            log.exception('Failed to decode logs for %s', container_id)
        t4 = time.time()

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


@main_bp.route("/stats", methods=["GET", "POST"])
def stats():
    """Display stats for selected containers."""
    container_ids = []
    container_ids.extend(request.values.getlist('interests'))
    single = request.values.get('stats') or request.args.get('container')
    if single:
        container_ids.append(single)
    container_ids = [c for i, c in enumerate(container_ids) if c and c not in container_ids[:i]]

    if not container_ids:
        flash('No containers selected.', 'warning')
        return redirect(url_for('main.containers'))

    try:
        client, _ = conf()
        lines = []
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

        def _fetch(cid):
            try:
                t0 = time.time()
                container = client.containers.get(cid)
                stats_data = container.stats(stream=False)

                cpu_delta = stats_data['cpu_stats']['cpu_usage']['total_usage'] - stats_data.get('precpu_stats', {}).get('cpu_usage', {}).get('total_usage', 0)
                system_delta = stats_data['cpu_stats'].get('system_cpu_usage', 0) - stats_data.get('precpu_stats', {}).get('system_cpu_usage', 0)
                online_cpus = stats_data['cpu_stats'].get('online_cpus') or len(stats_data['cpu_stats'].get('cpu_usage', {}).get('percpu_usage', []) or []) or 1
                cpu_pct = 0.0
                if system_delta > 0 and cpu_delta > 0:
                    cpu_pct = (cpu_delta / system_delta) * online_cpus * 100.0

                mem_used = stats_data.get('memory_stats', {}).get('usage', 0)
                mem_limit = stats_data.get('memory_stats', {}).get('limit', 0)
                mem_pct = (float(mem_used) / mem_limit * 100.0) if mem_limit else 0.0

                net_rx = 0
                net_tx = 0
                networks = stats_data.get('networks') or {}
                for iface, data in networks.items():
                    net_rx += data.get('rx_bytes', 0)
                    net_tx += data.get('tx_bytes', 0)

                blk_read = 0
                blk_write = 0
                for blk in stats_data.get('blkio_stats', {}).get('io_service_bytes_recursive', []) or []:
                    op = blk.get('op', '').lower()
                    val = blk.get('value', 0)
                    if op == 'read':
                        blk_read += val
                    elif op == 'write':
                        blk_write += val

                pids = stats_data.get('pids_stats', {}).get('current', '-')

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


@main_bp.route("/comma", methods=["POST"])
def comma():
    """Open a terminal for a specific container."""
    container_id = request.form.get("comma")
    if not container_id:
        flash('No container specified.', 'warning')
        return redirect(url_for('main.containers'))

    try:
        client, serverurl = conf()
        container = client.containers.get(container_id)
        
        # Check if container is running
        container.reload()
        state = container.attrs.get('State', {})
        if not state.get('Running'):
            flash('Container is not running. Start it first before opening a terminal.', 'warning')
            return redirect(url_for('main.containers'))
            
        # Render container terminal page
        return render_template('container_terminal.html', container_id=container_id, container_name=container.name)
        
    except docker.errors.NotFound:
        flash(f'Container {container_id} not found.', 'danger')
        return redirect(url_for('main.containers'))
    except Exception as e:
        flash(f'Error opening terminal: {e}', 'danger')
        log.error(f"Error opening terminal for {container_id}: {e}")
        return redirect(url_for('main.containers'))
