"""
Artifact Store — file-based persistence.
Reads/writes project files in the data directory (planner-data branch).
"""

import os
import json
from datetime import datetime, timezone


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ArtifactStore:
    def __init__(self, data_dir: str, project_id: str):
        self.project_dir = os.path.join(data_dir, "projects", project_id)
        self.artifacts_dir = os.path.join(self.project_dir, "artifacts")
        self.project_id = project_id
        os.makedirs(self.artifacts_dir, exist_ok=True)

    # ── Status / State ──────────────────────────────────────────────────────

    def read_input(self) -> dict:
        path = os.path.join(self.project_dir, "input.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def read_state(self) -> dict:
        path = os.path.join(self.project_dir, "state.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_state(self, state: dict):
        state["updated_at"] = _utcnow()
        path = os.path.join(self.project_dir, "state.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def read_status(self) -> dict:
        path = os.path.join(self.project_dir, "status.json")
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_status(self, status: str, ui_view: str, stage: str,
                     completed_steps: list = None, next_step: str = None,
                     error: dict = None, artifacts: list = None):
        data = {
            "project_id": self.project_id,
            "status": status,
            "ui_view": ui_view,
            "stage": stage,
            "updated_at": _utcnow(),
            "progress": {
                "completed_steps": completed_steps or [],
                "next_step": next_step,
            },
            "error": error,
            "artifacts": artifacts or self._list_artifacts(),
        }
        path = os.path.join(self.project_dir, "status.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return data

    def _list_artifacts(self) -> list:
        if not os.path.exists(self.artifacts_dir):
            return []
        return [f for f in os.listdir(self.artifacts_dir)
                if not f.startswith(".")]

    # ── Events ──────────────────────────────────────────────────────────────

    def append_event(self, event_type: str, message: str):
        path = os.path.join(self.project_dir, "events.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"events": []}

        data["events"].append({
            "at": _utcnow(),
            "type": event_type,
            "message": message,
        })

        # Keep last 200 events
        if len(data["events"]) > 200:
            data["events"] = data["events"][-200:]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ── Artifacts ───────────────────────────────────────────────────────────

    def write_artifact(self, name: str, content: str):
        path = os.path.join(self.artifacts_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def read_artifact(self, name: str) -> str:
        path = os.path.join(self.artifacts_dir, name)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def artifact_exists(self, name: str) -> bool:
        return os.path.exists(os.path.join(self.artifacts_dir, name))

    def write_artifact_json(self, name: str, data: dict):
        self.write_artifact(name, json.dumps(data, indent=2))

    def read_artifact_json(self, name: str) -> dict:
        content = self.read_artifact(name)
        if not content:
            return {}
        return json.loads(content)
