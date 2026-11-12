import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from index import app

client=TestClient(app)

def test_fail_closed_without_password():
    with patch.dict(os.environ, {'ADMIN_PASSWORD':''}):
        assert client.get('/').status_code == 503
        assert client.get('/api/status').status_code == 503

def test_auth_and_assets():
    with patch.dict(os.environ, {'ADMIN_PASSWORD':'example-test-password'}):
        assert client.get('/').status_code==401
        response=client.get('/',auth=('admin','example-test-password'))
        assert response.status_code==200
        assert '칼퇴' in response.text
        assert client.get('/app.js',auth=('admin','example-test-password')).status_code==200
        assert client.get('/styles.css',auth=('admin','example-test-password')).status_code==200
        assert client.get('/api/status',auth=('admin','example-test-password')).status_code==200

def test_unknown_provider_and_missing_key():
    with patch.dict(os.environ,{'ADMIN_PASSWORD':'example-test-password','G2B_API_KEY':''}):
        auth=('admin','example-test-password')
        assert client.post('/api/search',auth=auth,json={'module':'unknown'}).status_code==400
        r=client.post('/api/search',auth=auth,json={'module':'g2b','start':'2026-11-01','end':'2026-11-05'})
        assert r.status_code==422
        assert '인증키' in r.json()['detail']

def test_health():
    assert client.get('/health').json()['ok'] is True


def test_national_tax_status_validation():
    with patch.dict(os.environ, {'ADMIN_PASSWORD':'example-test-password','NTS_API_KEY':'test-key'}):
        r=client.post('/api/search',auth=('admin','example-test-password'),json={'module':'nts','numbers':'123'})
        assert r.status_code==422
        assert '사업자등록번호' in r.json()['detail']


def test_dart_bad_corp_code():
    with patch.dict(os.environ, {'ADMIN_PASSWORD':'example-test-password','DART_API_KEY':'test-key'}):
        r=client.post('/api/search',auth=('admin','example-test-password'),json={'module':'dart','corp_codes':'123'})
        assert r.status_code==422
        assert '8자리' in r.json()['detail']
