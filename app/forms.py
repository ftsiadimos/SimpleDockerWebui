"""Form definitions for LightDockerWebUI."""
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, PasswordField
from wtforms.validators import Optional, Length, Regexp, DataRequired


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
        'Docker Port',
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
    submit = SubmitField('Add Server')


class SelectServerForm(FlaskForm):
    """Form for selecting the active Docker server."""
    server = SelectField(
        'Select Docker Server',
        coerce=int,
        validators=[DataRequired()]
    )
    submit_select = SubmitField('Connect')


# Backward compatibility alias
AddForm = AddServerForm
    
