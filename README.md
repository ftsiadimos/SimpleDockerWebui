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
</table>

---

## Screenshot

<p align="center">
  <img src="mis/image1.png" alt="Dashboard" width="90%" />
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

> ⚠️ **Offline Use**: all CSS/JS libraries are bundled under `app/static/vendor` so the UI works without internet access. When updating third‑party assets, place new files in that folder and adjust templates accordingly.

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

## 🏗️ Project Structure

```
lightdockerwebui/
├── app/
│   ├── __init__.py          # Flask application factory
│   ├── main.py              # Routes, WebSocket handlers
│   ├── models.py            # SQLAlchemy models (DockerServer)
│   ├── forms.py             # WTForms (AddServer, SelectServer)
│   ├── static/              # CSS, JavaScript, images
│   └── templates/           # Jinja2 HTML templates
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