# System Patterns: Jelotia Imposer

## Architectural Paradigms
- **Event-Driven Pipeline**: The application utilizes an asynchronous queue and a worker pool to process files through sequential stages: Import -> Preflight -> Correction -> Nesting -> Layout -> Export.
- **Hot Folder Automation**: Uses `watchdog` to monitor input directories and auto-trigger pipelines.

## Coding Conventions & Data Access
- **Database Layer**: SQLAlchemy ORM with repository pattern (`DatabaseRepository`).
- **Session Management Gotchas**: A known issue in SQLite + SQLAlchemy is `DetachedInstanceError` when accessing related models outside the session. 
  - *Pattern to use*: Eager loading with `subqueryload` for relationships (like `files`, `sheets`), and `session.expunge(obj)` after materializing necessary attributes before closing the session. Ensure SQLite URLs start with `sqlite:///`.
- **Domain Models**: Immutable or strictly validated structures using Pydantic, separated from DB ORM models.

## Reliability
- Strict adherence to the Zero-Placeholder Policy (ZPP). Always produce fully functional, complete file outputs.
- Verification checks must be conducted after significant changes by running tests.
