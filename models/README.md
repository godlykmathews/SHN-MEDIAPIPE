# Specialist MediaPipe models

No specialist model is bundled. The attempted model download was cancelled before
any model bytes arrived. The app reports MediaPipe as unavailable until a model is
installed; the installed Ollama vision model can still provide clearly attributed
visual assessments.

MediaPipe is an inference runtime, not a crop disease model. Do not install a
general ImageNet classifier and label its output as crop disease identification.

## Install a compatible classifier

Run the following from the project root after installing the app dependencies:

```sh
.venv/bin/python scripts/download_models.py \
  --path /absolute/path/to/leaf_classifier.tflite \
  --labels-path /absolute/path/to/leaf_labels.json \
  --name 'My validated leaf classifier' \
  --kind disease
```

For a direct HTTPS download, use `--url` instead of `--path`, and optionally
`--labels-url` instead of `--labels-path`. Prefer immutable release or commit URLs.
The installer downloads only when you run it. It validates the file with the real
MediaPipe `ImageClassifier`, runs one synthetic compatibility check, and enables
the model in `manifest.json` only after those checks succeed. This check verifies
runtime compatibility, **not recognition accuracy**. Model files are named by
their content hash. An existing entry with a different model requires `--replace`.

Use `--kind pest` for a close-up pest **classifier**. Object detector models have a
different tensor contract and cannot be installed with this classifier adapter.
Restart the app after changing the manifest.

## Required model contract

- A valid TensorFlow Lite image classification model, supported by MediaPipe
  Tasks `ImageClassifier`; RGB input, batch size one, and a classification output.
- Float32 input models need the correct `NormalizationOptions` in their model
  metadata. The installer deliberately does not guess normalization or rewrite
  model weights/metadata. Use the model author's compatible export.
- Labels must be embedded in the model or provided as a JSON list in exact output
  index order. A JSON object mapping `"0"`, `"1"`, … to labels is also accepted.
  Newline-separated text labels are accepted too.
- Preprocessing must match the backend's current image path (MediaPipe's normal
  image conversion and resize). Models requiring a custom crop or other transform
  need a matching adapter before their predictions can be trusted.
- Keep source/license information and a supported class list with the model.
  Validate on held-out photographs from the actual camera conditions, including
  healthy plants, unknown diseases, and unrelated images.

`manifest.example.json` documents the backend format; it is not active. There is
no `manifest.json` until an installation succeeds. Optional `source_url` identifies
the model source; the installer also records a SHA-256 checksum.

Official contracts:

- [MediaPipe image classification](https://developers.google.com/edge/mediapipe/solutions/vision/image_classifier)
- [Python ImageClassifier requirements](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/ImageClassifier)

## Candidate to investigate

[KumarjitC/plantulus-doctor](https://huggingface.co/KumarjitC/plantulus-doctor)
is a publicly listed, MIT-labeled EfficientNetV2-B0 leaf classifier. Its author
describes a roughly 12 MB float16 TFLite export, 54 plant/condition classes, and
float32 input values in the range 0–255. **Its compatibility with this app has not
been verified and it is not installed.**

Its documented preprocessing is EXIF correction, RGB conversion, resizing the
shorter side to 256 pixels, then centered crops to 256 and 224 pixels. That differs
from a plain resize, so using it correctly needs the matching preprocessing
adapter and verified normalization metadata. The author also warns that unrelated
images are forced into one of the supported classes and that field-photo accuracy
can be lower than the reported dataset accuracy. It is not a general pest-species
identifier.
