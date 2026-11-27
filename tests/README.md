# Tests and continuous integration

## Run locally

On a configured Windows workstation, run this from the repository root:

```powershell
.\tests\run_tests.ps1
```

The installed `test-automation` shortcut invokes the same script. It uses the
repository's `.venv` and runs Python unittest discovery followed by the Banner
term, fiscal-period, and report-filing PowerShell tests. Use synthetic fixtures;
normal tests must not require production credentials or live institutional data.

## GitHub Actions

`.github/workflows/ci.yml` defines the **CI** workflow. It runs on pushes,
pull requests targeting `main`, and manual requests through GitHub's Actions
tab. Pushing a branch with an open pull request can produce both a push run
and a pull-request run. Newer runs cancel older runs for the same workflow/ref.

Each run creates separate jobs on fresh GitHub-hosted Windows machines for
Python 3.11 (the Mines-provided version) and Python 3.12. Each job checks out
the tested revision, creates `.venv`, installs `requirements.txt`, checks
dependency compatibility, and calls the existing `tests/run_tests.ps1` entry
point through Windows PowerShell. Qt tests use the offscreen platform so GUI
interactions do not need a visible desktop. Both jobs run the complete existing
test command. A failure in one version does not cancel the other version's
checks. Passing runs do not establish support for every newer Python.

The optional refund and institutional-loan PostgreSQL test classes require
`REFUNDS_TEST_DSN` and skip when it is unset. This initial workflow does not
provision that synthetic database, so those classes remain skipped. Never
configure that test variable with a production database.

CI does not run the interactive `setup.ps1`, install employee shortcuts or
scheduled tasks, download Playwright browsers, or sign in to Banner, Insights,
or SFTP. Tests substitute synthetic data and mocked integrations. Native
workstation setup, authentication, live extraction and business acceptance
still need separate verification. Nothing is installed on staff laptops by CI.

The workflow needs only read access to repository contents and no institution
secrets. The two GitHub actions are pinned to release commit hashes; update the
hashes and version comments together when intentionally upgrading them.

## Read a result

After the workflow file is committed and pushed, open the repository's
**Actions** tab, select **CI**, and open a run. The jobs are named
**Windows tests (Python 3.11)** and **Windows tests (Python 3.12)**.
Expand a failed step to see its output.

- A failure during installation indicates a dependency or runner problem.
- A test failure identifies the test and its assertion or traceback.
- A successful run means the configured checks passed for that tested revision.
  It does not certify all business rules or production integrations.

For a transient runner/download problem, use **Re-run failed jobs**. For a code
or test problem, fix it and push a new revision. The manual **Run workflow**
button becomes available once the workflow is on the default branch, subject
to repository Actions settings. Hosted runs consume the account's applicable
GitHub Actions allowance; they do not consume staff laptop resources.

## CI checks and staff releases

This workflow reports results; it does not deploy, merge, or configure repository
rules. The desktop updater currently follows its configured upstream and does
not inspect CI results. A failed check on an existing `main` commit therefore
does not by itself prevent that commit being offered by the updater.

For the protected release path, configure a GitHub branch rule/ruleset for `main`
requiring pull requests and both successful **Windows tests (Python 3.11)** and
**Windows tests (Python 3.12)** checks, with bypass permissions reviewed.
Adding the 3.11 matrix job does not automatically add it to an existing branch
rule: let it run, then select its name in the required checks. Availability
depends on repository visibility and the GitHub plan.
Requiring another person's approval is a separate policy choice.

### Working on Development

Keep `Development` as a permanent branch. Staff clones follow `main`, and an
administrator can switch a test installation to `Development` in **App updates**.
Push and test individual development commits with the current `APP_VERSION`.
Record the Git revision from **App updates** or the startup log when reporting a
test result, because several development commits can share the same version.

When a tested group is ready for staff, increment `APP_VERSION` once for the
whole release. Choose patch, minor or major according to the combined changes.
Open a PR from `Development` to `main`, review the final diff, and wait for both
Windows checks. Choose **Create a merge commit** to preserve the tested commit
history. Leave `Development` in place and bring it up to the released `main`
with a fast-forward. If both branches have advanced, merge `main` into
`Development` without rewriting either branch, and verify the result.

For this workflow, enable merge commits and allow them on `main` by leaving
linear history disabled. Keep automatic branch deletion from removing
`Development` after promotion by turning it off or protecting `Development`
against deletion. Preserve the PR and Windows check requirements for the
protected release path. The repository owner manages these settings.

### First selector release

Release 0.34.0 through a temporary feature branch PR targeting `main`, with both
Windows checks passing before merge. Once it lands, fast-forward `Development`
to the new `main` before switching a workstation to it. Both branches then have
the selector. Verify on the work PC with its usual Windows login and shortcut.

1. On `main`, use **App updates** to install 0.34.0, then close and reopen.
2. As an app administrator, switch to `Development` and reopen. Confirm the
   branch and running Git revision.
3. Publish a development-only fix to `Development`. Check for and install it,
   then reopen and verify the revision changed. A separate `main` installation
   should stay at the stable revision and should show no switch control for staff.
4. Switch the work PC back to `main` while `Development` is ahead. Reopen and
   verify the stable revision and that ordinary updates follow `main` again.
   Rerun `setup.ps1` before reopening whenever the app reports setup changes.

GitHub Actions documentation:
[Understanding GitHub Actions](https://docs.github.com/en/actions/get-started/understand-github-actions).
