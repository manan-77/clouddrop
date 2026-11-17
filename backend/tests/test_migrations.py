from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

from app.db.base import Base


def test_models_matchTheMigratedSchema(engine: Engine) -> None:
    """A model change without a migration (or the reverse) fails here, not in production."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
