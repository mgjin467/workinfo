# 칼퇴 업무정보 — Vercel 웹 전환 프로젝트

이 프로젝트는 업로드된 `칼퇴 업무정보.exe`(Python 3.12 / PyInstaller / PySide6)의 **정적 분석 및 내장 사용설명서에 기반하여 새로 작성한 웹 버전**입니다. 바이트코드에서 확인한 API 제공기관과 일부 엔드포인트를 참조했으나 원본 Python 소스코드 전체가 복원된 것이 아닙니다.

## 구현 범위
- 반응형 업무 대시보드, 모듈별 검색 및 결과 상세 확인
- 나라장터 공사·물품·용역·외자 공고 조회(기본 2페이지, 최대 5페이지)
- 국세청 사업자상태 조회(한 번에 최대 100개 번호)
- 기업마당 지원사업 / 국가법령정보센터 / Open DART 조회 어댑터
- 결과 내 검색, CSV 다운로드(수식 인젝션 방지), 브라우저별 관심 목록(localStorage)
- 환경변수 기반 API 키 관리, 기본 HTTP Basic 로그인(필수), 텔레그램 수동 연결 테스트
- HTML/CSS/JS 자체 포함, 빌드 단계 불필요

## 배포 (Vercel)
1. 프로젝트 폴더를 GitHub **비공개 저장소**에 업로드합니다. `extracted/*.dll`, `*.pyd`, EXE, 원본 .env는 업로드하지 마세요.
2. Vercel > Add New > Project에서 해당 저장소를 Import합니다.
3. Framework Preset은 `Other`, Root Directory는 저장소 루트로 둡니다. 빌드 명령은 비워 둡니다.
4. Settings > Environment Variables에서 `ADMIN_PASSWORD`를 **반드시** 입력합니다. 빈 값이면 서버가 503을 반환합니다.
5. 사용할 모듈의 환경변수(`G2B_API_KEY`, `NTS_API_KEY`, `BIZINFO_API_KEY`, `LAW_OC`, `DART_API_KEY`)를 입력합니다.
6. 텔레그램 시험 발송을 원하면 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 추가합니다.
7. Deploy 후 사이트에 접속합니다. 브라우저 인증 대화상자에서 사용자명은 `admin`, 비밀번호는 `ADMIN_PASSWORD`입니다.
8. **Vercel Preview 배포도 공개될 수 있으니** 비밀번호를 항상 설정하고, 보안이 중요한 사용 시 Vercel Deployment Protection을 추가하세요.

### 로컬 실행

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# 운영체제 환경변수에 ADMIN_PASSWORD 와 원하는 API 키 입력
uvicorn index:app --reload
```

접속 `http://localhost:8000` — `/health`는 로그인 없이 체크 가능, 그 외 경로는 로그인 필요.

## 중요 제한 및 원본 대비 차이
- EXE 소스코드는 `.marshal` 바이트코드만 추출되었고, 현재 작업은 **기능 기반 재구현**입니다.
- API 엔드포인트와 주요 데이터 필드명은 원본 바이트코드 분석으로 식별했지만 각 기관에 실제 키를 연결해 실시간 호출 테스트하지 않았습니다. 기관별 활용신청 및 최신 API 응답 구조를 확인해야 합니다.
- **영구 클라우드 DB / 조회 이력 / 상태변경 추적 / 실시간 자동조회 / 예약수집 / 다중 사용자 동기화는 미구현**입니다. 관심 목록은 브라우저 localStorage만 사용합니다. 보안상 민감한 연락처나 거래처 상태 결과는 자동 저장하지 않습니다.
- 법령 개정 비교, 나라장터 모든 페이지 전수 수집, 원본 Excel 세부 시트 복제, 고급 필터 및 모듈 전체 동시 조회는 추가 개발 대상입니다.
- EXE에 포함된 `secure_settings`의 Windows DPAPI는 서버에서 사용하지 않습니다. 키는 Vercel 환경변수로만 관리합니다.
- 원본 EXE 또는 DLL을 실행하거나 프로젝트에 포함하지 않습니다. 추출한 자료는 `recovered_reference/`의 비실행 리소스만 포함합니다.
- 업무용/상용 사용에는 Vercel 요금제 약관 및 사용량 정책을 확인하세요.

## 보안 주의
- `ADMIN_PASSWORD`는 강력한 임의 문자열로 설정하고 개인별 인증이 필요한 경우 정식 인증 시스템으로 교체하세요.
- 비밀번호/토큰을 프론트엔드 JS, 쿼리파라미터, Git 저장소에 기록하지 마세요.
- 기본 인증은 HTTPS를 통해서만 사용해야 합니다. 브라우저 공유 PC에서 로그인 상태를 유지할 수 있습니다.
- 무료 공개 배포에서 API 쿼터 남용을 방지하려면 추가 사용자별 레이트리밋과 호출량 관리가 필요합니다.
- 나라장터 지역 필터는 검색 응답에 등장한 지역 문자열을 근사 매칭하며, 실제 참가자격 및 현장 소재지 확인은 원문을 확인해야 합니다.
- CSV에는 Excel 수식 실행 방지를 위한 문자 이스케이프를 적용했습니다.

## 기술 구성

```
index.py                 FastAPI 웹앱 + 로그인 + API 라우트
api_clients.py           기관별 비밀키 서버 프록시 및 응답 정규화
public/index.html        대시보드 UI
public/styles.css        반응형 스타일
public/app.js            검색·관심·CSV·상세보기
recovered_reference/     원본 실행파일에서 추출한 문서/필드맵(비실행)
requirements.txt         Python 의존성
vercel.json              서울 리전 지정
.env.example             환경변수 샘플
```

## 공식 문서
- https://vercel.com/docs/frameworks/backend/fastapi
- https://vercel.com/docs/project-configuration/environment-variables
- https://vercel.com/docs/cron-jobs
