from enum import StrEnum


class JobStage(StrEnum):
    VERIFY_OBJECT = "verify_object"
    SCAN = "scan"
    DETECT_TYPE = "detect_type"
    EXTRACT = "extract"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
