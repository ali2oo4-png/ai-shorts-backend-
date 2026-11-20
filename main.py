import os
import json
import uuid
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
      margin: 0; padding: 24px 20px; background: #0b0b0f; color: #fff;
      display: flex; flex-direction: column; min-height: 100vh; justify-content: center;
    }
    .card {
      background: #16161e; border: 1px solid #262633; border-radius: 22px;
      padding: 24px; box-shadow: 0 12px 30px rgba(0,0,0,0.5);
    }
    h1 { font-size: 24px; margin: 0 0 8px; text-align: center; }
    p.sub { color: #9a9aa6; font-size: 14px; text-align: center; margin: 0 0 24px; }
    input {
      width: 100%; padding: 15px; border-radius: 14px; border: 1px solid #2e2e3d;
      background: #0f0f15; color: #fff; font-size: 16px; outline: none; margin-bottom: 14px;
    }
    input:focus { border-color: #6c5ce7; }
    button {
      width: 100%; padding: 16px; border-radius: 14px; border: none;
      background: linear-gradient(135deg, #6c5ce7, #a29bfe); color: #fff;
      font-size: 16px; font-weight: 700; cursor: pointer;
    }
    button:disabled { opacity: 0.5; }
    .status {
      margin-top: 18px; text-align: center; font-size: 14px; color: #a29bfe;
      line-height: 1.5; display: none;
    }
    .result { margin-top: 20px; display: none; text-align: center; }
    .result h3 { font-size: 16px; margin: 0 0 12px; color: #55efc4; }
    video { width: 100%; border-radius: 16px; background: #000; max-height: 420px; margin-bottom: 12px; }
    .dl-btn {
      display: block; padding: 14px; background: #00b894; color: #fff;
      text-decoration: none; border-radius: 14px; font-weight: 700; font-size: 15px;
    }
    .error { color: #ff7675; margin-top: 14px; font-size: 14px; text-align: center; display: none; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🎬 AI Shorts Maker</h1>
    <p class="sub">Ссылкаи YouTube-ро гузоред, AI беҳтарин лаҳзаро барои Reels / Shorts мебурад</p>
    <input type="url" id="urlInput" placeholder="https://www.youtube.com/watch?v=..." />
    <button id="genBtn" onclick="generateShort()">Сохтани Short</button>
    <div class="status" id="statusBox">⏳ Дар ҳоли коркард...<br><small>(То 1–2 дақиқа вақт мегирад)</small></div>
    <div class="error" id="errorBox"></div>
    <div class="result" id="resultBox">
      <h3 id="videoTitle"></h3>
      <video id="videoPlayer" controls playsinline></video>
      <a id="downloadLink" class="dl-btn" download>⬇️ Захира кардан ба iPhone</a>
    </div>
  </div>
  <script>
    async function generateShort() {
      const url = document.getElementById("urlInput").value.trim();
      if (!url) return alert("Лутфан ссылкаи YouTube-ро ворид кунед!");
      const btn = document.getElementById("genBtn");
      const statusBox = document.getElementById("statusBox");
      const errorBox = document.getElementById("errorBox");
      const resultBox = document.getElementById("resultBox");
      btn.disabled = true;
      statusBox.style.display = "block";
      errorBox.style.display = "none";
      resultBox.style.display = "none";
      try {
        const res = await fetch("/create-short", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Хатогии сервер");
        document.getElementById("videoTitle").innerText = "✨ " + data.title;
        document.getElementById("videoPlayer").src = data.download_url;
        document.getElementById("downloadLink").href = data.download_url;
        resultBox.style.display = "block";
      } catch (err) {
        errorBox.innerText = "❌ " + err.message;
        errorBox.style.display = "block";
      } finally {
        btn.disabled = false;
        statusBox.style.display = "none";
      }
    }
  </script>
</body>
</html>"""

class VideoRequest(BaseModel):
    url: str

def extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    elif "shorts/" in url:
        return url.split("shorts/")[1].split("?")[0]
    raise ValueError("Invalid YouTube URL")

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE

@app.post("/create-short")
def create_short(req: VideoRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY нест")

    try:
        video_id = extract_video_id(req.url)
    except Exception:
        raise HTTPException(status_code=400, detail="Ссылкаи YouTube нодуруст аст")

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'ru', 'tg', 'uz'])
    except Exception:
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            first_transcript = next(iter(transcript_list))
            transcript = first_transcript.fetch()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Субтитр ёфт нашуд: {str(e)}")

    formatted_text = "\n".join([f"[{int(item['start'])}s] {item['text']}" for item in transcript[:400]])

    client = genai.Client(api_key=api_key)
    prompt = f"""
    Analyze this video transcript with timestamps and pick the single most engaging, viral 30-to-45 second segment suitable for YouTube Shorts or Instagram Reels.
    Return ONLY valid JSON in this exact format:
    {{"start": 120, "end": 155, "title": "Short catchy title"}}

    Transcript:
    {formatted_text}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        clip_info = json.loads(response.text)
        start_time = int(clip_info.get("start", 0))
        end_time = int(clip_info.get("end", start_time + 35))
        duration = max(10, min(60, end_time - start_time))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Хатогии Gemini: {str(e)}")

    job_id = str(uuid.uuid4())[:8]
    raw_video = f"outputs/{job_id}_raw.mp4"
    final_video = f"outputs/{job_id}_short.mp4"

    dl_cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", raw_video,
        req.url
    ]
    subprocess.run(dl_cmd, check=True)

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", raw_video,
        "-t", str(duration),
        "-vf", "crop=ih*(9/16):ih,scale=720:1280",
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-c:a", "aac", "-b:a", "128k",
        final_video
    ]
    subprocess.run(ffmpeg_cmd, check=True)

    if os.path.exists(raw_video):
        os.remove(raw_video)

    return {
        "title": clip_info.get("title", "AI Short"),
        "download_url": f"/download/{job_id}_short.mp4"
    }

@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = f"outputs/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл ёфт нашуд")
    return FileResponse(file_path, media_type="video/mp4", filename=filename)
