"""
bench.py — Đo thời gian xử lý toàn trình qua Web UI, lặp nhiều lần để có trung bình và độ lệch chuẩn.

Thời gian một tài liệu = từ lúc tải lên tới khi trạng thái là "done" (đã ghép đủ trang, status success).

    # 3 lần liên tiếp, mỗi lần một tài liệu (đo độ trễ)
    python bench.py --pdf mau10trang.pdf --runs 3 --label cpu_10trang

    # 5 tài liệu tải lên cùng lúc (mô phỏng 5 người dùng; đo thông lượng)
    python bench.py --pdf decuong4.pdf --concurrent 5 --label gpu_5nguoi

Chỉ dùng thư viện chuẩn; chạy được trong container ocr-web-ui (--api http://localhost:8080).
"""
import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request
import uuid


def upload(api, path, name):
    boundary = uuid.uuid4().hex
    data = open(path, "rb").read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(api + "/api/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req).read())["id"]


def status(api, doc_id):
    return json.loads(urllib.request.urlopen(f"{api}/api/documents/{urllib.parse.quote(doc_id)}").read())


def wait_all(api, ids, t0, timeout):
    done = {}
    while len(done) < len(ids):
        for i in ids:
            if i in done:
                continue
            d = status(api, i)
            if d["status"] == "done":
                done[i] = (time.time() - t0[i], d["pages_total"])
                print(f"  {i}: {done[i][0]:.1f}s, {done[i][1]} trang", flush=True)
            elif d["status"] == "error":
                raise SystemExit(f"{i} lỗi: {d.get('error')}")
        if time.time() - min(t0.values()) > timeout:
            raise SystemExit("Hết thời gian chờ")
        time.sleep(2)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8501")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=1, help="số lần chạy lần lượt")
    ap.add_argument("--concurrent", type=int, default=1, help="số tài liệu tải lên cùng lúc trong mỗi lần")
    ap.add_argument("--timeout", type=int, default=7200)
    ap.add_argument("--out")
    a = ap.parse_args()

    runs = []
    for r in range(a.runs):
        t0, ids = {}, []
        for k in range(a.concurrent):
            name = f"bench_{a.label}_r{r + 1}_{k + 1}_{time.strftime('%H%M%S')}.pdf"
            i = upload(a.api, a.pdf, name)
            t0[i] = time.time()
            ids.append(i)
        print(f"Lần {r + 1}: tải lên {len(ids)} tài liệu", flush=True)
        done = wait_all(a.api, ids, t0, a.timeout)
        times = [v[0] for v in done.values()]
        pages = sum(v[1] for v in done.values())
        wall = max(times)
        runs.append({"seconds_each": [round(t, 1) for t in times], "wall_seconds": round(wall, 1), "pages": pages,
                     "seconds_per_page": round(wall / pages, 2)})
        print(f"Lần {r + 1}: xong {pages} trang sau {wall:.1f}s ({wall / pages:.2f}s/trang)", flush=True)

    walls = [x["wall_seconds"] for x in runs]
    spp = [x["seconds_per_page"] for x in runs]
    summary = {
        "label": a.label, "pdf": a.pdf, "runs": a.runs, "concurrent": a.concurrent,
        "wall_mean": round(statistics.mean(walls), 1), "wall_std": round(statistics.stdev(walls), 1) if len(walls) > 1 else 0.0,
        "spp_mean": round(statistics.mean(spp), 2), "spp_std": round(statistics.stdev(spp), 2) if len(spp) > 1 else 0.0,
        "detail": runs,
    }
    print(json.dumps(summary, ensure_ascii=False))
    if a.out:
        json.dump(summary, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
