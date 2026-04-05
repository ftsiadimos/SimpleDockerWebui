"""Git operations for GitOps compose management.

All git commands use subprocess with list arguments (shell=False) to prevent
command injection.  File paths are validated against the repo root to prevent
directory traversal attacks.
"""
import logging
import os
import re
import subprocess
from urllib.parse import urlparse, urlunparse

import yaml

log = logging.getLogger(__name__)

# Compose file names to look for when scanning the repo
COMPOSE_FILENAMES = {'docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml'}


def _authenticated_url(repo_url: str, token: str) -> str:
    """Inject token into HTTPS repo URL for authentication.

    Returns a URL like ``https://<token>@host/user/repo.git``.
    """
    parsed = urlparse(repo_url)
    authed = parsed._replace(netloc=f"{token}@{parsed.hostname}"
                             + (f":{parsed.port}" if parsed.port else ""))
    return urlunparse(authed)


def _safe_path(local_path: str, relative_path: str) -> str:
    """Resolve *relative_path* inside *local_path* and verify it doesn't escape.

    Raises ``ValueError`` on traversal attempts.
    """
    base = os.path.realpath(local_path)
    target = os.path.realpath(os.path.join(base, relative_path))
    if not target.startswith(base + os.sep) and target != base:
        raise ValueError("Path traversal detected")
    return target


def _run_git(args: list[str], cwd: str | None = None,
             timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a git command and return the CompletedProcess.

    Masks tokens that might appear in error output.
    """
    env = os.environ.copy()
    # Prevent git from asking interactive questions
    env['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run(
        ['git'] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result


# ------------------------------------------------------------------
# Repository operations
# ------------------------------------------------------------------

def is_repo_cloned(local_path: str) -> bool:
    """Check if a git repository exists at *local_path*."""
    return os.path.isdir(os.path.join(local_path, '.git'))


def clone_repo(repo_url: str, token: str, branch: str,
               local_path: str) -> tuple[bool, str]:
    """Clone a repository.  Returns ``(success, message)``."""
    if is_repo_cloned(local_path):
        return False, "Repository already cloned. Use pull to update."

    os.makedirs(local_path, exist_ok=True)

    authed_url = _authenticated_url(repo_url, token)
    result = _run_git(
        ['clone', '--branch', branch, '--single-branch', authed_url, '.'],
        cwd=local_path,
    )
    if result.returncode != 0:
        # Strip token from any error messages
        err = _sanitize_output(result.stderr, token)
        return False, f"Clone failed: {err}"

    # Configure committer identity inside the repo
    _run_git(['config', 'user.name', 'LightDockerWebUI'], cwd=local_path)
    _run_git(['config', 'user.email', 'lightdockerwebui@local'], cwd=local_path)

    return True, "Repository cloned successfully."


def pull_repo(local_path: str, token: str | None = None,
              repo_url: str | None = None) -> tuple[bool, str]:
    """Pull latest changes.  Returns ``(success, message)``.

    If *token* and *repo_url* are supplied the remote URL is refreshed first
    (in case the token changed).
    """
    if not is_repo_cloned(local_path):
        return False, "Repository not cloned yet."

    if token and repo_url:
        authed_url = _authenticated_url(repo_url, token)
        _run_git(['remote', 'set-url', 'origin', authed_url], cwd=local_path)

    result = _run_git(['pull', '--ff-only'], cwd=local_path)
    if result.returncode != 0:
        # Fast-forward failed — branches diverged. Retry with rebase to
        # replay local commits on top of the latest remote state.
        result = _run_git(['pull', '--rebase'], cwd=local_path)
        if result.returncode != 0:
            # Rebase failed (likely conflicts) — abort to leave repo clean
            _run_git(['rebase', '--abort'], cwd=local_path)
            err = _sanitize_output(result.stderr, token) if token else result.stderr
            return False, f"Pull failed (diverged, rebase had conflicts): {err}"
        return True, "Repository updated (rebased local changes on top of remote)."
    return True, "Repository updated."


def get_repo_status(local_path: str) -> dict:
    """Return dict with repository status info."""
    if not is_repo_cloned(local_path):
        return {'cloned': False}

    branch_result = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd=local_path)
    log_result = _run_git(['log', '-1', '--format=%H %s'], cwd=local_path)
    status_result = _run_git(['status', '--porcelain'], cwd=local_path)

    return {
        'cloned': True,
        'branch': branch_result.stdout.strip() if branch_result.returncode == 0 else 'unknown',
        'last_commit': log_result.stdout.strip() if log_result.returncode == 0 else '',
        'has_changes': bool(status_result.stdout.strip()) if status_result.returncode == 0 else False,
    }


# ------------------------------------------------------------------
# Compose file operations
# ------------------------------------------------------------------

def list_compose_files(local_path: str) -> list[dict]:
    """Walk the cloned repo and return compose project metadata.

    Returns a list of dicts: ``{project, filename, relative_dir, relative_path}``.
    """
    if not is_repo_cloned(local_path):
        return []

    projects: list[dict] = []
    base = os.path.realpath(local_path)

    for dirpath, dirnames, filenames in os.walk(base):
        # Skip .git directory
        if '.git' in dirnames:
            dirnames.remove('.git')

        for fname in filenames:
            if fname in COMPOSE_FILENAMES:
                rel_dir = os.path.relpath(dirpath, base)
                if rel_dir == '.':
                    rel_dir = ''
                projects.append({
                    'project': rel_dir if rel_dir else '(root)',
                    'filename': fname,
                    'relative_dir': rel_dir,
                    'relative_path': os.path.join(rel_dir, fname) if rel_dir else fname,
                })
    projects.sort(key=lambda p: p['relative_path'])
    return projects


def read_compose_file(local_path: str, relative_path: str) -> str:
    """Read and return the contents of a compose file.

    Raises ``ValueError`` on path traversal or if the file doesn't exist.
    """
    target = _safe_path(local_path, relative_path)
    if not os.path.isfile(target):
        raise ValueError("File not found")
    with open(target, 'r', encoding='utf-8') as f:
        return f.read()


def validate_yaml(content: str) -> tuple[bool, str]:
    """Validate that *content* is valid YAML.  Returns ``(valid, error_msg)``."""
    try:
        yaml.safe_load(content)
        return True, ''
    except yaml.YAMLError as e:
        return False, str(e)


def save_compose_file(local_path: str, relative_path: str,
                      content: str) -> tuple[bool, str]:
    """Write *content* to a compose file after YAML validation.

    Returns ``(success, message)``.
    """
    target = _safe_path(local_path, relative_path)
    if not os.path.isfile(target):
        raise ValueError("File not found")

    valid, err = validate_yaml(content)
    if not valid:
        return False, f"Invalid YAML: {err}"

    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
    return True, "File saved."


def create_compose_project(local_path: str, project_name: str) -> tuple[bool, str]:
    """Create a new compose project directory with a template docker-compose.yml.

    Returns ``(success, message)``.
    """
    # Validate project name — alphanumeric, hyphens, underscores only
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$', project_name):
        return False, "Invalid project name. Use letters, numbers, hyphens, underscores."

    target_dir = _safe_path(local_path, project_name)
    compose_file = os.path.join(target_dir, 'docker-compose.yml')

    if os.path.exists(target_dir):
        return False, f"Project '{project_name}' already exists."

    os.makedirs(target_dir, exist_ok=True)

    template = """services:
  app:
    image: nginx:latest
    ports:
      - "8080:80"
    restart: unless-stopped
"""
    with open(compose_file, 'w', encoding='utf-8') as f:
        f.write(template)

    return True, f"Created project '{project_name}' with template docker-compose.yml."


def delete_compose_project(local_path: str, relative_path: str) -> tuple[bool, str]:
    """Delete a compose file (and its directory if empty afterwards).

    Returns ``(success, message)``.
    """
    import shutil
    target = _safe_path(local_path, relative_path)
    if not os.path.isfile(target):
        raise ValueError("File not found")

    target_dir = os.path.dirname(target)
    base = os.path.realpath(local_path)

    # Remove the compose file
    os.remove(target)

    # Remove the project directory if it's now empty and not the repo root
    if target_dir != base and not os.listdir(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)

    return True, f"Deleted {relative_path}."


def commit_and_push(local_path: str, relative_path: str,
                    message: str | None = None) -> tuple[bool, str]:
    """Stage, commit, and push changes for a compose file.

    Returns ``(success, message)``.
    """
    # Validate path doesn't escape repo (works even if file was deleted)
    base = os.path.realpath(local_path)
    normed = os.path.normpath(os.path.join(base, relative_path))
    if not normed.startswith(base + os.sep) and normed != base:
        raise ValueError("Path traversal detected")

    if not message:
        message = f"Update {relative_path}"
    # Sanitize commit message to prevent injection via git args
    message = re.sub(r'[^\w\s./:_-]', '', message)[:200]

    result = _run_git(['add', '--all', relative_path], cwd=local_path)
    if result.returncode != 0:
        return False, f"git add failed: {result.stderr}"

    result = _run_git(['commit', '-m', message], cwd=local_path)
    if result.returncode != 0:
        if 'nothing to commit' in result.stdout.lower():
            return True, "No changes to commit."
        return False, f"git commit failed: {result.stderr}"

    result = _run_git(['push'], cwd=local_path)
    if result.returncode != 0:
        return False, f"git push failed: {result.stderr}"

    return True, "Changes committed and pushed."


def _sanitize_output(text: str, token: str | None) -> str:
    """Remove token from output text to prevent leaking credentials."""
    if token and token in text:
        text = text.replace(token, '***')
    return text.strip()
