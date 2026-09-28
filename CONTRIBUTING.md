# Contributing to EpisodAI

EpisodAI is the public MCP memory engine at [lalithbuilds/episodai](https://github.com/lalithbuilds/episodai). Its Python import package remains `engram` for compatibility.

## Local setup

Python 3.10 or newer is required. Clone the canonical repository, create a virtual environment, and install the development dependencies:

```bash
git clone https://github.com/lalithbuilds/episodai.git
cd episodai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

On Windows, activate with `.venv\Scripts\activate`. Hardware-specific tests can skip when the required accelerator is unavailable. CI covers Python 3.10–3.12 on Ubuntu, macOS, and Windows; check the current workflow for the exact matrix.

## Changes and evidence

- Keep code changes focused, add tests for new behavior, and run `python -m pytest -q` before opening a pull request.
- Describe user-visible behavior and include a reproducible command for bug fixes.
- For performance claims, state the hardware, dataset, command, and measurements. Do not generalize a result from one machine to every platform.
- Use EpisodAI as the product name. Preserve `engram` import paths and documented legacy command aliases unless a migration is intentionally proposed.
- Never commit credentials, private notes, `.env` files, or generated databases. Report security issues using [SECURITY.md](SECURITY.md).
