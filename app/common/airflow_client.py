import requests
from flask import current_app

TIMEOUT_SECONDS = 15


class AirflowError(Exception):
    pass


def _get_token(base_url: str) -> str:
    """Exchange the Airflow admin credentials for a JWT (Airflow 3 /auth/token)."""
    response = requests.post(
        f"{base_url}/auth/token",
        json={
            "username": current_app.config["AIRFLOW_USERNAME"],
            "password": current_app.config["AIRFLOW_PASSWORD"],
        },
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise AirflowError(f"Airflow auth failed ({response.status_code}): {response.text}")
    return response.json()["access_token"]


def trigger_dag(dag_id: str, conf: dict, dag_run_id: str | None = None) -> dict:
    """Start a run of `dag_id` with `conf` through the Airflow REST API."""
    base_url = current_app.config["AIRFLOW_API_URL"].rstrip("/")
    try:
        token = _get_token(base_url)
        payload = {"logical_date": None, "conf": conf}
        if dag_run_id:
            payload["dag_run_id"] = dag_run_id
        response = requests.post(
            f"{base_url}/api/v2/dags/{dag_id}/dagRuns",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as err:
        raise AirflowError(f"Airflow is unreachable: {err}") from err

    if not response.ok:
        raise AirflowError(f"Airflow trigger failed ({response.status_code}): {response.text}")
    return response.json()
