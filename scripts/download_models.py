#!/usr/bin/env python3
"""Install a user-selected MediaPipe classifier after runtime validation.

No model URL is preselected. Downloading and enabling a model is an explicit CLI
operation. This never guesses normalization, executes downloaded Python, or
claims that a successful load establishes prediction accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
MAX_MODEL_BYTES = 150 * 1024 * 1024
MAX_LABEL_BYTES = 1024 * 1024


def fetch(url: str, destination: Path, limit: int) -> None:
    """Download a bounded HTTPS file without loading it all into memory."""
    if urlparse(url).scheme != 'https':
        raise ValueError('Model and label downloads must use an HTTPS URL.')
    request = Request(url, headers={'User-Agent': 'PlantClinic-ModelInstaller/1.0'})
    with urlopen(request, timeout=60) as response, destination.open('wb') as output:
        if urlparse(response.url).scheme != 'https':
            raise ValueError('The download redirected away from HTTPS.')
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError(f'Download exceeds the {limit // (1024 * 1024)} MB limit.')
            output.write(chunk)


def acquire(path: str | None, url: str | None, destination: Path, limit: int) -> None:
    if url:
        fetch(url, destination, limit)
        return
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size > limit:
        raise ValueError('The source file is missing or exceeds the allowed size.')
    shutil.copyfile(source, destination)


def load_labels(path: Path) -> list[str]:
    content = path.read_text(encoding='utf-8-sig')
    try:
        labels = json.loads(content)
    except json.JSONDecodeError:
        labels = content.splitlines()
    if isinstance(labels, dict):
        if set(labels) != {str(i) for i in range(len(labels))}:
            raise ValueError('Label mapping keys must be consecutive output indexes: "0", "1", …')
        labels = [labels[str(i)] for i in range(len(labels))]
    if not isinstance(labels, list) or not labels or len(labels) > 10000:
        raise ValueError('Labels must be a nonempty list or indexed mapping, with at most 10,000 labels.')
    if not all(isinstance(label, str) and label.strip() for label in labels):
        raise ValueError('Every label must be a nonempty string.')
    return labels


def validate_classifier(path: Path, labels: list[str] | None) -> int:
    with path.open('rb') as source:
        header = source.read(8)
    if len(header) != 8 or header[4:] != b'TFL3':
        raise ValueError('The downloaded file is not a TensorFlow Lite model (TFL3 header missing).')
    # Import only when the user runs installation; --help needs no app dependencies.
    import mediapipe as mp
    import numpy as np

    options = mp.tasks.vision.ImageClassifierOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        max_results=-1,
    )
    with mp.tasks.vision.ImageClassifier.create_from_options(options) as classifier:
        image = mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=np.zeros((224, 224, 3), dtype=np.uint8))
        result = classifier.classify(image)
    if len(result.classifications) != 1:
        raise ValueError('The app currently supports classifiers with a single classification head.')
    categories = result.classifications[0].categories
    if not categories:
        raise ValueError('The model produced no categories during the compatibility check.')
    if labels is not None:
        indexes = {category.index for category in categories}
        if indexes != set(range(len(labels))):
            raise ValueError('The supplied labels do not match the model output class indexes.')
    elif not all(category.category_name or category.display_name for category in categories):
        raise ValueError('The model has no complete embedded labels; supply --labels-path or --labels-url.')
    return len(categories)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--path', help='Local author-supplied .tflite model')
    source.add_argument('--url', help='Direct HTTPS URL to the .tflite model')
    label_source = parser.add_mutually_exclusive_group()
    label_source.add_argument('--labels-path', help='JSON or newline-separated labels file')
    label_source.add_argument('--labels-url', help='Direct HTTPS URL to labels')
    parser.add_argument('--name', required=True, help='Human-readable model name')
    parser.add_argument('--kind', required=True, choices=['disease', 'pest'])
    parser.add_argument('--source-url', help='Model card or original repository URL for attribution')
    parser.add_argument('--replace', action='store_true', help='Replace a manifest entry with the same name')
    args = parser.parse_args()
    directory = ROOT / 'models'
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / 'manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'models': []}
        if not isinstance(manifest, dict) or not isinstance(manifest.get('models'), list):
            raise ValueError('Existing manifest.json is invalid; it was left unchanged.')
        if not args.name.strip():
            raise ValueError('The model name must not be empty.')
        prior = [entry for entry in manifest['models'] if entry.get('name') == args.name]
        if prior and not args.replace:
            raise ValueError('A model with this name is already installed. Use --replace to replace it.')
        with tempfile.TemporaryDirectory(prefix='.install-', dir=directory) as temporary:
            stage = Path(temporary)
            model_path = stage / 'model.tflite'
            acquire(args.path, args.url, model_path, MAX_MODEL_BYTES)
            labels = None
            if args.labels_path or args.labels_url:
                label_path = stage / 'labels.download'
                acquire(args.labels_path, args.labels_url, label_path, MAX_LABEL_BYTES)
                labels = load_labels(label_path)
            count = validate_classifier(model_path, labels)
            checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
            slug = re.sub(r'[^a-z0-9]+', '-', args.name.lower()).strip('-')[:60] or 'classifier'
            filename = f'{slug}-{checksum[:12]}.tflite'
            entry = {'name': args.name, 'kind': args.kind, 'file': filename,
                     'sha256': checksum, 'enabled': True}
            if args.source_url or args.url:
                entry['source_url'] = args.source_url or args.url
            # Copy only after all runtime checks succeed. The active manifest is
            # replaced last, so an interrupted install cannot enable partial files.
            os.replace(model_path, directory / filename)
            if labels is not None:
                labels_name = f'{slug}-{checksum[:12]}.labels.json'
                staged_labels = stage / 'labels.json'
                staged_labels.write_text(json.dumps(labels, ensure_ascii=False, indent=2) + '\n')
                os.replace(staged_labels, directory / labels_name)
                entry['labels_file'] = labels_name
            manifest['models'] = [item for item in manifest['models'] if item.get('name') != args.name]
            manifest['models'].append(entry)
            staged_manifest = stage / 'manifest.json'
            staged_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
            os.replace(staged_manifest, manifest_path)
        print(f'Installed {args.name}: {count} classifier outputs; SHA-256 {checksum}')
        print('Restart Plant Clinic to load it. Runtime compatibility passed; accuracy is not validated.')
        return 0
    except Exception as exc:
        print(f'Model was not enabled: {exc}', file=sys.stderr)
        print('Check the model author\'s input/normalization metadata and label order. '
              'No metadata is guessed or rewritten.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
