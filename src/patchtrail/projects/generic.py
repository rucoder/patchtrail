"""Projects with no trail beyond the mailing list."""

from patchtrail.projects.base import MAIL_ONLY, Project


def mail_only(name: str) -> Project:
    return Project(name, MAIL_ONLY, None)
