# SETUP.md — Airflow on AWS (Ansible-managed, CeleryExecutor)

This guide takes you from an empty AWS account to a working Apache Airflow
cluster (1 master + N workers + RDS PostgreSQL), using the Ansible project
in this repository. Every command is copy-paste ready. Placeholders look
like `<THIS>` — replace them before running the command.

---

## 1. Architecture

```text
                        Internet
                           |
                 [Internet Gateway]
                           |
                     Public Subnet
        -------------------------------------
        |                                   |
   airflow-master                     airflow-worker-N
   - webserver (8080)                 - Celery worker
   - scheduler                        - log server (8793)
   - triggerer
   - Redis broker (6379, private)
        |
        |  (TCP 5432, private)
        v
   RDS PostgreSQL 16  (metadata DB: "airflow")
```

- **Executor:** CeleryExecutor
- **Broker:** self-hosted Redis on the master (bound to the master's
  private IP, not `0.0.0.0`)
- **Metadata DB:** AWS RDS PostgreSQL 16 (this project does not install
  Postgres itself)
- **OS:** Ubuntu 24.04 LTS
- **Airflow:** 2.10.5, Python 3.12 (see `README.md` "Version matrix" for
  the full pinned stack)

---

## 2. Prerequisites

### AWS side
- An AWS account with permission to create VPC, EC2, RDS, and IAM
  resources.
- A region. Everywhere below uses `<AWS_REGION>` (e.g. `ap-south-1`) —
  pick one and use it consistently.

### Local machine (control node)
- Linux, macOS, or Windows with WSL.
- `git`, `python3` (3.10+), `ssh`, `openssl`.
- Internet access to PyPI and Ansible Galaxy.

Check what you have:

```bash
python3 --version
ssh -V
git --version
```

---

## 3. Required tools — install on your local machine

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv openssh-client git
```

Create an isolated environment inside the project so system Python is
never touched:

```bash
cd /home/vinay/projects/ansible-production
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "ansible-core>=2.16" ansible-lint yamllint cryptography
```

Confirm:

```bash
ansible --version
```

Expect `ansible-core` version `2.16` or higher.

Install this project's required Ansible collections:

```bash
ansible-galaxy collection install -r requirements.yml
```

This installs `community.general >=9.0.0` (used for the `airflow.cfg`
section-merge filter), `ansible.posix >=1.5.4`, and `community.docker
>=3.10.0`.

Every time you open a new terminal, re-activate the venv before running
Ansible:

```bash
cd /home/vinay/projects/ansible-production
source .venv/bin/activate
```

---

## 4. AWS network setup

Region used below: `<AWS_REGION>` (example in this guide: `ap-south-1`).

### 4.1 Key pair

AWS Console → **EC2 → Key pairs → Create key pair**

- Name: `airflow-key`
- Type: `ED25519` (or `RSA` if unavailable)
- Format: `.pem`

Save it locally:

```bash
mkdir -p ~/.ssh
mv ~/Downloads/airflow-key.pem ~/.ssh/airflow-key.pem
chmod 400 ~/.ssh/airflow-key.pem
```

### 4.2 VPC

**VPC → Create VPC** → "VPC only"

- Name: `airflow-vpc`
- IPv4 CIDR: `<VPC_CIDR>` (example: `10.0.0.0/16`)
- IPv6: none

### 4.3 Subnets

**Subnets → Create subnet**, VPC = `airflow-vpc`:

| Name | AZ | CIDR | Purpose |
|---|---|---|---|
| `public-a` | `<AWS_REGION>a` | `<PUBLIC_SUBNET_CIDR>` (e.g. `10.0.1.0/24`) | EC2 (master + workers) |
| `private-a` | `<AWS_REGION>a` | `<PRIVATE_SUBNET_A_CIDR>` (e.g. `10.0.2.0/24`) | RDS |
| `private-b` | `<AWS_REGION>b` | `<PRIVATE_SUBNET_B_CIDR>` (e.g. `10.0.3.0/24`) | RDS (needs 2 AZs) |

On `public-a`: **Actions → Edit subnet settings → Enable auto-assign
public IPv4** = on. Leave it off on the private subnets.

### 4.4 Internet Gateway

**Internet gateways → Create** → name `airflow-igw` → **Actions → Attach
to VPC** → `airflow-vpc`.

### 4.5 Route tables

**Route tables → Create route table**:

- `public-rt` (VPC `airflow-vpc`) → add route `0.0.0.0/0` → target
  `airflow-igw` → associate with `public-a`.
- `private-rt` (VPC `airflow-vpc`) → leave only the default `local`
  route → associate with `private-a` and `private-b`.

No NAT Gateway is used in this guide (keeps cost down). EC2 instances go
in the public subnet so `apt`/`pip` work directly through the Internet
Gateway.

### 4.6 Security groups

**EC2 → Security groups → Create security group**, VPC = `airflow-vpc`.

**`airflow-master-sg`** — inbound:

| Type | Port | Source |
|---|---:|---|
| SSH | 22 | `<YOUR_IP>/32` (your current public IP) |
| Custom TCP | 8080 | `<YOUR_IP>/32` (Airflow UI) |
| Custom TCP | 6379 | `airflow-worker-sg` (Redis, from workers only) |

**`airflow-worker-sg`** — inbound:

| Type | Port | Source |
|---|---:|---|
| SSH | 22 | `<YOUR_IP>/32` |
| Custom TCP | 8793 | `airflow-master-sg` (log server, master reads worker logs) |

**`airflow-rds-sg`** — inbound:

| Type | Port | Source |
|---|---:|---|
| PostgreSQL | 5432 | `airflow-master-sg` |
| PostgreSQL | 5432 | `airflow-worker-sg` |

Never open `22`, `6379`, `5432`, or `8793` to `0.0.0.0/0`. Outbound rules
stay at the default "all traffic" on every group.

### 4.7 IAM role

**IAM → Roles → Create role** → Trusted entity: `AWS service` → Use
case: `EC2`.

Attach only:

- `AmazonSSMManagedInstanceCore` (optional, lets you shell in without SSH
  if needed)

Do **not** attach `AdministratorAccess`. Name it `airflow-ec2-role`.

### 4.8 Launch EC2 instances

**EC2 → Launch instances**, repeated once for master and once per worker.

Common settings:

- AMI: **Ubuntu Server 24.04 LTS**, 64-bit (x86)
- Key pair: `airflow-key`
- Subnet: `public-a`, auto-assign public IP: enable
- IAM instance profile: `airflow-ec2-role`
- Metadata version: `V2 only` (IMDSv2 required)
- Storage: `gp3`, encrypted

| Instance | Type | Disk | Security group |
|---|---|---:|---|
| `airflow-master` | `t3.small` (2 GB RAM min) | 30 GiB | `airflow-master-sg` |
| `airflow-worker-1` | `t3.micro`/`t3.small` | 20 GiB | `airflow-worker-sg` |
| `airflow-worker-2` (optional) | `t3.micro`/`t3.small` | 20 GiB | `airflow-worker-sg` |

Record each instance's **public IP** and **private IP** — you need both
below.

### 4.9 RDS PostgreSQL

**RDS → Create database**

- Engine: PostgreSQL **16**
- Template: Dev/Test (or Production if you want Multi-AZ)
- DB instance identifier: `<RDS_IDENTIFIER>` (e.g. `airflow-db`)
- Master username: `airflow`
- Master password: generate one now (see §6) and reuse it as
  `vault_airflow_db_password`
- Instance class: `db.t4g.micro` / `db.t3.micro`
- Storage: 20 GiB `gp3`
- VPC: `airflow-vpc`
- DB subnet group: `private-a` + `private-b`
- **Public access: No**
- Security group: `airflow-rds-sg`
- Initial database name: leave blank here — you will create the
  database explicitly in §9 (this avoids a naming mismatch that is a
  common source of failure)
- Backup retention: 7+ days
- Encryption: enable
- Deletion protection: enable

After creation, copy the **endpoint** — it looks like:

```text
<RDS_IDENTIFIER>.<RANDOM_ID>.<AWS_REGION>.rds.amazonaws.com
```

---

## 5. SSH connectivity check

From your local machine:

```bash
ssh -i ~/.ssh/airflow-key.pem ubuntu@<MASTER_PUBLIC_IP>
exit
ssh -i ~/.ssh/airflow-key.pem ubuntu@<WORKER1_PUBLIC_IP>
exit
```

If this times out, check in order: instance `Running` + `2/2` status
checks, security group SSH source matches your current IP, route table
has `0.0.0.0/0 → igw`, subnet has auto-assign public IP enabled.

---

## 6. Project configuration

All of this happens on your **local machine**, inside the project
directory.

### 6.1 Inventory

```bash
cd /home/vinay/projects/ansible-production
cp inventory/hosts.ini.example inventory/hosts.ini
```

Edit `inventory/hosts.ini`:

```ini
[airflow_master]
airflow-master ansible_host=<MASTER_PUBLIC_IP> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/airflow-key.pem ansible_python_interpreter=/usr/bin/python3

[airflow_workers]
airflow-worker-1 ansible_host=<WORKER1_PUBLIC_IP> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/airflow-key.pem ansible_python_interpreter=/usr/bin/python3
airflow-worker-2 ansible_host=<WORKER2_PUBLIC_IP> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/airflow-key.pem ansible_python_interpreter=/usr/bin/python3

[airflow:children]
airflow_master
airflow_workers
```

This file is gitignored on purpose — it contains real IPs.

### 6.2 Database connection

Edit `inventory/group_vars/airflow/vars.yml`:

```yaml
airflow_db_host: "<RDS_ENDPOINT>"
airflow_db_port: 5432
airflow_db_name: airflow
airflow_db_user: airflow
```

`airflow_db_name` **must** be `airflow` (or whatever database you create
in §9 — the two must match exactly).

### 6.3 Redis reachability (master ↔ workers)

Redis on the master defaults to listening on `127.0.0.1` only. With
separate worker hosts, you must point it at the master's **private** IP.

Create `inventory/host_vars/airflow-master.yml`:

```bash
mkdir -p inventory/host_vars
```

```yaml
# inventory/host_vars/airflow-master.yml
---
redis_bind_address: "<MASTER_PRIVATE_IP>"
```

Edit `inventory/group_vars/airflow_workers.yml` and replace the
`airflow_celery_broker_url` line with:

```yaml
airflow_celery_broker_url: >-
  redis://:{{ redis_password }}@<MASTER_PRIVATE_IP>:6379/0
```

Use the master's **private** IP in both places — never the public IP for
Redis.

### 6.4 Secrets (Ansible Vault)

If `inventory/group_vars/airflow/vault.yml` does not exist yet:

```bash
cat > /tmp/vault-template.yml << 'EOF'
---
vault_airflow_fernet_key: "CHANGE_ME"
vault_airflow_web_secret_key: "CHANGE_ME"
vault_airflow_db_password: "CHANGE_ME"
vault_airflow_admin_password: "CHANGE_ME"
vault_airflow_admin_email: "CHANGE_ME"
vault_redis_password: "CHANGE_ME"
EOF
cp /tmp/vault-template.yml inventory/group_vars/airflow/vault.yml
```

Generate real values:

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# -> use as vault_airflow_fernet_key

openssl rand -hex 32
# -> use as vault_airflow_web_secret_key

openssl rand -hex 24
# -> use as vault_airflow_db_password (must match the RDS master password)
#    reuse a different run of this command for vault_redis_password

openssl rand -base64 18
# -> use as vault_airflow_admin_password (must be 12+ characters)
```

Edit `inventory/group_vars/airflow/vault.yml` and paste in the generated
values, plus a real email for `vault_airflow_admin_email`.

Encrypt it:

```bash
ansible-vault encrypt inventory/group_vars/airflow/vault.yml
```

You will be asked to set a **Vault password** — this is separate from
every other password in this project. Save it in a password manager; you
will need it on every deployment run.

To view/edit later:

```bash
ansible-vault view inventory/group_vars/airflow/vault.yml
ansible-vault edit inventory/group_vars/airflow/vault.yml
```

### 6.5 Environment variables reference

| Variable | Where | Purpose |
|---|---|---|
| `vault_airflow_fernet_key` | vault.yml | Encrypts connection passwords in the metadata DB |
| `vault_airflow_web_secret_key` | vault.yml | Flask session secret for the webserver |
| `vault_airflow_db_password` | vault.yml | Must match the RDS master password |
| `vault_airflow_admin_password` | vault.yml | Airflow UI admin login (12+ chars) |
| `vault_airflow_admin_email` | vault.yml | Airflow UI admin email |
| `vault_redis_password` | vault.yml | Celery broker auth |
| `redis_bind_address` | `host_vars/airflow-master.yml` | Must be the master's private IP for multi-host setups |
| `airflow_db_host` / `airflow_db_name` | `group_vars/airflow/vars.yml` | RDS endpoint and database name |

---

## 7. Create the database

PostgreSQL client on the master (or any machine that can reach RDS):

```bash
ssh -i ~/.ssh/airflow-key.pem ubuntu@<MASTER_PUBLIC_IP>
sudo apt update && sudo apt install -y postgresql-client
```

```bash
psql -h <RDS_ENDPOINT> -U airflow -d postgres -W
```

Enter the RDS master password when prompted, then:

```sql
CREATE DATABASE airflow OWNER airflow;
\l
\q
```

Exit back to your local machine:

```bash
exit
```

---

## 8. Deploy

From your local machine, project root, venv active:

```bash
ansible -m ping airflow
```

Expect `SUCCESS` for every host. Then:

```bash
ansible-playbook playbooks/install-airflow.yml --syntax-check
ansible-playbook playbooks/install-airflow.yml --ask-vault-pass
```

Enter the **Vault password** from §6.4 (not the RDS or admin password).

This installs Airflow 2.10.5 on every host, starts
webserver/scheduler/triggerer/Redis on the master, starts only the Celery
worker on each worker, and runs `airflow db migrate` on the master once.

---

## 9. Verify

**Master:**

```bash
ssh -i ~/.ssh/airflow-key.pem ubuntu@<MASTER_PUBLIC_IP>
sudo systemctl status airflow-webserver airflow-scheduler airflow-triggerer redis-server --no-pager
curl -fsS http://127.0.0.1:8080/health
exit
```

**Each worker:**

```bash
ssh -i ~/.ssh/airflow-key.pem ubuntu@<WORKER_PUBLIC_IP>
sudo systemctl status airflow-worker --no-pager
exit
```

**UI:** open `http://<MASTER_PUBLIC_IP>:8080` in a browser. Log in with
username `admin` and the `vault_airflow_admin_password` value.

**DAGs:** this project's `dags/` folder is not auto-synced to EC2 by the
playbook. Deploy it explicitly:

```bash
ansible airflow --become \
  -m ansible.builtin.copy \
  -a "src=dags/ dest=/opt/airflow/dags/ owner=airflow group=airflow mode=0640 directory_mode=0750"
```

Wait 30–60 seconds, refresh the UI, and confirm DAGs appear with no
import errors:

```bash
ssh -i ~/.ssh/airflow-key.pem ubuntu@<MASTER_PUBLIC_IP>
sudo -u airflow env AIRFLOW_HOME=/opt/airflow AIRFLOW_CONFIG=/etc/airflow/airflow.cfg \
  /opt/airflow/bin/airflow dags list-import-errors
```

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FATAL: database "..." does not exist` during `db migrate` | `airflow_db_name` doesn't match an actual RDS database | Create it (§7) and make `airflow_db_name` match exactly |
| Admin user task runs/fails on workers too | `users.yml` imported without a condition | Ensure `roles/airflow/tasks/main.yml` has `when: airflow_run_db_migrate \| default(false)` on the Users import |
| `Connection refused` to `9102/metrics` | statsd_exporter not running | Leave `airflow_monitoring_enabled: false` (already set in this repo) unless you need Prometheus metrics |
| UI log viewer: `Could not read served logs ... host supplied, Invalid URL 'http://:8793/...'` | The task never actually ran on a worker (e.g. `EmptyOperator`, no real execution) | Use a `BashOperator`/real task to test; `EmptyOperator` never produces a log file |
| UI log viewer: `ConnectTimeoutError ... port=8793` | Worker security group doesn't allow the master to reach port 8793 | Add inbound rule: TCP 8793, source = `airflow-master-sg`, on `airflow-worker-sg` |
| `ansible -m ping` fails for one host | Public IP changed after a stop/start, or SG source IP stale | Update `inventory/hosts.ini`; refresh `<YOUR_IP>/32` in the SSH rule |
| `sudo: unknown user airflow` when debugging | You ran the command on your **local laptop**, not the EC2 instance | SSH into the target host first — the `airflow` OS user only exists on EC2 |

---

## 11. Security best practices (already applied / to keep in mind)

- Secrets live only in `inventory/group_vars/airflow/vault.yml`,
  encrypted with Ansible Vault, and are gitignored.
- `inventory/hosts.ini` (real IPs/paths) is gitignored; only the
  `.example` template is committed.
- Redis binds to a private IP, never `0.0.0.0`, and requires a password.
- RDS has **Public access: No** and only accepts connections from the
  Airflow security groups.
- SSH (22), the UI (8080), and the worker log port (8793) are restricted
  to specific IPs/security groups — never `0.0.0.0/0`.
- systemd units run with `NoNewPrivileges`, `ProtectSystem=full`,
  `ProtectHome`, `PrivateTmp`.
- If any secret or IP was ever committed to git history before this
  setup, rotate it — this project does not rewrite git history for you
  (see `ISSUES.md`).

---

## 12. Cleanup — avoid unnecessary AWS costs

When you're done testing:

```text
EC2 → select instance → Stop instance   (keeps data, no compute charge)
EC2 → select instance → Terminate       (deletes data, no further charge)
```

To fully tear down and stop all billing:

1. **RDS** → delete the database (disable deletion protection first,
   skip the final snapshot only if you don't need it).
2. **EC2** → terminate `airflow-master` and all workers.
3. **EC2 → Elastic IPs** → release any unattached Elastic IP (these are
   billed even when idle).
4. **EC2 → Security groups** → delete `airflow-master-sg`,
   `airflow-worker-sg`, `airflow-rds-sg`.
5. **VPC** → delete subnets, route tables, detach and delete the
   Internet Gateway, then delete `airflow-vpc`.
6. **EC2 → Key pairs** → delete `airflow-key` if you no longer need it
   (keep the local `.pem` file only if you plan to reuse the key).

Avoid creating a NAT Gateway or Load Balancer for test/dev use — both
have an hourly charge even when idle. Set a Billing budget alert
(Billing → Budgets) at a low threshold (e.g. $10) as a safety net.

---

## Appendix: key file map

| File | Purpose |
|---|---|
| `inventory/hosts.ini` | Real hosts (not committed) |
| `inventory/hosts.ini.example` | Template (committed) |
| `inventory/group_vars/airflow/vars.yml` | Shared non-secret config |
| `inventory/group_vars/airflow/vault.yml` | Encrypted secrets (not committed) |
| `inventory/group_vars/airflow_master.yml` | Master-only service config |
| `inventory/group_vars/airflow_workers.yml` | Worker-only service config |
| `inventory/host_vars/airflow-master.yml` | Master's Redis bind address |
| `playbooks/install-airflow.yml` | Main deploy playbook |
| `playbooks/render-check.yml` | Local-only template smoke test (no AWS, no SSH) |
| `roles/airflow`, `roles/redis` | The actual install/config logic |
| `README.md` | Version matrix and project layout |
| `docs/DEPLOYMENT.md` | Operator runbook (longer form of this guide) |
| `ISSUES.md` | Known gaps and follow-ups |