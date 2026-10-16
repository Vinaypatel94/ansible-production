"""Minimal DAG used by Molecule to verify the role produced a working
Airflow install. `airflow.operators.dummy_operator.DummyOperator` was
removed in modern Airflow (2.4+); use `EmptyOperator` instead.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator

args = {
    "owner": "airflow",
    "start_date": datetime(2024, 1, 1),
}

with DAG(
    "sample_dag",
    schedule_interval="@once",
    default_args=args,
    catchup=False,
) as dag:
    t1 = EmptyOperator(task_id="extract_data")
    t2 = EmptyOperator(task_id="load_data")
    t3 = EmptyOperator(task_id="random_task")

    t1 >> t2 >> t3
