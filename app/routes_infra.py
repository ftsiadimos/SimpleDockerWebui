"""Images, volumes, and networks management routes."""
import os
import logging

import docker
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.models import DockerServer
from app.forms import SelectServerForm
from app.ssh_tunnel import conf
from app.docker_helpers import _human_size
from app.routes_index import main_bp

log = logging.getLogger(__name__)


@main_bp.route('/images', methods=['GET','POST'])
def images():
    """Images management and pruning."""
    select_form = SelectServerForm()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()
    select_form.server.choices = [(s.id, s.display_name) for s in servers]
    
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
            return redirect(url_for('main.images'))

        server = DockerServer.query.get(server_id)
        if server:
            try:
                if server.is_ssh_tunnel:
                    from app.ssh_tunnel import _open_ssh_tunnel
                    _open_ssh_tunnel(server)
                DockerServer.set_active(server_id)
                flash(f'Connected to "{server.display_name}".', 'success')
            except Exception as exc:
                flash(f"Error connecting to server: {exc}", 'warning')
        return redirect(url_for('main.images'))
    
    if active_server:
        select_form.server.data = active_server.id

    images_count = 0
    dangling_count = 0
    try:
        client, serverurl = conf()
        images = client.images.list()
        images_count = len(images)

        try:
            containers = client.containers.list(all=True)
            used_image_ids = {c.image.id for c in containers if hasattr(c, 'image')}
        except Exception:
            used_image_ids = set()

        try:
            prunable_images_raw = client.api.images(filters={'dangling': False})
            if prunable_images_raw:
                prunable_images_raw = [img for img in prunable_images_raw
                                      if img.get('Id', '') not in used_image_ids]
        except Exception:
            try:
                prunable_images_raw = client.images.list(filters={'dangling': True})
            except Exception:
                prunable_images_raw = [i for i in images if not getattr(i, 'tags', None)]

        images_list = []
        if isinstance(prunable_images_raw, list) and prunable_images_raw and isinstance(prunable_images_raw[0], dict):
            prunable_ids = {img.get('Id', '')[:12] for img in prunable_images_raw}
        else:
            prunable_ids = {getattr(i, 'id', '')[:12] for i in prunable_images_raw if getattr(i, 'id', '')}

        for i in images:
            iid = (getattr(i, 'id', '') or '')[:12]
            full_id = getattr(i, 'id', '')
            tags = ', '.join(getattr(i, 'tags', []) or ['<none>:<none>'])
            size_bytes = 0
            try:
                size_bytes = int(i.attrs.get('Size', 0)) if getattr(i, 'attrs', None) else 0
            except Exception:
                size_bytes = 0
            is_prunable = iid in prunable_ids or full_id not in used_image_ids
            images_list.append({
                'id': iid,
                'tags': tags,
                'size': _human_size(size_bytes),
                'prunable': is_prunable
            })

        dangling_count = sum(1 for img in images_list if img['prunable'])

        prunable_preview = []
        for i in prunable_images_raw[:5]:
            prunable_preview.append({
                'id': (getattr(i, 'id', '') or '')[:12],
                'tags': ', '.join(getattr(i, 'tags', []) or ['<none>:<none>'])
            })

        if request.method == 'POST' and request.form.get('action') == 'prune':
            try:
                result = client.api.prune_images(filters={'dangling': False})
                reclaimed = result.get('SpaceReclaimed', 0)
                deleted = result.get('ImagesDeleted') or []
                num_deleted = len(deleted) if isinstance(deleted, list) else 1
                flash(f'Pruned {num_deleted} images — reclaimed {reclaimed // (1024**2)} MB', 'success')
            except Exception as exc:
                flash(f'Error pruning images: {exc}', 'danger')
            return redirect(url_for('main.images'))

        if request.method == 'POST' and request.form.get('action') == 'bulk_delete':
            try:
                image_ids = request.form.getlist('image_ids')
                if not image_ids:
                    flash('No images selected', 'warning')
                else:
                    deleted_count = 0
                    errors = []
                    for img_id in image_ids:
                        try:
                            client.images.remove(img_id, force=True)
                            deleted_count += 1
                        except Exception as e:
                            errors.append(f"{img_id[:12]}: {str(e)}")

                    if errors:
                        flash(f'Deleted {deleted_count} images. Errors: ' + '; '.join(errors), 'warning')
                    else:
                        flash(f'Deleted {deleted_count} image(s)', 'success')
            except Exception as exc:
                flash(f'Error deleting images: {exc}', 'danger')
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
            return redirect(url_for('main.volumes'))

        server = DockerServer.query.get(server_id)
        if server:
            try:
                if server.is_ssh_tunnel:
                    from app.ssh_tunnel import _open_ssh_tunnel
                    _open_ssh_tunnel(server)
                DockerServer.set_active(server_id)
                flash(f'Connected to "{server.display_name}".', 'success')
            except Exception as exc:
                flash(f"Error connecting to server: {exc}", 'warning')
        return redirect(url_for('main.volumes'))
    
    if active_server:
        select_form.server.data = active_server.id

    volumes_count = 0
    dangling_count = 0
    try:
        client, serverurl = conf()
        volumes = client.volumes.list() or []
        volumes_count = len(volumes)

        try:
            containers = client.containers.list(all=True)
            volume_mounts = set()
            for c in containers:
                mounts = getattr(c, 'attrs', {}).get('Mounts', []) or []
                for mount in mounts:
                    if mount.get('Type') == 'volume' and mount.get('Name'):
                        volume_mounts.add(mount.get('Name'))
        except Exception:
            volume_mounts = set()

        volumes_list = []
        for v in volumes:
            name = getattr(v, 'name', '')
            mountpoint = (v.attrs.get('Mountpoint') if getattr(v, 'attrs', None) else '') or ''
            driver = (v.attrs.get('Driver') if getattr(v, 'attrs', None) else '') or ''
            is_prunable = name not in volume_mounts
            volumes_list.append({
                'name': name,
                'driver': driver,
                'mountpoint': mountpoint,
                'prunable': is_prunable
            })

        dangling_count = sum(1 for v in volumes_list if v['prunable'])
        prunable_preview = []

        if request.method == 'POST' and request.form.get('action') == 'prune':
            try:
                result = client.volumes.prune()
                deleted = result.get('VolumesDeleted') or []
                num_deleted = len(deleted)
                flash(f'Pruned {num_deleted} volumes', 'success')
            except Exception as exc:
                flash(f'Error pruning volumes: {exc}', 'danger')
            return redirect(url_for('main.volumes'))

        if request.method == 'POST' and request.form.get('action') == 'bulk_delete':
            try:
                volume_names = request.form.getlist('volume_names')
                if not volume_names:
                    flash('No volumes selected', 'warning')
                else:
                    deleted_count = 0
                    errors = []
                    for vol_name in volume_names:
                        try:
                            vol = client.volumes.get(vol_name)
                            vol.remove(force=True)
                            deleted_count += 1
                        except Exception as e:
                            errors.append(f"{vol_name}: {str(e)}")

                    if errors:
                        flash(f'Deleted {deleted_count} volumes. Errors: ' + '; '.join(errors), 'warning')
                    else:
                        flash(f'Deleted {deleted_count} volume(s)', 'success')
            except Exception as exc:
                flash(f'Error deleting volumes: {exc}', 'danger')
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
            return redirect(url_for('main.networks'))

        server = DockerServer.query.get(server_id)
        if server:
            try:
                if server.is_ssh_tunnel:
                    from app.ssh_tunnel import _open_ssh_tunnel
                    _open_ssh_tunnel(server)
                DockerServer.set_active(server_id)
                flash(f'Connected to "{server.display_name}".', 'success')
            except Exception as exc:
                flash(f"Error connecting to server: {exc}", 'warning')
        return redirect(url_for('main.networks'))
    
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

        container_network_counts = {}
        try:
            for c in client.containers.list(all=True):
                nets = getattr(c, 'attrs', {}).get('NetworkSettings', {}).get('Networks', {}) or {}
                for netname in nets.keys():
                    container_network_counts[netname] = container_network_counts.get(netname, 0) + 1
        except Exception:
            container_network_counts = {}

        for n in networks:
            name = getattr(n, 'name', '')
            driver = (n.attrs.get('Driver') if getattr(n, 'attrs', None) else '') or ''
            containers = (n.attrs.get('Containers') if getattr(n, 'attrs', None) else None)
            if isinstance(containers, dict):
                attached = len(containers)
            else:
                attached = container_network_counts.get(name, 0)

            is_prunable = attached == 0 and name not in builtin
            networks_list.append({'name': name, 'driver': driver, 'attached': attached, 'prunable': is_prunable})

        prunable_count = sum(1 for n in networks_list if n['prunable'])
        prunable_preview = []

        if request.method == 'POST' and request.form.get('action') == 'prune':
            try:
                result = client.networks.prune()
                deleted = result.get('NetworksDeleted') or []
                num_deleted = len(deleted)
                flash(f'Pruned {num_deleted} networks', 'success')
            except Exception as exc:
                flash(f'Error pruning networks: {exc}', 'danger')
            return redirect(url_for('main.networks'))

        if request.method == 'POST' and request.form.get('action') == 'bulk_delete':
            try:
                network_names = request.form.getlist('network_names')
                if not network_names:
                    flash('No networks selected', 'warning')
                else:
                    deleted_count = 0
                    errors = []
                    for net_name in network_names:
                        try:
                            net = client.networks.get(net_name)
                            net.remove()
                            deleted_count += 1
                        except Exception as e:
                            errors.append(f"{net_name}: {str(e)}")

                    if errors:
                        flash(f'Deleted {deleted_count} networks. Errors: ' + '; '.join(errors), 'warning')
                    else:
                        flash(f'Deleted {deleted_count} network(s)', 'success')
            except Exception as exc:
                flash(f'Error deleting networks: {exc}', 'danger')
            return redirect(url_for('main.networks'))

        return render_template('networks.html', networks_count=networks_count, prunable_count=prunable_count, networks_list=networks_list, prunable_preview=prunable_preview, select_form=select_form)
    except ValueError as err:
        flash(str(err), 'warning')
        return render_template('networks.html', networks_count=0, prunable_count=0, select_form=select_form)
