# SHN-MEDIAPIPE
![Project Cover](assets/cover.jpeg)

# Plant Clinic

A local plant and garden-pest photo journal, built for Saturday Hack Night. Capture or upload a photograph, inspect possible problems, read practical care notes, and revisit every scan. The interface uses a cream grid background, bold type, pastel cards, and dark outlines.

![Project Cover](assets/mainss.png)

## Run on this machine

Open the Ollama application, then run:

```bash
./run.sh
```

Visit **http://localhost:8000**. Stop the server with `Ctrl+C`. The app binds to this machine only. It uses the existing local Ollama service at `127.0.0.1:11434`.

## First-time installation

Use a MediaPipe-supported Python version (Python 3.14 is used in this checkout). Python 3.15 is not supported by the installed dependency set. With [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

Alternatively, with Python 3.14 already installed:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Install [Ollama](https://ollama.com/) and a local vision-capable model if you do not already have one. The app discovers installed model capabilities automatically. This machine already has `gemma4:12b` for image interpretation and `llama3.2:3b` for text-only fallback. Model speed and memory needs depend on the machine; the first analysis includes model loading.

**No specialist MediaPipe model is currently installed:** the model download was cancelled. The app currently uses the installed Ollama vision model and labels that method in every report. MediaPipe model requirements and the validated installer are documented in [models/README.md](models/README.md). Once dependencies and model files are installed, the application uses no cloud API, CDN, or remote font. Source links are ordinary external links opened only when clicked.

## What happens to a photo

1. The browser captures a still image or uploads a JPEG, PNG, or WebP (maximum 10 MB / 25 megapixels).
2. FastAPI validates and normalizes it, corrects orientation, removes embedded metadata, and writes a JPEG plus a thumbnail to `data/uploads/`.
3. SQLite stores a processing record before inference starts, so the photo remains in history if the model fails.
4. Available specialist models run through MediaPipe Tasks. Their top candidates are evidence, not a guaranteed diagnosis or a calibrated probability.
5. An image-capable Ollama model reviews the image, crop context, notes, and MediaPipe candidates. This helps distinguish visible pests, disease symptoms, healthy-looking plants, and unrelated photos. A non-plant result discards the leaf classifier's irrelevant scores.
6. The app matches the suggested issue against the local UC IPM / university-extension care library. Treatment and prevention text comes from those records; Ollama provides the interpretation and uncertainty. No chemical products or doses are generated.
7. The report, model provenance, scores, and source links are saved in SQLite. The browser loads history from the server on every visit.

The language model does not establish laboratory diagnoses. Unsupported plants and pests, blurry photos, nutrient stress, and multiple simultaneous problems can produce incorrect suggestions. Any configured classifier covers only its listed classes. Pest identification uses Ollama vision unless a specialist pest model is separately added. Uncertain findings are explicitly marked for review. If no matching care record exists, the report labels its steps as general care.

If only a text model is installed, it can explain MediaPipe candidates but cannot verify the photograph; those reports are always marked uncertain. If neither image interpretation path is available, the photo is saved with a recoverable setup error. There are no fabricated sample results.

## Configuration

Copy `.env.example` to `.env` to customize:

| Variable | Default |
| --- | --- |
| `OLLAMA_URL` | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | Auto-select an installed text model |
| `OLLAMA_VISION_MODEL` | Auto-select an installed vision model |
| `OLLAMA_TIMEOUT` | 240 seconds |
| `PLANT_DATA_DIR` | `data/` in this project |
| `PLANT_MODEL_DIR` | `models/` in this project |

Environment variables override `.env`. Keep `OLLAMA_URL` local to preserve the single-machine design. Restart the server after changing models or configuration. Run only one Uvicorn worker: one analysis at a time keeps model memory use bounded. Requests arriving during analysis receive a friendly busy response.

Use `PORT=8001 ./run.sh` to change the app port. Browser camera access works on `localhost` with permission. Access through a phone on the network is a separate configuration: bind intentionally to the LAN and provide trusted HTTPS for live camera capture. The default does not expose the service to the network.

## Project structure

```text
app/
  main.py          Local HTTP API and app lifecycle
  advisor.py       Ollama structured interpretation and care matching
  vision.py        MediaPipe model loading and classification
  storage.py       SQLite history
  images.py        Image validation and normalized files
  schemas.py       Validated model response structure
  remedies.json    Source-linked local care library
  static/          HTML, CSS, JavaScript; no frontend build step
models/            Specialist models, labels, and provenance
scripts/           Model setup utilities
tests/             Offline API and report behavior tests
data/              Private runtime data (gitignored)
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Local service and model readiness |
| POST | `/api/scans` | Multipart `file`, optional `crop` and `notes`; save and analyze |
| GET | `/api/scans?limit=100&offset=0` | Paginated server history |
| GET | `/api/scans/{id}` | Saved report |
| GET | `/api/scans/{id}/image` | Normalized photograph |
| GET | `/api/scans/{id}/thumbnail` | History thumbnail |
| POST | `/api/scans/{id}/retry` | Re-run a saved photo |
| DELETE | `/api/scans/{id}` | Remove the saved record and image files |

The machine-readable API schema is available at `http://localhost:8000/openapi.json`. The application is fully self-contained and works offline.

## Checks

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

The exact verified environment is also recorded in `requirements.lock.txt`. Install it with `uv pip install --python .venv/bin/python -r requirements.lock.txt` to reproduce these package versions.

Tests use deterministic doubles for inference, exercise real HTTP handlers and a temporary SQLite database, and never need cloud access or alter your history. Real-model smoke checks are separate from these tests.

Back up the whole `data/` directory while the server is stopped to preserve history and images together. Model files are downloaded separately and excluded from Git.


## Verification in this checkout

- 31 offline backend/advisor tests pass, including saved images, server restart persistence, retry, delete, upload limits, and source-controlled remedy selection.
- Live inference with the installed `gemma4:12b` completed the full upload/save/report flow for the repository's non-plant cover graphic and a synthetic geometric image. Both were correctly classified as unrelated, in approximately 17 and 11 seconds respectively. These checks used temporary history and did not add demonstration scans to your journal.
- JavaScript syntax, DOM references, Python compilation, and diff whitespace checks passed.
- Browser visual inspection and physical camera capture were not verified because computer-use access was unavailable. Responsive styles and camera permission/error handling are implemented.
- No specialist MediaPipe model is installed, and plant/pest recognition accuracy has not been benchmarked. Use real field photos to validate suggestions before relying on them.

Run an optional real-model check with a photo of your own (temporary history only):

```bash
.venv/bin/python scripts/smoke_test.py /absolute/path/to/photo.jpg
```
