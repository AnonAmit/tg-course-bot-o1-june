# Changelog

## [0.1.0] - YYYY-MM-DD
### Added
- Initial project setup for SQLite to PostgreSQL migration.
- Created `todo.md` for tracking progress.
- Created `changelog.md` for documenting changes.
### Changed
- Ensured `psycopg2-binary` is in `requirements.txt`.
- Verified `config.py` handles PostgreSQL connection via `DATABASE_URL`.
- Confirmed `Procfile` and `Dockerfile` are suitable for PostgreSQL deployment.

## [0.2.0] - YYYY-MM-DD
### Added
- Decided to migrate to MongoDB instead of PostgreSQL.
- Updated `todo.md` to reflect MongoDB migration plan and new bot feature request.

### Changed
- Updated `requirements.txt`: added `pymongo`, commented out `sqlalchemy`, `alembic`, `psycopg2-binary`.
- Updated `config/config.py` to use `MONGODB_URI` for database connection.
- Refactored `database/models.py` from SQLAlchemy to `pymongo`, including DB connection logic and index creation functions.
- Refactored `database/init_db.py` to use `pymongo` for initializing data (admin, categories, courses) and ensuring indexes.

### Removed
- Deleted `database/migration.py` as it's no longer needed for MongoDB.

## [0.3.0] - YYYY-MM-DD
### Changed
- Fully refactored `admin/app.py` to use MongoDB (`pymongo`) for all database interactions, including:
    - Login, logout, user session management.
    - Dashboard statistics.
    - CRUD operations for Courses, Payments, Users, Categories, Bot Settings, Course Requests.
    - Handling of `ObjectId` and client-side data resolution for display.
    - Updated `/fix-gift-codes` route for MongoDB.
    - Updated `app.run()` for Heroku compatibility. 