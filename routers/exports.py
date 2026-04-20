import base64
import io
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                 Table, TableStyle)
from sqlalchemy.orm import Session

import models
from database import get_db
from routers.auth import get_current_user

router = APIRouter()

STATUS_LABELS = {
    "wait":     "대기중",
    "loaded":   "상차완료",
    "departed": "출발",
    "done":     "완료",
    "cancel":   "취소",
}


# ── 엑셀 내보내기 ──────────────────────────────────────────────────────────────
@router.get("/excel")
def export_excel(
    status: Optional[str] = None,
    driver_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Delivery)
    if status:
        query = query.filter(models.Delivery.status == status)
    if driver_id:
        query = query.filter(models.Delivery.driver_id == driver_id)
    if date_from:
        query = query.filter(models.Delivery.scheduled_date >= date_from)
    if date_to:
        query = query.filter(models.Delivery.scheduled_date <= date_to)
    deliveries = query.order_by(
        models.Delivery.scheduled_date, models.Delivery.delivery_time
    ).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "배송 목록"

    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_wrap = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # 제목
    ws.merge_cells("A1:M1")
    ws["A1"] = "탱크로리 배송 내역"
    ws["A1"].font = Font(bold=True, size=15, color="1E3A5F")
    ws["A1"].alignment = center
    ws.row_dimensions[1].height = 34

    ws.merge_cells("A2:M2")
    ws["A2"] = f"출력일: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}"
    ws["A2"].font = Font(size=10, color="6B7280")
    ws["A2"].alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[2].height = 18

    # 헤더 (13열)
    headers = [
        "번호", "업체명", "목적지", "품목", "수량(Kg)",
        "기사명", "차량번호", "배송날짜", "배송시간",
        "상차완료", "출발", "완료시간", "상태", "특이사항",
    ]
    col_widths = [6, 16, 22, 20, 10, 10, 13, 13, 10, 10, 10, 10, 10, 26]

    # 열 수가 14개이므로 머지 셀 범위 조정
    ws.merge_cells("A1:N1")
    ws.merge_cells("A2:N2")

    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF", size=11)

    for col_idx, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=3, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin_border
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = w
    ws.row_dimensions[3].height = 22

    status_fills = {
        "wait":     PatternFill("solid", fgColor="FEF3C7"),
        "loaded":   PatternFill("solid", fgColor="EDE9FE"),
        "departed": PatternFill("solid", fgColor="DBEAFE"),
        "done":     PatternFill("solid", fgColor="DCFCE7"),
        "cancel":   PatternFill("solid", fgColor="FEE2E2"),
    }

    for row_idx, d in enumerate(deliveries, 4):
        row_values = [
            row_idx - 3,
            d.company,
            d.destination,
            d.item_name,
            d.quantity,
            d.driver_user.name if d.driver_user else "",
            d.vehicle_number or "",
            d.scheduled_date,
            d.delivery_time,
            d.loading_complete_time or "-",
            d.departure_time or "-",
            d.complete_time or "-",
            STATUS_LABELS.get(d.status, d.status),
            d.notes or "",
        ]
        status_fill = status_fills.get(d.status)
        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = left_wrap if col_idx == 15 else center
            cell.border = thin_border
            if col_idx == 14 and status_fill:
                cell.fill = status_fill
        ws.row_dimensions[row_idx].height = 18

    ws.freeze_panes = "A4"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"배송목록_{datetime.now().strftime('%Y%m%d')}.xlsx"
    encoded = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


# ── PDF 계근표 ─────────────────────────────────────────────────────────────────
@router.get("/pdf/{delivery_id}")
def export_pdf(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    d = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if not d:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "배송을 찾을 수 없습니다."})

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    # 제목
    story.append(Paragraph(
        "계   근   표",
        ParagraphStyle("title", parent=styles["Heading1"],
                       fontSize=22, textColor=colors.HexColor("#1E3A5F"),
                       spaceAfter=6, alignment=1, fontName="Helvetica-Bold"),
    ))
    story.append(Paragraph(
        f"배송번호: D{d.id:03d} &nbsp;&nbsp;|&nbsp;&nbsp; 출력일: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M')}",
        ParagraphStyle("sub", parent=styles["Normal"],
                       fontSize=10, textColor=colors.HexColor("#6B7280"),
                       spaceAfter=20, alignment=1),
    ))

    label_style = ParagraphStyle("lbl", parent=styles["Normal"],
                                  fontSize=10, fontName="Helvetica-Bold",
                                  textColor=colors.HexColor("#374151"))
    val_style = ParagraphStyle("val", parent=styles["Normal"],
                                fontSize=10, textColor=colors.HexColor("#1a202c"))

    def row(label, value):
        return [Paragraph(label, label_style), Paragraph(str(value or "-"), val_style)]

    info_data = [
        [Paragraph("항목", label_style), Paragraph("내용", label_style)],
        row("업체명", d.company),
        row("목적지", d.destination),
        row("품목", d.item_name),
        row("수량", f"{d.quantity:,} Kg"),
        row("담당 기사", d.driver_user.name if d.driver_user else "-"),
        row("차량 번호", d.vehicle_number),
        row("배송 일시", f"{d.scheduled_date} {d.delivery_time}"),
        row("상차 완료", d.loading_complete_time),
        row("출발", d.departure_time),
        row("완료 시간", d.complete_time),
        row("배송 상태", STATUS_LABELS.get(d.status, d.status)),
        row("특이사항", d.notes),
        row("완료 메모", d.complete_memo),
    ]

    info_table = Table(info_data, colWidths=[5 * cm, 12 * cm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0),  11),
        ("ALIGN",          (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("GRID",           (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
    ]))
    story.append(info_table)

    # 계근표 사진
    if d.photos:
        story.append(Spacer(1, 16))
        story.append(Paragraph(
            f"계근표 사진 ({len(d.photos)}장)",
            ParagraphStyle("ph_title", parent=styles["Heading2"],
                           fontSize=13, textColor=colors.HexColor("#1E3A5F"),
                           spaceBefore=10, spaceAfter=10, fontName="Helvetica-Bold"),
        ))
        for photo in d.photos:
            try:
                raw = photo.photo_data
                if "," in raw:
                    raw = raw.split(",", 1)[1]
                img_bytes = base64.b64decode(raw)
                img_buf = io.BytesIO(img_bytes)
                img = Image(img_buf, width=14 * cm, height=10 * cm)
                story.append(img)
                story.append(Spacer(1, 8))
            except Exception:
                pass

    # 서명란
    story.append(Spacer(1, 24))
    sig_data = [
        ["담당자 확인", "기사 서명", "관리자 확인"],
        ["\n\n\n\n", "\n\n\n\n", "\n\n\n\n"],
        ["(인)", "(인)", "(인)"],
    ]
    sig_table = Table(sig_data, colWidths=[5.7 * cm, 5.7 * cm, 5.6 * cm])
    sig_table.setStyle(TableStyle([
        ("GRID",           (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("ALIGN",          (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 10),
        ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#F3F4F6")),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(sig_table)

    doc.build(story)
    buf.seek(0)

    filename = f"계근표_D{d.id:03d}_{d.company}_{d.scheduled_date}.pdf"
    encoded = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
