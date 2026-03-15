# Phase 1: RAG MVP 상세 기획서

> 진입 시점: v2 정제 문서 5,000개 확보 직후
> 기간: 2~4주
> 목표: 출처 인용 포함 부동산 Q&A가 가능한 동작하는 RAG 프로토타입 완성

---

## 0. 진입 시점 상태 및 전제 조건

| 항목 | 상태 |
|---|---|
| v2 정제 문서 | **6,968개 확보** (목표 5,000 초과 달성) |
| v2 계속 생성 | 백그라운드에서 병행 진행 (목표 20,000개) |
| 임베딩 모델 | **KURE-v1 선정 완료** (568M, 1024차원, 8192토큰) |
| 벡터 DB | **Qdrant v1.17.0 Docker 구축 완료** |
| 색인 파이프라인 | **구현 + 테스트 완료** (25문서 290청크 검증) |
| 평가 기준 | 없음 → Week 4에 수립 |

!!! note "병행 작업"
    v2 데이터 생성(Phase 0)은 Phase 1과 동시에 계속 진행한다.
    색인 파이프라인은 증분 삽입을 지원하므로, 문서가 늘어날수록 검색 품질이 자동으로 향상된다.

---

## 1. 프로젝트 구조 (코드베이스 설계)

### 1-1. 현재 구현된 구조

```
rag/
├── docker/
│   └── docker-compose.yml      # ✅ Qdrant + KURE-v1 임베딩 컨테이너
├── codes/
│   └── embedding/              # ✅ 색인 파이프라인 (구현 완료)
│       ├── chunker.py          # v2 YAML → 3종 청크 분리
│       ├── embedder.py         # KURE-v1 GPU 배치 임베딩
│       ├── upserter.py         # Qdrant 컬렉션 생성 + upsert
│       └── index_all.py        # 전체 색인 오케스트레이터
├── rag_v2/                     # v2 정제 문서 (6,968개)
├── qdrant_storage/             # Qdrant 벡터 데이터 영구 저장
└── planning/                   # 기획 문서
```

### 1-2. 추후 구현 예정 구조

```
rag/
├── codes/
│   ├── embedding/              # (구현 완료)
│   ├── retriever/              # 검색 엔진 (Week 3)
│   │   ├── hybrid.py           # BM25 + 벡터 하이브리드
│   │   ├── reranker.py         # Cross-encoder 리랭킹
│   │   └── filter.py           # 메타데이터 필터 생성
│   ├── llm/                    # LLM 연동 (Week 3)
│   │   ├── client.py           # Claude API 클라이언트
│   │   ├── prompts.py          # 프롬프트 템플릿
│   │   └── rag_chain.py        # 검색 → 생성 파이프라인
│   └── eval/                   # 평가 (Week 4)
│       ├── evaluator.py        # 자동 평가 실행
│       └── metrics.py          # Recall@K, MRR, 속도
├── eval_set/                   # 평가셋 (100개 Q&A 쌍)
└── tests/
```

---

## 2. Week 1: 환경 구성 + 임베딩 모델 선정 ✅ 완료

### 2-1. 개발 환경 구성 — Docker Compose

Qdrant(벡터 DB)와 KURE-v1 임베딩 컨테이너를 Docker Compose로 한 번에 실행한다.

**파일 위치**: `rag/docker/docker-compose.yml`

```yaml
services:
  qdrant:                          # 벡터 데이터베이스
    image: qdrant/qdrant:v1.17.0   # ARM64 공식 지원, 경량 ~100MB
    container_name: rag-qdrant
    ports: ["6333:6333", "6334:6334"]
    volumes:
      - /home/gon/ws/rag/qdrant_storage:/qdrant/storage:z

  embedding:                       # 임베딩 모델 실행 환경
    image: nvcr.io/nvidia/pytorch:25.11-py3   # DGX Spark CUDA 13 호환
    container_name: rag-embedding
    ipc: host
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    volumes:
      - /home/gon/ws/models:/models:ro         # KURE-v1 모델
      - /home/gon/ws/rag:/workspace            # 코드 + 데이터
    depends_on:
      qdrant:
        condition: service_healthy
```

**실행 방법**:

```bash
cd ~/ws/rag/docker
docker compose up -d          # Qdrant + Embedding 컨테이너 실행

# 상태 확인
curl http://localhost:6333    # Qdrant 버전 확인
docker logs rag-embedding     # pip 설치 완료 대기
```

> 자세한 설정 및 DGX Spark 호환성 조사 결과:
> [Qdrant 컨테이너 설정 가이드](../settings/qdrant_container_setup.md),
> [KURE-v1 임베딩 컨테이너 가이드](../settings/embedding_container_setup.md)

### 2-2. 임베딩 모델 선정 결과

DGX Spark(aarch64, CUDA 13) 호환성과 한국어 부동산 도메인 특성을 종합 고려하여 **KURE-v1**을 채택하였다.

| 항목 | 값 |
|---|---|
| 모델 | `nlpai-lab/KURE-v1` |
| 파라미터 | 568M |
| 임베딩 차원 | 1,024 |
| 최대 토큰 | 8,192 |
| VRAM 사용 | ~3~4GB (FP16) |
| 로컬 경로 | `/home/gon/ws/models/KURE-v1` |

**채택 이유**:

- 한국어 검색 벤치마크(Ko-StrategyQA 등)에서 최상위권 성능
- 8,192 토큰 지원 → v2 문서의 긴 요약/원자사실도 손실 없이 임베딩
- NGC PyTorch 컨테이너(25.11)에서 sentence-transformers로 바로 실행 가능
- DGX Spark GB10에서 배치 64 기준 ~14 chunks/sec 처리량 확인

!!! note "Dense 전용 모델"
    KURE-v1은 Dense 임베딩만 생성한다. Sparse(BM25) 검색은 Qdrant의
    내장 BM25(SparseVectorParams + IDF modifier)를 활용하여 별도 구성한다.

---

## 3. Week 2: Qdrant 색인 파이프라인 구축 ✅ 완료

### 3-1. 컬렉션 스키마 설계

`upserter.py`의 `ensure_collection()` 함수가 자동으로 컬렉션을 생성한다.

```python
# rag/codes/embedding/upserter.py — ensure_collection()

client.create_collection(
    collection_name="realestate_v2",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(modifier=Modifier.IDF),  # 내장 BM25
    },
)

# 페이로드 인덱스 8개 자동 생성 (필터 검색 최적화)
for field, schema in [("doc_id", KEYWORD), ("chunk_type", KEYWORD), ...]:
    client.create_payload_index(collection_name, field, schema)
```

**페이로드 스키마 (메타데이터 필드)**:

| 필드 | 타입 | 용도 |
|---|---|---|
| `doc_id` | keyword | 원본 문서 고유 식별자 (증분 인덱싱 기준) |
| `chunk_id` | keyword | 청크 고유 ID (UUID v5, 결정론적) |
| `chunk_type` | keyword | `"summary"` / `"atomic_fact"` / `"hyde"` |
| `channel` | keyword | 유튜브 채널명 (필터용) |
| `upload_date` | keyword | 업로드 날짜 (필터용, "YYYY-MM-DD") |
| `topic_tags` | keyword[] | 주제 태그 (대출/세금/임대차 등) |
| `region_tags` | keyword[] | 언급 지역 태그 |
| `asset_type` | keyword[] | 자산 유형 (아파트/토지/경매 등) |
| `reliability_score` | integer | 채널 신뢰도 (1~4) |
| `source_url` | (비인덱스) | 원본 YouTube URL |
| `text` | (비인덱스) | 청크 원문 (답변 생성용) |

### 3-2. 청킹 전략

`chunker.py`가 v2 YAML 문서 1개를 **3종 청크**로 분리한다.

```
v2 문서 (.md, YAML frontmatter + 마크다운 본문)
│
├── [summary 청크] "핵심 요지" 섹션 전체 + 문서 제목
│   → 문서 전체 맥락 파악용 (~300~500토큰)
│   → 문서당 1개
│
├── [atomic_fact 청크] "원자 사실" 섹션에서 "- Fact: " 프리픽스 추출
│   → 정밀 사실 검색용 (~50~100토큰)
│   → 문서당 평균 8~10개
│
└── [hyde 청크] "예상 검색 질문 (HyDE)" 섹션에서 "- Q: " 프리픽스 추출
    → 쿼리-문서 임베딩 정렬 강화용 (~50~150토큰)
    → 문서당 평균 3~5개
```

**실측 총 청크 수** (100개 샘플 기반 추정):

| 항목 | 값 |
|---|---|
| v2 문서 수 | 6,968개 |
| 문서당 평균 청크 | 13.2개 |
| **전체 예상 청크** | **~92,000개** |
| 예상 Qdrant 메모리 | ~800MB ~ 1GB (128GB 통합 메모리 중 1% 미만) |

### 3-3. 색인 파이프라인 상세

전체 색인 과정은 4개 모듈이 순차적으로 협력한다:

```
┌─────────────────────────────────────────────────────────────────┐
│  index_all.py (오케스트레이터)                                    │
│                                                                 │
│  1. Qdrant 연결 + 컬렉션 생성 ─────────── upserter.py           │
│     └─ Dense 1024D + Sparse BM25 + 페이로드 인덱스 8개           │
│                                                                 │
│  2. 이미 색인된 doc_id 조회 ───────────── upserter.py           │
│     └─ Qdrant scroll API → set[doc_id]                         │
│     └─ 기존 색인 문서는 자동 스킵 (증분 인덱싱)                    │
│                                                                 │
│  3. v2 파일 순회 (6,968개 .md)                                   │
│     │                                                           │
│     │  ┌── chunker.py ──────────────────────────────────┐       │
│     ├─▶│  YAML frontmatter 파싱 → V2Metadata            │       │
│     │  │  마크다운 본문 → H2 섹션 분리                     │       │
│     │  │  3종 청크 생성 (summary, atomic_fact, hyde)      │       │
│     │  └─────────────────────────────────────────────────┘       │
│     │                                                           │
│     │  ┌── embedder.py ─────────────────────────────────┐       │
│     ├─▶│  KURE-v1 모델 로드 (싱글톤, GPU)                │       │
│     │  │  텍스트 → 1024차원 벡터 (L2 정규화)              │       │
│     │  │  배치 처리: batch_size=64                        │       │
│     │  └─────────────────────────────────────────────────┘       │
│     │                                                           │
│     │  ┌── upserter.py ─────────────────────────────────┐       │
│     └─▶│  PointStruct 생성 (UUID id + 벡터 + 페이로드)   │       │
│        │  Qdrant upsert (배치 100개씩)                    │       │
│        └─────────────────────────────────────────────────┘       │
│                                                                 │
│  4. 결과 통계 출력 (처리 문서/청크 수, 소요 시간, 오류 목록)       │
└─────────────────────────────────────────────────────────────────┘
```

### 3-4. 실행 방법

**전체 색인 (전체 6,968 문서)**:

```bash
# 1. 컨테이너가 실행 중인지 확인
cd ~/ws/rag/docker
docker compose up -d

# 2. 전체 색인 실행 (embedding 컨테이너 내부에서)
docker exec rag-embedding python3 \
  /workspace/codes/embedding/index_all.py
```

**증분 색인 (새 문서만 추가)**:

```bash
# 동일 명령어 재실행 — 이미 색인된 doc_id는 자동 스킵
docker exec rag-embedding python3 \
  /workspace/codes/embedding/index_all.py
```

**디버깅/테스트용 (일부 문서만)**:

```bash
# 처음 50개 문서만 색인
docker exec rag-embedding python3 \
  /workspace/codes/embedding/index_all.py --limit 50

# 강제 재색인 (기존 데이터 무시)
docker exec rag-embedding python3 \
  /workspace/codes/embedding/index_all.py --force --limit 100
```

**주요 옵션**:

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--v2-dir` | `/workspace/rag_v2` | v2 문서 디렉토리 |
| `--qdrant-url` | `http://qdrant:6333` | Qdrant 서버 URL |
| `--model-path` | `/models/KURE-v1` | 임베딩 모델 경로 |
| `--batch-size` | `64` | GPU 배치 크기 |
| `--embed-batch` | `500` | 임베딩 버퍼 크기 (메모리 관리) |
| `--limit` | `0` (전체) | 최대 문서 수 (디버깅용) |
| `--force` | `false` | 기존 색인 무시 재색인 |

### 3-5. 검증된 성능 수치

25개 문서(290 청크) 색인 테스트 결과:

| 지표 | 값 |
|---|---|
| 모델 로딩 | ~14초 (최초 1회) |
| 임베딩 처리량 | ~14.2 chunks/sec (GPU) |
| 문서당 평균 | 0.83초 (모델 로딩 포함 시) |
| Qdrant upsert | 배치 100개, <0.1초/배치 |
| **전체 6,968문서 예상** | **~20~30분** |

### 3-6. 색인 결과 확인

```bash
# Qdrant 컬렉션 상태 확인 (호스트에서)
curl -s http://localhost:6333/collections/realestate_v2 | python3 -m json.tool

# 벡터 검색 테스트 (embedding 컨테이너 내부)
docker exec rag-embedding python3 -c "
from codes.embedding.embedder import embed_texts
from codes.embedding.upserter import get_client, COLLECTION_NAME

client = get_client('http://qdrant:6333')
q_vec = embed_texts(['다주택자 취득세 중과 기준은?'], show_progress=False).embeddings[0]
hits = client.query_points(COLLECTION_NAME, query=q_vec.tolist(), using='dense', limit=5,
                           with_payload=['chunk_type','channel','text'])
for h in hits.points:
    print(f'[{h.score:.4f}] [{h.payload[\"chunk_type\"]}] {h.payload[\"text\"][:80]}...')
"
```

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

| 결정 사항 | 선택지 | 결정 결과 | 상태 |
|---|---|---|---|
| 임베딩 모델 | bge-m3 / e5-large / KURE-v1 | **KURE-v1** (한국어 최적, 1024D, 8192토큰) | ✅ 결정 |
| 벡터 DB | Qdrant / Milvus / Weaviate | **Qdrant v1.17.0** (Docker, ARM64 공식 지원) | ✅ 결정 |
| 청크 레벨 | 문서 단위 / 원자사실 / 혼합 | **혼합 3종** (summary + atomic_fact + hyde) | ✅ 결정 |
| 컨테이너 구성 | 개별 Docker / Compose | **Docker Compose** (Qdrant + Embedding 통합) | ✅ 결정 |
| Qdrant 위치 | 로컬 Docker / Qdrant Cloud | **로컬 Docker** (DGX Spark NVMe) | ✅ 결정 |
| 리랭킹 사용 여부 | bge-reranker / 없음 | 없음으로 시작 | Week 4 평가 후 |
| α 값 (BM25 비중) | 0.2 ~ 0.6 | 0.4 | Week 4 튜닝 |
| 오케스트레이션 | LangGraph / LlamaIndex / 직접 구현 | 직접 구현 (단순하게) | Week 3 |
| 컨텍스트 청크 수 | 5 / 10 / 15개 | 10개 | Week 4 튜닝 |

---

## 7. Phase 1 완료 기준 (체크리스트)

- [x] 임베딩 모델 선정 완료 (KURE-v1)
- [x] Qdrant 벡터 DB Docker 구축 완료 (v1.17.0)
- [x] 색인 파이프라인 구현 완료 (chunker + embedder + upserter + index_all)
- [x] 증분 인덱싱 동작 확인
- [x] 벡터 검색 동작 확인 (25문서 290청크 테스트)
- [ ] Qdrant에 6,968개 전체 문서 색인 완료 (~92,000 청크)
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

| 주차 | 완료 기준 | 상태 |
|---|---|---|
| **Week 1** | 임베딩 모델 선정 (KURE-v1), Docker Compose 환경 구축 | ✅ 완료 |
| **Week 2** | 색인 파이프라인 구현, 6,968문서 전체 색인 실행 | 🔄 진행 중 |
| **Week 3** | 하이브리드 검색 구현, CLI에서 질문-답변 루프 실행 가능 | 미착수 |
| **Week 4** | 평가셋 100개 구축, 목표 지표 달성 여부 확인, 실패 케이스 분석 | 미착수 |
