**Perfect — here's the fully reusable `DatabaseCustomAgent`**, built exactly like the `ApiFetcherCustomAgent` you loved (same style: `name`, `description`, `output_key`, `db_input_key`, `default_db_yaml`, deterministic, no LLM).

### New & innovative features
- Supports **Postgres, Oracle, SQL Server (MSSQL), generic SQL** (via SQLAlchemy) **and MongoDB** (via PyMongo).
- **Secure credential handling** — same `${ENV:YOUR_SECRET}` placeholders as the API agent (secrets never in YAML or code).
- **Connection caching** (optional but enabled by default) — reuses engine/client in the same session for speed.
- **Parameterized queries** for SQL (prevents injection).
- **Flexible Mongo operations** (`find`, `aggregate`, `insert_one`, easy to extend).
- **Unified YAML config** — one simple format for all DBs.
- 100% deterministic, works as sub-agent in any ADK workflow.

### Installation
```bash
pip install sqlalchemy psycopg2-binary oracledb pymongo pymssql PyYAML
```

### Reusable DatabaseCustomAgent

```python
import yaml
import os
import logging
from typing import Any, Dict, Optional, AsyncGenerator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import pymongo
from pymongo.errors import PyMongoError

from google.adk.agents import BaseAgent
from google.adk.context import InvocationContext
from google.adk.events import FinalResponseEvent, Event

logger = logging.getLogger(__name__)

class DatabaseCustomAgent(BaseAgent):
    """
    Reusable deterministic DB Agent (mirrors ApiFetcherCustomAgent style).
    Supports Postgres, Oracle, MSSQL, generic SQL (SQLAlchemy) + MongoDB.
    """

    def __init__(
        self,
        name: str = "db_agent",
        description: str = "Secure deterministic agent for Postgres, Oracle, SQL Server & MongoDB",
        output_key: str = "db_result",
        db_input_key: str = "db_yaml",
        default_db_yaml: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(name=name, description=description, **kwargs)
        self.output_key = output_key
        self.db_input_key = db_input_key
        self.default_db_yaml = default_db_yaml

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        logger.info(f"[{self.name}] Starting DB operation → output_key='{self.output_key}'")

        yaml_str: Optional[str] = ctx.session.state.get(self.db_input_key) or self.default_db_yaml
        if not yaml_str:
            error = {"error": f"No DB config in '{self.db_input_key}' or default"}
            ctx.session.state[self.output_key] = error
            yield FinalResponseEvent(content="Error: No database YAML provided", data=error)
            return

        try:
            config: Dict = yaml.safe_load(yaml_str) if isinstance(yaml_str, str) else yaml_str

            db_type = config.get("type", "").lower()

            if db_type in ("postgres", "postgresql", "oracle", "mssql", "mysql", "sqlite"):
                result = self._execute_sqlalchemy(config, ctx)
            elif db_type == "mongodb":
                result = self._execute_mongodb(config, ctx)
            else:
                raise ValueError(f"Unsupported db_type: {db_type}. Supported: postgres, oracle, mssql, mysql, sqlite, mongodb")

            ctx.session.state[self.output_key] = result
            logger.info(f"[{self.name}] DB operation successful")
            yield FinalResponseEvent(
                content=f"Database operation completed. Result stored in '{self.output_key}'.",
                data={"status": "success", "output_key": self.output_key},
            )

        except Exception as e:
            error_data = {"error": str(e)}
            ctx.session.state[self.output_key] = error_data
            logger.error(f"[{self.name}] Failed: {e}")
            yield FinalResponseEvent(content=f"Database operation failed: {str(e)}", data={"status": "error"})

    def _resolve_secrets_in_url(self, url: str) -> str:
        """Replace all ${ENV:VAR} in connection URL with real env values."""
        for key, val in os.environ.items():
            placeholder = f"${{ENV:{key}}}"
            if placeholder in url:
                url = url.replace(placeholder, val)
        return url

    def _execute_sqlalchemy(self, config: Dict, ctx: InvocationContext) -> Any:
        """SQLAlchemy path (Postgres, Oracle, MSSQL, MySQL, etc.)"""
        conn = config.get("connection", {})
        url = conn if isinstance(conn, str) else conn.get("url")
        if not url:
            raise ValueError("connection.url is required for SQL databases")

        url = self._resolve_secrets_in_url(url)

        # Optional: cache engine in session for reuse
        cache_key = f"sqlalchemy_engine_{hash(url)}"
        engine = ctx.session.state.get(cache_key)
        if not engine:
            engine = create_engine(url, echo=False, future=True, pool_pre_ping=True)
            ctx.session.state[cache_key] = engine

        query = config.get("query")
        if not query:
            raise ValueError("'query' is required for SQL databases")

        params = config.get("params", {})  # safe parameterized

        try:
            with engine.connect() as conn:
                result = conn.execute(text(query), params)
                if result.returns_rows:
                    return [dict(row._mapping) for row in result.all()]
                return {"affected_rows": result.rowcount, "status": "success"}
        except SQLAlchemyError as e:
            raise RuntimeError(f"SQL execution error: {e}")

    def _execute_mongodb(self, config: Dict, ctx: InvocationContext) -> Any:
        """PyMongo path"""
        uri = config.get("uri") or config.get("connection", {}).get("uri")
        if not uri:
            raise ValueError("uri is required for MongoDB")

        uri = self._resolve_secrets_in_url(uri)

        db_name = config.get("database")
        collection_name = config.get("collection")
        operation = config.get("operation", "find").lower()

        if not db_name or not collection_name:
            raise ValueError("database and collection are required for MongoDB")

        # Optional caching of client
        cache_key = f"mongodb_client_{hash(uri)}"
        client = ctx.session.state.get(cache_key)
        if not client:
            client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)
            ctx.session.state[cache_key] = client

        db = client[db_name]
        coll = db[collection_name]

        try:
            if operation == "find":
                filter_doc = config.get("filter", {})
                proj = config.get("projection")
                limit = config.get("limit", 1000)
                return list(coll.find(filter_doc, proj).limit(limit))

            elif operation == "aggregate":
                pipeline = config.get("pipeline", [])
                return list(coll.aggregate(pipeline))

            elif operation == "insert_one":
                doc = config.get("document")
                return {"inserted_id": str(coll.insert_one(doc).inserted_id)}

            elif operation == "update_one":
                filter_doc = config.get("filter", {})
                update_doc = config.get("update", {})
                return {"modified_count": coll.update_one(filter_doc, update_doc).modified_count}

            else:
                raise ValueError(f"Unsupported Mongo operation: {operation} (add more easily in _execute_mongodb)")
        except PyMongoError as e:
            raise RuntimeError(f"MongoDB error: {e}")
```

### Example YAML configs (what user provides)

**1. Postgres**
```yaml
type: postgres
connection:
  url: "postgresql+psycopg2://${ENV:DB_USER}:${ENV:DB_PASSWORD}@localhost:5432/mydb"
query: "SELECT * FROM users WHERE age > :min_age"
params:
  min_age: 25
```

**2. Oracle**
```yaml
type: oracle
connection:
  url: "oracle+oracledb://${ENV:ORACLE_USER}:${ENV:ORACLE_PASS}@//host:1521/service_name"
query: "SELECT * FROM employees WHERE department = :dept"
params:
  dept: "SALES"
```

**3. SQL Server (MSSQL)**
```yaml
type: mssql
connection:
  url: "mssql+pymssql://${ENV:MSSQL_USER}:${ENV:MSSQL_PASS}@localhost:1433/mydb"
query: "SELECT * FROM orders WHERE order_date > :start_date"
params:
  start_date: "2025-01-01"
```

**4. MongoDB**
```yaml
type: mongodb
uri: "mongodb://${ENV:MONGO_USER}:${ENV:MONGO_PASS}@localhost:27017/"
database: "ecommerce"
collection: "products"
operation: "find"
filter:
  price: { "$gt": 100 }
limit: 50
```

### Usage (same reusable pattern)

```python
# 1. Create reusable agent instance
db_agent = DatabaseCustomAgent(
    name="sales_db_fetcher",
    output_key="sales_data",          # your desired output_key
    # default_db_yaml=... (optional fixed config)
)

# 2. Provide YAML at runtime
session = InMemorySession(initial_state={
    "db_yaml": your_yaml_string_above   # or load from file
})

runner = Runner(agent=db_agent, session=session)

async for event in runner.run_async():
    print(event)   # result is in session.state["sales_data"]
```

You can now drop this agent into any `SequentialAgent`, `Supervisor`, or multi-agent team — it works exactly like your API agent.

Just send me your **exact YAML example** (or any extra operations like Mongo `delete`, SQL transactions, connection dict instead of URL, etc.) and I’ll tweak the code in seconds. Ready to integrate with your ApiFetcherCustomAgent? 🚀
