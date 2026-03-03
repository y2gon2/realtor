# Phase 1: RAG MVP 상세 기획서

> 진입 시점: v2 정제 문서 5,000개 확보 직후
> 기간: 2~4주
> 목표: 출처 인용 포함 부동산 Q&A가 가능한 동작하는 RAG 프로토타입 완성

---

## 0. 진입 시점 상태 및 전제 조건

| 항목 | 상태 |
|---|---|
| v2 정제 문서 | ~5,000개 (파일럿 색인에 충분) |
| v2 계속 생성 | 백그라운드에서 병행 진행 (목표 20,000개) |
| 임베딩 모델 | 미선정 → Week 1에 결정 |
| 벡터 DB | 미구축 → Week 2에 구축 |
| 평가 기준 | 없음 → Week 4에 수립 |

!!! note "병행 작업"
    v2 데이터 생성(Phase 0)은 Phase 1과 동시에 계속 진행한다.
    색인 파이프라인은 증분 삽입을 지원하므로, 문서가 늘어날수록 검색 품질이 자동으로 향상된다.

---

## 1. 프로젝트 구조 (코드베이스 설계)

Phase 1에서 생성할 폴더 구조:

```
rag/
├── src/
│   ├── indexer/          # 색인 파이프라인
│   │   ├── chunker.py    # v2 문서 → 청크 분리
│   │   ├── embedder.py   # 임베딩 생성 (배치)
│   │   └── upserter.py   # Qdrant 색인/갱신
│   ├── retriever/        # 검색 엔진
│   │   ├── hybrid.py     # BM25 + 벡터 하이브리드
│   │   ├── reranker.py   # Cross-encoder 리랭킹
│   │   └── filter.py     # 메타데이터 필터 생성
│   ├── llm/              # LLM 연동
│   │   ├── client.py     # Claude API 클라이언트
│   │   ├── prompts.py    # 프롬프트 템플릿
│   │   └── rag_chain.py  # 검색 → 생성 파이프라인
│   └── eval/             # 평가
│       ├── evaluator.py  # 자동 평가 실행
│       └── metrics.py    # Recall@K, MRR, 속도
├── scripts/
│   ├── index_all.py      # 전체 색인 배치 스크립트
│   └── eval_run.py       # 평가 실행 스크립트
├── config/
│   └── settings.yaml     # Qdrant URL, 모델명, 하이퍼파라미터
├── eval_set/             # 평가셋 (100개 Q&A 쌍)
└── tests/
```

---

## 2. Week 1: 환경 구성 + 임베딩 모델 선정

### 2-1. 개발 환경 구성

**Qdrant 로컬 실행 (Docker)**:

```bash
docker run -d -p 6333:6333 -p 6334:6334 \
  -v /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z \
  qdrant/qdrant

# 확인
curl http://localhost:6333/healthz
```

**Python 의존성**:

```bash
pip install qdrant-client \
            sentence-transformers \
            anthropic \
            pyyaml \
            tqdm \
            numpy
```

### 2-2. 임베딩 모델 벤치마크

후보 3종을 동일 조건에서 비교한다.

| 모델 | 파라미터 | 최대 토큰 | 특징 |
|---|---|---|---|
| `BAAI/bge-m3` | 570M | 8,192 | Dense + Sparse 통합, 다국어 강력 |
| `intfloat/multilingual-e5-large` | 560M | 512 | 다국어 강력, 짧은 문서 최적 |
| `snunlp/KR-ELECTRA-discriminator` | 110M | 512 | 한국어 특화, 경량·빠름 |

**벤치마크 평가셋 구성 (50개)**:

v2 문서에서 직접 추출한 질문-문서 쌍으로 구성한다.
LLM이 만든 HyDE 질문을 역으로 활용한다.

```python
# eval_set/embedding_bench.jsonl 예시
{"query": "다주택자 취득세 중과 기준이 어떻게 되나요?",
 "relevant_doc_id": "AllTax_GAGAM_20240915_xxx",
 "category": "세금"}

{"query": "DSR 2단계 적용 시 대출 한도 계산 방법",
 "relevant_doc_id": "weolbu_official_20241103_xxx",
 "category": "대출"}

{"query": "전세사기 예방 체크리스트",
 "relevant_doc_id": "alicehuh_20241220_xxx",
 "category": "임대차"}
```

**평가 지표**:

| 지표 | 설명 | 목표 |
|---|---|---|
| Recall@5 | 상위 5개 결과에 정답 포함 비율 | 70%+ |
| Recall@10 | 상위 10개 결과에 정답 포함 비율 | 85%+ |
| MRR | Mean Reciprocal Rank | 0.5+ |
| 배치 처리 속도 | 1,000 문서 임베딩 시간 | GPU: 5분↓ |

**예상 결과**:
`bge-m3`가 긴 v2 문서(원자 사실 다수)와 한국어 조합에서 우세할 것으로 예상.
벤치마크 결과가 예상과 다를 경우 `multilingual-e5-large`를 채택.

---

## 3. Week 2: Qdrant 색인 파이프라인 구축

### 3-1. 컬렉션 스키마 설계

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance,
    SparseVectorParams, Modifier
)

client = QdrantClient("localhost", port=6333)

client.create_collection(
    collection_name="realestate_v2",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(modifier=Modifier.IDF),
    },
)
```

**페이로드 스키마 (메타데이터 필드)**:

| 필드 | 타입 | 용도 |
|---|---|---|
| `doc_id` | keyword | 원본 문서 고유 식별자 (dedup 기준) |
| `chunk_id` | keyword | 청크 고유 ID |
| `chunk_type` | keyword | `"summary"` / `"atomic_fact"` / `"hyde"` |
| `channel` | keyword | 유튜브 채널명 (필터용) |
| `upload_date` | datetime | 업로드 날짜 (날짜 범위 필터용) |
| `topic_tags` | keyword[] | 주제 태그 (대출/세금/임대차 등) |
| `region_tags` | keyword[] | 언급 지역 태그 |
| `asset_type` | keyword[] | 자산 유형 (아파트/토지/경매 등) |
| `reliability_score` | integer | 채널 신뢰도 (1~4) |
| `text` | text | 청크 원문 (답변 생성용) |

### 3-2. 청킹 전략

v2 문서 1개 → **3종 청크**로 분리:

```
v2 문서 (1개)
├── [summary 청크] 문서 핵심 요지 전체 (~300~500토큰)
│   → 문서 전체 맥락 파악용
│
├── [atomic_fact 청크] 각 Atomic Fact 1개 (~50~100토큰)
│   → 정밀 사실 검색용
│   → v2 문서당 평균 10~20개 예상
│
└── [hyde 청크] HyDE 질문 + 연관 Atomic Fact 묶음 (~150~200토큰)
    → 쿼리-문서 임베딩 정렬 강화용
    → v2 문서당 평균 5~10개 예상
```

**예상 총 청크 수**: 5,000문서 × 평균 20청크 = **100,000개**
Qdrant 무료 클라우드(1M 벡터)로도 충분히 커버 가능.

### 3-3. 배치 색인 스크립트

```python
# scripts/index_all.py 핵심 로직

async def index_directory(v2_dir: Path, batch_size: int = 32):
    """
    rag_refined/ 디렉토리의 v2 YAML 파일을 읽어 Qdrant에 색인.
    - 이미 색인된 doc_id는 스킵 (증분 인덱싱)
    - 임베딩은 GPU 배치 처리
    - 오류 발생 시 해당 파일 스킵 + 로그 기록
    """
    already_indexed = get_indexed_doc_ids()  # Qdrant 조회

    for yaml_file in v2_dir.glob("*.yaml"):
        doc = parse_v2_yaml(yaml_file)
        if doc.id in already_indexed:
            continue

        chunks = create_chunks(doc)          # 3종 청크 생성
        embeddings = embed_batch(chunks)     # 배치 임베딩
        upsert_to_qdrant(chunks, embeddings) # 색인
```

**색인 속도 목표**:
- GPU 서버: 5,000문서 1~2시간 이내
- CPU only: 5,000문서 4~6시간 (하룻밤 배치 가능)

---

## 4. Week 3: 검색 + LLM 연동

### 4-1. 하이브리드 검색 구현

```python
# retriever/hybrid.py

async def hybrid_search(
    query: str,
    filters: dict | None = None,
    top_k: int = 15,
    alpha: float = 0.4,   # BM25 비중. 1-alpha = 벡터 비중
) -> list[SearchResult]:
    """
    1. 쿼리를 dense 벡터 + sparse 벡터로 동시 변환
    2. Qdrant query API로 하이브리드 검색 실행
    3. 메타데이터 필터 적용 (날짜/지역/주제)
    4. RRF (Reciprocal Rank Fusion)로 점수 결합
    5. 상위 top_k 반환
    """
```

**메타데이터 필터 자동 생성**:

질문 텍스트에서 LLM이 필터 조건을 추출한다.

```python
# 예: "최근 취득세 중과 기준은?" → 자동 필터 생성
filters = {
    "must": [
        {"key": "topic_tags", "match": {"any": ["세금/취득세"]}},
        {"key": "upload_date", "range": {"gte": "2023-01-01"}},  # 최신 우선
    ]
}
```

**α 초기값 및 튜닝 계획**:

| α 값 | BM25 비중 | 벡터 비중 | 적합한 케이스 |
|---|---|---|---|
| 0.2 | 20% | 80% | 의미 기반 질문 ("투자 가치가 있을까?") |
| **0.4** | **40%** | **60%** | **기본값 (시작점)** |
| 0.6 | 60% | 40% | 고유명사 검색 ("DSR 2단계", "규제지역") |

평가셋 결과 보고 최적값 결정.

### 4-2. 리랭킹 (선택 적용)

**채택 여부 기준**: 하이브리드 검색 Recall@5 < 70% 이면 적용.

```python
# retriever/reranker.py
# 모델: BAAI/bge-reranker-v2-m3 (한국어 강함)

def rerank(query: str, candidates: list[SearchResult]) -> list[SearchResult]:
    """
    Cross-encoder로 (query, document) 쌍 점수 재계산.
    상위 15개 → 재정렬 → 상위 10개 반환.
    추가 지연: 1~2초 (GPU), 5~8초 (CPU)
    """
```

### 4-3. Claude API 연동 + 프롬프트 설계

**시스템 프롬프트 원칙**:

```
- 역할: 대한민국 부동산 전문 AI 어드바이저
- 반드시 제공된 [컨텍스트] 문서 내용에 근거해서만 답변
- 숫자·정책 수치는 반드시 출처 명시 (채널명 + 날짜)
- 컨텍스트에 없는 내용은 "제공된 자료에서 확인되지 않음"으로 표시
- 세금·대출 수치는 참고용임을 고지 ("정확한 수치는 전문가 확인 필요")
- 최신 정책은 변경 가능성 언급
```

**RAG 사용자 프롬프트 템플릿**:

```
[참고 문서]
{% for doc in context_docs %}
문서 {{ loop.index }} (채널: {{ doc.channel }}, 날짜: {{ doc.date }}):
{{ doc.text }}
{% endfor %}

[질문]
{{ user_query }}

[답변 지침]
위 문서들을 근거로 답변하세요.
각 주장 뒤에 (출처: 채널명, YYYY-MM) 형식으로 인용하세요.
```

### 4-4. 기본 CLI 인터페이스 (MVP)

Phase 1 MVP는 웹 UI 없이 Python 대화형 CLI:

```
$ python -m src.chat

> 질문: 2024년 이후 다주택자 취득세 중과 기준이 어떻게 되나요?

[검색] 관련 문서 15개 발견 (0.3초)
[생성] 답변 작성 중...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2024년 현재 다주택자 취득세는 조정대상지역 여부와
주택 수에 따라 차등 적용됩니다...

[근거 출처]
1. AllTax_GAGAM (2024-09-15) — "취득세 중과율 개편..."
2. weolbu_official (2024-11-03) — "다주택자 취득세..."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
응답 시간: 4.2초

> 질문:
```

---

## 5. Week 4: 평가셋 구축 + 품질 측정

### 5-1. 평가셋 100개 구성

카테고리별로 균형 있게 구성한다:

| 카테고리 | 수량 | 예시 질문 |
|---|---|---|
| 세금 (취득/양도/보유) | 25개 | "다주택자 양도세 중과 한시 배제 기간?" |
| 대출 (LTV/DSR) | 20개 | "무주택자 생애최초 LTV 한도는?" |
| 임대차 | 20개 | "계약갱신청구권 행사 조건은?" |
| 경매/공매 | 15개 | "선순위 임차인 있을 때 낙찰 후 처리?" |
| 정책/규제 | 20개 | "규제지역 해제 기준과 현황은?" |

**평가셋 생성 방법**:

1. v2 문서에서 topic_tags 기반으로 카테고리별 샘플링
2. 해당 문서의 HyDE 질문 활용 (이미 생성되어 있음)
3. 정답 doc_id 수동 확인 (10~20%)
4. 나머지는 LLM이 자동 판정 (관련성 여부)

### 5-2. 자동 평가 파이프라인

```python
# eval/evaluator.py

def run_evaluation(eval_set_path: Path) -> EvalReport:
    results = []
    for item in load_eval_set(eval_set_path):
        # 1. 검색 품질 측정
        retrieved = hybrid_search(item["query"], top_k=10)
        recall_5 = item["relevant_doc_id"] in [r.doc_id for r in retrieved[:5]]
        mrr = compute_mrr(item["relevant_doc_id"], retrieved)

        # 2. 답변 품질 측정 (LLM 자동 채점)
        answer = rag_chain.run(item["query"])
        quality_score = judge_answer_quality(
            query=item["query"],
            answer=answer,
            expected_doc=item.get("expected_answer")
        )  # 0~5점: 사실성, 관련성, 출처 인용 여부

        # 3. 속도 측정
        results.append({**item, "recall_5": recall_5, "mrr": mrr,
                        "quality": quality_score, "latency": ...})

    return EvalReport(results)
```

### 5-3. 목표 지표

| 지표 | 목표 | 비고 |
|---|---|---|
| Recall@5 | 75%+ | 5개 결과 안에 관련 문서 포함 |
| Recall@10 | 87%+ | 10개 결과 안에 관련 문서 포함 |
| MRR | 0.55+ | 평균 역순위 |
| 답변 품질 (LLM 채점) | 3.5/5.0+ | 사실성 + 관련성 + 출처 인용 |
| 응답 시간 | 10초 이내 | 검색 + LLM 생성 합산 |

### 5-4. 실패 케이스 분류 및 후속 대응

평가 후 실패 케이스를 4가지로 분류해 우선순위를 정한다:

| 실패 유형 | 증상 | 대응 방안 |
|---|---|---|
| **검색 실패** | 관련 문서가 DB에 있는데 못 찾음 | α 조정, 청크 방식 변경, 리랭킹 적용 |
| **데이터 부재** | 해당 주제 문서 자체가 없음 | v2 생성 시 해당 카테고리 우선 처리 |
| **LLM 오류** | 문서는 찾았으나 답변이 잘못됨 | 프롬프트 수정, 컨텍스트 수 조정 |
| **환각** | 문서에 없는 수치를 생성 | 시스템 프롬프트 강화, temperature 낮춤 |

---

## 6. 핵심 기술 결정 체크리스트

Phase 1 진행 중 반드시 결정해야 할 사항들:

| 결정 사항 | 선택지 | 권장 시작값 | 결정 시점 |
|---|---|---|---|
| 임베딩 모델 | bge-m3 / e5-large / KR-ELECTRA | bge-m3 | Week 1 벤치마크 후 |
| 청크 레벨 | 문서 단위 / 원자사실 / 혼합 | 혼합 3종 | Week 2 |
| 리랭킹 사용 여부 | bge-reranker / 없음 | 없음으로 시작 | Week 4 평가 후 |
| α 값 (BM25 비중) | 0.2 ~ 0.6 | 0.4 | Week 4 튜닝 |
| 오케스트레이션 | LangGraph / LlamaIndex / 직접 구현 | 직접 구현 (단순하게) | Week 3 |
| 컨텍스트 청크 수 | 5 / 10 / 15개 | 10개 | Week 4 튜닝 |
| Qdrant 위치 | 로컬 Docker / Qdrant Cloud | 로컬 Docker | Week 2 |

---

## 7. Phase 1 완료 기준 (체크리스트)

- [ ] Qdrant에 5,000개 이상 문서 색인 완료
- [ ] 하이브리드 검색 (BM25 + 벡터) 정상 동작
- [ ] Claude API 연동 + RAG 출처 인용 답변 생성 동작
- [ ] 평가셋 100개 구축 완료
- [ ] Recall@5 **75%** 이상 달성
- [ ] 응답 시간 **10초** 이내
- [ ] CLI로 실제 부동산 질문 대화 가능

---

## 8. Phase 1 → Phase 2 전환 조건

Phase 2 (실거래 DB + 공간 분석)로 넘어가기 전 아래 조건을 모두 확인한다:

1. **RAG 검색 품질 안정**: Recall@5 75%+ 달성
2. **환각 비율 허용 수준**: LLM 채점 기준 오류 답변 < 15%
3. **데이터 볼륨**: v2 문서 10,000개 이상 확보
4. **인프라 준비**: 국토부 실거래가 API 키 발급 완료
5. **병목 파악**: 현재 답변에서 "데이터 없음"으로 실패하는 질문 유형 목록 정리
   → Phase 2에서 공공 API로 보완할 우선순위 결정에 활용

---

## 부록: 주간 체크포인트 요약

| 주차 | 완료 기준 |
|---|---|
| **Week 1** | 임베딩 모델 선정 완료, Recall@5 벤치마크 결과 표 작성 |
| **Week 2** | Qdrant 컬렉션 생성, 5,000문서 색인 완료, 색인 속도 확인 |
| **Week 3** | 하이브리드 검색 동작, CLI에서 질문-답변 루프 실행 가능 |
| **Week 4** | 평가셋 100개 구축, 목표 지표 달성 여부 확인, 실패 케이스 분석 |
