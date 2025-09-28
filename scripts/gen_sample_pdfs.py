from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
IMAGES_DIR = ROOT / "images"  # also used by image OCR ingest
GEN_IMG_DIR = IMAGES_DIR / "generated"
for p in (DATA_DIR, IMAGES_DIR, GEN_IMG_DIR):
    p.mkdir(parents=True, exist_ok=True)

def make_placeholder_image(text: str, out_path: Path, size=(1000, 600), bg=(235,240,250)):
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    # simple frame
    draw.rectangle([10,10,size[0]-10,size[1]-10], outline=(70,100,160), width=6)
    # title bar
    draw.rectangle([10,10,size[0]-10,90], fill=(70,100,160))
    # title text (ASCII safe)
    title = text[:40]
    draw.text((30, 30), title, fill=(255,255,255))
    # body markers
    for i in range(5):
        x0 = 60 + i*150
        draw.ellipse([x0, 180, x0+80, 260], outline=(120,160,220), width=4)
    img.save(out_path, format="PNG")

topics = [
    {
        "file": "IA_Overview_01.pdf",
        "title": "IA 개요 및 원칙",
        "bullets": [
            "IA는 정보 구조와 탐색 경험을 다룹니다.",
            "핵심 원칙: 명확성, 일관성, 확장성",
            "메타데이터와 네비게이션 체계 설계",
        ],
        "images": ["IA-Overview", "Navigation-Map"],
    },
    {
        "file": "IA_Guideline_02.pdf",
        "title": "IA 산출물 가이드라인",
        "bullets": [
            "목표/범위/가정/리스크/테스트 계획 포함",
            "표준 목차와 용어집 제공",
            "근거 자료의 출처 명시",
        ],
        "images": ["Template-Checklist", "IA-Diagram"],
    },
    {
        "file": "ESB_Design_03.pdf",
        "title": "ESB 연계 설계 개요",
        "bullets": [
            "OAuth2 CC, 재시도/큐 기반 복원력",
            "p95 300ms, 배치 허용",
            "감사 로그 보존 90일",
        ],
        "images": ["ESB-Flow", "Retry-Queue"],
    },
    {
        "file": "Payment_Guide_04.pdf",
        "title": "결제 인터페이스 가이드",
        "bullets": [
            "Idempotency-Key 필수",
            "표준 오류 코드/보안 마스킹",
            "SLA 99.9% 및 장애 알림",
        ],
        "images": ["Payment-Sequence", "Error-Catalog"],
    },
    {
        "file": "Search_RAG_05.pdf",
        "title": "검색 기반 RAG 아키텍처",
        "bullets": [
            "임베딩 + 하이브리드 검색",
            "프롬프트에 근거 스니펫 주입",
            "출처 표기 원칙",
        ],
        "images": ["RAG-Flow", "Index-Schema"],
    },
    {
        "file": "Security_06.pdf",
        "title": "보안 정책 요약",
        "bullets": [
            "민감정보 마스킹",
            "권한/감사 추적",
            "비정상 행위 탐지",
        ],
        "images": ["Masking-Policy", "Audit-Trail"],
    },
    {
        "file": "Observability_07.pdf",
        "title": "관측성(Obs) 구성",
        "bullets": [
            "로그/메트릭/트레이싱",
            "SLI/SLO 관리",
            "알림 및 대시보드",
        ],
        "images": ["Metrics-Dashboard", "Trace-Map"],
    },
    {
        "file": "Performance_08.pdf",
        "title": "성능 최적화 체크리스트",
        "bullets": [
            "캐싱/배치/비동기",
            "쿼리/인덱스 튜닝",
            "프로파일링 루틴",
        ],
        "images": ["Latency-Chart", "Cache-Layers"],
    },
    {
        "file": "Data_Quality_09.pdf",
        "title": "데이터 품질 관리",
        "bullets": [
            "정합성/중복/유효성",
            "스키마 버저닝",
            "데이터 린에이지",
        ],
        "images": ["DQ-Checklist", "Lineage-Graph"],
    },
    {
        "file": "Release_10.pdf",
        "title": "릴리스/변경관리",
        "bullets": [
            "릴리즈 노트 표준",
            "롤백 전략",
            "변경 승인 절차",
        ],
        "images": ["Release-Calendar", "Rollback-Plan"],
    },
]

def add_title_and_bullets(c: canvas.Canvas, title: str, bullets: list):
    w, h = A4
    y = h - 72
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, y, title)
    y -= 28
    c.setFont("Helvetica", 12)
    for line in bullets:
        c.drawString(72, y, f"- {line}")
        y -= 18
        if y < 120:
            c.showPage()
            y = h - 72
            c.setFont("Helvetica", 12)
    return y

def draw_image_block(c: canvas.Canvas, img_path: Path, caption: str, y: float):
    w, h = A4
    max_w = w - 144
    max_h = 300
    if y - (max_h + 60) < 72:
        c.showPage(); y = h - 72
    c.setFont("Helvetica-Oblique", 11)
    c.drawString(72, y, f"이미지: {caption}")
    y -= 16
    try:
        ir = ImageReader(str(img_path))
        c.drawImage(ir, 72, y - max_h, width=max_w, height=max_h, preserveAspectRatio=True, mask='auto')
    except Exception as e:
        c.setFont("Helvetica", 10)
        c.drawString(72, y-14, f"(이미지 로드 실패: {img_path.name} - {e})")
    y -= (max_h + 24)
    return y

def main():
    created = []
    for t in topics:
        # create placeholder images for this topic
        img_files = []
        for i, name in enumerate(t["images"], start=1):
            fpath = GEN_IMG_DIR / f"{t['file'].replace('.pdf','')}_{i:02d}.png"
            make_placeholder_image(f"{name}", fpath)
            img_files.append(fpath)

        # build PDF and embed images
        pdf_path = DATA_DIR / t["file"]
        c = canvas.Canvas(str(pdf_path), pagesize=A4)
        y = add_title_and_bullets(c, t["title"], t["bullets"])
        for cap, ip in zip(t["images"], img_files):
            y = draw_image_block(c, ip, cap, y)
        c.save()
        created.append(pdf_path)
        print(f"✅ created: {pdf_path}")

    print(f"\n🎉 Done. PDFs: {len(created)} | images saved under {GEN_IMG_DIR}")

if __name__ == "__main__":
    main()
