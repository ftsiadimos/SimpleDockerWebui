"""Compose and Git Compose management routes."""
import os
import shutil
import logging

import docker
import paramiko  # type: ignore
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

from app.models import DockerServer, GitRepoConfig, ProjectServerMapping, ContainerActivity
from app.forms import SelectServerForm
from app.ssh_tunnel import conf, get_docker_base_url, _open_ssh_tunnel
from app import git_service
from app.routes_index import main_bp

log = logging.getLogger(__name__)


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

        is_remote = (server_obj.host and
                    server_obj.host not in ['localhost', '127.0.0.1', ''] and
                    server_obj.user)

        if action == 'start':
            if is_remote:
                try:
                    ssh_client = paramiko.SSHClient()
                    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh_client.connect(**_ssh_connect_kwargs(server_obj))
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
                try:
                    activity = ContainerActivity(
                        container_id='compose',
                        container_name=os.path.basename(compose_dir.rstrip('/')),
                        action='started',
                        image='docker-compose',
                    )
                    db.session.add(activity)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    log.exception("Failed to log compose activity")
            else:
                flash(f'Error starting compose in {compose_dir}: {result.stderr}', 'danger')

        elif action == 'stop':
            if is_remote:
                try:
                    ssh_client = paramiko.SSHClient()
                    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh_client.connect(**_ssh_connect_kwargs(server_obj))
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
                try:
                    activity = ContainerActivity(
                        container_id='compose',
                        container_name=os.path.basename(compose_dir.rstrip('/')),
                        action='stopped',
                        image='docker-compose',
                    )
                    db.session.add(activity)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    log.exception("Failed to log compose activity")
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


def _get_running_compose_projects():
    """Return a dict keyed by compose project name with running/deployed status."""
    projects = {}
    try:
        client, _ = conf()
        containers = client.containers.list(all=True)
        for c in containers:
            labels = c.labels or {}
            proj_name = labels.get('com.docker.compose.project', '')
            if proj_name:
                if proj_name not in projects:
                    projects[proj_name] = {'running': False, 'deployed': True}
                if c.status == 'running':
                    projects[proj_name]['running'] = True
    except Exception:
        pass
    return projects


@main_bp.route('/gitcompose', methods=['GET', 'POST'])
def git_compose():
    """Browse and manage compose projects from the cloned git repo."""
    git_config = GitRepoConfig.get_config()
    if not git_config:
        flash('No git repository configured. Set it up in Settings.', 'warning')
        return redirect(url_for('main.settings'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'pull':
            ok, msg = git_service.pull_repo(
                git_config.local_path, git_config.token, git_config.repo_url)
            if ok:
                git_config.mark_synced()
                flash(msg, 'success')
            else:
                flash(msg, 'danger')
            return redirect(url_for('main.git_compose'))

        if action == 'create':
            project_name = request.form.get('project_name', '').strip()
            if not project_name:
                flash('Project name is required.', 'danger')
                return redirect(url_for('main.git_compose'))
            try:
                ok, msg = git_service.create_compose_project(
                    git_config.local_path, project_name)
                if ok:
                    flash(msg, 'success')
                    rel_path = os.path.join(project_name, 'docker-compose.yml')
                    ok2, msg2 = git_service.commit_and_push(
                        git_config.local_path, rel_path,
                        message=f'Add {project_name}',
                        repo_url=git_config.repo_url,
                        token=git_config.token)
                    if ok2:
                        flash(msg2, 'success')
                    else:
                        flash(msg2, 'warning')
                else:
                    flash(msg, 'danger')
            except ValueError as e:
                flash(str(e), 'danger')
            return redirect(url_for('main.git_compose'))

        compose_path = request.form.get('compose_path', '')
        if not compose_path:
            flash('No compose file specified.', 'danger')
            return redirect(url_for('main.git_compose'))

        try:
            abs_file = git_service._safe_path(git_config.local_path, compose_path)
        except ValueError:
            flash('Invalid path.', 'danger')
            return redirect(url_for('main.git_compose'))

        compose_dir = os.path.dirname(abs_file)
        compose_filename = os.path.basename(abs_file)

        gitops_host_path = current_app.config.get('GITOPS_HOST_PATH', '').strip()
        if gitops_host_path:
            rel_within_repo = os.path.relpath(compose_dir, os.path.realpath(git_config.local_path))
            host_compose_dir = os.path.normpath(os.path.join(gitops_host_path, rel_within_repo))
        else:
            host_compose_dir = None

        if action == 'assign_server':
            raw_sid = request.form.get('server_id', '')
            server_id = int(raw_sid) if raw_sid.isdigit() else None
            ProjectServerMapping.set_server_for_project(compose_path, server_id)
            flash(f'Server assignment updated for {compose_path}.', 'success')
            return redirect(url_for('main.git_compose'))

        override_sid = request.form.get('server_id', '')
        if override_sid.isdigit():
            target_server = DockerServer.query.get(int(override_sid))
        else:
            target_server = ProjectServerMapping.get_server_for_project(compose_path)
        if target_server and target_server.is_configured:
            if target_server.is_ssh_tunnel:
                _open_ssh_tunnel(target_server)
                base_url = target_server.connection_url
            else:
                base_url = f"tcp://{target_server.host}:{target_server.port}"
        else:
            base_url, _ = get_docker_base_url()

        env = os.environ.copy()
        env['DOCKER_HOST'] = base_url

        if action == 'deploy':
            if host_compose_dir:
                command = f'docker compose --project-directory "{host_compose_dir}" -f "{abs_file}" up -d'
            else:
                command = f'docker compose -f "{compose_filename}" up -d'
            try:
                result = subprocess.run(command, shell=True, env=env,
                                        cwd=compose_dir,
                                        capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                flash('Timeout deploying compose project.', 'danger')
                return redirect(url_for('main.git_compose'))
            if result.returncode == 0:
                flash(f'Deployed {compose_path} successfully.', 'success')
            else:
                flash(f'Deploy error: {result.stderr}', 'danger')

        elif action == 'pull_deploy':
            if host_compose_dir:
                pull_cmd = f'docker compose --project-directory "{host_compose_dir}" -f "{abs_file}" pull'
                up_cmd = f'docker compose --project-directory "{host_compose_dir}" -f "{abs_file}" up -d'
            else:
                pull_cmd = f'docker compose -f "{compose_filename}" pull'
                up_cmd = f'docker compose -f "{compose_filename}" up -d'
            try:
                result = subprocess.run(pull_cmd, shell=True, env=env,
                                        cwd=compose_dir,
                                        capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                flash('Timeout pulling compose project.', 'danger')
                return redirect(url_for('main.git_compose'))
            if result.returncode != 0:
                flash(f'Pull error: {result.stderr}', 'danger')
                return redirect(url_for('main.git_compose'))
            try:
                result = subprocess.run(up_cmd, shell=True, env=env,
                                        cwd=compose_dir,
                                        capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                flash('Timeout deploying compose project after pull.', 'danger')
                return redirect(url_for('main.git_compose'))
            if result.returncode == 0:
                flash(f'Pulled and deployed {compose_path} successfully.', 'success')
            else:
                flash(f'Deploy after pull error: {result.stderr}', 'danger')

        elif action == 'stop':
            if host_compose_dir:
                command = f'docker compose --project-directory "{host_compose_dir}" -f "{abs_file}" stop'
            else:
                command = f'docker compose -f "{compose_filename}" stop'
            try:
                result = subprocess.run(command, shell=True, env=env,
                                        cwd=compose_dir,
                                        capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                flash('Timeout stopping compose project.', 'danger')
                return redirect(url_for('main.git_compose'))
            if result.returncode == 0:
                flash(f'Stopped {compose_path}.', 'success')
            else:
                flash(f'Stop error: {result.stderr}', 'danger')

        elif action == 'delete':
            try:
                ok, msg = git_service.delete_compose_project(
                    git_config.local_path, compose_path)
                if ok:
                    flash(msg, 'success')
                    if git_config.auto_push:
                        ok2, msg2 = git_service.commit_and_push(
                            git_config.local_path, compose_path,
                            message=f'Delete {compose_path}',
                            repo_url=git_config.repo_url,
                            token=git_config.token)
                        if ok2:
                            flash(msg2, 'success')
                        else:
                            flash(msg2, 'danger')
                else:
                    flash(msg, 'danger')
            except ValueError as e:
                flash(str(e), 'danger')

        return redirect(url_for('main.git_compose'))

    # GET — list compose files and cross-reference with running containers
    git_status = git_service.get_repo_status(git_config.local_path)
    projects = git_service.list_compose_files(git_config.local_path)
    running_projects = _get_running_compose_projects()
    servers = DockerServer.query.all()
    active_server = DockerServer.get_active()

    for p in projects:
        proj_name = p['relative_dir'] if p['relative_dir'] else os.path.basename(os.path.realpath(git_config.local_path))
        status = running_projects.get(proj_name, {})
        p['running'] = status.get('running', False)
        p['deployed'] = status.get('deployed', False)
        assigned = ProjectServerMapping.get_server_for_project(p['relative_path'])
        p['server_id'] = assigned.id if assigned else None
        p['server_name'] = assigned.display_name if assigned else None

    return render_template('git_compose.html',
                           projects=projects, git_config=git_config,
                           git_status=git_status, servers=servers,
                           active_server=active_server)


@main_bp.route('/gitcompose/edit', methods=['GET', 'POST'])
def git_compose_edit():
    """Edit a compose file from the git repo."""
    git_config = GitRepoConfig.get_config()
    if not git_config:
        flash('No git repository configured.', 'warning')
        return redirect(url_for('main.settings'))

    if request.method == 'POST':
        file_path = request.form.get('path', '')
        content = request.form.get('content', '')
        save_action = request.form.get('save_action', 'save')

        try:
            ok, msg = git_service.save_compose_file(
                git_config.local_path, file_path, content)
            if not ok:
                flash(msg, 'danger')
                return render_template('edit_compose.html',
                                       file_path=file_path, content=content,
                                       auto_push=git_config.auto_push)
            flash(msg, 'success')

            if save_action == 'save_push' or git_config.auto_push:
                ok, msg = git_service.pull_repo(
                    git_config.local_path, git_config.token, git_config.repo_url)
                if not ok:
                    flash(msg, 'danger')
                    return render_template('edit_compose.html',
                                           file_path=file_path, content=content,
                                           auto_push=git_config.auto_push)
                flash(msg, 'success')
                ok, msg = git_service.commit_and_push(
                    git_config.local_path, file_path,
                    repo_url=git_config.repo_url,
                    token=git_config.token)
                if ok:
                    flash(msg, 'success')
                else:
                    flash(msg, 'danger')
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('main.git_compose'))

        return redirect(url_for('main.git_compose'))

    # GET — show editor
    file_path = request.args.get('path', '')
    if not file_path:
        flash('No file specified.', 'danger')
        return redirect(url_for('main.git_compose'))

    try:
        content = git_service.read_compose_file(git_config.local_path, file_path)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('main.git_compose'))

    return render_template('edit_compose.html',
                           file_path=file_path, content=content,
                           auto_push=git_config.auto_push)
