# Automation Repository

This repository contains automation tools that help run repeatable work processes.

Most users only need to run the setup steps once. After setup, workflows can be started with simple shortcut commands.

---

## First-Time Setup

Open PowerShell in this folder and run:

```powershell
.\setup.ps1
```

This prepares the automation tools by creating the local Python environment and installing required packages.

---

## Set Up Credentials

Some workflows need a username and password for systems like Banner, BankMobile, or Cashnet.

Run the credential setup for each system you need.

Example for Banner:

```powershell
.\powershell\credentials\setup_credentials.ps1 -Target Banner
```

Example for BankMobile:

```powershell
.\powershell\credentials\setup_credentials.ps1 -Target BankMobile
```

Example for Cashnet:

```powershell
.\powershell\credentials\setup_credentials.ps1 -Target Cashnet
```

You will be asked to enter your username and password.

Credentials are saved securely on your computer using Windows Credential Manager. They are not saved in this folder.

---

## Set Up Shortcuts

Run:

```powershell
.\powershell\credentials\setup_profile.ps1
```

Then run:

```powershell
. $PROFILE
```

This loads the shortcut commands into your PowerShell window.

---

## Running a Workflow

After setup, you can run the FGIGLAC workflow with:

```powershell
banner.fgiglac
```

You can also run it directly with:

```powershell
.\launcher\run.fgiglac.ps1
```

---

## Useful Shortcuts

```powershell
open-auto
```

Moves PowerShell to this automation folder.

```powershell
start-setup
```

Runs the setup script again.

```powershell
banner.fgiglac
```

Runs the Banner FGIGLAC workflow.

---

## If Something Goes Wrong

Try running setup again:

```powershell
auto-setup
```

or:

```powershell
.\setup.ps1
```

If your password changed, rerun the credential setup:

```powershell
.\powershell\credentials\setup_credentials.ps1 -Target Banner
```

---

## Logs

Workflow logs are saved in the `logs` folder.

If a workflow fails, check the most recent log file or share it with the person supporting the automation.

## Set Up Daily Trusted Browser Session

Some workflows use a saved browser session so you do not have to complete 2FA every time.

Run:

```powershell
.\powershell\setup\setup_trusted_session.ps1 -System Banner -Browser edge
```

A browser window will open.

Log in normally, complete 2FA, and select “remember this device” if prompted.

When fully logged in, return to PowerShell and press Enter.

This saves the trusted browser session on your computer.