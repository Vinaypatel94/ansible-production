# Airflow on Ansible (production-ready, AWS-ready)

Ansible project that installs a **CeleryExecutor** Apache Airflow cluster:

- **master**: webserver, scheduler, triggerer, and (by default) a local Redis broker
- **workers**: Celery workers only, pointed at the master's broker
- **metadata DB**: PostgreSQL (self-hosted or AWS RDS). This role does not install PostgreSQL.

Nothing in this repository deploys to AWS or contacts live hosts. Fill in inventory and vault, then run the playbook from a control node that can SSH to the targets.

## Version matrix

Pinned and intended to be installed together. Airflow's own dependency set (Celery, providers, SQLAlchemy, and so on) is taken from the upstream constraints file for this exact Airflow and Python pair, not pinned separately.

| Component | Version | Notes |
| --- | --- | --- |
| Ubuntu | 24.04 LTS | Target OS. Python 3.12 is the distro default. |
| Python | 3.12 | Virtualenv built by the role. |
| ansible-core | >= 2.16 | Enforced by a playbook pre-task. |
| Apache Airflow | 2.10.5 | Last 2.10 line. Airflow 3 is a separate migration (see `ISSUES.md`). |
| Celery | constraints-2.10.5 | Installed via the `celery` extra. |
| Redis | 7.x | Ubuntu `redis-server` package on the master, or ElastiCache. Local Compose uses `redis:7.2-alpine`. |
| PostgreSQL | 16 | Client libs via `libpq-dev` / `postgresql-client`. Server is external (RDS recommended). Compose uses `postgres:16`. |
| FAB provider | `fab` extra | Required on Airflow >= 2.9 for `webserver_config.py` / AUTH_DB. |
| Postgres provider | `postgres` extra | Metadata DB driver (`psycopg2`). |
| statsd_exporter | 0.31.0 | Optional Prometheus bridge. `airflow_monitoring_enabled`. |
| community.general | >= 9.0.0 | `lists_mergeby` filter used to build `airflow.cfg`. |

Constraints URL (also used at install time):

`https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt`

## Layout

| Path | Purpose |
| --- | --- |
| `playbooks/install-airflow.yml` | Cluster install/configure playbook. |
| `playbooks/render-check.yml` | Local-only template render. No SSH, no packages, no services. |
| `roles/airflow` | Airflow install, config, users, systemd, monitoring, backups. |
| `roles/redis` | Hardened Redis broker. No-op when `redis_manage: false`. |
| `group_vars/airflow/` | Shared non-secret vars + `vault.yml.example`. |
| `group_vars/airflow_master.yml` | Webserver, scheduler, triggerer, local Redis, `db migrate`. |
| `group_vars/airflow_workers.yml` | Worker only. Broker URL looks up the master host. |
| `inventory/hosts.ini.example` | Copy to `inventory/hosts.ini` (gitignored). |
| `docker-compose.yml` | Local Airflow 2.10.5 stack. Not used by Ansible. |
| `docs/DEPLOYMENT.md` | Vault, playbook, health checks, backups, AWS notes. |
| `ISSUES.md` | Known gaps and exact follow-ups. |

## Quick start

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.ini.example inventory/hosts.ini   # then set real hosts
cp group_vars/airflow/vault.yml.example group_vars/airflow/vault.yml
# edit vault.yml, then: ansible-vault encrypt group_vars/airflow/vault.yml
ansible-playbook playbooks/install-airflow.yml --ask-vault-pass
```

Local template check (no hosts required):

```bash
ansible-playbook playbooks/render-check.yml \
  -e @group_vars/airflow/vars.yml \
  -e @/tmp/test-vault.yml \
  -e @group_vars/airflow_master.yml
```

`/tmp/test-vault.yml` must define the `vault_*` keys from `vault.yml.example` with disposable values. Output lands in `/tmp/airflow-render-check`.

Local Docker stack (needs a Docker daemon; not run in CI here):

```bash
cp .env.example .env
docker compose up -d --build
```

UI: `http://localhost:8080`. Optional Flower: `docker compose --profile flower up -d`.

## What this playbook does

1. Fail if ansible-core < 2.16 or `community.general` is missing.
2. Validate secrets and the PostgreSQL connection string before installing anything.
3. Install OS build deps and a Python 3.12 virtualenv.
4. Install `apache-airflow[celery,postgres,fab]==2.10.5` against the constraints file.
5. Render a single `airflow.cfg` (sections are merged by name, so `[core]` cannot be duplicated).
6. Run `airflow db migrate` on the master only.
7. Create admin users from vault-backed variables (`no_log`, argv form, no shell interpolation).
8. Install and start the systemd units enabled for that group.
9. Optionally install statsd_exporter and a nightly `pg_dump` cron job.

Re-runs are idempotent: users are skipped when the email already exists, pip installs use `creates:`, and services use `state`/`enabled` from group vars.

## Secrets

Do not commit `group_vars/airflow/vault.yml`, `inventory/hosts.ini`, `.env`, or PEM files. They are gitignored. Previously committed secrets are **not** purged from git history by this change; see `ISSUES.md`.
