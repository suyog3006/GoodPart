"""Image quality checks, scale-marker detection and registration to the reference image."""
from __future__ import annotations

import cv2
import numpy as np


def quality(rgb: np.ndarray) -> dict:
    g = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
    sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
    mean = float(g.mean())
    clipped = float(((g < 5) | (g > 250)).mean())
    flags = []
    if sharp < 20:
        flags.append("blurry")
    if mean < 30:
        flags.append("too dark")
    if mean > 225:
        flags.append("too bright")
    if clipped > 0.25:
        flags.append("clipped exposure")
    return {"sharpness": sharp, "brightness": mean, "clipped": clipped, "flags": flags}


def fingerprint(rgb: np.ndarray) -> np.ndarray:
    """Tiny grey thumbnail for duplicate detection."""
    g = cv2.resize(cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY), (16, 16), interpolation=cv2.INTER_AREA)
    return (g.astype(np.float32) - g.mean()) / (g.std() + 1e-6)


def duplicates(images, thr: float = 0.995) -> list[tuple[int, int]]:
    fps = np.stack([fingerprint(im).ravel() for im in images]) / 256
    sim = fps @ fps.T
    i, j = np.nonzero(np.triu(sim, 1) > thr)
    return list(zip(i.tolist(), j.tolist()))


def pick_reference(images) -> int:
    """Sharpest image among those closest to the median appearance."""
    fps = np.stack([fingerprint(im).ravel() for im in images])
    dist = np.linalg.norm(fps - np.median(fps, 0), axis=1)
    cand = np.argsort(dist)[: max(3, len(images) // 4)]
    return int(max(cand, key=lambda i: quality(images[i])["sharpness"]))


def detect_scale(rgb: np.ndarray, marker_mm: float = 20.0) -> dict | None:
    """mm per pixel from a printed ArUco marker (DICT_4X4_50) of known side length."""
    g = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    corners, ids, _ = det.detectMarkers(g)
    if ids is None or not len(corners):
        return None
    c = corners[0][0]
    side_px = float(np.mean([np.linalg.norm(c[i] - c[(i + 1) % 4]) for i in range(4)]))
    return {"mm_per_px": marker_mm / side_px, "marker_id": int(ids[0][0]), "corners": c.tolist()}


class Registrar:
    """ORB keypoints + RANSAC homography to the reference; identity when the image is already aligned."""

    def __init__(self, reference: np.ndarray, n_features: int = 3000):
        self.ref = np.asarray(reference)
        self.orb = cv2.ORB_create(n_features)
        self.kp, self.des = self.orb.detectAndCompute(cv2.cvtColor(self.ref, cv2.COLOR_RGB2GRAY), None)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    def align(self, rgb: np.ndarray, min_inliers: int = 25) -> dict:
        img = np.asarray(rgb)
        kp, des = self.orb.detectAndCompute(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), None)
        if des is None or self.des is None or len(kp) < min_inliers:
            return {"ok": False, "reason": "too few keypoints (blurry, empty or wrong part?)", "image": img}
        m = sorted(self.matcher.match(des, self.des), key=lambda x: x.distance)[:500]
        if len(m) < min_inliers:
            return {"ok": False, "reason": "too few matches to the reference", "image": img}
        src = np.float32([kp[x.queryIdx].pt for x in m])
        dst = np.float32([self.kp[x.trainIdx].pt for x in m])
        H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        n_in = int(inl.sum()) if inl is not None else 0
        if H is None or n_in < min_inliers:
            return {"ok": False, "reason": "registration failed", "image": img, "inliers": n_in}
        # Reject implausible warps (large scale change or perspective) as a wrong part / bad capture.
        s = np.sqrt(abs(np.linalg.det(H[:2, :2])))
        if not 0.7 < s < 1.4 or np.abs(H[2, :2]).max() > 2e-3:
            return {"ok": False, "reason": "implausible alignment", "image": img, "inliers": n_in}
        h, w = self.ref.shape[:2]
        warped = cv2.warpPerspective(img, H, (w, h), borderMode=cv2.BORDER_REPLICATE)
        return {"ok": True, "image": warped, "inliers": n_in, "scale": float(s), "H": H.tolist()}
