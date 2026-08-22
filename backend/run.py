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
    parser.add_argument("--data-dir", required=True, help="Path to data directory (planner-data branch)")
    parser.add_argument("--project-id", required=True, help="Project ID")
    parser.add_argument("--action", default="start", choices=["start", "resume", "retry"])
    args = parser.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY environment variable is not set.")
        sys.exit(1)

    project_dir = os.path.join(args.data_dir, "projects", args.project_id)
    if not os.path.exists(project_dir):
        print(f"ERROR: Project directory not found: {project_dir}")
        sys.exit(1)

    print(f"[run] Starting orchestrator | project={args.project_id} action={args.action}")

    try:
        orch = Orchestrator(
            data_dir=args.data_dir,
            project_id=args.project_id,
            api_key=api_key,
        )
        orch.run(action=args.action)
        print("[run] Orchestrator finished successfully.")
    except Exception as e:
        print(f"[run] FATAL ERROR: {e}")
        traceback.print_exc()
        # Write error to status
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
        sys.exit(1)

if __name__ == "__main__":
    main()
