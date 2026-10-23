"""Tải text/raw/<doc>/page_N.txt từ MinIO về thư mục cục bộ để chấm bằng score_dir.py."""
import os, sys, boto3
doc, out = sys.argv[1], sys.argv[2]
s3 = boto3.client("s3", endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
                  aws_access_key_id=os.environ["MINIO_ACCESS_KEY"], aws_secret_access_key=os.environ["MINIO_SECRET_KEY"])
os.makedirs(out, exist_ok=True)
n = 0
for o in s3.list_objects_v2(Bucket="data-lake", Prefix=f"text/raw/{doc}/").get("Contents", []):
    k = o["Key"]
    if k.endswith(".txt"):
        open(os.path.join(out, os.path.basename(k)), "wb").write(s3.get_object(Bucket="data-lake", Key=k)["Body"].read()); n += 1
print(doc, n, "trang")
