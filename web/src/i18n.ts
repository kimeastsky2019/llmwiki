import { createContext, useContext } from "react";

export type Lang = "ko" | "en";

export const LANGS: Lang[] = ["ko", "en"];

// 규제 준수 화면은 영어로 통일한다. 판정 라벨·사유가 서버에서 영어로 오는데
// 화면 문구만 한국어면 한 줄 안에서 두 언어가 섞여 오히려 읽기 어렵다.
// 그래서 ko/en 양쪽이 같은 이 묶음을 본다.
const REG = {
    regLink: "Open compliance assessment →",
    regTitle: "Evidence-based compliance assessment",
    regLede:
      "The LLM fills the graph; rules on the graph do the judging. No LLM runs behind this screen — the same graph always yields the same verdicts.",
    regTabAssess: "Verdicts",
    regTabCoverage: "Coverage gap",
    regTabChanges: "Change approval",
    regTabGraph: "Graph",
    regEmpty: "The regulatory graph is empty.",
    regEmptyHint: "Run llmwiki reg seed on the server to load the demo data.",

    regStatDecided: "Auto-decided",
    regStatDeferred: "Deferred",
    regStatAuto: "Automation rate",
    regStatPrecision: "Goldset precision",
    regColService: "Service",
    regColControl: "Control",
    regColVerdict: "Verdict",
    regColRaw: "Rule result",
    regColBasis: "Basis",
    regColSign: "Sign-off",
    regDeferReason: "Deferral triggers",
    regProvisional: "provisional",
    regConfirmed: "confirmed",
    regConfirmBtn: "Sign off",
    regSigner: "Signing officer",
    regSignerHint: "The agent_id that confirms the verdict. It is recorded in the graph.",
    regDetailEvidence: "Evidence the verdict relied on",
    regDetailVersions: "The four versions needed to reproduce this verdict",
    regNoEvidence: "No accepted evidence.",
    regCommit: "Record verdicts in the graph",
    regCommitted: "Recorded {n} verdicts.",
    regNoAssessment: "No control applies.",

    regCoverageLede:
      "Regulatory obligations with no control attached. The graph produces this directly — it could not be counted before.",
    regUncovered: "Obligations with no control",
    regPartial: "Partially covered obligations",
    regNoEvidenceControls: "Controls with no required evidence",
    regManual: "Manual controls (automation candidates)",
    regColLevel: "Force",
    regColObligation: "Obligation",
    regColProvision: "Provision",
    regColMapping: "Mapping",
    regNoGap: "Nothing here.",

    regChangesLede:
      "Knowledge and criteria changes are reviewed like code. Until approved they do not affect any verdict.",
    regColId: "Change",
    regColGrade: "Grade",
    regColStatus: "Status",
    regColProposer: "Proposer",
    regColImpact: "Impact (controls/verdicts/services)",
    regBreaking: "breaking",
    regApprover: "Approval level",
    regGateCheck: "Machine check",
    regGateIssues: "What gate 1 caught",
    regDiffAdded: "added",
    regDiffChanged: "changed",
    regDiffObsoleted: "obsoleted",
    regApprove: "Approve (merge)",
    regReject: "Reject",
    regReviewNote: "Review note",
    regNoChanges: "No change proposals.",
    regBlockedHint:
      "Blocked by the machine check. It never reaches a reviewer, so it cannot be approved.",

    regGraphLede: "The approved graph. Proposals are not mixed in here.",
    regNodeCounts: "Nodes",
    regJournalSeq: "Journal records",
    regEdges: "Active edges",
    regPending: "Awaiting approval",
    regValidateOk: "Schema and the three constitutions hold",
    regValidateFail: "{n} violation(s)",
    regGoldsetTitle: "Goldset regression",
    regGoldsetLede:
      "Precision (of what it decided, how much was right) and coverage (how much it decided at all) are reported separately. A deferral is not a wrong answer.",
    regCoverageRate: "Coverage",
    regPrecisionRate: "Precision",
    regKappa: "Cohen κ",
    regGoldsetMiss: "Wrong",
} as const;

const STRINGS = {
  ko: {
    ...REG,
    brandSub: "프로그램 {programs} · 문서 {documents} · 테이블 {tables}",
    searchPlaceholder: "계좌, TB_CUST, CustomerMapper …",
    noPrograms: "분석된 프로그램이 없습니다.",
    noResults: "검색 결과가 없습니다.",
    tablesLink: "테이블 목록 보기 →",
    sourceLink: "소스 브라우저 열기 →",
    loading: "불러오는 중…",
    homeLede:
      "운영 소스에서 자동 추출한 프로그램 명세서입니다. 배포 파이프라인에서 재생성되므로 항상 운영계와 같은 상태를 유지합니다.",
    statPrograms: "프로그램",
    statDocuments: "생성된 문서",
    statClasses: "클래스",
    statStatements: "SQL 문",
    statTables: "테이블",
    missingDocs: "산출물이 아직 생성되지 않은 프로그램 {count}건이 있습니다 —",
    missingDocsCmd: "를 실행하세요.",
    programsHeading: "프로그램",
    excelDownload: "Excel 내려받기",
    analyzedSources: "분석 대상 소스",
    openInBrowser: "소스 브라우저에서 열기",
    tablesTitle: "테이블",
    tablesLede: "테이블별 CRUD 와 이를 사용하는 프로그램입니다.",
    colTable: "테이블",
    colUsedBy: "사용 프로그램",
    crumbTable: "테이블",
    affectedPrograms: "영향받는 프로그램",
    sqlUsingTable: "이 테이블을 쓰는 SQL",
    sourceBrowser: "소스 브라우저",
    filterFiles: "파일 경로 검색…",
    findInFile: "파일 내 검색…",
    noFiles: "파일이 없습니다.",
    noMatch: "일치하는 파일이 없습니다.",
    pickFile: "왼쪽에서 파일을 선택하세요.",
    close: "닫기",
    copyPath: "경로 복사",
    copied: "복사됨",
    lines: "{n}줄",
    matches: "{n}건",
    prevMatch: "이전",
    nextMatch: "다음",
    parsedBadge: "분석됨",
    highlightOff: "파일이 커서 구문 강조를 껐습니다.",
    projects: "프로젝트",
    openFolder: "＋ 소스 추가",
    openFolderTitle: "로컬 폴더 열기",
    addProjectTitle: "분석할 소스 추가",
    tabUpload: "내 컴퓨터에서 업로드",
    tabServer: "서버 폴더에서 선택",
    uploadHint:
      "분석할 소스 폴더나 ZIP 을 올리세요. 하위 폴더까지 훑어 Java · MyBatis XML · Python 을 찾습니다. node_modules · target · .git 같은 폴더와 소스가 아닌 파일은 올리기 전에 걸러집니다.",
    uploadDrop: "여기에 폴더나 ZIP 을 끌어다 놓으세요",
    uploadPickFolder: "폴더 선택",
    uploadPickZip: "ZIP 선택",
    uploadSelected: "선택됨",
    uploadFileCount: "파일 {n}개",
    uploadZipFile: "ZIP: {name}",
    uploadName: "프로젝트 이름",
    uploadStart: "업로드하고 분석",
    uploading: "업로드 중…",
    uploadCancel: "취소",
    uploadNothing:
      "분석할 수 있는 소스 파일이 없습니다. 폴더에 .java · .xml · .py 등이 있는지 확인하세요.",
    uploadSkipped: "{n}개 파일은 저장하지 않았습니다",
    pickFolderHint:
      "서버에 이미 올라와 있는 폴더를 고릅니다. 하위 폴더까지 훑어 Java · MyBatis XML 을 찾습니다.",
    pathPlaceholder: "경로 직접 입력 (예: /Users/me/workspace/loan)",
    goPath: "이동",
    upFolder: "상위 폴더",
    analyzeThis: "이 폴더 분석",
    emptyFolder: "하위 폴더가 없습니다.",
    countHint: "Java {java} · XML {xml}",
    countHintCapped: "Java {java}+ · XML {xml}+",
    noSourcesHere: "이 폴더에서 Java/XML 을 찾지 못했습니다. 그래도 분석할 수 있습니다.",
    parsing: "분석 중…",
    parseFailed: "분석 실패",
    reparse: "다시 분석",
    removeProject: "목록에서 제거",
    removeConfirm: "'{name}' 을 목록에서 제거할까요? 원본 소스는 그대로 두고 생성된 산출물만 지웁니다.",
    builtinTag: "config.yaml",
    notParsed: "아직 분석되지 않았습니다.",
    parsedAt: "분석 {when}",
    missingRoot: "폴더를 찾을 수 없습니다",
    programsCount: "프로그램 {n}",
    generateDoc: "명세서 생성",
    regenerate: "재생성",
    generating: "생성 중…",
    generateFailed: "생성 실패",
    noDocYet: "이 프로그램의 명세서는 아직 생성되지 않았습니다.",
    noDocHint:
      "아래는 정적 분석으로 확인된 사실입니다. LLM 서술까지 채우려면 명세서를 생성하세요.",
    providerNote: "공급자: {provider}",
    provider_grok: "Grok (외부 API)",
    provider_ollama: "사내 LLM (서버 GPU)",
    provider_claude: "Claude (외부 API)",
    provider_template: "LLM 없음 (구조만)",
    providerUnavailable: "사용 불가",
    providerLocalNote: "소스가 서버 밖으로 나가지 않습니다",
    providerCloudNote: "소스가 외부 API 로 전송됩니다",
    entryClass: "진입 클래스",
    sqlCount: "SQL {n}건",
    emptyProject: "분석된 프로그램이 없습니다. 좌측에서 폴더를 불러오세요.",
    noProgramsFound: "Java 클래스 {classes}개는 찾았지만 프로그램 단위를 만들지 못했습니다.",
    noProgramsHint:
      "LLMWiki 는 Spring MVC 의 @Controller / @Service 를 프로그램 단위로 잡습니다. 이 폴더에는 해당하는 클래스가 없습니다. 상위 폴더를 고르거나 다른 폴더를 불러와 보세요.",
    notParsedYet: "이 프로젝트는 아직 분석되지 않았습니다.",
    runParse: "지금 분석하기",
    shortcuts: "바로가기",
    recent: "최근",
    filterHere: "이 폴더에서 찾기…",
    noMatchHere: "일치하는 하위 폴더가 없습니다.",
    keyHint: "↑↓ 이동 · Enter 들어가기 · Backspace 상위 · Esc 닫기",
    folderTree: "폴더",
    projectLikely: "프로젝트로 보입니다",
    noJavaTitle: "이 폴더에서 Java 소스를 찾지 못했습니다.",
    noJavaScanned: "파일 {files}개를 살펴봤습니다. 가장 많은 확장자:",
    noJavaScope:
      "LLMWiki 는 Java(Spring MVC) + MyBatis Mapper XML 만 분석합니다. JSP·Struts·EJB 와 Java 가 아닌 언어는 아직 다루지 않습니다.",
    noJavaSkipped: "건너뛴 폴더: {dirs}",
    noJavaNext: "소스가 상위/하위 폴더에 있다면 그 폴더로 다시 열어 보세요.",
    scanSummary: "클래스 {classes} · SQL {statements} · 테이블 {tables}",
    providerNotReady: "LLM 공급자를 쓸 수 없습니다",
    howToFix: "해결 방법",
  },
  en: {
    ...REG,
    brandSub: "{programs} programs · {documents} docs · {tables} tables",
    searchPlaceholder: "account, TB_CUST, CustomerMapper …",
    noPrograms: "No programs have been analyzed.",
    noResults: "No results.",
    tablesLink: "Browse tables →",
    sourceLink: "Open source browser →",
    loading: "Loading…",
    homeLede:
      "Program specifications extracted automatically from the production source. They are regenerated by the deployment pipeline, so they always match what is running.",
    statPrograms: "Programs",
    statDocuments: "Documents",
    statClasses: "Classes",
    statStatements: "SQL statements",
    statTables: "Tables",
    missingDocs: "{count} program(s) have no generated document yet —",
    missingDocsCmd: "to create them.",
    programsHeading: "Programs",
    excelDownload: "Download Excel",
    analyzedSources: "Analyzed sources",
    openInBrowser: "Open in source browser",
    tablesTitle: "Tables",
    tablesLede: "CRUD per table and the programs that use it.",
    colTable: "Table",
    colUsedBy: "Programs",
    crumbTable: "TABLE",
    affectedPrograms: "Affected programs",
    sqlUsingTable: "SQL statements using this table",
    sourceBrowser: "Source browser",
    filterFiles: "Filter file paths…",
    findInFile: "Find in file…",
    noFiles: "No files.",
    noMatch: "No matching file.",
    pickFile: "Select a file on the left.",
    close: "Close",
    copyPath: "Copy path",
    copied: "Copied",
    lines: "{n} lines",
    matches: "{n} hits",
    prevMatch: "Prev",
    nextMatch: "Next",
    parsedBadge: "parsed",
    highlightOff: "Syntax highlighting is off for this large file.",
    projects: "Projects",
    openFolder: "＋ Add source",
    openFolderTitle: "Open local folder",
    addProjectTitle: "Add source to analyze",
    tabUpload: "Upload from my computer",
    tabServer: "Pick a folder on the server",
    uploadHint:
      "Upload the source folder or a ZIP. Subfolders are scanned for Java, MyBatis XML and Python. Folders like node_modules, target and .git — and non-source files — are filtered out before upload.",
    uploadDrop: "Drop a folder or ZIP here",
    uploadPickFolder: "Choose folder",
    uploadPickZip: "Choose ZIP",
    uploadSelected: "Selected",
    uploadFileCount: "{n} files",
    uploadZipFile: "ZIP: {name}",
    uploadName: "Project name",
    uploadStart: "Upload and analyze",
    uploading: "Uploading…",
    uploadCancel: "Cancel",
    uploadNothing:
      "No analyzable source files. Check that the folder contains .java, .xml or .py files.",
    uploadSkipped: "{n} files were not stored",
    pickFolderHint:
      "Pick a folder that is already on the server. Subfolders are scanned for Java and MyBatis XML.",
    pathPlaceholder: "Type a path (e.g. /Users/me/workspace/loan)",
    goPath: "Go",
    upFolder: "Parent folder",
    analyzeThis: "Analyze this folder",
    emptyFolder: "No subfolders.",
    countHint: "Java {java} · XML {xml}",
    countHintCapped: "Java {java}+ · XML {xml}+",
    noSourcesHere: "No Java/XML found here. You can still analyze it.",
    parsing: "Analyzing…",
    parseFailed: "Analysis failed",
    reparse: "Re-analyze",
    removeProject: "Remove from list",
    removeConfirm:
      "Remove '{name}' from the list? The original source is left untouched; only generated output is deleted.",
    builtinTag: "config.yaml",
    notParsed: "Not analyzed yet.",
    parsedAt: "Analyzed {when}",
    missingRoot: "Folder not found",
    programsCount: "{n} programs",
    generateDoc: "Generate spec",
    regenerate: "Regenerate",
    generating: "Generating…",
    generateFailed: "Generation failed",
    noDocYet: "No specification has been generated for this program yet.",
    noDocHint:
      "Below are the facts confirmed by static analysis. Generate the spec to fill in the narrative.",
    providerNote: "Provider: {provider}",
    provider_grok: "Grok (external API)",
    provider_ollama: "On-prem LLM (server GPU)",
    provider_claude: "Claude (external API)",
    provider_template: "No LLM (structure only)",
    providerUnavailable: "unavailable",
    providerLocalNote: "Source never leaves the server",
    providerCloudNote: "Source is sent to an external API",
    entryClass: "Entry class",
    sqlCount: "{n} SQL statements",
    emptyProject: "No programs analyzed. Open a folder from the sidebar.",
    noProgramsFound: "Found {classes} Java classes, but no program units could be built.",
    noProgramsHint:
      "LLMWiki treats Spring MVC @Controller / @Service classes as program units, and this folder has none. Try a parent folder, or open a different one.",
    notParsedYet: "This project has not been analyzed yet.",
    runParse: "Analyze now",
    shortcuts: "Shortcuts",
    recent: "Recent",
    filterHere: "Filter this folder…",
    noMatchHere: "No matching subfolder.",
    keyHint: "↑↓ move · Enter open · Backspace up · Esc close",
    folderTree: "Folders",
    projectLikely: "Looks like a project",
    noJavaTitle: "No Java source was found in this folder.",
    noJavaScanned: "Scanned {files} files. Most common extensions:",
    noJavaScope:
      "LLMWiki analyzes Java (Spring MVC) + MyBatis Mapper XML only. JSP, Struts, EJB and non-Java languages are not covered yet.",
    noJavaSkipped: "Skipped folders: {dirs}",
    noJavaNext:
      "If the source lives in a parent or child folder, open that folder instead.",
    scanSummary: "{classes} classes · {statements} SQL · {tables} tables",
    providerNotReady: "The LLM provider is not usable",
    howToFix: "How to fix",
  },
} as const;

export type StringKey = keyof (typeof STRINGS)["ko"];

export function translate(
  lang: Lang,
  key: StringKey,
  vars?: Record<string, string | number>
): string {
  const text: string = STRINGS[lang][key] ?? STRINGS.ko[key] ?? key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole
  );
}

export interface LangValue {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: StringKey, vars?: Record<string, string | number>) => string;
}

export const LangContext = createContext<LangValue>({
  lang: "ko",
  setLang: () => {},
  t: (key, vars) => translate("ko", key, vars),
});

export function useLang(): LangValue {
  return useContext(LangContext);
}

const STORAGE_KEY = "llmwiki.lang";

export function readStoredLang(): Lang | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "ko" || v === "en" ? v : null;
  } catch {
    return null;
  }
}

export function storeLang(lang: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* 프라이빗 모드 등에서 실패해도 무시 — 세션 안에서는 동작한다 */
  }
}
