# Demo recording guide

This is the script for the ~20–30 second GIF shown at the top of the
[README](../README.md). It walks the four core scenarios and, above all,
showcases the North Star: **grounded, cited answers and an honest refusal when a
question is out of course.**

The resulting file should be saved as `docs/demo.gif`; the README already
references it (`![grounded-rag demo](docs/demo.gif)`), so you only need to drop
the file in.

## 0. Before you record

Start the stack on the host (Qdrant in Docker, API + UI on the host):

```bash
docker compose up -d qdrant   # vector store (course already indexed)
make api                      # FastAPI on http://localhost:8000
make ui                       # Streamlit UI on http://localhost:8501
```

Then open <http://localhost:8501>. Do **not** run `docker compose down` while
recording — it stops Qdrant.

Recording hygiene:

- In the sidebar, keep **Student id** at `demo-student` and leave the **Course
  filter** empty (or set it to `Wavelet Transform`).
- Confirm the sidebar shows a healthy **Backend** label before recording.
- Use a clean browser window, zoom so the answer and its sources fit on screen,
  and pre-type nothing — the typing is part of the story.

## 1. Storyboard (≈ 20–30 s)

Keep each beat short; the contrast between beat A and beat B is the whole point.

| Beat | Tab | Action | What the viewer should see |
| --- | --- | --- | --- |
| **A. Grounded answer** (~8 s) | **Ask** | Type *"What is a piecewise constant approximation?"* and click **Ask** | A short answer **with a `Sources` block** citing `(Wavelet Transform, Chap. …, p. …)` — proof every claim is sourced |
| **B. Honest refusal** (~6 s) | **Ask** | Clear the box, type *"How do I set up a Kubernetes cluster?"*, click **Ask** | The refusal banner: *"This is not covered in the course material."* — the model declines instead of inventing |
| **C. Generate an exercise** (~7 s) | **Exercise** | In *Notion to practice* type *"piecewise constant approximation"*, click **Generate exercise** | A course-grounded problem statement (the reference solution is **never** shown) |
| **D. Grade an answer** (~7 s) | **Grade** | Note the *"Grading against generated exercise #N"* banner, type a short answer, click **Grade** | A **Score /100** progress bar plus written feedback |

Optional 2-second closer: back on the **Ask** tab, pick a level under
*"Did not get it? Re-explain at a level"* and click **Re-explain** to show the
memory-aware rephrase.

## 2. Recording the screen (macOS)

Record a tight region around the browser window, then convert to GIF.

Capture with the built-in macOS recorder (`Cmd+Shift+5` → *Record Selected
Portion*), or capture straight to a file with `ffmpeg` + AVFoundation:

```bash
# List capture devices to find your screen index (look for "Capture screen 0").
ffmpeg -f avfoundation -list_devices true -i ""

# Record screen index 1 at 30 fps to demo.mov (Ctrl+C to stop).
ffmpeg -f avfoundation -framerate 30 -i "1" demo.mov
```

## 3. Convert to an optimized GIF

Target roughly **1200–1280 px wide** and keep the file small (aim for < 8 MB so
it renders inline on GitHub). Two options:

### Option A — `gifski` (best quality, recommended)

```bash
# Extract frames, then encode with gifski.
mkdir -p frames
ffmpeg -i demo.mov -vf "fps=15,scale=1200:-1:flags=lanczos" frames/frame_%04d.png
gifski --fps 15 --width 1200 -o docs/demo.gif frames/frame_*.png
rm -rf frames
```

### Option B — `ffmpeg` palette method (no extra tool)

```bash
# 1. Build an optimized palette from the source.
ffmpeg -i demo.mov -vf "fps=15,scale=1200:-1:flags=lanczos,palettegen" palette.png

# 2. Encode the GIF using that palette.
ffmpeg -i demo.mov -i palette.png \
  -lavfi "fps=15,scale=1200:-1:flags=lanczos[x];[x][1:v]paletteuse" \
  docs/demo.gif
rm -f palette.png
```

If the GIF is still too large, drop `fps` to 12 or the width to 1000.

## 4. Verify

```bash
# Confirm the file landed where the README expects it.
ls -lh docs/demo.gif
```

Open `README.md` in a Markdown preview (or push to a branch and view on GitHub)
to confirm the GIF renders and loops.
