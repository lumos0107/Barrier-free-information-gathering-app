// 칸 정의의 원본. 화면과 내보내기, 저녁 검사가 이 정의를 따른다.
// 단계 종류: mark(표시값), num(숫자), signed(부호 있는 숫자), choice(버튼), text(글자)
// blank: 비울 수 있고 그 뜻을 적는다. 비운 칸은 null로 저장하고 0으로 쓰지 않는다.

const yesNo = [["yes", "있음"], ["no", "없음"]];
const markStep = { key: "mark", label: "표시값", type: "mark", unit: "m", decimals: 1 };
const markBlank = { ...markStep, blank: "표시값 없음" };
const endMark = { key: "mark_end", label: "끝 표시값", type: "mark", unit: "m", decimals: 1 };
const unreadable = "못 잼";
export const UNREADABLE = unreadable;
const TOOLS = [["level_ruler", "수평계와 철자"], ["caliper", "캘리퍼"], ["tape", "줄자"], ["eye", "철자 눈높이"]];

export const BARRIERS = {
  bump: {
    label: "턱", group: "value",
    steps: [
      markStep,
      { key: "value", label: "높이", type: "num", unit: "mm", decimals: 0, blank: unreadable, warn: (v, R) => (v != null && v < R.bump.record_mm ? `${R.bump.record_mm} mm 미만은 기록하지 않아도 됩니다` : v != null && v > R.range.bump_mm ? `${R.range.bump_mm} mm 넘음. 1번 더 읽어 주세요` : null) },
      { key: "reason", label: "못 잰 이유", type: "text", showIf: (a) => a.value == null },
      { key: "value2", label: "둘째 값(캘리퍼)", type: "num", unit: "mm", decimals: 0, blank: "바닥이 거칠어 안 잼", showIf: (a, R) => a.value != null && a.value >= R.bump.recheck_mm[0] && a.value <= R.bump.recheck_mm[1] },
      { key: "tool", label: "쓴 도구", type: "choice", options: TOOLS, auto: "level_ruler" },
      { key: "tool2", label: "둘째 값 도구", type: "choice", options: TOOLS, auto: "caliper", showIf: (a) => a.value2 != null },
      { key: "dir", label: "방향", type: "choice", options: [["up", "진행 쪽 높음"], ["down", "진행 쪽 낮음"]] },
      { key: "shape", label: "모양", type: "choice", options: [["square", "직각"], ["chamfer", "모서리 깎임"], ["smooth", "완만한 잇기"]] },
      { key: "run_mm", label: "가로 길이", type: "num", unit: "mm", decimals: 0, blank: unreadable, showIf: (a) => a.shape && a.shape !== "square" },
      { key: "remain_cm", label: "턱을 피해 이어지는 남은 폭", type: "num", unit: "cm", decimals: 0, blank: unreadable, quick: [["0", 0, "없음(0)"]], showIf: (a, R) => a.value != null && a.value >= R.bump.photo_mm },
      { key: "repeat", label: "1 m 안에 반복", type: "choice", options: [["no", "아님"], ["yes", "반복"]], auto: "no" },
      { key: "mark_end", label: "반복이 끝나는 표시값", type: "mark", unit: "m", decimals: 1, showIf: (a) => a.repeat === "yes" },
    ],
    photos: (a, R) => (a.value == null || a.value >= R.bump.photo_mm ? 2 : 0),
    shot: "도구 눈금 가까이 1장 + 길 방향 멀리 1장",
  },
  gap: {
    label: "틈", group: "value",
    steps: [
      markStep,
      { key: "value", label: "틈 너비", type: "num", unit: "mm", decimals: 0, blank: unreadable },
      { key: "reason", label: "못 잰 이유", type: "text", showIf: (a) => a.value == null },
      { key: "dir", label: "틈 방향", type: "choice", options: [["parallel", "진행 방향과 나란함"], ["cross", "직각"]] },
      { key: "remain_cm", label: "틈을 피해 이어지는 남은 폭", type: "num", unit: "cm", decimals: 0, blank: unreadable, quick: [["0", 0, "없음(0)"]] },
      { key: "reason_remain", label: "남은 폭을 못 잰 이유", type: "text", showIf: (a) => a.remain_cm == null },
      { key: "repeat", label: "같은 틈이 반복", type: "choice", options: [["no", "아님"], ["yes", "반복 (가장 넓은 곳을 적음)"]], auto: "no" },
      { key: "mark_end", label: "반복이 끝나는 표시값", type: "mark", unit: "m", decimals: 1, showIf: (a) => a.repeat === "yes" },
    ],
    photos: () => 1,
    shot: "틈이 보이게 1장",
  },
  width_rep: {
    label: "대표 폭", group: "value", autoSave: true,
    steps: [
      { ...markBlank, auto: "current" },
      { key: "value", label: "폭", type: "num", unit: "cm", decimals: 0, blank: unreadable, quick: [["over5", 500, "5 m 이상"]], warn: (v, R) => (v != null && (v < R.range.width_cm[0] || v > R.range.width_cm[1]) ? "범위 밖입니다. 1번 더 읽어 주세요" : null) },
      { key: "value2", label: "105 cm 이하: 1번 더", type: "num", unit: "cm", decimals: 0, blank: unreadable, showIf: (a, R) => a.value != null && a.value <= R.width.recheck_cm },
      { key: "min_cm", label: "구간 전체가 1.5 m보다 좁으면 구간 최솟값", type: "num", unit: "cm", decimals: 0, blank: "해당 없음", showIf: (a, R) => a.value != null && a.value < R.width.narrow_cm },
    ],
    photos: () => 0,
  },
  narrow: {
    label: "좁은 곳", group: "value",
    steps: [
      markStep,
      { key: "value", label: "폭", type: "num", unit: "cm", decimals: 0, blank: unreadable },
      { key: "value2", label: "더 좁은 자리에서 1번 더", type: "num", unit: "cm", decimals: 0, blank: "더 좁은 자리 없음", showIf: (a, R) => a.value != null && a.value <= R.width.recheck_cm },
      { key: "over2m", label: "좁은 곳이 2 m 넘게 이어지나요", type: "choice", options: [["yes", "2 m 넘음"], ["no", "2 m 안 됨"]] },
    ],
    photos: () => 2,
    shot: "줄자 댄 모습 1장 + 멀리 1장",
  },
  steps: {
    label: "계단", group: "place",
    steps: [markStep, { key: "count", label: "계단 칸 수", type: "num", unit: "칸", decimals: 0, blank: "셀 수 없음" }],
    photos: () => 1,
    shot: "길 방향 멀리 1장",
  },
  broken: { label: "끊긴 길", group: "place", steps: [markStep], photos: () => 1, shot: "길 방향 멀리 1장" },
  dead_end: { label: "막다른 길", group: "place", steps: [markStep], photos: () => 1, shot: "길 방향 멀리 1장" },
  nogo: {
    label: "못 감 구간", group: "span",
    steps: [
      { ...markStep, label: "시작 표시값" }, endMark,
      { key: "side_line", label: "옆에 바퀴로 지나갈 줄", type: "choice", options: yesNo },
      { key: "reason", label: "못 가는 이유", type: "choice", options: [["stones", "돌이 움직임"], ["sink", "바퀴가 빠짐"], ["bumps", "턱이나 틈이 되풀이됨"], ["parallel", "나란한 틈이 이어짐"], ["other", "그 밖"]] },
    ],
    photos: () => 3,
    shot: "시작 1장, 끝 1장, 노면 가까이 철자 놓고 1장",
  },
  hazard: {
    label: "위험 지점", group: "span",
    steps: [
      { key: "hazard", label: "종류", type: "choice", options: [["ends_road", "내리막이 차도로 끝남"], ["ends_steps", "내리막이 계단으로 끝남"], ["ends_drop", "내리막이 낙차로 끝남"], ["drop", "길 옆 낙차"], ["shared", "차량과 함께 쓰는 길"]] },
      { ...markStep, label: "시작 표시값" }, { ...endMark, blank: "한 지점" },
      { key: "low_side", label: "낮은 쪽", type: "choice", options: [["left", "진행 왼쪽"], ["right", "진행 오른쪽"], ["flat", "기울지 않음"]], showIf: (a) => a.hazard === "drop" },
      { key: "guard", label: "난간이나 턱", type: "choice", options: [["rail", "난간 있음"], ["kerb", "턱 있음"], ["none", "없음"]], showIf: (a) => a.hazard === "drop" },
      { key: "leans", label: "그쪽으로 기우나요", type: "choice", options: [["yes", "기움"], ["no", "안 기움"]], showIf: (a) => a.hazard === "drop" && a.low_side !== "flat" },
    ],
    photos: () => 1,
  },
  temp_block: {
    label: "일시 막힘", group: "place",
    steps: [markStep, { key: "what", label: "무엇", type: "choice", options: [["works", "공사"], ["blocked", "임시 막힘"], ["parked", "주차 차량"]] }],
    photos: () => 1,
  },
  rest: {
    label: "쉬는 평지", group: "place",
    steps: [markStep, { key: "flat", label: "위쪽 끝에 평지", type: "choice", options: yesNo }],
    photos: () => 1,
  },
  passing: { label: "비켜설 곳", group: "place", steps: [markStep], photos: () => 1 },
  turn: {
    label: "회전 공간", group: "size",
    steps: [markStep, { key: "w_cm", label: "가로", type: "num", unit: "cm", decimals: 0, blank: unreadable }, { key: "d_cm", label: "세로", type: "num", unit: "cm", decimals: 0, blank: unreadable }],
    photos: () => 1,
  },
  driveway: {
    label: "차량 진출입부", group: "size",
    steps: [markStep, { key: "cross", label: "좌우 경사", type: "num", unit: "°", decimals: 1, blank: unreadable }, { key: "bump_mm", label: "턱", type: "num", unit: "mm", decimals: 0, blank: unreadable }],
    photos: () => 2,
    shot: "수평계 댄 모습 1장 + 멀리 1장",
  },
  puddle: { label: "물 고임", group: "place", steps: [markStep], photos: () => 1 },
  other: {
    label: "표에 없는 것", group: "place",
    steps: [markStep, { key: "memo", label: "무엇인지", type: "text", required: true }],
    photos: () => 1,
  },
};

export const MATERIALS = [["asphalt", "아스팔트"], ["concrete", "콘크리트"], ["block", "보도블록"], ["slab", "판석"], ["stone", "돌길"], ["gravel", "자갈"], ["songi", "송이"], ["soil", "흙"], ["grass", "잔디"], ["deck", "데크"], ["rubber", "고무·우레탄"], ["coir", "야자매트"], ["other", "기타"]];
export const GRADES = [["good", "매끈"], ["intermediate", "보통"], ["bad", "거침"], ["very_bad", "못 감"]];

export const SURFACE = {
  label: "노면",
  steps: [
    { ...markStep, auto: "current" },
    { key: "material", label: "재질", type: "choice", options: MATERIALS, grid: true },
    { key: "grade", label: "등급", type: "choice", options: GRADES },
    { key: "grade2", label: "합의가 안 되면 둘째 등급", type: "choice", options: [["", "합의함"], ...GRADES] },
    { key: "reason", label: "못 감 이유", type: "text", required: true, showIf: (a) => a.grade === "very_bad" },
  ],
  photos: (a) => (a.changed ? 1 : 0) + (a.grade2 ? 1 : 0),
  shot: "두 재질 경계에 철자를 놓고 1장. 둘째 등급을 적었으면 바닥 1장 더",
};

const dest = { key: "dest", label: "그 시설로 가는 곳", type: "choice", options: [["main", "본선"], ["door", "특정 출입구"], ["goal", "목적지"]] };
const facMark = { ...markBlank, auto: "current" };
const slopeNum = (key, label) => ({ key, label, type: "signed", unit: "°", decimals: 1, blank: unreadable });

export const FACILITIES = {
  toilet: {
    label: "화장실",
    steps: [
      facMark, dest,
      { key: "stall", label: "장애인 칸", type: "choice", options: yesNo },
      { key: "lock", label: "잠김", type: "choice", options: [["open", "열림"], ["ask", "요청하면 열림"], ["locked", "잠김"]], showIf: (a) => a.stall === "yes" },
      { key: "door_cm", label: "문 통과 폭 (기준 90)", type: "num", unit: "cm", decimals: 0, blank: unreadable, showIf: (a) => a.stall === "yes" },
      { key: "w_cm", label: "칸 안 폭", type: "num", unit: "cm", decimals: 0, blank: unreadable, showIf: (a) => a.stall === "yes" },
      { key: "d_cm", label: "칸 안 깊이", type: "num", unit: "cm", decimals: 0, blank: unreadable, showIf: (a) => a.stall === "yes" },
      { key: "side_cm", label: "변기 옆 빈 폭 (기준 75)", type: "num", unit: "cm", decimals: 0, blank: unreadable, showIf: (a) => a.stall === "yes" },
      { key: "bump_mm", label: "입구 턱", type: "num", unit: "mm", decimals: 0, blank: unreadable, showIf: (a) => a.stall === "yes" },
    ],
    photos: (a) => (a.stall === "yes" ? 3 : 1),
    shot: "정면 + 문 폭 재는 모습 + 칸 안 변기와 옆 공간",
  },
  entrance: {
    label: "출입구",
    steps: [
      facMark, dest,
      { key: "place", label: "시설", type: "choice", options: [["ticket", "매표소"], ["info", "안내소"], ["hall", "전시관"], ["food", "식당"], ["shop", "상점"], ["house", "전시 가옥"]], grid: true },
      { key: "door_cm", label: "문 통과 폭 (기준 90)", type: "num", unit: "cm", decimals: 0, blank: unreadable },
      { key: "sill_mm", label: "문턱", type: "num", unit: "mm", decimals: 0, blank: unreadable },
      { key: "door", label: "문 형태", type: "choice", options: [["swing", "여닫이"], ["slide", "미닫이"], ["auto", "자동문"], ["none", "문 없음"], ["other", "그 밖"]], grid: true },
    ],
    photos: () => 2,
    shot: "정면 1장 + 문 폭 재는 모습 1장",
  },
  ramp: {
    label: "경사로",
    steps: [
      facMark, dest,
      slopeNum("slope_low", "기울기 아래"), slopeNum("slope_mid", "기울기 가운데"), slopeNum("slope_top", "기울기 위"),
      { key: "w_cm", label: "폭 (기준 120)", type: "num", unit: "cm", decimals: 0, blank: unreadable },
      { key: "len_m", label: "길이", type: "num", unit: "m", decimals: 1, blank: unreadable },
    ],
    photos: () => 2,
    shot: "아래에서 올려다봄 1장 + 위에서 내려다봄 1장",
  },
  curb_ramp: {
    label: "연석경사로",
    steps: [
      facMark, dest,
      { key: "w_cm", label: "폭 (기준 90)", type: "num", unit: "cm", decimals: 0, blank: unreadable },
      slopeNum("slope", "기울기"),
      { key: "end_mm", label: "끝 턱", type: "num", unit: "mm", decimals: 0, blank: unreadable },
    ],
    photos: () => 2,
    shot: "차도 쪽(건너편 보도에서) 1장 + 보도 쪽 1장",
  },
  parking: {
    label: "장애인 주차",
    steps: [
      facMark,
      { key: "w_cm", label: "주차 폭 (기준 330)", type: "num", unit: "cm", decimals: 0, blank: unreadable },
      { key: "l_cm", label: "주차 길이 (기준 500)", type: "num", unit: "cm", decimals: 0, blank: unreadable },
      slopeNum("slope", "바닥 기울기"),
      { key: "path", label: "입구까지 가는 길", type: "text" },
    ],
    photos: () => 1,
  },
  bench: { label: "쉴 곳", steps: [facMark, { key: "many", label: "모여 있나요", type: "choice", options: [["no", "1개"], ["yes", "여러 개"]] }], photos: () => 0 },
  service: {
    label: "대여, 엘리베이터, 수유실, 운영 시간",
    steps: [
      facMark,
      { key: "what", label: "무엇", type: "choice", options: [["rental_wc", "휠체어 대여"], ["rental_st", "유모차 대여"], ["lift", "엘리베이터"], ["nursing", "수유실"], ["hours", "운영 시간"]], grid: true },
      { key: "exists", label: "있나요", type: "choice", options: yesNo },
      { key: "memo", label: "메모", type: "text" },
    ],
    photos: () => 1,
  },
};

export const MAP_CHECK = {
  label: "지도 표시 확인",
  steps: [
    { ...markBlank, auto: "current" },
    { key: "what", label: "표시 내용", type: "text", required: true },
    { key: "result", label: "현장 결과", type: "choice", options: [["right", "맞음"], ["wrong", "틀림"], ["unknown", "모름"]] },
  ],
  photos: () => 1,
};

export const BREAK_FORM = {
  label: "끊김",
  steps: [
    { key: "orig", label: "마지막 지점의 원래 표시값", type: "mark", unit: "m", decimals: 1 },
    { key: "now", label: "바퀴를 대고 읽은 지금 표시값", type: "mark", unit: "m", decimals: 1 },
  ],
  photos: () => 0,
};

export const CLEAR_NOTES = [["", "치운 것 없음"], ["gravel", "자갈"], ["sand", "모래"], ["leaves", "낙엽"]];
export const POINT_NOTE = {
  label: "이 지점 메모",
  steps: [
    { key: "clear", label: "치우기 전 상태", type: "choice", options: CLEAR_NOTES },
    { key: "memo", label: "메모", type: "text" },
  ],
  photos: () => 0,
};
export const BOUNDARY_NOTES = [["whole", "바퀴 줄 전체"], ["stone", "돌 하나"]];
export const RESULTS = [["ok", "길 맞음"], ["stopped", "끝까지 못 감"], ["temp_block", "일시 막힘"], ["no_entry", "출입 금지"], ["not_path", "길 아님"]];
export const WEATHER = [["sunny", "맑음"], ["cloudy", "흐림"], ["wet", "바닥 젖음"], ["rain", "비"]];
export const LINES = { main: "기본 줄", walk: "사람이 다니는 줄", gentle: "가장 완만한 줄" };
export const STATUS_LABEL = { open: "재는 중", done: "끝", partial: "일부", redo: "다시 잼", not_path: "길 아님", no_entry: "출입 금지", temp_block: "일시 막힘" };
export const POINT_KIND = { gap: "간격", fine: "1순위", end: "끝 앞", more: "더함" };
export const MISSING_LABEL = { slope: "경사", slope_points: "일부 경사 지점", width: "폭", surface: "노면", cross: "좌우 경사", barrier_value: "장벽 값", other: "그 밖" };

export function labelOf(options, value) {
  const o = options.find((x) => x[0] === value);
  return o ? o[1] : value;
}
