"""Xóa dữ liệu của các tài liệu đo hiệu năng (mã bắt đầu bằng bench_) khỏi bucket data-lake.
python clean_bench.py          # chỉ liệt kê
python clean_bench.py --xoa    # xóa thật
"""
import os, sys, collections, boto3
s3 = boto3.client("s3", endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
                  aws_access_key_id=os.environ["MINIO_ACCESS_KEY"], aws_secret_access_key=os.environ["MINIO_SECRET_KEY"])
keys, kw = [], {"Bucket": "data-lake"}
while True:
    r = s3.list_objects_v2(**kw)
    keys += [o["Key"] for o in r.get("Contents", [])]
    if not r.get("IsTruncated"): break
    kw["ContinuationToken"] = r["NextContinuationToken"]
hit = [k for k in keys if any(seg.startswith("bench_") for seg in k.split("/"))]
print("tổng", len(keys), "khóa; khóa của bench_*:", len(hit))
print(collections.Counter(k.split("/")[0] for k in hit))
print("mẫu:", hit[:3])
if "--xoa" in sys.argv:
    for i in range(0, len(hit), 1000):
        s3.delete_objects(Bucket="data-lake", Delete={"Objects": [{"Key": k} for k in hit[i:i + 1000]], "Quiet": True})
    print("đã xóa", len(hit))
