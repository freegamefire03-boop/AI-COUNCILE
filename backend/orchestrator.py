"""
Orchestrator — Planning Council v0

Sequential execution:
  CEO Intake → Brief → 5 Specialists → CEO Synthesis → plan.md

v0: No question loop. CEO proceeds directly to brief.
Checkpoint-aware: each completed step is saved so retries skip completed work.
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
    "MEMBER_1_PRODUCT_COMPLETE": {
        "role": "product_analyst",
        "artifact": "product.json",
        "stage": "MEMBER_1_PRODUCT",
        "prompt_key": "member_product",
    },
    "MEMBER_2_CONSTRAINTS_COMPLETE": {
        "role": "constraint_analyst",
        "artifact": "constraints.json",
        "stage": "MEMBER_2_CONSTRAINTS",
        "prompt_key": "member_constraints",
    },
    "MEMBER_3_ARCHITECT_COMPLETE": {
        "role": "solution_architect",
        "artifact": "architecture.json",
        "stage": "MEMBER_3_ARCHITECT",
        "prompt_key": "member_architect",
    },
    "MEMBER_4_EXECUTION_COMPLETE": {
        "role": "execution_planner",
        "artifact": "execution.json",
        "stage": "MEMBER_4_EXECUTION",
        "prompt_key": "member_planner",
    },
    "MEMBER_5_REDTEAM_COMPLETE": {
        "role": "red_team",
        "artifact": "redteam.json",
        "stage": "MEMBER_5_REDTEAM",
        "prompt_key": "member_redteam",
    },
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
    """Load prompt from prompts/ directory relative to backend/."""
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
    return " ".join(words[:max_words]) + "\n\n[OUTPUT TRUNCATED TO FIT LIMITS]"


class Orchestrator:
    def __init__(self, data_dir: str, project_id: str, api_key: str):
        self.api_key = api_key
        self.project_id = project_id
        self.store = ArtifactStore(data_dir, project_id)
        self.free_models = None

    def _models(self) -> list:
        if self.free_models is None:
            self.free_models = fetch_free_models(self.api_key)
        return self.free_models

    def run(self, action: str = "start"):
        state = self.store.read_state()
        completed = set(state.get("completed_steps", []))

        print(f"[orch] action={action} completed_steps={len(completed)}")

        if action == "start" and completed:
            print("[orch] State exists, treating as resume.")
            action = "resume"

        # ── Step 1: Parse files (no upload in v0, just read input prompt) ──
        if "FILES_PARSED" not in completed:
            self._step_files_parsed(state, completed)

        # ── Step 2: CEO Intake → direct to brief (no questions in v0) ───────
        if "CEO_INTAKE_COMPLETE" not in completed:
            self._step_ceo_intake(state, completed)

        # ── Step 3: Planning Brief ───────────────────────────────────────────
        if "BRIEF_COMPLETE" not in completed:
            self._step_brief(state, completed)

        # ── Steps 4-8: Specialists ───────────────────────────────────────────
        for step_key in SPECIALIST_STEP_ORDER:
            if step_key not in completed:
                spec = SPECIALIST_MAP[step_key]
                self._step_specialist(
                    state, completed,
                    role=spec["role"],
                    artifact_name=spec["artifact"],
                    stage=spec["stage"],
                    step_key=step_key,
                    prompt_key=spec["prompt_key"],
                )

        # ── Step 9: CEO Synthesis ────────────────────────────────────────────
        if "SYNTHESIS_COMPLETE" not in completed:
            self._step_synthesis(state, completed)

        # ── Step 10: Finalize ────────────────────────────────────────────────
        if "PLAN_FINALIZED" not in completed:
            self._step_finalize(state, completed)

        print("[orch] All steps complete.")

    # ── Step Implementations ────────────────────────────────────────────────

    def _step_files_parsed(self, state, completed):
        self.store.append_event("stage_changed", "Parsing input...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")

        digest = f"# Input Digest\n\n**User prompt:** {prompt}\n\n*No files uploaded in v0.*\n"
        self.store.write_artifact("file_digest.md", digest)

        self._checkpoint(state, completed, "FILES_PARSED", "FILES_PARSED",
                         "EXECUTING_COUNCIL", "CEO_INTAKE")
        print("[orch] FILES_PARSED done.")

    def _step_ceo_intake(self, state, completed):
        self.store.append_event("stage_changed", "CEO intake...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")

        system = _load_prompt("ceo_intake") or (
            "You are the CEO of a planning council. A user has submitted a planning goal. "
            "In v0 of this system, you proceed DIRECTLY to creating a planning brief — "
            "do NOT ask questions. Acknowledge the goal briefly and confirm you are proceeding to planning."
        )

        messages = [{"role": "user", "content": f"User goal:\n{prompt}"}]
        response = call_llm(self.api_key, messages, system=system,
                            max_tokens=400, free_models=self._models())

        self.store.write_artifact("ceo_intake.md", f"# CEO Intake\n\n{response}\n")
        self.store.append_event("llm_call", f"CEO intake complete.")
        self._checkpoint(state, completed, "CEO_INTAKE_COMPLETE", "CEO_INTAKE_COMPLETE",
                         "EXECUTING_COUNCIL", "BRIEF")
        print("[orch] CEO_INTAKE_COMPLETE done.")

    def _step_brief(self, state, completed):
        self.store.append_event("stage_changed", "Generating planning brief...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")

        system = _load_prompt("ceo_brief") or (
            "You are the CEO and lead planner. Based on the user goal, produce a concise "
            "planning brief with: Problem Statement, Desired Outcome, Known Constraints, "
            "Assumptions, Success Criteria, Scope (In/Out). Max 800 words. Be structured."
        )

        messages = [{"role": "user", "content": f"User goal:\n{prompt}"}]
        brief = call_llm(self.api_key, messages, system=system,
                         max_tokens=1200, free_models=self._models())
        brief = _truncate_words(brief, WORD_LIMITS["brief"])

        self.store.write_artifact("brief.md", f"# Planning Brief\n\n{brief}\n")
        self.store.append_event("llm_call", "Planning brief generated.")
        self._checkpoint(state, completed, "BRIEF_COMPLETE", "BRIEF_COMPLETE",
                         "EXECUTING_COUNCIL", "MEMBER_1_PRODUCT")
        print("[orch] BRIEF_COMPLETE done.")

    def _step_specialist(self, state, completed, role, artifact_name,
                         stage, step_key, prompt_key):
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

        result = call_llm_json(self.api_key, messages, system=system,
                               max_tokens=1000, free_models=self._models())

        # Validate and truncate summary if needed
        if "summary" in result:
            result["summary"] = _truncate_words(result["summary"], max_words)

        self.store.write_artifact_json(artifact_name, result)
        self.store.append_event("llm_call", f"{role} complete.")
        self._checkpoint(state, completed, step_key, stage + "_COMPLETE",
                         "EXECUTING_COUNCIL", self._next_stage(step_key))
        print(f"[orch] {step_key} done.")

    def _step_synthesis(self, state, completed):
        self.store.append_event("stage_changed", "CEO synthesis...")
        inp = self.store.read_input()
        prompt = inp.get("prompt", "")

        brief = self.store.read_artifact("brief.md")
        product = self.store.read_artifact("product.json")
        constraints = self.store.read_artifact("constraints.json")
        architecture = self.store.read_artifact("architecture.json")
        execution = self.store.read_artifact("execution.json")
        redteam = self.store.read_artifact("redteam.json")

        context = (
            f"USER GOAL:\n{prompt}\n\n"
            f"PLANNING BRIEF:\n{brief}\n\n"
            f"PRODUCT ANALYST:\n{product}\n\n"
            f"CONSTRAINT ANALYST:\n{constraints}\n\n"
            f"SOLUTION ARCHITECT:\n{architecture}\n\n"
            f"EXECUTION PLANNER:\n{execution}\n\n"
            f"RED TEAM REVIEW:\n{redteam}\n"
        )

        system = _load_prompt("ceo_synthesis") or (
            "You are the CEO. Synthesize the specialist inputs into ONE coherent, actionable final plan. "
            "Resolve conflicts, remove duplication, preserve assumptions, include risks. "
            "Structure the plan with clear numbered sections. Do NOT simply concatenate. "
            "Produce a final plan the user can act on immediately."
        )

        messages = [{"role": "user", "content": context}]
        plan = call_llm(self.api_key, messages, system=system,
                        max_tokens=2000, free_models=self._models())

        self.store.write_artifact("plan.md", f"# Final Plan\n\n{plan}\n")
        self.store.append_event("llm_call", "CEO synthesis complete.")
        self._checkpoint(state, completed, "SYNTHESIS_COMPLETE", "SYNTHESIS_COMPLETE",
                         "EXECUTING_COUNCIL", "PLAN_FINALIZED")
        print("[orch] SYNTHESIS_COMPLETE done.")

    def _step_finalize(self, state, completed):
        self.store.append_event("status_changed", "Plan finalized.")
        self.store.write_status(
            status="COMPLETE",
            ui_view="PLAN_VIEWER",
            stage="PLAN_FINALIZED",
            completed_steps=list(completed) + ["PLAN_FINALIZED"],
            next_step=None,
        )
        state["stage"] = "PLAN_FINALIZED"
        state["completed_steps"] = list(completed) + ["PLAN_FINALIZED"]
        state["next_step"] = None
        self.store.write_state(state)
        completed.add("PLAN_FINALIZED")
        print("[orch] PLAN_FINALIZED done.")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _checkpoint(self, state, completed, step_key, stage, pub_status_key, next_step):
        completed.add(step_key)
        state["stage"] = stage
        state["completed_steps"] = list(completed)
        state["next_step"] = next_step
        state["project_id"] = self.project_id
        self.store.write_state(state)
        self.store.write_status(
            status="EXECUTING_COUNCIL",
            ui_view="PROGRESS_SPINNER",
            stage=stage,
            completed_steps=list(completed),
            next_step=next_step,
        )

    def _next_stage(self, step_key: str) -> str:
        idx = SPECIALIST_STEP_ORDER.index(step_key) if step_key in SPECIALIST_STEP_ORDER else -1
        if idx == -1 or idx + 1 >= len(SPECIALIST_STEP_ORDER):
            return "CEO_SYNTHESIS"
        next_key = SPECIALIST_STEP_ORDER[idx + 1]
        return SPECIALIST_MAP[next_key]["stage"]

    def _default_specialist_prompt(self, role: str, max_words: int) -> str:
        return (
            f"You are the {role.replace('_', ' ').title()} in a planning council.\n"
            f"Analyze the provided planning brief from your specialist perspective.\n"
            f"Be concise and structured. Max {max_words} words in your summary.\n"
            f"Return ONLY valid JSON (no markdown fences) with this exact schema:\n"
            f'{{"role":"{role}","summary":"<1-2 paragraphs>","key_points":["..."],'
            f'"assumptions":["..."],"recommendations":["..."]}}'
        )
