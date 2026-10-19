"""Form definitions for LightDockerWebUI."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, PasswordField, BooleanField
from wtforms.validators import Optional, Length, Regexp, DataRequired, URL


class AddServerForm(FlaskForm):
    """Form for adding a new Docker server."""
    display_name = StringField(
        'Server Name',
        validators=[
            DataRequired(message='Server name is required'),
            Length(max=100, message='Name must be less than 100 characters')
        ],
        render_kw={'placeholder': 'My Docker Server'}
    )
    host = StringField(
        'Docker Host (FQDN/IP)',
        validators=[
            Optional(),
            Length(max=255, message='Host must be less than 255 characters')
        ],
        render_kw={'placeholder': 'docker.example.com or 192.168.1.100'}
    )
    port = StringField(
        'Docker or SSH-Port',
        validators=[
            Optional(),
            Length(max=10),
            Regexp(r'^\d*$', message='Port must be a number')
        ],
        render_kw={'placeholder': '2376'}
    )
    user = StringField(
        'SSH User',
        validators=[
            Optional(),
            Length(max=100, message='User must be less than 100 characters')
        ],
        render_kw={'placeholder': 'root or your-username', 'autocomplete': 'username'}
    )
    password = PasswordField(
        'SSH Password',
        validators=[
            Optional(),
            Length(max=255, message='Password must be less than 255 characters')
        ],
        render_kw={'placeholder': 'SSH password (optional if using keys)', 'autocomplete': 'current-password'}
    )
    ssh_key = SelectField(
        'SSH Key',
        validators=[Optional()],
        choices=[],
        validate_choice=False,
    )
    # Use an SSH tunnel instead of a manually entered local port. The local
    # tunnel port itself is assigned dynamically by the application.
    ssh_tunnel = BooleanField('Use SSH Tunnel (dynamic local port)', default=False)
    # Remote Docker endpoint reached through the SSH tunnel. Defaults to the
    # standard Docker unix socket /var/run/docker.sock.
    tunnel_target = StringField(
        'Docker Endpoint (tunnel target)',
        validators=[
            Optional(),
            Length(max=255, message='Endpoint must be less than 255 characters')
        ],
        default='/var/run/docker.sock',
        render_kw={'placeholder': '/var/run/docker.sock or 127.0.0.1:2375'}
    )
    submit = SubmitField('Add Server')


class SelectServerForm(FlaskForm):
    """Form for selecting the active Docker server."""
    server = SelectField(
        'Select Docker Server',
        coerce=int,
        validators=[DataRequired()]
    )
    submit_select = SubmitField('Connect')


class GitRepoForm(FlaskForm):
    """Form for configuring the global git repository for GitOps."""
    repo_url = StringField(
        'Repository URL',
        validators=[
            DataRequired(message='Repository URL is required'),
            Length(max=500),
            URL(message='Must be a valid URL (e.g. https://gitea.example.com/user/repo.git)')
        ],
        render_kw={'placeholder': 'https://gitea.example.com/user/compose-files.git'}
    )
    token = PasswordField(
        'Personal Access Token',
        validators=[
            Optional(),
            Length(max=500)
        ],
        render_kw={'placeholder': 'Gitea personal access token', 'autocomplete': 'off'}
    )
    branch = StringField(
        'Branch',
        validators=[
            DataRequired(),
            Length(max=100),
            Regexp(r'^[a-zA-Z0-9._/-]+$', message='Invalid branch name')
        ],
        render_kw={'placeholder': 'main'},
        default='main'
    )
    auto_push = BooleanField('Auto commit & push on save', default=True)
    submit_git = SubmitField('Save & Clone')


# Backward compatibility alias
AddForm = AddServerForm
    
