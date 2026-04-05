# 🐳 LightDockerWebUI

<p align="center">
  <img src="app/static/dockermanager.png" alt="LightDockerWebUI Logo" width="120" />
</p>

<p align="center">
  <strong>A lightweight, elegant web interface for Docker container management</strong>
</p>

<p align="center">
  <a href="https://hub.docker.com/r/ftsiadimos/lightdockerwebui"><img src="https://img.shields.io/docker/pulls/ftsiadimos/lightdockerwebui?style=flat-square&logo=docker" alt="Docker Pulls"></a>
  <a href="https://ghcr.io/ftsiadimos/simpledockerwebui"><img src="https://img.shields.io/badge/GHCR-available-blue?style=flat-square&logo=github" alt="GHCR Available"></a>
  <a href="https://github.com/ftsiadimos/lightdockerwebui/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://flask.palletsprojects.com/"><img src="https://img.shields.io/badge/Flask-3.x-000000.svg?style=flat-square&logo=flask" alt="Flask"></a>
  <a href="https://getbootstrap.com/"><img src="https://img.shields.io/badge/Bootstrap-5.3-7952B3.svg?style=flat-square&logo=bootstrap&logoColor=white" alt="Bootstrap"></a>
</p>

---

## 🎯 Overview

LightDockerWebUI is a **clean, fast, and simple** web-based Docker management tool designed for home servers, development environments, and small deployments. No complex setup — just run and manage your containers from any browser.



## ✨ Features

<table>
<tr>
<td width="50%">

### 📊 Dashboard
- Real-time container status
- Quick status indicators (running, stopped, paused)
- Port mappings with clickable links
- Container images and names at a glance

</td>
<td width="50%">

### 🎮 Container Control
- **Start** / **Stop** / **Restart** containers
- **Delete** containers with confirmation
- Bulk actions on selected containers
- Instant feedback with flash messages

</td>
</tr>
<tr>
<td width="50%">

### 📝 Live Logs
- Real-time log streaming
- Auto-scroll with manual override
- Timestamp display
- Search and filter logs

</td>
<td width="50%">

### 💻 Web Terminal
- Interactive shell access:
  - Full server SSH terminal (via **Terminal** under Configuration)
  - Interactive container shell (full PTY via `xterm.js`) accessible from **Containers → Terminal**


</td>
</tr>
<tr>
<td width="50%">

### 🌐 Multi-Server Support
- Connect to multiple Docker hosts
- Easy server switching via dropdown
- Local socket or remote TCP
- Persistent server configuration

</td>
<td width="50%">

### 📱 Responsive Design
- Mobile-friendly interface
- Tablet optimized
- Touch-friendly controls
- Works on any screen size

</td>
</tr>
<tr>
<td width="50%">

### 🔀 GitOps for Compose
- Clone a git repo with docker-compose files
- Browse, create, edit, and delete compose projects
- Save & push changes back to Gitea/GitHub
- Deploy or stop projects directly from the UI
- Auto-push on save (optional)
- Gitea Actions CI/CD integration

</td>
<td width="50%">

### 🧹 Resource Management
- **Images**: Browse all images, prune dangling
- **Volumes**: List and prune unused volumes
- **Networks**: View attached containers, prune empty
- Reclaimed space reporting after prune

</td>
</tr>
</table>

---

## Screenshot

<p align="center">
  <img src="mis/image.webp" alt="Dashboard" width="90%" />
</p>
<p align="center"><em>Dashboard — View and manage all containers</em></p>

---

## 📦 Installation Options

<details>
<summary><b>🐳 Docker (Recommended)</b></summary>

```bash
# Pull and run using Docker Hub
docker pull ftsiadimos/lightdockerwebui:latest

docker run -d --restart unless-stopped \
-p 8008:8008 \
--name=DockerManager \
-v $(pwd)/instance:/app/instance \
ftsiadimos/lightdockerwebui:latest

# or pull from GitHub Container Registry
# (repository is named "simpledockerwebui" there)
docker pull ghcr.io/ftsiadimos/simpledockerwebui:latest

docker run -d --restart unless-stopped \
-p 8008:8008 \
--name=DockerManager \
-v $(pwd)/instance:/app/instance \
ghcr.io/ftsiadimos/simpledockerwebui:latest
```

</details>


<details>
<summary><b>📄 Docker Compose</b></summary>

```yaml
# docker-compose.yml
version: '3.8'

services:
  DockerManager:
    image: ftsiadimos/lightdockerwebui:latest  # or ghcr.io/ftsiadimos/simpledockerwebui:latest
    container_name: DockerManager
    ports:
      - "8008:8008"
    volumes:
      - ./instance:/app/instance
    restart: unless-stopped
```

```bash
docker-compose up -d
```

</details>

<details>
<summary><b>🦾 ARM64 Support</b></summary>

```bash
# Build for both amd64 and arm64 (requires docker buildx + QEMU enabled)
docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/ftsiadimos/simpledockerwebui:latest --push .

# Run the arm64 image on arm64 host (or with qemu emulation on amd64)
docker run --platform linux/arm64 -d --restart unless-stopped -p 8008:8008 -v $(pwd)/instance:/app/instance ghcr.io/ftsiadimos/simpledockerwebui:latest
```

</details>

<details>
<summary><b>🐍 From Source (Development)</b></summary>

```bash
# Clone repository
git clone https://github.com/ftsiadimos/lightdockerwebui.git
cd lightdockerwebui

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run application
flask run --host=0.0.0.0 --port=8008
```

</details>

---

## ⚙️ Configuration

### Connecting to Docker Hosts

LightDockerWebUI supports **multiple Docker servers**. Configure them through the web UI:

1. Click **Config** in the navigation bar
2. Add servers with a display name and connection details:
   - **Local**: Leave host empty to use `/var/run/docker.sock`
   - **Remote**: Enter IP/hostname and port (default: 2375 or 2376)
3. Select the active server from the dropdown

### Server Terminal (SSH)

- A full interactive **server terminal** is available via the **Terminal** menu (under Configuration)
- Container terminals are full PTY shells (using `xterm.js`) available from the **Containers** page; the legacy limited command terminal has been removed

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| \`FLASK_DEBUG\` | \`0\` | Enable debug mode (development only) |
| \`SECRET_KEY\` | (random) | Flask secret key for sessions |
| \`SQLALCHEMY_DATABASE_URI\` | \`sqlite:///serverinfo.db\` | Database connection string |
## 🛰️ API: `/api/stats`

LightDockerWebUI now exposes a lightweight JSON API for dashboard metrics.

- `GET /api/stats` returns a JSON object with:
  - `servers_count`
  - `containers_count`
  - `running_count`
  - `images_count`
  - `total_images`
  - `total_images_size_gb`
  - `networks_count`
  - `volumes_count`
  - `compose_stacks_count`
  - `recent_activity`

### Example usage

```bash
# get full metric object
curl -s http://localhost:8008/api/stats | jq .

# get total images
curl -s http://localhost:8008/api/stats | jq '.total_images'

# get total image size in GB
curl -s http://localhost:8008/api/stats | jq -r '.total_images_size_gb'

# single summary line
curl -s http://localhost:8008/api/stats | jq -r '"images=\(.total_images) size=\(.total_images_size_gb)"'
```

### Note for custom host/port

If the app is not on localhost:8008, change to your host, e.g.:

```bash
curl -s http://docker.myserver:5000/api/stats | jq .
```

### (Optional) Unix socket Access using netcat + HTTP over socket

```bash
printf 'GET /api/stats HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' | socat - UNIX-CONNECT:/var/run/docker.sock | jq .
```
### Exposing Remote Docker Daemon

To manage containers on a remote host, enable TCP on the Docker daemon:

```bash
# Create systemd override
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/override.conf << EOF
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2375
EOF

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart docker
```

> ⚠️ **Security Warning**: Use TLS (port 2376) for production. Unencrypted connections should only be used on trusted networks.

---

## 🔀 GitOps for Compose

LightDockerWebUI can manage docker-compose projects from a **git repository** (Gitea, GitHub, etc.), giving you a full GitOps workflow:

### Setup

1. Go to **Settings** → **Git Repository (GitOps)**
2. Enter your repository HTTPS URL and a Personal Access Token
3. Choose the branch (default: `main`) and enable **Auto-push** if desired
4. Click **Save & Clone** — the repo is cloned locally

### Usage

- **Browse** — Navigate to **Git Compose** in the sidebar to see all compose projects
- **Create** — Click "New Project" to scaffold a new project folder with a template `docker-compose.yml`
- **Edit** — Open any compose file in the built-in editor with YAML validation
- **Deploy / Stop** — Deploy or stop projects directly to the connected Docker host
- **Delete** — Remove compose projects from the repo
- **Save & Push** — Changes are committed and pushed to your git remote (automatically if auto-push is on)

### Gitea Actions Integration

For automatic deployment on push, see the [Gitea Actions example](docs/gitea-actions-example.md) which provides ready-to-use CI/CD workflows.

### Architecture Notes

- Compose files are stored in `instance/gitops-repo/` (persisted via the Docker volume mount `./instance:/app/instance`)
- The app uses the Docker CLI with `DOCKER_HOST` to deploy to remote Docker daemons
- Git operations use the `git` CLI (installed in the Docker image) with PAT authentication

---

## 🏗️ Project Structure

```
lightdockerwebui/
├── app/
│   ├── __init__.py          # Flask application factory
│   ├── main.py              # Routes, WebSocket handlers
│   ├── models.py            # SQLAlchemy models (DockerServer, GitRepoConfig)
│   ├── forms.py             # WTForms (AddServer, SelectServer, GitRepo)
│   ├── git_service.py       # Git operations (clone, pull, commit, push)
│   ├── static/              # CSS, JavaScript, images
│   └── templates/           # Jinja2 HTML templates
├── docs/                    # Documentation (rendered in-app)
├── config.py                # Flask configuration classes
├── start.py                 # Application entry point
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container build file
└── docker-compose.yml       # Compose configuration
```

---

## 🛠️ Development

```bash
# Clone and setup
git clone https://github.com/ftsiadimos/lightdockerwebui.git
cd lightdockerwebui
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run with hot reload
export FLASK_DEBUG=1
flask run --host=0.0.0.0 --port=8008
```

### Production deployment tips ⚙️

For production use we recommend running Gunicorn with the threaded worker class and a higher timeout to avoid workers being killed during occasional slow operations. Example command:

```bash
# Example Gunicorn command (used in Dockerfile / docker-compose)
/usr/local/bin/gunicorn -b :8008 -k gthread --workers 3 --threads 4 --timeout 120 start:app
```

Also ensure the Docker Python SDK is available in the environment where the app runs (needed to talk to Docker):

```bash
pip install docker
```

### Tech Stack

- **Backend**: Flask 3.x, Flask-SQLAlchemy, Flask-Sock
- **Frontend**: Bootstrap 5.3, DataTables, jQuery
- **Database**: SQLite (persistent server configuration)
- **Container**: Docker SDK for Python

---

## 🤝 Contributing

Contributions are welcome! Here's how:

1. **Fork** the repository
2. **Create** a feature branch: \`git checkout -b feature/awesome-feature\`
3. **Commit** changes: \`git commit -m 'Add awesome feature'\`
4. **Push** to branch: \`git push origin feature/awesome-feature\`
5. **Open** a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

---

## 💬 Support & Links

<p align="center">
  <a href="https://github.com/ftsiadimos/lightdockerwebui/issues">🐛 Report Bug</a> •
  <a href="https://github.com/ftsiadimos/lightdockerwebui/discussions">💡 Request Feature</a> •
  <a href="https://hub.docker.com/r/ftsiadimos/lightdockerwebui">🐳 Docker Hub</a>
</p>

<p align="center">
  ⭐ <strong>Star this repo if you find it useful!</strong> ⭐
</p>

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/ftsiadimos">Fotis Tsiadimos</a>
</p>