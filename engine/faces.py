#!/usr/bin/env python3
"""Which side of the frame has a face, for each image given. Runs in /root/venv-qc (mediapipe), never in ComfyUI's environment.

Usage: faces.py <image> [<image> ...]  ->  one JSON line: [{"left": bool, "right": bool, "faces": int}, ...]
Left or right is decided by the nose tip's position in the frame, as av_qc.py does.
"""
import json
import sys


def main() -> None:
    import cv2
    import mediapipe as mp
    mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2, refine_landmarks=False, min_detection_confidence=0.3)
    out = []
    for path in sys.argv[1:]:
        image = cv2.imread(path)
        if image is None:
            raise SystemExit(f"cannot read {path}")
        res = mesh.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        sides = {"left": False, "right": False, "faces": 0}
        for lm in res.multi_face_landmarks or []:
            sides["faces"] += 1
            sides["left" if lm.landmark[1].x < 0.5 else "right"] = True
        out.append(sides)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
