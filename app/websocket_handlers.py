"""WebSocket handlers for SSH and container terminal sessions."""
import json
import threading
import time

import docker
import paramiko
from flask import request
from flask_sock import Sock
sock = Sock()

from app.ssh_tunnel import _open_ssh_tunnel, _ssh_connect_kwargs, _tunnel_status


def init_sock(app):
    """Initialize the Sock instance with a Flask app."""
    sock.init_app(app)


@sock.route('/ssh')
def ssh(sock):
    """WebSocket handler to provide a full interactive PTY shell over SSH.

    Implements a background reader thread to stream data from the SSH channel
    to the WebSocket and accepts raw key data from the client. Clients may also
    send a JSON message {type:'resize', cols: N, rows: M} to resize the remote
    pty.
    """
    # Resolve server from query or active
    from app.models import DockerServer

    server_id = request.args.get('server')
    server = None
    if server_id:
        try:
            server = DockerServer.query.get(int(server_id))
        except Exception:
            server = None
    if not server:
        server = DockerServer.get_active()

    if not server:
        sock.send('Error: No server configured')
        return

    # Establish SSH connection
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(**_ssh_connect_kwargs(server))
    except Exception as e:
        sock.send(f'SSH connection error: {e}')
        return

    transport = ssh_client.get_transport()

    # Default terminal size
    cols = int(request.args.get('cols') or 80)
    rows = int(request.args.get('rows') or 24)

    try:
        channel = transport.open_session()
        channel.get_pty(term='xterm', width=cols, height=rows)
        channel.invoke_shell()
        channel.settimeout(0.0)
    except Exception as e:
        sock.send(f'Failed to open interactive shell: {e}')
        try:
            ssh_client.close()
        except Exception:
            pass
        return

    stop_event = threading.Event()

    def _reader():
        """Read from SSH channel and forward to WebSocket."""
        try:
            while not stop_event.is_set():
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if not data:
                            break
                        try:
                            sock.send(data.decode('utf-8', errors='replace'))
                        except Exception:
                            break
                    else:
                        time.sleep(0.01)
                except Exception:
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            try:
                data = sock.receive()
            except Exception:
                break

            if data is None:
                break

            # Try to parse JSON control messages (e.g., resize)
            parsed = None
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = None

            if isinstance(parsed, dict) and parsed.get('type') == 'resize':
                try:
                    c = int(parsed.get('cols', cols))
                    r = int(parsed.get('rows', rows))
                    channel.resize_pty(width=c, height=r)
                except Exception as e:
                    try:
                        sock.send(f'Resize error: {e}')
                    except Exception:
                        pass
                continue

            # Local client-side commands
            if data == 'clear':
                try:
                    sock.send('__CLEAR__')
                except Exception:
                    pass
                continue

            if data == 'exit':
                try:
                    sock.send('Session closed. Bye!')
                except Exception:
                    break

            # Raw input: send directly to SSH channel
            try:
                if isinstance(data, str):
                    channel.send(data)
                else:
                    channel.send(str(data))
            except Exception as e:
                try:
                    sock.send(f'Error sending to channel: {e}')
                except Exception:
                    pass
                break

    finally:
        stop_event.set()
        try:
            channel.close()
        except Exception:
            pass
        try:
            ssh_client.close()
        except Exception:
            pass


@sock.route('/container')
def container(sock):
    """WebSocket PTY for container shells (interactive).

    Establish a Docker exec with TTY and stream I/O between the exec socket and
    the WebSocket. Supports JSON resize messages: {type:'resize', cols: N, rows: M}.
    """
    container_id = request.args.get('id')
    if not container_id:
        sock.send('Error: No container ID provided')
        return

    try:
        from app.ssh_tunnel import conf
        client, _ = conf()
        container = client.containers.get(container_id)
    except (ValueError, docker.errors.NotFound) as e:
        sock.send(f'Error: {e}')
        return

    # Container must be running
    try:
        container.reload()
        state = container.attrs.get('State', {})
        if not state.get('Running'):
            sock.send('Error: Container is not running')
            return
    except Exception:
        sock.send('Error: Failed to inspect container')
        return

    # Try a list of common shells (prefer bash, then sh/ash/dash/zsh).
    # IMPORTANT: only set `exec_id` after exec_start succeeds to avoid a race
    # where the client sends a resize for an exec instance that hasn't started yet.
    exec_id = None
    sock_obj = None
    shells = ['/bin/bash', '/usr/bin/bash', '/bin/sh', '/bin/ash', '/bin/dash', '/bin/zsh']
    for shell in shells:
        created = None
        try:
            created = client.api.exec_create(container.id, cmd=[shell], tty=True, stdin=True)['Id']
            sock_obj = client.api.exec_start(created, tty=True, socket=True)

            # Poll exec_inspect briefly to ensure the exec process started and did
            # not immediately fail (e.g., binary missing such as /bin/bash).
            started = False
            try:
                for _ in range(8):  # poll ~400ms (8 * 50ms)
                    ins = client.api.exec_inspect(created)
                    # If 'Running' field exists and is True it's good
                    if ins.get('Running'):
                        started = True
                        break
                    # If ExitCode is present and non-zero, the exec failed to start
                    if ins.get('ExitCode') is not None and ins.get('ExitCode') != 0:
                        started = False
                        break
                    time.sleep(0.05)
            except Exception:
                # If inspect fails, fall back to assuming it failed to start
                started = False

            if not started:
                # cleanup and try next shell
                try:
                    if hasattr(sock_obj, 'close'):
                        sock_obj.close()
                except Exception:
                    pass
                exec_id = None
                sock_obj = None
                continue

            # success: assign exec_id only after the exec actually started
            exec_id = created
            try:
                # Notify client which shell was chosen (optional, helpful for debugging)
                sock.send(f'Connected to container shell: {shell}')
            except Exception:
                pass
            break
        except Exception:
            exec_id = None
            sock_obj = None
            continue
    if not sock_obj:
        sock.send('Failed to start container shell: no suitable shell found')
        return

    # Access underlying raw socket if present
    raw_sock = sock_obj._sock if hasattr(sock_obj, '_sock') else sock_obj
    try:
        raw_sock.setblocking(False)
    except Exception:
        pass

    stop_event = threading.Event()

    def _reader():
        try:
            while not stop_event.is_set():
                try:
                    data = None
                    try:
                        data = sock_obj.recv(4096)
                    except Exception:
                        try:
                            data = raw_sock.recv(4096)
                        except Exception:
                            data = None
                    if not data:
                        time.sleep(0.01)
                        continue
                    try:
                        sock.send(data.decode('utf-8', errors='replace'))
                    except Exception:
                        break
                except Exception:
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        while True:
            try:
                data = sock.receive()
            except Exception:
                break

            if data is None:
                break

            parsed = None
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = None

            if isinstance(parsed, dict) and parsed.get('type') == 'resize':
                try:
                    c = int(parsed.get('cols', 80))
                    r = int(parsed.get('rows', 24))
                    try:
                        client.api.exec_resize(exec_id, height=r, width=c)
                    except Exception as e:
                        try:
                            sock.send(f'Resize error: {e}')
                        except Exception:
                            pass
                except Exception:
                    pass
                continue

            if data == 'clear':
                try:
                    sock.send('__CLEAR__')
                except Exception:
                    pass
                continue

            if data == 'exit':
                try:
                    sock.send('Session closed. Bye!')
                except Exception:
                    break

            # Forward raw input to container socket
            try:
                if isinstance(data, str):
                    to_send = data.encode('utf-8')
                else:
                    to_send = data
                try:
                    sock_obj.send(to_send)
                except Exception:
                    try:
                        raw_sock.send(to_send)
                    except Exception as e:
                        try:
                            sock.send(f'Error sending to container: {e}')
                        except Exception:
                            pass
                        break
            except Exception as e:
                try:
                    sock.send(f'Error: {e}')
                except Exception:
                    pass
                break

    finally:
        stop_event.set()
        try:
            if hasattr(sock_obj, 'close'):
                sock_obj.close()
        except Exception:
            pass
        try:
            # Best-effort: inspect to trigger cleanup / update state
            client.api.exec_inspect(exec_id)
        except Exception:
            pass
