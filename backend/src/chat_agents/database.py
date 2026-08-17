"""Shared database metadata and schema names."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

APP_SCHEMA = "app"
OBSERVABILITY_SCHEMA = "obs"
MANAGED_SCHEMAS = frozenset({APP_SCHEMA, OBSERVABILITY_SCHEMA})


class Base(DeclarativeBase):
    metadata = MetaData()
