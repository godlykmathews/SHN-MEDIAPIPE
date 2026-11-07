"""Opt-in real local model smoke test. Never modifies the user's saved history.

Usage: .venv/bin/python scripts/smoke_test.py /path/to/plant-photo.jpg
"""
import argparse
import io
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('photo', type=Path)
    parser.add_argument('--expect', choices=['disease', 'pest', 'healthy', 'uncertain', 'not_plant'], help='Optional expected category for the supplied image.')
    parser.add_argument('--output', type=Path, default=Path('/tmp/plant-clinic-smoke.json'))
    args = parser.parse_args()
    results = {}
    with tempfile.TemporaryDirectory(prefix='plant-clinic-smoke-') as directory:
        with TestClient(create_app(Path(directory))) as client:
            health = client.get('/api/health').json()
            results['health'] = health
            print(json.dumps({'health': health}), flush=True)
            assert health['status'] == 'ready', 'The local models are not ready.'
            pictures = [('supplied_image', args.photo.read_bytes())]
            image = Image.new('RGB', (500, 350), '#ececec')
            draw = ImageDraw.Draw(image)
            draw.rectangle((90, 70, 410, 280), fill='#316ba1')
            draw.text((120, 160), 'TEST GEOMETRIC RECTANGLE', fill='white')
            buffer = io.BytesIO()
            image.save(buffer, 'PNG')
            pictures.append(('unrelated', buffer.getvalue()))
            for name, raw in pictures:
                started = time.monotonic()
                response = client.post('/api/scans', files={'file': (name + '.jpg', raw, 'image/jpeg')})
                response.raise_for_status()
                scan = response.json()
                results[name] = {'elapsed_seconds': round(time.monotonic() - started, 2), 'scan': scan}
                args.output.write_text(json.dumps(results, indent=2))
                print(json.dumps({'case': name, 'elapsed': results[name]['elapsed_seconds'],
                                  'status': scan['status'], 'issue': (scan.get('report') or {}).get('issue'),
                                  'category': (scan.get('report') or {}).get('category'),
                                  'error': scan.get('error')}), flush=True)
                assert scan['status'] != 'error', scan['error']
                if name == 'supplied_image' and args.expect:
                    assert scan['report']['category'] == args.expect
                assert client.get(scan['image_url']).status_code == 200
                assert client.get(scan['thumbnail_url']).status_code == 200
                assert client.get('/api/scans').json()['total'] == len(results) - 1
                if name == 'unrelated':
                    assert scan['report']['category'] == 'not_plant', 'The unrelated image was not rejected.'
                    assert scan['predictions'] == []
            assert client.get('/').status_code == 200
    print(f'Real model checks passed. Report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
