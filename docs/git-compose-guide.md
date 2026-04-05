# Git Compose — Deploy Guide

This guide explains how the built-in **Git Compose** feature works and how to use it to deploy docker-compose projects to your Docker servers — no CI/CD pipeline or Gitea Actions required.

## How It Works

LightDockerWebUI acts as the deployment agent. The entire workflow runs from the web UI:

1. **Pull** — The app clones or pulls your git repository to a local directory on the WebUI host
2. **Deploy** — When you click "Deploy", the app runs `docker compose up -d` as a local subprocess, targeting the selected Docker server via the `DOCKER_HOST` environment variable
3. **Stop** — Same approach: runs `docker compose stop` against the target server

```
Git Repo (Gitea/GitHub) --pull--> Local clone on WebUI host --docker compose up--> Docker Server (via DOCKER_HOST=tcp://...)
```

There is **no SSH deploy** and **no CI/CD pipeline** involved. The WebUI machine talks directly to the Docker daemon API over TCP.

## Prerequisites

- The WebUI host needs **network access** to your git repository (to pull)
- The WebUI host needs **network access** to the Docker API on each target server (typically port 2376)
- The `docker` CLI must be **installed** on the WebUI host
- Docker servers must have their API **exposed via TCP** (configured in Add Server page)

## Setup

### 1. Configure the Git Repository

Go to **Settings** and fill in the Git Repository section:

- **Repository URL** — Your HTTPS git repo URL (e.g. `https://gitea.example.com/user/compose-files.git`)
- **Personal Access Token** — A token with read/write access to the repo
- **Branch** — The branch to track (default: `main`)
- **Auto Push** — When enabled, edits made in the UI are automatically committed and pushed back to the repo

### 2. Add Docker Servers

Go to **Add Server** and configure one or more Docker servers:

- **Server Name** — A friendly display name
- **Docker Host** — The FQDN or IP address of the server
- **Docker Port** — The Docker API port (e.g. `2376`)
- **SSH User / Password** — Optional, used for remote terminal access

### 3. Assign Servers to Projects

On the **Git Compose** page, each project row has a **Target Server** dropdown. Use it to assign a specific Docker server per compose project:

- **Active Server (default)** — Uses whichever server is currently selected globally
- **Specific server** — Always deploys to the chosen server, regardless of which server is globally active

The assignment is saved automatically when you change the dropdown.

## Deploying a Project

1. Go to **Git Compose**
2. Click **Pull Latest** to fetch the newest compose files from the repository
3. Find your project in the table
4. (Optional) Change the **Target Server** dropdown to assign or override the target
5. Click **Deploy** — the compose project is started on the resolved server

The server is resolved in this order:

1. The project's assigned server (from the Target Server dropdown)
2. Falls back to the globally active server if no assignment is set

## Stopping a Project

Click **Stop** on a running project. It targets the same server as deploy (assigned server or active server).

## Creating a New Project

1. Click **New Project** on the Git Compose page
2. Enter a project name (letters, numbers, hyphens, underscores)
3. A folder with a template `docker-compose.yml` is created in the repo
4. If Auto Push is enabled, the new file is committed and pushed to git automatically

## Editing Compose Files

Click **Edit** on any project to open the built-in editor. Changes are saved to the local clone and (if Auto Push is enabled) pushed to git.

## Deleting a Project

Click **Delete** to remove the compose file from the git repository. This does **not** stop running containers — stop the project first if needed.

## Do I Need Gitea Actions?

**No.** The Git Compose feature handles the entire deploy workflow from the web UI. Gitea Actions are only useful if you want **automatic deployment on git push** — i.e., push a change to the repo and have it deploy without clicking "Deploy" in the UI. See the [Gitea Actions Integration](gitea-actions) doc for that approach.

For manual, push-button deploys from the web UI, Gitea Actions are not needed.
