# Shortform Pulse — Output Layer V0 (HW6)

KAIST 수업 **HW6 개인 과제** 제출용 데모.
그룹 프로젝트 [trendingshorts](https://github.com/seu-seo/trendingshorts)의 마지막 마디로 통합되는 피처입니다.

라이브 데모: <https://kaist9558.github.io/hw6/>

---

## 컨셉

trendingshorts는 다음 4단계 파이프라인으로 동작합니다.

```
 [발견]  →  [분석]  →  [개인화]  →  [실행]
  규동       승연        지은         나
백엔드    카테고리     유저       대본 초안
트렌딩    분석/벤치   페르소나    생성
데이터    마크
```

이 데모(`hw6/`)는 마지막 **[실행]** 단계입니다.
트렌딩 영상 한 건을 입력으로 받아, 컨텐츠 마케팅용 60초 숏폼 대본 초안을
**3가지 톤**으로 동시에 생성합니다.

- **정보형** — 사실/데이터/팁 중심, 신뢰감 있는 어조
- **스토리형** — 1인칭 경험담/감정 기반 내러티브
- **후킹형** — 강한 호기심 유발, 빠른 전개

각 톤마다 `Hook (첫 3초) / 본문 (3~5단계) / CTA` 구조의 JSON으로 결과를 받아 렌더링합니다.

---

## 사용법

1. 라이브 데모 접속: <https://kaist9558.github.io/hw6/>
2. Anthropic API 키 발급: <https://console.anthropic.com>
3. 페이지에 키 입력 → **"대본 초안 생성"** 클릭
4. 3개 탭(정보형/스토리형/후킹형)에서 결과 비교 → 복사 버튼으로 활용

> **API 키 보안**
> 입력한 키는 브라우저 `sessionStorage`에만 저장되며 어디로도 전송되지 않습니다.
> 페이지를 닫거나 새로고침하면 사라집니다.
> 코드에 키가 하드코딩되어 있지 않으며, 호출은 사용자 브라우저에서 직접 Anthropic API로 향합니다.

---

## 로컬에서 확인하는 법

별도 빌드/서버 불필요합니다.

```
브라우저로 hw6/index.html 파일을 열기
```

또는 간단한 정적 서버를 띄워도 됩니다.

```bash
# 프로젝트 루트에서
python3 -m http.server 8000
# → http://localhost:8000/hw6/ 접속
```

---

## 파일 구조

```
hw6/
├── index.html    메인 데모 페이지 (UI 마크업, Tailwind CDN 로드)
├── style.css     스피너/탭 등 Tailwind로 처리 못 하는 커스텀 스타일
├── script.js     API 키 관리, Anthropic API 호출, 결과 렌더링, 복사 버튼
└── README.md     이 문서
```

---

## 기술 스택

- 단일 HTML + 분리된 JS/CSS (정적 파일만)
- **Tailwind CSS** (CDN: `https://cdn.tailwindcss.com`)
- **Anthropic API** — 클라이언트에서 `fetch`로 직접 호출
  - 모델: `claude-sonnet-4-5`
  - 헤더: `x-api-key`, `anthropic-version: 2023-06-01`, `anthropic-dangerous-direct-browser-access: true`
  - 응답: 시스템 프롬프트로 JSON 출력 강제 → 클라이언트에서 파싱
- 호스팅: **GitHub Pages** (서버 사이드 코드 없음)

---

## V0 한계

- 트렌딩 영상 데이터 1건 하드코딩 (오럴케어/생활 카테고리)
- 백엔드 API 미연결 — 규동님 데이터 파이프라인과 분리 동작
- 페르소나/타겟 유저 정보 미반영 — 지은님 개인화 로직과 분리
- 단일 카테고리 / 단일 플랫폼 (YouTube Shorts)
- 대본 평가/저장/공유 기능 없음
- 영상 길이 옵션 없음 (60초 고정)

---

## V1 계획

- [ ] **trendingshorts 백엔드 API 연결** — 실시간 트렌딩 데이터 사용
- [ ] **다중 카테고리/플랫폼 지원** — 사용자가 카테고리 선택 가능
- [ ] **지은님 페르소나 데이터 통합** — 타겟 유저별 톤 미세 조정
- [ ] **영상 길이 옵션** — 15초 / 30초 / 60초
- [ ] **대본 저장/공유** — 마음에 드는 대본을 즐겨찾기, 링크 공유
- [ ] **A/B 후크 비교** — 같은 대본에 후크만 여러 버전

---

## 시스템 프롬프트 설계 (참고)

각 톤마다 별도 호출하며, 시스템 프롬프트에 다음을 모두 주입합니다.

- 역할 정의: "한국 숏폼 컨텐츠 마케팅 대본 전문가"
- 입력 데이터: 영상 제목 / 카테고리 / 플랫폼 / 인게이지먼트 메타
- 출력 톤: 정보형 / 스토리형 / 후킹형 중 하나
- 출력 형식: `{hook, body[], cta}` JSON 스키마 강제
- 길이 제약: 60초 영상 (300~400자 내외), body는 3~5단계

자세한 프롬프트 빌더는 `script.js`의 `buildSystemPrompt()` 함수 참고.

---

## 라이선스 / 크레딧

- 본 데모는 KAIST 수업 HW6 과제 제출용으로 작성되었습니다.
- 그룹 프로젝트 컨텍스트: [seu-seo/trendingshorts](https://github.com/seu-seo/trendingshorts)
