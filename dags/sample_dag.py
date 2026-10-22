"""Celery worker smoke-test DAG."""

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="sample_dag",
    description="Celery worker execution smoke test",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["smoke-test"],
) as dag:
    start = EmptyOperator(task_id="start")

    worker_test = BashOperator(
        task_id="worker_test",
        bash_command="""
        echo "Task executed successfully"
        echo "Hostname: $(hostname)"
        echo "User: $(whoami)"
        echo "Date: $(date -u)"
        """,
    )

    end = EmptyOperator(task_id="end")

    start >> worker_test >> end