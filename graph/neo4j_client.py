import os
from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, ConfigurationError, DatabaseError, ServiceUnavailable


class Neo4jClient:
    def __init__(self) -> None:
        self.uri = os.getenv("NEO4J_URI")
        self.username = os.getenv("NEO4J_USERNAME")
        self.password = os.getenv("NEO4J_PASSWORD")
        self.database = os.getenv("NEO4J_DATABASE", "neo4j")

        missing_variables = []
        if not self.uri:
            missing_variables.append("NEO4J_URI")
        if not self.username:
            missing_variables.append("NEO4J_USERNAME")
        if not self.password:
            missing_variables.append("NEO4J_PASSWORD")

        if missing_variables:
            raise ValueError("未读取到 Neo4j 环境变量：" + ", ".join(missing_variables))

        try:
            self.driver: Driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
                connection_timeout=10,
            )
            self.driver.verify_connectivity()

        except AuthError as exc:
            raise RuntimeError(
                "Neo4j 认证失败：请检查 NEO4J_USERNAME 和 NEO4J_PASSWORD。"
            ) from exc

        except ServiceUnavailable as exc:
            raise RuntimeError(
                f"无法连接 Neo4j：{self.uri}。请确认 Neo4j Desktop 实例已启动，Bolt 端口可访问。"
            ) from exc

        except ConfigurationError as exc:
            raise RuntimeError(f"Neo4j URI 配置错误：{self.uri}") from exc

        except DatabaseError as exc:
            raise RuntimeError(f"Neo4j 数据库访问失败：{self.database}") from exc

    def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        with self.driver.session(database=self.database) as session:
            session.run(query, parameters or {}).consume()

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
