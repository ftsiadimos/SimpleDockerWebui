"""Flask application configuration."""
import os
from secrets import token_hex

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or token_hex(32)
    INSTANCE_PATH = os.path.join(basedir, 'instance')
    # When running inside Docker the gitops repo is stored at a container-internal
    # path.  Set GITOPS_HOST_PATH to the equivalent path on the Docker HOST so that
    # "docker compose ls" labels reflect the host filesystem (e.g. /srv/app/instance/gitops-repo).
    GITOPS_HOST_PATH = os.environ.get('GITOPS_HOST_PATH', '')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(INSTANCE_PATH, 'serverinfo.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,  # Check connection validity before use
        'pool_recycle': 300,    # Recycle connections after 5 minutes
    }


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
