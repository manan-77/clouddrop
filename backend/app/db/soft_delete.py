"The one place the soft-delete predicate is written."

from sqlalchemy import ColumnElement

from app.db.base import SoftDeleteMixin


def only_active(model: type[SoftDeleteMixin]) -> ColumnElement[bool]:
    return model.deleted_at.is_(None)
