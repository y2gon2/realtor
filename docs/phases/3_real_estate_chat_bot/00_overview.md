# Phase 3: 대한민국 부동산 RAG 챗봇

## 1. 배경 및 목적

Phase 1(RAG MVP)에서 11,035개 유튜브 문서를 가공/색인하고, Phase 2(도메인 온톨로지)에서 2,146개 전문 용어 + 25,670개 은어/별칭 + 법률 문서를 구축하여 P@3 68%의 검색 파이프라인을 완성했다.

그러나 **답변 생성 레이어가 미구현** 상태로, 검색 결과를 사용자에게 자연어로 전달하는 마지막 단계가 빠져있다. Phase 3에서는 기존 검색 인프라 위에 **간단한 대화형 챗봇**을 구축한다.

### 목표
1. 사용자 질문 → 검색 → LLM 답변 생성 → 출처 인용의 **전체 흐름 완성**
2. **멀티턴 대화**로 후속 질문 처리 (코레퍼런스 해소)
3. **스트리밍 응답**으로 체감 속도 개선
4. 모든 설정을 `params.yaml`로 외부화하여 튜닝 용이

---

## 2. 아키텍처 개요

```
┌──────────────────┐
│   Chainlit UI    │  한국어 채팅 인터페이스
│  (localhost:8000) │  스트리밍 + 인용 렌더링
└────────┬─────────┘
         │ WebSocket
┌────────▼─────────┐
│   ChatService    │  세션 관리 + 대화 컨텍스트 + 오케스트레이션
│  (chat_service)  │  코레퍼런스 해소 → 검색 → 평가 → 생성
└───┬──────────┬───┘
    │          │
┌───▼────┐ ┌──▼──────────┐
│  LLM   │ │SearchPipeline│  기존 Phase 1+2 코드 재사용
│(claude │ │(query/)      │  Qdrant 3개 컬렉션
│ code   │ │BGE-M3+CE+CRAG│  하이브리드 RRF 검색
│  CLI)  │ │              │
└────────┘ └──────────────┘
```

### 레이어 구성
- **Presentation**: Chainlit — 네이티브 스트리밍, 메시지 스레딩, 피드백 수집
- **Service**: ChatService — 멀티턴 대화 관리, 코레퍼런스 해소, Adaptive RAG 상태머신
- **Infrastructure**: 기존 SearchPipeline + Qdrant + BGE-M3 + Cross-Encoder (변경 없음)

---

## 3. 핵심 기술 결정

### 3.1 UI: Chainlit
| 비교 항목 | Chainlit | Streamlit | Gradio |
|-----------|----------|-----------|--------|
| 대화형 AI 특화 | 네이티브 | 부가 기능 | 부가 기능 |
| 스트리밍 | WebSocket 네이티브 | 폴링 기반 | 제한적 |
| 중간 단계 표시 | cl.Step 내장 | 수동 구현 | 미지원 |
| 사용자 피드백 | 내장 (thumbs up/down) | 수동 구현 | 미지원 |
| 대화 히스토리 | cl.user_session 내장 | 수동 구현 | 미지원 |
| 프로덕션 준비 | 인증 지원 | 제한적 | 데모용 |

**결정**: Chainlit — 대화형 AI 전용 프레임워크로 최소 코드로 최대 기능

### 3.2 LLM 호출: Claude Code CLI 유지
- 현재 `_call_claude_cli()` (subprocess) 그대로 사용
- `params.yaml`에 `llm.backend: "cli"` vs `"api"` 스위치 포함하여 향후 SDK 전환 용이
- 모델 라우팅도 params.yaml에서 관리

### 3.3 상태머신: Pure Python (LangGraph 제거)
- `graph.py`의 `_run_fallback()` (102-132행)이 이미 동일 로직을 완전 구현
- LangGraph 미설치 상태, 6노드 선형 그래프에 불필요한 의존성

### 3.4 대화 메모리: 슬라이딩 윈도우
- "간단 챗봇" 스코프에서 최근 5턴 유지면 충분
- 장기 벡터 메모리는 딥 리포트 단계에서 추가

### 3.5 인용 시스템
- 답변 생성 시 검색 결과 기반 [1], [2] 인용 표기
- 하단에 출처 섹션 렌더링
- 향후 Anthropic Citations API 전환 시 `params.yaml`의 `citations.mode` 변경으로 대응

---

## 4. 설정 외부화: params.yaml

모든 사용자 튜닝 가능 변수를 `codes/app/config/params.yaml`에 집중 관리:

```yaml
# LLM 설정
llm:
  backend: "cli"                          # "cli" (claude-code) 또는 "api" (anthropic SDK)
  cli:
    binary: "/usr/local/bin/claude-code"
    timeout: 180
    cooldown: 7
  api:
    model_generation: "claude-sonnet-4-6"
    model_classification: "claude-haiku-4-5-20251001"
    max_retries: 3
    retry_base_delay: 1.0

# 모델 라우팅
model_routing:
  query_classification: "sonnet"          # cli 모드에서 사용할 모델명
  document_grading: "sonnet"
  hallucination_check: "sonnet"
  query_rewriting: "sonnet"
  coreference_resolution: "sonnet"
  answer_generation: "sonnet"
  crag_evaluation: "sonnet"

# Chainlit 설정
app:
  host: "0.0.0.0"
  port: 8000
  title: "부동산 AI 어드바이저"
  welcome_message: "안녕하세요! 대한민국 부동산에 대해 무엇이든 물어보세요."

# 검색 설정
search:
  qdrant_url: "http://qdrant:6333"
  limit: 5
  rerank: true
  rerank_candidates: 20
  crag: true

# 대화 관리
conversation:
  max_turns: 5                            # 컨텍스트 윈도우 크기
  session_summary_after: 10               # 이 턴 이후 요약 압축
  coreference_markers:                    # 코레퍼런스 해소 트리거
    - "그거"
    - "이거"
    - "그건"
    - "그럼"
    - "거기"
    - "이건"
    - "그래서"
    - "그러면"
  min_query_length_for_resolution: 15     # 이 길이 미만 + 도메인 키워드 없으면 해소 시도

# 생성 설정
generation:
  max_retries: 2                          # 재검색 최대 횟수
  temperature: 0.0                        # 그라운딩을 위해 0
  citations:
    mode: "prompt"                        # "prompt" (프롬프트 기반) 또는 "api" (Citations API)
    max_per_answer: 5                     # 답변당 최대 인용 수
  disclaimer: "본 답변은 참고용이며 전문가 상담을 권장합니다."
```

---

## 5. Sprint 구성

### Sprint 1: 기반 구조 + params.yaml (2-3일)
- `codes/app/config/params.yaml` 생성
- `codes/app/config/__init__.py` — YAML 로더 (params 딕셔너리 제공)
- `codes/generation/state.py` — 멀티턴 필드 추가
- `codes/generation/graph.py` — LangGraph 코드 제거, fallback만 유지

### Sprint 2: 멀티턴 대화 관리 (2-3일)
- `codes/generation/conversation.py` — ConversationSession, ConversationTurn
- `codes/generation/coreference.py` — 한국어 코레퍼런스 해소
- `codes/generation/citation_formatter.py` — 검색 결과 → 인용 텍스트 변환

### Sprint 3: Chainlit UI + 오케스트레이션 (2-3일)
- `codes/app/__init__.py`
- `codes/app/chat_service.py` — ChatService 오케스트레이션
- `codes/app/chat.py` — Chainlit 메인 앱

### Sprint 4: Docker + 통합 테스트 (2-3일)
- `docker/docker-compose.yml` 업데이트
- 50개 골든 QA 쌍으로 생성 품질 평가
- 20개 멀티턴 시나리오 테스트

---

## 6. 파일 변경 요약

### 신규 생성
| 파일 | 역할 |
|------|------|
| `codes/app/config/params.yaml` | 모든 설정 외부화 |
| `codes/app/config/__init__.py` | YAML 로더 |
| `codes/app/__init__.py` | 앱 패키지 |
| `codes/app/chat.py` | Chainlit 메인 진입점 |
| `codes/app/chat_service.py` | 오케스트레이션 서비스 |
| `codes/generation/conversation.py` | 멀티턴 대화 관리자 |
| `codes/generation/coreference.py` | 한국어 코레퍼런스 해소 |
| `codes/generation/citation_formatter.py` | 인용 포매터 |

### 기존 수정
| 파일 | 변경 내용 |
|------|----------|
| `codes/generation/state.py` | 멀티턴 필드 추가 |
| `codes/generation/graph.py` | LangGraph 제거, fallback만 유지 |
| `codes/generation/gen_prompts.py` | GENERATE_SYSTEM_PROMPT 분리 |
| `docker/docker-compose.yml` | chatbot 서비스 추가 |

---

## 7. 미색인 문서 4,692개 처리

- Phase 3 **블로커 아님**: 기존 93,943 포인트 + 3,122 온톨로지/법률 포인트로 MVP 충분
- 기존 `codes/embedding/index_phase2_v2.py`로 백그라운드 증분 색인
- 챗봇 개발과 독립적으로 병행 가능

---

## 8. 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| BGE-M3/CE 모델이 챗봇과 같은 프로세스에서 GPU 필요 | 기존 `rag-embedding` 컨테이너에서 실행 |
| CLI subprocess 레이턴시 (~14초) | 현재 수용, params.yaml에서 `llm.backend: "api"` 전환 준비 |
| SearchPipeline 동기식 → async 이벤트루프 블로킹 | `run_in_executor()` 래핑 |
| 한국어 코레퍼런스 해소 실패 | 실패 시 원본 질의 그대로 사용 |

---

## 9. 참고 자료

- [Anthropic Citations API](https://docs.anthropic.com/en/docs/build-with-claude/citations)
- [Adaptive RAG with LangGraph](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/)
- [Agentic RAG Systems 2026 Guide](https://rahulkolekar.com/building-agentic-rag-systems-with-langgraph/)
- [Context Window Management for AI Agents](https://www.getmaxim.ai/articles/context-window-management-strategies-for-long-context-ai-agents-and-chatbots/)
- [Streamlit vs Gradio vs Chainlit Comparison](https://medium.com/@atnoforgenai/streamlit-vs-gradio-vs-chainlit-building-quick-uis-for-your-ai-applications-138e3baa5317)
- [RAGAS Evaluation Framework](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
- [LangChain RAG + 한국어 속성 감성 분석](https://www.koreascience.kr/article/JAKO202510157604017.page?lang=ko)
- [Multi-RAG + Multi-Region LLM 한국어 Chatbot (AWS)](https://aws.amazon.com/ko/blogs/tech/multi-rag-and-multi-region-llm-for-chatbot/)
- [RAG Chatbot Enterprise Docs 2026](https://www.docsie.io/blog/articles/rag-chatbot-enterprise-docs-2026/)
- [Reducing Hallucinations with Custom Intervention (AWS)](https://aws.amazon.com/blogs/machine-learning/reducing-hallucinations-in-large-language-models-with-custom-intervention-using-amazon-bedrock-agents/)

---

## 10. 총 일정: 8-12일

| Sprint | 기간 | 산출물 |
|--------|------|--------|
| Sprint 1: 기반 구조 | 2-3일 | params.yaml, state 확장, graph 정리 |
| Sprint 2: 멀티턴 | 2-3일 | 대화 관리자 + 코레퍼런스 + 인용 포매터 |
| Sprint 3: UI | 2-3일 | Chainlit + ChatService |
| Sprint 4: 통합 | 2-3일 | Docker, E2E 테스트, 프롬프트 튜닝 |
