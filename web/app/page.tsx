"use client";

import { useState, useRef } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

interface ResolveData {
  title: string;
  url: string;
}

interface ApiResponse {
  code: number;
  message: string;
  data: ResolveData | null;
}

type Status = "idle" | "loading" | "error" | "done";

export default function Home() {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const [video, setVideo] = useState<ResolveData | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const trimmed = text.trim();

  async function resolveUrl(): Promise<ResolveData> {
    const res = await fetch(
      `${API_BASE}/api/resolve?url=${encodeURIComponent(trimmed)}`
    );
    const json: ApiResponse = await res.json();
    if (json.code !== 0 || !json.data) throw new Error(json.message);
    return json.data;
  }

  async function handlePlay() {
    if (!trimmed || status === "loading") return;
    setStatus("loading");
    setError("");
    setVideo(null);

    try {
      const data = await resolveUrl();
      setVideo(data);
      setStatus("done");
      // 等 video 元素渲染后滚到视野
      setTimeout(() => videoRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
      setStatus("error");
    }
  }

  async function handleDownload() {
    if (!trimmed || status === "loading") return;
    setStatus("loading");
    setError("");

    try {
      // 先 resolve 验证链接有效，顺带拿 title 展示
      const data = await resolveUrl();
      setVideo(data);
      setStatus("done");
      window.location.href = `${API_BASE}/proxy?url=${encodeURIComponent(trimmed)}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
      setStatus("error");
    }
  }

  async function pasteFromClipboard() {
    try {
      const t = await navigator.clipboard.readText();
      setText(t);
      setVideo(null);
      setError("");
    } catch {
      textareaRef.current?.focus();
    }
  }

  function reset() {
    setText("");
    setVideo(null);
    setError("");
    setStatus("idle");
  }

  const isLoading = status === "loading";

  return (
    <main style={s.main}>
      {/* Logo */}
      <div style={s.logoWrap}>
        <div style={s.logoIcon}>▶</div>
        <h1 style={s.title}>抖音解析</h1>
        <p style={s.subtitle}>无水印播放 &amp; 下载</p>
      </div>

      {/* 输入卡片 */}
      <div style={s.card}>
        <div style={s.cardHeader}>
          <span style={s.muted}>粘贴分享内容或链接</span>
          <button style={s.pasteBtn} onClick={pasteFromClipboard}>粘贴</button>
        </div>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => { setText(e.target.value); setVideo(null); setError(""); }}
          placeholder={"5.33 kcN:/ 挫折不是绊脚石…  https://v.douyin.com/xxx/\n或直接粘贴链接"}
          rows={4}
          style={s.textarea}
        />
        {trimmed && (
          <button style={s.clearBtn} onClick={reset}>清空</button>
        )}
      </div>

      {/* 错误 */}
      {status === "error" && (
        <div style={s.errorBox}>{error}</div>
      )}

      {/* 操作按钮 */}
      <div style={s.btnRow}>
        <button
          onClick={handlePlay}
          disabled={!trimmed || isLoading}
          style={{ ...s.btn, ...s.btnPlay, opacity: !trimmed || isLoading ? 0.4 : 1 }}
        >
          {isLoading ? <Spinner /> : "▶ 播放"}
        </button>
        <button
          onClick={handleDownload}
          disabled={!trimmed || isLoading}
          style={{ ...s.btn, ...s.btnDownload, opacity: !trimmed || isLoading ? 0.4 : 1 }}
        >
          {isLoading ? <Spinner /> : "↓ 下载"}
        </button>
      </div>

      {/* 视频播放器 */}
      {video && (
        <div style={s.playerWrap}>
          <p style={s.playerTitle} title={video.title}>
            {video.title.length > 40 ? video.title.slice(0, 40) + "…" : video.title}
          </p>
          <video
            ref={videoRef}
            src={video.url}
            controls
            autoPlay
            playsInline          /* iOS 禁止自动全屏 */
            controlsList="nodownload"
            style={s.video}
          />
        </div>
      )}

      <p style={s.hint}>支持分享文案 · 短链 · 完整链接</p>
    </main>
  );
}

function Spinner() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
      style={{ animation: "spin 0.8s linear infinite" }}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}

const s: Record<string, React.CSSProperties> = {
  main: {
    minHeight: "100dvh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "flex-start",
    paddingTop: 48,
    paddingBottom: 40,
    paddingLeft: 16,
    paddingRight: 16,
    background: "var(--bg)",
    gap: 0,
  },
  logoWrap: { textAlign: "center", marginBottom: 24 },
  logoIcon: {
    width: 60, height: 60, borderRadius: 15,
    background: "var(--accent)",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 28, margin: "0 auto 10px",
  },
  title: { margin: 0, fontSize: 21, fontWeight: 700, color: "var(--text)" },
  subtitle: { margin: "5px 0 0", fontSize: 13, color: "var(--muted)" },

  card: {
    width: "100%", maxWidth: 480,
    background: "var(--surface)",
    borderRadius: 16, border: "1px solid var(--border)",
    padding: 16, marginBottom: 0,
  },
  cardHeader: { display: "flex", justifyContent: "space-between", marginBottom: 8 },
  muted: { fontSize: 13, color: "var(--muted)" },
  pasteBtn: {
    fontSize: 13, color: "var(--accent)",
    background: "none", border: "none", cursor: "pointer",
    padding: 0, fontFamily: "inherit",
  },
  textarea: {
    width: "100%", background: "transparent",
    border: "none", outline: "none",
    color: "var(--text)", fontSize: 14,
    lineHeight: 1.7, resize: "none", fontFamily: "inherit",
  },
  clearBtn: {
    fontSize: 12, color: "var(--muted)",
    background: "none", border: "none", cursor: "pointer",
    padding: 0, marginTop: 4, fontFamily: "inherit",
  },

  errorBox: {
    marginTop: 12, width: "100%", maxWidth: 480,
    background: "#2a1010", border: "1px solid #5a1a1a",
    borderRadius: 10, padding: "10px 14px",
    fontSize: 13, color: "#ff6b6b",
  },

  btnRow: {
    marginTop: 14, width: "100%", maxWidth: 480,
    display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12,
  },
  btn: {
    height: 52, borderRadius: 12,
    fontSize: 16, fontWeight: 600,
    cursor: "pointer", fontFamily: "inherit",
    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
    transition: "opacity 0.15s", border: "none",
  },
  btnPlay: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    color: "var(--text)",
  },
  btnDownload: {
    background: "var(--accent)",
    color: "#fff",
  },

  playerWrap: {
    marginTop: 20, width: "100%", maxWidth: 480,
  },
  playerTitle: {
    margin: "0 0 8px 2px",
    fontSize: 13, color: "var(--muted)",
    lineHeight: 1.5,
    wordBreak: "break-all",
  },
  video: {
    width: "100%",
    borderRadius: 12,
    background: "#000",
    display: "block",
    maxHeight: "60dvh",
  },

  hint: {
    marginTop: 20, fontSize: 12,
    color: "var(--muted)", textAlign: "center",
  },
};
