"""Validate parallel Celery worker execution."""

import socket
import time
from collections import Counter
from datetime import datetime, timezone

from airflow.decorators import dag, task


@dag(
    dag_id="parallel_workers_test",
    description="Run parallel tasks across Celery workers",
    schedule=None,
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_tasks=16,
    tags=["validation", "celery", "parallel"],
)
def parallel_workers_test():
    @task
    def worker_probe(task_number):
        hostname = socket.getfqdn()

        print(f"Probe {task_number} started on {hostname}")
        time.sleep(15)
        print(f"Probe {task_number} finished on {hostname}")

        return {
            "task_number": task_number,
            "hostname": hostname,
        }

    @task
    def summarize(results):
        host_counts = Counter(item["hostname"] for item in results)

        print("Task distribution:")
        for hostname, count in sorted(host_counts.items()):
            print(f"{hostname}: {count} task(s)")

        assert results
        assert all(item["hostname"] for item in results)

        return dict(host_counts)

    probe_results = worker_probe.expand(task_number=list(range(1, 13)))
    summarize(probe_results)


parallel_workers_test()