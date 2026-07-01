# Tech Context: Jelotia Imposer

## Environment
- OS: Windows
- Python: >=3.12
- Dependency Management: `uv`

## Technology Stack
- **UI**: PySide6 (Qt 6)
- **Database**: SQLite with SQLAlchemy ORM and Alembic for migrations
- **PDF Processing**: PyMuPDF (fitz), pikepdf, ReportLab
- **Image Processing**: Pillow, OpenCV
- **Nesting / Geometry**: rectpack, Shapely
- **Concurrency**: `multiprocessing` + `asyncio`
- **File System Monitoring**: `watchdog`
- **Validation**: Pydantic v2
- **Logging**: `loguru`
- **Testing**: `pytest`

## Folder Topology
```
jelotia-imposer/
├── memory-bank/         # AI Context (MANDATORY)
├── src/
│   ├── core/            # Business logic, engines, Pydantic models
│   ├── database/        # SQLAlchemy models, repository, Alembic migrations
│   ├── ui/              # PySide6 components
│   └── utils/           # Utilities, config, logging
├── tests/               # pytest unit/integration tests
├── docs/
├── installer/
├── main.py              # Application entry point
├── pyproject.toml       # Dependencies and project metadata
└── uv.lock
```
