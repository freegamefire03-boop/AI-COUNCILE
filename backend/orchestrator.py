"""
Orchestrator — Planning Council v0

Sequential execution:
  CEO Intake → Brief → 5 Specialists → CEO Synthesis → plan.md

Commits to GitHub after every step via API (no git required).
"""

import json
import os
from artifact_store import ArtifactStore
from llm_gateway import call_llm, call_llm_json, fetch_free_models

STEPS = [
    "FILES_PARSED",
    "CEO_INTAKE_COMPLETE",
    "BRIEF_COMPLETE",
    "MEMBER_1_PRODUCT_COMPLETE",
    "MEMBER_2_CONSTRAINTS_COMPLETE",
    "MEMBER_3_ARCHITECT_COMPLETE",
    "MEMBER_4_EXECUTION_COMPLETE",
    "MEMBER_5_REDTEAM_COMPLETE",
    "SYNTHESIS_COMPLETE",
    "PLAN_FINALIZED",
]

SPECIALIST_MAP = {
    "MEMBER_1_PRODUCT_COMPLETE":    {"role": "product_analyst",   "artifact": "product.json",      "stage": "MEMBER_1_PRODUCT",    "prompt_key": "member_product"},
    "MEMBER_2_CONSTRAINTS_COMPLETE":{"role": "constraint_analyst","artifact": "constraints.json",  "stage": "MEMBER_2_CONSTRAINTS","prompt_key": "member_constraints"},
    "MEMBER_3_ARCHITECT_COMPLETE":  {"role": "solution_architect","artifact": "architecture.json", "stage": "MEMBER_3_ARCHITECT",  "prompt_key": "member_architect"},
    "MEMBER_4_EXECUTION_COMPLETE":  {"role": "execution_planner", "artifact": "execution.json",    "stage": "MEMBER_4_EXECUTION",  "prompt_key": "member_planner"},
    "MEMBER_5_REDTEAM_COMPLETE":    {"role": "red_team",          "artifact": "redteam.json",      "stage": "MEMBER_5_REDTEAM",    "prompt_key": "member_redteam"},
}

SPECIALIST_STEP_ORDER = [
    "MEMBER_1_PRODUCT_COMPLETE",
    "MEMBER_2_CONSTRAINTS_COMPLETE",
    "MEMBER_3_ARCHITECT_COMPLETE",
    "MEMBER_4_EXECUTION_COMPLETE",
    "MEMBER_5_REDTEAM_COMPLETE",
]

WORD_LIMITS = {
    "product_analyst": 400,
    "constraint_analyst": 400,
    "solution_architect": 400,
    "execution_planner": 400,
    "red_team": 300,
    "brief": 800,
}


def _load_prompt(name: str) -> str:
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(backend_dir)
    path = os.path.join(repo_root, "prompts", f"{name}.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n[TRUNCATED]"


class Orchestrator:
    def __init__(self, data_dir: str, project_id: str, api_key: str,
                 gh_token: str = "", gh_owner: str = "", gh_repo: str = ""):
        self.api_key = api_key
        self.project_id = project_id
        self.store = ArtifactStore(data_dir, project_id)
        self.free_models = None
        self.pusher = None

        if gh_token and gh_owner and gh_repo:
            try:
                from github_pusher import GitHubPusher
                self.pusher = GitHubPusher(gh_token, gh_owner, gh_repo)
                print(f"[orch] GitHub pusher enabled → {gh_owner}/{gh_repo}")
            except Exception as e:
                print(f"[orch] Pusher init failed: {e}")

    def _push_project(self):
        """Push entire project directory to GitHub after each step."""
        if not self.pusher:
            return
        project_dir = self.store.project_dir
        try:
            self.pusher.push_project_dir(project_dir, self.project_id)
        except Exception as e:
            print(f"[orch] Push failed (non-fatal): {e}")

    def _models(self) -> list:
        if self.free_models is None:
            self.free_models = fetch_free_models(self.api_key)
        return self.free_models

    def run(self, action: str = "start"):
        state = self.store.read_state()
        completed = set(state.get("completed_steps", []))
        print(f"[orch] action={action} completed={len(completed)}")

        if action == "start" and completed:
            action = "resume"

        if "FILES_PARSED" not in completed:
            self._step_files_parsed(state, completed)

        if "CEO_INTAKE_COMPLETE" not in completed:
            self._step_ceo_intake(state, completed)

        if "BRIEF_COMPLETE" not in completed:
            self._step_brief(state, completed)

        for step_key in SPECIALIST_STEP_ORDER:
            if step_key not in completed:
                spec = SPECIALIST_MAP[step_key]
                self._step_specialist(state, completed,
                    role=spec["role"], artifact_name=spec["artifact"],
                    stage=spec["stage"], step_key=step_key, prompt_key=spec["prompt_key"])

        if "SYNTHESIS_COMPLETE" not in completed:
            self._step_synthesis(state, completed)

        if "PLAN_FINALIZED" not in completed:
            self._step_finalize(state, completed)

        print("[orch] All steps complete.")

    # ── Steps ────────────────────────────────────────────────────────────────

    def _step_files_parsed(self, state, completed):
        self.store.append_event("stage_changed", "Parsing input...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")
        digest = f"# Input Digest\n\n**User prompt:** {prompt}\n\n*No files in v0.*\n"
        self.store.write_artifact("file_digest.md", digest)
        self._checkpoint(state, completed, "FILES_PARSED", "FILES_PARSED", "CEO_INTAKE")
        print("[orch] FILES_PARSED done.")

    def _step_ceo_intake(self, state, completed):
        self.store.append_event("stage_changed", "CEO intake...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")
        system = _load_prompt("ceo_intake") or (
            "You are the CEO of a planning council. The user has submitted a planning goal. "
            "Acknowledge it in 2-3 sentences and confirm you are proceeding to generate a planning brief. "
            "Do NOT ask questions."
        )
        messages = [{"role": "user", "content": f"User goal:\n{prompt}"}]
        response = call_llm(self.api_key, messages, system=system, max_tokens=400, free_models=self._models())
        self.store.write_artifact("ceo_intake.md", f"# CEO Intake\n\n{response}\n")
        self.store.append_event("llm_call", "CEO intake complete.")
        self._checkpoint(state, completed, "CEO_INTAKE_COMPLETE", "CEO_INTAKE_COMPLETE", "BRIEF")
        print("[orch] CEO_INTAKE_COMPLETE done.")

    def _step_brief(self, state, completed):
        self.store.append_event("stage_changed", "Generating planning brief...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")
        system = _load_prompt("ceo_brief") or (
            "You are the CEO and lead planner. Produce a structured planning brief. "
            "Include: Problem Statement, Desired Outcome, Constraints, Assumptions, "
            "Success Criteria, Scope (In/Out). Max 800 words. Be specific."
        )
        messages = [{"role": "user", "content": f"User goal:\n{prompt}"}]
        brief = call_llm(self.api_key, messages, system=system, max_tokens=1200, free_models=self._models())
        brief = _truncate_words(brief, WORD_LIMITS["brief"])
        self.store.write_artifact("brief.md", f"# Planning Brief\n\n{brief}\n")
        self.store.append_event("llm_call", "Planning brief generated.")
        self._checkpoint(state, completed, "BRIEF_COMPLETE", "BRIEF_COMPLETE", "MEMBER_1_PRODUCT")
        print("[orch] BRIEF_COMPLETE done.")

    def _step_specialist(self, state, completed, role, artifact_name, stage, step_key, prompt_key):
        self.store.append_event("stage_changed", f"Running {role}...")
        brief = self.store.read_artifact("brief.md")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")
        max_words = WORD_LIMITS.get(role, 400)
        system = _load_prompt(prompt_key) or self._default_specialist_prompt(role, max_words)
        user_content = (
            f"User goal:\n{prompt}\n\n"
            f"Planning Brief:\n{brief}\n\n"
            f"Return ONLY valid JSON matching the schema in your instructions."
        )
        messages = [{"role": "user", "content": user_content}]
        result = call_llm_json(self.api_key, messages, system=system, max_tokens=1000, free_models=self._models())
        if "summary" in result:
            result["summary"] = _truncate_words(result["summary"], max_words)
        self.store.write_artifact_json(artifact_name, result)
        self.store.append_event("llm_call", f"{role} complete.")
        self._checkpoint(state, completed, step_key, stage + "_COMPLETE", self._next_stage(step_key))
        print(f"[orch] {step_key} done.")

    def _step_synthesis(self, state, completed):
        self.store.append_event("stage_changed", "CEO synthesis...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")
        brief        = self.store.read_artifact("brief.md")
        product      = self.store.read_artifact("product.json")
        constraints  = self.store.read_artifact("constraints.json")
        architecture = self.store.read_artifact("architecture.json")
        execution    = self.store.read_artifact("execution.json")
        redteam      = self.store.read_artifact("redteam.json")
        context = (
            f"USER GOAL:\n{prompt}\n\nPLANNING BRIEF:\n{brief}\n\n"
            f"PRODUCT ANALYST:\n{product}\n\nCONSTRAINT ANALYST:\n{constraints}\n\n"
            f"SOLUTION ARCHITECT:\n{architecture}\n\nEXECUTION PLANNER:\n{execution}\n\n"
            f"RED TEAM:\n{redteam}\n"
        )
        system = _load_prompt("ceo_synthesis") or (
            "You are the CEO. Synthesize all specialist inputs into ONE coherent, actionable final plan. "
            "Resolve conflicts, remove duplication, include risks. Structure with numbered sections."
        )
        messages = [{"role": "user", "content": context}]
        plan = call_llm(self.api_key, messages, system=system, max_tokens=2000, free_models=self._models())
        self.store.write_artifact("plan.md", f"# Final Plan\n\n{plan}\n")
        self.store.append_event("llm_call", "CEO synthesis complete.")
        self._checkpoint(state, completed, "SYNTHESIS_COMPLETE", "SYNTHESIS_COMPLETE", "PLAN_FINALIZED")
        print("[orch] SYNTHESIS_COMPLETE done.")

    def _step_finalize(self, state, completed):
        self.store.append_event("status_changed", "Plan finalized.")
        completed.add("PLAN_FINALIZED")
        self.store.write_status(
            status="COMPLETE", ui_view="PLAN_VIEWER", stage="PLAN_FINALIZED",
            completed_steps=list(completed), next_step=None,
        )
        state["stage"] = "PLAN_FINALIZED"
        state["completed_steps"] = list(completed)
        state["next_step"] = None
        self.store.write_state(state)
        # Final push — push everything
        self._push_project()
        print("[orch] PLAN_FINALIZED done.")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _checkpoint(self, state, completed, step_key, stage, next_step):
        completed.add(step_key)
        state["stage"] = stage
        state["completed_steps"] = list(completed)
        state["next_step"] = next_step
        state["project_id"] = self.project_id
        self.store.write_state(state)
        self.store.write_status(
            status="EXECUTING_COUNCIL", ui_view="PROGRESS_SPINNER",
            stage=stage, completed_steps=list(completed), next_step=next_step,
        )
        # Push after every step for live UI updates
        self._push_project()

    def _next_stage(self, step_key: str) -> str:
        idx = SPECIALIST_STEP_ORDER.index(step_key) if step_key in SPECIALIST_STEP_ORDER else -1
        if idx == -1 or idx + 1 >= len(SPECIALIST_STEP_ORDER):
            return "CEO_SYNTHESIS"
        return SPECIALIST_MAP[SPECIALIST_STEP_ORDER[idx + 1]]["stage"]

    def _default_specialist_prompt(self, role: str, max_words: int) -> str:
        return (
            f"You are the {role.replace('_', ' ').title()} in a planning council.\n"
            f"Analyze the planning brief from your specialist perspective.\n"
            f"Max {max_words} words in your summary.\n"
            f"Return ONLY valid JSON (no markdown) with this schema:\n"
            f'{{"role":"{role}","summary":"...","key_points":["..."],"assumptions":["..."],"recommendations":["..."]}}'
        )
