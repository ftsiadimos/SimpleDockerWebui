"""Database models for LightDockerWebUI."""
import os
import socket
from datetime import datetime, timezone
from app import db


class DockerServer(db.Model):
    """Docker server configuration model."""
    __tablename__ = "docker_server"

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(100), nullable=False)  # Friendly name
    host = db.Column(db.String(255), nullable=True)  # Docker host FQDN/IP
    port = db.Column(db.String(10), nullable=True)   # Docker API or SSH port
    user = db.Column(db.String(100), nullable=True)  # SSH user for remote commands
    password = db.Column(db.String(255), nullable=True)  # SSH password for remote commands
    # Selected SSH key: basename of a key file inside <USERHOME>/.ssh (or an absolute path).
    ssh_key = db.Column(db.String(500), nullable=True)
    # Local ssh tunnel port. Assigned dynamically by the app, never user editable.
    localPort = db.Column(db.String(10), nullable=True)
    # Use an SSH tunnel to reach the Docker API (replaces the manual localPort field).
    ssh_tunnel = db.Column(db.Boolean, default=False, nullable=False)
    # Remote Docker endpoint reached through the SSH tunnel. Default: the
    # standard Docker unix socket. Can also be "host:port" for a TCP endpoint.
    tunnel_target = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=False)  # Currently selected server

    def __repr__(self):
        return f"<DockerServer {self.display_name}>"

    @staticmethod
    def ssh_dir():
        """Return the SSH directory of the current user (<USERHOME>/.ssh)."""
        return os.path.join(os.path.expanduser('~'), '.ssh')

    @staticmethod
    def list_ssh_keys():
        """List all SSH key files found in <USERHOME>/.ssh.

        Public keys (*.pub) and known metadata files (known_hosts,
        authorized_keys, config, ...) are skipped. Returns a list of basenames.
        """
        ssh_dir = DockerServer.ssh_dir()
        if not os.path.isdir(ssh_dir):
            return []
        skip = {
            'known_hosts', 'known_hosts.old', 'authorized_keys',
            'authorized_keys2', 'config', 'environment',
        }
        keys = []
        try:
            for name in os.listdir(ssh_dir):
                full = os.path.join(ssh_dir, name)
                if not os.path.isfile(full):
                    continue
                if name.endswith('.pub') or name in skip:
                    continue
                keys.append(name)
        except OSError:
            return []
        return sorted(keys)

    def resolve_ssh_key(self):
        """Resolve the stored SSH key value to an absolute file path."""
        if not self.ssh_key:
            return None
        if os.path.isabs(self.ssh_key):
            return self.ssh_key
        return os.path.join(self.ssh_dir(), os.path.basename(self.ssh_key))

    @property
    def auth_method(self):
        """Return the configured SSH auth method ('key' or 'password')."""
        return 'key' if self.ssh_key else 'password'

    @property
    def is_configured(self):
        """Check if Docker server is configured for remote access."""
        return bool(self.host and self.port)

    @property
    def is_ssh_tunnel(self):
        """Check if the SSH tunnel option is enabled for this server."""
        if not (self.host and self.port and self.ssh_tunnel):
            return False
        # Assign a dynamic local port on first use (persisted to the model).
        if not self.localPort:
            self.ensure_local_port(persist=True)
        return bool(self.localPort)

    def ensure_local_port(self, persist=False):
        """Assign a free local TCP port (dynamic) if none is set yet.

        The port is stored in ``localPort`` so the tunnel endpoint stays stable
        across requests. Returns the assigned port as int, or None on failure.
        """
        if self.local_port:
            return self.local_port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                free_port = s.getsockname()[1]
        except OSError:
            return None
        self.localPort = str(free_port)
        if persist:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return free_port

    @property
    def local_port(self):
        """Return the local tunnel port as int (or None if unset/invalid)."""
        try:
            return int(self.localPort)
        except (TypeError, ValueError):
            return None

    @property
    def tunnel_target_spec(self):
        """Return the SSH tunnel target as a (kind, value) tuple.

        - ``('unix', '/var/run/docker.sock')`` when the target denotes a unix
          socket path (default).
        - ``('tcp', ('host', port))`` when the target looks like ``host:port``.
        """
        target = (self.tunnel_target or '/var/run/docker.sock').strip()
        if target.startswith('/') or target.startswith('unix://'):
            path = target
            if path.startswith('unix://'):
                path = path[len('unix://'):]
            return ('unix', path)
        # host:port form
        if ':' in target:
            host, _, port = target.rpartition(':')
            try:
                return ('tcp', (host or '127.0.0.1', int(port)))
            except ValueError:
                pass
        # Fallback: treat "host" as TCP host on the standard Docker port.
        return ('tcp', (target or '127.0.0.1', 2375))

    @property
    def connection_url(self):
        """Get the connection URL for this server.

        When an SSH tunnel is configured the Docker daemon is reached via the
        locally-forwarded port (127.0.0.1:<localPort>). Otherwise we connect
        directly to the remote host.
        """
        if self.is_ssh_tunnel and self.local_port:
            return f"tcp://127.0.0.1:{self.local_port}"
        if self.is_configured:
            return f"tcp://{self.host}:{self.port}"
        return "unix://var/run/docker.sock"

    @classmethod
    def get_active(cls):
        """Get the currently active Docker server."""
        return cls.query.filter_by(is_active=True).first()

    @classmethod
    def set_active(cls, server_id):
        """Set a server as active and deactivate others."""
        cls.query.update({cls.is_active: False})
        server = cls.query.get(server_id)
        if server:
            server.is_active = True
        db.session.commit()
        return server


# Alias for backward compatibility
Owner = DockerServer


class GitRepoConfig(db.Model):
    """Global git repository configuration for GitOps compose management."""
    __tablename__ = "git_repo_config"

    id = db.Column(db.Integer, primary_key=True)
    repo_url = db.Column(db.String(500), nullable=False)
    token = db.Column(db.String(500), nullable=False)
    branch = db.Column(db.String(100), nullable=False, default='main')
    local_path = db.Column(db.String(500), nullable=False)
    auto_push = db.Column(db.Boolean, default=True)
    last_synced = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<GitRepoConfig {self.repo_url}>"

    @classmethod
    def get_config(cls):
        """Get the global git repo config (single row)."""
        return cls.query.first()

    def mark_synced(self):
        """Update the last_synced timestamp to now."""
        self.last_synced = datetime.now(timezone.utc)
        db.session.commit()


class ContainerActivity(db.Model):
    """Track container lifecycle events (start, stop, restart) for dashboard activity feed."""
    __tablename__ = "container_activity"

    id = db.Column(db.Integer, primary_key=True)
    container_id = db.Column(db.String(256), nullable=False)  # Short container ID
    container_name = db.Column(db.String(256), nullable=False)
    action = db.Column(db.String(32), nullable=False)  # 'started', 'stopped', 'restarted'
    image = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<ContainerActivity {self.container_name} {self.action}>"

    @classmethod
    def get_recent(cls, limit: int = 10) -> list:
        """Return the most recent activity entries, ordered newest first."""
        return (
            cls.query.order_by(cls.timestamp.desc()).limit(limit).all()
        )


class ProjectServerMapping(db.Model):
    """Maps a git compose project (by relative path) to a target Docker server."""
    __tablename__ = "project_server_mapping"

    id = db.Column(db.Integer, primary_key=True)
    project_path = db.Column(db.String(500), nullable=False, unique=True)
    server_id = db.Column(
        db.Integer,
        db.ForeignKey('docker_server.id', ondelete='SET NULL'),
        nullable=True,
    )

    server = db.relationship('DockerServer', lazy='joined')

    def __repr__(self):
        return f"<ProjectServerMapping {self.project_path} -> server {self.server_id}>"

    @classmethod
    def get_server_for_project(cls, project_path):
        """Return the assigned DockerServer for a project, or None."""
        mapping = cls.query.filter_by(project_path=project_path).first()
        if mapping and mapping.server:
            return mapping.server
        return None

    @classmethod
    def set_server_for_project(cls, project_path, server_id):
        """Create or update the server mapping for a project.

        Pass server_id=None to clear the assignment (fall back to active).
        """
        mapping = cls.query.filter_by(project_path=project_path).first()
        if server_id is None:
            if mapping:
                db.session.delete(mapping)
                db.session.commit()
            return
        if mapping:
            mapping.server_id = server_id
        else:
            mapping = cls(project_path=project_path, server_id=server_id)
            db.session.add(mapping)
        db.session.commit()
