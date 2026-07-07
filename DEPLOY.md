# Deploying a public link

The app is fully deploy-ready (production server = gunicorn, validated). It runs
as a normal Python web service — all data ships in `data/` (no external DB).

**The one thing that can't be automated for you:** signing into a hosting
account. Pick a host below, sign in once, and you get a public `https://…` URL.

---

## Fastest: Render (free public URL)

1. Put this `app/` folder on GitHub (one time):
   ```
   cd "app"
   git init && git add -A && git commit -m "TI cross-reference tool"
   # create an empty repo on github.com, then:
   git remote add origin https://github.com/<you>/ti-cross-reference.git
   git branch -M main && git push -u origin main
   ```
2. Go to <https://render.com> → **New → Blueprint** → connect the repo.
   `render.yaml` is detected automatically. Click **Apply**.
3. In ~3–4 min you get a public URL like `https://ti-cross-reference.onrender.com`.

Notes
- The blueprint uses the **starter** plan so the link stays warm (no cold start).
  Change `plan: starter` → `plan: free` in `render.yaml` for $0 (it sleeps after
  15 min idle and takes ~30 s to wake — that's the only "latency").
- First boot indexes the 94k master (~10–20 s), then every request is instant.

## Alternative: Hugging Face Spaces (free, Docker)

Create a Space → **Docker** template → push this folder (it has a `Dockerfile`).
Public URL: `https://<you>-ti-cross-reference.hf.space`.

## Alternative: Railway / Fly.io / Google Cloud Run

All work with the included `Dockerfile` / `Procfile` — `gunicorn app:app`.

---

## Custom domain (optional)

On Render/HF you can point a domain (e.g. `crossref.yourteam.com`) in the
dashboard's *Custom Domains* — no code change.
