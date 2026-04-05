"""Database models for LightDockerWebUI."""
from datetime import datetime, timezone
from app import db


class DockerServer(db.Model):
    """Docker server configuration model."""
    __tablename__ = "docker_server"

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String(100), nullable=False)  # Friendly name
    host = db.Column(db.String(255), nullable=True)  # Docker host FQDN/IP
    port = db.Column(db.String(10), nullable=True)   # Docker API port
    user = db.Column(db.String(100), nullable=True)  # SSH user for remote commands
    password = db.Column(db.String(255), nullable=True)  # SSH password for remote commands
    is_active = db.Column(db.Boolean, default=False)  # Currently selected server

    def __repr__(self):
        return f"<DockerServer {self.display_name}>"

    @property
    def is_configured(self):
        """Check if Docker server is configured for remote access."""
        return bool(self.host and self.port)

    @property
    def connection_url(self):
        """Get the connection URL for this server."""
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
