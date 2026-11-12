"""Clean-room HTTP adapters based on EXE metadata/manual, not decompiled source.

No request accepts client-provided credentials or arbitrary URLs.
No automatic exfiltration, scheduled jobs, or filesystem writes.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from urllib.parse import unquote
import os
import re
import httpx

MODULES = {
    'g2b': '나라장터 입찰공고',
    'nts': '거래처 사업자상태',
    'bizinfo': '기업마당 지원사업',
    'law': '국가법령',
    'dart': 'DART 기업공시',
}
KEY_ENV = {'g2b':'G2B_API_KEY', 'nts':'NTS_API_KEY','bizinfo':'BIZINFO_API_KEY','law':'LAW_OC','dart':'DART_API_KEY'}
G2B_OPERATIONS = {
    '용역':'getBidPblancListInfoServcPPSSrch',
    '물품':'getBidPblancListInfoThngPPSSrch',
    '공사':'getBidPblancListInfoCnstwkPPSSrch',
    '외자':'getBidPblancListInfoFrgcptPPSSrch',
}

class ProviderError(Exception):
    pass

def authkey(module):
    key = os.getenv(KEY_ENV[module], '').strip()
    if not key:
        raise ProviderError(f'{MODULES[module]} API 인증키가 서버에 설정되지 않았습니다.')
    return unquote(key) if module in ('g2b','nts') else key

def terms(value):
    return [v.strip().casefold() for v in re.split(r'[,\n]+',value or '') if v.strip()]

def normdate(value):
    return re.sub(r'[^0-9]', '', str(value or ''))[:8]

def as_items(value):
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value,list) else []

def first(d, *keys):
    for key in keys:
        v = d.get(key)
        if v is not None and str(v).strip():
            return str(v)
    return ''

def item(module, key, title, org='', published='', deadline='', url='', status='', extra=None):
    return {'module':module,'id':str(key),'title':title,'organization':org,'published_at':published,
            'deadline':deadline,'url':url,'status':status,'extra':extra or {}}

async def get_json(client, url, *, params=None, json=None):
    try:
        r = await client.request('POST' if json is not None else 'GET', url, params=params, json=json)
        r.raise_for_status()
        return r.json()
    except (httpx.TimeoutException, httpx.ConnectError):
        raise ProviderError('외부 API 연결이 실패했거나 응답시간을 초과했습니다.') from None
    except httpx.HTTPStatusError as e:
        raise ProviderError(f'외부 API HTTP {e.response.status_code} 오류 (인증·승인·호출한도 확인)') from None
    except ValueError:
        raise ProviderError('외부 API가 JSON이 아닌 응답을 반환했습니다.') from None


def check_period(start, end, max_days=31):
    try:
        a = date.fromisoformat(start); b=date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ProviderError('시작일과 종료일은 YYYY-MM-DD 형식이어야 합니다.')
    if a>b or (b-a).days > max_days:
        raise ProviderError(f'조회 기간은 0~{max_days}일 이내여야 합니다.')
    return a,b

async def g2b(client, p):
    key = authkey('g2b')
    start,end=check_period(p.start,p.end, 31)
    category = p.category if p.category in G2B_OPERATIONS else '공사'
    op = G2B_OPERATIONS[category]
    found={}
    # Data.go.kr API requires the minute granularity as in original metadata.
    for page in range(1, p.pages+1):
        params={'serviceKey':key,'type':'json','numOfRows':100,'pageNo':page,
                'inqryDiv':'1','inqryBgnDt':start.strftime('%Y%m%d')+'0000',
                'inqryEndDt':end.strftime('%Y%m%d')+'2359'}
        data=await get_json(client, f'https://apis.data.go.kr/1230000/ad/BidPublicInfoService/{op}',params=params)
        response=data.get('response',{})
        header=response.get('header',{})
        if str(header.get('resultCode','00')) not in ('00','0'):
            raise ProviderError(f"나라장터 API 오류: {header.get('resultMsg','unknown')}")
        body=response.get('body',{})
        rows=as_items((body.get('items') or {}).get('item') if isinstance(body.get('items'),dict) else body.get('items'))
        for d in rows:
            if not isinstance(d,dict): continue
            title=first(d,'bidNtceNm')
            org=first(d,'dminsttNm','ntceInsttNm')
            raw=' '.join([title,org,str(d.get('bidNtceDtlUrl',''))]).casefold()
            if p.keyword and not any(t in raw for t in terms(p.keyword)): continue
            if p.organization and p.organization.casefold() not in org.casefold(): continue
            # region is an approximate metadata substring, not eligibility verification.
            if p.region and p.region.casefold() not in str(d).casefold(): continue
            rid=first(d,'bidNtceNo')+'-'+first(d,'bidNtceOrd')
            found[rid]=item('g2b',rid,title,org,first(d,'bidNtceDt'),first(d,'bidClseDt'),
                    first(d,'bidNtceDtlUrl'),category,d)
        if len(rows)<100: break
    return list(found.values())

async def nts(client, p):
    key=authkey('nts')
    values=[]
    for line in (p.numbers or '').splitlines():
        # comma-separated company name + number, OR number alone.
        bits=[v.strip() for v in line.split(',')]
        number=re.sub(r'\D','',''.join(bits[-1:]))
        if number:
            if len(number)!=10: raise ProviderError(f'잘못된 사업자등록번호: {line[:45]}')
            values.append((number,','.join(bits[:-1])))
    values=list(dict((n,(n,name)) for n,name in values).values())
    if not values: raise ProviderError('사업자번호를 한 줄에 하나씩 입력하세요.')
    if len(values)>100: raise ProviderError('한 번에 최대 100개 사업자번호를 조회할 수 있습니다.')
    name_map=dict(values)
    out=[]
    for offset in range(0,len(values),100):
        nums=[x[0] for x in values[offset:offset+100]]
        data=await get_json(client,'https://api.odcloud.kr/api/nts-businessman/v1/status',
                            params={'serviceKey':key},json={'b_no':nums})
        if data.get('status_code') not in (None,'OK', '200',200):
            raise ProviderError(f"국세청 응답 오류: {data.get('status_code')}")
        for d in as_items(data.get('data')):
            n=first(d,'b_no')
            out.append(item('nts',n,name_map.get(n) or n,first(d,'tax_type'),
                datetime.now().date().isoformat(),'', '',first(d,'b_stt'),d))
    return out

async def dart(client,p):
    key=authkey('dart')
    start,end=check_period(p.start,p.end, 90)
    corps=[v.strip() for v in p.corp_codes.split(',') if v.strip()]
    if any(not re.fullmatch(r'\d{8}',c) for c in corps):
        raise ProviderError('DART 기업 고유번호는 8자리여야 합니다.')
    if len(corps)>10: raise ProviderError('기업번호는 10개까지 입력할 수 있습니다.')
    output={}
    # DART API page_count up to 100; cap pages for serverless execution.
    for corp in (corps or ['']):
        for page in range(1,p.pages+1):
            params={'crtfc_key':key,'bgn_de':start.strftime('%Y%m%d'),'end_de':end.strftime('%Y%m%d'),
                    'page_no':page,'page_count':100}
            if corp: params['corp_code']=corp
            data=await get_json(client,'https://opendart.fss.or.kr/api/list.json',params=params)
            if data.get('status')=='013':break
            if data.get('status')!='000':
                raise ProviderError(f"DART 오류 {data.get('status')}: {data.get('message','')}")
            rows=as_items(data.get('list'))
            for d in rows:
                rid=first(d,'rcept_no'); title=first(d,'report_nm')
                if p.keyword and not any(t in (title+' '+first(d,'corp_name')).casefold() for t in terms(p.keyword)):continue
                output[rid]=item('dart',rid,title,first(d,'corp_name'),first(d,'rcept_dt'),'',
                     f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rid}',first(d,'pblntf_ty'),d)
            if len(rows)<100:break
    return list(output.values())

async def bizinfo(client,p):
    key=authkey('bizinfo')
    data=await get_json(client,'https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do',
              params={'crtfcKey':key,'dataType':'json','searchLclasId':p.category if p.category!='전체' else '',
                      'hashtags':p.keyword})
    rows=data.get('jsonArray') or data.get('items') or data.get('item') or []
    if isinstance(rows,dict):rows=rows.get('item',rows)
    if not isinstance(rows,(dict,list)):
        raise ProviderError('기업마당 JSON 응답 구조가 예상과 다릅니다.')
    result=[]
    for d in as_items(rows)[:p.max_results]:
        if not isinstance(d,dict):continue
        title=first(d,'pblancNm','title','nttNm')
        if p.keyword and not any(t in (title+' '+str(d)).casefold() for t in terms(p.keyword)):continue
        url=first(d,'pblancUrl','link','originUrl','detailUrl')
        if url.startswith('/'):url='https://www.bizinfo.go.kr'+url
        result.append(item('bizinfo',first(d,'pblancId','bizPbancSn','seq','nttId') or title,
             title,first(d,'jrsdInsttNm','originEngnNm','originOrg'),first(d,'creatPnttm','pubDate'),
             first(d,'reqstEndDt'),url,'지원사업',d))
    return result

async def law(client,p):
    key=authkey('law')
    if not terms(p.keyword):raise ProviderError('법령명을 입력하세요.')
    out={}
    for query in terms(p.keyword)[:5]:
        data=await get_json(client,'https://www.law.go.kr/DRF/lawSearch.do',
           params={'OC':key,'target':'law','type':'JSON','query':query,'display':100,'page':1})
        root=data.get('LawSearch') or {}
        rows=(root.get('법령') or []) if isinstance(root,dict) else []
        for d in as_items(rows):
            if not isinstance(d,dict): continue
            name=first(d,'법령명한글','법령명')
            if query not in name.casefold():continue
            rid=first(d,'법령ID','법령일련번호') or name
            url=first(d,'법령상세링크')
            if url.startswith('/'):url='https://www.law.go.kr'+url
            if not url.startswith('https://'):url='https://www.law.go.kr/법령/'+name
            out[rid]=item('law',rid,name,first(d,'소관부처명'),first(d,'공포일자'),
                first(d,'시행일자'),url,first(d,'제개정구분명'),d)
    return list(out.values())

ADAPTERS={'g2b':g2b,'nts':nts,'dart':dart,'bizinfo':bizinfo,'law':law}
