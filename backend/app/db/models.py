"""Every table of the application, registered on `Base.metadata` by importing its models.

A foreign key can only be resolved once the table it points to has been imported. The API
imports everything through its routers, but a worker or a script does not, and fails the first time
it touches a table (`NoReferencedTableError`). So any process that opens a database session
imports this module once: the API, the worker and Alembic. A new module's models are added here and
nowhere else.
"""

from app.modules.audit import models as audit_models
from app.modules.auth import models as auth_models
from app.modules.processing import models as processing_models
from app.modules.sharing import models as sharing_models
from app.modules.storage import models as storage_models
from app.modules.workspaces import models as workspace_models

__all__ = [
    "audit_models",
    "auth_models",
    "processing_models",
    "sharing_models",
    "storage_models",
    "workspace_models",
]
