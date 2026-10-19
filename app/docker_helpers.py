"""Docker helper utilities: stats collection, human-readable sizes."""
import time

import docker

from app.models import DockerServer, GitRepoConfig, ContainerActivity
from app import git_service


def _human_size(bytes_num: int) -> str:
    """Return human-readable size string from bytes (KB/MB/GB).

    Keep output short (e.g. "12.3 MB", "1.23 GB") used for image sizes.
    """
    try:
        b = float(bytes_num)
    except Exception:
        return "0 B"
    units = [(1024**3, 'GB'), (1024**2, 'MB'), (1024, 'KB')]
    for thresh, unit in units:
        if b >= thresh:
            return f"{b / thresh:.2f} {unit}"
    return f"{b:.0f} B"


def get_dashboard_stats():
    """Collect global dashboard stats and recent activity."""
    stats = {
        'servers_count': len(DockerServer.query.all()),
        'containers_count': 0,
        'running_count': 0,
        'images_count': 0,
        'total_images': 0,
        'total_images_size_gb': '0.00 GB',
        'networks_count': 0,
        'volumes_count': 0,
        'compose_stacks_count': 0,
        'git_compose_total': 0,
        'recent_activity': [],
    }

    try:
        git_config = GitRepoConfig.get_config()
        if git_config and git_service.is_repo_cloned(git_config.local_path):
            stats['git_compose_total'] = len(git_service.list_compose_files(git_config.local_path))
    except Exception:
        stats['git_compose_total'] = 0

    try:
        from app.ssh_tunnel import conf
        client, _ = conf()
        raw_containers = client.containers.list(all=True)
        stats['containers_count'] = len(raw_containers)
        stats['running_count'] = sum(1 for c in raw_containers if getattr(c, 'status', '') == 'running')
        stats['images_count'] = len({
            (c.attrs.get('Config', {}).get('Image', '') if getattr(c, 'attrs', None) else '')
            for c in raw_containers
        })

        images = client.images.list()
        stats['total_images'] = len(images)
        total_images_size_bytes = 0
        for img in images:
            try:
                total_images_size_bytes += img.attrs.get('Size', 0) if getattr(img, 'attrs', None) else 0
            except Exception:
                continue
        stats['total_images_size_gb'] = f"{(total_images_size_bytes / (1024 ** 3)):.2f} GB"

        stats['networks_count'] = len(client.networks.list())
        stats['volumes_count'] = len(client.volumes.list())

        compose_projects = set()
        for c in raw_containers:
            labels = getattr(c, 'labels', {}) or {}
            proj = labels.get('com.docker.compose.project')
            if proj:
                compose_projects.add(proj)
        stats['compose_stacks_count'] = len(compose_projects)

        # Fetch recent container activity from database
        recent_activity = []
        try:
            activities = ContainerActivity.get_recent(limit=10)
            for a in activities:
                recent_activity.append({
                    'name': a.container_name,
                    'action': a.action,
                    'image': a.image or '',
                    'timestamp': a.timestamp,
                })
        except Exception:
            pass

        stats['recent_activity'] = recent_activity

    except Exception:
        # keep default zero values if Docker is unavailable
        pass

    return stats
