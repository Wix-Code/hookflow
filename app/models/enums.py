from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    DEVELOPER = "developer"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"