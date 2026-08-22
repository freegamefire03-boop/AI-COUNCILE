# Planning Council v0

Testing version of a CEO-controlled sequential AI planning council.

**Live UI:** https://freegamefire03-boop.github.io/planning-council-v0/site/

## Architecture

```
Browser (GitHub Pages)
  → writes input to planner-data branch via GitHub API
  → triggers GitHub Actions workflow
  → polls status.json every 6s

GitHub Actions
  → runs Python orchestrator
  → calls OpenRouter free models (sequential)
  → writes artifacts to planner-data branch
```

## Council Execution Order

1. CEO Intake
2. Planning Brief
3. Product / Intent Analyst
4. Constraint / Dependency Analyst
5. Solution Architect
6. Execution Planner
7. QA / Red Team
8. CEO Synthesis → `plan.md`

## Setup

1. Add `OPENROUTER_API_KEY` to repo secrets (Settings → Secrets → Actions)
2. Enable GitHub Pages from `main` branch, `/site` folder
3. Open the site and enter your OpenRouter key + planning goal

## v0 Limitations

- No file upload
- No question loop (CEO proceeds directly to planning)
- No authentication (GitHub token hardcoded for testing)
- No persistent history
