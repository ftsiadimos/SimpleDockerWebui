# Gitea Actions Integration for LightDockerWebUI

This document provides an example Gitea Actions workflow that automatically deploys
docker-compose projects whenever changes are pushed to the repository.

## Overview

The workflow:
1. Triggers on push to the `main` branch
2. SSHes into your Docker host
3. Pulls the latest compose files
4. Runs `docker compose up -d` to deploy

## When to Use Actions

Use this Actions workflow when you want a separate CI/CD step to deploy compose files after they are pushed to the repo. This is especially useful when:

- LightDockerWebUI is not running on the target Docker host
- you need deployment to happen from a dedicated runner or remote host
- you want a GitOps pipeline that deploys after every push

If you are using LightDockerWebUI's Git Compose editor with `Auto commit & push on save` enabled, the app already pushes changes to the repo automatically when you save. In that case, Actions are only needed if you also want automatic deployment on the remote host.

## When Not to Use Actions

You may not need Actions if the repo and target Docker host are the same environment where LightDockerWebUI is running and you are managing deployments directly from the app. In that setup:

- `Save & Push` or auto-push already commits changes to the repository
- you can deploy directly from LightDockerWebUI without a separate actions runner
- Actions become optional unless you want an external deployment step

If you disable auto-push, use `Save & Push` manually. Actions can still be useful, but you should be aware that the workflow only triggers on git push, so manual pushes or auto-push are required to invoke it.

## Prerequisites

- A Gitea instance with Actions enabled
- An Actions runner registered to your repository
- SSH access from the runner to your Docker host
- Repository secrets configured (see below)

## Repository Secrets

Configure these secrets in your Gitea repo under **Settings > Actions > Secrets**:

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Docker host IP/FQDN |
| `DEPLOY_USER` | SSH username |
| `DEPLOY_KEY` | SSH private key |
| `DEPLOY_PATH` | Path to compose files on the host (e.g., `/opt/compose-files`) |

## Example Workflow

Create `.gitea/workflows/deploy.yml` in your compose repository:

```yaml
name: Deploy Compose Projects
on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_KEY }}
          script: |
            cd ${{ secrets.DEPLOY_PATH }}
            git pull --ff-only

            # Find and deploy all compose projects
            find . -name 'docker-compose.yml' -o -name 'compose.yml' | while read f; do
              dir=$(dirname "$f")
              echo "Deploying $dir ..."
              cd "${{ secrets.DEPLOY_PATH }}/$dir"
              docker compose pull
              docker compose up -d
              cd "${{ secrets.DEPLOY_PATH }}"
            done

            echo "Deployment complete."
```

## Per-Project Workflow

If you only want to deploy specific projects when their files change:

```yaml
name: Deploy Changed Projects
on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Detect changed projects
        id: changes
        run: |
          CHANGED=$(git diff --name-only HEAD~1 HEAD | grep -E '(docker-)?compose\.ya?ml' | xargs -I{} dirname {} | sort -u | tr '\n' ' ')
          echo "dirs=$CHANGED" >> "$GITHUB_OUTPUT"

      - name: Deploy changed projects
        if: steps.changes.outputs.dirs != ''
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_KEY }}
          script: |
            cd ${{ secrets.DEPLOY_PATH }}
            git pull --ff-only
            for dir in ${{ steps.changes.outputs.dirs }}; do
              echo "Deploying $dir ..."
              cd "${{ secrets.DEPLOY_PATH }}/$dir"
              docker compose pull
              docker compose up -d
              cd "${{ secrets.DEPLOY_PATH }}"
            done
```

## How It Works With LightDockerWebUI

1. **Configure** your Gitea repo URL and token in LightDockerWebUI **Settings**
2. **Edit** compose files in the Git Compose editor
3. **Save & Push** commits changes to Gitea
4. Gitea Actions workflow **triggers automatically** on push
5. The workflow **SSHes** to your Docker host and **deploys** the updated compose files
6. Containers are visible in LightDockerWebUI's **Dashboard** and **Containers** pages

This gives you a full GitOps loop: edit in the UI → push to git → auto-deploy via CI/CD.