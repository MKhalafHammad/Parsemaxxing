# Setup

Every step from an empty machine to an approved add-on, then configuration, usage, tests and troubleshooting. Steps 1 to 7 were tested on a fresh Ubuntu 26.04 VM with v1; the Phase 12 additions (Docker secrets, the KEK, settings import, backups, the `https` profile) and the Phase 13 additions (the first admin, sign-in, MFA, API tokens) are described from the code and its tests. The commands are for Ubuntu; on other systems, install the same tools your usual way.

A first-run setup wizard in the web UI is **planned** (Phase 15). Until then, setup is the command line below.

**Contents**

- [What you need](#what-you-need)
- [Step 1: Install the tools](#step-1-install-the-tools)
- [Step 2: Let your user run Docker](#step-2-let-your-user-run-docker)
- [Step 3: Get the code and create `.env`](#step-3-get-the-code-and-create-env)
- [Step 4: Add the Splunk CIM add-on](#step-4-add-the-splunk-cim-add-on)
- [Step 5: Start everything](#step-5-start-everything)
- [Back up the KEK](#back-up-the-kek)
- [Create the first admin](#create-the-first-admin)
- [API token for the CLI](#api-token-for-the-cli)
- [Step 6: Start the first run](#step-6-start-the-first-run)
- [Step 7: Review and approve](#step-7-review-and-approve)
- [Messages that are safe to ignore](#messages-that-are-safe-to-ignore)
- [Upgrading from Parsewright (v1.0.0)](#upgrading-from-parsewright-v100)
- [Licence](#licence)
- [Real log retention](#real-log-retention)
- [Stop, restart or reset](#stop-restart-or-reset)
- [Configuration](#configuration)
- [Settings and secrets](#settings-and-secrets)
- [Backups](#backups)
- [HTTPS](#https)
- [Usage](#usage)
- [Running tests and security checks](#running-tests-and-security-checks)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## What you need

| Item | Requirement |
| --- | --- |
| Operating system | Linux or macOS. On Windows, use WSL2 |
| CPU | x86-64, 4 cores recommended. The Splunk image is x86-64, so on Apple Silicon it runs under emulation and is slower |
| Memory | At least 8 GB of RAM free for Docker (4 GB is the bare minimum) |
| Disk | At least 40 GB free, for the images, Splunk's data and the builds. Splunk pauses indexing when free disk drops below 5 GB |
| Tools | Docker Engine 24+, Docker Compose v2.20+, `git`, `make`, `curl`, Python 3.10+ ([Step 1](#step-1-install-the-tools)) |
| Meta Model API key | From your Meta developer account. One run uses about 50k tokens |
| Splunkbase account | Free, to download the CIM add-on ([Step 4](#step-4-add-the-splunk-cim-add-on)) |
| Internet access | To download the images and to reach the Meta Model API |

For development you also need Python 3.12+ and Node 24, plus [gitleaks](https://github.com/gitleaks/gitleaks) and [semgrep](https://semgrep.dev/) for `make security`.

If you added disk to a VM, check that the system can use it: `df -h /` should show the new size.

## Step 1: Install the tools

Skip this step if `docker --version` and `docker compose version` already show the versions above.

```bash
sudo apt update
sudo apt install -y git make python3 curl
curl -fsSL https://get.docker.com | sudo sh
```

For other systems, see [Install Docker Engine](https://docs.docker.com/engine/install/); on macOS or Windows, Docker Desktop includes Compose.

Check the versions:

```bash
docker --version          # 24 or later
docker compose version    # v2.20 or later
python3 --version         # 3.10 or later
```

## Step 2: Let your user run Docker

Run this once, then **log out and back in** so the change applies:

```bash
sudo usermod -aG docker $USER
```

Check it with `docker ps`, which must work without `sudo`.

**Why this matters:** the app itself doesn't depend on this group, but every `make` command that calls Docker does. Without it, `make up` stops with `permission denied while trying to connect to the docker API`.

If you can't change the group, use this form of the command in Step 5, which runs only Docker through `sudo`:

```bash
DOCKER="sudo docker" make up
```

`make down` and `make logs` always use plain `docker`, so in that case run `sudo docker compose down` and `sudo docker compose logs -f` instead.

> [!WARNING]
> Never run `sudo make up`. It stops with a message, because running the setup as root would leave `.env` owned by root, and your own commands would then fail with `open .env: permission denied`.

Members of the `docker` group have root-level access to the machine, so add only users you trust.

## Step 3: Get the code and create `.env`

```bash
git clone https://github.com/MKhalafHammad/Parsemaxxing.git
cd Parsemaxxing
make env
```

`make env` creates `.env` and generates every password. **It then ends with an error, and that is expected at this point:**

```text
created .env from .env.example
generated: SPLUNK_PASSWORD, POSTGRES_PASSWORD, POSTGRES_APP_PASSWORD
LLM_API_KEY is still a placeholder: set your Meta Model API key in .env
make: *** [Makefile:18: env] Error 2
```

`.env` was created correctly. The message is only a reminder to add your key, so open `.env` and set it:

```bash
nano .env        # set LLM_API_KEY=<your key>, then save
```

Nothing else needs a value: the passwords are generated, and the Splunk tokens are created in Step 5. Never commit `.env`.

`.env` holds bootstrap values: what the stack needs before the engine can read its settings store (the PostgreSQL connection, ports, the Splunk container's licence lines and admin password). The v1 runtime keys (`LLM_*`, `SPLUNK_HOST`, `PARSEMAXXING_TEST_INDEX` and the limits) still work there as read-only overrides, and so do the secrets (`LLM_API_KEY`, `SPLUNK_SEARCH_TOKEN`, `SPLUNK_DEPLOY_TOKEN`): set and not empty, they win over the vault ([Settings and secrets](#settings-and-secrets)). [.env.example](../.env.example) explains each line.

## Step 4: Add the Splunk CIM add-on

The CIM stage checks events against Splunk's Common Information Model data models, so Splunk needs this add-on. It is free, but Splunk licenses it, so it can't be included in this repository.

1. Sign in to Splunkbase with a free account and download [Splunk Common Information Model (CIM)](https://splunkbase.splunk.com/app/1621). Parsemaxxing's checks are pinned to version **8.7.0**.
2. Copy the `.tgz` into `lab/`, keeping its name:
   ```bash
   cp ~/splunk-common-information-model-cim_870.tgz lab/
   chmod 644 lab/*.tgz
   ```
   If you downloaded it on another computer, copy it to the server first:
   ```bash
   scp splunk-common-information-model-cim_870.tgz <user>@<server>:~/Parsemaxxing/lab/
   ```
3. Check that `ls lab/*.tgz` shows exactly one file. It must be a regular file, not a link.

> [!WARNING]
> **If you skip this step, setup stops partway.** `make up` starts Splunk and PostgreSQL, then fails at "preparing Splunk" with:
>
> `FAILED: the CIM add-on is not installed; put exactly one CIM package (a regular file, not a link) in lab/`
>
> The engine and the web UI don't start, and no Splunk tokens are created. To recover, add the file and run `make up` again. You don't need to wipe anything. The same message appears if `lab/` holds two packages.

## Step 5: Start everything

```bash
make up
```

This takes about 15 minutes the first time, mostly Splunk's first start. Always use `make up` rather than `docker compose up`, because it also prepares Splunk:

1. It creates `.env` if missing, and the Docker secrets in `secrets/` if missing: the KEK (`secrets/pmx_kek`) and the two database passwords, each owned by uid 10001 with mode 0400, and `secrets/pmx_proxy_hop` (the `https` proxy's header secret), owned by uid 1000 (the web container's user) with mode 0400. `make secrets` does the same on its own. It never overwrites one.
1. It starts Splunk and PostgreSQL and waits until they are healthy.
2. It creates the `pmx_test` index and three least-privilege service accounts (search, deploy, drift).
3. It installs the CIM add-on, restarts Splunk, and points the add-on's index macros at `pmx_*`.
4. It creates one fresh token per account and writes them to `.env` without printing them.
5. It builds and starts the engine and the web UI.

Success ends with:

```text
Parsemaxxing is up.
  UI:          http://localhost:3000
  Splunk Web:  http://localhost:8000  (user admin, password SPLUNK_PASSWORD in .env)
First run:     make first-run
```

While no admin account exists, it also prints:

```text
Setup needed: no admin account exists yet.
  1. make setup-token   (prints a one-time token, valid 60 minutes)
  2. open http://localhost:3000 and create the first admin with that token
```

Do that now: [Create the first admin](#create-the-first-admin). `make up` is safe to run again at any point, and it continues from where it stopped.

## Back up the KEK

**`secrets/pmx_kek` is the key-encryption key (KEK) of the vault. Losing it loses every secret stored in the vault (the LLM key and the Splunk tokens): nothing can decrypt them again. Back it up now, to somewhere off this server.**

**The file is owned by uid 10001 (the containers' user) with mode 0400, so your own user cannot read it. Print it with `sudo cat secrets/pmx_kek` and store the one line in a password manager or an offline place away from the server. Never put it in `.env`, the repository or a backup of the database.**

A backup of the database without the KEK cannot open the secrets in it, and the KEK without a database backup holds nothing; keep them apart.

Rotating the KEK (the engine must be stopped, and the new KEK must be written on the host):

```bash
docker compose stop engine
docker compose --profile cli up -d postgres-cli          # PostgreSQL on 127.0.0.1 for the host CLI
sudo sh -c 'umask 077; openssl rand -base64 32 > secrets/pmx_kek.new'
sudo PARSEMAXXING_KEK_FILE=secrets/pmx_kek .venv/bin/parsemaxxing secrets rotate-kek --new-kek-file secrets/pmx_kek.new
sudo mv secrets/pmx_kek secrets/pmx_kek.old && sudo mv secrets/pmx_kek.new secrets/pmx_kek
make secrets && make up                                   # hands the new file to uid 10001, mode 0400
```

`rotate-kek` rewraps every data key in one transaction; a running engine keeps the old KEK and is refused afterwards. Back up the new KEK as above. Keep `secrets/pmx_kek.old` until the engine starts cleanly, then delete it (`sudo shred -u secrets/pmx_kek.old`).

A first engine start against an empty vault adopts whatever KEK it is given, so if you restore a database onto a new server, put the matching KEK in `secrets/pmx_kek` before the first `make up` there.

## Create the first admin

There are no default accounts. The first admin is created with a one-time setup token.

1. Run `make setup-token`. It prints a new token, valid for 60 minutes and usable once. Every run of it replaces the previous token. The engine also keeps the token in `/app/.runs/setup-token` inside its container (mode 0600) and logs only that path.
2. Open http://localhost:3000. With no admin yet, the UI opens the setup page.
3. Paste the token, choose a user name and a password (12 to 128 characters; common passwords are refused), and create the admin.
4. Enrol MFA: add the key shown on the page to an authenticator app (there is no QR code yet, Phase 15), then enter the 6-digit code. Admins must use MFA by default.
5. **Save the 10 recovery codes now, somewhere off this server (a password manager).** Each works once, in place of an authenticator code. They are shown only once.

Use Chromium, Chrome, Edge or Firefox on this machine. They treat `http://localhost` as a secure context, so the `__Host-pmx_session` cookie works over plain http. Safari does not keep it; use the [`https` profile](#https) with Safari.

Other users: an admin adds them under **Users** (`/settings/users`) with a temporary password. Each user manages their own password, MFA, recovery codes and sessions under **Account security** (`/me/security`). The **Audit log** (`/settings/audit-log`) lists every sign-in, failure, lockout, MFA, user, role and token change, approval, rollback and kill-switch use, with the client IP; admins and viewers can read it, nobody can edit it.

**Lost access** (forgotten password, or lost authenticator and recovery codes): someone with the database owner credentials (`POSTGRES_PASSWORD` in `.env`) runs the break-glass reset on the host, with the `cli` profile up:

```bash
docker compose --profile cli up -d postgres-cli
.venv/bin/parsemaxxing admin reset <user name>
```

It asks for a new password twice without echo, clears MFA (the user enrols again at the next sign-in), enables and unlocks the account, revokes all of its sessions and API tokens, and writes an audit row. Reset MFA and Unlock from the Users screen are planned (Phase 15).

## API token for the CLI

`run`, `update`, `approve`, `reject`, `promote`, `rollback` and `kill` go through the engine API with an API token, so they get the same role checks and audit rows as the UI. `run`, `update` and `promote` also need the engine running (`make up`, or `parsemaxxing serve` and `parsemaxxing worker`). `run --local` uses neither the API nor PostgreSQL.

1. In the UI, open **API tokens** (`/settings/api-tokens`) and create a token: a name (for example `cli`), the role `admin` (these commands need it), and an expiry of 1 to 90 days.
2. Copy the `pmxt_...` value. It is shown once.
3. Give it to the CLI in one of two ways. Never put it on the command line or in `.env`:
   - a file only you can read: `install -m 600 /dev/null ~/.pmx-token`, paste the token into it with an editor, then pass `--token-file ~/.pmx-token` (the file must be mode 0600 or 0400 and not a link);
   - or `export PARSEMAXXING_API_TOKEN=<your token>` in your shell.

The CLI talks to `PARSEMAXXING_API_URL` (default `http://127.0.0.1:8080`). Plain http is allowed only for `localhost`, `127.0.0.1`, `::1` or `engine`; any other host needs https. A token stops working when it expires, when it is revoked, and when its owner's password or role changes or the owner is disabled or reset. A token never has a higher role than its owner has now.

`make first-run` and the `demo/` scripts send the token from `PARSEMAXXING_API_TOKEN`: `export PARSEMAXXING_API_TOKEN=$(cat ~/.pmx-token)` first.

## Step 6: Start the first run

Sample logs come with the repository, in `engine/parsemaxxing/generator/fixtures/`. All of them are synthetic, with 300 events each:

| File | Format |
| --- | --- |
| `acme_vpn.json` | JSON (a good first run) |
| `acme_fw.log` | key=value |
| `acme_ssh.log` | syslog |
| `acme_proxy.csv` | CSV |

Ignore the `.manifest.json` files: they are answer keys, and you don't need to upload them.

1. Open http://localhost:3000 and click **New run**.
2. Choose `engine/parsemaxxing/generator/fixtures/acme_vpn.json` as the log file, then click **Start run**. Vendor, product and timezone are optional.
3. Check what the Profiler found on the profile review screen, then click **Confirm profile**.
4. Watch the agents work. Each attempt is deployed to Splunk and checked. The run takes a few minutes and stops at **Awaiting approval**.

**Or from the terminal:** `.venv/bin/parsemaxxing run engine/parsemaxxing/generator/fixtures/acme_vpn.json --token-file ~/.pmx-token` ([API token for the CLI](#api-token-for-the-cli)). `make first-run` uses the same token from `PARSEMAXXING_API_TOKEN`. Uploading the same log twice opens the existing run.

## Step 7: Review and approve

A human approves every add-on before it is promoted, so this last step is yours. Approve, reject and New run need the `admin` role; viewers see them disabled with "Admin only".

1. Open the run's page from Step 6, or start at http://localhost:3000.
2. Review raw vs parsed events and the configuration.
3. Click **Approve** and confirm.

The run ends as `done`, and the add-on appears in the TA registry.

Splunk Web is at http://localhost:8000 (user `admin`, password `SPLUNK_PASSWORD` from `.env`).

> [!IMPORTANT]
> **The web UI and Splunk Web open only on the machine running Parsemaxxing, not from another machine.** This is a security choice: sign-in and roles are built (Phase 13), but exposure beyond localhost waits for the Phase 14 hardening, so every port is bound to `127.0.0.1`, and the UI accepts only `localhost:3000` and `127.0.0.1:3000` (plus the `https` profile's host name, [HTTPS](#https)). Use a browser on that same machine.

## Messages that are safe to ignore

| Message | When | Why it's fine |
| --- | --- | --- |
| `LLM_API_KEY is still a placeholder` and `make: *** [Makefile:18: env] Error 2` | `make env`, before you set the key | `.env` was created. Set the key ([Step 3](#step-3-get-the-code-and-create-env)) |
| `unhealthy` in `docker compose ps` | While Splunk starts or restarts | `make up` keeps waiting, and it clears once Splunk is ready. It's a problem only if it lasts more than 15 minutes |
| A failed attempt in a run | During a run | That is the fix loop: Splunk's evidence goes back to the agent, which tries again. Each stage gets up to 5 attempts |
| `(already known)` after the job id | `make first-run` again | The same log already has a run, so the script follows that run instead of starting another |

## Upgrading from Parsewright (v1.0.0)

1. Stop the old stack, keeping its data: `docker compose -p parsewright down` (never add `-v`).
2. In `.env`, rename every `PARSEWRIGHT_*` key to `PARSEMAXXING_*` and set `PARSEMAXXING_TEST_INDEX=pmx_test`. The engine refuses to start while an old key is set, and names the new one.
3. Run `make up`. It backs up the old `parsewright_*` volumes into `backups/`, copies them into the new `parsemaxxing_*` volumes, and leaves the old ones in place. The database migration renames the app role to `parsemaxxing_app`. The backup holds your v1 runs, so it can contain real log samples: delete `backups/v1-volumes-*` once the upgrade works, and within 30 days at most.
4. Add-ons you already built keep their `TA-parsewright-*` names and can still be updated and rolled back. New add-ons are named `TA-parsemaxxing-*`. The old `pw_test` index is left alone; remove it by hand when you no longer need it.
5. `make up` also created `secrets/` with a new KEK: [back it up](#back-up-the-kek). Your v1 `.env` keeps working; to move its values into the settings store and its secrets into the vault, see [Settings and secrets](#settings-and-secrets).

## Licence

Parsemaxxing is source-available, not open source. Versions up to and including v1.0.0 (released as Parsewright) are under the MIT License and stay that way. Everything after v1.0.0, including v2, is under the [PolyForm Shield License 1.0.0](../LICENSE): you may use, change and run it for any purpose, including inside your company or as an MSSP serving your own clients, but not to offer a product or service that competes with it, paid or free. Add-ons it generates for you are yours. The name and logo are covered by [TRADEMARKS.md](../TRADEMARKS.md), and third-party components keep their own licences ([THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)).

## Real log retention

Planned (Phase 21, design 7.19). Today nothing is deleted on a schedule: use synthetic logs, or remove real samples and their jobs yourself.

When it lands: real samples (uploaded or pulled from Splunk), their copies in the `pmx_` test index, raw lines in evidence, reports and transcripts, and masking maps are deleted 30 days after the job ends by default. An admin can shorten this per client down to 0 days; nothing is kept longer than 30 days. Job metadata, ledger events, check results and numbers, add-on versions and each version's masked regression set stay.

**Do not keep backups longer than 30 days**, so real logs in them age out too. `make backup` and `parsemaxxing backup` delete their own backups older than 30 days in the backup folder at each run; copies you made elsewhere are yours to delete ([Backups](#backups)).

## Stop, restart or reset

```bash
make down                # stop the stack; all data is kept
make up                  # start it again
make logs                # follow the logs
docker compose down -v   # stop and DELETE all Splunk and PostgreSQL data
```

To start from nothing, run `docker compose down -v`, delete the folder, and go back to [Step 3](#step-3-get-the-code-and-create-env). Save your CIM `.tgz` first. Deleting the folder also deletes `secrets/`, including the KEK: the new stack gets a new one, and the old vault's secrets are gone with the old database.

**Without Docker, against your own Splunk** (the lab setup): follow [docs/lab-findings.md](lab-findings.md), "Lab setup", set `SPLUNK_HOST`, `SPLUNK_PORT` and the tokens in `.env`, then `make setup` and `.venv/bin/parsemaxxing serve`. `make setup` needs Docker running even here, because `make secrets` hands the secret files to uid 10001 through a throwaway container. An engine on the host cannot read that KEK, so point `PARSEMAXXING_KEK_FILE` at a KEK file your own user owns (mode 0400, made with `umask 077; openssl rand -base64 32 > <file>`), and back that file up as above.

## Configuration

Bootstrap values live in `.env`; runtime settings in the settings store and secrets in the vault ([Settings and secrets](#settings-and-secrets)). [.env.example](../.env.example) documents each variable: what it is, whether it is required and where to get it. Docker Compose reads `.env` and refuses to start if a required value is missing. The KEK and the database passwords the containers use are Docker secrets in `secrets/`, never in `.env`.

| Docker Compose profile | Turn on with | Adds |
| --- | --- | --- |
| `cli` | `docker compose --profile cli up -d`, or `COMPOSE_PROFILES=cli` in `.env` | PostgreSQL on `127.0.0.1:${POSTGRES_PORT}` (default 55432) for the CLI on the host. Without it PostgreSQL is not published at all |
| `https` | `COMPOSE_PROFILES=https` in `.env` | A Caddy reverse proxy with TLS and HSTS in front of the web UI ([HTTPS](#https)) |

Both together: `COMPOSE_PROFILES=cli,https`.

**Using a self-hosted Muse Spark Open (on-prem mode).** Run Muse Spark Open behind an OpenAI-compatible endpoint inside your network. Then point Parsemaxxing at it:

```bash
LLM_BASE_URL=https://llm.example.com/v1
LLM_MODEL=<model name your server exposes>
LLM_API_KEY=<key your server expects, or any placeholder if none>
```

Nothing else changes, and sample logs never leave your network. Put the key in `LLM_API_KEY`, never in the URL: a base URL with a user name or password (`https://user:pass@...`) is refused. If you already imported your `.env` into the settings store, run the import again after the change ([Settings and secrets](#settings-and-secrets)).

**Serving the UI on the network, outside Docker.** Start the UI with `HOSTNAME=0.0.0.0` (set it explicitly: shells often set `HOSTNAME` to the machine's name) and add the server's address to `ALLOWED_HOSTS` and `WEB_ORIGINS` (see the note at the end of [.env.example](../.env.example)), then open the port in the server's firewall. With firewalld, `sudo firewall-cmd --add-port=3000/tcp --permanent` changes only the saved rules: run `sudo firewall-cmd --reload` to apply them. Every route needs a sign-in, but exposure beyond localhost is not supported before Phase 14, and over plain http on a host name other than `localhost` browsers drop the `__Host-` session cookie: use https there.

## Settings and secrets

The engine reads its runtime settings (LLM endpoint and model, Splunk host and port, test index, budgets, ingest caps, backup recipient) from the settings store in PostgreSQL, and its secrets (the LLM key, the Splunk search and deploy tokens) from the vault, encrypted with AES-256-GCM under the KEK. Settings are read when a process starts: a change applies after a restart. There is no settings screen yet (Phase 15, **planned**); today the store is filled once from your v1-style `.env`:

```bash
docker compose --profile cli up -d postgres-cli     # PostgreSQL on 127.0.0.1 for the host CLI
sudo PARSEMAXXING_KEK_FILE=secrets/pmx_kek .venv/bin/parsemaxxing settings import-env --dry-run
sudo PARSEMAXXING_KEK_FILE=secrets/pmx_kek .venv/bin/parsemaxxing settings import-env
```

`sudo` is needed only to read the KEK (owned by uid 10001). The import shows a diff (secret values are never shown), is safe to run again (a value already stored is "unchanged"; a changed secret is replaced), and ends with the variables that can now be removed from `.env`. A variable that stays in `.env` and is passed to the engine overrides the stored setting and shows as "managed by environment".

**Which secret is used.** `LLM_API_KEY`, `SPLUNK_SEARCH_TOKEN` and `SPLUNK_DEPLOY_TOKEN` work like the other overrides: set and not empty in the engine's environment, the variable wins over the vault; empty or unset, the vault value is used. The Docker stack passes them from `.env`. Each `make up` deletes the old Splunk tokens in Splunk and writes new ones (valid 7 days) into `.env`, so the engine always gets the current ones; you do not need to run the import again after `make up`.

To keep the LLM key only in the vault, remove `LLM_API_KEY` from `.env` (or leave it empty) after the import; `make up` then warns and goes on, and runs fail if the vault has no key either. A value in `.env` sits in the engine container's environment, where `docker inspect` and `/proc` can show it.

A setup wizard that lists the removable `.env` keys is **planned** (Phase 15). `SPLUNK_DRIFT_TOKEN` is no longer read by the engine; the drift pipeline (Phase 22) will use it.

**Ledger check.** Every ledger row is chained to the one before by SHA-256. With the `cli` profile up:

```bash
.venv/bin/parsemaxxing ledger head                              # prints <id>:<hash>; keep it off the server
.venv/bin/parsemaxxing ledger verify --expect-head <id>:<hash>   # exit code 5 means a problem
```

`verify` reports edited, removed or moved rows. A removed tail is detectable only against a head recorded earlier, so record the head now and then (every backup records it too). A database superuser who recomputes the whole chain after your last recorded head is not detected.

## Backups

Backups are encrypted with [age](https://age-encryption.org/) to a public key; the private key never lives on the server. Make the key pair on another machine:

```bash
age-keygen -o pmx-backup.key        # keep this file off the server; it prints the public key (age1...)
```

| Command | Backs up | Recipient (public key) from |
| --- | --- | --- |
| `make backup` | `pg_dump` of the database, piped into `age` in a container with no network, written to `backups/pmx-<UTC time>.dump.age` (folder 0700, file 0600) | `secrets/backup_recipients.txt` (yours to create and read), one `age1...` key per line, or the file named by `PMX_BACKUP_RECIPIENTS` |
| `parsemaxxing backup [--out-dir backups]` (engine CLI, with the `cli` profile up) | The same dump, from the host | The setting `backup.age_recipient`, or `PARSEMAXXING_BACKUP_RECIPIENT` |

`make up` and `make secrets` change only their own four files in `secrets/` (`pmx_kek`, `postgres_password`, `postgres_app_password`, `pmx_proxy_hop`); `backup_recipients.txt` stays yours.

Each backup gets a `<backup>.sha256` file beside it (0600). Line 1 is in `sha256sum` format (the SHA-256 of the encrypted file and its name), line 2 is `ledger-head <id>:<hash>`, the newest ledger row at backup time. Keep the two together: a restore refuses a backup without its checksum file, or one that does not match it. Someone who can rewrite both files can change the recorded head too, so also keep a head off the server ([Ledger check](#settings-and-secrets)). The backup tools give `pg_dump`, `pg_restore` and `age` only a minimal environment (`PATH`, `HOME`, `LANG` and the `PG*` connection values), never the engine's other variables.

Restore (replaces every row in the database; stops the engine and the UI first; type `RESTORE` to confirm):

```bash
make restore FILE=backups/pmx-<UTC time>.dump.age IDENTITY=/path/to/pmx-backup.key
make up
```

`make restore` prints the recorded head; after `make up`, check the restored ledger with `.venv/bin/parsemaxxing ledger verify --expect-head <id>:<hash>` (`cli` profile up). On a fresh database volume, run `docker compose run --rm migrate` first, so the app role exists. `make restore-test` runs the whole round trip in a separate compose project and leaves your stack alone; CI runs it on every pull request.

`parsemaxxing restore <file> --identity <key> --target-dsn <dsn> --yes` does the same from the host CLI and then verifies the restored ledger against the recorded head.

What a backup does not hold: the KEK ([back it up separately](#back-up-the-kek)) and the add-on package store (**planned**, Phase 17b). **Do not keep backups longer than 30 days**; both backup commands delete their own backups (and `.sha256` files) older than 30 days in the backup folder after each new one.

## HTTPS

The optional `https` profile puts Caddy in front of the web UI with TLS and HSTS (`max-age=31536000`). Set in `.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `COMPOSE_PROFILES` | unset | `https` turns the proxy on |
| `PMX_PUBLIC_HOST` | `localhost` | The host name the browser uses; the web UI accepts it with and without the port |
| `HTTPS_PORT` | `8443` | The published port |
| `HTTPS_BIND` | `127.0.0.1` | The host address it listens on. Sign-in is built (Phase 13), but exposure beyond localhost waits for the Phase 14 hardening, so `make up` refuses any address other than loopback unless you also set `PMX_ALLOW_UNAUTHENTICATED_NETWORK=yes` in your shell to accept that risk |
| `PMX_TLS` | `internal` | `internal` (Caddy's own CA, kept in the `caddy-data` volume; browsers warn until you trust it) or `/certs/<cert>.pem /certs/<key>.pem` for your own certificate in `./certs` |

Then `make up` and open `https://<PMX_PUBLIC_HOST>:8443`. The engine and the web UI accept state changes only from the origins docker-compose puts in `WEB_ORIGINS` (`http://localhost:3000`, `http://127.0.0.1:3000` and `https://<PMX_PUBLIC_HOST>` with and without `:8443`). Caddy sends the `pmx_proxy_hop` secret as `X-Pmx-Hop` and replaces any value a client sends, so the web UI passes the client's address on to the engine (for lockout per IP and the audit log) only for requests that came through Caddy.

## Usage

**Web UI** (http://localhost:3000)
1. **New run:** upload a sample log from one source (JSON, key=value, syslog or CSV; at least 50 events, at most 10 MB). That is all that is needed; vendor, product and timezone are optional. Or choose a promoted TA to update it for a new log format.
2. **Profile review:** confirm or correct what the Profiler found (vendor, product, sourcetype, timezone), with field coverage shown. Skippable, except when the timestamps carry no timezone and none was given: nothing in the file can prove which zone they are in, so the run asks.
3. **Run workspace:** the "Now" banner names the agent at work; the phase rail opens any phase and attempt (`/runs/<job>?phase=extraction&attempt=2`). Each attempt shows the proposal, the guardrail gate's verdict, Splunk's checks (expected vs actual, failing events) and what changed since the previous attempt. The activity feed is grouped by phase and attempt.
4. **Approval report:** CIM scores, attempts per phase and holdout; how the run was validated (against known answers, or mechanically); the decisions the agents made (how the timestamp is read, with the first event's result; field meanings; each source value → CIM value with its count), which are what you vouch for when you approve; raw vs parsed with one colour per field and a CIM view; the configuration as the `.conf` files themselves. Approve (bound to the package's SHA-256, with a second confirmation), reject, or download the `.tgz`.

**CLI**
```bash
.venv/bin/parsemaxxing run engine/parsemaxxing/generator/fixtures/acme_vpn.json --vendor acme --product vpn --token-file ~/.pmx-token
.venv/bin/parsemaxxing update TA-parsemaxxing-acme-fw new_format.log --token-file ~/.pmx-token
.venv/bin/parsemaxxing approve <job> --sha256 <hash> --token-file ~/.pmx-token && .venv/bin/parsemaxxing promote <job> --token-file ~/.pmx-token
```
These commands go through the engine API with an admin API token ([API token for the CLI](#api-token-for-the-cli)); `run`, `update` and `promote` wait for the engine's workers and print each attempt, check and the CIM score. A refusal prints the engine's message and request id and exits with code 4. `status`, `tas` and the host-only commands (`migrate`, `admin reset`, `setup-token`, `secrets rotate-kek`, `settings import-env`, `ledger verify`, `backup`, `restore`) use the database directly. `run --local` runs the pipeline without API and database.

## Running tests and security checks

```bash
make test      # pytest (engine and repo tooling), then the web build and Playwright end-to-end tests
make lint      # all pre-commit hooks (ruff, gitleaks, file checks), then ESLint and TypeScript
make security  # bandit, semgrep, pip-audit, npm audit, gitleaks over full git history
```

| Other targets | Does |
| --- | --- |
| `make secrets` | Create `.env` and the Docker secrets in `secrets/` if missing (needs Docker) |
| `make setup-token` | Print a new one-time setup token from the running engine ([Create the first admin](#create-the-first-admin)) |
| `make e2e` | Web build and Playwright end-to-end tests only |
| `make lock` | Regenerate `engine/requirements.lock` with hashes, from releases older than `BEFORE` (default 2026-11-04); needs `uv` |
| `make digests` | Show where each pinned image tag points now; `make digests WRITE=1` updates the files |
| `make sbom` | CycloneDX SBOM per built image into `sbom/` (Syft) |
| `make scan` | Trivy scan of the built images, failing on fixable HIGH or CRITICAL findings (`.trivyignore` holds reviewed exceptions) |
| `make backup`, `make restore`, `make restore-test` | [Backups](#backups) |

`make setup` creates `.env` and `secrets/` first, so it needs Docker running.

`make security` needs `gitleaks` and `semgrep` on your PATH:

```bash
brew install gitleaks          # or: go install github.com/zricethezav/gitleaks/v8@v8.30.1
pipx install semgrep           # kept out of the project venv to avoid dependency clashes
```

CI runs `make lint`, `make test` and `make security` on every pull request and on pushes to `main`, plus two more jobs: `images` (builds the engine and web images, keeps an SBOM per image as an artifact for 30 days, runs the Trivy scan) and `restore-test`. Any failure fails the build.

## Project structure

```
.
├── engine/                  Python backend (package: parsemaxxing)
│   ├── parsemaxxing/
│   │   ├── api/             FastAPI routes, upload checks and the SSE stream (built)
│   │   ├── orchestrator/    three-stage run loop, workers, approval and promotion (built)
│   │   ├── agents/          LLM client, Profiler, Index-time, Extraction, CIM mapper (built)
│   │   ├── tools/           lab probes, Splunk client, search guard, test_regex (built)
│   │   ├── guardrails/      index-time and search-time gates, final package gate, adversarial suite (built)
│   │   ├── validator/       index-time, extraction and CIM checks (built)
│   │   ├── ta_builder/      escaping conf writer, naming, .tgz packaging (built)
│   │   ├── ledger/          PostgreSQL job queue, append-only hash-chained ledger, encrypted backups (built)
│   │   ├── settings/        typed, versioned settings with history and import (built)
│   │   ├── secrets/         the vault: AES-256-GCM envelope encryption under the KEK (built)
│   │   ├── auth/            local accounts, sessions, MFA, API tokens, route policy, audit (built; LDAP planned)
│   │   ├── cim_spec/        CIM 8.7.0 required fields and allowed values, pinned from Splunk_SA_CIM (built)
│   │   └── generator/       synthetic logs in four formats + truth manifests; fixtures/ (built)
│   └── tests/               engine tests
├── web/                     Next.js + shadcn/ui UI (built)
├── docs/                    design.md (source of truth), setup.md, features.md, threat-model.md,
│                            lab-findings.md, build-plan.md, build-log.md, knowledge-sources.md
├── scripts/                 one-command setup (up.sh, Splunk bootstrap, make_secrets.py), backups,
│                            image checks, the TCP relay, the Caddyfile, first run, commit-msg hook
├── secrets/                 Docker secrets: KEK, database passwords, proxy hop secret (git-ignored, made by make secrets)
├── lab/                     licensed add-ons you download (CIM); git-ignored packages
├── demo/                    repeatable scenario scripts
├── tests/                   repo tooling tests
├── .claude/                 project settings and subagents for Claude Code
├── .github/workflows/       CI
├── docker-compose.yml       Splunk Enterprise, PostgreSQL, engine, web, relays; cli and https profiles
├── Makefile                 setup, env, secrets, up, first-run, down, logs, test, e2e, lint, security,
│                            lock, digests, sbom, scan, backup, restore, restore-test
└── .env.example             bootstrap values and v1 overrides, placeholders only
```

## Troubleshooting

- **Splunk is slow to start.** The first start takes several minutes while the container provisions itself. Follow it with `make logs` (or `docker compose logs -f splunk`). Wait for `docker compose ps` to show `healthy`.
- **Splunk exits right away mentioning the license or general terms.** `SPLUNK_START_ARGS=--accept-license` and `SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com` must both be set in `.env`. Setting them means you accept the Splunk license and terms.
- **Splunk rejects the admin password.** `SPLUNK_PASSWORD` needs at least 8 characters. If you change it after the first start, the old password stays in the `splunk-etc` volume. Run `docker compose down -v` to reset, which **deletes all Splunk and PostgreSQL data**.
- **`the KV store is not ready`.** Splunk's tokens need its KV store. `make up` waits 5 minutes for it; run `make up` again, and if it repeats, read `docker compose logs splunk`.
- **Port already in use.** Change `SPLUNK_WEB_PORT` or `WEB_PORT` in `.env`, then run `make down && make up`.
- **`required variable ... is missing a value`.** A required `.env` value is empty or missing. Compare your `.env` with `.env.example`.
- **`FAILED: the CIM add-on is not installed`.** `lab/` has no CIM package, or more than one. See [Step 4](#step-4-add-the-splunk-cim-add-on), then run `make up` again.
- **`permission denied while trying to connect to the docker API`.** Your user can't reach Docker yet. See [Step 2](#step-2-let-your-user-run-docker), and remember to log out and back in.
- **`open .env: permission denied`.** `.env` is owned by root, usually from an older `sudo make up`. Run `sudo chown "$USER":"$USER" .env`.
- **`make first-run` ends with `error`.** Read the reason with `docker compose logs --tail=40 engine`. Running `make first-run` again starts a new run.
- **The engine logs 401 from Splunk.** The service tokens last 7 days. Run `make up` again: it replaces all three in `.env`, and a token set in `.env` wins over the vault ([Settings and secrets](#settings-and-secrets)).
- **`could not hand the secret files to uid 10001: is Docker running?`** `make secrets` (also run by `make setup` and `make up`) needs Docker. Start it, or use `DOCKER="sudo docker"`.
- **`secrets/... is not a regular file: fix it by hand`.** Something other than a plain file sits at that path in `secrets/` (a link or a folder). Move it away; `make secrets` then creates a new one. Never do this to `pmx_kek` if the vault holds secrets: restore it from your KEK backup instead.
- **`refused:` from `rotate-kek` or `import-env` about the KEK.** The KEK file must be a regular file with no group or other permissions, one line of base64 of 32 bytes. Run the command with `sudo` and `PARSEMAXXING_KEK_FILE=secrets/pmx_kek`. A KEK that does not match the vault is refused: use the one you backed up.
- **The host CLI cannot reach PostgreSQL.** It is published only with the `cli` profile: `docker compose --profile cli up -d postgres-cli`.
- **`no backup recipients` or `not an age public key`.** Put your `age1...` public key in the recipients file ([Backups](#backups)).
- **The setup page says the token is not valid.** Tokens last 60 minutes and work once. Run `make setup-token` for a new one.
- **Signing in returns to the sign-in page.** The browser dropped the `__Host-pmx_session` cookie. Safari does this on plain `http://localhost`, and every browser does it on plain http with another host name: use Chromium, Chrome, Edge or Firefox on `http://localhost:3000`, or the [`https` profile](#https).
- **"Too many attempts. Try again in N minutes."** 5 failures for one user name, or 20 from one IP, lock sign-in for 60 seconds, doubling up to 15 minutes. Wait, or clear it with `parsemaxxing admin reset <user name>` ([Create the first admin](#create-the-first-admin)). Anyone can lock a known user name this way for up to 15 minutes (threat model R23).
- **`no API token: set PARSEMAXXING_API_TOKEN or pass --token-file`.** Create a token ([API token for the CLI](#api-token-for-the-cli)). A token file readable by group or others, or a link, is refused.
- **`make first-run` or a `demo/` script fails with HTTP 401 or asks for `PARSEMAXXING_API_TOKEN`.** Create an admin API token under Settings > API tokens, save it with mode 0600, and `export PARSEMAXXING_API_TOKEN=$(cat ~/.pmx-token)`.
- **Meta API errors:**
  - 401/403: check `LLM_API_KEY`.
  - 404: check `LLM_BASE_URL` and `LLM_MODEL`.
  - 429: you hit a rate limit or used up your credits. Check the spend limit on your Meta billing page.
