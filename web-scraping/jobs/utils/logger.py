# Standard Library Imports
import json
import os
from datetime import datetime

# Third-Party Imports
import boto3
from botocore.client import Config


def _resolve_storage_config():
    """
    Tier A: STORAGE_ENDPOINT / STORAGE_ACCESS_KEY_ID / STORAGE_SECRET_ACCESS_KEY
    point at Cloudflare R2.
    Local dev / legacy Helm: MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY
    point at MinIO.
    """
    endpoint = os.getenv("STORAGE_ENDPOINT") or os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("STORAGE_ACCESS_KEY_ID") or os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("STORAGE_SECRET_ACCESS_KEY") or os.getenv("MINIO_SECRET_KEY")
    region = os.getenv("STORAGE_REGION", "auto")
    bucket = os.getenv("STORAGE_BUCKET") or os.getenv("MINIO_BUCKET", "salt-media")
    log_prefix = os.getenv("BUCKET_SCRAPER_LOGS", "scraper-logs")
    return {
        "endpoint": endpoint,
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "bucket": bucket,
        "log_prefix": log_prefix,
    }


class Logger:
    """
    In-memory log buffer flushed to object storage at context exit.
    Logical "argo-logs" bucket from the old MinIO setup is now a key prefix
    (BUCKET_SCRAPER_LOGS, default "scraper-logs") inside the single Tier A
    R2 bucket.
    """

    def __init__(self, job_name):
        self.job_name = job_name
        self.log_path = self.generate_log_path()
        self.log_content = []

        cfg = _resolve_storage_config()
        self._bucket = cfg["bucket"]
        self._key = f"{cfg['log_prefix'].rstrip('/')}/{self.log_path}"

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=cfg["endpoint"],
            aws_access_key_id=cfg["access_key"],
            aws_secret_access_key=cfg["secret_key"],
            region_name=cfg["region"],
            config=Config(signature_version="s3v4"),
        )

    def generate_log_path(self):
        """Generate the log path based on the job name and timestamp."""
        current_time = datetime.now()
        date_str = current_time.strftime("%m-%d-%Y")
        time_str = current_time.strftime("%H-%M")
        return f"{self.job_name}/{date_str}/{time_str}.log"

    def log_json(self, level, message, context=None):
        """Append a JSON log entry to the in-memory buffer."""
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message,
        }
        if context:
            log_entry["context"] = context
        self.log_content.append(json.dumps(log_entry))

    def upload_logs(self):
        """Flush accumulated logs to object storage."""
        log_data = "\n".join(self.log_content)
        try:
            self.s3_client.put_object(Body=log_data, Bucket=self._bucket, Key=self._key)
            print(f"Logs successfully uploaded to s3://{self._bucket}/{self._key}")
        except Exception as e:
            print(f"Failed to upload logs to storage: {e}")
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.upload_logs()
