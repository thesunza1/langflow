# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

Langflow is a visual workflow builder for AI-powered agents. It has a Python/FastAPI backend, React/TypeScript frontend, and a lightweight executor CLI (lfx).

## Prerequisites

- **Python:** 3.10-3.14
- **uv:** >=0.4 (Python package manager)
- **Node.js:** >=20.19.0 (v22.12 LTS recommended)
- **npm:** v10.9+
- **make:** For build coordination

## Common Commands

### Development Setup
```bash
make init              # Install all dependencies + pre-commit hooks
make run_cli           # Build and run Langflow (http://localhost:7860)
make run_clic          # Clean build and run (use when frontend issues occur)
```

### Development Mode (Hot Reload)
```bash
make backend           # FastAPI on port 7860 (terminal 1)
make frontend          # Vite dev server on port 3000 (terminal 2)
```

For component development, enable dynamic loading:
```bash
LFX_DEV=1 make backend                    # Load all components dynamically
LFX_DEV=mistral,openai make backend       # Load only specific modules
```

### Code Quality
```bash
make format_backend    # Format Python (ruff) - run FIRST before lint
make format_frontend   # Format TypeScript (biome)
make format            # Both
make lint              # mypy type checking
```

### Testing
```bash
make unit_tests                    # Backend unit tests (pytest, parallel)
make unit_tests async=false        # Sequential tests
uv run pytest path/to/test.py      # Single test file
uv run pytest path/to/test.py::test_name  # Single test

make test_frontend                 # Jest unit tests
make tests_frontend                # Playwright e2e tests
```

### Database Migrations
```bash
make alembic-revision message="Description"  # Create migration
make alembic-upgrade                         # Apply migrations
make alembic-downgrade                       # Rollback one version
```

## Architecture

### Monorepo Structure
```
src/
├── backend/
│   ├── base/langflow/     # Core backend package (langflow-base)
│   │   ├── api/           # FastAPI routes (v1/, v2/)
│   │   ├── components/    # Built-in Langflow components
│   │   ├── services/      # Service layer (auth, database, cache, etc.)
│   │   ├── graph/         # Flow graph execution engine
│   │   └── custom/        # Custom component framework
│   └── tests/             # Backend tests
├── frontend/              # React/TypeScript UI
│   └── src/
│       ├── components/    # UI components
│       ├── stores/        # Zustand state management
│       └── icons/         # Component icons
└── lfx/                   # Lightweight executor CLI
```

### Key Packages
- **langflow**: Main package with all integrations
- **langflow-base**: Core framework (api, services, graph engine)
- **lfx**: Standalone CLI for running flows (`lfx serve`, `lfx run`)

### Service Layer
Backend services in `src/backend/base/langflow/services/`:
- `auth/` - Authentication
- `authorization/` - Authorization (RBAC) plugin layer — see below
- `database/` - SQLAlchemy models and migrations
- `cache/` - Caching layer
- `storage/` - File storage
- `tracing/` - Observability integrations

### Authorization (RBAC)

Authorization is a pluggable layer separate from authentication:

- **OSS** ships the interface (`BaseAuthorizationService` in `lfx`) + a pass-through implementation (`LangflowAuthorizationService`) + the `authz_*` and `casbin_rule` DB schema + route guards.
- Implementations register via the `lfx.services` entry point `authorization_service` in `lfx.toml` (same pattern as the SSO `auth_service`). A registered plugin reads the `authz_*` admin tables and writes compiled rules to `casbin_rule`.

Default is **off**: `LANGFLOW_AUTHZ_ENABLED=false`. When enabled with only the OSS stub registered, every check returns allow — the stub is a no-op so routes stay wired and audit rows still flow. Real allow/deny requires a registered authorization plugin.

Route guards live in `langflow.services.authorization.guards` (the legacy `langflow.services.authorization.utils` path re-exports them for backward compatibility):
- `ensure_flow_permission(user, FlowAction.*, flow_id=..., flow_user_id=..., workspace_id=..., folder_id=...)` — single-flow CRUD + execute
- `ensure_deployment_permission(user, DeploymentAction.*, deployment_id=..., deployment_user_id=..., workspace_id=..., project_id=...)`
- `ensure_project_permission(user, ProjectAction.*, project_id=..., project_user_id=..., workspace_id=...)`
- `ensure_knowledge_base_permission(user, KnowledgeBaseAction.*, kb_name=..., kb_user_id=...)`
- `ensure_variable_permission(user, VariableAction.*, variable_id=..., variable_user_id=...)`
- `ensure_file_permission(user, FileAction.*, file_id=..., file_user_id=...)`
- `ensure_share_permission(user, ShareAction.*, share_id=..., share_user_id=...)`
- `filter_visible_resources(user, resource_type=..., candidates=..., act=...)` — list-endpoint filter; safe no-op in OSS

The enforcement request shape is `(subject, domain, object, action)`:
- subject = `user:{uuid}`
- domain = `project:{uuid}` → `workspace:{uuid}` → `*` (resolved by `_resolve_flow_domain`; the more specific domain wins so project-scoped grants match directly while workspace-scoped grants still flow down via plugin-side role inheritance)
- object = `flow:{uuid}` / `deployment:{uuid}` / `project:{uuid}` / `flow:*` / etc.
- action = `read` / `write` / `create` / `delete` / `execute` / `deploy`

**Share-aware fetch (Phase 3):** route fetch helpers (`_read_flow`, `get_flow_by_id_or_endpoint_name`, `get_deployment`, project reads in `projects.py`, v2 file fetcher, variable PATCH/DELETE in `variable.py`) branch on `BaseAuthorizationService.supports_cross_user_fetch()`. The OSS pass-through reports `False` so the existing owner-scoped queries are preserved — enabling `LANGFLOW_AUTHZ_ENABLED=true` without a registered plugin cannot widen visibility. Plugins set `SUPPORTS_CROSS_USER_FETCH=True` so resources load by id alone and `ensure_*_permission` decides access; route handlers can convert a plugin-deny `HTTPException(403)` to `HTTPException(404)` via `langflow.services.authorization.fetch.deny_to_404` to preserve UUID privacy.

**Share CRUD API (Phase 3):** `/api/v1/authz/shares` provides POST / GET / PATCH / DELETE on `authz_share` rows. The handler enforces an OSS floor (resource owner or superuser may administer shares for that resource) so the OSS pass-through cannot let a non-owner mint share rows. Each write fires `BaseAuthorizationService.invalidate_user` / `invalidate_all` so a registered enforcer can drop cached policy. Audit rows are written via `audit_decision` with `share:create` / `share:update` / `share:delete` actions.

**Audit query API (Phase 4):** `GET /api/v1/authz/audit` (superuser-only) exposes a paginated, filterable view of `authz_audit_log`. Supports `user_id`, `resource_type`, `resource_id`, `action`, `result`, `since`, `until` filters; page size capped at 200.

**Default role catalog (Phase 4):** the consolidated foundations migration `7c8d9e0f1a2b_authz_foundations` seeds the three built-in `is_system=True` roles (viewer / developer / admin) with `"{resource}:{action}"` permission slugs. OSS does not interpret these — they exist so a registered plugin's policy sync has a stable bootstrap source.

## Component Development

Components live in `src/backend/base/langflow/components/`. To add a new component:

1. Create component class inheriting from `Component`
2. Define `display_name`, `description`, `icon`, `inputs`, `outputs`
3. Add to `__init__.py` (alphabetical order)
4. Run with `LFX_DEV=1 make backend` for hot reload

**IMPORTANT:** Changing a component's class name is a breaking change and should never be done. The class name serves as an identifier used to match components in saved flows and to flag them for updates in the UI. Renaming it will break existing flows that use that component.

### Component Structure
```python
from langflow.custom import Component
from langflow.io import MessageTextInput, Output

class MyComponent(Component):
    display_name = "My Component"
    description = "What it does"
    icon = "component-icon"  # Lucide icon name or custom

    inputs = [
        MessageTextInput(name="input_value", display_name="Input"),
    ]
    outputs = [
        Output(display_name="Output", name="output", method="process"),
    ]

    def process(self) -> Message:
        # Component logic
        return Message(text=self.input_value)
```

### Component Testing
Tests go in `src/backend/tests/unit/components/`. Use base classes:
- `ComponentTestBaseWithClient` - Components needing API access
- `ComponentTestBaseWithoutClient` - Pure logic components

Required fixtures: `component_class`, `default_kwargs`, `file_names_mapping`

## Frontend Development

- **React 19** + TypeScript + Vite
- **Zustand** for state management
- **@xyflow/react** for graph visualization
- **Tailwind CSS** for styling

### Custom Icons
1. Create SVG component in `src/frontend/src/icons/YourIcon/`
2. Export with `forwardRef` and `isDark` prop support
3. Add to `lazyIconImports.ts`
4. Set `icon = "YourIcon"` in Python component

## Testing Notes

- `@pytest.mark.api_key_required` - Tests requiring external API keys
- `@pytest.mark.no_blockbuster` - Skip blockbuster plugin
- Database tests may fail in batch but pass individually
- Pre-commit hooks require `uv run git commit`
- Always use `uv run` when running Python commands
- When running tests inside a sub-package (e.g. `langflow-base`, `lfx`), sync that package's dev group first: `uv sync --group dev --package langflow-base`. The default `uv sync` only resolves the top-level workspace and may leave dev-only test deps (e.g. `fakeredis`) uninstalled.

### Graph Testing Pattern

Proper Graph tests follow this pattern:
1. Build graph with connected components
2. Connect them via `.set()` calls
3. Call `async_start` and iterate over the results
4. Validate the results

### Testing Best Practices

- Avoid mocking in tests when possible
- Prefer real integrations for more reliable tests

## Version Management
```bash
make patch v=1.5.0  # Update version across all packages
```

This updates: `pyproject.toml`, `src/backend/base/pyproject.toml`, `src/frontend/package.json`

## Pre-commit Workflow

Pre-commit hooks run ruff and biome automatically on `git commit`, so manual
formatting is not required. To avoid an extra commit cycle when you have many
changes:

1. Run `make format_backend` once before staging - fixes most ruff issues up front.
2. Run `uv run git commit` (the `uv run` ensures pre-commit finds the right Python).
3. If you touched backend code, run `make unit_tests` locally for faster feedback than CI.

## Pull Request Guidelines

- Follow [semantic commit conventions](https://www.conventionalcommits.org/)
- Reference any issues fixed (e.g., `Fixes #1234`)
- Ensure all tests pass before submitting

## Documentation

Documentation uses Docusaurus and lives in `docs/`:
```bash
cd docs
yarn install
yarn start        # Dev server on port 3000 (prompts for 3001 if 3000 is in use)
```

## Q Procedures

Five sequential procedures for feature development: **qplan**, **qcode**, **qtest**, **qcommit**, **qstart**.
Run them in order. Each expects the previous step to be complete before starting.

Run **qstart** standalone anytime after code changes for a faster production-mode test.

Run **qstart_dev** anytime during active development for hot-reload mode (no rebuild needed).


### qplan — Requirement Planning

Translate user requests into a structured plan saved as HTML files under `qplan/`. Before drafting the plan, use **gitnexus** to analyze the existing codebase so the plan is grounded in the actual architecture:

1. **Codebase analysis** — Query gitnexus for relevant context:
   - Read `gitnexus://repo/langflow/context` for codebase stats and entry points.
   - Read `gitnexus://repo/langflow/clusters` to identify relevant modules (e.g. `auth`, `api`, `components`, `frontend`).
   - Deep-dive into specific clusters via `gitnexus://repo/langflow/cluster/{name}` to understand existing implementations, data models, and service boundaries.

2. **Analyze** — Read the user's request and break it down into clear functional requirements.
3. **Write SRS** — Create a Software Requirements Specification in HTML format covering:
   - Purpose and scope
   - Functional requirements (numbered, detailed)
   - Non-functional requirements (performance, security, UX)
   - User interaction flow
   - Component tree / page structure
4. **Create wireframe** — Embed an interactive or visual wireframe in the same HTML (CSS-drawn mockup or inline SVG schematic showing layout, major UI elements, and navigation flow).
5. **Save** — Write the file to `qplan/<feature-name>.html`. Create `qplan/` directory if it doesn't exist.
6. **Scope boundary** — Clearly mark what is in scope and what is out of scope. Do not modify, refactor, or touch any feature or functionality not directly related to the requirements defined in this plan.

7. **Confirm** — Present the plan to the user for approval before moving to qcode.

The HTML should be self-contained (no external dependencies) so it can be opened in any browser.



### qcode — Implementation

Implement the feature following the approved qplan.

1. **Read plan** — Load the SRS and wireframe from `qplan/<feature-name>.html`.
2. **Scope** — Identify which files need to be created or modified (backend, frontend, tests).
3. **Implement** — Write code following the existing project conventions:
   - Backend: FastAPI routes in `src/backend/base/langflow/api/`, services in `services/`, components in `components/`.
   - Frontend: React components in `src/frontend/src/components/`, stores in `stores/`, pages in `pages/`.
   - Follow the patterns described in Component Development and Frontend Development sections above.
4. **Integrate** — If the feature touches both backend and frontend, wire up API calls using the existing Axios + TanStack React Query pattern (see `frontend-query-mutation` skill).
5. **Verify build** — Run the relevant format/lint checks:
   ```bash
   make format_backend   # if backend changed
   make format_frontend  # if frontend changed
   ```
6. **Commit readiness** — Do not commit yet; that is qcommit's job.

### qtest — GUI Testing

Test the implemented feature through its user interface.

1. **Start the app** — Ensure Langflow is running (see Common Commands / Development Setup).
2. **Manual smoke test** — Walk through the feature's UI flow:
   - Navigate to the feature's page/component.
   - Execute the primary happy-path scenario.
   - Test at least one edge case or error state.
3. **Automated test** — If applicable, write or update tests:
   - **Playwright E2E tests** in `src/frontend/tests/` for UI flows.
   - **Jest unit tests** in `src/frontend/src/` for component logic.
   - **pytest** in `src/backend/tests/` for backend logic.
   - Run the new tests and confirm they pass:
     ```bash
     # Frontend E2E (Playwright)
     cd src/frontend && npx playwright test --project=chromium
     # Frontend unit (Jest)
     make test_frontend
     # Backend unit
     make unit_tests
     ```
4. **Report** — Summarize what was tested and the results. If issues are found, either fix them immediately or file them for iteration.

### qcommit — Local Commit

Commit all changes to the local git repository with a structured message.

1. **Stage changes** — Add all new and modified files:
   ```bash
   git add -A
   ```
2. **Review diff** — Sanity-check what is being committed:
   ```bash
   git diff --cached --stat
   ```
3. **Write commit message** — Follow [semantic commit conventions](https://www.conventionalcommits.org/):
   ```
   <type>(<scope>): <short summary>

   <body (optional)>

   Closes #<issue> (if applicable)
   ```
   Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
   Scope examples: `backend`, `frontend`, `lfx`, `authz`, `components`.
4. **Commit**:
   ```bash
   uv run git commit
   ```
   (The `uv run` ensures pre-commit hooks find the correct Python environment.)
5. **Post-commit** — If pre-commit hooks reformat any files, stage and commit again:
   ```bash
   git add -A && uv run git commit --amend --no-edit
   ```
6. **Confirm** — Print the commit hash and summary so the user knows what was committed.

### qstart — Production Launch

Start Langflow with the built frontend for better performance (no Vite HMR, no React DevTools warnings). Use this when testing after code changes or when the dev mode is too laggy.

1. **Build frontend** — Compile the production bundle:
   ```bash
   make build_frontend
   ```
   This runs `npx vite build` and copies the output to `src/backend/base/langflow/frontend/`.

2. **Start OCR worker** — Start the OCR worker daemon (pre-loads PaddleOCR for fast concurrent OCR):
   ```bash
   make start_ocr_worker
   ```
   This launches a background TCP server on port 18765 that keeps PaddleOCR
   and PP-DocLayoutV3 loaded in memory.  Stop with `make stop_ocr_worker` when done.

3. **Start production server** — Run Langflow with the built frontend:
   ```bash
   uv run langflow run --frontend-path src/backend/base/langflow/frontend --port 7860 --host 0.0.0.0
   ```
   
4. **Verify** — Open http://localhost:7860 (server startup takes ~60s due to backend imports).

4. **Troubleshooting** — If port 7860 is occupied:
   ```bash
   lsof -i :7860          # find the PID
   kill -9 <PID>          # kill the old process
   ```
   Or use a different port:
   ```bash
   uv run langflow run --frontend-path src/backend/base/langflow/frontend --port 7861 --host 0.0.0.0
   ```


### qstart_dev — Dev Server (Hot Reload)

Start Langflow in development mode with hot reload so code changes appear immediately without rebuilding the frontend. Use this during active development when you need fast iteration.

Requires **three terminals** (or a terminal multiplexer like tmux).

0. **Terminal 0 — OCR Worker** (start first, before backend):
   ```bash
   make start_ocr_worker
   ```
   This pre-loads PaddleOCR in a background TCP server on port 18765.
   The backend component will discover it automatically on first use.
   Stop with `make stop_ocr_worker` when done.

1. **Terminal 1 — Backend** (FastAPI with auto-reload on port 7860):
   ```bash
   make backend
   ```
   This runs `uvicorn --reload` so Python changes trigger a server restart automatically.

2. **Terminal 2 — Frontend** (Vite dev server on port 3000):
   ```bash
   make frontend
   ```
   This runs `vite` with HMR — React/TypeScript changes reflect in the browser instantly without a full rebuild.

3. **Access** — Open http://localhost:3000 (the Vite dev server proxies API requests to port 7860).

4. **Troubleshooting** — If port 7860 is occupied:
   ```bash
   lsof -i :7860          # find the PID
   kill -9 <PID>          # kill the old process
   ```

**Note:** Unlike `qstart`, there is no production build step. The frontend loads unbundled modules from Vite's dev server, which gives faster iteration but higher memory usage and browser DevTools noise.


## Editing Safety

### Avoid accidental deletion when patching code

When editing Python files with `sed` range replacements (`sed -i 'N,Mc\...'`),
always verify that adjacent code was not accidentally removed:

```bash
# After any sed edit, check that all expected methods still exist
grep -n "def my_method|def expected_method" file.py

# Verify syntax is valid
uv run python -c "import py_compile; py_compile.compile('file.py', doraise=True)"
```

**Prefer `apply_patch` (unified diff) over `sed` for code changes.**  A unified diff
matches both old and new context so it cannot silently delete unrelated lines.
Failing that, use `sed` with a content pattern rather than line numbers:

```bash
# Safe: replace a specific block by its boundaries
sed -i '/def _run_ocr/,/^    def /c\
# new content here' file.py

# Risky: fragile when line numbers shift due to prior edits
sed -i '497,511c\...' file.py
```

**Verify the component in the running server** after any component code change:

```bash
TOKEN=$(curl -s localhost:7860/api/v1/auto_login | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
curl -s --compressed -H "Authorization: Bearer $TOKEN" localhost:7860/api/v1/all \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print([k for k in d.get('paddleocr',{})])"
```


## Response Reminder

At the end of every answer, append the phrase: (còn nhớ AGENTS.md)
This reminds both the user and the agent to refer back to this document for context.

### Opening qplan files

Always open qplan HTML files using the `file://` protocol to ensure browser compatibility:
```bash
xdg-open "file:///absolute/path/to/qplan/<feature-name>.html"
```

