# Active Context: Jelotia Imposer

## Current Implementation State
- Project has successfully completed **Phase 0: Setup & Architecture**.
- Directory structure is set up.
- `pyproject.toml` is initialized using `uv` with all major dependencies including dev tools (`ruff`, `mypy`, `black`, `pytest-cov`).
- Pydantic models (`Job`, `FileItem`, `Sheet`) are created in `src/core/models/domain.py`.
- SQLAlchemy ORM models (`JobModel`, `FileItemModel`, `SheetModel`) are set up in `src/database/models.py`.
- Alembic configured and initial DB migration generated.
- Repository layer (`DatabaseRepository`) created with mitigations for `DetachedInstanceError`.
- Logging (`loguru`) and Configuration (`AppConfig`) modules established with auto-creation of system directories.
- `main.py` is initialized with a basic PySide6 UI.

## Pending Immediate Tasks
- Ready to move to **Phase 1: Moteurs Core**.
- Task 1.1: Import Engine (PyMuPDF, Pillow, Metadata extraction).

## Technical Debt / Known Issues
- None currently.
