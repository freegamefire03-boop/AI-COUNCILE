#!/usr/bin/env python3
"""
Planning Council v0 — Entry Point
"""

import argparse
import sys
import os
import json
import traceback
from orchestrator import Orchestrator

def main():
    parser = argparse.ArgumentParser(description="Planning Council Orchestrator v0")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--action", default="start", choices=["start", "resume", "retry"])
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set.")
        sys.exit(1)

    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gh_repo  = os.environ.get("GITHUB_REPO", "").strip()   # format: owner/repo
    gh_owner, gh_repo_name = (gh_repo.split("/") + [""])[:2] if gh_repo else ("", "")

    project_dir = os.path.join(args.data_dir, "projects", args.project_id)
    if not os.path.exists(project_dir):
        print(f"ERROR: Project directory not found: {project_dir}")
        sys.exit(1)

    print(f"[run] project={args.project_id} action={args.action} push_enabled={bool(gh_token and gh_owner)}")

    try:
        orch = Orchestrator(
            data_dir=args.data_dir,
            project_id=args.project_id,
            api_key=api_key,
            gh_token=gh_token,
            gh_owner=gh_owner,
            gh_repo=gh_repo_name,
        )
        orch.run(action=args.action)
        print("[run] Orchestrator finished successfully.")
    except Exception as e:
        print(f"[run] FATAL ERROR: {e}")
        traceback.print_exc()
        # Write error status locally then push
        status_path = os.path.join(project_dir, "status.json")
        try:
            with open(status_path, "r") as f:
                status = json.load(f)
        except Exception:
            status = {"project_id": args.project_id}
        status["status"] = "BLOCKED_ON_HARD_DEPENDENCY"
        status["ui_view"] = "BLOCKED_VIEW"
        status["error"] = {"type": "orchestrator_crash", "message": str(e), "retry_available": True}
        with open(status_path, "w") as f:
            json.dump(status, f, indent=2)

        if gh_token and gh_owner and gh_repo_name:
            try:
                from github_pusher import GitHubPusher
                pusher = GitHubPusher(gh_token, gh_owner, gh_repo_name)
                with open(status_path) as f:
                    pusher.push_file(f"projects/{args.project_id}/status.json", f.read())
            except Exception as pe:
                print(f"[run] Push error status failed: {pe}")
        sys.exit(1)

if __name__ == "__main__":
    main()
