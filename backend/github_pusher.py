"""
GitHub API Pusher — commits local project files to planner-data branch.
No git required. Used by orchestrator to push state after each step.
"""

import os
import base64
import json
import requests
import time


class GitHubPusher:
    def __init__(self, token: str, owner: str, repo: str, branch: str = "planner-data"):
        self.token = token
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self.base = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github.v3+json",
        }

    def _get_sha(self, path: str) -> str | None:
        r = requests.get(
            f"{self.base}/repos/{self.owner}/{self.repo}/contents/{path}",
            headers=self.headers,
            params={"ref": self.branch},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("sha")
        return None

    def push_file(self, repo_path: str, content: str, message: str = None) -> bool:
        if message is None:
            message = f"planner: update {repo_path}"
        encoded = base64.b64encode(content.encode("utf-8")).decode()
        sha = self._get_sha(repo_path)
        body = {"message": message, "content": encoded, "branch": self.branch}
        if sha:
            body["sha"] = sha
        r = requests.put(
            f"{self.base}/repos/{self.owner}/{self.repo}/contents/{repo_path}",
            headers=self.headers,
            json=body,
            timeout=20,
        )
        if r.status_code in (200, 201):
            return True
        print(f"[pusher] Failed to push {repo_path}: {r.status_code} {r.text[:200]}")
        return False

    def push_project_dir(self, local_project_dir: str, project_id: str):
        """Walk the local project directory and push all files to GitHub."""
        pushed = 0
        failed = 0
        for dirpath, _, filenames in os.walk(local_project_dir):
            for fname in filenames:
                local_path = os.path.join(dirpath, fname)
                # Compute repo path: projects/{id}/...
                rel = os.path.relpath(local_path, os.path.dirname(local_project_dir))
                repo_path = f"projects/{rel}".replace("\\", "/")
                try:
                    with open(local_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    ok = self.push_file(repo_path, content)
                    if ok:
                        pushed += 1
                    else:
                        failed += 1
                    time.sleep(0.3)
                except Exception as e:
                    print(f"[pusher] Error reading {local_path}: {e}")
                    failed += 1
        print(f"[pusher] Pushed {pushed} files, {failed} failures for project {project_id}")
