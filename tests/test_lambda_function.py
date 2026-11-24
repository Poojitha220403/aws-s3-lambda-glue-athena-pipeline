import io
from datetime import datetime, timedelta

import pytest

import LambdaFunction


class FakeS3:
    """Minimal in-memory stand-in for the boto3 S3 client."""

    def __init__(self, objects):
        self.objects = dict(objects)
        self.puts = {}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)].encode("utf-8"))}

    def put_object(self, Bucket, Key, Body):
        self.puts[(Bucket, Key)] = Body


def day(offset_days):
    return (datetime.now() - timedelta(days=offset_days)).strftime("%Y-%m-%d")


def make_event(key, bucket="orders-bucket"):
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def run(monkeypatch, csv_text, key="raw/orders.csv"):
    fake = FakeS3({("orders-bucket", key): csv_text})
    monkeypatch.setattr(LambdaFunction, "s3", fake)
    result = LambdaFunction.lambda_handler(make_event(key), None)
    return fake, result


def kept_ids(fake, key):
    body = fake.puts[("orders-bucket", key)]
    lines = body.strip().splitlines()
    return [line.split(",")[0] for line in lines[1:]]


HEADER = "OrderID,OrderDate,Customer,Amount,Status\n"


def test_old_pending_and_cancelled_orders_are_dropped(monkeypatch):
    csv_text = HEADER + (
        f"1,{day(90)},Ann,10.00,Pending\n"
        f"2,{day(90)},Bob,20.00,Cancelled\n"
        f"3,{day(90)},Cy,30.00,Shipped\n"
    )
    fake, result = run(monkeypatch, csv_text)
    assert kept_ids(fake, "processed/filtered_orders.csv") == ["3"]
    assert result["statusCode"] == 200
    assert "Filtered 1 rows" in result["body"]


def test_recent_pending_orders_are_kept(monkeypatch):
    csv_text = HEADER + (
        f"1,{day(5)},Ann,10.00,Pending\n"
        f"2,{day(5)},Bob,20.00,Cancelled\n"
    )
    fake, _ = run(monkeypatch, csv_text)
    assert kept_ids(fake, "processed/filtered_orders.csv") == ["1", "2"]


def test_status_matching_ignores_case_and_whitespace(monkeypatch):
    csv_text = HEADER + f"1,{day(90)},Ann,10.00,  PENDING \n"
    fake, _ = run(monkeypatch, csv_text)
    assert kept_ids(fake, "processed/filtered_orders.csv") == []


def test_header_is_preserved_even_when_every_row_is_filtered(monkeypatch):
    csv_text = HEADER + f"1,{day(90)},Ann,10.00,Pending\n"
    fake, _ = run(monkeypatch, csv_text)
    body = fake.puts[("orders-bucket", "processed/filtered_orders.csv")]
    assert body.splitlines()[0] == HEADER.strip()


def test_output_goes_to_processed_folder_with_decoded_key(monkeypatch):
    csv_text = HEADER + f"1,{day(1)},Ann,10.00,Shipped\n"
    fake = FakeS3({("orders-bucket", "raw/my orders.csv"): csv_text})
    monkeypatch.setattr(LambdaFunction, "s3", fake)
    LambdaFunction.lambda_handler(make_event("raw/my+orders.csv"), None)
    assert ("orders-bucket", "processed/filtered_my orders.csv") in fake.puts


def test_missing_input_object_raises(monkeypatch):
    monkeypatch.setattr(LambdaFunction, "s3", FakeS3({}))
    with pytest.raises(KeyError):
        LambdaFunction.lambda_handler(make_event("raw/missing.csv"), None)
