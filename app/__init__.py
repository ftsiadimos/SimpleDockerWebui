from flask import Flask
import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()


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

    return app


# For backward compatibility
app = create_app()
