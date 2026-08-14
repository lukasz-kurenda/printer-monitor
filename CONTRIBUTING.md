# Contributing to Printers Dashboard

Thanks for taking the time to contribute! This document keeps the process simple
for both sides.

## Quick start for developers

```bash
git clone https://github.com/lukasz-kurenda/printer-monitor.git
cd printer-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest flake8        # test/dev tools
```

Run the checks before submitting anything:

```bash
python -m pytest                 # 47 tests
flake8 . --count --select=E9,F63,F7,F82   # fatal lint (must be 0)
```

The test suite does not need real printers — use the built-in simulator
(see `simulator/README.md`).

## Reporting issues

- **Bugs**: describe what you expected, what happened, and the version you used.
  Include logs (`printer_monitor.log`) if possible.
- **Security**: do **not** open a public issue — use SECURITY.md instead.

## Submitting changes

1. Fork the repository and create a feature branch:
   `git checkout -b fix/short-description`
2. Keep the change focused — one logical change per PR.
3. Add or update tests for the change; keep the suite green.
4. Follow the existing style (PEP 8, line length 127, English comments/messages).
5. Commit with **Conventional Commits**, e.g.:
   - `fix(counters): handle zero totals correctly`
   - `feat(dashboard): add history chart`
   - `docs(readme): explain custom OIDs`
6. Open a pull request against `main`.

## Project structure

```
main.py / dashboard.py   entry points (CLI worker + web dashboard)
db.py, printers.py, email_utils.py, alerts.py,
snmp_client.py, web_scraper.py, reports.py   cohesive modules
simulator/               fake printers for testing without hardware
tests/                   pytest suite
```

## Code of conduct

Be respectful. This is a small, friendly project — keep it that way. If your
first PR is also your first PR anywhere: welcome, we are glad you are here.
