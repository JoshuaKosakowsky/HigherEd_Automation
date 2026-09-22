# Insights API proof of concept

This workflow tests native SQL access to the Ellucian Insights
TEST or PROD environment. It uses the shared client under `shared/insights` so
future workflows do not need to know whether authentication uses a permanent
Metabase API key or a temporary SSO session.

## Configuration

Department TEST and PROD addresses and database IDs are bundled in
`config/institutions/mines/insights.json`. Both the GUI and this command-line
proof of concept use that non-secret configuration, so employees do not need to
copy those values into `.env`. Both entry points reuse the same OS-vault session
when their environment, server, and database settings match.

TEST is the default. Use `--environment PROD` only when PROD access and the
specific query have been approved. `.env` remains optional for an API key or a
fully explicit alternate deployment; never commit `.env`, API keys, SSO JWTs,
session values, cookies, or credential-bearing SSO URLs.

The bundled Mines portal-first sign-in address is:

```dotenv
INSIGHTS_TEST_SSO_START_URL=https://my.mines.edu/app/UserHome
```

In the opened dedicated automation browser, sign in to MyMines normally. Follow your usual route to
Experience TEST (`https://experience-test.elluciancloud.com/comtemp`), then open
Insights TEST. You can enter the Experience TEST URL in the same browser after
signing in; new tabs opened there are also observed. Signing in through a
different, already-open personal browser window does not authenticate the
automation profile. The helper waits up to five minutes.

When locally overridden, the starting URL is separate from
`INSIGHTS_TEST_BASE_URL`, which must remain the Insights API host, not MyMines
or Experience. Capture still accepts a JWT
only at that Insights host's SSO endpoint; it does not capture MyMines tokens.
Use a stable starting URL without query strings, fragments, or credentials;
do not save a URL copied from the middle of an SSO redirect. The optional
`INSIGHTS_PROD_SSO_START_URL` is configured independently. Leaving either start
URL blank preserves the direct Insights `/auth/login` behavior.

If no API key is configured for the selected environment, the workflow reuses a
validated same-day Metabase session from Windows Credential Manager (Windows)
or Keychain (macOS). When no valid session exists, it opens a dedicated,
persistent Chrome automation profile on Windows and macOS and waits for the user
to complete the normal Ellucian SSO/2FA flow. The automation captures only the
JWT handoff to the configured Insights origin and exchanges the JWT in memory
for a Metabase session. The ordinary browser SSO request is not intercepted or
blocked; capture observes request events, including redirect hops. Whether the
tenant accepts that JWT for a subsequent session exchange must be tested live.
It does not enumerate or
export browser cookies, local storage, passwords, or browsing history.

The browser window closes after capture or failure, but its machine-local
profile persists local storage and persistent SSO cookies so the identity
provider can recognize the employee/device later. Session-only cookies still
end when the browser closes. No HAR, trace, screenshot, or JWT is
intentionally saved. DEBUG, PWDEBUG, and SSLKEYLOGFILE must be unset to prevent
diagnostic credential exposure.

All repository Playwright helpers using the same browser channel share one
profile. Windows Chrome uses
`%LOCALAPPDATA%\HigherEdAutomation\Playwright\Shared_Chrome`; macOS Chrome uses
`~/Library/Application Support/HigherEdAutomation/Playwright/Shared_Chrome`.
The profile is outside the repository and normal OneDrive project folder.
Edge remains an explicit fallback with a separate profile. Only one automation browser may use a profile at a
time. Never copy, sync, commit, or share it. Old system-specific profiles are
not imported or deleted automatically.

Only the resulting Metabase session is placed in the native OS credential vault.
Windows credentials use local-machine persistence, not enterprise roaming.
The code refuses other platform backends rather than falling back to plaintext.
The cache includes the environment, database, principal ID, and expiration
metadata, but never the SSO JWT. It is accepted only on the local calendar date
when it was created and is validated with `/api/user/current` before reuse.

Start with a non-sensitive connectivity check (no export):

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --smoke-test
```

On macOS, use your Python environment, for example:

```sh
python3 -m workflows.insights_api_test.run_insights_test --browser chrome --smoke-test
```

Install the repository's declared `playwright` and `keyring` dependencies in
that environment and have Chrome installed. Complete password/MFA prompts
yourself in the opened window. Never send tokens in chat or command arguments.

From the repository root, inspect safe connection metadata without executing
SQL:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --discover-only
```

Run the safe `STVTERM` reference-data sample and create the ignored Excel
output at `data/insights_api_test/stvterm_sample.xlsx`:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test
```

This sample returns at most ten Banner term-code rows and does not query or
export student records. The generated workbook is ignored by Git and should
remain on an approved local or institutional storage location.

To run the same proof of concept against PROD explicitly:

```powershell
.\.venv\Scripts\python.exe -m workflows.insights_api_test.run_insights_test --environment PROD
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
client builder refuses an expired entry and attempts revocation before a new
login. This is checked when building a client, not on every request of a
long-lived client. The vault entry itself does not automatically expire; the
server can expire or revoke the session earlier. To also
attempt cleanup automatically at the end of each day, install the current-user
Scheduled Task once:

```powershell
.\powershell\setup_insights_session_cleanup.ps1
```

The task runs at midnight with limited current-user permissions. If the
computer is asleep, it runs at the next available sign-in. This is best-effort:
the server ultimately controls session lifetime, and an offline computer cannot
contact Metabase to revoke a session.

No scheduled cleanup is installed automatically, and the Windows task does not
run on macOS. Use `--logout` when finished on the Mac. A failed revocation keeps
the cache entry available for a later retry. When switching to an API key, run
`--logout` explicitly to remove a previously cached session; API-key mode does
not read or modify the session vault. No request follows HTTP redirects with
API credentials. `--logout` revokes the Insights API session but does not clear
SSO cookies from the shared browser profile.

The workflow reports only the authentication method, principal ID,
administrator status, version, accessible database count, configured database
summary, row count, and output path. It does not print query rows or raw API
error bodies.

This is an interactive temporary bridge, not an unattended service account or
a way around institutional controls. Each person must sign in using their own
account and OS vault. Do not distribute your session to Jenny, Stanley, or a
shared job. Existing UI access does not establish institutional approval for
automation. The client accepts SQL; read-only enforcement must come from the
server/database permissions, not the filename or Python code. A successful
Insights query does not prove direct Banner API access or real-time warehouse
freshness.

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
