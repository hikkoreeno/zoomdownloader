from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
import os
import uuid
import threading
from zoom_downloader import download_zoom_recording

app = FastAPI()

# Store download progress in memory
# { job_id: { "message": str, "progress": int, "status": "running" | "completed" | "error" } }
download_jobs = {}

# Serve static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

@app.post("/download")
async def start_download(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    url = data.get("url")
    if not url:
        return JSONResponse({"status": "error", "message": "URL is required"}, status_code=400)
    
    job_id = str(uuid.uuid4())
    download_jobs[job_id] = {"message": "Initializing...", "progress": 0, "status": "running"}
    
    background_tasks.add_task(run_download, job_id, url)
    
    return {"status": "ok", "job_id": job_id}

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    job = download_jobs.get(job_id)
    if not job:
        return JSONResponse({"status": "error", "message": "Job not found"}, status_code=404)
    return job

def run_download(job_id, url):
    def progress_callback(update):
        download_jobs[job_id]["message"] = update.get("message", "Downloading...")
        prog = update.get("progress")
        if prog is not None:
            download_jobs[job_id]["progress"] = prog
        if prog == 100:
            download_jobs[job_id]["status"] = "completed"
        elif prog == -1:
            download_jobs[job_id]["status"] = "error"

    try:
        result = download_zoom_recording(url, progress_callback=progress_callback)
        if result:
            download_jobs[job_id]["status"] = "completed"
            download_jobs[job_id]["message"] = f"Success: {os.path.basename(result)}"
        else:
            if download_jobs[job_id]["status"] != "error":
                download_jobs[job_id]["status"] = "error"
                download_jobs[job_id]["message"] = "Download failed."
    except Exception as e:
        download_jobs[job_id]["status"] = "error"
        download_jobs[job_id]["message"] = f"Error: {str(e)}"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
