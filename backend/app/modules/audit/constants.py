from enum import StrEnum


class AuditAction(StrEnum):
    FILE_UPLOADED = "file.uploaded"
    FILE_DOWNLOADED = "file.downloaded"
    FILE_DELETED = "file.deleted"
    FOLDER_DELETED = "folder.deleted"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_CHANGED = "permission.changed"
    PERMISSION_REVOKED = "permission.revoked"
    LOGIN = "auth.login"


class ResourceType(StrEnum):
    FILE = "file"
    FOLDER = "folder"
    USER = "user"
