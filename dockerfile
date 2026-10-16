# Local test image: a real Apache Airflow 2.10.5 install matching the
# versions pinned by the Ansible role (roles/airflow/defaults/main/main.yml),
# used ONLY by docker-compose.yml for fully local testing. This is not
# used by the Ansible playbooks against EC2 - those build their own
# virtualenv on the target host (see roles/airflow/tasks/install.yml).
FROM python:3.12-slim-bookworm

ARG AIRFLOW_VERSION=2.10.5
ARG PYTHON_VERSION=3.12
ENV AIRFLOW_VERSION=${AIRFLOW_VERSION} \
    AIRFLOW_HOME=/opt/airflow \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SLUGIFY_USES_TEXT_UNIDECODE=yes

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      curl \
      netcat-openbsd \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 50000 airflow \
 && useradd --uid 50000 --gid 50000 --shell /usr/sbin/nologin --create-home airflow

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
      "apache-airflow[celery,postgres,fab]==${AIRFLOW_VERSION}" \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

RUN mkdir -p "${AIRFLOW_HOME}/dags" "${AIRFLOW_HOME}/logs" "${AIRFLOW_HOME}/plugins" \
 && chown -R airflow:airflow "${AIRFLOW_HOME}"

USER airflow
WORKDIR ${AIRFLOW_HOME}

HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
  CMD curl -fsS http://localhost:8080/health || exit 1
