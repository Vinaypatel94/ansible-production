"""Basic Airflow/Celery worker validation DAG."""

import os
import platform
import socket
from datetime import datetime, timezone

from airflow.decorators import dag, task


@dag(
    dag_id="runtime_smoke_test",
    description="Validate worker execution, Python runtime, and XCom",
    schedule=None,
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    tags=["validation", "smoke-test"],
)
def runtime_smoke_test():
    @task
    def collect_runtime_information():
        information = {
            "hostname": socket.getfqdn(),
            "short_hostname": socket.gethostname(),
            "user": os.getenv("USER", "unknown"),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "airflow_home": os.getenv("AIRFLOW_HOME", "not-set"),
            "airflow_config": os.getenv("AIRFLOW_CONFIG", "not-set"),
        }

        print("Runtime information:")
        for key, value in information.items():
            print(f"{key}: {value}")

        assert information["hostname"]
        assert information["airflow_home"] == "/opt/airflow"
        assert information["airflow_config"] == "/etc/airflow/airflow.cfg"

        return information

    @task
    def verify_xcom(information):
        print(f"XCom received from worker: {information}")

        assert "hostname" in information
        assert information["hostname"]

        return "Runtime and XCom validation passed"

    runtime_information = collect_runtime_information()
    verify_xcom(runtime_information)


runtime_smoke_test()