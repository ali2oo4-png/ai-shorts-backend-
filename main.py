import os
import json
import uuid
import glob
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("outputs", exist_ok=True)

MODEL_NAME = "gemini-3.8-flash"

YTDLP_BASE_ARGS = [
    "yt-dlp",
    "--no-check-certificates",
    "--no-warnings",
    "--extractor-args", "youtube:player_client=tv_embedded,web_creator,mediaconnect",
]

HTML_PAGE = """<!DOCTYPE html>
<html lang="tg">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="AI Shorts">
  <title>AI Shorts Maker</title>
  <style>
    * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body {
      margin: 0; padding: 20px 16px 40px; background: #0b0b0f; color: #fff;
      display: flex; flex-direction: column; min-height: 100vh;
    }
    .card {
      background: #16161e; border: 1px solid #262633; border-radius: 22px;
      padding: 20px; box-shadow: 0 12px 30px rgba(0,0,0,0.5); max-width: 500px; width: 100%; margin: 0 auto;
    }
    h1 { font-size: 22px; margin: 0 0 6px; text-align: center; }
    p.sub { color: #9a9aa6; font-size: 13px; text-align: center; margin: 0 0 18px; line-height: 1.4; }
    input {
      width: 100%; padding: 14px; border-radius: 14px; border: 1px solid #2e2e3d;
      background: #0f0f15; color: #fff; font-size: 16px; outline: none; margin-bottom: 12px;
    }
    input:focus { border-color: #6c5ce7; }
    .main-btn {
      width: 100%; padding: 15px; border-radius: 14px; border: none;
      background: linear-gradient(135deg, #6c5ce7, #a29bfe); color: #fff;
      font-size: 16px; font-weight: 700; cursor: pointer;
    }
    .main-btn:disabled { opacity: 0.5; }
    .status {
      margin-top: 14px; text-align: center; font-size: 13px; color: #a29bfe;
      line-height: 1.5; display: none;
    }
    .error { color: #ff7675; margin-top: 12px; font-size: 13px; text-align: center; display: none; word-break: break-word; }
    .clips-list { margin-top: 20px; display: flex; flex-direction: column; gap: 14px; }
    .clip-item {
      background: #0f0f15; border: 1px solid #2a2a38; border-radius: 16px; padding: 14px;
    }
    .clip-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    .badge {
      background: #262638; color: #a29bfe; font-size: 12px; font-weight: 700;
      padding: 4px 8px; border-radius: 8px;
    }
    .clip-title { font-size: 15px; font-weight: 700; margin: 0 0 6px; color: #fff; }
    .clip-reason { font-size: 12px; color: #9a9aa6; margin: 0 0 12px; line-height: 1.4; }
    .cut-btn {
      width: 100%; padding: 11px; border-radius: 12px; border: none;
      background: #2d3436; color: #55efc4; font-size: 14px; font-weight: 700; cursor: pointer;
    }
    .cut-btn:disabled { opacity: 0.5; color: #9a9aa6; }
    .video-box { margin-top: 12px; text-align: center; }
    video { width: 100%; border-radius: 12px; background: #000; max-height: 380px; margin-bottom: 10px; }
    .dl-btn {
      display: block; padding: 12px; background: #00b894; color: #fff;
      text-decoration: none; border-radius: 12px; font-weight: 700; font-size: 14px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>🎬 AI Shorts Maker</h1>
    <p class="sub">Ҳар гуна видеои YouTube (бо субтитр ё бе субтитр)-ро гузоред — AI 5 то 8 лаҳзаи беҳтаринро меёбад</p>
    <input type="url" id="urlInput" placeholder="https://www.youtube.com/watch?v=..." />
    <button class="main-btn" id="analyzeBtn" onclick="analyzeVideo()">🔍 Ёфтани беҳтарин лаҳзаҳо</button>
    <div class="status" id="statusBox">⏳ AI видеоро тамошо ва таҳлил карда истодааст...</div>
    <div class="error" id="errorBox"></div>
    <div class="clips-list" id="clipsList"></div>
  </div>

  <script>
    let currentVideoUrl = "";

    function formatTime(sec) {
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    async function analyzeVideo() {
      const url = document.getElementById("urlInput").value.trim();
      if (!url) return alert("Лутфан ссылкаи YouTube-ро ворид кунед!");

      currentVideoUrl = url;
      const btn = document.getElementById("analyzeBtn");
      const statusBox = document.getElementById("statusBox");
      const errorBox = document.getElementById("errorBox");
      const clipsList = document.getElementById("clipsList");

      btn.disabled = true;
      statusBox.style.display = "block";
      errorBox.style.display = "none";
      clipsList.innerHTML = "";

      try {
        const res = await fetch("/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Хатогии сервер");

        data.clips.forEach((clip, idx) => {
          const item = document.createElement("div");
          item.className = "clip-item";
          item.innerHTML = `
            <div class="clip-header">
              <span class="badge">#${idx + 1} • ${formatTime(clip.start)} – ${formatTime(clip.end)} (${clip.end - clip.start}с)</span>
            </div>
            <div class="clip-title">${clip.title}</div>
            <div class="clip-reason">${clip.reason || ""}</div>
            <button class="cut-btn" id="btn-${idx}" onclick="cutClip(${idx}, ${clip.start}, ${clip.end})">✂️ Сохтани ин Short</button>
            <div class="video-box" id="vbox-${idx}"></div>
          `;
          clipsList.appendChild(item);
        });
      } catch (err) {
        errorBox.innerText = "❌ " + err.message;
        errorBox.style.display = "block";
      } finally {
        btn.disabled = false;
        statusBox.style.display = "none";
      }
    }

    async function cutClip(idx, start, end) {
      const btn = document.getElementById(`btn-${idx}`);
      const vbox = document.getElementById(`vbox-${idx}`);
      btn.disabled = true;
      btn.innerText = "⏳ Дар ҳоли буридан (20–40 сония)...";
      vbox.innerHTML = "";

      try {
        const res = await fetch("/cut", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: currentVideoUrl, start, end })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Хатогӣ ҳангоми буридан");

        btn.innerText = "✅ Омода шуд!";
        vbox.innerHTML = `
          <video src="${data.download_url}" controls playsinline></video>
          <a href="${data.download_url}" class="dl-btn" download>⬇️ Захира кардан ба iPhone</a>
        `;
      } catch (err) {
        btn.disabled = false;
        btn.innerText = "❌ Хатогӣ. Аз нав кӯшиш кунед";
        alert(err.message);
      }
    }
  </script>
</body>
</html>"""

class AnalyzeRequest(BaseModel):
    url: str

class CutRequest(BaseModel):
    url: str
    start: int
    end: int

def extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    elif "shorts/" in url:
        return url.split("shorts/")[1].split("?")[0]
    raise ValueError("Invalid YouTube URL")

def cleanup_old_files():
    files = sorted(glob.glob("outputs/*.mp4"), key=os.path.getmtime)
    while len(files) > 5:
        try:
            os.remove(files.pop(0))
        except Exception:
            pass

def run_cmd(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err_msg = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "Хатогии номаълум"
        raise RuntimeError(err_msg)
    return proc

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE

@app.post("/analyze")
def analyze_video(req: AnalyzeRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY нест")

    try:
        video_id = extract_video_id(req.url)
    except Exception:
        raise HTTPException(status_code=400, detail="Ссылкаи YouTube нодуруст аст")

    clean_url = f"https://www.youtube.com/watch?v={video_id}"
    client = genai.Client(api_key=api_key)
    transcript = None

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'ru', 'tg', 'uz'])
    except Exception:
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            first_transcript = next(iter(transcript_list))
            transcript = first_transcript.fetch()
        except Exception:
            transcript = None

    prompt_base = """
    Analyze this video content and pick the top 5 to 8 most engaging, viral 25-to-50 second segments suitable for YouTube Shorts or Instagram Reels.
    Make sure segments do not overlap and each has a strong hook.
    Return ONLY a valid JSON array with integer timestamps in seconds in this exact format:
    [
      {"start": 120, "end": 155, "title": "Catchy short title", "reason": "Why this moment is interesting in 1 short sentence"}
    ]
    """

    try:
        if transcript:
            formatted_text = "\n".join([f"[{int(item['start'])}s] {item['text']}" for item in transcript[:700]])
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=f"{prompt_base}\n\nTranscript:\n{formatted_text}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
        else:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=types.Content(
                    parts=[
                        types.Part(
                            file_data=types.FileData(file_uri=clean_url)
                        ),
                        types.Part(text=prompt_base),
                    ]
                ),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

        clips = json.loads(response.text)
        valid_clips = []
        for c in clips:
            s = max(0, int(c.get("start", 0)))
            e = max(s + 15, int(c.get("end", s + 35)))
            if e - s > 60:
                e = s + 60
            valid_clips.append({
                "start": s,
                "end": e,
                "title": c.get("title", "AI Short"),
                "reason": c.get("reason", "")
            })
        return {"clips": valid_clips}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Хатогии таҳлил: {str(e)}")

@app.post("/cut")
def cut_clip(req: CutRequest):
    cleanup_old_files()
    try:
        video_id = extract_video_id(req.url)
        clean_url = f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        clean_url = req.url

    duration = max(10, min(60, req.end - req.start))
    job_id = str(uuid.uuid4())[:8]
    raw_video = f"outputs/{job_id}_raw.mp4"
    final_video = f"outputs/{job_id}_short.mp4"

    try:
        dl_cmd = YTDLP_BASE_ARGS + [
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", raw_video,
            clean_url
        ]
        run_cmd(dl_cmd)

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", str(req.start),
            "-i", raw_video,
            "-t", str(duration),
            "-vf", "crop=ih*(9/16):ih,scale=720:1280",
            "-c:v", "libx264", "-preset", "fast", "-crf", "26",
            "-c:a", "aac", "-b:a", "128k",
            final_video
        ]
        run_cmd(ffmpeg_cmd)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Хатогӣ ҳангоми коркарди видео: {str(e)}")
    finally:
        if os.path.exists(raw_video):
            os.remove(raw_video)

    return {"download_url": f"/download/{job_id}_short.mp4"}

@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = f"outputs/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл ёфт нашуд")
    return FileResponse(file_path, media_type="video/mp4", filename=filename)
