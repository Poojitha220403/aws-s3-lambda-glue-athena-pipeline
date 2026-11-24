import os

# The modules create boto3 clients at import time; give them a region and
# dummy credentials so no AWS account is needed to run the tests.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
