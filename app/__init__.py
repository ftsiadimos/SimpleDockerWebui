from flask import Flask
import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()


def _add_missing_columns(table, columns):
    """Add missing columns to an existing table if the DB predates the model.

    ``db.create_all()`` only creates missing tables, it never alters existing
    ones. This helper performs a very small, idempotent schema migration for
    newly introduced columns using plain ``ALTER TABLE ... ADD COLUMN``.
    ``columns`` is an iterable of ``(column_name, column_ddl)`` tuples.
    """
    from sqlalchemy import inspect, text
    try:
        inspector = inspect(db.engine)
        if table not in inspector.get_table_names():
            return
        existing = {col['name'] for col in inspector.get_columns(table)}
    except Exception:
        return

    for name, ddl in columns:
        if name in existing:
            continue
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
        except Exception:
            # Never break app startup because of a best-effort migration.
            pass


def create_app(config_class=Config):
    """Application factory for creating Flask app instances."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        from app import models  # noqa: F401
        from app.main import main_bp, init_sock
        app.register_blueprint(main_bp)
        init_sock(app)

        # Ensure instance directory exists for SQLite
        instance_path = app.config.get('INSTANCE_PATH')
        if instance_path and not os.path.exists(instance_path):
            os.makedirs(instance_path, exist_ok=True)

        # Create database tables if they don't exist.
        # In production with multiple gunicorn workers, concurrent create_all() calls can race.
        from sqlalchemy.exc import OperationalError
        try:
            db.create_all()
        except OperationalError as exc:
            if 'already exists' in str(exc).lower():
                pass
            else:
                raise

        # Best-effort schema upgrade for pre-existing databases: add the new
        # SSH key / tunnel columns to the docker_server table if missing.
        _add_missing_columns('docker_server', [
            ('ssh_key', 'VARCHAR(500)'),
            ('ssh_tunnel', 'BOOLEAN DEFAULT 0 NOT NULL'),
            ('tunnel_target', 'VARCHAR(255)'),
            ('localPort', 'VARCHAR(10)'),
        ])

    return app


# For backward compatibility
app = create_app()

