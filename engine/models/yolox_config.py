"""Pinned official YOLOX-s release and exact upstream COCO vocabulary.

Class names adapted from Megvii YOLOX, Apache-2.0; see licenses/YOLOX-NOTICE.md.
"""

MODEL_ID = "yolox-s-onnx-coco"
ADAPTER_ID = "yolox-onnx"
MODEL_FILENAME = "model.onnx"
MODEL_SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
MODEL_BYTES = 35_858_002
SOURCE_COMMIT = "6ddff4824372906469a7fae2dc3206c7aa4bbaee"
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx"
INPUT_SIZE = 640
NMS_IOU = 0.45
INTRA_OP_THREADS = 4
INTER_OP_THREADS = 1
COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)
