/* ========================================================================
   Shortform Pulse — Output Layer V0 (HW6)
   Anthropic API를 직접 호출해 3가지 톤의 영상 대본 초안을 생성합니다.
   ======================================================================== */

/* ---------------------------------------------------------------
   1. 트렌딩 영상 데이터 (V0는 하드코딩)
   V1에서 규동님 백엔드 API 응답으로 교체될 부분
   --------------------------------------------------------------- */
const TRENDING = {
  title: "초간단 5분 양치 루틴, 이거 모르면 손해", // 영상 제목
  category: "오럴케어/생활",                       // 카테고리
  platform: "YouTube Shorts",                       // 플랫폼
  views: "1.2M",                                    // 조회수
  likes: "98K",                                     // 좋아요 수
  engagement: "8.2%",                               // 인게이지먼트율
  categoryAvg: "5.91%",                             // 카테고리 평균
  delta: "+39%"                                     // 평균 대비 차이
};

/* ---------------------------------------------------------------
   2. 3가지 톤 정의
   각 톤마다 별도로 API 호출 → 병렬로 실행해서 속도 확보
   --------------------------------------------------------------- */
const TONES = [
  {
    id: "info",
    label: "정보형",
    description: "사실, 데이터, 팁 중심으로 신뢰감 있게 전달. 차분한 어조."
  },
  {
    id: "story",
    label: "스토리형",
    description: "1인칭 경험담/감정에 기반한 내러티브. 공감대 형성."
  },
  {
    id: "hook",
    label: "후킹형",
    description: "강한 호기심 유발, 빠른 전개, 자극적인 도입. 이탈률 최소화."
  }
];

/* ---------------------------------------------------------------
   3. API 키 sessionStorage 관리
   페이지 새로고침 시 입력한 키를 자동 복구하기 위함.
   sessionStorage는 탭 닫으면 사라짐 → 보안상 적절.
   --------------------------------------------------------------- */
const KEY_STORAGE = "anthropic_api_key";          // 저장 키 이름
const apiKeyInput = document.getElementById("apiKey");

// 페이지 로드 시 sessionStorage에서 키 복구
const savedKey = sessionStorage.getItem(KEY_STORAGE);
if (savedKey) apiKeyInput.value = savedKey;

// 입력값이 바뀔 때마다 sessionStorage에 저장
apiKeyInput.addEventListener("input", (e) => {
  sessionStorage.setItem(KEY_STORAGE, e.target.value);
});

/* ---------------------------------------------------------------
   4. 시스템 프롬프트 빌더
   각 톤별로 트렌딩 데이터를 컨텍스트로 주입해서 시스템 메시지 생성
   --------------------------------------------------------------- */
function buildSystemPrompt(tone) {
  return `당신은 한국 숏폼 컨텐츠 마케팅 대본 전문가입니다.

[입력 데이터]
- 영상 제목: ${TRENDING.title}
- 카테고리: ${TRENDING.category}
- 플랫폼: ${TRENDING.platform}
- 조회수/좋아요: ${TRENDING.views} / ${TRENDING.likes}
- 인게이지먼트: ${TRENDING.engagement} (카테고리 평균 ${TRENDING.categoryAvg} 대비 ${TRENDING.delta})

[작성 톤]
"${tone.label}" 톤으로 작성하세요.
가이드: ${tone.description}

[출력 형식 — 반드시 준수]
다음 JSON 스키마로만 응답하세요. 마크다운 코드블록(\`\`\`) 금지, 설명 문장 금지, 순수 JSON만:
{
  "hook": "영상 첫 3초에 들어갈 임팩트 있는 한 문장 멘트",
  "body": ["본문 흐름 1단계", "본문 흐름 2단계", "본문 흐름 3단계"],
  "cta": "마지막 콜투액션 한 문장"
}

[제약]
- 60초 영상 분량 기준 (300~400자 내외)
- body 배열은 3~5개 단계로 구성
- 한국어로 작성
- JSON 외 다른 텍스트는 절대 포함하지 마세요`;
}

/* ---------------------------------------------------------------
   5. Anthropic API 직접 호출
   브라우저에서 직접 호출하므로 dangerous-direct-browser-access 헤더 필수
   --------------------------------------------------------------- */
async function callClaude(apiKey, tone) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": apiKey,                                  // 사용자 입력 키
      "anthropic-version": "2023-06-01",                    // API 버전 고정
      "anthropic-dangerous-direct-browser-access": "true",  // 브라우저 직접 호출 허용
      "content-type": "application/json"
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-5",                           // 사용할 모델
      max_tokens: 1024,                                     // 최대 출력 토큰
      system: buildSystemPrompt(tone),                      // 시스템 프롬프트 (컨텍스트 주입)
      messages: [
        {
          role: "user",
          content: `위 트렌딩 영상에 대한 "${tone.label}" 대본 초안을 JSON으로 생성해주세요.`
        }
      ]
    })
  });

  // 응답이 실패면 한국어 에러 메시지로 변환
  if (!res.ok) {
    let detail = "";
    try {
      const errBody = await res.json();
      detail = (errBody && errBody.error && errBody.error.message) ? errBody.error.message : "";
    } catch (_) { /* JSON 아니면 무시 */ }

    let msg = `[${tone.label}] API 오류 (${res.status})`;
    if (res.status === 401) msg += " — 키가 올바른지 확인해주세요.";
    else if (res.status === 429) msg += " — 요청 한도 초과. 잠시 후 다시 시도해주세요.";
    else if (res.status >= 500) msg += " — Anthropic 서버 문제. 잠시 후 재시도해주세요.";
    if (detail) msg += `\n${detail}`;
    throw new Error(msg);
  }

  // 정상 응답: content 배열에서 텍스트 추출
  const data = await res.json();
  return data.content[0].text;
}

/* ---------------------------------------------------------------
   6. JSON 파싱 헬퍼
   모델이 가끔 ```json ... ``` 으로 감싸서 주는 경우 대비해 정리 후 파싱
   --------------------------------------------------------------- */
function parseScript(text) {
  let cleaned = text.trim();
  // 시작 부분 ```json 또는 ``` 제거
  cleaned = cleaned.replace(/^```json\s*/i, "").replace(/^```\s*/, "");
  // 끝 부분 ``` 제거
  cleaned = cleaned.replace(/```\s*$/, "");
  return JSON.parse(cleaned.trim());
}

/* ---------------------------------------------------------------
   7. HTML 이스케이프 (XSS 방지)
   사용자/모델 출력을 innerHTML로 넣을 때 반드시 이스케이프
   --------------------------------------------------------------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  }[c]));
}

/* ---------------------------------------------------------------
   8. 생성된 대본 저장소
   복사 버튼 클릭 시 여기서 텍스트를 가져옴
   --------------------------------------------------------------- */
const generated = {}; // { info: {hook, body, cta}, story: {...}, hook: {...} }

/* ---------------------------------------------------------------
   9. 결과 카드 렌더링 (한 톤 분량)
   tone.id별로 해당 탭 컨테이너에 카드 3개 + 전체 복사 버튼 삽입
   --------------------------------------------------------------- */
function renderScript(toneId, script) {
  generated[toneId] = script; // 복사용 저장

  const container = document.querySelector(`[data-tab-content="${toneId}"]`);
  // body가 배열이 아닐 때를 대비
  const bodyArr = Array.isArray(script.body) ? script.body : [String(script.body)];

  // 카드 3장 + 전체 복사 버튼 한 번에 그리기
  container.innerHTML = `
    <!-- Hook 카드 -->
    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-3 shadow-sm">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Hook · 첫 3초</span>
        <button class="copy-btn text-xs px-2 py-1 border border-gray-200 rounded hover:bg-gray-100" data-tone="${toneId}" data-field="hook">복사</button>
      </div>
      <p class="text-sm leading-relaxed">${escapeHtml(script.hook || "")}</p>
    </div>

    <!-- 본문 카드 -->
    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-3 shadow-sm">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide">본문 · 단계별</span>
        <button class="copy-btn text-xs px-2 py-1 border border-gray-200 rounded hover:bg-gray-100" data-tone="${toneId}" data-field="body">복사</button>
      </div>
      <ol class="script-body-list list-decimal list-inside text-sm space-y-1 marker:text-gray-400">
        ${bodyArr.map(step => `<li>${escapeHtml(step)}</li>`).join("")}
      </ol>
    </div>

    <!-- CTA 카드 -->
    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-3 shadow-sm">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide">CTA · 콜투액션</span>
        <button class="copy-btn text-xs px-2 py-1 border border-gray-200 rounded hover:bg-gray-100" data-tone="${toneId}" data-field="cta">복사</button>
      </div>
      <p class="text-sm leading-relaxed">${escapeHtml(script.cta || "")}</p>
    </div>

    <!-- 전체 복사 버튼 -->
    <button class="copy-btn w-full mt-2 text-sm py-2 border border-gray-300 rounded-lg hover:bg-gray-100" data-tone="${toneId}" data-field="all">
      전체 복사
    </button>
  `;
}

/* ---------------------------------------------------------------
   10. 단일 톤 에러 렌더 (파싱 실패 등 부분 실패 시)
   --------------------------------------------------------------- */
function renderToneError(toneId, message) {
  const container = document.querySelector(`[data-tab-content="${toneId}"]`);
  container.innerHTML = `
    <div class="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 text-sm">
      <strong>이 톤은 생성에 실패했습니다.</strong><br />
      ${escapeHtml(message)}
    </div>
  `;
}

/* ---------------------------------------------------------------
   11. 전체 에러 박스 표시
   --------------------------------------------------------------- */
const errorBox = document.getElementById("errorBox");
function showError(msg) {
  errorBox.textContent = msg;
  errorBox.classList.remove("hidden");
}
function hideError() {
  errorBox.textContent = "";
  errorBox.classList.add("hidden");
}

/* ---------------------------------------------------------------
   12. 탭 전환
   --------------------------------------------------------------- */
function activateTab(id) {
  // 버튼 active 클래스 토글
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === id);
  });
  // 컨텐츠 영역 표시/숨김
  document.querySelectorAll(".tab-content").forEach((c) => {
    c.classList.toggle("hidden", c.dataset.tabContent !== id);
  });
}

// 탭 버튼 클릭 시 전환
document.querySelectorAll(".tab-btn").forEach((b) => {
  b.addEventListener("click", () => activateTab(b.dataset.tab));
});

/* ---------------------------------------------------------------
   13. 클립보드 복사 (이벤트 위임)
   동적으로 생성된 .copy-btn 모두 처리
   --------------------------------------------------------------- */
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".copy-btn");
  if (!btn) return;

  const toneId = btn.dataset.tone;
  const field = btn.dataset.field;
  const data = generated[toneId];
  if (!data) return;

  // field에 따라 복사할 텍스트 조립
  let text = "";
  if (field === "hook") text = data.hook || "";
  else if (field === "cta") text = data.cta || "";
  else if (field === "body") {
    const arr = Array.isArray(data.body) ? data.body : [String(data.body)];
    text = arr.map((s, i) => `${i + 1}. ${s}`).join("\n");
  } else if (field === "all") {
    const arr = Array.isArray(data.body) ? data.body : [String(data.body)];
    text =
      `[Hook]\n${data.hook}\n\n` +
      `[본문]\n${arr.map((s, i) => `${i + 1}. ${s}`).join("\n")}\n\n` +
      `[CTA]\n${data.cta}`;
  }

  // navigator.clipboard로 복사 시도
  try {
    await navigator.clipboard.writeText(text);
    const original = btn.textContent;
    btn.textContent = "복사됨!";
    setTimeout(() => { btn.textContent = original; }, 1500);
  } catch (_) {
    btn.textContent = "복사 실패";
    setTimeout(() => { btn.textContent = "복사"; }, 1500);
  }
});

/* ---------------------------------------------------------------
   14. 메인 액션: "대본 초안 생성" 버튼 클릭 핸들러
   --------------------------------------------------------------- */
const generateBtn = document.getElementById("generateBtn");
const resultsSection = document.getElementById("results");

generateBtn.addEventListener("click", async () => {
  hideError();

  // 키 입력 검증
  const key = apiKeyInput.value.trim();
  if (!key) {
    showError("API 키를 입력해주세요.");
    return;
  }
  if (!key.startsWith("sk-ant-")) {
    showError('API 키 형식이 올바르지 않습니다. "sk-ant-"로 시작해야 합니다.');
    return;
  }

  // 버튼 로딩 상태로 전환
  generateBtn.disabled = true;
  generateBtn.innerHTML = '<span class="spinner"></span>생성 중...';

  // 결과 영역 표시 + 각 탭에 로딩 메시지 임시로 채움
  resultsSection.classList.remove("hidden");
  TONES.forEach((t) => {
    const container = document.querySelector(`[data-tab-content="${t.id}"]`);
    container.innerHTML = `<p class="text-sm text-gray-400">${t.label} 대본 생성 중...</p>`;
  });
  activateTab("info");

  // 3톤 병렬 호출 (allSettled로 부분 실패 허용)
  const settled = await Promise.allSettled(TONES.map((t) => callClaude(key, t)));

  // 각 톤별 결과 처리
  let anySuccess = false;
  settled.forEach((result, i) => {
    const tone = TONES[i];
    if (result.status === "fulfilled") {
      try {
        const script = parseScript(result.value);
        renderScript(tone.id, script);
        anySuccess = true;
      } catch (err) {
        renderToneError(tone.id, "응답 파싱 실패: " + err.message);
      }
    } else {
      renderToneError(tone.id, result.reason.message);
    }
  });

  // 모두 실패면 상단 에러도 표시
  if (!anySuccess) {
    showError("모든 톤 생성에 실패했습니다. API 키와 네트워크를 확인해주세요.");
  }

  // 버튼 원상복구
  generateBtn.disabled = false;
  generateBtn.textContent = "대본 초안 생성";
});
