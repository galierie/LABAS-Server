from __future__ import annotations
from pydantic import BaseModel
from typing import TypedDict
import argparse
import json
import sys
import base64

import cv2
import numpy as np

from phases.print_constants import (
    PAGE_WIDTH, PAGE_HEIGHT,
    BUBBLE_RADIUS,
    MARKER_SIZE, MARKER_POSITIONS,
)

# from printing import 

PAGE_WIDTH_PT = PAGE_WIDTH
PAGE_HEIGHT_PT = PAGE_HEIGHT
BUBBLE_RADIUS_PT = BUBBLE_RADIUS

MARKERS_PT = [(x + MARKER_SIZE / 2, y + MARKER_SIZE / 2)
              for (x, y) in MARKER_POSITIONS]

DEFAULT_THRESHOLD = 0.4
ALIGN_DPI = 200

# Base Models

class BubbleCoordinate(TypedDict):
    candidate_id: int
    bubble_x_pt: float
    bubble_y_pt: float
    page: int

class OMRInputData(BaseModel):
    coords_json: list[BubbleCoordinate]
    scan_bytes: bytes

def detect_corners(gray):
    h, w = gray.shape
    page_diag = (h * h + w * w) ** 0.5
    min_area = (0.003 * page_diag) ** 2
    max_area = (0.04 * page_diag) ** 2

    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binv = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(
        binv, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    corner_band = 0.25
    bx, by = corner_band * w, corner_band * h

    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        aspect = bw / float(bh) if bh else 0
        if not (0.7 < aspect < 1.4):
            continue
        if area / (bw * bh) < 0.75:
            continue
        cx, cy = x + bw / 2, y + bh / 2
        in_corner = ((cx < bx or cx > w - bx) and
                     (cy < by or cy > h - by))
        if not in_corner:
            continue
        candidates.append((cx, cy, area))

    if len(candidates) < 4:
        raise RuntimeError(f"Found only {len(candidates)} corners.")

    image_corners = [(0, 0), (w, 0), (0, h), (w, h)]
    chosen = []
    used = set()
    for ix, iy in image_corners:
        ranked = sorted(candidates,
                        key=lambda p: (p[0] - ix) ** 2 + (p[1] - iy) ** 2)
        pick = next((p for p in ranked if (p[0], p[1]) not in used), ranked[0])
        used.add((pick[0], pick[1]))
        chosen.append((pick[0], pick[1]))
    return np.array(chosen, dtype=np.float32)


def order_corners(pts):
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    return np.array([pts[np.argmin(s)],
                     pts[np.argmax(d)],
                     pts[np.argmin(d)],
                     pts[np.argmax(s)]],
                    dtype=np.float32)


def align(img, markers_px, dpi=ALIGN_DPI):
    scale = dpi / 72.0
    out_w, out_h = int(PAGE_WIDTH_PT * scale), int(PAGE_HEIGHT_PT * scale)

    canon = np.array(MARKERS_PT, dtype=np.float32)
    canon[:, 1] = PAGE_HEIGHT_PT - canon[:, 1]
    canon *= scale

    src = order_corners(markers_px)
    dst = order_corners(canon)
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (out_w, out_h),
                                 borderValue=(255, 255, 255))
    return warped, scale


def measure_fill(bin_inv, cx, cy, r):
    r = max(2, r * 0.78)
    h, w = bin_inv.shape
    x0, x1 = max(0, int(cx - r)), min(w, int(cx + r) + 1)
    y0, y1 = max(0, int(cy - r)), min(h, int(cy + r) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    if not mask.any():
        return 0.0
    return float(np.mean(bin_inv[y0:y1, x0:x1][mask] > 0))


def check_page(input: OMRInputData, threshold=DEFAULT_THRESHOLD) -> tuple[list[int], bytes]:
    bubbles = input.coords_json

    # Decode the base64 string into raw image bytes
    # image_bytes = base64.b64decode(input.scan_bytes)
    image_bytes = input.scan_bytes
    
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    markers = detect_corners(gray)
    warped, scale = align(img, markers)
    radius_px = BUBBLE_RADIUS_PT * scale

    warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    _, bin_inv = cv2.threshold(
        cv2.GaussianBlur(warped_gray, (5, 5), 0),
        0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    results = []
    debug_records = []

    for b in bubbles:
        cx = b["bubble_x_pt"] * scale
        cy = (PAGE_HEIGHT_PT - b["bubble_y_pt"]) * scale
        fill = measure_fill(bin_inv, cx, cy, radius_px)
        debug_records.append((cx, cy, fill))
        if fill >= threshold:
            results.append(b["candidate_id"])

    dbg = cv2.cvtColor(warped_gray, cv2.COLOR_GRAY2BGR)
    for cx, cy, fill in debug_records:
        color = (0, 200, 0) if fill >= threshold else (60, 60, 200)
        cv2.circle(dbg, (int(cx), int(cy)), int(radius_px), color, 2)

    _, buf = cv2.imencode(".png", dbg)
    # cv2.imwrite("debug.png", dbg)

    return results, buf.tobytes()


# def main():
#     ap = argparse.ArgumentParser()
#     ap.add_argument("coords_json")
#     ap.add_argument("img")
#     args = ap.parse_args()

#     with open(args.img, "rb") as f:
#         scan_bytes = f.read()

#     results, debug_png = check_page(
#         args.coords_json, scan_bytes)


# if __name__ == "__main__":
#     sys.exit(main() or 0)
