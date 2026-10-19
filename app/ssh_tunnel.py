"""SSH tunnel management for remote Docker servers.

Handles local port-forwarding via SSH to remote Docker daemons,
including Unix socket and TCP target support.
"""
import logging
import select
import socket
import threading

import docker
import paramiko  # type: ignore

log = logging.getLogger(__name__)

# Cache for Docker client to avoid reconnecting on every request
_docker_client_cache = {}

# Keyed by server id -> _SSHTunnel instance. Allows reusing an already open
# tunnel across requests and cleaning it up when the server is switched/deleted.
_ssh_tunnels = {}
_ssh_tunnels_lock = threading.Lock()


class _SSHTunnel:
    """A local port-forward (``ssh -L``) mapping 127.0.0.1:<localPort> to the
    remote Docker API endpoint.

    The local listener socket is owned and managed by this class. For every
    incoming local connection we open an SSH channel to the remote target:
      - ``('unix', '/var/run/docker.sock')`` -> OpenSSH ``direct-streamlocal``
        channel (equivalent to ``ssh -L port:/var/run/docker.sock``)
      - ``('tcp', ('host', port))``          -> ``direct-tcpip`` channel
        (equivalent to ``ssh -L port:host:port``)

    This mirrors what the OpenSSH client does for ``-L`` forwards and does
    NOT require the SSH server to allow *remote* (``-R``) forwarding, so it
    works on servers where ``request_port_forward`` would be denied.
    """

    def __init__(self, ssh_client, bind_host, bind_port, target):
        self.ssh_client = ssh_client
        self.transport = ssh_client.get_transport()
        self.bind_host = bind_host
        self.bind_port = bind_port
        # target is (kind, value): ('unix', path) or ('tcp', (host, port))
        self.target = target
        self._stop = threading.Event()
        self._thread = None
        self._listener = None
        self._channels = []

    @property
    def target_label(self):
        """Human readable description of the forward target."""
        kind, value = self.target
        if kind == 'unix':
            return value
        return f"{value[0]}:{value[1]}"

    def start(self):
        # For a classic local forward we only need to accept connections on a
        # local socket and open a channel to the remote target for each one.
        # Bind synchronously so a bind failure (e.g. port in use) is raised to
        # the caller instead of silently failing in the thread.
        import socket as _socket
        listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        listener.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.bind_host, self.bind_port))
        except OSError:
            listener.close()
            raise
        listener.listen(50)
        listener.settimeout(0.5)
        self._listener = listener

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self):
        listener = self._listener
        if listener is None:
            return
        while not self._stop.is_set():
            try:
                client_conn, addr = listener.accept()
            except Exception:
                # Timeout (0.5s) or listener closed -> loop again / exit.
                if self._stop.is_set():
                    break
                continue
            try:
                chan = self._open_channel(addr)
            except Exception as exc:
                log.warning("SSH tunnel: failed to open channel to %s: %s",
                            self.target_label, exc)
                try:
                    client_conn.close()
                except Exception:
                    pass
                continue
            self._channels.append(chan)
            handler = threading.Thread(
                target=self._bridge, args=(client_conn, chan), daemon=True)
            handler.start()

    def _open_channel(self, src_addr):
        """Open an SSH channel (direct-streamlocal or direct-tcpip) to target."""
        kind, value = self.target
        if kind == 'unix':
            return _open_direct_streamlocal_channel(self.transport, value)
        return self.transport.open_channel('direct-tcpip', value, src_addr)

    def _bridge(self, sock, chan):
        """Pump bytes in both directions between the local socket and channel."""
        try:
            while not self._stop.is_set():
                r, _w, _x = select.select([sock, chan], [], [], 0.5)
                if sock in r:
                    data = sock.recv(4096)
                    if not data:
                        break
                    chan.sendall(data)
                if chan in r:
                    data = chan.recv(4096)
                    if not data:
                        break
                    sock.sendall(data)
        except Exception:
            pass
        finally:
            for obj in (chan, sock):
                try:
                    obj.close()
                except Exception:
                    pass
            if chan in self._channels:
                self._channels.remove(chan)

    def stop(self):
        self._stop.set()
        try:
            if self._listener:
                self._listener.close()
        except Exception:
            pass
        for chan in list(self._channels):
            try:
                chan.close()
            except Exception:
                pass
        try:
            self.ssh_client.close()
        except Exception:
            pass


def _open_direct_streamlocal_channel(transport, socket_path):
    """Open an OpenSSH ``direct-streamlocal@openssh.com`` channel.

    This is the channel type OpenSSH uses for ``ssh -L localport:/path/to.sock``
    (Unix domain socket forwarding). Paramiko's ``open_channel`` does not
    implement it, so we craft the ``SSH_MSG_CHANNEL_OPEN`` message ourselves,
    following the OpenSSH PROTOCOL spec:

        byte      SSH_MSG_CHANNEL_OPEN
        string    "direct-streamlocal@openssh.com"
        uint32    sender channel
        uint32    initial window size
        uint32    maximum packet size
        string    socket path
        string    reserved (empty)
        uint32    reserved (0)
    """
    import time as _time
    from paramiko.message import Message
    from paramiko.channel import Channel
    from paramiko.common import cMSG_CHANNEL_OPEN
    from paramiko.ssh_exception import SSHException

    if not transport.active:
        raise SSHException("SSH session not active")

    timeout = transport.channel_timeout
    transport.lock.acquire()
    try:
        window_size = transport._sanitize_window_size(None)
        max_packet_size = transport._sanitize_packet_size(None)
        chanid = transport._next_channel()
        m = Message()
        m.add_byte(cMSG_CHANNEL_OPEN)
        m.add_string("direct-streamlocal@openssh.com")
        m.add_int(chanid)
        m.add_int(window_size)
        m.add_int(max_packet_size)
        m.add_string(socket_path)
        m.add_string("")   # reserved: originator address
        m.add_int(0)       # reserved: originator port
        chan = Channel(chanid)
        transport._channels.put(chanid, chan)
        transport.channel_events[chanid] = event = threading.Event()
        transport.channels_seen[chanid] = True
        chan._set_transport(transport)
        chan._set_window(window_size, max_packet_size)
    finally:
        transport.lock.release()

    transport._send_user_message(m)
    start_ts = _time.time()
    while True:
        event.wait(0.1)
        if not transport.active:
            e = transport.get_exception()
            if e is None:
                e = SSHException("Unable to open channel.")
            raise e
        if event.is_set():
            break
        if start_ts + timeout < _time.time():
            raise SSHException("Timeout opening channel.")
    chan = transport._channels.get(chanid)
    if chan is not None:
        return chan
    e = transport.get_exception()
    if e is None:
        e = SSHException("Unable to open channel.")
    raise e


def _ssh_connect_kwargs(server):
    """Build paramiko ``connect`` kwargs honoring password/key authentication.

    If the server has an ``ssh_key`` configured, key-based auth with that
    specific key file is used. Otherwise password based auth is used (when a
    password is stored), falling back to the SSH agent / default key lookup.
    """
    kwargs = {
        'hostname': server.host,
        'username': server.user,
        'timeout': 10,
    }
    key_path = server.resolve_ssh_key()
    if key_path:
        kwargs.update({
            'key_filename': key_path,
            'look_for_keys': False,
            'allow_agent': False,
        })
        if server.password:
            kwargs['password'] = server.password
    elif server.password:
        kwargs.update({
            'password': server.password,
            'look_for_keys': False,
            'allow_agent': False,
        })
    else:
        kwargs.update({'allow_agent': True, 'look_for_keys': True})
    return kwargs


def _open_ssh_tunnel(server):
    """Open (or reuse) a local SSH tunnel for ``server``.

    Returns the ``_SSHTunnel`` instance on success, ``None`` if no tunnel is
    configured, or raises on connection failure.
    """
    if not (server.host and server.port and server.ssh_tunnel):
        return None
    # Ensure a dynamic local port has been assigned (stored on the model).
    local_port = server.ensure_local_port(persist=True)
    if not local_port:
        return None

    with _ssh_tunnels_lock:
        existing = _ssh_tunnels.get(server.id)
        if existing and existing.ssh_client.get_transport() \
                and existing.ssh_client.get_transport().is_active():
            return existing

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Try to connect with better error handling
        try:
            ssh_client.connect(**_ssh_connect_kwargs(server))
        except (paramiko.ssh_exception.SSHException, 
                paramiko.ssh_exception.AuthenticationException,
                socket.error,
                socket.timeout,
                OSError,
                ConnectionRefusedError,
                TimeoutError) as e:
            ssh_client.close()
            error_msg = f"SSH connection to {server.host}:{server.port} failed: {e}"
            log.error(error_msg)
            raise Exception(error_msg) from e

        # Destination the SSH server forwards to (unix socket or tcp host:port).
        target = server.tunnel_target_spec

        # If the previously assigned local port is occupied (e.g. leftover
        # process), pick a fresh free port and persist it.
        try:
            tunnel = _SSHTunnel(
                ssh_client,
                bind_host='127.0.0.1',
                bind_port=local_port,
                target=target,
            ).start()
        except OSError:
            ssh_client.close()
            server.localPort = None
            new_port = server.ensure_local_port()
            if not new_port:
                raise
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh_client.connect(**_ssh_connect_kwargs(server))
            except (paramiko.ssh_exception.SSHException,
                    paramiko.ssh_exception.AuthenticationException,
                    socket.error,
                    socket.timeout,
                    OSError,
                    ConnectionRefusedError,
                    TimeoutError) as e:
                ssh_client.close()
                error_msg = f"SSH connection to {server.host}:{server.port} failed: {e}"
                log.error(error_msg)
                raise Exception(error_msg) from e
            tunnel = _SSHTunnel(
                ssh_client,
                bind_host='127.0.0.1',
                bind_port=new_port,
                target=target,
            ).start()
        _ssh_tunnels[server.id] = tunnel
        return tunnel


def _close_ssh_tunnel(server_id):
    """Close and forget the tunnel for ``server_id`` (if any)."""
    with _ssh_tunnels_lock:
        tunnel = _ssh_tunnels.pop(server_id, None)
    if tunnel:
        try:
            tunnel.stop()
        except Exception:
            log.exception("Failed to close SSH tunnel for server %s", server_id)


def _tunnel_status(server):
    """Return a display-friendly dict describing the SSH tunnel state.

    Keys:
      configured     -- the server has an SSH tunnel defined (host/port/localPort)
      active         -- a live tunnel is currently open for this server
      local_port     -- the configured local port (int) or None
      remote         -- "127.0.0.1:<port>" the Docker API is forwarded to, or None
    """
    configured = bool(server and server.host and server.port and server.ssh_tunnel)
    active = False
    if configured:
        with _ssh_tunnels_lock:
            tunnel = _ssh_tunnels.get(server.id)
        if tunnel and tunnel.ssh_client.get_transport() \
                and tunnel.ssh_client.get_transport().is_active():
            active = True
    return {
        'configured': configured,
        'active': active,
        'local_port': server.local_port if configured else None,
        'remote': _target_label(server) if configured else None,
    }


def _target_label(server):
    """Human readable label for the SSH tunnel target of ``server``."""
    try:
        kind, value = server.tunnel_target_spec
        if kind == 'unix':
            return value
        return f"{value[0]}:{value[1]}"
    except Exception:
        return None


def get_docker_base_url():
    """Get the Docker base URL from the active server configuration.

    If the server has an SSH tunnel configured, the tunnel is opened (or
    reused) and the local forwarded port is used as the Docker endpoint.
    """
    from app.models import DockerServer
    
    server = DockerServer.get_active()
    if not server or not server.is_configured:
        return 'unix://var/run/docker.sock', server
    if server.is_ssh_tunnel:
        _open_ssh_tunnel(server)
        return server.connection_url, server
    return f"tcp://{server.host}:{server.port}", server


def conf(use_cache=True):
    """
    Return a Docker client and the Owner record.

    If the Owner record does not specify a host/port, connect to the
    local Docker daemon via the Unix socket.

    Args:
        use_cache: If True, reuse cached client for the same base_url.

    Raises:
        ValueError: If the Docker endpoint cannot be reached.
    """
    base_url, serverurl = get_docker_base_url()

    # Return cached client if available and valid
    if use_cache and base_url in _docker_client_cache:
        try:
            client = _docker_client_cache[base_url]
            client.ping()
            return client, serverurl
        except docker.errors.DockerException:
            # Client is stale, remove from cache
            _docker_client_cache.pop(base_url, None)

    try:
        client = docker.DockerClient(base_url=base_url, timeout=60)
        client.ping()
        if use_cache:
            _docker_client_cache[base_url] = client
    except docker.errors.DockerException as exc:
        raise ValueError(f"Cannot connect to Docker at {base_url}: {exc}") from exc

    return client, serverurl
