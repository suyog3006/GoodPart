"use client";
import { useEffect, useRef, useState } from "react";

// Live camera in the browser: capture a frame and send it for inspection.
export function Camera({ onCapture, busy }: { onCapture: (f: File) => void; busy: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;
    navigator.mediaDevices
      ?.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1920 } } })
      .then((s) => {
        stream = s;
        if (video.current) video.current.srcObject = s;
      })
      .catch(() => setError("Camera unavailable. Allow camera access in the browser, or upload a photo instead."));
    return () => stream?.getTracks().forEach((t) => t.stop());
  }, []);

  function capture() {
    const v = video.current;
    if (!v) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d")?.drawImage(v, 0, 0);
    c.toBlob((b) => b && onCapture(new File([b], "camera.jpg", { type: "image/jpeg" })), "image/jpeg", 0.92);
  }

  if (error) return <p className="text-hold">{error}</p>;
  return (
    <div className="flex flex-col gap-2">
      <video ref={video} autoPlay playsInline muted className="w-full rounded-sm border border-rule" />
      <button onClick={capture} disabled={busy} className="rounded-sm bg-steel px-4 py-3 text-lg font-semibold text-tag-ink disabled:opacity-60">
        {busy ? "Inspecting…" : "Capture and inspect"}
      </button>
    </div>
  );
}
