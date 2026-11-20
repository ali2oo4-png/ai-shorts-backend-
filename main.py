import os
import json
import uuid
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

@app.get("/")
def home():
    return {"status": "AI Shorts Backend is Live!"}

@app.post("/create-short")
def create_short(req: VideoRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY нест")

    try:
        video_id = extract_video_id(req.url)
    except Exception:
        raise HTTPException(status_code=400, detail="Ссылкаи YouTube нодуруст аст")

    # 1. Гирифтани субтитрҳои видео
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

    # 2. Таҳлил бо Gemini барои ёфтани лаҳзаи ҷолибтарин
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

    # 3. Боргирии видео бо yt-dlp
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

    # 4. Буридан ва вертикалӣ кардан (9:16) бо FFmpeg
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
