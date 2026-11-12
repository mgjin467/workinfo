"""Vercel FastAPI entrypoint. Credentials never leave the server."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
import base64
import hmac
import os
import re
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from api_clients import ADAPTERS, KEY_ENV, MODULES, ProviderError

BASE=Path(__file__).parent
app=FastAPI(title='칼퇴 업무정보 — Vercel', docs_url=None, redoc_url=None, openapi_url=None)

@app.middleware('http')
async def authentication(request:Request, call_next):
    if request.url.path == '/health':
        return await call_next(request)
    password=os.getenv('ADMIN_PASSWORD','').strip()
    # Fail closed: a publicly accessible instance cannot run without ADMIN_PASSWORD.
    if not password:
        return JSONResponse(status_code=503,content={'detail':'ADMIN_PASSWORD 환경변수를 설정해야 서비스를 사용할 수 있습니다.'})
    header=request.headers.get('authorization','')
    try:
        scheme, b64=header.split(' ',1)
        decoded=base64.b64decode(b64, validate=True).decode('utf-8')
        user, supplied=decoded.split(':',1)
        valid=(scheme.lower()=='basic' and hmac.compare_digest(user,'admin')
               and hmac.compare_digest(supplied,password))
    except Exception:
        valid=False
    if not valid:
        return JSONResponse(status_code=401, content={'detail':'로그인이 필요합니다.'},
                            headers={'WWW-Authenticate':'Basic realm="Kaltoe Workplace"'})
    return await call_next(request)

@app.get('/health')
def health():
    return {'ok':True,'service':'kaltoe-web'}

@app.get('/')
def homepage():
    return FileResponse(BASE/'public'/'index.html')

@app.get('/styles.css')
def styles():
    return FileResponse(BASE/'public'/'styles.css',media_type='text/css')

@app.get('/app.js')
def client_js():
    return FileResponse(BASE/'public'/'app.js',media_type='application/javascript')

@app.get('/api/status')
def status():
    return {'modules':[{'id':k,'name':v,'configured':bool(os.getenv(KEY_ENV[k],'').strip())} for k,v in MODULES.items()],
            'telegram_configured':bool(os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID')),
            'storage':'browser-local-only','version':'0.1.0'}

class SearchRequest(BaseModel):
    module: str
    start: str = Field(default_factory=lambda:(date.today()-timedelta(days=7)).isoformat(),max_length=10)
    end: str = Field(default_factory=lambda:date.today().isoformat(),max_length=10)
    category: str = Field('공사',max_length=50)
    keyword: str = Field('',max_length=300)
    organization: str = Field('',max_length=100)
    region: str = Field('',max_length=80)
    numbers: str = Field('',max_length=5000)
    corp_codes: str = Field('',max_length=200)
    pages: int = Field(2,ge=1,le=5)
    max_results: int = Field(100,ge=1,le=500)

@app.post('/api/search')
async def search(req:SearchRequest):
    if req.module not in ADAPTERS:
        raise HTTPException(status_code=400,detail='지원되지 않는 모듈입니다.')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(17.0),follow_redirects=False,
                 headers={'User-Agent':'CompanyWatch-Web/0.1','Accept':'application/json'}) as client:
            rows=await ADAPTERS[req.module](client,req)
        return {'module':req.module,'count':len(rows),'items':rows[:500]}
    except ProviderError as e:
        raise HTTPException(status_code=422,detail=str(e)) from None
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail='외부 API 연결 중 오류가 발생했습니다.') from None

class TelegramMessage(BaseModel):
    text: str = Field(min_length=1,max_length=2000)

@app.post('/api/telegram/test')
async def telegram_test(req:TelegramMessage):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    chat_id=os.getenv('TELEGRAM_CHAT_ID','').strip()
    if not token or not chat_id:
        raise HTTPException(status_code=422,detail='텔레그램 환경변수가 설정되지 않았습니다.')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{25,}',token):
        raise HTTPException(status_code=422,detail='텔레그램 토큰 형식이 유효하지 않습니다.')
    try:
        async with httpx.AsyncClient(timeout=12.0,follow_redirects=False) as client:
            r=await client.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                json={'chat_id':chat_id,'text':req.text})
            r.raise_for_status()
            data=r.json()
            if not data.get('ok'):raise ValueError('Telegram API failed')
        return {'ok':True}
    except (httpx.HTTPError,ValueError):
        raise HTTPException(status_code=502,detail='텔레그램 발송 실패: Chat ID 및 토큰을 확인하세요.') from None
