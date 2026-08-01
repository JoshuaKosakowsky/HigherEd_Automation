from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv


# Make repository-level imports work when this file is run directly.
REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from shared.insights.auth import exchange_sso_jwt
from shared.insights.client import InsightsClient


SQL_PATH = (
    REPO_ROOT
    / "query"
    / "insights_testing"
    / "spriden_sample.sql"
)

OUTPUT_PATH = (
    REPO_ROOT
    / "data"
    / "insights_api_test"
    / "spriden_sample.xlsx"
)


def get_required_environment_variable(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Required environment variable is missing: {name}"
        )

    return value


def build_client() -> tuple[InsightsClient, str]:
    """
    Build the client using a permanent API key when available.

    Until an API key is provisioned, prompt for a fresh SSO JWT
    and exchange it for a temporary session token.
    """

    environment = os.getenv(
        "INSIGHTS_ENV",
        "test",
    ).strip().upper()

    variable_prefix = f"INSIGHTS_{environment}"

    base_url = get_required_environment_variable(
        f"{variable_prefix}_BASE_URL"
    )

    database_id_text = get_required_environment_variable(
        f"{variable_prefix}_DATABASE_ID"
    )

    try:
        database_id = int(database_id_text)
    except ValueError as error:
        raise RuntimeError(
            f"{variable_prefix}_DATABASE_ID must be an integer."
        ) from error

    api_key = os.getenv(
        f"{variable_prefix}_API_KEY",
        "",
    ).strip()

    if api_key:
        return (
            InsightsClient(
                base_url=base_url,
                database_id=database_id,
                api_key=api_key,
            ),
            "API key",
        )

    print(
        "No Insights API key is configured.\n"
        "A temporary SSO session will be used for this run."
    )

    jwt_token = getpass(
        "Paste a freshly issued Ellucian Insights SSO JWT: "
    ).strip()

    session_token = exchange_sso_jwt(
        base_url=base_url,
        jwt_token=jwt_token,
    )

    return (
        InsightsClient(
            base_url=base_url,
            database_id=database_id,
            session_token=session_token,
        ),
        "temporary SSO session",
    )


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    client, authentication_method = build_client()

    print()
    print(f"Authentication: {authentication_method}")
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
    print(dataframe.to_string(index=False))
    print()
    print(f"Rows returned: {len(dataframe):,}")
    print(f"Excel output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()