"""Settings, server management, and terminal routes."""
import os
import logging

import docker
import paramiko  # type: ignore
from flask import Blueprint, render_template, request, redirect, url_for, flash

from app import db
from app.models import DockerServer, GitRepoConfig
from app.forms import AddServerForm, SelectServerForm, GitRepoForm
from app.ssh_tunnel import conf, _open_ssh_tunnel, _close_ssh_tunnel, _tunnel_status, _docker_client_cache
from app import git_service
from app.routes_index import main_bp

log = logging.getLogger(__name__)


@main_bp.route('/settings', methods=['GET','POST'])
def settings():
    """User settings: select UI theme and git repository config."""
    current = request.cookies.get('ldwui_theme', 'default')
    themes = [('default','Default'), ('terminal-dark','Terminal Dark')]

    git_config = GitRepoConfig.get_config()
    git_form = GitRepoForm(obj=git_config)
    if git_config:
        git_form.token.data = ''

    basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    default_local_path = os.path.join(basedir, 'instance', 'gitops-repo')

    git_status = None
    if git_config and git_config.local_path:
        git_status = git_service.get_repo_status(git_config.local_path)

    if request.method == 'POST':
        action = request.form.get('form_action', '')

        if action == 'theme':
            theme = request.form.get('theme', 'default')
            if theme not in [t[0] for t in themes]:
                theme = 'default'
            resp = redirect(url_for('main.settings'))
            resp.set_cookie('ldwui_theme', theme, max_age=30*24*3600)
            flash('Theme updated.', 'success')
            return resp

        elif action == 'git_save':
            git_form = GitRepoForm(request.form)
            if git_form.validate():
                repo_url = git_form.repo_url.data.strip()
                token = git_form.token.data.strip()
                branch = git_form.branch.data.strip()
                auto_push = git_form.auto_push.data

                if not git_config and not token:
                    flash('Token is required when configuring a new git repository.', 'danger')
                    return redirect(url_for('main.settings'))

                if not git_config:
                    git_config = GitRepoConfig(
                        repo_url=repo_url,
                        token=token,
                        branch=branch,
                        local_path=default_local_path,
                        auto_push=auto_push,
                    )
                    db.session.add(git_config)
                else:
                    git_config.repo_url = repo_url
                    if token:
                        git_config.token = token
                    git_config.branch = branch
                    git_config.auto_push = auto_push
                    if not git_config.local_path:
                        git_config.local_path = default_local_path
                db.session.commit()

                if not git_service.is_repo_cloned(git_config.local_path):
                    ok, msg = git_service.clone_repo(
                        git_config.repo_url, git_config.token,
                        git_config.branch, git_config.local_path)
                    if ok:
                        git_config.mark_synced()
                        flash(msg, 'success')
                    else:
                        flash(msg, 'danger')
                else:
                    flash('Git configuration updated.', 'success')

                return redirect(url_for('main.settings'))
            else:
                for field, errors in git_form.errors.items():
                    for error in errors:
                        flash(f'{field}: {error}', 'danger')

        elif action == 'git_pull':
            if git_config:
                ok, msg = git_service.pull_repo(
                    git_config.local_path, git_config.token, git_config.repo_url)
                if ok:
                    git_config.mark_synced()
                    flash(msg, 'success')
                else:
                    flash(msg, 'danger')
            else:
                flash('No git repository configured.', 'warning')
            return redirect(url_for('main.settings'))

        elif action == 'git_reclone':
            if git_config:
                if git_config.local_path and os.path.isdir(git_config.local_path):
                    shutil.rmtree(git_config.local_path, ignore_errors=True)
                ok, msg = git_service.clone_repo(
                    git_config.repo_url, git_config.token,
                    git_config.branch, git_config.local_path)
                if ok:
                    git_config.mark_synced()
                    flash(msg, 'success')
                else:
                    flash(msg, 'danger')
            else:
                flash('No git repository configured.', 'warning')
            return redirect(url_for('main.settings'))

        elif action == 'git_delete':
            if git_config:
                if git_config.local_path and os.path.isdir(git_config.local_path):
                    shutil.rmtree(git_config.local_path, ignore_errors=True)
                db.session.delete(git_config)
                db.session.commit()
                flash('Git configuration removed.', 'success')
            return redirect(url_for('main.settings'))

    return render_template('settings.html',
                           current_theme=current, themes=themes,
                           git_form=git_form, git_config=git_config,
                           git_status=git_status)


@main_bp.route('/addcon', methods=['GET', 'POST'])
def addcon():
    """Configure Docker server connections."""
    add_form = AddServerForm()
    select_form = SelectServerForm()

    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()

    def get_server_label(s):
        return s.display_name

    select_form.server.choices = [(s.id, get_server_label(s)) for s in servers]

    ssh_keys = DockerServer.list_ssh_keys()
    add_form.ssh_key.choices = [('', '— Password authentication —')] + [
        (name, name) for name in ssh_keys
    ]

    if request.method == 'POST':
        if 'submit' in request.form:
            if add_form.validate():
                ssh_key = add_form.ssh_key.data or None
                if ssh_key and ssh_key not in ssh_keys:
                    ssh_key = None
                new_server = DockerServer(
                    display_name=add_form.display_name.data,
                    host=add_form.host.data or None,
                    port=add_form.port.data or None,
                    user=add_form.user.data or None,
                    password=None if ssh_key else (add_form.password.data or None),
                    ssh_key=ssh_key,
                    ssh_tunnel=bool(add_form.ssh_tunnel.data),
                    tunnel_target=(add_form.tunnel_target.data or '/var/run/docker.sock').strip(),
                    is_active=len(servers) == 0
                )
                if new_server.ssh_tunnel:
                    new_server.ensure_local_port()
                db.session.add(new_server)
                db.session.commit()
                _docker_client_cache.clear()
                flash(f'Server "{new_server.display_name}" added successfully.', 'success')
                return redirect(url_for('main.addcon'))
            else:
                log.warning("AddCon: form validation failed: %s", add_form.errors)
                for field, errs in add_form.errors.items():
                    for err in errs:
                        try:
                            label = getattr(add_form, field).label.text
                        except Exception:
                            label = field
                        flash(f"{label}: {err}", 'danger')
                return redirect(url_for('main.addcon'))

        if 'submit_select' in request.form:
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

        if 'delete_server' in request.form:
            server_id = request.form.get('delete_server')
            server = db.session.get(DockerServer, server_id)
            if server:
                name = server.display_name
                was_active = server.is_active
                deleted_id = server.id
                db.session.delete(server)
                db.session.commit()
                _close_ssh_tunnel(deleted_id)
                if was_active:
                    remaining = DockerServer.query.first()
                    if remaining:
                        DockerServer.set_active(remaining.id)
                _docker_client_cache.clear()
                flash(f'Server "{name}" deleted.', 'success')
            return redirect(url_for('main.addcon'))

        if 'tunnel_open' in request.form:
            server_id = request.form.get('tunnel_open')
            server = db.session.get(DockerServer, server_id)
            if not server:
                flash('Server not found.', 'danger')
            elif not (server.host and server.port and server.ssh_tunnel):
                flash('This server has no SSH tunnel configured.', 'warning')
            else:
                try:
                    tunnel = _open_ssh_tunnel(server)
                    if tunnel:
                        flash(f'SSH tunnel opened on 127.0.0.1:{server.local_port}.', 'success')
                    else:
                        flash('SSH tunnel could not be opened.', 'warning')
                except Exception as e:
                    log.exception("Failed to open tunnel for server %s", server_id)
                    flash(f'Failed to open SSH tunnel: {e}', 'danger')
            return redirect(url_for('main.addcon'))

        if 'tunnel_close' in request.form:
            server_id = request.form.get('tunnel_close')
            try:
                _close_ssh_tunnel(int(server_id))
                _docker_client_cache.clear()
                flash('SSH tunnel closed.', 'success')
            except Exception as e:
                flash(f'Failed to close SSH tunnel: {e}', 'danger')
            return redirect(url_for('main.addcon'))

    if active_server:
        select_form.server.data = active_server.id

    tunnel_status = {s.id: _tunnel_status(s) for s in servers}

    return render_template('addcon.html',
                          add_form=add_form,
                          select_form=select_form,
                          servers=servers,
                          active_server=active_server,
                          tunnel_status=tunnel_status,
                          ssh_dir=DockerServer.ssh_dir())


@main_bp.route('/terminal', methods=['GET', 'POST'])
def terminal():
    """Open a terminal session to the Docker server via SSH."""
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

    return render_template('terminal.html', server=server, select_form=select_form,
                           tunnel_status=_tunnel_status(server))
