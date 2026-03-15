# Hybrid Search — Dense + Sparse(BM25) 융합 검색

## 개요

RAG 파이프라인의 검색 품질을 높이기 위해, 기존 Dense(임베딩) 검색에 Sparse(BM25) 검색을 결합한 **Hybrid Search**를 도입한다. 두 검색 방식의 강점을 RRF(Reciprocal Rank Fusion)로 융합하여, 의미적 유사성과 키워드 정확성을 동시에 확보한다.

---

## 기술적 배경

### Dense Search (의미 검색)

```
질의 → KURE-v1 임베딩 → 1024차원 벡터 → 코사인 유사도 검색
```

- **원리:** 텍스트를 고차원 벡터 공간에 매핑하여 의미적 거리를 계산
- **강점:** "내 집 마련 방법" → "주택 구입 전략" 같은 **동의어·유사 표현**을 잡아냄
- **약점:** "DSR 40%" 같은 **고유 키워드·숫자·약어**가 매칭에서 누락될 수 있음

### Sparse Search (키워드 검색 / BM25)

```
질의 → 형태소 분석(Kiwi) → 토큰화 → TF 값 SparseVector 생성 → BM25 스코어링
```

- **원리:** 전통적 정보 검색(IR) 방식. 문서에 등장하는 **정확한 단어**의 빈도(TF)와 희소성(IDF)으로 관련도를 계산
- **강점:** "재건축 초과이익환수제", "DSR", "강남구" 같은 **정확한 키워드 매칭**에 강함
- **약점:** 단어가 다르면 같은 의미라도 매칭 불가 ("집값" ≠ "부동산 가격")

### Hybrid Search (융합 검색)

```
질의 ──┬── Dense 검색  → top-N 후보 ──┐
       └── Sparse 검색 → top-N 후보 ──┴── RRF 융합 → 최종 top-K
```

- **원리:** Dense와 Sparse 각각의 결과를 RRF(Reciprocal Rank Fusion) 알고리즘으로 순위를 합산
- **RRF 공식:** `score(d) = Σ 1 / (k + rank_i(d))` (k=60이 일반적)
- **효과:** 두 검색 모두에서 상위에 오른 문서가 가장 높은 점수를 받음

---

## BM25 Sparse 벡터 생성 파이프라인

### 아키텍처

```
텍스트
  │
  ▼
┌─────────────────────────┐
│  Kiwi 형태소 분석기      │
│  - 내용어 추출 (명사,    │
│    동사, 형용사, 부사 등)  │
│  - 접두사(XPN) 포함      │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  복합명사 결합            │
│  - 인접 명사 bigram 결합  │
│    (재+건축 → 재건축)     │
│  - trigram 결합           │
│    (초과+이익+환수)       │
│  - 개별 형태소도 유지     │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  해시 기반 인덱스 매핑    │
│  - MD5 해시 → 정수 인덱스 │
│  - 해시 공간: 2^31 - 1    │
│  - TF(빈도) 값 계산      │
└──────────┬──────────────┘
           │
           ▼
  SparseVector(indices, values)
```

### 왜 한국어 형태소 분석이 필요한가?

영어는 공백으로 단어가 분리되지만, 한국어는 **교착어**로서 어근에 조사·어미가 붙는다.

| 입력 | 단순 공백 분리 | Kiwi 형태소 분석 |
|---|---|---|
| "강남구 아파트 시세 전망은 어떤가요?" | `강남구`, `아파트`, `시세`, `전망은`, `어떤가요?` | `강남구`, `아파트`, `시세`, `전망` |
| "전세사기 예방하려면 어떻게 해야 하나요?" | `전세사기`, `예방하려면`, `어떻게`, `해야`, `하나요?` | `전세`, `사기`, `예방`, `전세사기` |
| "재건축 초과이익환수제가 뭔가요?" | `재건축`, `초과이익환수제가`, `뭔가요?` | `건축`, `초과`, `이익`, `환수`, `재건축`, `초과이익`, `이익환수` |

공백 분리 시 "전망**은**", "예방**하려면**" 처럼 조사/어미가 붙어 다른 문서의 "전망", "예방"과 매칭되지 않는다. 형태소 분석을 통해 **원형(lemma)**을 추출해야 정확한 키워드 매칭이 가능하다.

### 복합명사 결합 전략

한국어 형태소 분석기는 복합명사를 최소 단위로 분리하는 경향이 있다 (예: "재건축" → "재" + "건축"). 이를 보완하기 위해 **인접 명사 n-gram 결합**을 수행한다.

```
원본: "재건축 초과이익환수제"
형태소: [재(XPN), 건축(NNG), 초과(NNG), 이익(NNG), 환수(NNG)]

→ 개별:  건축, 초과, 이익, 환수
→ bigram:  재건축, 건축초과, 초과이익, 이익환수
→ trigram: 재건축초과, 건축초과이익, 초과이익환수
```

이렇게 하면 "재건축"으로 검색해도, "초과이익"으로 검색해도 해당 문서가 매칭된다.

### Qdrant의 IDF 자동 계산

컬렉션 생성 시 `SparseVectorParams(modifier=Modifier.IDF)`를 설정하면, Qdrant가 **IDF(Inverse Document Frequency)를 서버 측에서 자동 계산**한다. 클라이언트는 **TF(Term Frequency)만 제공**하면 된다.

```
최종 BM25 스코어 = TF(클라이언트 제공) × IDF(Qdrant 자동 계산)
```

이 방식의 장점:
- 문서가 추가/삭제될 때 IDF가 자동으로 재계산됨
- 클라이언트 코드가 단순해짐 (TF만 계산)
- 별도의 IDF 사전 관리가 불필요

---

## 도입 필요성

### Phase 1.1 테스트에서 발견된 문제

2026-03-15 임베딩 데이터 테스트 결과, 다음 문제가 확인되었다:

1. **Hybrid 검색 비활성 상태** — Sparse 벡터가 저장·질의 모두에서 빈 값으로 처리되어 실질적으로 Dense 검색만 동작
2. **Dense-Hybrid 일치율 100%** — Hybrid가 Dense와 동일한 결과를 반환하여 차별적 가치 없음
3. **키워드 매칭 부재** — "DSR 40%", "강남구" 같은 고유 키워드가 의미 검색에서 간접적으로만 매칭

### Hybrid 검색이 필요한 실제 시나리오

| 시나리오 | Dense만 | Hybrid |
|---|---|---|
| "DSR 규제가 대출한도에 미치는 영향" | 의미적으로 유사한 문서를 찾지만, "DSR"이라는 약어 매칭이 약할 수 있음 | "DSR" 키워드로 정확히 매칭 + 의미적 유사 문서 결합 |
| "서울/강남구 재건축 초과이익환수제" | 재건축 관련 문서를 넓게 검색 | "강남구", "재건축", "초과이익환수" 키워드 매칭으로 정확도 향상 |
| "2024년 스트레스 DSR 변경" | "DSR 변경"의 의미를 이해하지만 연도 매칭이 약함 | "2024", "스트레스", "DSR" 키워드로 시점 특정 가능 |

---

## 구현 파일 구조

```
codes/embedding/
├── sparse_bm25.py        # BM25 Sparse 벡터 생성기 (Kiwi 형태소 분석)
├── upserter.py            # [수정] upsert 시 dense + sparse 벡터 동시 저장
├── search_test.py         # [수정] hybrid 검색 시 실제 sparse 질의 벡터 전달
└── backfill_sparse.py     # 기존 포인트에 sparse 벡터 보강 (일회성 마이그레이션)
```

### sparse_bm25.py — 핵심 함수

| 함수 | 용도 |
|---|---|
| `tokenize(text)` | 텍스트 → 내용어 토큰 리스트 (복합명사 결합 포함) |
| `get_sparse_vector(text)` | 단일 텍스트 → `SparseVector` |
| `get_sparse_vectors(texts)` | 배치 텍스트 → `SparseVector` 리스트 |

### 사용 예시

#### 색인 시 (upserter.py)

```python
from sparse_bm25 import get_sparse_vectors

texts = [chunk.text for chunk in chunks]
sparse_vectors = get_sparse_vectors(texts)

PointStruct(
    id=chunk_id,
    vector={
        "dense": dense_embedding,    # KURE-v1 1024D
        "sparse": sparse_vectors[i], # BM25 TF
    },
    payload={...},
)
```

#### 검색 시 (search_test.py)

```python
from sparse_bm25 import get_sparse_vector

sparse_vector = get_sparse_vector("강남구 재건축 투자 전망")

client.query_points(
    prefetch=[
        Prefetch(query=dense_vector, using="dense", limit=10),
        Prefetch(query=sparse_vector, using="sparse", limit=10),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=5,
)
```

---

## 기존 데이터 마이그레이션

기존 93,943개 포인트에는 sparse 벡터가 없다. `backfill_sparse.py`로 보강한다.

```bash
# 컨테이너 내부에서 실행
python codes/embedding/backfill_sparse.py

# 또는 소량 테스트
python codes/embedding/backfill_sparse.py --limit 100
```

**동작 방식:**
1. `scroll` API로 포인트를 배치 단위로 순회
2. 각 포인트의 `text` 페이로드를 읽어 `get_sparse_vectors()`로 sparse 벡터 생성
3. `update_vectors` API로 sparse 슬롯만 업데이트 (dense 벡터는 유지)

---

## 기대 효과

| 항목 | 개선 전 (Dense only) | 개선 후 (Hybrid) |
|---|---|---|
| 키워드 정확도 | 의미적 근사 매칭만 가능 | 정확한 키워드 + 의미 매칭 결합 |
| 고유명사/약어 검색 | "DSR", "LTV" 등 약어 매칭 불안정 | BM25로 정확 매칭 보장 |
| Dense-Hybrid 일치율 | 100% (차별 없음) | 70~85% 예상 (상호보완 영역 발생) |
| 검색 다양성 | Dense 편향 결과만 반환 | 키워드 관점의 관련 문서도 상위 노출 |
| RAG 응답 품질 | 검색 누락 시 환각 위험 | 키워드 매칭으로 사실 기반 문서 확보율 향상 |

### 주의사항

- sparse 벡터 보강(backfill) 후 Qdrant의 IDF 통계가 수렴하려면 전체 포인트에 대해 완료되어야 한다
- 향후 새 문서 색인 시에는 `upserter.py`가 자동으로 dense + sparse를 함께 저장한다
- Kiwi 형태소 분석기의 로드 시간(~1초)은 첫 호출에만 발생하며, 이후는 싱글톤으로 재사용된다
