# Insights API proof of concept

This workflow validates read-only native SQL access to the Ellucian Insights
TEST or PROD environment. It uses the shared client under `shared/insights` so
future workflows do not need to know whether authentication uses a permanent
Metabase API key or a temporary SSO session.

## Local configuration

Copy `.env.example` to `.env`. Keep `INSIGHTS_ENV=TEST` until PROD access has
been separately approved and configured. Never commit `.env`, API keys, SSO
JWTs, session values, cookies, or credential-bearing SSO URLs.

If no API key is configured for the selected environment, the workflow reuses a
validated same-day Metabase session from Windows Credential Manager. When no
valid session exists, it opens a dedicated Edge profile and waits for the user
to complete the normal Ellucian SSO/2FA flow. The automation captures only the
JWT handoff to the configured Insights origin, aborts that browser request, and
exchanges the JWT in memory for a Metabase session. It does not enumerate or
export browser cookies, local storage, passwords, or browsing history.

The dedicated browser profile is stored under the signed-in user's local
application-data directory, outside this repository. Like any normal browser
profile, it may retain SSO cookies so the identity provider can reduce repeated
login prompts. Treat that profile as sensitive and never copy or synchronize
it. The automation does not read those cookies; the browser uses them normally.

Only the resulting Metabase session is placed in Windows Credential Manager.
The cache includes the environment, database, principal ID, and expiration
metadata, but never the SSO JWT. It is accepted only on the local calendar date
when it was created and is validated with `/api/user/current` before reuse.

From the repository root, inspect safe connection metadata without executing
SQL:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --discover-only
```

Run the SQL file and create the ignored Excel output:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test
```

Force a fresh login and revoke the previous cached session:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --fresh-login
```

If browser capture is unavailable, retain the hidden manual-JWT fallback:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --manual-jwt
```

Revoke the Metabase session and remove it from Credential Manager:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --logout
```

Windows Credential Manager does not have native per-entry expiration. The
client refuses and revokes an entry after its creation date changes. To also
attempt cleanup automatically at the end of each day, install the current-user
Scheduled Task once:

```powershell
.\powershell\setup_insights_session_cleanup.ps1
```

The task runs at midnight with limited current-user permissions. If the
computer is asleep, it runs at the next available sign-in. This is best-effort:
the server ultimately controls session lifetime, and an offline computer cannot
contact Metabase to revoke a session.

The workflow reports only the authentication method, principal ID,
administrator status, version, accessible database count, configured database
summary, row count, and output path. It does not print query rows or raw API
error bodies.

## Request for IT / Insights administrators

Ask for a dedicated Metabase API key for this automation, assigned to a
least-privilege reporting group. The group should be able to view and run
native queries only against the required Insights warehouse. The warehouse's
underlying database credential—not merely the Metabase group—should be
read-only, because native SQL is ultimately constrained by that database
credential.

Ask IT to confirm separately for TEST and PROD:

- the base URL and database ID;
- whether API keys are supported in the Ellucian-managed tenant;
- the approved process for creating, storing, rotating, and revoking the key;
- permission to run native SQL through `POST /api/dataset`;
- the schemas/tables the reporting group may query;
- query timeout, row-limit, concurrency, and acceptable-use expectations;
- whether automation traffic requires an allow-listed network or service
  account; and
- the appropriate non-production dataset for validation without exposing
  student records.

The integration does not require Metabase administrator access, user/group
management access, database connection details, or direct credentials for the
warehouse.
