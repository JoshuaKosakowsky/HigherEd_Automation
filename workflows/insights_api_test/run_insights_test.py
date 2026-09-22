from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv

from shared.insights.auth import InsightsAuthenticationError, exchange_sso_jwt
from shared.insights.browser_auth import InsightsBrowserAuthenticationError
from shared.insights.client import InsightsAPIError, InsightsClient
from shared.insights.config import (
    InsightsConfigurationError,
    InsightsSettings,
    load_configured_settings,
)
from shared.insights.session_cache import InsightsCredentialError
from shared.insights.session_auth import (
    InsightsSessionError,
    build_authenticated_client,
    clear_cached_session,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


SQL_PATH = (
    REPO_ROOT
    / "query"
    / "insights_testing"
    / "stvterm_sample.sql"
)

OUTPUT_PATH = (
    REPO_ROOT
    / "data"
    / "insights_api_test"
    / "stvterm_sample.xlsx"
)


def acquire_manual_session(settings: InsightsSettings) -> str:
    jwt_token = getpass(
        "Paste a freshly issued Ellucian Insights SSO JWT: "
    ).strip()

    try:
        return exchange_sso_jwt(settings.base_url, jwt_token)
    finally:
        jwt_token = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the configured Ellucian Insights connection."
    )
    mode = parser.add_mutually_exclusive_group()
    parser.add_argument(
        "--environment",
        choices=["TEST", "PROD"],
        help="Insights environment (default: INSIGHTS_ENV or TEST).",
    )
    mode.add_argument(
        "--discover-only",
        action="store_true",
        help="Show safe connection metadata without running the SQL file.",
    )
    mode.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run SELECT 1 only, without student data or an output file.",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome"],
        default="chrome",
        help="SSO browser (default: Chrome; Edge is an explicit fallback).",
    )
    parser.add_argument(
        "--fresh-login",
        action="store_true",
        help="Revoke any cached session and perform a fresh SSO login.",
    )
    parser.add_argument(
        "--manual-jwt",
        action="store_true",
        help="Prompt invisibly for a JWT instead of opening the SSO browser.",
    )
    mode.add_argument(
        "--logout",
        action="store_true",
        help="Revoke and delete the cached session without running a query.",
    )
    return parser.parse_args()


def print_discovery(client: InsightsClient, settings: InsightsSettings) -> None:
    user = client.get_current_user()
    server = client.get_server_info()
    databases = client.list_databases()
    configured_database = next(
        (
            database
            for database in databases
            if database.id == settings.database_id
        ),
        None,
    )

    print(f"Environment: {settings.environment}")
    print(f"Metabase version: {server.version_tag or 'unknown'}")
    print(f"Authenticated principal ID: {user.id or 'unknown'}")
    print(f"Principal is administrator: {user.is_superuser}")
    print(f"Accessible databases: {len(databases)}")

    if configured_database is None:
        raise InsightsAPIError(
            "The configured database ID is not visible to the authenticated "
            "principal."
        )

    print(
        "Configured database: "
        f"{configured_database.name} "
        f"(ID {configured_database.id}, "
        f"engine {configured_database.engine or 'unknown'})"
    )


def main() -> None:
    arguments = parse_args()
    load_dotenv(REPO_ROOT / ".env")
    settings = load_configured_settings(environment=arguments.environment)

    if arguments.logout:
        removed = clear_cached_session(settings)
        print(
            "Cached Insights session revoked and removed."
            if removed
            else "No cached Insights session was found."
        )
        return

    if not settings.api_key and not arguments.manual_jwt:
        print(
            "A valid daily SSO session will be reused when available. "
            "Otherwise, a browser will open for login and 2FA."
        )

    acquire_session = (
        (lambda: acquire_manual_session(settings))
        if arguments.manual_jwt
        else None
    )
    client, authentication_method = build_authenticated_client(
        settings,
        browser=arguments.browser,
        force_login=arguments.fresh_login,
        acquire_session=acquire_session,
    )

    with client:
        print()
        print(f"Authentication: {authentication_method}")
        if arguments.smoke_test:
            dataframe = client.run_sql_file(
                SQL_PATH.with_name("connection_check.sql")
            )
            if dataframe.shape != (1, 1) or dataframe.iloc[0, 0] != 1:
                raise InsightsAPIError("The SELECT 1 check returned an unexpected result.")
            print(f"{settings.environment}: SELECT 1 succeeded; no student data queried or saved.")
            return
        print_discovery(client, settings)

        if arguments.discover_only:
            return

        print(f"SQL file: {SQL_PATH}")
        print("Running query...")
        dataframe = client.run_sql_file(SQL_PATH)

        OUTPUT_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        dataframe.to_excel(
            OUTPUT_PATH,
            index=False,
        )

        print()
        print(f"Rows returned: {len(dataframe):,}")
        print(f"Excel output: {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except (
        InsightsAuthenticationError, InsightsBrowserAuthenticationError,
        InsightsConfigurationError, InsightsCredentialError,
        InsightsSessionError, InsightsAPIError,
    ) as error:
        print(f"Insights: {error}", file=sys.stderr)
        raise SystemExit(1) from None
