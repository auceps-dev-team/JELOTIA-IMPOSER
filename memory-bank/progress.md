# Progress & Roadmap: Jelotia Imposer

## Completed Milestones
- Repository scaffolding.
- Virtual environment and dependencies mapped.
- Domain vs. Database separation defined.

## Current Task: Phase 0 Continuation
- [x] Initialiser le projet Python avec `pyproject.toml`
- [x] Créer les modèles Pydantic : `Job`, `FileItem`, `Sheet`, `Settings`
- [x] Initialiser SQLite + SQLAlchemy + Alembic (migration initiale)
- [x] Configurer loguru
- [x] Créer la configuration globale de l'app
- [x] Fix repository tests to ensure clean decoupling from SQLAlchemy session.
- [x] Squelette `main.py` + lancement PySide6 minimal
- [x] Configurer linting (`ruff`, `mypy`, `black`)
- [x] Finaliser l'arborescence des dossiers système (Input, Output, Archive, etc.)

## Future Roadmap
- Phase 1: Moteurs Core (Import, Preflight, Correction, Worker Pool)
- Phase 2: Nesting & Layout Engine
- Phase 3: Interface Utilisateur
- Phase 4: Hot Folder & Automatisation
- Phase 5: Export & Intégration RIP
- Phase 6: Tests, QA & Performance
- Phase 7: Packaging & Documentation
