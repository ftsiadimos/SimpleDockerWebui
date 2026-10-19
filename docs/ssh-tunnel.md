# SSH Tunnel Guide

**Contributed by:** Sven Hofrichter (sven@hofrichter.net)

## Preparations

On the remote VM, a restricted SSH user must be given access to `/var/run/docker.sock`. The management host then establishes an SSH tunnel to the Docker Unix socket and binds it locally to a TCP port.

**Important:** Access to the Docker socket is roughly equivalent to root privileges on the remote host. The SSH user described here prevents shell access, arbitrary SSH commands, TCP forwarding, and remote socket forwarding. However, they can still use the Docker socket and manage containers with it. For the strongest isolation, a Docker socket proxy should additionally be used; see below.

## Security model

The `docker-agent` user may only:

- log in using public-key authentication,
- establish an SSH tunnel to a Unix socket on the remote host,
- forward local TCP ports on the management host to the remote Docker socket.

They must not:

- open an interactive shell,
- execute arbitrary SSH commands,
- forward TCP ports,
- forward Unix sockets from the management host back to the remote host,
- use agent forwarding, X11 forwarding, or PTYs.

With `AllowStreamLocalForwarding local`, OpenSSH allows only local Unix socket forwardings from the SSH client's perspective; `PermitOpen none` forbids all TCP forwarding destinations.

## Prepare access

### Management host

Create a separate key for each remote host:

```shell
HOST_NAME="my-remote-host"

ssh-keygen -t ed25519 \
  -C "docker-agent-tunnel-${HOST_NAME}" \
  -f ~/.ssh/docker_agent_${HOST_NAME}_ed25519

cat ~/.ssh/docker_agent_${HOST_NAME}_ed25519.pub
```

The output of `cat` is entered into `~/.ssh/authorized_keys` in the next section.

### Target/remote host

```shell
USER_NAME="docker-agent"

# Create a system user without a home directory.
# The shell must work so that SSH can keep the tunnel alive.
# The actual protection is provided by ForceCommand in the sshd Match block.
PASSWORD_HASH="$(openssl passwd -6 "$(openssl rand -base64 32)")"
sudo useradd --system \
  --shell /bin/sh \
  --home-dir /nonexistent \
  --no-create-home \
  --password "$PASSWORD_HASH" \
  "$USER_NAME"

# Create the SSH configuration for the user
sudo install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" \
  /home/${USER_NAME}/.ssh

sudo usermod --unlock --home /home/docker-agent docker-agent
sudo sh -c 'echo "docker-agent:$(openssl rand -base64 32)" | chpasswd'

sudo install -d -m 0755 -o docker-agent -g docker-agent /home/docker-agent
sudo install -d -m 0700 -o docker-agent -g docker-agent /home/docker-agent/.ssh

# Store the management host's public key.
# No permitopen="any": TCP forwarding is completely forbidden on the server side.
echo "restrict,port-forwarding ssh-ed25519 AAAAC3Nza..." \
  | sudo tee /home/${USER_NAME}/.ssh/authorized_keys

sudo chown -R "$USER_NAME:$USER_NAME" /home/docker-agent
sudo chmod 0750 /home/docker-agent
sudo chmod 0700 /home/docker-agent/.ssh
sudo chmod 0600 /home/${USER_NAME}/.ssh/authorized_keys

# Ensure the Docker group exists
sudo groupadd --force docker

# Add the user for Docker socket access
sudo usermod -aG docker "$USER_NAME"

# Check Docker socket permissions
sudo -u docker-agent ls -l /var/run/docker.sock
```

If the socket is not already configured correctly:

```shell
sudo chown root:docker /var/run/docker.sock
sudo chmod 0660 /var/run/docker.sock
```

## Harden the SSH server

Create a dedicated SSH configuration:

```shell
sudo vi /etc/ssh/sshd_config.d/60-docker-agent.conf
```

Content:

```text
Match User docker-agent
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    AllowTcpForwarding local
    PermitListen none
    # Allow only local Unix socket forwardings:
    # ssh -L <local port>:/var/run/docker.sock
    AllowStreamLocalForwarding local
    # Force a harmless, long-running process.
    # Without this command, the session would end immediately.
    ForceCommand sleep 31536000
    StreamLocalBindUnlink yes
```

Then check the configuration and reload SSH:

```shell
sudo sshd -t && sudo systemctl reload ssh
```

Notes:

- `ForceCommand` overrides any command requested by the client. This means the user does not get a shell and cannot execute arbitrary commands.
- `sleep` is started via the user's shell. Therefore `/bin/sh` is required; `/usr/sbin/nologin` would terminate the SSH session immediately.
- `AllowStreamLocalForwarding local` is required for this use case because `ssh -L <Port>:/var/run/docker.sock` uses Unix socket forwarding.
- `PermitOpen none` blocks TCP forwarding; this is independent of Unix socket forwarding.

## Management host: set up the SSH tunnel

### Linux

Determine the IP of the Docker network if the WebUI runs in a container and the tunnel should only be reachable for this container:

Determine the image's networks:

```shell
docker ps

IMAGE_NETWORK=$(docker inspect --format='{{range $net, $config := .NetworkSettings.Networks}}{{$net}}{{println}}{{end}}' "<image-name-oder-id>")

GATEWAY_IP="$(
  docker network inspect $IMAGE_NETWORK \
    | grep Gateway \
    | grep -Eo '[0-9.]+'
)"
```

For a manual test:

```shell
HOST_NAME="my-remote-host"
SSH_PORT="22"
TUNNEL_PORT_FOR_HOST="22222"

ssh -N \
  -p "$SSH_PORT" \
  -i ~/.ssh/docker_agent_${HOST_NAME}_ed25519 \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -L "${GATEWAY_IP}:${TUNNEL_PORT_FOR_HOST}:/var/run/docker.sock" \
  docker-agent@"$HOST_NAME"
```

For a persistent tunnel with `autossh`:

```shell
HOST_NAME="my-remote-host"
SSH_PORT="22"
TUNNEL_PORT_FOR_HOST="12376"

autossh -M 0 \
  -p "$SSH_PORT" \
  -N \
  -i ~/.ssh/docker_agent_${HOST_NAME}_ed25519 \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -L "${GATEWAY_IP}:${TUNNEL_PORT_FOR_HOST}:/var/run/docker.sock" \
  docker-agent@"$HOST_NAME"
```

### Windows

If possible, do not bind the tunnel to `0.0.0.0`. Otherwise it would be reachable from the local network if the Windows firewall allows the port.

Preferably bind only locally:

```powershell
$HOST_NAME = "my-remote-host"
$SSH_PORT = 22
$TUNNEL_PORT_FOR_HOST = 12376

ssh -N `
  -p $SSH_PORT `
  -i "$env:USERPROFILE\.ssh\docker_agent_${HOST_NAME}_ed25519" `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -o ExitOnForwardFailure=yes `
  -L "127.0.0.1:$($TUNNEL_PORT_FOR_HOST):/var/run/docker.sock" `
  docker-agent@$HOST_NAME
```

If the WebUI runs in Docker Desktop and uses `host.docker.internal`, `127.0.0.1` is usually sufficient.

If the tunnel should specifically be reachable only from the Docker network, use the gateway IP of the respective Docker network instead of `0.0.0.0`:

```powershell
ssh -N `
  -L "${GATEWAY_IP}:$($TUNNEL_PORT_FOR_HOST):/var/run/docker.sock" `
  docker-agent@$HOST_NAME
```

## Persistent tunnel under Linux

Create a systemd user unit:

```shell
mkdir -p ~/.config/systemd/user
vi ~/.config/systemd/user/docker-agent-tunnel@.service
```

Content:

```ini
[Unit]
Description=SSH tunnel to Docker socket on %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/ssh -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -o StrictHostKeyChecking=yes \
  -F %h/.ssh/config \
  %i
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Add an alias per remote host in `~/.ssh/config`:

```text
Host tunnel-my-remote-host
    HostName my-remote-host
    Port 22
    User docker-agent
    IdentityFile ~/.ssh/docker_agent_my-remote-host_ed25519
    IdentitiesOnly yes
    ExitOnForwardFailure yes
    ServerAliveInterval 30
    ServerAliveCountMax 3
    LocalForward 127.0.0.1:12376 /var/run/docker.sock
```

Enable:

```shell
systemctl --user daemon-reload
systemctl --user enable --now docker-agent-tunnel@tunnel-my-remote-host.service
systemctl --user status docker-agent-tunnel@tunnel-my-remote-host.service
```

## In LightDockerWebUI

Configuration:

- **Host/IP:** `host.docker.internal`
- **Port:** `$TUNNEL_PORT_FOR_HOST`, for example `12376`

On Linux without Docker Desktop, `host.docker.internal` may not be available. In this case, either use the Docker gateway IP or add the following to `docker-compose.yml`:

```yaml
services:
  light-docker-webui:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

## Verification

On the remote host:

```shell
sudo journalctl -u ssh -e
sudo sshd -T -C user=docker-agent,host=localhost,addr=127.0.0.1 \
  | grep -E 'allowtcpforwarding|allowstreamlocalforwarding|permitopen|forcecommand|permittty'
```

From the management host:

```shell
ssh -N \
  -L 127.0.0.1:12376:/var/run/docker.sock \
  docker-agent@my-remote-host
```

In a second terminal:

```shell
curl --unix-socket /var/run/docker.sock http://localhost/_ping
```

Or against the local tunnel:

```shell
curl http://127.0.0.1:12376/_ping
```

Expected output:

```text
OK
```

## Optional hardening: Docker socket proxy

Direct Docker socket access effectively gives the tunnel user full control over Docker. If the WebUI only needs container status, logs, start/stop, and similar actions, a socket proxy is the better solution.

In this setup, a container runs on the remote host that exposes the Docker API with a whitelist/filtering configuration. The SSH tunnel then no longer points directly to `/var/run/docker.sock`, but to the local proxy port.

Example:

```shell
ssh -N \
  -L 127.0.0.1:12376:127.0.0.1:2375 \
  docker-agent@my-remote-host
```

In this case, `docker-agent` does not need access to `/var/run/docker.sock` and should therefore **not** be a member of the `docker` group.

# Deleting the docker-agent user

If access to a remote host is no longer required, the user can be completely deleted on that machine.

## Preparation

First, check whether any processes are still running.

```shell
ps -u docker-agent -f
sudo pkill -u docker-agent
```

## Delete the user and clean up groups

```shell
# Delete user `docker-agent`
sudo userdel --remove docker-agent

# Clean up the `docker` group
sudo gpasswd --delete docker-agent docker

# Remove user-specific SSH settings
sudo rm /etc/ssh/sshd_config.d/60-docker-agent.conf
sudo sshd -t && sudo systemctl reload ssh
```

## Search for remnants of the user in the system

```shell
getent passwd docker-agent
id docker-agent
sudo find / -xdev -user docker-agent -print 2>/dev/null
```

## If Docker is no longer installed at all

> **IMPORTANT NOTE:**  
> The `docker` group must of course not be deleted if it is still in use.

```shell
getent group docker
# Only run the following command if `getent` outputs no other identifiers:
# sudo groupdel docker
```