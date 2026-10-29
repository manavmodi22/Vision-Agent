# YOLOX adapted source notice

`yolox_ops.py` and the class vocabulary in `yolox_config.py` adapt code from
Megvii-BaseDetection/YOLOX at commit
`6ddff4824372906469a7fae2dc3206c7aa4bbaee`, Copyright (c) Megvii Inc. and its
affiliates. Licensed under Apache License 2.0; the complete license is included
in `YOLOX-Apache-2.0.txt`.

Original files: `yolox/data/data_augment.py`, `yolox/utils/demo_utils.py`, and
`yolox/data/datasets/coco_classes.py` from
https://github.com/Megvii-BaseDetection/YOLOX/tree/6ddff4824372906469a7fae2dc3206c7aa4bbaee.
Modifications: fixed 640x640 model contract; typed functions; image conversion;
strict finite/value checks; output normalization; local artifact validation and
bounded CPU session lifecycle. Raw BGR input, top-left 114 padding, stride decode,
inclusive-pixel class-agnostic NMS and post-NMS class filtering are preserved.

The ONNX checkpoint is downloaded separately by explicit installation approval.
It is not included in the source repository or app package. Its identity is the
official `0.1.1rc0` release asset `yolox_s.onnx`, size 35,858,002 bytes, SHA256
`c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`.
License attribution uses the official repository's Apache-2.0 declaration;
the inspected release supplies no separate asset-specific license statement.
This is not a claim of separately verified weight or training-image rights.
