import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .advisor import AnalysisUnavailable, OllamaAdvisor
from .images import save_image
from .storage import Store
from .vision import PlantVision

log = logging.getLogger('plant_clinic')
STATIC = Path(__file__).parent / 'static'


def create_app(data_dir=None, vision=None, advisor=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(Path(data_dir or config.DATA_DIR))
        app.state.vision = vision if vision is not None else PlantVision(config.MODEL_DIR)
        app.state.advisor = advisor if advisor is not None else OllamaAdvisor()
        app.state.analysis_lock = asyncio.Lock()
        yield
        app.state.vision.close()
        await app.state.advisor.close()

    app = FastAPI(title='Plant Clinic', version='1.0.0', lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware('http')
    async def local_headers(request: Request, call_next):
        # Browsers on unrelated websites must not write to this localhost service.
        if request.method in {'POST', 'DELETE', 'PUT', 'PATCH'}:
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': 'Open Plant Clinic directly to make changes.'}, status_code=403)
        length = request.headers.get('content-length', '')
        if length.isdigit() and int(length) > config.MAX_UPLOAD_BYTES + 64 * 1024:
            return JSONResponse({'detail': 'Choose an image smaller than 10 MB.'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    async def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/api/health')
    async def health(request: Request):
        ollama = await request.app.state.advisor.status()
        mediapipe = request.app.state.vision.status()
        can_analyze = ollama['available'] and (ollama.get('vision_model') or mediapipe['available'])
        return {'status': 'ready' if can_analyze else 'setup_required', 'ollama': ollama,
                'mediapipe': mediapipe, 'version': '1.0.0'}

    @app.get('/api/scans')
    async def list_scans(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        return request.app.state.store.list(limit, offset)

    def get_scan(request: Request, scan_id: str):
        scan = request.app.state.store.get(scan_id)
        if scan is None:
            raise HTTPException(404, 'This scan was not found.')
        return scan

    async def analyze(request, scan_id):
        state = request.app.state
        scan = get_scan(request, scan_id)
        path = state.store.uploads / f'{scan_id}.jpg'
        try:
            try:
                predictions = await asyncio.to_thread(state.vision.classify, path)
            except Exception:
                log.exception('Specialist model failed for scan %s; trying local vision model', scan_id)
                predictions = []
            state.store.update(scan_id, predictions=predictions)
            report, method, model = await state.advisor.analyze(path, predictions, scan['crop'], scan['notes'])
            # Closed-set leaf scores are meaningless for unrelated photographs.
            if report['category'] == 'not_plant':
                predictions = []
            status = 'needs_review' if report['category'] == 'uncertain' or report['needs_expert'] else 'complete'
            return state.store.update(scan_id, status=status, report=report, predictions=predictions,
                                      analysis_method=method, model=model, error=None)
        except AnalysisUnavailable as exc:
            return state.store.update(scan_id, status='error', error=str(exc))
        except Exception:
            log.exception('Analysis failed for scan %s', scan_id)
            return state.store.update(scan_id, status='error', error='Analysis could not finish. Your photo is saved; retry or check the server log.')

    @app.post('/api/scans', status_code=201)
    async def upload(request: Request, file: UploadFile = File(...), crop: str = Form('', max_length=100), notes: str = Form('', max_length=1000)):
        state = request.app.state
        if state.analysis_lock.locked():
            raise HTTPException(409, 'Another photo is being analyzed. Please wait for it to finish.')
        async with state.analysis_lock:
            raw = await file.read(config.MAX_UPLOAD_BYTES + 1)
            await file.close()
            if len(raw) > config.MAX_UPLOAD_BYTES:
                raise HTTPException(413, 'Choose an image smaller than 10 MB.')
            scan_id = uuid4().hex
            try:
                await asyncio.to_thread(save_image, raw, state.store.uploads, scan_id)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            state.store.create(scan_id, crop.strip(), notes.strip())
            return await analyze(request, scan_id)

    @app.get('/api/scans/{scan_id}')
    async def scan_detail(request: Request, scan_id: str):
        return get_scan(request, scan_id)

    @app.get('/api/scans/{scan_id}/image')
    async def scan_image(request: Request, scan_id: str):
        get_scan(request, scan_id)
        return FileResponse(request.app.state.store.uploads / f'{scan_id}.jpg', media_type='image/jpeg')

    @app.get('/api/scans/{scan_id}/thumbnail')
    async def scan_thumbnail(request: Request, scan_id: str):
        get_scan(request, scan_id)
        return FileResponse(request.app.state.store.uploads / f'{scan_id}.thumb.jpg', media_type='image/jpeg')

    @app.post('/api/scans/{scan_id}/retry')
    async def retry(request: Request, scan_id: str):
        scan = get_scan(request, scan_id)
        state = request.app.state
        if state.analysis_lock.locked():
            raise HTTPException(409, 'Another photo is being analyzed. Please wait for it to finish.')
        async with state.analysis_lock:
            state.store.update(scan_id, status='processing', error=None, report=None,
                               predictions=[], analysis_method='', model='')
            return await analyze(request, scan['id'])

    @app.delete('/api/scans/{scan_id}', status_code=204)
    async def delete_scan(request: Request, scan_id: str):
        scan = get_scan(request, scan_id)
        if scan['status'] == 'processing':
            raise HTTPException(409, 'Wait for this analysis to finish before deleting it.')
        request.app.state.store.delete(scan_id)
        return Response(status_code=204)

    app.mount('/static', StaticFiles(directory=STATIC, check_dir=False), name='static')
    return app


app = create_app()
