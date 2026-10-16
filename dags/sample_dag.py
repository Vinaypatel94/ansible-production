"""Sample DAG for local docker-compose validation.

Appears in the UI at http://localhost:8080 after `docker compose up`.
Safe to delete once you've confirmed the local stack works end-to-end.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="sample_dag",
    description="Smoke-test DAG for the local docker-compose stack",
    schedule="@once",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["smoke-test"],
) as dag:
    start = EmptyOperator(task_id="start")
    end = EmptyOperator(task_id="end")
    start >> end
