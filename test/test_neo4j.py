import os
import sys
from uuid import uuid4

from neo4j import GraphDatabase
from neo4j.exceptions import (
    AuthError,
    ConfigurationError,
    DatabaseError,
    Neo4jError,
    ServiceUnavailable,
)


def mask_value(value: str | None, visible_chars: int = 2) -> str:
    """Mask sensitive values for console diagnostics."""
    if not value:
        return "<not set>"

    if len(value) <= visible_chars * 2:
        return "*" * len(value)

    return (
        value[:visible_chars]
        + "*" * (len(value) - visible_chars * 2)
        + value[-visible_chars:]
    )


def main() -> None:
    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    print("=" * 60)
    print("Neo4j 环境变量检查")
    print("=" * 60)
    print(f"NEO4J_URI      : {uri!r}")
    print(f"NEO4J_USERNAME : {username!r}")
    print(f"NEO4J_PASSWORD : {mask_value(password)}")
    print(f"密码长度        : {len(password) if password else 0}")
    print(f"NEO4J_DATABASE : {database!r}")
    print()

    missing_variables = []
    if not uri:
        missing_variables.append("NEO4J_URI")
    if not username:
        missing_variables.append("NEO4J_USERNAME")
    if not password:
        missing_variables.append("NEO4J_PASSWORD")

    if missing_variables:
        print("错误：以下环境变量未读取到：" + ", ".join(missing_variables))
        print("请确认变量已经写入，并重新启动 Anaconda Prompt / PowerShell / IDE。")
        sys.exit(1)

    print("[connect] 准备连接 Neo4j...")
    print(f"[connect] URI: {uri}")
    print(f"[connect] username: {username}")
    print(f"[connect] database: {database}")
    print()

    try:
        with GraphDatabase.driver(
            uri,
            auth=(username, password),
            connection_timeout=10,
        ) as driver:
            print("[connect] 验证 Bolt 服务和身份认证。")
            driver.verify_connectivity()
            print("[connect] Bolt 服务连接和身份认证成功。")

            print("[query] 验证目标数据库可执行查询。")
            records, summary, keys = driver.execute_query(
                """
                RETURN
                    $username AS username,
                    $database AS database,
                    'not_checked' AS server_time,
                    'Neo4j connection successful' AS message
                """,
                username=username,
                database=database,
                database_=database,
            )

            if not records:
                raise RuntimeError("查询成功，但没有返回任何记录。")

            record = records[0]
            print("[query] 基础查询成功。")

            test_id = f"connection-test-{uuid4()}"

            print(f"[write] 创建测试节点，test_id={test_id}")
            create_records, _, _ = driver.execute_query(
                """
                CREATE (n:__ConnectionTest {
                    test_id: $test_id,
                    created_by: $username
                })
                RETURN n.test_id AS test_id
                """,
                test_id=test_id,
                username=username,
                database_=database,
            )

            if not create_records or create_records[0]["test_id"] != test_id:
                raise RuntimeError("测试节点写入后未返回预期 test_id。")

            print("[write] 测试节点写入成功。")

            print("[read] 查询测试节点。")
            read_records, _, _ = driver.execute_query(
                """
                MATCH (n:__ConnectionTest {test_id: $test_id})
                RETURN count(n) AS count
                """,
                test_id=test_id,
                database_=database,
            )

            if not read_records or read_records[0]["count"] != 1:
                raise RuntimeError("测试节点写入后无法读取。")

            print("[read] 测试节点读取成功。")

            print("[delete] 删除测试节点。")
            delete_records, _, _ = driver.execute_query(
                """
                MATCH (n:__ConnectionTest {test_id: $test_id})
                DETACH DELETE n
                RETURN count(*) AS deleted_count
                """,
                test_id=test_id,
                database_=database,
            )

            if not delete_records or delete_records[0]["deleted_count"] != 1:
                raise RuntimeError("测试节点删除结果异常。")

            print("[delete] 测试节点删除成功。")

            print("[cleanup] 确认测试节点已清理。")
            verify_delete_records, _, _ = driver.execute_query(
                """
                MATCH (n:__ConnectionTest {test_id: $test_id})
                RETURN count(n) AS count
                """,
                test_id=test_id,
                database_=database,
            )

            if not verify_delete_records or verify_delete_records[0]["count"] != 0:
                raise RuntimeError("测试节点删除后仍可查询到。")

            print("[cleanup] 测试节点清理确认成功。")

            print()
            print("=" * 60)
            print("Neo4j 连接与读写删除测试成功")
            print("=" * 60)
            print(f"当前用户    ：{record['username']}")
            print(f"当前数据库  ：{record['database']}")
            print(f"服务器时间  ：{record['server_time']}")
            print(f"服务器地址  ：{summary.server.address}")
            print(f"Neo4j版本   ：{summary.server.agent}")
            print(f"返回字段    ：{keys}")
            print("=" * 60)

    except AuthError as exc:
        print()
        print("=" * 60)
        print("Neo4j 身份认证失败")
        print("=" * 60)
        print("Bolt 服务可以连接，但用户名或密码不正确。")
        print(f"原始错误：{exc}")
        sys.exit(2)

    except ServiceUnavailable as exc:
        print()
        print("=" * 60)
        print("无法连接 Neo4j 服务")
        print("=" * 60)
        print("请检查 Neo4j 是否运行、Bolt 端口是否正确、URI 是否应为 bolt/neo4j 协议。")
        print(f"当前 URI：{uri!r}")
        print(f"原始错误：{exc}")
        sys.exit(3)

    except ConfigurationError as exc:
        print()
        print("=" * 60)
        print("Neo4j URI 配置错误")
        print("=" * 60)
        print(f"当前 URI：{uri!r}")
        print(f"原始错误：{exc}")
        sys.exit(4)

    except DatabaseError as exc:
        print()
        print("=" * 60)
        print("Neo4j 数据库访问失败")
        print("=" * 60)
        print(f"当前数据库名：{database!r}")
        print("请在 Neo4j Browser 中执行 SHOW DATABASES，确认该数据库存在。")
        print(f"原始错误：{exc}")
        sys.exit(5)

    except Neo4jError as exc:
        print()
        print("=" * 60)
        print("Neo4j 查询或写入失败")
        print("=" * 60)
        print(f"错误类型：{type(exc).__name__}")
        print(f"错误信息：{exc}")
        sys.exit(6)

    except Exception as exc:
        print()
        print("=" * 60)
        print("出现未预期错误")
        print("=" * 60)
        print(f"错误类型：{type(exc).__name__}")
        print(f"错误信息：{exc}")
        sys.exit(10)


if __name__ == "__main__":
    main()
