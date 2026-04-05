# Phase 4: API 연동 상세 가이드

## 1. API 클라이언트 아키텍처

### 1.1 클래스 계층

```
BaseAPIClient (abstract)
    │
    ├── JsonAPIClient ── 카카오, KOSIS, SGIS, 네이버뉴스, 빅카인즈
    │
    ├── XmlAPIClient ─── 실거래가, 건축물대장, 토지이용규제, 온비드
    │
    └── WmsWfsClient ─── VWorld (Phase 4.1)
```

### 1.2 공통 기능 (BaseAPIClient)

| 기능 | 구현 | 설명 |
|------|------|------|
| **재시도** | Exponential backoff (1s, 2s, 4s, max 30s) | 429/500/502/503, TimeoutError 시 재시도 |
| **레이트 리미팅** | AsyncTokenBucket | API별 초당 허용량 제한 |
| **일일 쿼터** | DailyQuotaTracker | data.go.kr 일일 1,000건 등 |
| **캐싱** | Redis (프로덕션) / InMemory (개발) | 응답별 TTL 차등 적용 |
| **인증** | QUERY_PARAM / HEADER / NONE | API별 인증 방식 |
| **XML 파싱** | data.go.kr 공통 envelope 처리 | `<response><header><body>` 구조 |
| **에러 분류** | 6종 에러 타입 | retryable 여부 자동 판단 |

### 1.3 에러 타입

| 에러 | 재시도 | 발생 조건 |
|------|:------:|----------|
| `APITimeoutError` | O | 연결/응답 타임아웃 |
| `APIRateLimitError` | O | HTTP 429, 일일 쿼터 초과 |
| `APIServerError` | O | HTTP 5xx |
| `APIParseError` | O | XML/JSON 파싱 실패 |
| `APIAuthError` | X | HTTP 401/403 |
| `APIInvalidParamsError` | X | HTTP 400 |
| `APINoDataError` | X | 유효 응답이나 데이터 없음 |

---

## 2. API별 상세 연동 가이드

### 2.1 국토교통부 실거래가 API

**엔드포인트:**
```
아파트 매매: http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev
아파트 전월세: http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent
```

**요청 파라미터:**

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `serviceKey` | 인증키 (URL 인코딩 주의) | `%2F...` |
| `LAWD_CD` | 법정동코드 앞 5자리 | `11680` (강남구) |
| `DEAL_YMD` | 거래년월 | `202604` |
| `pageNo` | 페이지 번호 | `1` |
| `numOfRows` | 페이지당 행 수 | `100` |

**응답 필드 (매매):**

| 필드 | 설명 | 예시 |
|------|------|------|
| `거래금액` | 만원 단위 (콤마 포함) | `"85,000"` |
| `건축년도` | YYYY | `"2005"` |
| `년`/`월`/`일` | 계약일 | `"2026"`, `"3"`, `"15"` |
| `법정동` | 법정동명 | `"역삼동"` |
| `아파트` | 단지명 | `"래미안역삼"` |
| `전용면적` | m² | `"84.82"` |
| `층` | 거래 층 | `"15"` |
| `지번` | 지번 | `"677"` |
| `해제사유발생일` | 해제 시 | `"26.03.20"` |
| `해제여부` | 해제 거래 | `"O"` |

**구현 시 주의사항:**
1. **12개월 병렬 fetch**: 12개 월별 API 호출을 `Semaphore(3)`으로 제한하여 병렬 실행
2. **단지명 필터**: 응답은 해당 동의 모든 거래 → `아파트` 필드로 단지명 퍼지 매칭 필요
3. **해제 거래 필터**: `해제여부 == "O"` 인 거래는 취소된 거래이므로 제외
4. **금액 파싱**: 콤마, 공백 제거 후 정수 변환
5. **serviceKey 인코딩**: data.go.kr이 키를 이중 인코딩하므로, 원본(디코딩된) 키를 사용해야 할 수 있음

**캐시 전략:**
- 현재 월: TTL 24시간 (새 거래 추가 가능)
- 과거 월: TTL 30일 (확정된 데이터)
- 캐시 키: `deep_report:tx:{LAWD_CD}:{DEAL_YMD}`

### 2.2 건축물대장 API

**엔드포인트:**
```
기본개요: http://apis.data.go.kr/1613000/BldRgstHubService/getBrBasisOulnInfo
총괄표제부: http://apis.data.go.kr/1613000/BldRgstHubService/getBrRecapTitleInfo
표제부: http://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo
```

**요청 파라미터:**

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `sigunguCd` | 시군구코드 5자리 | `11680` |
| `bjdongCd` | 법정동코드 뒤 5자리 | `10300` |
| `bun` | 본번 4자리 (zero-padded) | `0677` |
| `ji` | 부번 4자리 (zero-padded) | `0000` |

**주요 응답 필드:**

| 필드 | 설명 |
|------|------|
| `platPlc` | 대지위치 |
| `mainPurpsCdNm` | 주용도 (공동주택 등) |
| `strctCdNm` | 구조 (철근콘크리트 등) |
| `useAprDay` | 사용승인일 (YYYYMMDD) |
| `totArea` | 연면적 (m²) |
| `grndFlrCnt` | 지상층수 |
| `ugrndFlrCnt` | 지하층수 |
| `hhldCnt` | 세대수 |
| `engrGrade` | 에너지효율등급 |
| `rideUseElvtCnt` | 승객용 승강기 수 |
| `totPkngCnt` | 총 주차대수 |

**캐시 전략:** TTL 7일 (건물 정보는 거의 변하지 않음)

### 2.3 카카오맵 API

#### Geocoding (키워드 검색)

```
GET https://dapi.kakao.com/v2/local/search/keyword.json
Headers: Authorization: KakaoAK {REST_API_KEY}
Params: query={검색어}
```

**응답 핵심 필드:**
```json
{
  "documents": [{
    "place_name": "마포래미안푸르지오",
    "address_name": "서울 마포구 아현동 716",
    "road_address_name": "서울 마포구 마포대로 217",
    "x": "126.956888",   // 경도
    "y": "37.554722",    // 위도
    "address": {
      "b_code": "1144012200",  // 법정동코드 10자리
      "h_code": "1144065000"   // 행정동코드
    }
  }]
}
```

#### 카테고리 장소검색 (주변 시설)

```
GET https://dapi.kakao.com/v2/local/search/category.json
Params: category_group_code={코드}&x={경도}&y={위도}&radius={미터}
```

**카테고리 코드:**

| 코드 | 분류 |
|------|------|
| `SW8` | 지하철역 |
| `SC4` | 학교 |
| `HP8` | 병원 |
| `MT1` | 대형마트 |
| `BK9` | 은행 |
| `CT1` | 문화시설 |
| `PK6` | 주차장 |

#### 길찾기 (Direction)

카카오모빌리티 API 사용:
```
GET https://apis-navi.kakaomobility.com/v1/directions
Headers: Authorization: KakaoAK {REST_API_KEY}
Params: origin={출발 lng,lat}&destination={도착 lng,lat}
```

### 2.4 토지이용규제 API

**엔드포인트:**
```
토지이용계획: http://apis.data.go.kr/1611000/nsdi/eios/LaIndUsService/attrInfoLaIndUs
```

**요청 파라미터:**

| 파라미터 | 설명 |
|----------|------|
| `pnu` | 19자리 필지고유번호 |

**응답 필드:**

| 필드 | 설명 | 예시 |
|------|------|------|
| `prposAreaDstrcCodeNm` | 용도지역명 | `"제3종일반주거지역"` |
| `cnflcAtCode` | 저촉여부코드 | |
| `etcLaws` | 기타 법률 관련 | |

### 2.5 KOSIS API

**엔드포인트:**
```
통계자료: https://kosis.kr/openapi/Param/statisticsParameterData.do
```

**핵심 파라미터:**

| 파라미터 | 설명 |
|----------|------|
| `apiKey` | 인증키 |
| `itmId` | 항목 ID |
| `objL1` | 분류값1 (지역코드) |
| `prdSe` | 수록주기 (M=월, Q=분기, Y=연) |
| `startPrdDe` | 시작 시점 |
| `endPrdDe` | 종료 시점 |
| `format` | json/xml |

**주요 통계표 ID:**

| 통계표 | 용도 |
|--------|------|
| `101_DT_1B040A3` | 시군구별 인구수 |
| `101_DT_1B040B4` | 시군구별 세대수 |
| `101_DT_1YL2001` | 시군구별 주택수 |
| `408_DT_30404_N0010` | 주택매매가격지수 |

### 2.6 SGIS API

**인증:** OAuth 토큰 발급 필요 (12시간 만료)
```
GET https://sgisapi.kostat.go.kr/OpenAPI3/auth/authentication.json
Params: consumer_key={}&consumer_secret={}
```

**격자 통계:**
```
GET https://sgisapi.kostat.go.kr/OpenAPI3/stats/grid.json
Params: accessToken={}&year=2023&lv=1&x_min=..&y_min=..&x_max=..&y_max=..
```

### 2.7 학교알리미 API

```
GET https://www.schoolinfo.go.kr/openApi.do
Params: apiKey={}&schulCode={학교코드}&datatDiv=공시항목코드
```

**공시 항목:** 학생수, 교원현황, 학업성취, 급식, 건강, 시설 등 15종

### 2.8 네이버 뉴스 검색 API

```
GET https://openapi.naver.com/v1/search/news.json
Headers: X-Naver-Client-Id: {}, X-Naver-Client-Secret: {}
Params: query={검색어}&display=10&sort=date
```

**응답:** 제목, 요약(description), 링크, 발행일, 언론사 (본문 전체 미제공)

### 2.9 빅카인즈 API

```
POST https://tools.kinds.or.kr/search/news
Body: {
  "access_key": "{}",
  "argument": {
    "query": "마포구 부동산",
    "published_at": {"from": "2025-01-01", "until": "2026-04-05"},
    "provider": [],
    "category": ["부동산"],
    "sort": {"date": "desc"},
    "return_from": 0,
    "return_size": 10
  }
}
```

**특장점:** NER(개체명인식), 뉴스 요약, 관계망 분석, 키워드 추출 내장

---

## 3. 캐시 정책

| 데이터 | 캐시 키 패턴 | TTL | 이유 |
|--------|-------------|-----|------|
| Kakao Geocoding | `geo:{input_hash}` | 30일 | 주소 변경 극히 드뭄 |
| 실거래가 (현재 월) | `tx:{lawd}:{yyyymm}` | 24시간 | 신규 거래 추가 가능 |
| 실거래가 (과거 월) | `tx:{lawd}:{yyyymm}` | 30일 | 확정 데이터 |
| 건축물대장 | `bld:{sigungu}:{bjdong}:{bun}:{ji}` | 7일 | 변경 드뭄 |
| 토지이용규제 | `land:{pnu}` | 7일 | 규제 변경 비빈번 |
| Kakao 주변검색 | `nearby:{lat_4dp}:{lng_4dp}:{cat}` | 24시간 | 시설 변동 느림 |
| KOSIS 통계 | `kosis:{table}:{region}` | 7일 | 월/분기 업데이트 |
| SGIS 격자 | `sgis:{x}:{y}` | 7일 | 분기 업데이트 |
| 뉴스 | `news:{keyword_hash}:{date}` | 6시간 | 시의성 중요 |
| 온비드 | `onbid:{sigungu}:{date}` | 12시간 | 경매 일정 변동 |

---

## 4. API 키 관리

`.env` 파일에 추가 필요한 키:

```env
# Phase 4 API Keys
KAKAO_REST_API_KEY=           # developers.kakao.com
DATA_GO_KR_SERVICE_KEY=       # data.go.kr (URL 디코딩 상태로 저장)
VWORLD_API_KEY=               # vworld.kr
KOSIS_API_KEY=                # kosis.kr/openapi
SGIS_CONSUMER_KEY=            # sgis.kostat.go.kr
SGIS_CONSUMER_SECRET=         # sgis.kostat.go.kr
NAVER_SEARCH_CLIENT_ID=       # developers.naver.com
NAVER_SEARCH_CLIENT_SECRET=   # developers.naver.com
BIGKINDS_API_KEY=             # bigkinds.or.kr
```

### API 키 신청 절차

| API | 신청 사이트 | 승인 소요 | 비고 |
|-----|-----------|----------|------|
| data.go.kr (실거래가 등) | data.go.kr 회원가입 → 활용신청 | 즉시~24시간 | 자동승인 대부분 |
| 카카오 | developers.kakao.com → 앱 등록 | 즉시 | REST API 키 발급 |
| VWorld | vworld.kr → 개발자 등록 | 즉시 | 무료 |
| KOSIS | kosis.kr → OpenAPI → 인증키 신청 | 즉시 | 1인 1키 |
| SGIS | sgis.kostat.go.kr → 개발지원센터 | 즉시 | consumer key+secret |
| 네이버 검색 | developers.naver.com → 앱 등록 | 즉시 | Client ID+Secret |
| 빅카인즈 | bigkinds.or.kr → 회원가입 | 즉시 | API 키 발급 |
