# Deployment guide

This document covers local development and Hugging Face Spaces deployment (Gradio SDK). See [SECURITY.md](SECURITY.md) for credential and hosting boundaries.

## Local development

Use Python **3.13** to match the release environment. From the repository root:

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-space-lock.txt -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m scripts.init_env
.\.venv\Scripts\python.exe -m scripts.launch_demo
```

```bash
# Linux / macOS
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-space-lock.txt -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m scripts.init_env
.venv/bin/python -m scripts.launch_demo
```

Open **http://127.0.0.1:8501**. The launcher starts the decision engine on port 8000 (loopback only) and the Streamlit dashboard on port 8501. Ctrl+C stops both. Local SQLite state is written under `runtime/`.

### AI provider options

| Flag | Behavior |
|---|---|
| `--ai off` (default) | No Groq calls; visitors can supply their own key in the sidebar |
| `--ai fake` | Visibly labeled mock responses; useful for UI testing |
| `--ai groq` | Operator-owned Groq key read from `.env` (`GROQ_API_KEY=...`) |

The public Spaces launcher always uses `--ai off`.

## Hugging Face Spaces (Gradio SDK)

The app runs on a **Gradio** Space — no Docker subscription required. The Space uses `app.py` at the repository root as its entry point, which starts the FastAPI engine on loopback and Streamlit on port 7860.

### One-time Space setup

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space).
2. Choose **Gradio** as the Space SDK.
3. Set the Space to **Public** (or **Private** for a restricted demo).
4. The Space ID will be `<your-username>/harbor-maester`.

> [!IMPORTANT]
> Do **not** set `GROQ_API_KEY` as a Space secret. The public launcher clears any inherited key and forces the AI provider off. Visitors supply their own key in the Streamlit sidebar.

### Manual upload via `huggingface_hub` CLI

```sh
# Install the HF CLI
pip install 'huggingface_hub>=1,<2'

# Authenticate (one-time; creates ~/.cache/huggingface/token)
huggingface-cli login

# Build the upload bundle (never uploads the working directory wholesale)
python -m scripts.prepare_space --output runtime/space-upload

# Upload to your Space
huggingface-cli upload <your-username>/harbor-maester runtime/space-upload . --repo-type space
```

The upload bundle contains only allowlisted source files (see `scripts/prepare_space.py`). It includes `app.py` (the Gradio Space entry point), source code, config and data. It excludes local credentials, SQLite databases, training environments, test fixtures and ground-truth labels.

### Automated deployment via GitHub Actions

The repository includes `.github/workflows/space.yml`. To trigger it:

1. Add `HF_TOKEN` as a GitHub Actions secret in your repository settings  
   (**Settings → Secrets and variables → Actions → New repository secret**).
2. Go to **Actions → Deploy Hugging Face Space (Gradio) → Run workflow**.
3. Enter your Space ID in the format `username/harbor-maester`.

The workflow runs the release check, builds the upload bundle, and calls `huggingface-cli upload` using the stored token.

### Environment variables inside the Space

`app.py` sets all required variables at startup:

| Variable | Value | Purpose |
|---|---|---|
| `AI_PROVIDER` | `off` | Disables instance-wide Groq |
| `GROQ_API_KEY` | `` (cleared) | Prevents any inherited credential leaking |
| `HARBOR_PUBLIC_DEMO` | `true` | Enables public-demo UI notice and disables host-AI path |
| `HARBOR_AUTOSTART` | `true` | Starts the exercise without a manual trigger |
| `DATABASE_PATH` | `runtime/space.sqlite3` | Local container storage (ephemeral) |
| `ENGINE_*_TOKEN` | Random per boot | Internal service tokens; never set by users |

Do not set `ENGINE_*_TOKEN` manually — they are regenerated on every restart.

## Release hygiene

Before merging to `main`, run:

```sh
python -m scripts.release_check
python project-website/check_site.py
node --check project-website/app.js
```

To run the full test suite locally (not run on CI automatically):

```sh
python -m pytest tests simulator/tests -q
```

These checks (excluding tests) are also run by the CI workflow on every push and pull request against `main`.

## GitHub Pages (static website)

The website under `project-website/` is deployed automatically when files under that path change on the `main` branch, via `.github/workflows/pages.yml`. To trigger a manual redeploy:

```sh
# From the GitHub UI: Actions → Harbor-maester website → Run workflow
# Or force a commit touching the workflow file:
git commit --allow-empty -m "chore: trigger pages redeploy"
git push origin main
```

The workflow copies only `index.html`, `style.css`, `app.js`, `favicon.svg` and `assets/*.png` to the deployment artifact. No Python source, credentials or runtime state are published.
