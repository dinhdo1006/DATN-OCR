import os
import cv2
import json
import time
import boto3
import logging
import numpy as np

from kafka import KafkaConsumer
from kafka import KafkaProducer

from paddleocr import PaddleOCR


# =====================================================
# LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# =====================================================
# OCR DETECTOR
# =====================================================

logging.info("Loading PaddleOCR detector")

ocr = PaddleOCR(
    lang="vi",
    rec=False,
    use_angle_cls=False,
    show_log=False
)

logging.info("Paddle detector ready")


# =====================================================
# MINIO
# =====================================================

s3 = boto3.client(
    "s3",

    endpoint_url=os.getenv(
        "MINIO_ENDPOINT",
        "http://minio:9000"
    ),

    aws_access_key_id=os.getenv(
        "MINIO_ACCESS_KEY",
        "admin"
    ),

    aws_secret_access_key=os.environ["MINIO_SECRET_KEY"]
)


# =====================================================
# KAFKA
# =====================================================

broker = os.getenv(
    "KAFKA_BROKER",
    "kafka:9092"
)

consumer = KafkaConsumer(
    "layout-completed",

    bootstrap_servers=[broker],

    group_id="text-crop-group",

    auto_offset_reset="latest",

    enable_auto_commit=True,

    value_deserializer=lambda x:
    json.loads(
        x.decode()
    )
)

producer = KafkaProducer(

    bootstrap_servers=[broker],

    value_serializer=lambda v:
    json.dumps(v).encode()
)


# =====================================================
# HELPERS
# =====================================================

def crop_rotate(img, box):

    pts = np.array(
        box,
        dtype=np.float32
    )

    w = int(max(
        np.linalg.norm(
            pts[0]-pts[1]
        ),

        np.linalg.norm(
            pts[2]-pts[3]
        )
    ))

    h = int(max(
        np.linalg.norm(
            pts[0]-pts[3]
        ),

        np.linalg.norm(
            pts[1]-pts[2]
        )
    ))

    if w <= 0 or h <= 0:
        return None

    dst = np.float32([
        [0,0],
        [w,0],
        [w,h],
        [0,h]
    ])

    M = cv2.getPerspectiveTransform(
        pts,
        dst
    )

    return cv2.warpPerspective(
        img,
        M,
        (w,h)
    )


# =====================================================
# LOOP
# =====================================================

for msg in consumer:

    try:

        data = msg.value

        bucket = data["bucket"]

        image_path = data[
            "original_image"
        ]

        regions = data[
            "regions"
        ]

        obj = s3.get_object(
            Bucket=bucket,
            Key=image_path
        )

        page = cv2.imdecode(
            np.frombuffer(
                obj["Body"].read(),
                np.uint8
            ),

            cv2.IMREAD_COLOR
        )

        total = 0

        for region in regions:

            if region[
                "type"
            ] != "text":

                continue

            x1,y1,x2,y2 = (
                region[
                    "bbox"
                ]
            )

            block = page[
                y1:y2,
                x1:x2
            ]

            dt_boxes,_ = (
                ocr.text_detector(
                    block
                )
            )

            if (
                dt_boxes
                is None
            ):
                continue

            for box_id,box in enumerate(
                dt_boxes
            ):

                crop = crop_rotate(
                    block,
                    box
                )

                if crop is None:
                    continue

                ok,buf = (
                    cv2.imencode(
                        ".png",
                        crop
                    )
                )

                if not ok:
                    continue

                key = (
                    f"crop/"
                    f"{data['document_id']}/"
                    f"{data['page']}_"
                    f"{total}.png"
                )

                s3.put_object(

                    Bucket=bucket,

                    Key=key,

                    Body=buf
                )

                producer.send(

                    "crop-completed",

                    value={

                        "document_id":
                        data[
                            "document_id"
                        ],

                        "page":
                        data[
                            "page"
                        ],

                        "bucket":
                        bucket,

                        "s3_key":
                        key,

                        "box_id":
                        total,

                        "coordinates":
                        box.tolist(),

                        "created_at":
                        time.time()
                    }
                )

                total += 1

        producer.flush()

        logging.info(
            f"Done "
            f"{image_path}"
        )

    except Exception as e:

        logging.exception(e)