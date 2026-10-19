import os
import json
import time
import logging
import boto3
from kafka import KafkaConsumer, KafkaProducer
from kafka.structs import OffsetAndMetadata

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Thời gian rảnh (không nhận thêm box) trước khi ghi tạm một trang chưa đủ box.
# Tính theo lần nhận box gần nhất: box có thể xếp hàng lâu ở VietOCR khi tài liệu nhiều trang.
TIMEOUT = int(os.getenv("RECONSTRUCT_TIMEOUT", 120))
# Trang đã ghi tạm được giữ lại để ghép tiếp nếu box đến muộn
EVICT_AFTER = int(os.getenv("RECONSTRUCT_EVICT_AFTER", 3600))
BUCKET = os.getenv("MINIO_BUCKET", "data-lake")

document_buffer = {}

# =========================
# GEOMETRY UTILS
# =========================
def get_center_y(box): return sum(p[1] for p in box) / 4
def get_center_x(box): return sum(p[0] for p in box) / 4
def get_height(box):
    y_coords = [p[1] for p in box]
    return max(y_coords) - min(y_coords)

# Khối ảnh/bảng (ô giả bao cả khối) đứng riêng một dòng, không tham gia gom dòng chữ
BLOCK_TYPES = {"figure", "table"}


def is_block(b):
    return b.get("content_type") in BLOCK_TYPES


def get_top_y(box):
    return min(p[1] for p in box)


def sort_boxes(boxes):
    valid_boxes = [b for b in boxes if b.get("coordinates") and len(b["coordinates"]) == 4]
    return sorted(valid_boxes, key=lambda x: (get_center_y(x['coordinates']), get_center_x(x['coordinates'])))


def group_lines(boxes):
    """Gom box chữ thành dòng theo trục y; khối ảnh/bảng thành dòng riêng.

    Ô bảng (table_cell) chỉ gom với ô cùng bảng, để mỗi dòng là một hàng của bảng.
    """
    text = [b for b in boxes if not is_block(b)]
    blocks = [b for b in boxes if is_block(b)]

    lines = []
    if text:
        # Chỉ lấy chiều cao box chữ: ô giả của ảnh/bảng cao cả khối sẽ làm ngưỡng gom dòng sai
        avg_height = sum(get_height(b['coordinates']) for b in text) / len(text)
        y_threshold = avg_height * 0.5

        current, prev_y = [], None
        for b in text:
            y = get_center_y(b['coordinates'])
            same_table = not current or current[-1].get("table_id") == b.get("table_id")
            if prev_y is None or (abs(y - prev_y) < y_threshold and same_table):
                current.append(b)
            else:
                lines.append(current)
                current = [b]
            prev_y = sum(get_center_y(box['coordinates']) for box in current) / len(current)
        if current:
            lines.append(current)

        for line in lines:
            line.sort(key=lambda x: get_center_x(x['coordinates']))

    # Sắp lại theo trục y: dòng chữ theo tâm, khối theo cạnh trên (nhãn bảng đứng trước các hàng của nó)
    keyed = [(sum(get_center_y(b['coordinates']) for b in line) / len(line), 1, line) for line in lines]
    keyed += [(get_top_y(b['coordinates']) - 1, 0, [b]) for b in blocks]
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [line for _, _, line in keyed]


# =========================
# THỨ TỰ ĐỌC THEO VÙNG BỐ CỤC (nhiều cột)
# =========================
def order_regions(regions):
    """Chia các vùng bố cục thành các nhóm đọc liền mạch, theo thứ tự đọc tự nhiên.

    Vùng được chia thành các dải theo trục y (các vùng có khoảng y chồng nhau thuộc cùng một dải).
    Trong một dải không có vùng trải rộng cả trang, nếu có vùng ở cả hai phía đường giữa trang thì
    đọc hết cột trái rồi mới tới cột phải; ngược lại đọc từ trên xuống.
    """
    left = min(r["bbox"][0] for r in regions)
    right = max(r["bbox"][2] for r in regions)
    width = max(1, right - left)
    mid = (left + right) / 2

    def spans_page(r):
        x1, _, x2, _ = r["bbox"]
        return (x2 - x1) >= 0.6 * width or (x1 < mid - 0.05 * width and x2 > mid + 0.05 * width)

    bands = []
    for r in sorted(regions, key=lambda r: (r["bbox"][1], r["bbox"][0])):
        if bands and r["bbox"][1] < bands[-1]["y2"]:
            bands[-1]["items"].append(r)
            bands[-1]["y2"] = max(bands[-1]["y2"], r["bbox"][3])
        else:
            bands.append({"y2": r["bbox"][3], "items": [r]})

    # Mỗi nhóm = các vùng đọc liền một mạch (một cột của dải, hoặc cả dải); trả về theo thứ tự đọc
    groups = []
    for band in bands:
        items = band["items"]
        cx = lambda r: (r["bbox"][0] + r["bbox"][2]) / 2
        lefts = [r for r in items if cx(r) < mid]
        rights = [r for r in items if cx(r) >= mid]
        if lefts and rights and not any(spans_page(r) for r in items):
            # Thụt lề của cột phải tính từ mép trái cột phải, không phải mép trái trang
            base = min(r["bbox"][0] for r in rights)
            groups += [{"regions": lefts}, {"regions": rights, "indent_base": base}]
        else:
            groups.append({"regions": items})
    return groups


def reading_order_lines(boxes):
    """Gom dòng trong từng vùng bố cục rồi nối các vùng theo thứ tự đọc.

    Box không mang thông tin vùng (dữ liệu cũ) thì gom dòng trên cả trang như trước.
    """
    boxes = sort_boxes(boxes)
    for b in boxes:
        b.pop("_indent_base", None)
    if not boxes or any(not b.get("region_bbox") for b in boxes):
        return group_lines(boxes)
    regions = {}
    for b in boxes:
        regions.setdefault(b.get("region_id"), {"bbox": b["region_bbox"], "boxes": []})["boxes"].append(b)
    # Vùng chỉ dùng để biết box thuộc cột nào; trong một cột gom dòng trên toàn bộ box của cột,
    # vì YOLO có thể trả nhiều vùng chồng nhau trong cùng một cột
    lines = []
    for g in order_regions(list(regions.values())):
        group_boxes = [b for r in g["regions"] for b in r["boxes"]]
        if "indent_base" in g:
            for b in group_boxes:
                b["_indent_base"] = g["indent_base"]
        lines += group_lines(sort_boxes(group_boxes))
    return lines


# =========================
# OUTPUT BUILDERS (văn bản Markdown + JSON)
# =========================
def is_table_row(line):
    return bool(line) and all(b.get("content_type") == "table_cell" for b in line)


def detect_columns(rows):
    """Tìm mép trái các cột: gom mép trái (x_min) của box, giữ cụm xuất hiện ở >= 2 hàng.

    Chữ căn đều bị Paddle tách thành nhiều box trong một ô chỉ xuất hiện ở một hàng
    nên không tạo cột giả.
    """
    xs = [min(p[0] for p in b["coordinates"]) for r in rows for b in r]
    width = max(max(p[0] for p in b["coordinates"]) for r in rows for b in r) - min(xs)
    tol = max(25, 0.02 * width)

    clusters = []  # [x_trung_bình, tập_hàng]
    for x, ri in sorted((min(p[0] for p in b["coordinates"]), ri) for ri, r in enumerate(rows) for b in r):
        if clusters and x - clusters[-1][0] <= tol:
            c = clusters[-1]
            c[0] = (c[0] * c[2] + x) / (c[2] + 1)
            c[1].add(ri)
            c[2] += 1
        else:
            clusters.append([x, {ri}, 1])
    starts = [c[0] for c in clusters if len(c[1]) >= 2]
    return (starts or [min(xs)]), tol


def render_table(rows):
    """Các hàng của một bảng -> bảng Markdown (hàng đầu làm tiêu đề).

    Box được gán vào cột có mép trái gần nhất bên trái nó; hàng trống ở cột đầu
    là dòng tiếp theo của ô nhiều dòng nên được nối vào hàng trước.
    """
    starts, tol = detect_columns(rows)
    ncols = len(starts)

    table = []
    for row in rows:
        cells = [[] for _ in range(ncols)]
        for b in sorted(row, key=lambda b: min(p[0] for p in b["coordinates"])):
            x = min(p[0] for p in b["coordinates"])
            col = max([i for i, s in enumerate(starts) if s <= x + tol] or [0])
            text = (b.get("recognized_text") or "").strip()
            if text:
                cells[col].append(text)
        cells = [" ".join(c) for c in cells]
        if table and not cells[0] and any(cells):
            prev = table[-1]
            for i, c in enumerate(cells):
                if c:
                    prev[i] = f"{prev[i]} {c}".strip()
        elif any(cells):
            table.append(cells)

    out = []
    for i, cells in enumerate(table):
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        if i == 0:
            out.append("|" + "|".join([" --- "] * ncols) + "|")
    return out


def build_text(lines):
    if not lines:
        return ""

    text_boxes = [b for line in lines for b in line if b.get("coordinates") and not is_block(b)]
    min_x_global = min((min(p[0] for p in b["coordinates"]) for b in text_boxes), default=0)
    CHAR_WIDTH = 45
    out = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Gom các hàng liên tiếp của cùng một bảng -> bảng Markdown
        if is_table_row(line):
            table_id = line[0].get("table_id")
            rows = []
            while i < len(lines) and is_table_row(lines[i]) and lines[i][0].get("table_id") == table_id:
                rows.append(lines[i])
                i += 1
            out += [""] + render_table(rows) + [""]
            continue

        # Khối ảnh/bảng: nhãn tham chiếu tới ảnh đã lưu trong assets/
        if len(line) == 1 and is_block(line[0]):
            out += ["", line[0].get("recognized_text", "")]
            i += 1
            continue

        line_str = ""
        is_title = any(b.get("content_type") == "title" for b in line)
        is_list = any(b.get("content_type") == "list" for b in line)

        for j, b in enumerate(line):
            text = b.get("recognized_text", "")
            if not text:
                continue

            x_min = min(p[0] for p in b["coordinates"])
            if j == 0:
                base_x = line[0].get("_indent_base", min_x_global)
                indent_spaces = int((x_min - base_x) / CHAR_WIDTH)
                line_str += " " * max(0, indent_spaces)
            else:
                prev_x_max = max(p[0] for p in line[j - 1]["coordinates"])
                gap_spaces = int((x_min - prev_x_max) / CHAR_WIDTH)
                line_str += " " * max(1, gap_spaces)
            line_str += text

        final_line = line_str.rstrip()
        if not final_line.strip():
            i += 1
            continue

        # Bọc thẻ Markdown tăng tính cấu trúc văn bản
        if is_title:
            out += ["", f"# {final_line.strip()}", ""]
        elif is_list:
            out.append(f"- {final_line.strip()}")
        else:
            out.append(final_line)
        i += 1

    return "\n".join(out).strip("\n") + "\n"


def build_json(image, lines):
    return {
        "source_image": image,
        "processed_at": time.time(),
        "lines": [
            {
                "line_id": i,
                "line_type": line[0].get("content_type", "text") if line else "text",
                "line_text": " ".join(b.get("recognized_text", "") for b in line if b.get("recognized_text")).strip(),
                "elements": [
                    {
                        "box_id": b.get("box_id"),
                        "type": b.get("content_type", "text"),
                        "table_id": b.get("table_id"),
                        "text": b.get("recognized_text", ""),
                        "coordinates": b.get("coordinates"),
                        "region_id": b.get("region_id"),
                        "region_bbox": b.get("region_bbox"),
                        "s3_asset_url": b.get("s3_key") if b.get("content_type") in ["figure", "table"] else None
                    } for b in line
                ]
            }
            for i, line in enumerate(lines)
        ]
    }


def page_keys(image):
    base_name = os.path.splitext(os.path.basename(image))[0]
    sub_path = os.path.dirname(image).replace("pic/", "", 1)
    return base_name, f"text/{sub_path}/{base_name}.txt", f"preprocessed/{sub_path}/{base_name}.json"


def load_stored_boxes(s3, image):
    """Box của trang đã ghi trên MinIO (nếu có).

    Khi worker khởi động lại hoặc box đến muộn sau khi bộ đệm bị dọn, Kafka giao lại một phần thông điệp;
    nạp lại box đã lưu để không ghi đè trang đầy đủ bằng một bản thiếu.
    """
    _, _, json_key = page_keys(image)
    try:
        doc = json.loads(s3.get_object(Bucket=BUCKET, Key=json_key)["Body"].read().decode("utf-8"))
    except Exception:
        return {}
    boxes = {}
    for line in doc.get("lines", []):
        for el in line.get("elements", []):
            if el.get("box_id") is None:
                continue
            boxes[el["box_id"]] = {
                "box_id": el["box_id"],
                "content_type": el.get("type", "text"),
                "table_id": el.get("table_id"),
                "recognized_text": el.get("text", ""),
                "coordinates": el.get("coordinates"),
                "s3_key": el.get("s3_asset_url"),
                "region_id": el.get("region_id"),
                "region_bbox": el.get("region_bbox"),
            }
    return boxes


# =========================
# MAIN LOOP
# =========================
def main():
    broker = os.getenv("KAFKA_BROKER", "kafka:9092")
    consumer = KafkaConsumer(
        "ocr-completed",
        bootstrap_servers=[broker],
        group_id="reconstruct-group",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        max_poll_records=100,
        value_deserializer=lambda m: json.loads(m.decode("utf-8"))
    )
    producer = KafkaProducer(
        bootstrap_servers=[broker],
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8")
    )
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"]
    )

    logging.info("Reconstruct worker started...")

    # Offset của box đã nhận nhưng trang chưa được ghi lên MinIO: chỉ commit tới offset nhỏ nhất trong số này,
    # để reconstruct sập giữa chừng thì Kafka giao lại các box đó (at-least-once).
    pending = {}      # TopicPartition -> {offset: image}
    next_offset = {}  # TopicPartition -> offset kế tiếp đã đọc
    committed = {}

    while True:
        msg_pack = consumer.poll(timeout_ms=500)

        for tp, msgs in msg_pack.items():
            for msg in msgs:
                next_offset[tp] = msg.offset + 1
                try:
                    data = msg.value
                    image = data.get("original_image")
                    box_id = data.get("box_id")
                    total = data.get("total_boxes")

                    if image is None or box_id is None:
                        continue

                    if image not in document_buffer:
                        document_buffer[image] = {
                            "last_seen": time.time(),
                            "dirty": True,
                            "boxes": load_stored_boxes(s3, image),
                            "offsets": [],
                            "total_boxes": total,
                            "total_pages": data.get("total_pages"),
                            "document_id": data.get("document_id", "unknown")
                        }

                    buf = document_buffer[image]
                    if buf["total_boxes"] is None and total is not None:
                        buf["total_boxes"] = total
                    if buf.get("total_pages") is None and data.get("total_pages") is not None:
                        buf["total_pages"] = data.get("total_pages")

                    buf["boxes"][box_id] = data
                    buf["last_seen"] = time.time()
                    buf["dirty"] = True
                    buf["offsets"].append((tp, msg.offset))
                    pending.setdefault(tp, {})[msg.offset] = image
                except Exception as e:
                    logging.error(f"Error parsing message: {e}")

        # Quét bộ đệm: ghi trang đủ box hoặc quá thời gian chờ
        now = time.time()
        for image, buf in list(document_buffer.items()):
            received = len(buf["boxes"])
            total = buf["total_boxes"]
            idle = now - buf["last_seen"]

            # Đã ghi, không có box mới: chỉ dọn RAM sau một thời gian
            if not buf["dirty"]:
                if idle > EVICT_AFTER:
                    del document_buffer[image]
                continue
            if now < buf.get("retry_at", 0):
                continue

            is_done = (total is not None) and (received >= total)
            is_timeout = idle > TIMEOUT

            if is_done or is_timeout:
                if is_done:
                    logging.info(f"SUCCESS {image}: Gathered {received}/{total} boxes.")
                else:
                    logging.warning(f"TIMEOUT {image}: Gathered {received}/{total} boxes (sẽ ghép lại nếu box đến muộn).")

                try:
                    lines = reading_order_lines(list(buf["boxes"].values()))
                    text_content = build_text(lines)
                    json_content = build_json(image, lines)
                    base_name, txt_key, json_key = page_keys(image)

                    s3.put_object(Bucket=BUCKET, Key=txt_key, Body=text_content.encode("utf-8"))
                    s3.put_object(Bucket=BUCKET, Key=json_key, Body=json.dumps(json_content, ensure_ascii=False).encode("utf-8"))

                    producer.send(
                        "document-completed",
                        value={
                            "document_id": buf["document_id"],
                            "total_pages": buf.get("total_pages"),
                            "page_name": base_name,
                            "original_image": image,
                            "text_path": txt_key,
                            "json_path": json_key,
                            "status": "success" if is_done else "partial",
                            "boxes_processed": received,
                            "total_boxes": total
                        }
                    )
                    producer.flush()
                    # Trang đã nằm trên MinIO: các box của nó không cần Kafka giao lại nữa
                    for tp, off in buf["offsets"]:
                        pending.get(tp, {}).pop(off, None)
                    buf["offsets"] = []
                    # Giữ lại (kể cả trang đủ box) để box đến muộn / tin nhắn gửi lại không tạo ra trang thiếu
                    buf["dirty"] = False
                except Exception as e:
                    logging.error(f"Error saving reconstruct for {image}: {e} (thử lại sau 10 giây)")
                    buf["retry_at"] = now + 10

        # Commit tới offset nhỏ nhất của box chưa được ghi (hoặc offset kế tiếp nếu không còn box nào chờ)
        commits = {}
        for tp, nxt in next_offset.items():
            waiting = pending.get(tp)
            off = min(waiting) if waiting else nxt
            if committed.get(tp) != off:
                commits[tp] = OffsetAndMetadata(off, None)
        if commits:
            try:
                consumer.commit(offsets=commits)
                committed.update({tp: c.offset for tp, c in commits.items()})
            except Exception as e:
                logging.warning(f"Commit offset failed: {e}")

if __name__ == "__main__":
    main()
