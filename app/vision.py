"""MediaPipe Tasks adapters. Only explicitly configured specialist models run."""
import json
import threading
from pathlib import Path


class PlantVision:
    def __init__(self, directory: Path):
        self.directory = directory
        self.classifiers = []
        self.errors = []
        self.lock = threading.Lock()
        manifest = directory / 'manifest.json'
        if not manifest.exists():
            self.errors.append('No specialist MediaPipe model is installed yet.')
            return
        try:
            import mediapipe as mp
            self.mp = mp
            entries = json.loads(manifest.read_text())['models']
        except Exception as exc:
            self.errors.append(f'MediaPipe could not load: {exc}')
            return
        for entry in entries:
            if entry.get('enabled', True) is False:
                continue
            try:
                path = directory / entry['file']
                options = mp.tasks.vision.ImageClassifierOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
                    running_mode=mp.tasks.vision.RunningMode.IMAGE,
                    max_results=3,
                    score_threshold=0.0,
                )
                classifier = mp.tasks.vision.ImageClassifier.create_from_options(options)
                labels = None
                if entry.get('labels_file'):
                    label_path = directory / entry['labels_file']
                    labels = json.loads(label_path.read_text()) if label_path.suffix == '.json' else label_path.read_text().splitlines()
                self.classifiers.append((entry, classifier, labels))
            except Exception as exc:
                self.errors.append(f"{entry.get('name', 'Model')}: {exc}")

    def status(self):
        return {'available': bool(self.classifiers),
                'models': [{'name': entry['name'], 'kind': entry['kind']} for entry, _, _ in self.classifiers],
                'message': ' '.join(self.errors) or 'Specialist image model is ready.'}

    def classify(self, path: Path):
        predictions = []
        if not self.classifiers:
            return predictions
        with self.lock:
            image = self.mp.Image.create_from_file(str(path))
            for entry, classifier, labels in self.classifiers:
                result = classifier.classify(image)
                for classification in result.classifications:
                    for category in classification.categories:
                        label = category.category_name or category.display_name
                        if not label and labels:
                            label = labels[category.index] if isinstance(labels, list) else labels.get(str(category.index))
                        predictions.append({'label': label or f'Class {category.index}',
                                            'score': round(float(category.score), 5),
                                            'kind': entry['kind'], 'model': entry['name']})
        return predictions

    def close(self):
        for _, classifier, _ in self.classifiers:
            classifier.close()
