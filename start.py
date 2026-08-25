from app import app, db
from app.models import Owner
from app.context_processors import select_form_processor

app.context_processor(select_form_processor)

@app.shell_context_processor
def make_shell_context():
    return {'db':db, 'Owner': Owner}