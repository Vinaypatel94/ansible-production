# Known gaps

These are deliberate leftovers. They do not block preparing the repo. They do block a real deploy until the operator items below are done.

## Do before the first real deploy

1. Copy `inventory/hosts.ini.example` to `inventory/hosts.ini` and set real `ansible_host` values. Do not commit `inventory/hosts.ini`.
2. Copy `group_vars/airflow/vault.yml.example` to `group_vars/airflow/vault.yml`, fill every `vault_*` value, then run `ansible-vault encrypt group_vars/airflow/vault.yml`.
3. Point `airflow_db_host` in `group_vars/airflow/vars.yml` at the real PostgreSQL endpoint (RDS hostname).
4. If workers are on other hosts, Redis on the master must listen on the private IP. `redis_bind_address` defaults to `127.0.0.1`, so workers cannot reach it until you override that and open security-group port 6379 only from the worker subnet.
5. Rotate every password, Fernet key, web secret, and SSH key that was ever committed in older git history. This repo does not rewrite history.

## Not done in this pass

- Airflow 3.x is not installed. The pinned line is Airflow 2.10.5 because 3.x changes the webserver, auth, and config layout.
- Molecule and `docker compose up` were not executed here because no Docker daemon was available. Static checks that did run: `ansible-playbook --syntax-check` and `playbooks/render-check.yml`.
- A clean `pip install apache-airflow[celery,postgres,fab]==2.10.5` against the constraints file was not executed in a fresh virtualenv.