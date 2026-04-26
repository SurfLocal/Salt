# Standard Library Imports
import os

# Third-Party Imports
import psycopg2
from psycopg2 import sql

# Local Application Imports
from .logger import Logger


class PostgresConnection:
    """
    Thin wrapper around psycopg2. Tier A connects via DATABASE_URL (Neon),
    Tier B connects via the same env var pointed at Cloud SQL. Legacy
    DB_HOST/DB_USER/DB_PASSWORD/DB_NAME are still honored as a fallback so
    local dev and the existing Helm chart keep working unchanged.
    """

    def __init__(
        self,
        host=None,
        user=None,
        password=None,
        database=None,
        dsn=None,
        logger=None,
    ):
        self.dsn = dsn
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.conn = None
        self.cursor = None
        self.logger = logger

    @classmethod
    def from_env(cls, logger=None, *, analytics=False):
        """
        Resolve connection info from env vars. Prefers DATABASE_URL /
        ANALYTICS_DATABASE_URL; falls back to discrete DB_* vars.
        """
        url_var = "ANALYTICS_DATABASE_URL" if analytics else "DATABASE_URL"
        dsn = os.getenv(url_var) or os.getenv("DATABASE_URL")
        if dsn:
            return cls(dsn=dsn, logger=logger)

        return cls(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME") if not analytics else os.getenv("ANALYTICS_DB_NAME", "surf_analytics"),
            logger=logger,
        )

    def connect(self):
        """Establish connection to PostgreSQL database."""
        try:
            if self.dsn:
                self.conn = psycopg2.connect(self.dsn, connect_timeout=10)
            else:
                self.conn = psycopg2.connect(
                    host=self.host,
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    connect_timeout=10,
                )
            if self.conn:
                self.cursor = self.conn.cursor()
        except psycopg2.Error as e:
            target = self.dsn or self.host
            if self.logger:
                self.logger.log_json(
                    "ERROR",
                    f"Unable to connect to PostgreSQL database: {e}",
                    {"target": target},
                )
            self.conn = None

    def close(self):
        """Close the PostgreSQL connection."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def execute_query(self, query, params=None, fetch=False):
        """Execute a query on the PostgreSQL database."""
        try:
            if not self.conn:
                raise ConnectionError("PostgreSQL connection is not established")

            self.cursor.execute(query, params or ())
            if fetch:
                return self.cursor.fetchall()
            self.conn.commit()
            return True
        except psycopg2.Error as e:
            if self.logger:
                self.logger.log_json("ERROR", f"Failure executing query: {e}")
            return None
        except ConnectionError as e:
            if self.logger:
                self.logger.log_json("ERROR", f"Connection error: {e}")
            return None

    def insert(self, table, data):
        """Insert data into a schema-qualified table."""
        schema, table = table.split(".")
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(columns),
            sql.SQL(placeholders),
        )
        if self.execute_query(query, tuple(data.values())) is None:
            if self.logger:
                self.logger.log_json("ERROR", "Failed to insert data", {"table": table, "data": data})
            return False
        return True

    def select(self, table, columns="*", where=None, params=None):
        """Select data from a table."""
        query = f"SELECT {columns} FROM {table}"
        if where:
            query += f" WHERE {where}"
        return self.execute_query(query, params, fetch=True)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
