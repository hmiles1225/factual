# Models

`face_detection_yunet_2023mar.onnx`: YuNet face detector, from the OpenCV model zoo
(github.com/opencv/opencv_zoo, models/face_detection_yunet). MIT License, Copyright (c) 2020 Shiqi Yu.
Used by `pipeline/images.py` `face()` to find where the face is in a photo, so the site can frame it.
It finds a face; it never identifies anyone.
