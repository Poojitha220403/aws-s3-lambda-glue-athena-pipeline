import io

import pytest

import EC2NanoApp


class FakeAthena:
    def __init__(self, states, output="s3://results-bucket/enriched/q1.csv", reason=None):
        self.states = list(states)
        self.output = output
        self.reason = reason
        self.started = []

    def start_query_execution(self, QueryString, QueryExecutionContext, ResultConfiguration):
        self.started.append((QueryString, QueryExecutionContext, ResultConfiguration))
        return {"QueryExecutionId": "abc"}

    def get_query_execution(self, QueryExecutionId):
        state = self.states.pop(0)
        status = {"State": state}
        if self.reason:
            status["StateChangeReason"] = self.reason
        return {
            "QueryExecution": {
                "Status": status,
                "ResultConfiguration": {"OutputLocation": self.output},
            }
        }


class FakeS3:
    def __init__(self, body):
        self.body = body
        self.requested = None

    def get_object(self, Bucket, Key):
        self.requested = (Bucket, Key)
        return {"Body": io.BytesIO(self.body.encode("utf-8"))}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(EC2NanoApp.time, "sleep", lambda _s: None)


def test_five_dashboard_queries_are_defined_with_titles():
    queries = EC2NanoApp.queries_to_run
    assert len(queries) == 5
    assert all(q["title"] and "SELECT" in q["query"].upper() for q in queries)


def test_successful_query_returns_parsed_header_and_rows(monkeypatch):
    athena = FakeAthena(["RUNNING", "SUCCEEDED"])
    s3 = FakeS3('"Customer","Total"\n"Ann","30.0"\n"Bob","12.5"\n')
    monkeypatch.setattr(EC2NanoApp, "athena_client", athena)
    monkeypatch.setattr(EC2NanoApp, "s3_client", s3)

    header, rows = EC2NanoApp.run_athena_query("SELECT 1")

    assert header == ["Customer", "Total"]
    assert rows == [["Ann", "30.0"], ["Bob", "12.5"]]
    assert s3.requested == ("results-bucket", "enriched/q1.csv")
    _query, context, result_cfg = athena.started[0]
    assert context == {"Database": EC2NanoApp.ATHENA_DATABASE}
    assert result_cfg == {"OutputLocation": EC2NanoApp.S3_OUTPUT_LOCATION}


def test_failed_query_reports_the_reason(monkeypatch):
    athena = FakeAthena(["FAILED"], reason="SYNTAX_ERROR")
    monkeypatch.setattr(EC2NanoApp, "athena_client", athena)
    header, message = EC2NanoApp.run_athena_query("SELECT bad")
    assert header is None
    assert "SYNTAX_ERROR" in message


def test_exceptions_are_returned_not_raised(monkeypatch):
    class Boom:
        def start_query_execution(self, **_kw):
            raise RuntimeError("no credentials")

    monkeypatch.setattr(EC2NanoApp, "athena_client", Boom())
    header, message = EC2NanoApp.run_athena_query("SELECT 1")
    assert header is None
    assert "no credentials" in message


def test_index_renders_a_table_per_query(monkeypatch):
    monkeypatch.setattr(
        EC2NanoApp, "run_athena_query", lambda q: (["Customer", "Total"], [["Ann", "30"]])
    )
    response = EC2NanoApp.app.test_client().get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert html.count("<table>") == len(EC2NanoApp.queries_to_run)
    assert "Ann" in html and "1. Total Sales by Customer" in html


def test_index_shows_error_message_when_a_query_fails(monkeypatch):
    monkeypatch.setattr(EC2NanoApp, "run_athena_query", lambda q: (None, "Query failed: boom"))
    html = EC2NanoApp.app.test_client().get("/").get_data(as_text=True)
    assert "Query failed: boom" in html
    assert "<table>" not in html
