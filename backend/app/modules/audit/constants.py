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
    LINK_CREATED = "share_link.created"
    LINK_REVOKED = "share_link.revoked"
    LINK_DOWNLOADED = "share_link.downloaded"


class ResourceType(StrEnum):
    FILE = "file"
    FOLDER = "folder"
    USER = "user"
