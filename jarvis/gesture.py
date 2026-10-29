"""Hand tracking through the camera, for steering holograms with gestures.

The camera runs only while the HUD asks for it (a hologram or demo is on screen). Each frame goes through the
system's hand-pose detector (Apple Vision on macOS, MediaPipe elsewhere; see platforms/), offline; for every hand
we send the HUD a few numbers: palm and index-tip position (mirrored, 0..1 from top-left), how many fingers
are stretched out, and the thumb-index pinch. The HUD turns those into gestures (hud/index.html, "hand").
Messages: {"type":"hand","hands":[{"x","y","ix","iy","ext","fx","pinch","ip","im","s"}]}, {"type":"hand","status":...}
and {"type":"hand_frame","jpg":base64} (a small preview with the skeleton drawn on it).
"""
import math, threading, time

UI = None              # set by the service: UI(msg) sends to the HUD
FPS = 8                # Vision + JPEG per frame: 8 a second is plenty for gestures and leaves the CPU to the hologram


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} gesture: {msg}", flush=True)


def _d(a, b, ar):
    return math.hypot((a[0] - b[0]) * ar, a[1] - b[1])


def features(pts, ar=4 / 3):
    """pts: joint -> (x, y) in image space, 0..1 from the TOP-LEFT of the mirrored picture. ar = width / height."""
    need = ("wrist", "index_mcp", "middle_mcp", "little_mcp")
    if any(k not in pts for k in need):
        return None
    w = pts["wrist"]
    size = _d(w, pts["middle_mcp"], ar)
    if size < 0.02:
        return None
    fx = ""                                   # which of index, middle, ring, little are stretched out: "1000" = pointing
    for f in ("index", "middle", "ring", "little"):
        tip, pip = pts.get(f + "_tip"), pts.get(f + "_pip")
        fx += "1" if tip and pip and _d(w, tip, ar) > _d(w, pip, ar) * 1.18 else "0"
    pinch = _d(pts["thumb_tip"], pts["index_tip"], ar) / size if "thumb_tip" in pts and "index_tip" in pts else 9.0
    palm = [sum(pts[k][i] for k in need) / 4 for i in (0, 1)]
    tip = pts.get("index_tip", palm)
    ip = _d(tip, palm, ar) / size             # index tip to palm: small when curled into a fist, larger in a pinch
    im = _d(tip, pts["index_mcp"], ar) / size  # index tip to its knuckle: a fist curls it right back, a pinch does not
    return {"x": round(palm[0], 4), "y": round(palm[1], 4), "ix": round(tip[0], 4), "iy": round(tip[1], 4),
            "ext": fx.count("1"), "fx": fx, "pinch": round(pinch, 3), "ip": round(ip, 3), "im": round(im, 3), "s": round(size, 4)}


class Tracker:
    def __init__(self):
        self.want = False
        self.thread = None
        self.lock = threading.Lock()

    def set(self, on):
        with self.lock:
            self.want = bool(on)
            if self.want and not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _send(self, msg):
        if UI:
            try:
                UI(msg)
            except Exception:
                pass

    BONES = [("wrist", "thumb_mp"), ("thumb_mp", "thumb_ip"), ("thumb_ip", "thumb_tip"), ("wrist", "index_mcp"), ("index_mcp", "index_pip"),
             ("index_pip", "index_tip"), ("wrist", "middle_mcp"), ("middle_mcp", "middle_pip"), ("middle_pip", "middle_tip"),
             ("ring_mcp", "ring_pip"), ("ring_pip", "ring_tip"), ("wrist", "little_mcp"), ("little_mcp", "little_pip"), ("little_pip", "little_tip"),
             ("index_mcp", "middle_mcp"), ("middle_mcp", "ring_mcp"), ("ring_mcp", "little_mcp")]

    def _preview(self, cv2, frame, drawn):
        """A small mirrored picture with the detected hand skeleton, for the HUD's camera window (about 5 a second)."""
        if time.time() - getattr(self, "_pv_at", 0) < 0.19:
            return
        self._pv_at = time.time()
        import base64
        img = cv2.resize(cv2.flip(frame, 1), (224, 168), interpolation=cv2.INTER_AREA)
        img = cv2.convertScaleAbs(img, alpha=0.75, beta=0)
        W, H = img.shape[1], img.shape[0]
        for pts in drawn:
            P = {k: (int(x * W), int(y * H)) for k, (x, y) in pts.items()}
            for a, b in self.BONES:
                if a in P and b in P:
                    cv2.line(img, P[a], P[b], (255, 217, 115), 2, cv2.LINE_AA)
            for k, q in P.items():
                cv2.circle(img, q, 4 if k.endswith("tip") else 3, (200, 240, 255) if k != "index_tip" else (122, 178, 255), -1, cv2.LINE_AA)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if ok:
            self._send({"type": "hand_frame", "jpg": base64.b64encode(jpg.tobytes()).decode()})

    def _run(self):
        try:
            import cv2
            from . import platforms
            det = platforms.hand_detector()
        except Exception as e:
            log(f"cannot start: {e}")
            self._send({"type": "hand", "status": "missing", "error": str(e)[:200]})
            return
        cap = platforms.open_camera(lambda: self.want, self._send)
        if cap is None:
            log("no camera")
            self._send({"type": "hand", "status": "no_camera"})
            return
        log("camera on")
        self._send({"type": "hand", "status": "on"})
        frames = seen = 0
        t_log = time.time()
        empty_at = 0.0
        try:
            while self.want:
                t0 = time.time()
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue
                if frame.shape[1] > 480:                    # hands are found fine at 480 px, at half the cost of 640
                    frame = cv2.resize(frame, (480, int(frame.shape[0] * 480 / frame.shape[1])), interpolation=cv2.INTER_AREA)
                h, w = frame.shape[:2]
                hands, drawn = [], []
                for pts in det.detect(frame):
                    f = features(pts, w / h)
                    if f:
                        hands.append(f)
                        drawn.append(pts)
                frames += 1
                self._preview(cv2, frame, drawn)
                if hands:
                    seen += 1
                    self._send({"type": "hand", "hands": hands})
                elif time.time() - empty_at > 0.5:
                    empty_at = time.time()
                    self._send({"type": "hand", "hands": []})
                if time.time() - t_log > 30:
                    log(f"{frames} frames, hands in {seen}")
                    frames = seen = 0
                    t_log = time.time()
                time.sleep(max(0.0, 1.0 / FPS - (time.time() - t0)))
        except Exception as e:
            log(f"stopped: {type(e).__name__}: {e}")
        finally:
            cap.release()
            log("camera off")
            self._send({"type": "hand", "status": "off"})


TRACKER = Tracker()


def selftest():
    """Check the pieces without opening the camera."""
    import cv2, numpy as np
    from . import platforms
    det = platforms.hand_detector()
    found = det.detect(np.zeros((360, 480, 3), np.uint8))
    print(f"selftest ok: opencv {cv2.__version__}, {type(det).__name__} ran, hands in a black frame: {len(found)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
