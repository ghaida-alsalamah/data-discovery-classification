from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import SQLITE_ATTACH, SQLITE_DENY, SQLITE_OK

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError


@dataclass
class InformationAsset:
    name: str
    description: str
    owner: str
    database_type: str = "sqlite"
    access_scope: str = "read_only"
    connection_status: str = "disconnected"


class SourceConnectionError(RuntimeError):
    pass


class SQLiteConnector:
    def __init__(self, path: Path, asset: InformationAsset):
        self.asset = asset
        self.asset.database_type = "sqlite"
        self.asset.access_scope = "read_only"
        self.engine = create_engine(
            URL.create("sqlite", database=path.resolve().as_uri(),
                       query={"mode": "ro", "uri": "true"}),
            hide_parameters=True,
        )

        event.listen(self.engine, "connect", self._configure_connection)

    @staticmethod
    def _configure_connection(connection, _):
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(
            lambda action, *_: SQLITE_DENY if action == SQLITE_ATTACH else SQLITE_OK
        )

    @contextmanager
    def connect(self):
        try:
            connection = self.engine.connect()
        except SQLAlchemyError:
            self.asset.connection_status = "error"
            raise SourceConnectionError("Could not open the SQLite source read-only.") from None
        self.asset.connection_status = "connected"
        try:
            with connection:
                yield connection
        finally:
            self.asset.connection_status = "disconnected"
            self.engine.dispose()
