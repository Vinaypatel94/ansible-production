# Deployment

This document is the operator runbook. It does not create AWS resources.

## 1. Control node

- Ubuntu or any host with `ansible-core` >= 2.16 and Python 3.
- SSH private key that can reach every target as `ansible_user` (the example inventory uses `ubuntu`).
- Network path to the targets. For AWS, that is usually a bastion or a control node inside the VPC. This repo does not configure either.

```bash
ansible-galaxy collection install -r requirements.yml
```

## 2. Inventory

```bash
cp inventory/hosts.ini.example inventory/hosts.ini
```

Set `ansible_host` to the private IP when the control node is inside the VPC, otherwise the public IP or EIP. Keep workers off the public internet if you can; they only need the metadata DB, the Redis broker, and SSH from the control node.

Groups:

- `airflow_master` — exactly one host. Runs webserver, scheduler, triggerer, and (unless you override it) Redis.
- `airflow_workers` — zero or more Celery workers.
- `airflow` — parent of both. Shared vars live in `group_vars/airflow/`.

## 3. Vault

```bash
cp group_vars/airflow/vault.yml.example group_vars/airflow/vault.yml
```

Generate values (hex passwords are URI-safe and do not need encoding inside `sql_alchemy_conn`):

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
openssl rand -hex 24    # db password
openssl rand -hex 32    # webserver secret_key and redis password
```

`vault_airflow_admin_password` must be at least 12 characters. Then:

```bash
ansible-vault encrypt group_vars/airflow/vault.yml
```

Required keys: `vault_airflow_fernet_key`, `vault_airflow_web_secret_key`, `vault_airflow_db_password`, `vault_airflow_admin_password`, `vault_airflow_admin_email`, `vault_redis_password`.

Edit `group_vars/airflow/vars.yml` and set `airflow_db_host` to the RDS endpoint (or your PostgreSQL host). Create the database and role yourself; the role only runs `CREATE` migrations via `airflow db migrate` on the master (`airflow_run_db_migrate: true`). Workers set that flag to `false` so they cannot race the migration.

## 4. Redis reachability

Default `redis_bind_address` is `127.0.0.1`, which is correct only when every Airflow process is on the master.

With separate workers, set a host var on the master (for example `host_vars/airflow-master.yml`):

```yaml
redis_bind_address: "<master private IP>"
```

Open TCP 6379 from the worker security group to the master only. Do not use `0.0.0.0`. Workers already build the broker URL from the master's `ansible_host`:

`redis://:<password>@<master ansible_host>:6379/0`

To use ElastiCache instead, set `redis_manage: false` on the master and override `airflow_celery_broker_url` on the whole `airflow` group.

## 5. Run

```bash
ansible-playbook playbooks/install-airflow.yml --ask-vault-pass
```

Useful tags match the task file names (`install`, `config`, `users`, plus `always` on preflight). Re-running the full playbook is safe.

## 6. Health checks

On the master, after the playbook:

```bash
sudo systemctl status airflow-webserver airflow-scheduler airflow-triggerer
curl -fsS http://127.0.0.1:8080/health
```

On a worker:

```bash
sudo systemctl status airflow-worker
```

If monitoring is left enabled (the default), Prometheus can scrape `http://127.0.0.1:9102/metrics` on each Airflow host (statsd_exporter). Airflow itself emits StatsD to `127.0.0.1:9125`. Confirm the port in `roles/airflow/defaults/main/main.yml` (`airflow_statsd_exporter_web_port`) before opening a security group; the exporter is bound to localhost.

Flower is installed as a unit but **disabled** on both groups. Enable it only on the master, and do not publish port 5555 to the internet.

## 7. Backups

Metadata backups are off by default (`airflow_backup_enabled: false`). On RDS, use automated snapshots as the primary backup.

To also keep portable `pg_dump` copies on the master:

```yaml
airflow_backup_enabled: true
```

The role installs `postgresql-client`, writes `/usr/local/bin/airflow-db-backup.sh` (mode `0750`), and schedules cron at 02:30 as the `airflow` user. Dumps go to `/var/backups/airflow` and are kept for `airflow_backup_retention_days` (14). Logs: `{{ airflow_logs_folder }}/db-backup.log`, rotated weekly.

Restore (run manually, against a maintenance window):

```bash
sudo -u airflow bash -c 'PGPASSWORD="$AIRFLOW_DB_PASSWORD" pg_restore --clean --if-exists -h "$AIRFLOW_DB_HOST" -U "$AIRFLOW_DB_USER" -d "$AIRFLOW_DB_NAME" /var/backups/airflow/<file>'
```

Stop scheduler and workers before restoring. The script uses custom-format `pg_dump -Fc`. If `airflow_backup_s3_uri` is set, the script also attempts an `aws s3 cp` when the AWS CLI is already installed; this role does not install the CLI or an instance role.

## 8. Local validation (no AWS, no SSH)

```bash
ansible-playbook playbooks/install-airflow.yml --syntax-check
ansible-playbook playbooks/render-check.yml \
  -e @group_vars/airflow/vars.yml \
  -e @/tmp/test-vault.yml \
  -e @group_vars/airflow_master.yml
docker compose config
```

`docker compose up` needs a daemon and is the full runtime check of the same Airflow/Postgres/Redis versions. Molecule (`roles/airflow/molecule/default`) boots systemd + Postgres 16 + Redis 7.2 and converges the role; it also needs Docker.

## 9. AWS shape (not applied by this repo)

Suggested, not created here:

- VPC with private subnets for master, workers, and RDS.
- RDS PostgreSQL 16, not publicly accessible. Security group allows 5432 from the Airflow security group only.
- Optional ElastiCache Redis 7 instead of the host Redis role.
- EC2 Ubuntu 24.04. No public IP on workers. Master webserver on 8080 only from a bastion or an internal ALB.
- Do not put Fernet keys, DB passwords, or the Flask secret in user-data or SSM in plaintext if you can use Vault (or SSM SecureString) and `ansible-vault` on the control node.

Rotate any credential that ever lived in git history before the first real deploy. See `ISSUES.md`.
