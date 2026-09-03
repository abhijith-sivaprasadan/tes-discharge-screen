# Contributing

This is a solo research/portfolio project. Issues and pull requests are welcome, but
contributions must preserve the project's central discipline: verified is not
validated, and no claim goes further than the evidence committed alongside it.

## Development setup

1. Clone the repository.
2. Create a Python 3.10-3.13 virtual environment, or use `uv venv`.
3. Install `pip install -e ".[dev]"` (or `uv pip install -e ".[dev]"`).
4. Run `pytest` and `ruff check .`.

## Rules that apply to every change

- No magic constants in source. Every assumption lives in a config YAML.
- No result committed without a solver status and a traceable config.
- No use of the word "validate" for anything checked only against the model's own
  physics, an analytic limit, or a hand calculation; that is "verified". Grep for
  "validate" before committing documentation.
- No material property, cost figure, or performance parameter without a citation
  naming source and year.
- No synthetic load profile or price series presented without the word "synthetic"
  on the same screen as the first result that uses it.
- Documentation ships in the same commit as the capability it describes.
- Tests check physics or contracts, not syntax. When a test fails, work out whether
  the model or the test encoded the wrong expectation; never weaken the physics to
  make a test pass.

## Pull requests

Keep changes focused. Explain the physical assumption, its units, and how it is
verified. New dependencies must be open source and justified.
